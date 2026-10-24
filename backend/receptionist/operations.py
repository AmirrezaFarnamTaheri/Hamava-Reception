"""Tenant-scoped jobs and operational workflows with explicit external boundaries."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
import os
import re
import secrets
from time import monotonic
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, Header, Request, HTTPException
from pydantic import Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .config import settings
from .core import CALL_DURATION_KINDS, ReceptionService, call_minutes, iso, jalali_label, notification_dict, request_digest
from .db import SessionLocal, get_db, now_utc
from .models import (
    Appointment,
    AuditEvent,
    ConsentGrant,
    IdempotencyRecord,
    Membership,
    MessageOutbox,
    Occupancy,
    Service,
    SlotHold,
    StaffTask,
    Tenant,
    UsageEvent,
    uid,
)
from .models_ops import (
    BillingAdjustment,
    DeliveryReceipt,
    Invoice,
    OutreachSuppression,
    PaymentIntent,
    PrivacyTombstone,
    RefundLedger,
    WaitlistEntry,
    WaitlistOffer,
)
from .models_partner import ChannelPermission
from . import models_core, models_finance, models_privacy, models_ops_control  # noqa: F401
from .providers import KavenegarSMS, ProviderError, SpeechGateway, enabled, verify_webhook
from .schemas import StrictModel
from .security import Actor, current_actor, decrypt, encrypt, fail, has_permission, hash_phone, mask_phone, normalize_phone, require_permissions

router = APIRouter(prefix="/api/v1")
admin = require_permissions("billing:write")
staff = require_permissions("appointment:write")


def audit(db, tenant_id, actor_id, action, entity_type, entity_id, **details):
    db.add(AuditEvent(tenant_id=tenant_id, actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, details=details))


def observe_adapter_failure(db, tenant_id, provider, operation, error, *, synthetic=False, latency_ms=None):
    """Only known transport/response errors are evidence of attempted provider I/O.

    Adapter invocation alone is insufficient: configuration checks and an open
    local circuit can reject before a request. Keep this allowlist aligned with
    the bounded Kavenegar/Zarinpal adapters; unknown codes remain unobserved.
    """
    from .provider_control import observe_activity

    responses = {
        ("sms_kavenegar", "send"): {"SMS_REJECTED", "INVALID_SMS_RESPONSE"},
        ("sms_kavenegar", "delivery"): {"SMS_STATUS_UNAVAILABLE", "INVALID_SMS_STATUS"},
        ("payment_primary", "request"): {"PAYMENT_REJECTED", "INVALID_PAYMENT_RESPONSE"},
        ("payment_primary", "verify"): {"PAYMENT_NOT_SETTLED", "INVALID_PAYMENT_VERIFICATION"},
    }
    performed_io = error.code in {"PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE", "PROVIDER_REJECTED"} | responses.get((provider, operation), set())
    # The current adapters aggregate multiple provider rejection codes. Until
    # a normal business decline is separately typed, an aggregate rejection
    # must not hide a broken merchant/account configuration as healthy.
    return observe_activity(db, tenant_id, provider, operation,
        outcome="unknown" if error.unknown_outcome else "failed",
        code=error.code, performed_io=performed_io, synthetic=synthetic, latency_ms=latency_ms)


def suppressed(db: Session, tenant_id: str, phone: str, purpose: str | None = None) -> bool:
    subject = hash_phone(phone)
    erased = (
        db.scalar(select(PrivacyTombstone.id).where(PrivacyTombstone.tenant_id == tenant_id, PrivacyTombstone.subject_hash == subject))
        is not None
    )
    if erased or purpose is None:
        return erased
    return (
        db.scalar(
            select(OutreachSuppression.id).where(
                OutreachSuppression.tenant_id == tenant_id,
                OutreachSuppression.subject_hash == subject,
                OutreachSuppression.purpose == purpose,
            )
        )
        is not None
    )


def sms_outreach_allowed(db: Session, tenant_id: str, phone: str, purpose: str) -> bool:
    """Channel-specific choices override existing purpose-bound SMS consent.

    An absent channel row preserves the existing reminder opt-in, waitlist
    consent or followup enrollment checks. A present row must pass the partner
    channel policy, whose broader privacy and purpose suppression takes priority.
    """
    if suppressed(db, tenant_id, phone, purpose):
        return False
    if purpose not in {"reminder", "waitlist", "followup"}:
        return True
    from .partners import channel_allowed

    row = db.scalar(
        select(ChannelPermission.id).where(
            ChannelPermission.tenant_id == tenant_id,
            ChannelPermission.subject_hash == hash_phone(phone),
            ChannelPermission.channel == "sms",
            ChannelPermission.purpose == purpose,
        )
    )
    return row is None or channel_allowed(db, tenant_id, phone, "sms", purpose)


def lock_tenant(db: Session, tenant_id: str) -> None:
    """Serialize infrequent privacy/refund controls on SQLite and PostgreSQL."""
    changed = db.execute(update(Tenant).where(Tenant.id == tenant_id).values(active=Tenant.active))
    if changed.rowcount != 1:
        fail(404, "NOT_FOUND", "مرکز پیدا نشد.")


def next_permitted_time(tenant: Tenant, moment: datetime) -> datetime:
    """Return now or the end of the tenant's local quiet window; handles midnight."""
    local = moment.astimezone(ZoneInfo(tenant.timezone))
    start = time.fromisoformat(tenant.quiet_hours["start"])
    end = time.fromisoformat(tenant.quiet_hours["end"])
    clock = local.time().replace(tzinfo=None)
    quiet = start <= clock < end if start < end else clock >= start or clock < end
    if not quiet:
        return moment
    day = local.date() + timedelta(days=1) if start > end and clock >= start else local.date()
    return datetime.combine(day, end, local.tzinfo)


def enqueue(db: Session, **values) -> bool:
    """An outbox key is the scheduling job's single-writer invariant."""
    if db.scalar(
        select(MessageOutbox.id).where(MessageOutbox.tenant_id == values["tenant_id"], MessageOutbox.dedupe_key == values["dedupe_key"])
    ):
        return False
    try:
        with db.begin_nested():
            db.add(MessageOutbox(**values))
            db.flush()
        return True
    except IntegrityError:
        return False


def run_jobs(db: Session) -> dict:
    """Plan/expire local jobs. No external I/O and no inferred delivery success."""
    now = now_utc()
    counts = {"reminders_queued": 0, "offers_expired": 0, "uncertain_sends": 0, "calls_expired": 0, "retention_purged": 0}
    from .models_voice import CallSession, VerificationChallenge
    from .operations_outreach import process_auto_offers, record_capacity_release, schedule_outreach
    from .privacy_controls import purge_administrative_transcripts

    counts["followups_queued"] = 0

    for tenant in db.scalars(select(Tenant).where(Tenant.active.is_(True)).order_by(Tenant.id)):
        ReceptionService(db, tenant.id, "worker")._expire()
        stalled = list(
            db.scalars(
                select(MessageOutbox).where(
                    MessageOutbox.tenant_id == tenant.id, MessageOutbox.status == "SENDING", MessageOutbox.locked_until <= now
                )
            )
        )
        for msg in stalled:
            msg.status, msg.last_error_code = "UNKNOWN", "WORKER_LOST_AFTER_DISPATCH"
            msg.locked_until = None
            db.add(
                StaffTask(
                    tenant_id=tenant.id,
                    reason="NOTIFICATION_RECONCILE",
                    summary="نتیجه ارسال پیام نامشخص است؛ پیش از ارسال مجدد باید از درگاه بررسی شود.",
                )
            )
            counts["uncertain_sends"] += 1
        scheduled = schedule_outreach(db, tenant, now)
        counts["reminders_queued"] += scheduled["reminders_queued"]
        counts["followups_queued"] += scheduled["followups_queued"]
        expired = list(
            db.scalars(
                select(WaitlistOffer)
                .where(WaitlistOffer.tenant_id == tenant.id, WaitlistOffer.status == "OFFERED", WaitlistOffer.expires_at <= now)
                .with_for_update()
            )
        )
        for offer in expired:
            offer.status = "EXPIRED"
            entry = db.get(WaitlistEntry, offer.entry_id)
            if entry and entry.status == "OFFERED":
                entry.status = "WAITING" if entry.offer_attempts < 3 else "EXHAUSTED"
                if entry.status == "EXHAUSTED":
                    entry.active_key = None
            db.execute(
                update(SlotHold)
                .where(SlotHold.tenant_id == tenant.id, SlotHold.id == offer.hold_id, SlotHold.status == "HELD")
                .values(status="EXPIRED")
            )
            db.execute(
                delete(Occupancy).where(
                    Occupancy.tenant_id == tenant.id, Occupancy.owner_type == "hold", Occupancy.owner_id == offer.hold_id
                )
            )
            counts["offers_expired"] += 1
            hold = db.scalar(select(SlotHold).where(SlotHold.id == offer.hold_id, SlotHold.tenant_id == tenant.id))
            if hold:
                record_capacity_release(db, hold, "waitlist_expired", 1)
            audit(db, tenant.id, "worker", "waitlist.expired", "offer", offer.id, entry_status=entry.status if entry else None)
        # No room/session silently continues after its authorized life.
        expired_calls = list(
            db.scalars(
                select(CallSession).where(CallSession.tenant_id == tenant.id, CallSession.ended_at.is_(None), CallSession.expires_at <= now)
            )
        )
        for call in expired_calls:
            changed = db.execute(
                update(CallSession)
                .where(CallSession.id == call.id, CallSession.tenant_id == tenant.id, CallSession.ended_at.is_(None))
                .values(ended_at=now, state="EXPIRED", lease_token=None, lease_until=None)
            )
            if changed.rowcount:
                from .voice import release_holds
                from .media_cost import finalize_media_cost

                release_holds(db, call)
                finalize_media_cost(db, call, reason="expiry")
                seconds = max(0, (call.expires_at - call.started_at).total_seconds())
                db.add(UsageEvent(tenant_id=tenant.id, call_id=call.id, kind="call_seconds", quantity=seconds, unit="second", cost_toman=0))
                counts["calls_expired"] += 1
        counts["retention_purged"] += purge_administrative_transcripts(db, tenant, moment=now)
        db.execute(
            delete(VerificationChallenge).where(
                VerificationChallenge.tenant_id == tenant.id, VerificationChallenge.expires_at < now - timedelta(hours=1)
            )
        )
        db.execute(
            update(ConsentGrant)
            .where(ConsentGrant.tenant_id == tenant.id, ConsentGrant.granted.is_(True), ConsentGrant.expires_at <= now)
            .values(granted=False)
        )
    db.commit()
    counts.update(process_auto_offers(db))
    return counts


