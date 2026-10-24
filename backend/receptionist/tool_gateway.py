"""Strict administrative tool boundary used by the conversation state machine.

The caller supplies a server-created tenant context. Tool data cannot grant
identity proof, change tenant scope, run SQL, or select a network endpoint.
External tools persist an operation for an asynchronous worker instead of
holding the turn's database transaction while waiting for a provider.
"""
import os
import time

from fastapi import HTTPException
from pydantic import ValidationError

from .core import ReceptionService
from .models_core import ExternalCalendarOperation
from .security import Actor, fail, hash_phone


from .tool_contract import TOOL_NAMES, TOOLS, validate_model_tool_event, ModelToolEvent

# Preserve the prior public tool_gateway imports while keeping schemas pure.
__all__ = ["ToolGateway", "persist_tool_spans", "TOOL_NAMES", "TOOLS", "validate_model_tool_event", "ModelToolEvent"]


def persist_tool_spans(db, row, spans, *, turn_id=None, parent_id=None, attempt_id=None, rolled_back=False):
    """Persist closed metadata after the caller has resolved its transaction.

    Arguments, returned values and exception messages never enter a trace. A
    queued remote operation measures local dispatch, not remote completion.
    """
    from .ops_controls import append_trace
    prefix = "turn:" + turn_id if turn_id else "tool-attempt:" + attempt_id
    for index, span in enumerate(spans):
        attributes = {key: value for key, value in span.items() if key not in {"tool", "rolled_back"}}
        attributes["status"] = "rolled_back" if rolled_back or span.get("rolled_back") else "committed"
        append_trace(db, row.tenant_id, f"{prefix}:tool:{index}", "tool." + span["tool"],
            call_id=row.id, turn_id=turn_id, parent_id=parent_id,
            versions=row.policy_snapshot.get("versions", {}), attributes=attributes)


