"""Automated media admission liability, separate from a carrier bill.

The configured maximum automated duration is reserved before media access. A
local disconnect, silence-inclusive elapsed time or AI-to-human handoff does not
prove a carrier's final charge; its liability remains UNKNOWN until the existing
operator-evidenced financial reconciliation workflow records the result.
"""
import os
from decimal import Decimal

from sqlalchemy import select

from .billing import mark_cost_started, reserve_cost, settle_cost, ticket_dict
from .core_policy import lock
from .db import now_utc
from .models import AuditEvent
from .models_finance import CostReservation
from .ops_controls import append_trace
from .privacy_controls import require_processor
from .provider_control import require_capability
from .security import fail


def reserve_media_cost(db, call):
    """Flush-only; commit before releasing a SIP grant or calling room APIs."""
    lock(db, call.tenant_id)
    require_capability(db, call.tenant_id, "telephony_primary", "start")
    require_processor(db, call.tenant_id, "telephony_primary", "processing",
                      os.getenv("TELEPHONY_PROCESSOR_REGION", "not_recorded"), subject_hash="session:" + call.id)
    key = "media:" + call.id
    previous = db.scalar(select(CostReservation).where(CostReservation.tenant_id == call.tenant_id,
        CostReservation.provider == "telephony_primary", CostReservation.meter == "telephony_seconds", CostReservation.operation_key == key))
    if previous:
        if previous.status == "STARTED" and call.media_room:
            return {**ticket_dict(previous), "replayed": True}
        fail(409, "MEDIA_ADMISSION_PENDING", "A prior media admission must be reconciled before another attempt.")
    duration = Decimal(str(max(1, (call.expires_at - now_utc()).total_seconds())))
    ticket = reserve_cost(db, call.tenant_id, key, "telephony_primary", "telephony_seconds", duration, call_id=call.id)
    mark_cost_started(db, ticket["id"])
    append_trace(db, call.tenant_id, key + ":reserved", "media.cost_reserved", call_id=call.id, provider="telephony_primary",
        attributes={"reservation_id": ticket["id"], "quantity": str(duration), "unit": "second", "status": "automated_media_admission"})
    return {**ticket, "replayed": False}


def finalize_media_cost(db, call, *, reason="disconnect"):
    """Flush-only, idempotent. Measured elapsed is evidence, never a final bill."""
    lock(db, call.tenant_id)
    reservation = db.scalar(select(CostReservation).where(CostReservation.tenant_id == call.tenant_id,
        CostReservation.call_id == call.id, CostReservation.provider == "telephony_primary", CostReservation.meter == "telephony_seconds"))
    if not reservation:
        return {"status": "NOT_RESERVED"}
    previous = db.scalar(select(AuditEvent.id).where(AuditEvent.tenant_id == call.tenant_id,
        AuditEvent.action == "media.cost_reconciliation_required", AuditEvent.entity_id == call.id))
    if previous or reservation.status in {"SETTLED", "RELEASED", "EXPIRED"}:
        return {"status": reservation.status, "reservation_id": reservation.id}
    ended = min(call.ended_at or now_utc(), call.expires_at)
    elapsed_ms = max(0, int((ended - call.started_at).total_seconds() * 1000))
    reason = reason if reason in {"disconnect", "expiry", "human_takeover", "admission_failure"} else "disconnect"
    settle_cost(db, reservation.id, 0, "media-pending:" + call.id, outcome="unknown")
    db.add(AuditEvent(tenant_id=call.tenant_id, actor_id="media-cost", action="media.cost_reconciliation_required",
        entity_type="call", entity_id=call.id, details={"reason": reason, "measured_elapsed_ms": elapsed_ms,
            "measurement_boundary": "logical_session_including_silence", "reservation_id": reservation.id,
            "charge_status": "UNKNOWN", "scope": "automated_media_only"}))
    append_trace(db, call.tenant_id, "media:" + call.id + ":finalized", "media.cost_pending", call_id=call.id, provider="telephony_primary",
        attributes={"reservation_id": reservation.id, "duration_ms": elapsed_ms, "status": "UNKNOWN", "outcome": reason})
    return {"status": "UNKNOWN", "reservation_id": reservation.id, "measured_elapsed_ms": elapsed_ms}