async def run_once(session_factory=SessionLocal, sms: KavenegarSMS | None = None) -> dict:
    """Bounded outbox worker. Claim/commit before external send; no blind retries."""
    gateway = sms or KavenegarSMS()
    with session_factory() as db:
        report = run_jobs(db)
        candidates = list(
            db.execute(
                select(MessageOutbox.id, MessageOutbox.tenant_id)
                .where(MessageOutbox.status == "QUEUED", MessageOutbox.available_at <= now_utc(), MessageOutbox.attempts < 3)
                .order_by(MessageOutbox.created_at)
                .limit(100)
            )
        )
    report.update({"simulated": 0, "sent": 0, "failed": 0, "unknown": 0, "suppressed": 0})
    for message_id, tenant_id in candidates:
        with session_factory() as db:
            claimed = db.execute(
                update(MessageOutbox)
                .where(
                    MessageOutbox.id == message_id,
                    MessageOutbox.tenant_id == tenant_id,
                    MessageOutbox.status == "QUEUED",
                    MessageOutbox.available_at <= now_utc(),
                )
                .values(status="SENDING", locked_until=now_utc() + timedelta(minutes=2), attempts=MessageOutbox.attempts + 1)
            )
            if claimed.rowcount != 1:
                db.rollback()
                continue
            msg = db.get(MessageOutbox, message_id)
            tenant = db.get(Tenant, tenant_id)
            phone = decrypt(msg.recipient_encrypted)
            booking = db.get(Appointment, msg.appointment_id) if msg.appointment_id else None
            try:
                same_time = bool(
                    booking and datetime.fromisoformat(str(msg.payload.get("start_at", "")).replace("Z", "+00:00")) == booking.start_at
                )
            except ValueError:
                same_time = False
            invalid_booking = bool(
                booking
                and (
                    booking.tenant_id != tenant_id
                    or (msg.purpose in {"confirmed", "reminder", "rescheduled"} and (booking.status != "CONFIRMED" or not same_time))
                    or (msg.purpose == "reminder" and (not booking.reminder_opt_in or booking.start_at <= now_utc()))
                    or (msg.purpose == "pending" and booking.status not in {"PENDING_PAYMENT", "PENDING_STAFF_APPROVAL"})
                )
            )
            invalid_offer = False
            if msg.purpose == "reminder" and msg.payload.get("offset_minutes") is not None:
                from .operations_outreach import policy_for

                outreach = policy_for(db, tenant_id)
                valid_offsets = outreach.reminder_offsets_minutes if outreach else [1440]
                invalid_booking = invalid_booking or msg.payload["offset_minutes"] not in valid_offsets
            if msg.purpose == "followup":
                from .operations_outreach import followup_send_allowed

                invalid_offer = not followup_send_allowed(db, tenant_id, str(msg.payload.get("enrollment_id", "")), booking)
            if booking and msg.purpose in {"confirmed", "reminder", "rescheduled"}:
                from .models_ext import AppointmentImpact

                invalid_booking = (
                    invalid_booking
                    or db.scalar(
                        select(AppointmentImpact.id)
                        .where(
                            AppointmentImpact.tenant_id == tenant_id,
                            AppointmentImpact.appointment_id == booking.id,
                            AppointmentImpact.state != "RESOLVED",
                        )
                        .limit(1)
                    )
                    is not None
                )
            if msg.purpose == "disruption":
                from .models_ext import AppointmentImpact

                invalid_offer = (
                    not booking
                    or booking.status not in {"CONFIRMED", "PENDING_PAYMENT", "PENDING_STAFF_APPROVAL"}
                    or db.scalar(
                        select(AppointmentImpact.id)
                        .where(
                            AppointmentImpact.tenant_id == tenant_id,
                            AppointmentImpact.appointment_id == booking.id,
                            AppointmentImpact.disruption_id == str(msg.payload.get("disruption_id", "")),
                            AppointmentImpact.state != "RESOLVED",
                        )
                        .limit(1)
                    )
                    is None
                )
            if msg.purpose == "waitlist":
                offer = db.scalar(
                    select(WaitlistOffer).where(
                        WaitlistOffer.id == str(msg.payload.get("offer_id", "")), WaitlistOffer.tenant_id == tenant_id
                    )
                )
                entry = (
                    db.scalar(select(WaitlistEntry).where(WaitlistEntry.id == offer.entry_id, WaitlistEntry.tenant_id == tenant_id))
                    if offer
                    else None
                )
                hold = db.scalar(select(SlotHold).where(SlotHold.id == offer.hold_id, SlotHold.tenant_id == tenant_id)) if offer else None
                invalid_offer = not (
                    offer
                    and offer.status == "OFFERED"
                    and offer.expires_at > now_utc()
                    and entry
                    and entry.status == "OFFERED"
                    and entry.consent
                    and hold
                    and hold.status == "HELD"
                    and hold.expires_at > now_utc()
                )
            if not sms_outreach_allowed(db, tenant_id, phone, msg.purpose) or invalid_booking or invalid_offer or not tenant.active:
                msg.status, msg.locked_until = "SUPPRESSED", None
                db.commit()
                report["suppressed"] += 1
                continue
            if msg.purpose in {"reminder", "waitlist", "followup"}:
                permitted = next_permitted_time(tenant, now_utc())
                if permitted > now_utc() + timedelta(seconds=1):
                    msg.status, msg.available_at, msg.locked_until = "QUEUED", permitted, None
                    msg.attempts -= 1
                    db.commit()
                    continue
            if settings.demo_mode:
                msg.status, msg.last_error_code, msg.locked_until = "SIMULATED", "DEMO_NO_EXTERNAL_SEND", None
                db.commit()
                report["simulated"] += 1
                continue
            otp = None
            if msg.purpose == "verification":
                otp = json.loads(decrypt(msg.payload["secret"]))["code"]
                body = "کد تایید پذیرش"
            elif msg.purpose == "conversation_reply":
                from .models_voice import CallSession
                call = db.get(CallSession, str(msg.payload.get("call_id", "")))
                if not call or call.tenant_id != tenant_id or not call.processing_consent or call.phone_hash != hash_phone(phone):
                    msg.status, msg.last_error_code, msg.locked_until = "SUPPRESSED", "CONVERSATION_PERMISSION_REQUIRED", None
                    db.commit()
                    report["suppressed"] += 1
                    continue
                body = decrypt(msg.payload.get("text_encrypted", ""))
                if not body or len(body) > 2000:
                    msg.status, msg.last_error_code, msg.locked_until = "FAILED", "INVALID_CONVERSATION_REPLY", None
                    db.commit()
                    report["failed"] += 1
                    continue
            elif booking:
                words = {
                    "confirmed": "ثبت شد",
                    "reminder": "یادآوری می‌شود",
                    "canceled": "لغو شد",
                    "rescheduled": "جابه‌جا شد",
                    "pending": "در انتظار تکمیل است",
                }
                body = f"{tenant.name}: نوبت با کد {booking.reference} {words.get(msg.purpose, 'به‌روزرسانی شد')}. {jalali_label(booking.start_at, tenant.timezone)}"
                if msg.purpose == "disruption":
                    descriptions = {
                        "LATE_ARRIVAL": "تاخیر شما برای بررسی پذیرش ثبت شد.",
                        "PROVIDER_DELAY": "پزشک در برنامه تاخیر دارد.",
                        "EMERGENCY_CLOSURE": "مرکز در بازه نوبت شما محدودیت یا تعطیلی اعلام کرده است.",
                    }
                    body = f"{tenant.name}: {descriptions.get(msg.payload.get('kind'), 'برنامه نوبت تغییر کرده است.')} کد {booking.reference}. زمان جایگزین هنوز ثبت نشده است؛ پذیرش باید وضعیت نوبت را با شما تعیین تکلیف کند."
                elif msg.purpose == "followup":
                    body = f"{tenant.name}: برای هماهنگی پیگیری پس از مراجعه، در صورت تمایل با پذیرش تماس بگیرید."
                elif msg.purpose == "reminder" and msg.payload.get("response_id"):
                    from .models_outreach import AppointmentResponse
                    from .operations_outreach import response_path

                    response = db.scalar(
                        select(AppointmentResponse).where(
                            AppointmentResponse.id == msg.payload["response_id"],
                            AppointmentResponse.tenant_id == tenant_id,
                            AppointmentResponse.appointment_id == booking.id,
                        )
                    )
                    public_base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
                    if response and response.status != "REVOKED" and public_base.startswith("https://"):
                        body += " پاسخ به یادآوری: " + public_base + response_path(response)
            elif msg.purpose == "waitlist":
                body = f"{tenant.name}: یک زمان برای شما موقتاً نگه داشته شده است. برای پذیرش پیشنهاد با پذیرش تماس بگیرید."
            else:
                msg.status, msg.last_error_code, msg.locked_until = "FAILED", "UNAPPROVED_TEMPLATE", None
                db.commit()
                report["failed"] += 1
                continue
            from .billing import reserve_cost, mark_cost_started, settle_cost, record_vendor_cost
            from .privacy_controls import require_processor, neutral_message
            from .ops_controls import append_trace
            from .messaging_controls import sms_segment_count
            body = neutral_message(db, tenant_id, hash_phone(phone), body, tenant.name)
            try:
                quantity = 1 if otp else sms_segment_count(body)
                require_processor(db, tenant_id, "sms_kavenegar", "processing", os.getenv("SMS_PROCESSOR_REGION", "IR"), hash_phone(phone))
                ticket = reserve_cost(db, tenant_id, f"sms:{msg.id}:{msg.attempts}", "sms_kavenegar", "sms_otp_lookup" if otp else "sms_segments", quantity)
                mark_cost_started(db, ticket["id"])
                trace = append_trace(db, tenant_id, f"sms:{msg.id}:{msg.attempts}:started", "provider.started",
                    job_id=msg.id, appointment_id=msg.appointment_id, provider="sms_kavenegar", versions={"adapter": "kavenegar-v1"},
                    attributes={"reservation_id": ticket["id"], "quantity": quantity, "unit": "lookup" if otp else "segment"})
                trace_id = trace.id
            except HTTPException as exc:
                msg.status, msg.last_error_code, msg.locked_until = "FAILED", exc.detail["code"], None
                db.commit()
                report["failed"] += 1
                continue
            db.commit()
            started = monotonic()
            try:
                result = await gateway.send(phone, body, otp=otp)
                from .provider_control import observe_activity
                observe_activity(db, tenant_id, "sms_kavenegar", "send", outcome="succeeded", code="SMS_SEND_ACCEPTED",
                    performed_io=True, synthetic=getattr(gateway, "synthetic", False), latency_ms=int((monotonic() - started) * 1000))
                msg = db.get(MessageOutbox, message_id)
                msg.status, msg.provider_id, msg.locked_until = "SENT", result["provider_id"], None
                msg.last_error_code = None
                db.add(UsageEvent(tenant_id=tenant_id, kind="sms", quantity=1, unit="message", cost_toman=(result.get("cost_rial") or 0) / 10))
                charge = settle_cost(db, ticket["id"], quantity, "sms-receipt:" + str(result["provider_id"]))
                if result.get("cost_rial") is not None:
                    record_vendor_cost(db, charge["charge_id"], result["cost_rial"], "IRR", "sms-cost:" + str(result["provider_id"]))
                append_trace(db, tenant_id, f"sms:{message_id}:{msg.attempts}:sent", "provider.completed", job_id=message_id,
                    appointment_id=msg.appointment_id, parent_id=trace_id, provider="sms_kavenegar", attributes={"status": "SENT"})
                from .models_ops_control import SMSReceiptPoll
                if not db.get(SMSReceiptPoll, msg.id):
                    db.add(SMSReceiptPoll(message_id=msg.id, tenant_id=tenant_id, next_poll_at=now_utc() + timedelta(minutes=1)))
                report["sent"] += 1
            except ProviderError as exc:
                observe_adapter_failure(db, tenant_id, "sms_kavenegar", "send", exc,
                    synthetic=getattr(gateway, "synthetic", False), latency_ms=int((monotonic() - started) * 1000))
                msg = db.get(MessageOutbox, message_id)
                msg.status = "UNKNOWN" if exc.unknown_outcome else "FAILED"
                msg.last_error_code, msg.locked_until = exc.code, None
                settle_cost(db, ticket["id"], 0, f"sms-failure:{message_id}:{msg.attempts}", "unknown" if exc.unknown_outcome else "no_charge")
                append_trace(db, tenant_id, f"sms:{message_id}:{msg.attempts}:failed", "provider.failed", job_id=message_id,
                    parent_id=trace_id, provider="sms_kavenegar", attributes={"error_code": exc.code, "outcome": "unknown" if exc.unknown_outcome else "no_charge"})
                report["unknown" if exc.unknown_outcome else "failed"] += 1
                if exc.unknown_outcome:
                    db.add(
                        StaffTask(
                            tenant_id=tenant_id,
                            reason="NOTIFICATION_RECONCILE",
                            summary="نتیجه ارسال مشخص نیست؛ ارسال مجدد خودکار متوقف شد.",
                        )
                    )
            db.commit()
    return report


