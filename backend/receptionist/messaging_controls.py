"""Trusted SMS receipt polling and a deliberately explicit outbound gateway contract.

The outbound adapter is our contract for an operator-approved gateway. It does
not claim any particular carrier implements it. No endpoint means no dialing.
"""
from __future__ import annotations

from datetime import timedelta
import os
from time import monotonic
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from .billing import IDENTIFIER, digest, lock_tenant, mark_cost_started, reserve_cost, settle_cost
from .config import settings
from .db import get_db, now_utc
from .models import Appointment, MessageOutbox, Tenant
from .models_ops_control import SMSReceiptPoll, VoiceOutreach
from .models_privacy import ContactPreference
from .operations import ReceiptInput, apply_receipt, audit, next_permitted_time, observe_adapter_failure
from .ops_controls import append_trace
from .privacy_controls import purpose_allowed, require_processor
from .providers import KavenegarSMS, ProviderError, approved_url, enabled, provider_request
from .schemas import StrictModel
from .security import Actor, decrypt, fail, normalize_phone, require_permissions

router = APIRouter(prefix="/api/v1/operations")


def sms_segment_count(body: str) -> int:
    basic = set("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
    extended = set("^{}\\[~]|€\f")
    if all(char in basic or char in extended for char in body):
        units = sum(2 if char in extended else 1 for char in body)
        segments = 1 if units <= 160 else (units + 152) // 153
    else:
        units = len(body.encode("utf-16-be")) // 2
        segments = 1 if units <= 70 else (units + 66) // 67
    if not body or segments > 10:
        fail(422, "MESSAGE_TOO_LARGE", "Approved transactional messages must use 1 to 10 segments.")
    return segments


async def poll_sms_receipts(session_factory, sms=None, limit=50):
    if settings.demo_mode:
        return {"checked": 0, "reason": "demo_no_provider_poll"}
    gateway = sms or KavenegarSMS()
    report = {"checked": 0, "delivered": 0, "failed": 0, "errors": 0}
    with session_factory() as db:
        # Backfill only real SENT jobs with a recorded provider identity.
        for msg in db.scalars(select(MessageOutbox).where(MessageOutbox.status == "SENT", MessageOutbox.provider_id.is_not(None), MessageOutbox.created_at >= now_utc() - timedelta(days=7)).limit(limit)):
            if not db.get(SMSReceiptPoll, msg.id):
                db.add(SMSReceiptPoll(message_id=msg.id, tenant_id=msg.tenant_id))
        db.commit()
        candidates = list(db.scalars(select(SMSReceiptPoll.message_id).where(SMSReceiptPoll.stopped_at.is_(None),
            SMSReceiptPoll.attempts < 12, SMSReceiptPoll.next_poll_at <= now_utc(), or_(SMSReceiptPoll.lease_until.is_(None), SMSReceiptPoll.lease_until < now_utc())).limit(limit)))
    for message_id in candidates:
        with session_factory() as db:
            poll = db.get(SMSReceiptPoll, message_id)
            lock_tenant(db, poll.tenant_id)
            claimed = db.execute(update(SMSReceiptPoll).where(SMSReceiptPoll.message_id == message_id,
                SMSReceiptPoll.stopped_at.is_(None), SMSReceiptPoll.next_poll_at <= now_utc(),
                or_(SMSReceiptPoll.lease_until.is_(None), SMSReceiptPoll.lease_until < now_utc())).values(lease_until=now_utc() + timedelta(minutes=2), attempts=SMSReceiptPoll.attempts + 1))
            if not claimed.rowcount:
                db.rollback()
                continue
            db.refresh(poll)
            msg = db.get(MessageOutbox, message_id)
            if msg.status != "SENT" or not msg.provider_id:
                poll.stopped_at, poll.last_status, poll.lease_until = now_utc(), msg.status, None
                db.commit()
                continue
            try:
                require_processor(db, poll.tenant_id, "sms_kavenegar", "processing", os.getenv("SMS_PROCESSOR_REGION", "IR"))
                ticket = reserve_cost(db, poll.tenant_id, f"sms-status:{message_id}:{poll.attempts}", "sms_kavenegar", "sms_status_request", 1)
                mark_cost_started(db, ticket["id"])
            except HTTPException as exc:
                poll.last_error_code, poll.lease_until = exc.detail["code"], None
                poll.next_poll_at = now_utc() + timedelta(minutes=30)
                db.commit()
                report["errors"] += 1
                continue
            tenant_id, provider_id, attempt = poll.tenant_id, msg.provider_id, poll.attempts
            db.commit()
            started = monotonic()
            try:
                status = await gateway.delivery(provider_id)
                if status not in {"SENT", "DELIVERED", "FAILED"}:
                    raise ProviderError("INVALID_SMS_STATUS")
                from .provider_control import observe_activity
                observe_activity(db, tenant_id, "sms_kavenegar", "delivery",
                    outcome="declined" if status == "FAILED" else "succeeded", code="SMS_DELIVERY_" + status,
                    performed_io=True, synthetic=getattr(gateway, "synthetic", False), latency_ms=int((monotonic() - started) * 1000))
                settle_cost(db, ticket["id"], 1, f"sms-status:{message_id}:{attempt}")
                if status in {"DELIVERED", "FAILED"}:
                    apply_receipt(db, ReceiptInput(event_id=f"poll:{message_id}:{status}", message_id=message_id, provider_id=provider_id, status=status))
                poll = db.get(SMSReceiptPoll, message_id)
                poll.last_status, poll.last_error_code = status, None
                append_trace(db, tenant_id, f"sms-receipt:{message_id}:{status}", "notification.receipt", job_id=message_id,
                    appointment_id=msg.appointment_id, provider="sms_kavenegar", attributes={"status": status})
                if status in {"DELIVERED", "FAILED"}:
                    poll.stopped_at = now_utc()
                    report[status.lower()] += 1
                report["checked"] += 1
            except ProviderError as exc:
                observe_adapter_failure(db, tenant_id, "sms_kavenegar", "delivery", exc,
                    synthetic=getattr(gateway, "synthetic", False), latency_ms=int((monotonic() - started) * 1000))
                settle_cost(db, ticket["id"], 0, f"sms-status-failure:{message_id}:{attempt}", "unknown" if exc.unknown_outcome else "no_charge")
                poll = db.get(SMSReceiptPoll, message_id)
                poll.last_error_code = exc.code
                report["errors"] += 1
            poll.lease_until = None
            poll.next_poll_at = now_utc() + timedelta(minutes=min(360, 2 ** min(attempt, 9)))
            if attempt >= 12 and not poll.stopped_at:
                poll.last_status, poll.stopped_at = "RECEIPT_NOT_CONFIRMED", now_utc()
            db.commit()
    return report


class ApprovedOutboundGateway:
    """Contract v1: bounded idempotent originate, followed by authoritative readback."""
    def __init__(self, client=None):
        self.client = client

    @property
    def configured(self):
        return enabled("OUTBOUND_VOICE_APPROVED") and bool(os.getenv("OUTBOUND_VOICE_GATEWAY_URL")) and len(os.getenv("OUTBOUND_VOICE_GATEWAY_TOKEN", "")) >= 32

    def connection(self):
        if not self.configured:
            raise ProviderError("OUTBOUND_VOICE_NOT_CONFIGURED")
        url = approved_url(os.environ["OUTBOUND_VOICE_GATEWAY_URL"], "OUTBOUND_VOICE_APPROVED").rstrip("/")
        return url, {"Authorization": "Bearer " + os.environ["OUTBOUND_VOICE_GATEWAY_TOKEN"]}

    async def originate(self, job_id, recipient, max_seconds, voicemail_allowed):
        url, headers = self.connection()
        prefixes = [p.strip() for p in os.getenv("OUTBOUND_ALLOWED_PREFIXES", "").split(",") if p.strip()]
        phone = normalize_phone(recipient)
        if not prefixes or not any(phone.startswith(prefix) and prefix.startswith("09") for prefix in prefixes):
            raise ProviderError("OUTBOUND_DESTINATION_NOT_APPROVED")
        capability = await provider_request("GET", url + "/v1/capabilities", operation="outbound-capabilities", headers=headers, client=self.client)
        try:
            spec = capability.json()
        except ValueError as exc:
            raise ProviderError("INVALID_OUTBOUND_CAPABILITIES") from exc
        required = {"idempotent_originate", "authoritative_readback", "max_duration_enforced", "voicemail_suppression"}
        if spec.get("schema_version") != "1.0" or not required.issubset(set(spec.get("capabilities", []))):
            raise ProviderError("OUTBOUND_CONTRACT_NOT_SUPPORTED")
        await provider_request("POST", url + "/v1/calls", operation="outbound-originate", write=True,
            headers={**headers, "Idempotency-Key": job_id}, client=self.client,
            json={"schema_version": "1.0", "request_id": job_id, "destination": phone, "max_seconds": max_seconds,
                "template": "neutral_reception_callback_v1", "text": "این پیام برای هماهنگی پذیرش است. در صورت تمایل با پذیرش تماس بگیرید.",
                "voicemail_allowed": voicemail_allowed, "machine_detection_required": True})
        try:
            return await self.read(job_id)
        except ProviderError as exc:
            raise ProviderError(exc.code, unknown_outcome=True) from exc

    async def read(self, job_id):
        url, headers = self.connection()
        response = await provider_request("GET", url + "/v1/calls/by-key/" + job_id, operation="outbound-readback", headers=headers, client=self.client)
        try:
            body = response.json()
            if body.get("request_id") != job_id or body.get("status") not in {"ACCEPTED", "RINGING", "CONNECTED", "COMPLETED", "NO_ANSWER", "REJECTED", "SUPPRESSED_VOICEMAIL"} or not isinstance(body.get("reference"), str):
                raise ValueError
            seconds = body.get("billable_seconds")
            if seconds is not None and (isinstance(seconds, bool) or not isinstance(seconds, int) or not 0 <= seconds <= 1800):
                raise ValueError
            return {"reference": body["reference"], "status": body["status"], "billable_seconds": seconds}
        except (ValueError, TypeError) as exc:
            raise ProviderError("INVALID_OUTBOUND_READBACK", unknown_outcome=True) from exc


class VoiceReminderInput(StrictModel):
    appointment_id: str
    purpose: Literal["reminder"] = "reminder"
    idempotency_key: str = Field(pattern=IDENTIFIER)
    max_seconds: int = Field(default=60, ge=10, le=120)
    patient_voice_request_confirmed: bool


@router.post("/voice-outreach")
def queue_voice(data: VoiceReminderInput, actor: Actor = Depends(require_permissions("appointment:write")), db: Session = Depends(get_db)):
    if not data.patient_voice_request_confirmed:
        fail(422, "VOICE_PERMISSION_REQUIRED", "Record the patient's request for this voice reminder.")
    lock_tenant(db, actor.tenant_id)
    appointment = db.get(Appointment, data.appointment_id)
    if not appointment or appointment.tenant_id != actor.tenant_id:
        fail(404, "APPOINTMENT_NOT_FOUND", "Appointment is unavailable.")
    if appointment.status != "CONFIRMED" or appointment.start_at <= now_utc() or not appointment.reminder_opt_in:
        fail(409, "VOICE_REMINDER_NOT_ELIGIBLE", "Only opted-in future confirmed appointments are eligible.")
    from .partners import channel_allowed
    if not channel_allowed(db, actor.tenant_id, decrypt(appointment.phone_encrypted), "voice", data.purpose) or not purpose_allowed(db, actor.tenant_id, appointment.phone_hash, data.purpose):
        fail(403, "VOICE_PERMISSION_REQUIRED", "Current purpose and voice-channel permission are both required.")
    old = db.scalar(select(VoiceOutreach).where(VoiceOutreach.tenant_id == actor.tenant_id, VoiceOutreach.idempotency_key == data.idempotency_key))
    request_hash = digest(data.model_dump())
    if old:
        if old.request_hash != request_hash:
            fail(409, "VOICE_JOB_CONFLICT", "This voice request already has different details.")
        return voice_dict(old)
    existing = list(db.scalars(select(VoiceOutreach).where(VoiceOutreach.tenant_id == actor.tenant_id, VoiceOutreach.appointment_id == appointment.id, VoiceOutreach.purpose == data.purpose)))
    if len(existing) >= 2 or any(row.status not in {"NO_ANSWER", "REJECTED", "FAILED", "SUPPRESSED", "SIMULATED"} for row in existing):
        fail(429, "VOICE_ATTEMPT_LIMIT", "A maximum of two explicitly requested, definitively unsuccessful attempts is allowed.")
    preference = db.scalar(select(ContactPreference).where(ContactPreference.tenant_id == actor.tenant_id, ContactPreference.subject_hash == appointment.phone_hash))
    row = VoiceOutreach(tenant_id=actor.tenant_id, appointment_id=appointment.id, subject_hash=appointment.phone_hash,
        recipient_encrypted=appointment.phone_encrypted, purpose=data.purpose, idempotency_key=data.idempotency_key,
        request_hash=request_hash, max_seconds=data.max_seconds, expires_at=appointment.start_at,
        voicemail_allowed=bool(preference and preference.voicemail_allowed and not preference.shared_phone), created_by=actor.id)
    db.add(row)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "outreach.voice_requested", "voice_outreach", row.id, appointment_id=row.appointment_id)
    db.commit()
    return voice_dict(row)