class ToolGateway:
    def __init__(self, db, row, context, *, spans=None):
        self.db, self.row, self.context = db, row, context
        self.spans = spans if spans is not None else []
        self.service = ReceptionService(db, row.tenant_id, "caller:" + row.id)
        self.actor = Actor("caller:" + row.id, row.tenant_id, "caller", "", "", "")

    def call(self, name, arguments):
        started = time.monotonic()
        span = {"tool": name if name in TOOL_NAMES else "invalid", "outcome": "failed", "error_code": "TOOL_FAILURE"}
        try:
            result = self._call(name, arguments, started)
            span = {"tool": span["tool"], "outcome": "queued" if isinstance(result, dict) and result.get("pending_tool") else "completed"}
            return result
        except HTTPException as exc:
            # Only fixed classifications are retained: arbitrary detail/code
            # strings may contain identifiers supplied by a caller or adapter.
            deadline = isinstance(exc.detail, dict) and exc.detail.get("code") == "TOOL_DEADLINE"
            span.update(outcome="deadline" if deadline else "rejected" if exc.status_code < 500 else "failed",
                error_code="TOOL_DEADLINE" if deadline else "TOOL_REJECTED" if exc.status_code < 500 else "TOOL_FAILURE",
                http_status=exc.status_code)
            raise
        finally:
            span["duration_ms"] = max(0, int((time.monotonic() - started) * 1000))
            self.spans.append(span)

    def _call(self, name, arguments, started):
        try:
            parsed = TOOLS.validate_python({"tool": name, "arguments": arguments})
        except ValidationError:
            fail(422, "INVALID_TOOL_ARGUMENTS", "ساختار درخواست اداری معتبر نیست.")
        values = parsed.arguments.model_dump()
        if name in {"book", "cancel", "reschedule"}:
            verified = self.context.get("verified_phone")
            phone = self.context.get("phone")
            if not phone or verified != hash_phone(phone) or name == "book" and verified != hash_phone(values["phone"]):
                fail(403, "VERIFICATION_REQUIRED", "هویت تماس‌گیرنده برای تغییر تقویم تایید نشده است.")
            if self.context.get("sms_enabled") and self.context.get("sms_subject") != verified:
                fail(403, "SMS_SUBJECT_MISMATCH", "تغییر شماره پیامک به تایید مستقل و تازه نیاز دارد.")
        from .calendar_bridge import is_external
        if is_external(self.db, self.row.tenant_id):
            return self.external(name, values)
        if name == "slots":
            result = self.service.slots(values["provider_id"], values["service_id"], values["date"])
        elif name == "hold":
            result = self.service.hold(values["slot_id"], self.row.id)
        elif name == "book":
            values["session_id"] = self.row.id
            result = self.service.create_appointment(**values, force_approval=self.row.policy_snapshot.get("mode") == "supervised")
        elif name == "cancel":
            booking = self.service.get_appointment(values.pop("appointment_id"))
            if booking.phone_hash != self.context["verified_phone"]:
                fail(404, "NOT_FOUND", "نوبت متعلق به تماس‌گیرنده پیدا نشد.")
            result = self.service.cancel_appointment(booking.id, **values, verified=True)
        else:
            booking = self.service.get_appointment(values.pop("appointment_id"))
            if booking.phone_hash != self.context["verified_phone"]:
                fail(404, "NOT_FOUND", "نوبت متعلق به تماس‌گیرنده پیدا نشد.")
            values.pop("reason", None)
            result = self.service.reschedule_appointment(booking.id, **values, verified=True)
        # The voice transaction adapter only flushes service commits. A deadline
        # rejection rolls back both the mutation and its transcript receipt.
        if (time.monotonic() - started) * 1000 > int(os.getenv("TOOL_TIMEOUT_MS", "3000")):
            fail(503, "TOOL_DEADLINE", "عملیات در مهلت مجاز تکمیل نشد؛ نتیجه باید بررسی شود.")
        return result

    def external(self, name, values):
        from .calendar_bridge import decode_slot, prepare_booking, queue_operation
        from .core import request_digest
        if name == "slots":
            request = values
            key = "voice-slots:" + self.row.id + ":" + str(self.row.turn_count) + ":" + request_digest(values)[:20]
            operation = "slots"
        elif name == "hold":
            slot = decode_slot(self.db, self.row.tenant_id, values["slot_id"])
            request = {"slot_id": slot["id"], "revision": slot["revision"], "session_id": self.row.id}
            key, operation = "voice-hold:" + self.row.id + ":" + str(self.row.turn_count), "hold"
        elif name == "book":
            row = prepare_booking(self.db, self.actor, values, call_id=self.row.id)
            return {"pending_tool": {"id": row.id, "operation": row.operation, "status": row.status}}
        else:
            from sqlalchemy import select
            import json
            from .security import decrypt
            remote_id = values["appointment_id"].removeprefix("external:")
            owned = self.db.scalar(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == self.row.tenant_id,
                ExternalCalendarOperation.remote_id == remote_id, ExternalCalendarOperation.operation == "create",
                ExternalCalendarOperation.phone_hash == self.context["verified_phone"], ExternalCalendarOperation.status == "SUCCEEDED"))
            if not owned:
                fail(404, "NOT_FOUND", "نوبت معتبر تماس‌گیرنده پیدا نشد.")
            request = {"remote_id": remote_id, "revision": str(values["version"])}
            operation, key = "cancel" if name == "cancel" else "update", values["idempotency_key"]
            if name == "reschedule":
                slot = decode_slot(self.db, self.row.tenant_id, values["slot_id"])
                prior = json.loads(decrypt(owned.result_encrypted))
                if slot["service_id"] != prior["service_id"]:
                    fail(422, "SERVICE_CHANGE_REQUIRES_REVIEW", "تغییر خدمت نیاز به بررسی پذیرش دارد.")
                request.update(slot_id=slot["id"], slot_revision=slot["revision"], provider_id=slot["provider_id"],
                               service_id=slot["service_id"], patient_token=self.context["verified_phone"])
        row = queue_operation(self.db, self.row.tenant_id, operation, request, key, self.actor.id,
                              call_id=self.row.id, phone_hash=self.context.get("verified_phone"))
        return {"pending_tool": {"id": row.id, "operation": row.operation, "status": row.status}}