@router.post("/operations/notifications/{message_id}/retry")
def retry_notification(message_id: str, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    msg = db.scalar(
        select(MessageOutbox).where(MessageOutbox.id == message_id, MessageOutbox.tenant_id == actor.tenant_id).with_for_update()
    )
    if not msg:
        fail(404, "NOT_FOUND", "پیام پیدا نشد.")
    if msg.status != "FAILED" or msg.attempts >= 3:
        fail(409, "RETRY_NOT_SAFE", "ارسال دوباره برای این وضعیت مجاز نیست؛ ابتدا نتیجه ارسال را بررسی کنید.")
    changed = db.execute(
        update(MessageOutbox)
        .where(
            MessageOutbox.id == msg.id,
            MessageOutbox.tenant_id == actor.tenant_id,
            MessageOutbox.status == "FAILED",
            MessageOutbox.attempts < 3,
        )
        .values(status="QUEUED", available_at=now_utc(), locked_until=None)
    )
    if changed.rowcount != 1:
        fail(409, "RETRY_NOT_SAFE", "وضعیت پیام هم‌زمان تغییر کرده است.")
    audit(db, actor.tenant_id, actor.id, "notification.retry_queued", "message", msg.id)
    db.commit()
    db.refresh(msg)
    return notification_dict(msg)


class ReceiptInput(StrictModel):
    event_id: str = Field(min_length=8, max_length=150)
    message_id: str = Field(max_length=60)
    provider_id: str = Field(max_length=150)
    status: Literal["DELIVERED", "FAILED"]


def apply_receipt(db: Session, data: ReceiptInput) -> dict:
    digest = request_digest(data.model_dump())
    old = db.scalar(select(DeliveryReceipt).where(DeliveryReceipt.event_id == data.event_id))
    if old:
        if old.payload_hash != digest:
            fail(409, "RECEIPT_REPLAY_MISMATCH", "رویداد تکراری متفاوت است.")
        return {"status": "already_processed"}
    msg = db.scalar(
        select(MessageOutbox).where(MessageOutbox.id == data.message_id, MessageOutbox.provider_id == data.provider_id).with_for_update()
    )
    if not msg:
        fail(404, "NOT_FOUND", "پیام یافت نشد.")
    if msg.status not in {"SENT", "DELIVERED", "FAILED", "UNKNOWN"}:
        fail(409, "INVALID_DELIVERY_STATE", "نتیجه دریافت با وضعیت ارسال سازگار نیست.")
    # Delivered is terminal: a late failure notification may not downgrade it.
    if msg.status != "DELIVERED":
        msg.status = data.status
    db.add(DeliveryReceipt(tenant_id=msg.tenant_id, event_id=data.event_id, message_id=msg.id, payload_hash=digest, status=data.status))
    audit(db, msg.tenant_id, "provider", "notification.receipt", "message", msg.id, status=data.status)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        old = db.scalar(select(DeliveryReceipt).where(DeliveryReceipt.event_id == data.event_id))
        if not old or old.payload_hash != digest:
            fail(409, "RECEIPT_REPLAY_MISMATCH", "رویداد تکراری متفاوت است.")
    return {"status": "processed"}


@router.post("/webhooks/notifications")
async def notification_receipt(
    request: Request, x_timestamp: str = Header(default=""), x_signature: str = Header(default=""), db: Session = Depends(get_db)
):
    body = await request.body()
    if len(body) > 8192 or not verify_webhook(body, x_timestamp, x_signature, os.getenv("NOTIFICATION_WEBHOOK_SECRET", "")):
        fail(401, "INVALID_WEBHOOK_SIGNATURE", "درخواست معتبر نیست.")
    return apply_receipt(db, ReceiptInput.model_validate_json(body))


class WaitlistInput(StrictModel):
    provider_id: str = Field(max_length=60)
    service_id: str = Field(max_length=60)
    patient_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(max_length=30)
    date_from: date
    date_to: date
    time_from: str = "09:00"
    time_to: str = "20:00"
    travel_minutes: int = Field(default=60, ge=0, le=1440)
    consent: bool


def add_waitlist(db: Session, tenant_id: str, data: WaitlistInput):
    ReceptionService(db, tenant_id)._catalog(data.provider_id, data.service_id)
    phone = normalize_phone(data.phone)
    try:
        valid_times = bool(
            re.fullmatch(r"\d{2}:\d{2}", data.time_from) and re.fullmatch(r"\d{2}:\d{2}", data.time_to)
        ) and time.fromisoformat(data.time_from) < time.fromisoformat(data.time_to)
    except ValueError:
        valid_times = False
    if not data.consent or not valid_times or data.date_from > data.date_to or (data.date_to - data.date_from).days > 90:
        fail(422, "INVALID_WAITLIST", "بازه معتبر و رضایت دریافت پیشنهاد لازم است.")
    if not sms_outreach_allowed(db, tenant_id, phone, "waitlist"):
        fail(409, "CONTACT_SUPPRESSED", "این شماره از دریافت پیام انصراف داده است.")
    active_key = request_digest(
        {"tenant": tenant_id, "subject": hash_phone(phone), "provider": data.provider_id, "service": data.service_id}
    )
    existing = db.scalar(select(WaitlistEntry).where(WaitlistEntry.tenant_id == tenant_id, WaitlistEntry.active_key == active_key))
    if existing:
        return {"id": existing.id, "status": existing.status, "phone_masked": mask_phone(phone), "existing": True}
    entry = WaitlistEntry(
        tenant_id=tenant_id,
        provider_id=data.provider_id,
        service_id=data.service_id,
        name_encrypted=encrypt(data.patient_name),
        phone_encrypted=encrypt(phone),
        phone_hash=hash_phone(phone),
        active_key=active_key,
        date_from=data.date_from.isoformat(),
        date_to=data.date_to.isoformat(),
        time_from=data.time_from,
        time_to=data.time_to,
        travel_minutes=data.travel_minutes,
        consent=True,
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(select(WaitlistEntry).where(WaitlistEntry.tenant_id == tenant_id, WaitlistEntry.active_key == active_key))
        if not existing:
            raise
        return {"id": existing.id, "status": existing.status, "phone_masked": mask_phone(phone), "existing": True}
    return {"id": entry.id, "status": entry.status, "phone_masked": mask_phone(phone)}


@router.post("/operations/waitlist", status_code=201)
def create_waitlist(data: WaitlistInput, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    return add_waitlist(db, actor.tenant_id, data)


@router.get("/operations/waitlist")
def waitlist(actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    return [
        {
            "id": r.id,
            "provider_id": r.provider_id,
            "service_id": r.service_id,
            "patient_name": decrypt(r.name_encrypted),
            "phone_masked": mask_phone(decrypt(r.phone_encrypted)),
            "date_from": r.date_from,
            "date_to": r.date_to,
            "status": r.status,
            "offer_attempts": r.offer_attempts,
        }
        for r in db.scalars(
            select(WaitlistEntry).where(WaitlistEntry.tenant_id == actor.tenant_id).order_by(WaitlistEntry.created_at).limit(200)
        )
    ]


class OfferInput(StrictModel):
    slot_id: str = Field(max_length=3000)


def offer_waitlist(db: Session, tenant_id: str, slot_id: str) -> dict:
    service = ReceptionService(db, tenant_id, "waitlist")
    tenant, provider, catalog, start, _end = service._decode_slot(slot_id)
    local = start.astimezone(ZoneInfo(tenant.timezone))
    now = now_utc()
    rows = db.scalars(
        select(WaitlistEntry)
        .where(
            WaitlistEntry.tenant_id == tenant_id,
            WaitlistEntry.provider_id == provider.id,
            WaitlistEntry.service_id == catalog.id,
            WaitlistEntry.status == "WAITING",
            WaitlistEntry.consent.is_(True),
            WaitlistEntry.date_from <= local.date().isoformat(),
            WaitlistEntry.date_to >= local.date().isoformat(),
            WaitlistEntry.offer_attempts < 3,
        )
        .order_by(WaitlistEntry.created_at)
        .with_for_update()
    ).all()
    entry = next(
        (
            r
            for r in rows
            if r.time_from <= local.strftime("%H:%M") < r.time_to
            and start >= now + timedelta(minutes=r.travel_minutes)
            and (r.last_offered_at is None or r.last_offered_at < now - timedelta(hours=24))
            and sms_outreach_allowed(db, tenant_id, decrypt(r.phone_encrypted), "waitlist")
        ),
        None,
    )
    if entry is None:
        return {"status": "NO_ELIGIBLE_CANDIDATE"}
    if next_permitted_time(tenant, now) > now + timedelta(seconds=1):
        return {"status": "QUIET_HOURS"}
    offer_id, token = uid(), secrets.token_urlsafe(32)
    hold = service.hold(slot_id, "waitlist:" + offer_id)
    # The authoritative hold exists before any outbound offer. If a crash occurs
    # here its short TTL releases it; no caller receives an unreserved promise.
    changed = db.execute(
        update(WaitlistEntry)
        .where(
            WaitlistEntry.id == entry.id,
            WaitlistEntry.tenant_id == tenant_id,
            WaitlistEntry.status == "WAITING",
            WaitlistEntry.consent.is_(True),
        )
        .values(status="OFFERED", offer_attempts=WaitlistEntry.offer_attempts + 1, last_offered_at=now)
    )
    if changed.rowcount != 1:
        db.rollback()
        db.execute(
            update(SlotHold)
            .where(SlotHold.tenant_id == tenant_id, SlotHold.id == hold["id"], SlotHold.status == "HELD")
            .values(status="RELEASED")
        )
        db.execute(
            delete(Occupancy).where(Occupancy.tenant_id == tenant_id, Occupancy.owner_type == "hold", Occupancy.owner_id == hold["id"])
        )
        db.commit()
        fail(409, "WAITLIST_ALREADY_OFFERED", "پیشنهاد دیگری برای این فرد در جریان است.")
    offer = WaitlistOffer(
        id=offer_id,
        tenant_id=tenant_id,
        entry_id=entry.id,
        hold_id=hold["id"],
        slot_id=slot_id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        token_encrypted=encrypt(token),
        expires_at=datetime.fromisoformat(hold["expires_at"].replace("Z", "+00:00")),
    )
    db.add(offer)
    enqueue(
        db,
        tenant_id=tenant_id,
        recipient_encrypted=entry.phone_encrypted,
        purpose="waitlist",
        template="waitlist_offer_v1",
        payload={"offer_id": offer.id},
        dedupe_key="waitlist:" + offer.id,
    )
    audit(db, tenant_id, "waitlist", "waitlist.offered", "offer", offer.id)
    db.commit()
    return {
        "id": offer.id,
        "status": offer.status,
        "expires_at": iso(offer.expires_at),
        "entry_id": entry.id,
        "accept_token": token,
        **offer_payment_details(db, offer),
    }


@router.post("/operations/waitlist/offer")
def make_offer(data: OfferInput, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    return offer_waitlist(db, actor.tenant_id, data.slot_id)


class AcceptOfferInput(StrictModel):
    token: str = Field(min_length=20, max_length=200)
    confirmed: bool
    payment_terms_version: int | None = Field(default=None, ge=0)
    payment_terms_accepted: bool = False


def accept_offer(
    db: Session,
    offer_id: str,
    token: str,
    confirmed: bool,
    actor_id: str = "caller",
    payment_terms_version: int | None = None,
    payment_terms_accepted: bool = False,
) -> dict:
    tenant_id = db.scalar(
        select(WaitlistOffer.tenant_id).where(
            WaitlistOffer.id == offer_id, WaitlistOffer.token_hash == hashlib.sha256(token.encode()).hexdigest()
        )
    )
    if tenant_id is None:
        fail(404, "NOT_FOUND", "پیشنهاد پیدا نشد.")
    lock_tenant(db, tenant_id)
    offer = db.scalar(
        select(WaitlistOffer)
        .where(WaitlistOffer.id == offer_id, WaitlistOffer.token_hash == hashlib.sha256(token.encode()).hexdigest())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not offer:
        fail(404, "NOT_FOUND", "پیشنهاد پیدا نشد.")
    service = ReceptionService(db, offer.tenant_id, "waitlist-accept")
    if offer.appointment_id:
        return service.appointment_dict(service.get_appointment(offer.appointment_id))
    if offer.status != "OFFERED" or offer.expires_at <= now_utc() or confirmed is not True:
        fail(409, "OFFER_EXPIRED", "پیشنهاد منقضی شده یا تایید نشده است.")
    entry = db.get(WaitlistEntry, offer.entry_id)
    if (
        not entry
        or entry.tenant_id != offer.tenant_id
        or not entry.consent
        or entry.status != "OFFERED"
        or not sms_outreach_allowed(db, offer.tenant_id, decrypt(entry.phone_encrypted), "waitlist")
    ):
        fail(409, "OFFER_NOT_ELIGIBLE", "این پیشنهاد دیگر فعال نیست.")
    booking = service.create_appointment(
        offer.slot_id,
        decrypt(entry.name_encrypted),
        decrypt(entry.phone_encrypted),
        "waitlist-accept:" + offer.id,
        True,
        hold_id=offer.hold_id,
        session_id="waitlist:" + offer.id,
        reminder_opt_in=False,
        payment_terms_version=payment_terms_version,
        payment_terms_accepted=payment_terms_accepted,
    )
    offer.appointment_id, offer.status = booking["id"], "ACCEPTED"
    entry.status, entry.active_key = "BOOKED", None
    audit(db, offer.tenant_id, actor_id, "waitlist.accepted", "offer", offer.id, appointment_id=booking["id"])
    db.commit()
    return booking


@router.post("/public/waitlist/{offer_id}/accept")
def public_accept_offer(offer_id: str, data: AcceptOfferInput, db: Session = Depends(get_db)):
    return accept_offer(
        db,
        offer_id,
        data.token,
        data.confirmed,
        payment_terms_version=data.payment_terms_version,
        payment_terms_accepted=data.payment_terms_accepted,
    )


def offer_payment_details(db: Session, offer: WaitlistOffer) -> dict:
    """Safe readback only; current policy is still checked at atomic booking."""
    from .payment_policy import public_payment_policy, public_snapshot

    if offer.appointment_id:
        booking = db.scalar(select(Appointment).where(Appointment.id == offer.appointment_id, Appointment.tenant_id == offer.tenant_id))
        if booking:
            return {
                "deposit_toman": booking.deposit_toman,
                "price_toman": booking.price_toman,
                "payment_terms": public_snapshot(booking.payment_terms_snapshot) if booking.payment_terms_snapshot else None,
            }
    entry = db.scalar(select(WaitlistEntry).where(WaitlistEntry.id == offer.entry_id, WaitlistEntry.tenant_id == offer.tenant_id))
    catalog = db.scalar(select(Service).where(Service.id == entry.service_id, Service.tenant_id == offer.tenant_id)) if entry else None
    if catalog is None:
        fail(404, "NOT_FOUND", "خدمت این پیشنهاد پیدا نشد.")
    return {
        "deposit_toman": catalog.deposit_toman,
        "price_toman": catalog.price_toman,
        "payment_terms": public_payment_policy(db, offer.tenant_id) if catalog.deposit_toman else None,
    }


def active_offer_view(db: Session, offer: WaitlistOffer) -> dict:
    entry = db.scalar(select(WaitlistEntry).where(WaitlistEntry.id == offer.entry_id, WaitlistEntry.tenant_id == offer.tenant_id))
    hold = db.scalar(select(SlotHold).where(SlotHold.id == offer.hold_id, SlotHold.tenant_id == offer.tenant_id))
    if (
        offer.status != "OFFERED"
        or offer.expires_at <= now_utc()
        or not entry
        or entry.status != "OFFERED"
        or not entry.consent
        or not hold
        or hold.status != "HELD"
        or hold.expires_at <= now_utc()
        or not sms_outreach_allowed(db, offer.tenant_id, decrypt(entry.phone_encrypted), "waitlist")
    ):
        fail(409, "OFFER_EXPIRED", "پیشنهاد فعال نیست؛ برای زمان تازه با پذیرش هماهنگ کنید.")
    tenant = db.get(Tenant, offer.tenant_id)
    return {
        "id": offer.id,
        "status": offer.status,
        "expires_at": iso(offer.expires_at),
        "display": jalali_label(hold.start_at, tenant.timezone),
        **offer_payment_details(db, offer),
    }


class OfferViewInput(StrictModel):
    token: str = Field(min_length=20, max_length=200)


@router.post("/public/waitlist/{offer_id}/view")
def public_offer_view(offer_id: str, data: OfferViewInput, db: Session = Depends(get_db)):
    offer = db.scalar(
        select(WaitlistOffer).where(
            WaitlistOffer.id == offer_id, WaitlistOffer.token_hash == hashlib.sha256(data.token.encode()).hexdigest()
        )
    )
    if offer is None:
        fail(404, "NOT_FOUND", "پیشنهاد پیدا نشد.")
    return active_offer_view(db, offer)


@router.get("/operations/waitlist/offers/{offer_id}/terms")
def staff_offer_terms(offer_id: str, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    offer = db.scalar(select(WaitlistOffer).where(WaitlistOffer.id == offer_id, WaitlistOffer.tenant_id == actor.tenant_id))
    if offer is None:
        fail(404, "NOT_FOUND", "پیشنهاد پیدا نشد.")
    return active_offer_view(db, offer)


@router.get("/operations/waitlist/offers")
def list_offers(actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    offers = list(
        db.scalars(
            select(WaitlistOffer).where(WaitlistOffer.tenant_id == actor.tenant_id).order_by(WaitlistOffer.created_at.desc()).limit(200)
        )
    )
    result = []
    for row in offers:
        entry, hold = db.get(WaitlistEntry, row.entry_id), db.get(SlotHold, row.hold_id)
        result.append(
            {
                "id": row.id,
                "entry_id": row.entry_id,
                "status": row.status,
                "expires_at": iso(row.expires_at),
                "appointment_id": row.appointment_id,
                "patient_name": decrypt(entry.name_encrypted),
                "phone_masked": mask_phone(decrypt(entry.phone_encrypted)),
                "start_at": iso(hold.start_at),
                "display": jalali_label(hold.start_at),
                "created_at": iso(row.created_at),
                **offer_payment_details(db, row),
            }
        )
    return result


class StaffAcceptOffer(StrictModel):
    confirmed: bool
    payment_terms_version: int | None = Field(default=None, ge=0)
    payment_terms_accepted: bool = False


@router.post("/operations/waitlist/offers/{offer_id}/accept")
def staff_accept_offer(offer_id: str, data: StaffAcceptOffer, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    offer = db.scalar(select(WaitlistOffer).where(WaitlistOffer.id == offer_id, WaitlistOffer.tenant_id == actor.tenant_id))
    if not offer:
        fail(404, "NOT_FOUND", "پیشنهاد پیدا نشد.")
    return accept_offer(
        db,
        offer.id,
        decrypt(offer.token_encrypted),
        data.confirmed,
        actor.id,
        payment_terms_version=data.payment_terms_version,
        payment_terms_accepted=data.payment_terms_accepted,
    )


class PaymentCreateInput(StrictModel):
    appointment_id: str = Field(max_length=60)


async def create_payment(db: Session, tenant_id: str, appointment_id: str, gateway=None) -> dict:
    from .models_ext import AppointmentImpact
    from .payment_policy import booking_payment_terms, gateway_for_intent

    lock_tenant(db, tenant_id)
    service = ReceptionService(db, tenant_id, "payment")
    booking = service.get_appointment(appointment_id)
    if db.scalar(
        select(AppointmentImpact.id)
        .where(
            AppointmentImpact.tenant_id == tenant_id,
            AppointmentImpact.appointment_id == appointment_id,
            AppointmentImpact.state != "RESOLVED",
        )
        .limit(1)
    ):
        fail(409, "SCHEDULE_DISRUPTED", "پیش از پرداخت، اختلال برنامه باید توسط پذیرش تعیین تکلیف شود.")
    old = db.scalar(select(PaymentIntent).where(PaymentIntent.tenant_id == tenant_id, PaymentIntent.appointment_id == appointment_id))
    if old:
        return payment_dict(old)
    if booking.status != "PENDING_PAYMENT" or booking.expires_at <= now_utc():
        fail(409, "PAYMENT_NOT_REQUIRED", "این نوبت منتظر پرداخت نیست.")
    if not settings.demo_mode:
        from .models_ops import TenantPaymentPolicy

        current_policy = db.get(TenantPaymentPolicy, tenant_id)
        if current_policy is None or not current_policy.enabled:
            fail(409, "DEPOSIT_POLICY_NOT_PUBLISHED", "دریافت بیعانه این مرکز اکنون غیرفعال است؛ پذیرش باید بررسی کند.")
    snapshot = booking.payment_terms_snapshot
    if not snapshot:
        if not settings.demo_mode:
            fail(409, "PAYMENT_TERMS_NOT_CAPTURED", "این رزرو سابقه تایید شرایط و درگاه ندارد؛ پذیرش باید آن را بررسی کند.")
        snapshot = booking_payment_terms(db, tenant_id, service._catalog(booking.provider_id, booking.service_id)[1], None, False)
        booking.payment_terms_snapshot = snapshot
    intent = PaymentIntent(
        tenant_id=tenant_id,
        appointment_id=booking.id,
        amount_toman=booking.deposit_toman,
        expires_at=booking.expires_at,
        currency="TOMAN",
        gateway_currency="IRR",
        merchant_alias=snapshot["merchant_alias"],
        merchant_identity_hash=snapshot["merchant_identity_hash"],
        merchant_sandbox=snapshot["merchant_sandbox"],
        terms_version=snapshot["version"],
        terms_snapshot=dict(snapshot),
    )
    if not settings.demo_mode:
        try:
            bound = gateway_for_intent(intent)
        except ProviderError:
            fail(503, "PAYMENT_MERCHANT_UNAVAILABLE", "شناسه درگاه این رزرو قابل تایید نیست؛ دوباره پرداخت نکنید و از پذیرش کمک بگیرید.")
        gateway = gateway or bound
    db.add(intent)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return payment_dict(
            db.scalar(select(PaymentIntent).where(PaymentIntent.tenant_id == tenant_id, PaymentIntent.appointment_id == appointment_id))
        )
    if settings.demo_mode:
        intent.authority, intent.status = "DEMO" + secrets.token_hex(16), "DEMO_PENDING"
        db.commit()
        return payment_dict(intent)
    callback_base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
    synthetic = intent.merchant_sandbox or intent.terms_snapshot.get("synthetic", False) or getattr(gateway, "synthetic", False)
    started = monotonic()
    try:
        result = await gateway.create(intent.amount_toman, callback_base + "/api/v1/payments/callback", "بیعانه نوبت پذیرش")
        from .provider_control import observe_activity
        observe_activity(db, tenant_id, "payment_primary", "request", outcome="succeeded", code="PAYMENT_REQUEST_ACCEPTED",
            performed_io=True, synthetic=synthetic, latency_ms=int((monotonic() - started) * 1000))
        intent.authority, intent.payment_url, intent.status = result["authority"], result["url"], "PENDING"
    except ProviderError as exc:
        observe_adapter_failure(db, tenant_id, "payment_primary", "request", exc,
            synthetic=synthetic, latency_ms=int((monotonic() - started) * 1000))
        intent.status = "UNKNOWN" if exc.unknown_outcome else "FAILED"
        audit(db, tenant_id, "payment", "payment.create_failed", "payment", intent.id, code=exc.code)
    db.commit()
    return payment_dict(intent)


def payment_dict(row: PaymentIntent):
    from .payment_policy import public_snapshot

    return {
        "id": row.id,
        "appointment_id": row.appointment_id,
        "amount_toman": row.amount_toman,
        "status": row.status,
        "payment_url": row.payment_url,
        "expires_at": iso(row.expires_at),
        "provider_reference": row.provider_reference,
        "currency": row.currency,
        "payment_terms": public_snapshot(row.terms_snapshot),
    }


@router.post("/operations/payments")
async def payment_link(data: PaymentCreateInput, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    if not (has_permission(actor, "billing:write") or has_permission(actor, "appointment:write")):
        fail(403, "PERMISSION_REQUIRED", "Payment links require billing or appointment-write access.")
    return await create_payment(db, actor.tenant_id, data.appointment_id)


@router.get("/operations/payments/appointments")
def payment_appointments(status: str | None = None, actor: Actor = Depends(require_permissions("billing:read")), db: Session = Depends(get_db)):
    if status and status not in {"PENDING_PAYMENT", "CONFIRMED", "ATTENDED", "CANCELED", "EXPIRED", "NO_SHOW", "PENDING_STAFF_APPROVAL"}:
        fail(422, "INVALID_APPOINTMENT_STATUS", "Unsupported appointment status.")
    query = select(Appointment).where(Appointment.tenant_id == actor.tenant_id, Appointment.deposit_toman > 0)
    if status:
        query = query.where(Appointment.status == status)
    return [{"id": row.id, "reference": row.reference, "deposit_toman": row.deposit_toman, "status": row.status}
        for row in db.scalars(query.order_by(Appointment.created_at.desc()).limit(250))]


@router.get("/operations/payments")
def payments(actor: Actor = Depends(require_permissions("billing:read")), db: Session = Depends(get_db)):
    return [
        {**payment_dict(p), "appointment_reference": reference}
        for p, reference in db.execute(
            select(PaymentIntent, Appointment.reference).join(Appointment, Appointment.id == PaymentIntent.appointment_id)
            .where(PaymentIntent.tenant_id == actor.tenant_id, Appointment.tenant_id == actor.tenant_id).order_by(PaymentIntent.created_at.desc()).limit(200)
        )
    ]


def settle_verified_payment(db: Session, intent: PaymentIntent, reference: str) -> dict:
    lock_tenant(db, intent.tenant_id)
    intent = db.scalar(
        select(PaymentIntent)
        .where(PaymentIntent.id == intent.id, PaymentIntent.tenant_id == intent.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if intent.status in {"SETTLED", "LATE_REQUIRES_REFUND", "PARTIALLY_REFUNDED", "REFUNDED"}:
        if intent.provider_reference != reference:
            fail(409, "PAYMENT_REFERENCE_MISMATCH", "شناسه تایید پرداخت با سابقه قطعی سازگار نیست.")
        return payment_dict(intent)
    if intent.status not in {"PENDING", "DEMO_PENDING", "UNKNOWN"}:
        fail(409, "PAYMENT_STATE_INVALID", "وضعیت پرداخت نیاز به بررسی دارد.")
    service = ReceptionService(db, intent.tenant_id, "verified-gateway")
    service._expire()
    booking = service.get_appointment(intent.appointment_id, lock=True)
    intent.provider_reference, intent.settled_at = reference, now_utc()
    if (
        booking.status != "PENDING_PAYMENT"
        or booking.expires_at is None
        or booking.expires_at <= now_utc()
        or booking.start_at <= now_utc()
    ):
        intent.status = "LATE_REQUIRES_REFUND"
        db.add(
            StaffTask(
                tenant_id=intent.tenant_id,
                reason="LATE_PAYMENT_REFUND",
                priority="high",
                summary="پرداخت پس از پایان رزرو دریافت شد؛ زمان رزرو نشده و بازپرداخت باید بررسی شود.",
                appointment_id=booking.id,
            )
        )
        audit(db, intent.tenant_id, "gateway", "payment.late", "payment", intent.id, amount_toman=intent.amount_toman)
    else:
        service.settle_payment(booking.id, intent.amount_toman, reference)
        intent.status = "SETTLED"
    db.commit()
    return payment_dict(intent)


@router.get("/payments/callback")
async def payment_callback(Authority: str, Status: str, db: Session = Depends(get_db)):
    from .payment_policy import gateway_for_intent

    intent = db.scalar(select(PaymentIntent).where(PaymentIntent.authority == Authority))
    if not intent or settings.demo_mode or Authority.startswith("DEMO"):
        fail(404, "NOT_FOUND", "پرداخت پیدا نشد.")
    if Status != "OK":
        return {"status": "NOT_COMPLETED", "message": "پرداخت تکمیل نشد؛ نوبت تایید نشده است."}
    # Verification is external I/O. Release the read snapshot/connection first;
    # settle_verified_payment reacquires the tenant and current payment locks.
    amount_toman, tenant_id = intent.amount_toman, intent.tenant_id
    try:
        gateway = gateway_for_intent(intent)
    except ProviderError:
        fail(
            503,
            "PAYMENT_MERCHANT_UNAVAILABLE",
            "درگاه ثبت‌شده این پرداخت تغییر کرده یا در دسترس نیست؛ تطبیق مالی لازم است و نباید دوباره پرداخت کنید.",
        )
    synthetic = intent.merchant_sandbox or intent.terms_snapshot.get("synthetic", False) or getattr(gateway, "synthetic", False)
    db.commit()
    started = monotonic()
    try:
        result = await gateway.verify(Authority, amount_toman)
    except ProviderError as exc:
        observe_adapter_failure(db, tenant_id, "payment_primary", "verify", exc,
            synthetic=synthetic, latency_ms=int((monotonic() - started) * 1000))
        db.commit()
        fail(503, "PAYMENT_VERIFICATION_UNAVAILABLE", "نتیجه پرداخت هنوز قابل تایید نیست؛ دوباره پرداخت نکنید.")
    from .provider_control import observe_activity
    observe_activity(db, tenant_id, "payment_primary", "verify", outcome="succeeded", code="PAYMENT_VERIFIED",
        performed_io=True, synthetic=synthetic, latency_ms=int((monotonic() - started) * 1000))
    return settle_verified_payment(db, intent, result["reference"])


@router.post("/operations/payments/{payment_id}/simulate")
def simulate_payment(payment_id: str, actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    if not settings.demo_mode:
        fail(404, "NOT_FOUND", "مسیر پیدا نشد.")
    lock_tenant(db, actor.tenant_id)
    intent = db.scalar(
        select(PaymentIntent).where(PaymentIntent.id == payment_id, PaymentIntent.tenant_id == actor.tenant_id).with_for_update()
    )
    if not intent or not intent.authority or not intent.authority.startswith("DEMO"):
        fail(404, "NOT_FOUND", "پرداخت نمایشی پیدا نشد.")
    return settle_verified_payment(db, intent, "DEMO-VERIFIED-" + intent.id)


class RefundInput(StrictModel):
    amount_toman: int = Field(gt=0, le=1000000000)
    reason: str = Field(min_length=3, max_length=100)
    idempotency_key: str = Field(min_length=8, max_length=160)


def refund_reason(db: Session, row: RefundLedger) -> str:
    """Reveal staff financial notes only through the scoped authorized view.

    Older ledgers may still have a plain reason; new records keep only a
    categorical marker on the ledger and encrypt the free text in the audit.
    """
    event = db.scalar(
        select(AuditEvent).where(
            AuditEvent.tenant_id == row.tenant_id,
            AuditEvent.action == "refund.requested",
            AuditEvent.entity_type == "refund",
            AuditEvent.entity_id == row.id,
        )
    )
    encrypted = (event.details or {}).get("reason_encrypted") if event else None
    return decrypt(encrypted) if encrypted else row.reason


@router.post("/operations/payments/{payment_id}/refunds")
def request_refund(payment_id: str, data: RefundInput, actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    from .models_ext import PaymentAdjustment

    lock_tenant(db, actor.tenant_id)
    old = db.scalar(
        select(RefundLedger).where(RefundLedger.tenant_id == actor.tenant_id, RefundLedger.idempotency_key == data.idempotency_key)
    )
    if old:
        if old.payment_id != payment_id or old.amount_toman != data.amount_toman or refund_reason(db, old) != data.reason:
            fail(409, "IDEMPOTENCY_MISMATCH", "کلید تکرار با درخواست دیگری استفاده شده است.")
        return {"id": old.id, "status": old.status, "amount_toman": old.amount_toman}
    intent = db.scalar(
        select(PaymentIntent).where(PaymentIntent.id == payment_id, PaymentIntent.tenant_id == actor.tenant_id).with_for_update()
    )
    if not intent or intent.status not in {"SETTLED", "LATE_REQUIRES_REFUND", "PARTIALLY_REFUNDED"}:
        fail(409, "REFUND_NOT_ELIGIBLE", "پرداخت برای بازپرداخت قابل بررسی نیست.")
    principal_adjustments = db.scalar(
        select(func.coalesce(func.sum(PaymentAdjustment.amount_toman), 0)).where(
            PaymentAdjustment.tenant_id == actor.tenant_id, PaymentAdjustment.payment_id == intent.id
        )
    )
    refundable_ceiling = max(0, intent.amount_toman + principal_adjustments)
    reservation = db.execute(
        update(PaymentIntent)
        .where(
            PaymentIntent.id == intent.id,
            PaymentIntent.tenant_id == actor.tenant_id,
            PaymentIntent.refund_reserved_toman + data.amount_toman <= refundable_ceiling,
        )
        .values(refund_reserved_toman=PaymentIntent.refund_reserved_toman + data.amount_toman)
    )
    if reservation.rowcount != 1:
        fail(409, "REFUND_EXCEEDS_PAYMENT", "مبلغ بازپرداخت از مبلغ پرداخت‌شده بیشتر است.")
    row = RefundLedger(
        tenant_id=actor.tenant_id,
        payment_id=intent.id,
        amount_toman=data.amount_toman,
        idempotency_key=data.idempotency_key,
        reason="staff_request",
    )
    db.add(row)
    db.flush()
    db.add(
        StaffTask(
            tenant_id=actor.tenant_id,
            reason="REFUND_EXECUTION",
            summary="درخواست بازپرداخت ثبت شد؛ اجرای واقعی و مدرک درگاه لازم است.",
            appointment_id=intent.appointment_id,
        )
    )
    audit(
        db,
        actor.tenant_id,
        actor.id,
        "refund.requested",
        "refund",
        row.id,
        amount_toman=row.amount_toman,
        reason_encrypted=encrypt(data.reason),
    )
    db.commit()
    return {"id": row.id, "status": row.status, "amount_toman": row.amount_toman, "message": "درخواست ثبت شد؛ پولی خودکار منتقل نشده است."}


class RefundEvidence(StrictModel):
    provider_reference: str = Field(min_length=6, max_length=120)
    confirmed: bool


@router.get("/operations/refunds")
def refunds(actor: Actor = Depends(require_permissions("billing:read")), db: Session = Depends(get_db)):
    return [
        {
            "id": row.id,
            "payment_id": row.payment_id,
            "amount_toman": row.amount_toman,
            "reason": refund_reason(db, row),
            "status": row.status,
            "provider_reference": row.provider_reference,
            "created_at": iso(row.created_at),
            "completed_at": iso(row.completed_at),
        }
        for row in db.scalars(
            select(RefundLedger).where(RefundLedger.tenant_id == actor.tenant_id).order_by(RefundLedger.created_at.desc()).limit(200)
        )
    ]


@router.post("/operations/refunds/{refund_id}/record")
def record_refund(refund_id: str, data: RefundEvidence, actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    # This also serializes distinct partial refunds and transfer reference use.
    lock_tenant(db, actor.tenant_id)
    row = db.scalar(
        select(RefundLedger)
        .where(RefundLedger.id == refund_id, RefundLedger.tenant_id == actor.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not row or data.confirmed is not True:
        fail(422, "REFUND_EVIDENCE_REQUIRED", "تایید اجرای واقعی و شناسه درگاه لازم است.")
    if row.status == "COMPLETED":
        if row.provider_reference != data.provider_reference:
            fail(409, "REFUND_EVIDENCE_MISMATCH", "شناسه بازپرداخت قبلاً با مدرک دیگری ثبت شده است.")
        return {"id": row.id, "status": row.status}
    duplicate = db.scalar(
        select(RefundLedger.id).where(
            RefundLedger.tenant_id == actor.tenant_id, RefundLedger.provider_reference == data.provider_reference, RefundLedger.id != row.id
        )
    )
    if duplicate:
        fail(409, "REFUND_REFERENCE_REUSED", "این شناسه انتقال قبلاً برای بازپرداخت دیگری ثبت شده است.")
    if row.status not in {"REQUESTED", "RECONCILING", "RECONCILIATION_REQUIRED"}:
        fail(409, "REFUND_STATE_INVALID", "وضعیت بازپرداخت برای ثبت مدرک معتبر نیست.")
    row.status, row.provider_reference, row.completed_at = "COMPLETED", data.provider_reference, now_utc()
    intent = db.scalar(
        select(PaymentIntent)
        .where(PaymentIntent.id == row.payment_id, PaymentIntent.tenant_id == actor.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    db.flush()
    total = db.scalar(
        select(func.coalesce(func.sum(RefundLedger.amount_toman), 0)).where(
            RefundLedger.payment_id == intent.id, RefundLedger.tenant_id == actor.tenant_id, RefundLedger.status == "COMPLETED"
        )
    )
    intent.status = "REFUNDED" if total == intent.amount_toman else "PARTIALLY_REFUNDED"
    from .operations_extensions import resolve_refund_tasks

    resolve_refund_tasks(db, actor.tenant_id, intent)
    audit(db, actor.tenant_id, actor.id, "refund.recorded_by_staff", "refund", row.id, amount_toman=row.amount_toman)
    db.commit()
    return {"id": row.id, "status": row.status, "payment_status": intent.status}


@router.get("/operations/integrations")
def integrations(actor: Actor = Depends(require_permissions("integration:read"))):
    from .payment_policy import configured_merchant

    try:
        configured_merchant(actor.tenant_id)
        merchant_configured = True
    except ProviderError:
        merchant_configured = False

    def item(identifier, name, configured, description, *, demo_disables=False, **extra):
        return {
            "id": identifier,
            "name": name,
            "configured": bool(configured),
            "status": (
                "demo_disabled"
                if settings.demo_mode and configured and demo_disables
                else "configured_unverified"
                if configured
                else "not_configured"
            ),
            "description": description,
            **extra,
        }

    return {
        "mode": "demo" if settings.demo_mode else "configured",
        "items": [
            {
                "id": "calendar",
                "name": "تقویم داخلی",
                "configured": True,
                "status": "active",
                "description": "ثبت نوبت تراکنشی در پایگاه داده همین مرکز.",
            },
            item(
                "speech",
                "گفتار فارسی",
                SpeechGateway().configured,
                "درگاه STT/TTS؛ کیفیت تماس و مجوز پردازش باید روی محیط واقعی تایید شود.",
            ),
            item(
                "sms",
                "پیامک کاوه‌نگار",
                KavenegarSMS().configured,
                "کلید و رضایت سرویس لازم است؛ ارسال با تحویل تفاوت دارد.",
                demo_disables=True,
            ),
            item(
                "payments",
                "بیعانه زرین‌پال",
                merchant_configured,
                "درگاه باید به همین مرکز متصل و شرایط منتشر باشد؛ فقط تایید سمت سرور، پرداخت را قطعی می‌کند.",
                demo_disables=True,
            ),
            item(
                "livekit",
                "تماس WebRTC و SIP",
                enabled("LIVEKIT_APPROVED")
                and bool(os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY") and os.getenv("LIVEKIT_API_SECRET")),
                "پیکربندی رسانه به معنی تایید اتصال اپراتور تلفن نیست.",
            ),
            item(
                "audiosocket",
                "Asterisk AudioSocket",
                bool(os.getenv("MEDIA_API_TOKEN")),
                "پل PCM و ثبت نشست؛ نیازمند PBX و شبکه مجاز واقعی.",
            ),
            item(
                "calendar_partner",
                "تقویم شریک",
                enabled("CALENDAR_PARTNER_APPROVED"),
                "قرارداد اتصال رسمی لازم است؛ دسترسی نوشتن پلتفرم‌ها فرض نشده است.",
            ),
        ],
    }


@router.get("/operations/privacy")
def privacy_summary(actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, actor.tenant_id)
    rows = db.execute(
        select(ConsentGrant.purpose, ConsentGrant.granted, func.count())
        .where(ConsentGrant.tenant_id == actor.tenant_id)
        .group_by(ConsentGrant.purpose, ConsentGrant.granted)
    ).all()
    processors = []
    if SpeechGateway().configured:
        processors.append(
            {
                "name": "configured_speech_gateway",
                "purpose": "live_speech",
                "region": os.getenv("SPEECH_PROCESSOR_REGION", "requires_operator_verification"),
            }
        )
    if KavenegarSMS().configured:
        processors.append({"name": "Kavenegar", "purpose": "transactional_sms", "region": "requires_contract_verification"})
    return {
        "recording_default": False,
        "training_default": False,
        "retention_days": tenant.retention_days,
        "processors": processors,
        "consents": [{"purpose": purpose, "granted": granted, "count": count} for purpose, granted, count in rows],
        "audio_storage": "disabled",
        "deletion_policy": "conversation data is erased; active booking evidence requires controlled review",
    }


class SubjectInput(StrictModel):
    phone: str = Field(max_length=30)


class DeleteSubjectInput(SubjectInput):
    confirm: bool


class RevokeConsentInput(SubjectInput):
    purposes: list[Literal["reminder", "waitlist", "followup"]] = Field(
        default_factory=lambda: ["reminder", "waitlist", "followup"], min_length=1, max_length=3
    )


def revoke_outreach(db: Session, tenant_id: str, phone: str, purposes: list[str], actor_id: str, *, commit: bool = True) -> dict:
    from .models_voice import CallSession
    from .models_outreach import FollowupEnrollment

    phone = normalize_phone(phone)
    subject = hash_phone(phone)
    selected = sorted(set(purposes))
    if not selected or any(p not in {"reminder", "waitlist", "followup"} for p in selected):
        fail(422, "INVALID_CONSENT_PURPOSE", "هدف انصراف معتبر نیست.")
    lock_tenant(db, tenant_id)
    for purpose in selected:
        existing = db.scalar(
            select(OutreachSuppression.id).where(
                OutreachSuppression.tenant_id == tenant_id,
                OutreachSuppression.subject_hash == subject,
                OutreachSuppression.purpose == purpose,
            )
        )
        if existing is None:
            db.add(OutreachSuppression(tenant_id=tenant_id, subject_hash=subject, purpose=purpose))
    call_ids = list(db.scalars(select(CallSession.id).where(CallSession.tenant_id == tenant_id, CallSession.phone_hash == subject)))
    grants = db.execute(
        update(ConsentGrant)
        .where(
            ConsentGrant.tenant_id == tenant_id,
            ConsentGrant.subject_hash.in_([subject] + ["session:" + i for i in call_ids]),
            ConsentGrant.purpose.in_(selected),
            ConsentGrant.granted.is_(True),
        )
        .values(granted=False)
    ).rowcount
    if "reminder" in selected:
        db.execute(
            update(Appointment).where(Appointment.tenant_id == tenant_id, Appointment.phone_hash == subject).values(reminder_opt_in=False)
        )
    if "followup" in selected:
        db.execute(
            update(FollowupEnrollment)
            .where(
                FollowupEnrollment.tenant_id == tenant_id, FollowupEnrollment.subject_hash == subject, FollowupEnrollment.status == "ACTIVE"
            )
            .values(status="REVOKED")
        )
    entries_canceled = released_holds = 0
    if "waitlist" in selected:
        entries = list(
            db.scalars(
                select(WaitlistEntry).where(WaitlistEntry.tenant_id == tenant_id, WaitlistEntry.phone_hash == subject).with_for_update()
            )
        )
        for entry in entries:
            entry.consent = False
            if entry.status in {"WAITING", "OFFERED"}:
                entry.status, entry.active_key = "WITHDRAWN", None
                entries_canceled += 1
            for offer in db.scalars(
                select(WaitlistOffer)
                .where(WaitlistOffer.tenant_id == tenant_id, WaitlistOffer.entry_id == entry.id, WaitlistOffer.status == "OFFERED")
                .with_for_update()
            ):
                offer.status, offer.token_encrypted = "WITHDRAWN", encrypt("withdrawn")
                offer.token_hash = hashlib.sha256(("withdrawn:" + offer.id).encode()).hexdigest()
                released_holds += db.execute(
                    update(SlotHold)
                    .where(SlotHold.tenant_id == tenant_id, SlotHold.id == offer.hold_id, SlotHold.status == "HELD")
                    .values(status="RELEASED")
                ).rowcount
                db.execute(
                    delete(Occupancy).where(
                        Occupancy.tenant_id == tenant_id, Occupancy.owner_type == "hold", Occupancy.owner_id == offer.hold_id
                    )
                )
    suppressed_messages = dispatches_inflight = 0
    for msg in db.scalars(
        select(MessageOutbox)
        .where(
            MessageOutbox.tenant_id == tenant_id,
            MessageOutbox.purpose.in_(selected),
            MessageOutbox.status.in_(["QUEUED", "FAILED", "SENDING"]),
        )
        .with_for_update()
    ):
        recipient = decrypt(msg.recipient_encrypted)
        if recipient == "deleted" or hash_phone(recipient) != subject:
            continue
        if msg.status == "SENDING":
            dispatches_inflight += 1
        else:
            msg.status, msg.locked_until, msg.last_error_code = "SUPPRESSED", None, "CONSENT_WITHDRAWN"
            suppressed_messages += 1
    audit(
        db,
        tenant_id,
        actor_id,
        "consent.outreach_revoked",
        "subject",
        subject,
        purposes=selected,
        suppressed_messages=suppressed_messages,
        released_holds=released_holds,
        dispatches_inflight=dispatches_inflight,
    )
    if commit:
        db.commit()
    return {
        "status": "REVOKED",
        "purposes": selected,
        "phone_masked": mask_phone(phone),
        "revoked_grants": grants,
        "suppressed_messages": suppressed_messages,
        "canceled_waitlist_entries": entries_canceled,
        "released_holds": released_holds,
        "dispatches_inflight": dispatches_inflight,
        "dispatch_boundary": "Already dispatched or in-flight provider messages cannot be recalled.",
    }


@router.post("/operations/consents/revoke")
def revoke_consent(data: RevokeConsentInput, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    return revoke_outreach(db, actor.tenant_id, data.phone, data.purposes, actor.id)


def export_subject(db: Session, tenant_id: str, phone: str) -> dict:
    from .models_voice import CallSession, VoiceTurn
    from .models_ext import CorrectionRecord

    subject = hash_phone(phone)
    service = ReceptionService(db, tenant_id)
    calls = list(db.scalars(select(CallSession).where(CallSession.tenant_id == tenant_id, CallSession.phone_hash == subject)))
    bookings = list(db.scalars(select(Appointment).where(Appointment.tenant_id == tenant_id, Appointment.phone_hash == subject)))
    tasks = list(
        db.scalars(
            select(StaffTask).where(
                StaffTask.tenant_id == tenant_id,
                StaffTask.appointment_id.in_([booking.id for booking in bookings]) | StaffTask.call_id.in_([call.id for call in calls]),
            )
        )
    )
    return {
        "subject_hash": subject,
        "exported_at": iso(now_utc()),
        "appointments": [service.appointment_dict(row) for row in bookings],
        "waitlist": [
            {"id": r.id, "name": decrypt(r.name_encrypted), "date_from": r.date_from, "date_to": r.date_to, "status": r.status}
            for r in db.scalars(select(WaitlistEntry).where(WaitlistEntry.tenant_id == tenant_id, WaitlistEntry.phone_hash == subject))
        ],
        "consents": [
            {"purpose": r.purpose, "granted": r.granted, "policy_version": r.policy_version, "created_at": iso(r.created_at)}
            for r in db.scalars(
                select(ConsentGrant).where(
                    ConsentGrant.tenant_id == tenant_id, ConsentGrant.subject_hash.in_([subject] + ["session:" + c.id for c in calls])
                )
            )
        ],
        "calls": [
            {
                "id": c.id,
                "started_at": iso(c.started_at),
                "ended_at": iso(c.ended_at),
                "state": c.state,
                "context": json.loads(decrypt(c.context_encrypted)),
                "turns": [
                    json.loads(decrypt(t.result_encrypted))
                    for t in db.scalars(select(VoiceTurn).where(VoiceTurn.tenant_id == tenant_id, VoiceTurn.call_id == c.id))
                ],
            }
            for c in calls
        ],
        "recordings": [],
        "staff_tasks": [
            {
                "id": task.id,
                "appointment_id": task.appointment_id,
                "call_id": task.call_id,
                "status": task.status,
                "reason": task.reason,
                "summary": task.summary,
                "resolution": task.resolution,
                "notes": [
                    {"created_at": iso(event.created_at), "text": decrypt(event.details["reason_encrypted"])}
                    for event in db.scalars(
                        select(AuditEvent)
                        .where(AuditEvent.tenant_id == tenant_id, AuditEvent.entity_type == "task", AuditEvent.entity_id == task.id)
                        .order_by(AuditEvent.created_at)
                    )
                    if event.details.get("reason_encrypted")
                ],
            }
            for task in tasks
        ],
        "corrections": [
            {
                "appointment_id": row.appointment_id,
                "created_at": iso(row.created_at),
                "reason": decrypt(row.reason_encrypted),
                "changes": json.loads(decrypt(row.changes_encrypted)),
            }
            for row in db.scalars(
                select(CorrectionRecord).where(
                    CorrectionRecord.tenant_id == tenant_id,
                    (CorrectionRecord.subject_hash == subject) | (CorrectionRecord.previous_subject_hash == subject),
                )
            )
        ],
        "outreach_suppressions": [
            {"purpose": row.purpose, "created_at": iso(row.created_at)}
            for row in db.scalars(
                select(OutreachSuppression).where(OutreachSuppression.tenant_id == tenant_id, OutreachSuppression.subject_hash == subject)
            )
        ],
        "note": "No raw audio is stored by the default deployment. External backups and approved research exports need their own erasure reconciliation.",
    }


@router.post("/operations/privacy/export")
def privacy_export(data: SubjectInput, actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    result = export_subject(db, actor.tenant_id, data.phone)
    audit(db, actor.tenant_id, actor.id, "privacy.exported", "subject", result["subject_hash"])
    db.commit()
    return result


def delete_subject(db: Session, tenant_id: str, phone: str, actor_id: str = "privacy") -> dict:
    from .models_voice import CallSession, MediaRegistration, VerificationChallenge, VoiceTurn
    from .voice import release_holds
    from .models_ext import CorrectionRecord
    from .models_outreach import AppointmentResponse, FollowupEnrollment

    subject = hash_phone(phone)
    lock_tenant(db, tenant_id)
    from .privacy_controls import erase_subject_extensions
    extension_erasure = erase_subject_extensions(db, tenant_id, subject)
    bookings = list(db.scalars(select(Appointment).where(Appointment.tenant_id == tenant_id, Appointment.phone_hash == subject)))
    active = [b for b in bookings if b.status in {"CONFIRMED", "PENDING_PAYMENT", "PENDING_STAFF_APPROVAL"} and b.start_at > now_utc()]
    existing = db.scalar(select(PrivacyTombstone).where(PrivacyTombstone.tenant_id == tenant_id, PrivacyTombstone.subject_hash == subject))
    if not existing:
        db.add(PrivacyTombstone(tenant_id=tenant_id, subject_hash=subject, retained_business_records=bool(active)))
    elif active:
        existing.retained_business_records = True
    calls = list(db.scalars(select(CallSession).where(CallSession.tenant_id == tenant_id, CallSession.phone_hash == subject)))
    linked_tasks = list(
        db.scalars(
            select(StaffTask).where(
                StaffTask.tenant_id == tenant_id,
                StaffTask.appointment_id.in_([booking.id for booking in bookings]) | StaffTask.call_id.in_([call.id for call in calls]),
            )
        )
    )
    for task in linked_tasks:
        # Keep operational ownership/status and categorical reason; remove free
        # text that may repeat the subject's identity or conversation content.
        task.summary = "متن درخواست به‌دلیل حذف داده شخصی پاک شد؛ وضعیت عملیاتی حفظ شده است."
        if task.resolution:
            task.resolution = "متن نتیجه به‌دلیل حذف داده شخصی پاک شد."
        for event in db.scalars(
            select(AuditEvent).where(AuditEvent.tenant_id == tenant_id, AuditEvent.entity_type == "task", AuditEvent.entity_id == task.id)
        ):
            details = dict(event.details)
            for key in ("reason", "note", "resolution", "summary", "reason_encrypted", "note_encrypted"):
                if key in details:
                    details[key] = encrypt("privacy_erasure") if key.endswith("_encrypted") else "privacy_erasure"
            event.details = details
    for call in calls:
        release_holds(db, call)
        db.execute(delete(VoiceTurn).where(VoiceTurn.tenant_id == tenant_id, VoiceTurn.call_id == call.id))
        db.execute(
            delete(VerificationChallenge).where(VerificationChallenge.tenant_id == tenant_id, VerificationChallenge.call_id == call.id)
        )
        db.execute(delete(MediaRegistration).where(MediaRegistration.tenant_id == tenant_id, MediaRegistration.call_id == call.id))
        call.context_encrypted, call.phone_hash, call.policy_snapshot = encrypt("{}"), None, {}
        call.token_hash = hashlib.sha256(("deleted:" + call.id).encode()).hexdigest()
        call.ended_at, call.state, call.lease_token, call.lease_until = now_utc(), "DELETED", None, None
        call.recording_consent, call.training_consent = False, False
    db.execute(
        delete(VerificationChallenge).where(VerificationChallenge.tenant_id == tenant_id, VerificationChallenge.phone_hash == subject)
    )
    db.execute(
        update(ConsentGrant)
        .where(ConsentGrant.tenant_id == tenant_id, ConsentGrant.subject_hash.in_([subject] + ["session:" + c.id for c in calls]))
        .values(granted=False)
    )
    db.execute(
        update(CorrectionRecord)
        .where(
            CorrectionRecord.tenant_id == tenant_id,
            (CorrectionRecord.subject_hash == subject) | (CorrectionRecord.previous_subject_hash == subject),
        )
        .values(reason_encrypted=encrypt("privacy_erasure"), changes_encrypted=encrypt("{}"))
    )
    db.execute(
        update(FollowupEnrollment)
        .where(FollowupEnrollment.tenant_id == tenant_id, FollowupEnrollment.subject_hash == subject)
        .values(status="REVOKED")
    )
    for response in db.scalars(
        select(AppointmentResponse).where(
            AppointmentResponse.tenant_id == tenant_id, AppointmentResponse.appointment_id.in_([booking.id for booking in bookings])
        )
    ):
        response.status, response.token_encrypted = "REVOKED", encrypt("deleted")
        response.token_hash = hashlib.sha256(("deleted:" + response.id).encode()).hexdigest()
    for booking in bookings:
        booking.reminder_opt_in = False
        if booking not in active:
            booking.patient_name_encrypted, booking.phone_encrypted = encrypt("حذف‌شده"), encrypt("deleted")
        db.execute(
            update(IdempotencyRecord)
            .where(IdempotencyRecord.tenant_id == tenant_id, IdempotencyRecord.entity_id == booking.id)
            .values(response={"encrypted": encrypt("{}")})
        )
    entries = list(db.scalars(select(WaitlistEntry).where(WaitlistEntry.tenant_id == tenant_id, WaitlistEntry.phone_hash == subject)))
    for entry in entries:
        entry.name_encrypted, entry.phone_encrypted, entry.consent, entry.status = encrypt("حذف‌شده"), encrypt("deleted"), False, "WITHDRAWN"
        entry.active_key = None
        for offer in db.scalars(select(WaitlistOffer).where(WaitlistOffer.tenant_id == tenant_id, WaitlistOffer.entry_id == entry.id)):
            if offer.status == "OFFERED":
                offer.status = "WITHDRAWN"
            offer.token_encrypted = encrypt("deleted")
            offer.token_hash = hashlib.sha256(("deleted:" + offer.id).encode()).hexdigest()
            db.execute(
                update(SlotHold)
                .where(SlotHold.tenant_id == tenant_id, SlotHold.id == offer.hold_id, SlotHold.status == "HELD")
                .values(status="EXPIRED")
            )
            db.execute(
                delete(Occupancy).where(
                    Occupancy.tenant_id == tenant_id, Occupancy.owner_type == "hold", Occupancy.owner_id == offer.hold_id
                )
            )
    # Includes verification messages with no appointment FK. Do not log raw recipients.
    for msg in db.scalars(select(MessageOutbox).where(MessageOutbox.tenant_id == tenant_id)):
        try:
            same = hash_phone(decrypt(msg.recipient_encrypted)) == subject
        except Exception:
            same = False
        if same:
            msg.recipient_encrypted, msg.payload = encrypt("deleted"), {}
            if msg.status in {"QUEUED", "FAILED"}:
                msg.status, msg.locked_until = "SUPPRESSED", None
    if active and not existing:
        db.add(
            StaffTask(
                tenant_id=tenant_id,
                reason="PRIVACY_ACTIVE_BOOKING",
                priority="high",
                summary="درخواست حذف داده برای فرد دارای نوبت آینده ثبت شد. اطلاعات ضروری نوبت تا بررسی مسئول مرکز نگه‌داری می‌شود.",
                appointment_id=active[0].id,
            )
        )
    audit(
        db,
        tenant_id,
        actor_id,
        "privacy.erasure_applied",
        "subject",
        subject,
        active_booking_review=bool(active),
        calls_erased=len(calls),
        staff_task_texts_erased=len(linked_tasks),
    )
    db.commit()
    return {
        "status": "REVIEW_REQUIRED" if active else "ANONYMIZED",
        "calls_erased": len(calls),
        "staff_task_texts_erased": len(linked_tasks),
        "active_bookings_retained": len(active),
        "outreach_suppressed": True,
        "extensions": extension_erasure,
        "reason": "نوبت آینده بدون اطلاع لغو نشد؛ نگه‌داری ضروری آن نیاز به بررسی دارد."
        if active
        else "داده‌های گفت‌وگو حذف و مشخصات سابقه نوبت ناشناس شد.",
        "external_erasure": "backup expiry and any approved dataset/export recipients must be reconciled separately",
    }


@router.post("/operations/privacy/delete")
def privacy_delete(data: DeleteSubjectInput, actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    if data.confirm is not True:
        fail(422, "CONFIRMATION_REQUIRED", "تایید صریح حذف لازم است.")
    return delete_subject(db, actor.tenant_id, data.phone, actor.id)


@router.get("/operations/building")
def building(actor: Actor = Depends(require_permissions("building:read")), db: Session = Depends(get_db)):
    from .models_voice import CallSession

    memberships = db.execute(
        select(Tenant, Membership)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_id == actor.id, Membership.active.is_(True), Tenant.active.is_(True))
    ).all()
    clinics = []
    for tenant, membership in memberships:
        if membership.role not in {"owner", "admin", "manager", "coordinator"}:
            continue
        bookings = db.execute(
            select(Appointment.status, Appointment.attendance, func.count())
            .where(Appointment.tenant_id == tenant.id)
            .group_by(Appointment.status, Appointment.attendance)
        ).all()
        minutes = db.scalar(
            select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                UsageEvent.tenant_id == tenant.id, UsageEvent.unit.in_(["minute", "minutes"]), UsageEvent.kind.in_(CALL_DURATION_KINDS)
            )
        )
        seconds = db.scalar(
            select(func.coalesce(func.sum(UsageEvent.quantity), 0)).where(
                UsageEvent.tenant_id == tenant.id, UsageEvent.unit.in_(["second", "seconds"]), UsageEvent.kind.in_(CALL_DURATION_KINDS)
            )
        )
        clinics.append(
            {
                "id": tenant.id,
                "name": tenant.name,
                "calls": db.scalar(select(func.count()).select_from(CallSession).where(CallSession.tenant_id == tenant.id)),
                "confirmed": sum(n for status, _attendance, n in bookings if status == "CONFIRMED"),
                "attended": sum(n for _status, attendance, n in bookings if attendance == "ATTENDED"),
                "open_tasks": db.scalar(
                    select(func.count())
                    .select_from(StaffTask)
                    .where(StaffTask.tenant_id == tenant.id, StaffTask.status.in_(["OPEN", "IN_PROGRESS", "PENDING", "CALLBACK"]))
                ),
                "minutes_used": round(minutes + seconds / 60, 2),
            }
        )
    return {
        "clinics": clinics,
        "totals": {key: sum(c[key] for c in clinics) for key in ("calls", "confirmed", "attended", "open_tasks", "minutes_used")},
        "scope": "authorized memberships only",
        "period": "all_time",
        "patient_details_included": False,
    }


def period_bounds(period: str):
    if not re.fullmatch(r"\d{4}-\d{2}", period):
        fail(422, "INVALID_PERIOD", "دوره باید به شکل YYYY-MM باشد.")
    try:
        start = datetime.strptime(period, "%Y-%m").replace(tzinfo=ZoneInfo("Asia/Tehran"))
    except ValueError:
        fail(422, "INVALID_PERIOD", "دوره معتبر نیست.")
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end


class AdjustmentInput(StrictModel):
    period: str = Field(max_length=7)
    amount_toman: int = Field(ge=-1000000000, le=1000000000)
    reason: str = Field(min_length=3, max_length=200)
    idempotency_key: str = Field(min_length=8, max_length=160)


@router.post("/operations/billing/adjustments")
def billing_adjustment(data: AdjustmentInput, actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    period_bounds(data.period)
    db.execute(update(Tenant).where(Tenant.id == actor.tenant_id).values(active=Tenant.active))
    if db.scalar(select(Invoice.id).where(Invoice.tenant_id == actor.tenant_id, Invoice.period == data.period)):
        fail(409, "INVOICE_ALREADY_FROZEN", "صورت‌حساب این دوره ثبت شده است؛ اصلاح باید در دوره بعد انجام شود.")
    old = db.scalar(
        select(BillingAdjustment).where(
            BillingAdjustment.tenant_id == actor.tenant_id, BillingAdjustment.idempotency_key == data.idempotency_key
        )
    )
    if old:
        if old.amount_toman != data.amount_toman or old.period != data.period or adjustment_reason(db, old) != data.reason:
            fail(409, "IDEMPOTENCY_MISMATCH", "کلید تکراری متفاوت است.")
        return {"id": old.id, "amount_toman": old.amount_toman}
    row = BillingAdjustment(tenant_id=actor.tenant_id, **data.model_dump(exclude={"reason"}), reason="encrypted_audit_evidence")
    db.add(row)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "billing.adjustment", "billing_adjustment", row.id, amount_toman=row.amount_toman, reason_encrypted=encrypt(data.reason))
    db.commit()
    return {"id": row.id, "amount_toman": row.amount_toman}


def adjustment_reason(db, row):
    if row.reason != "encrypted_audit_evidence":
        return row.reason
    events = db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == row.tenant_id, AuditEvent.entity_type == "billing_adjustment", AuditEvent.entity_id == row.id, AuditEvent.action == "billing.adjustment").order_by(AuditEvent.created_at.desc()))
    for event in events:
        if event.details.get("reason_encrypted"):
            return decrypt(event.details["reason_encrypted"])
    return "Unavailable encrypted adjustment reason"


class InvoiceInput(StrictModel):
    period: str = Field(max_length=7)
    base_fee_toman: int = Field(default=0, ge=0, le=1000000000)
    included_minutes: int = Field(default=0, ge=0, le=1000000)
    per_minute_toman: int = Field(default=0, ge=0, le=1000000)
    pricing_approved: bool


@router.post("/operations/billing/invoices")
def create_invoice(data: InvoiceInput, actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    if not data.pricing_approved:
        fail(422, "PRICING_APPROVAL_REQUIRED", "تعرفه باید با قرارداد مرکز تطبیق و تایید شود.")
    start, end = period_bounds(data.period)
    if end > now_utc():
        fail(409, "PERIOD_NOT_CLOSED", "صورت‌حساب نهایی فقط برای دوره پایان‌یافته ساخته می‌شود.")
    db.execute(update(Tenant).where(Tenant.id == actor.tenant_id).values(active=Tenant.active))
    old = db.scalar(select(Invoice).where(Invoice.tenant_id == actor.tenant_id, Invoice.period == data.period))
    if old:
        if old.snapshot["pricing"] != data.model_dump():
            fail(409, "FROZEN_INVOICE_MISMATCH", "صورت‌حساب ثبت‌شده با تعرفه متفاوت بازنویسی نمی‌شود.")
        return {"id": old.id, "status": old.status, "amount_toman": old.amount_toman, "snapshot": old.snapshot}
    events = list(
        db.scalars(
            select(UsageEvent).where(UsageEvent.tenant_id == actor.tenant_id, UsageEvent.created_at >= start, UsageEvent.created_at < end)
        )
    )
    minutes = sum(call_minutes(e) for e in events)
    costs = sum(e.cost_toman for e in events)
    adjustments = list(
        db.scalars(select(BillingAdjustment).where(BillingAdjustment.tenant_id == actor.tenant_id, BillingAdjustment.period == data.period))
    )
    usage_charge = math.ceil(max(0, minutes - data.included_minutes) * data.per_minute_toman)
    total = data.base_fee_toman + usage_charge + sum(a.amount_toman for a in adjustments)
    snapshot = {
        "pricing": data.model_dump(),
        "minutes": round(minutes, 4),
        "provider_cost_toman": round(costs, 2),
        "usage_charge_toman": usage_charge,
        "adjustments": [{"id": a.id, "amount_toman": a.amount_toman, "reason": "authorized_billing_adjustment"} for a in adjustments],
        "event_count": len(events),
        "frozen_at": iso(now_utc()),
        "tax": "not_calculated_contract_and_tax_review_required",
    }
    invoice = Invoice(tenant_id=actor.tenant_id, period=data.period, amount_toman=total, snapshot=snapshot)
    db.add(invoice)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "invoice.drafted", "invoice", invoice.id, period=data.period, amount_toman=total)
    db.commit()
    return {"id": invoice.id, "status": invoice.status, "amount_toman": total, "snapshot": snapshot}


@router.get("/operations/billing/invoices")
def invoices(actor: Actor = Depends(require_permissions("billing:read")), db: Session = Depends(get_db)):
    return [
        {"id": r.id, "period": r.period, "status": r.status, "amount_toman": r.amount_toman, "snapshot": r.snapshot}
        for r in db.scalars(select(Invoice).where(Invoice.tenant_id == actor.tenant_id).order_by(Invoice.period.desc()).limit(60))
    ]