def voice_dict(row):
    return {k: getattr(row, k) for k in ("id", "appointment_id", "purpose", "status", "attempts", "max_seconds", "provider_reference", "last_error_code", "not_before", "expires_at", "created_at")}


@router.get("/voice-outreach")
def voice_jobs(actor: Actor = Depends(require_permissions("appointment:read")), db: Session = Depends(get_db)):
    return {"gateway_configured": ApprovedOutboundGateway().configured,
        "jobs": [voice_dict(row) for row in db.scalars(select(VoiceOutreach).where(VoiceOutreach.tenant_id == actor.tenant_id).order_by(VoiceOutreach.created_at.desc()).limit(100))],
        "contract": "operator_approved_outbound_gateway_v1", "real_carrier_verification": "external_gate"}


async def run_voice_jobs(session_factory, gateway=None, limit=20):
    gateway = gateway or ApprovedOutboundGateway()
    report = {"submitted": 0, "reconciled": 0, "suppressed": 0, "unknown": 0, "simulated": 0}
    with session_factory() as db:
        candidates = list(db.execute(select(VoiceOutreach.id, VoiceOutreach.tenant_id).where(
            VoiceOutreach.status.in_(["QUEUED", "ACCEPTED", "RINGING", "CONNECTED", "UNKNOWN", "DISPATCHING"]),
            VoiceOutreach.not_before <= now_utc(), or_(VoiceOutreach.lease_until.is_(None), VoiceOutreach.lease_until < now_utc())).limit(limit)))
    for job_id, tenant_id in candidates:
        with session_factory() as db:
            lock_tenant(db, tenant_id)
            job = db.get(VoiceOutreach, job_id)
            if job.lease_until and job.lease_until > now_utc():
                continue
            is_new = job.status == "QUEUED"
            appointment = db.get(Appointment, job.appointment_id)
            from .partners import channel_allowed
            if is_new and (job.expires_at <= now_utc() or appointment.status != "CONFIRMED" or not appointment.reminder_opt_in
                or not purpose_allowed(db, tenant_id, job.subject_hash, job.purpose) or not channel_allowed(db, tenant_id, decrypt(job.recipient_encrypted), "voice", job.purpose)):
                job.status = "SUPPRESSED"
                db.commit()
                report["suppressed"] += 1
                continue
            if is_new:
                permitted = next_permitted_time(db.get(Tenant, tenant_id), now_utc())
                if permitted > now_utc() + timedelta(seconds=1):
                    job.not_before = permitted
                    db.commit()
                    continue
                if settings.demo_mode:
                    job.status = "SIMULATED"
                    db.commit()
                    report["simulated"] += 1
                    continue
                if not gateway.configured:
                    job.status, job.last_error_code = "FAILED", "OUTBOUND_VOICE_NOT_CONFIGURED"
                    db.commit()
                    continue
                try:
                    require_processor(db, tenant_id, "telephony_primary", "reminder", os.getenv("OUTBOUND_PROCESSOR_REGION", "IR"), job.subject_hash)
                    ticket = reserve_cost(db, tenant_id, "voice-outreach:" + job.id, "telephony_primary", "outbound_call_seconds", job.max_seconds)
                    mark_cost_started(db, ticket["id"])
                    job.reservation_id = ticket["id"]
                except HTTPException as exc:
                    job.status, job.last_error_code = "FAILED", exc.detail["code"]
                    db.commit()
                    continue
                job.status, job.attempts = "DISPATCHING", job.attempts + 1
            job.lease_until = now_utc() + timedelta(minutes=3)
            phone, max_seconds, voicemail = decrypt(job.recipient_encrypted), job.max_seconds, job.voicemail_allowed
            reservation = job.reservation_id
            db.commit()
            try:
                result = await gateway.originate(job_id, phone, max_seconds, voicemail) if is_new else await gateway.read(job_id)
                job = db.get(VoiceOutreach, job_id)
                job.status, job.provider_reference = result["status"], result["reference"]
                terminal = result["status"] in {"COMPLETED", "NO_ANSWER", "REJECTED", "SUPPRESSED_VOICEMAIL"}
                if terminal and result.get("billable_seconds") is not None:
                    settle_cost(db, reservation, result["billable_seconds"], "voice-receipt:" + result["reference"])
                elif terminal:
                    settle_cost(db, reservation, 0, "voice-cost-unknown:" + job_id, "unknown")
                    job.last_error_code = "BILLABLE_DURATION_NOT_CONFIRMED"
                report["submitted" if is_new else "reconciled"] += 1
            except ProviderError as exc:
                job = db.get(VoiceOutreach, job_id)
                if exc.unknown_outcome or not is_new:
                    job.status = "UNKNOWN"
                    if reservation:
                        settle_cost(db, reservation, 0, "voice-unknown:" + job_id, "unknown")
                    report["unknown"] += 1
                else:
                    job.status = "FAILED"
                    if reservation:
                        settle_cost(db, reservation, 0, "voice-not-started:" + job_id, "no_charge")
                job.last_error_code = exc.code
            job.lease_until, job.not_before = None, now_utc() + timedelta(minutes=5)
            db.commit()
    return report


async def run_messaging_control_jobs(session_factory):
    return {"receipts": await poll_sms_receipts(session_factory), "voice": await run_voice_jobs(session_factory)}
