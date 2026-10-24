"""Purpose-bound outreach, patient responses and real-capacity waitlist automation."""

from datetime import datetime, timedelta
import hashlib
import secrets
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .core import ReceptionService, iso, jalali_label
from .db import get_db, now_utc
from .models import Appointment, ConsentGrant, Membership, MessageOutbox, Occupancy, SlotHold, Tenant, User
from .models_ext import AppointmentImpact
from .models_ops import WaitlistEntry, WaitlistOffer
from .models_outreach import AppointmentResponse, CapacityRelease, FollowupEnrollment, OutreachPolicy
from .operations import audit, enqueue, lock_tenant, next_permitted_time, offer_waitlist, sms_outreach_allowed, suppressed
from .schemas import StrictModel
from .security import Actor, decrypt, encrypt, fail, require_roles, require_permissions

router = APIRouter(prefix="/api/v1")
staff = require_permissions("appointment:write")
admin = require_permissions("policy:write")


def policy_for(db: Session, tenant_id: str) -> OutreachPolicy | None:
    return db.get(OutreachPolicy, tenant_id)


def approved_followup(db: Session, policy: OutreachPolicy | None) -> bool:
    if not policy or not policy.followup_enabled or not policy.followup_offsets_days or policy.clinician_approved_version != policy.version:
        return False
    return (
        db.scalar(
            select(Membership.id)
            .join(User, Membership.user_id == User.id)
            .where(
                Membership.tenant_id == policy.tenant_id,
                Membership.user_id == policy.clinician_user_id,
                Membership.role == "clinician",
                Membership.active.is_(True),
                User.active.is_(True),
            )
        )
        is not None
    )


def outreach_policy_dict(db: Session, tenant_id: str) -> dict:
    row = policy_for(db, tenant_id)
    return {
        "version": row.version if row else 1,
        "reminder_offsets_minutes": row.reminder_offsets_minutes if row else [1440],
        "waitlist_auto_offer": row.waitlist_auto_offer if row else False,
        "waitlist_offer_limit_per_run": row.waitlist_offer_limit_per_run if row else 5,
        "followup_enabled": row.followup_enabled if row else False,
        "followup_offsets_days": row.followup_offsets_days if row else [],
        "clinician_approved_version": row.clinician_approved_version if row else None,
        "clinician_user_id": row.clinician_user_id if row else None,
        "clinician_approved_at": iso(row.clinician_approved_at) if row else None,
        "followup_effective": approved_followup(db, row),
        "followup_template": "administrative_followup_v1",
        "outbound_voice_enabled": False,
    }


@router.get("/operations/outreach-policy")
def get_outreach_policy(actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    return outreach_policy_dict(db, actor.tenant_id)


class OutreachPolicyInput(StrictModel):
    version: int = Field(ge=1)
    reminder_offsets_minutes: list[int] = Field(default_factory=lambda: [1440], max_length=6)
    waitlist_auto_offer: bool = False
    waitlist_offer_limit_per_run: int = Field(default=5, ge=1, le=20)
    followup_enabled: bool = False
    followup_offsets_days: list[int] = Field(default_factory=list, max_length=6)


@router.put("/operations/outreach-policy")
def publish_outreach_policy(data: OutreachPolicyInput, actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    if len(set(data.reminder_offsets_minutes)) != len(data.reminder_offsets_minutes) or any(
        isinstance(n, bool) or not 5 <= n <= 10080 for n in data.reminder_offsets_minutes
    ):
        fail(422, "INVALID_REMINDER_OFFSETS", "بازه‌های یادآوری باید یکتا و بین ۵ دقیقه تا ۷ روز باشند.")
    if len(set(data.followup_offsets_days)) != len(data.followup_offsets_days) or any(
        isinstance(n, bool) or not 1 <= n <= 365 for n in data.followup_offsets_days
    ):
        fail(422, "INVALID_FOLLOWUP_CADENCE", "روزهای پیگیری باید یکتا و بین یک تا ۳۶۵ روز باشند.")
    if data.followup_enabled and not data.followup_offsets_days:
        fail(422, "FOLLOWUP_CADENCE_REQUIRED", "برای پیگیری برنامه روزها لازم است.")
    lock_tenant(db, actor.tenant_id)
    row = policy_for(db, actor.tenant_id)
    current = row.version if row else 1
    if data.version != current:
        fail(409, "STALE_VERSION", "سیاست پیام‌رسانی هم‌زمان تغییر کرده است.")
    if row is None:
        row = OutreachPolicy(tenant_id=actor.tenant_id)
        db.add(row)
    row.version, row.updated_by, row.updated_at = current + 1, actor.id, now_utc()
    row.reminder_offsets_minutes = sorted(data.reminder_offsets_minutes, reverse=True)
    row.waitlist_auto_offer, row.waitlist_offer_limit_per_run = data.waitlist_auto_offer, data.waitlist_offer_limit_per_run
    row.followup_enabled, row.followup_offsets_days = data.followup_enabled, sorted(data.followup_offsets_days)
    row.clinician_approved_version, row.clinician_user_id, row.clinician_approved_at = None, None, None
    audit(
        db,
        actor.tenant_id,
        actor.id,
        "outreach.policy_published",
        "tenant",
        actor.tenant_id,
        version=row.version,
        reminder_offsets=row.reminder_offsets_minutes,
        followup_offsets=row.followup_offsets_days,
        auto_offer=row.waitlist_auto_offer,
        clinical_approval_required=row.followup_enabled,
    )
    db.commit()
    return outreach_policy_dict(db, actor.tenant_id)


class ApproveOutreachInput(StrictModel):
    version: int = Field(ge=1)
    confirmed: bool


@router.post("/operations/outreach-policy/approve")
def approve_outreach(data: ApproveOutreachInput, actor: Actor = Depends(require_roles("clinician")), db: Session = Depends(get_db)):
    if not data.confirmed:
        fail(422, "CONFIRMATION_REQUIRED", "تایید صلاحیت برنامه پیگیری لازم است.")
    lock_tenant(db, actor.tenant_id)
    row = policy_for(db, actor.tenant_id)
    if row is None or row.version != data.version:
        fail(409, "STALE_VERSION", "نسخه برنامه پیگیری تغییر کرده است.")
    if not row.followup_enabled or not row.followup_offsets_days:
        fail(409, "FOLLOWUP_NOT_ENABLED", "برنامه پیگیری فعال و قابل تایید نیست.")
    # Direct internal calls also verify the active tenant-specific clinical role.
    member = db.scalar(
        select(Membership.id).where(
            Membership.user_id == actor.id,
            Membership.tenant_id == actor.tenant_id,
            Membership.role == "clinician",
            Membership.active.is_(True),
        )
    )
    if member is None:
        fail(403, "CLINICIAN_APPROVAL_REQUIRED", "تایید باید توسط نقش بالینی مجاز همین مرکز انجام شود.")
    row.clinician_user_id, row.clinician_approved_version, row.clinician_approved_at = actor.id, row.version, now_utc()
    audit(
        db,
        actor.tenant_id,
        actor.id,
        "outreach.clinician_approved",
        "tenant",
        actor.tenant_id,
        version=row.version,
        template="administrative_followup_v1",
        offsets_days=row.followup_offsets_days,
    )
    db.commit()
    return outreach_policy_dict(db, actor.tenant_id)


class FollowupInput(StrictModel):
    appointment_id: str = Field(max_length=60)
    policy_version: int = Field(ge=1)
    confirmed_consent: bool


@router.post("/operations/followups", status_code=201)
def enroll_followup(data: FollowupInput, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    row = policy_for(db, actor.tenant_id)
    if not row or row.version != data.policy_version or not approved_followup(db, row):
        fail(409, "CLINICIAN_APPROVAL_REQUIRED", "نسخه جاری پیگیری باید توسط مسئول بالینی تایید شود.")
    appointment = ReceptionService(db, actor.tenant_id).get_appointment(data.appointment_id)
    if not data.confirmed_consent or appointment.attendance != "ATTENDED":
        fail(422, "FOLLOWUP_CONSENT_REQUIRED", "پیگیری به رضایت مشخص و مراجعه ثبت‌شده نیاز دارد.")
    if not sms_outreach_allowed(db, actor.tenant_id, decrypt(appointment.phone_encrypted), "followup"):
        fail(409, "CONTACT_SUPPRESSED", "انصراف ثبت‌شده برای این هدف باید در فرایند مستقل رضایت جدید بررسی شود.")
    existing = db.scalar(
        select(FollowupEnrollment).where(
            FollowupEnrollment.tenant_id == actor.tenant_id,
            FollowupEnrollment.appointment_id == appointment.id,
            FollowupEnrollment.policy_version == row.version,
        )
    )
    if existing:
        return {"id": existing.id, "status": existing.status, "policy_version": existing.policy_version}
    grant = ConsentGrant(
        tenant_id=actor.tenant_id,
        subject_hash=appointment.phone_hash,
        purpose="followup",
        granted=True,
        policy_version=str(row.version),
        evidence={"actor_id": actor.id, "method": "staff_recorded_explicit_patient_request", "appointment_id": appointment.id},
        expires_at=now_utc() + timedelta(days=366),
    )
    db.add(grant)
    db.flush()
    enrollment = FollowupEnrollment(
        tenant_id=actor.tenant_id,
        appointment_id=appointment.id,
        subject_hash=appointment.phone_hash,
        policy_version=row.version,
        offsets_days=list(row.followup_offsets_days),
        consent_grant_id=grant.id,
    )
    db.add(enrollment)
    db.flush()
    audit(
        db,
        actor.tenant_id,
        actor.id,
        "followup.enrolled",
        "followup",
        enrollment.id,
        appointment_id=appointment.id,
        policy_version=row.version,
    )
    db.commit()
    return {"id": enrollment.id, "status": enrollment.status, "policy_version": enrollment.policy_version}


@router.get("/operations/followups")
def followups(actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    return [
        {
            "id": row.id,
            "appointment_id": row.appointment_id,
            "policy_version": row.policy_version,
            "offsets_days": row.offsets_days,
            "status": row.status,
            "created_at": iso(row.created_at),
        }
        for row in db.scalars(
            select(FollowupEnrollment)
            .where(FollowupEnrollment.tenant_id == actor.tenant_id)
            .order_by(FollowupEnrollment.created_at.desc())
            .limit(200)
        )
    ]


def ensure_response(db: Session, booking: Appointment) -> AppointmentResponse:
    row = db.scalar(
        select(AppointmentResponse).where(
            AppointmentResponse.tenant_id == booking.tenant_id,
            AppointmentResponse.appointment_id == booking.id,
            AppointmentResponse.appointment_version == booking.version,
        )
    )
    if row is None:
        token = secrets.token_urlsafe(32)
        row = AppointmentResponse(
            tenant_id=booking.tenant_id,
            appointment_id=booking.id,
            appointment_version=booking.version,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            token_encrypted=encrypt(token),
            expires_at=booking.start_at,
        )
        db.add(row)
        db.flush()
    return row


def response_path(row: AppointmentResponse) -> str:
    return "/respond/" + row.id + "#" + decrypt(row.token_encrypted)


def check_response_schedule(db: Session, booking: Appointment) -> None:
    if db.scalar(
        select(AppointmentImpact.id)
        .where(
            AppointmentImpact.tenant_id == booking.tenant_id,
            AppointmentImpact.appointment_id == booking.id,
            AppointmentImpact.state != "RESOLVED",
        )
        .limit(1)
    ):
        fail(409, "SCHEDULE_DISRUPTED", "برنامه این نوبت نیاز به هماهنگی پذیرش دارد؛ پاسخ عمومی تا تعیین تکلیف برنامه بسته است.")


class ResponseLinkInput(StrictModel):
    version: int = Field(ge=1)


@router.post("/operations/appointments/{appointment_id}/response-link")
def create_response_link(appointment_id: str, data: ResponseLinkInput, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    service = ReceptionService(db, actor.tenant_id)
    booking = service.get_appointment(appointment_id)
    service._version(booking, data.version)
    if booking.status != "CONFIRMED" or booking.start_at <= now_utc() or suppressed(db, actor.tenant_id, decrypt(booking.phone_encrypted)):
        fail(409, "RESPONSE_LINK_UNAVAILABLE", "نوبت برای پاسخ عمومی معتبر نیست.")
    check_response_schedule(db, booking)
    row = ensure_response(db, booking)
    audit(db, actor.tenant_id, actor.id, "appointment.response_link_created", "appointment", booking.id, response_id=row.id)
    db.commit()
    return {"response_id": row.id, "public_path": response_path(row), "expires_at": iso(row.expires_at), "status": row.status}


class ResponseTokenInput(StrictModel):
    token: str = Field(min_length=20, max_length=200)


class PatientResponseInput(ResponseTokenInput):
    action: Literal["CONFIRM", "DECLINE"]


def authorized_response(db: Session, response_id: str, token: str, lock: bool = False) -> AppointmentResponse:
    query = select(AppointmentResponse).where(
        AppointmentResponse.id == response_id, AppointmentResponse.token_hash == hashlib.sha256(token.encode()).hexdigest()
    )
    row = db.scalar(query)
    if row is None or row.status == "REVOKED":
        fail(404, "NOT_FOUND", "پیوند معتبر پیدا نشد.")
    if lock:
        lock_tenant(db, row.tenant_id)
        row = db.scalar(query.with_for_update().execution_options(populate_existing=True))
        if row is None or row.status == "REVOKED":
            fail(404, "NOT_FOUND", "پیوند معتبر پیدا نشد.")
    if row.expires_at <= now_utc():
        fail(410, "RESPONSE_LINK_EXPIRED", "مهلت این پیوند تمام شده است؛ با پذیرش تماس بگیرید.")
    return row


def response_view(db: Session, row: AppointmentResponse) -> dict:
    service = ReceptionService(db, row.tenant_id)
    booking = service.get_appointment(row.appointment_id)
    check_response_schedule(db, booking)
    if row.action is None and (booking.version != row.appointment_version or booking.status != "CONFIRMED"):
        fail(409, "STALE_RESPONSE_LINK", "برنامه این نوبت تغییر کرده است؛ از پذیرش پیوند جدید بگیرید.")
    tenant = service.tenant()
    return {
        "response_id": row.id,
        "clinic": tenant.name,
        "reference": booking.reference,
        "display": jalali_label(booking.start_at, tenant.timezone),
        "booking_status": booking.status,
        "response_status": row.status,
        "expires_at": iso(row.expires_at),
        "action": row.action,
    }


@router.post("/public/appointments/responses/{response_id}/view")
def view_response(response_id: str, data: ResponseTokenInput, db: Session = Depends(get_db)):
    return response_view(db, authorized_response(db, response_id, data.token))


@router.post("/public/appointments/responses/{response_id}")
def patient_response(response_id: str, data: PatientResponseInput, db: Session = Depends(get_db)):
    from .models import StaffTask

    row = authorized_response(db, response_id, data.token, lock=True)
    if row.action is not None:
        if row.action != data.action:
            fail(409, "RESPONSE_ALREADY_USED", "پاسخ قبلی ثبت شده است؛ تغییر تصمیم را با پذیرش هماهنگ کنید.")
        return response_view(db, row)
    response_view(db, row)  # Verify current appointment version before writing.
    service = ReceptionService(db, row.tenant_id, "patient-response:" + row.id)
    booking = service.get_appointment(row.appointment_id)
    row.action, row.responded_at = data.action, now_utc()
    if data.action == "CONFIRM":
        row.status = "CONFIRMED_ATTENDANCE_INTENT"
    elif booking.start_at < now_utc() + timedelta(hours=service.tenant().cancellation_notice_hours):
        row.status = "DECLINE_REVIEW_REQUIRED"
        db.add(
            StaffTask(
                tenant_id=row.tenant_id,
                appointment_id=booking.id,
                reason="PATIENT_DECLINE_REVIEW",
                priority="high",
                summary="مراجعه‌کننده درخواست عدم حضور داده است؛ پنجره لغو بسته شده و پذیرش باید تصمیم را بررسی کند.",
            )
        )
    else:
        # The response ledger and core cancellation/outbox commit together.
        row.status = "DECLINED_CANCELED"
        service.cancel_appointment(booking.id, "rsvp-decline:" + row.id, booking.version, reason="patient_rsvp_decline", verified=True)
    audit(
        db,
        row.tenant_id,
        "patient-response",
        "appointment.patient_response",
        "appointment",
        booking.id,
        response_id=row.id,
        response_status=row.status,
    )
    db.commit()
    result = response_view(db, row)
    result["message"] = (
        "درخواست عدم حضور برای بررسی پذیرش ثبت شد؛ نوبت هنوز لغو نشده است."
        if row.status == "DECLINE_REVIEW_REQUIRED"
        else "پاسخ شما ثبت شد."
    )
    return result


def followup_send_allowed(db: Session, tenant_id: str, enrollment_id: str, booking: Appointment | None) -> bool:
    if not booking or booking.tenant_id != tenant_id or booking.attendance != "ATTENDED":
        return False
    enrollment = db.scalar(
        select(FollowupEnrollment).where(
            FollowupEnrollment.id == enrollment_id,
            FollowupEnrollment.tenant_id == tenant_id,
            FollowupEnrollment.appointment_id == booking.id,
            FollowupEnrollment.status == "ACTIVE",
        )
    )
    policy = policy_for(db, tenant_id)
    if not enrollment or not approved_followup(db, policy) or enrollment.policy_version != policy.version:
        return False
    grant = db.scalar(
        select(ConsentGrant).where(
            ConsentGrant.id == enrollment.consent_grant_id,
            ConsentGrant.tenant_id == tenant_id,
            ConsentGrant.subject_hash == booking.phone_hash,
            ConsentGrant.purpose == "followup",
            ConsentGrant.granted.is_(True),
        )
    )
    return bool(grant and (grant.expires_at is None or grant.expires_at > now_utc()))


def schedule_outreach(db: Session, tenant: Tenant, now: datetime) -> dict:
    result = {"reminders_queued": 0, "followups_queued": 0}
    policy = policy_for(db, tenant.id)
    offsets = policy.reminder_offsets_minutes if policy else [1440]
    if offsets:
        for booking in db.scalars(
            select(Appointment).where(
                Appointment.tenant_id == tenant.id,
                Appointment.status == "CONFIRMED",
                Appointment.reminder_opt_in.is_(True),
                Appointment.start_at > now,
                Appointment.start_at <= now + timedelta(minutes=max(offsets)),
            )
        ):
            phone = decrypt(booking.phone_encrypted)
            if not sms_outreach_allowed(db, tenant.id, phone, "reminder"):
                continue
            due = [offset for offset in offsets if booking.start_at - timedelta(minutes=offset) <= now]
            if not due:
                continue
            offset = min(due)  # A delayed worker sends one latest-due reminder, not a burst of missed offsets.
            permitted = next_permitted_time(tenant, now)
            if permitted >= booking.start_at:
                continue
            legacy = db.scalar(
                select(MessageOutbox.id).where(
                    MessageOutbox.tenant_id == tenant.id, MessageOutbox.dedupe_key == f"reminder:{booking.id}:v{booking.version}"
                )
            )
            if legacy and offset == 1440:
                continue
            response = ensure_response(db, booking)
            result["reminders_queued"] += int(
                enqueue(
                    db,
                    tenant_id=tenant.id,
                    appointment_id=booking.id,
                    recipient_encrypted=booking.phone_encrypted,
                    purpose="reminder",
                    template="appointment_reminder_v1",
                    payload={
                        "reference": booking.reference,
                        "start_at": iso(booking.start_at),
                        "status": "CONFIRMED",
                        "offset_minutes": offset,
                        "outreach_policy_version": policy.version if policy else 1,
                        "response_id": response.id,
                    },
                    dedupe_key=f"reminder:{booking.id}:v{booking.version}:offset:{offset}",
                    available_at=permitted,
                )
            )
    if approved_followup(db, policy):
        for enrollment in db.scalars(
            select(FollowupEnrollment).where(
                FollowupEnrollment.tenant_id == tenant.id,
                FollowupEnrollment.status == "ACTIVE",
                FollowupEnrollment.policy_version == policy.version,
            )
        ):
            booking = db.scalar(select(Appointment).where(Appointment.id == enrollment.appointment_id, Appointment.tenant_id == tenant.id))
            if not followup_send_allowed(db, tenant.id, enrollment.id, booking) or not sms_outreach_allowed(
                db, tenant.id, decrypt(booking.phone_encrypted), "followup"
            ):
                continue
            end_local = booking.end_at.astimezone(ZoneInfo(tenant.timezone))
            due_days = [days for days in enrollment.offsets_days if end_local + timedelta(days=days) <= now]
            if not due_days:
                continue
            days = max(due_days)
            # Do not revive months-old care reminders on a recovered worker.
            if now - (end_local + timedelta(days=days)) > timedelta(days=2):
                continue
            result["followups_queued"] += int(
                enqueue(
                    db,
                    tenant_id=tenant.id,
                    appointment_id=booking.id,
                    recipient_encrypted=booking.phone_encrypted,
                    purpose="followup",
                    template="administrative_followup_v1",
                    payload={"enrollment_id": enrollment.id, "offset_days": days, "outreach_policy_version": enrollment.policy_version},
                    dedupe_key=f"followup:{enrollment.id}:day:{days}",
                    available_at=next_permitted_time(tenant, now),
                )
            )
    return result


def record_capacity_release(db: Session, source, source_kind: str, source_version: int, *, start=None, end=None) -> None:
    start, end = start or source.start_at, end or getattr(source, "occupied_until", source.end_at)
    if start <= now_utc():
        return
    old = db.scalar(
        select(CapacityRelease.id).where(
            CapacityRelease.tenant_id == source.tenant_id,
            CapacityRelease.source_kind == source_kind,
            CapacityRelease.source_id == source.id,
            CapacityRelease.source_version == source_version,
        )
    )
    if old is None:
        db.add(
            CapacityRelease(
                tenant_id=source.tenant_id,
                provider_id=source.provider_id,
                service_id=source.service_id,
                start_at=start,
                end_at=end,
                source_kind=source_kind,
                source_id=source.id,
                source_version=source_version,
            )
        )


def process_auto_offers(db: Session) -> dict:
    counts = {"automatic_offers": 0, "capacity_events_checked": 0}
    now = now_utc()
    db.execute(
        update(CapacityRelease)
        .where(CapacityRelease.status == "PROCESSING", CapacityRelease.locked_until <= now)
        .values(status="PENDING", locked_until=None)
    )
    db.commit()
    for policy in db.scalars(select(OutreachPolicy).where(OutreachPolicy.waitlist_auto_offer.is_(True))).all():
        candidates = list(
            db.scalars(
                select(CapacityRelease.id)
                .where(
                    CapacityRelease.tenant_id == policy.tenant_id,
                    CapacityRelease.status == "PENDING",
                    CapacityRelease.available_at <= now,
                    CapacityRelease.attempts < 3,
                )
                .order_by(CapacityRelease.created_at)
                .limit(policy.waitlist_offer_limit_per_run)
            )
        )
        for event_id in candidates:
            changed = db.execute(
                update(CapacityRelease)
                .where(CapacityRelease.id == event_id, CapacityRelease.tenant_id == policy.tenant_id, CapacityRelease.status == "PENDING")
                .values(status="PROCESSING", locked_until=now_utc() + timedelta(minutes=2), attempts=CapacityRelease.attempts + 1)
            )
            if changed.rowcount != 1:
                db.rollback()
                continue
            event = db.get(CapacityRelease, event_id)
            tenant = db.get(Tenant, policy.tenant_id)
            db.commit()
            counts["capacity_events_checked"] += 1
            if event.start_at <= now_utc() or not tenant.active:
                event.status, event.reason_code, event.locked_until = "SKIPPED", "CAPACITY_EXPIRED", None
                db.commit()
                continue
            permitted = next_permitted_time(tenant, now_utc())
            if permitted > now_utc() + timedelta(seconds=1):
                event.status, event.available_at, event.locked_until = "PENDING", permitted, None
                event.attempts -= 1
                db.commit()
                continue
            try:
                lock_tenant(db, tenant.id)
                latest_policy = db.scalar(
                    select(OutreachPolicy).where(OutreachPolicy.tenant_id == tenant.id).execution_options(populate_existing=True)
                )
                db.refresh(tenant)
                if not latest_policy or not latest_policy.waitlist_auto_offer or not tenant.active:
                    event.status, event.locked_until, event.reason_code = "PENDING", None, "AUTOMATION_DISABLED"
                    event.attempts -= 1
                    db.commit()
                    break
                service = ReceptionService(db, tenant.id, "auto-waitlist")
                token = service._encode_slot(tenant, event.provider_id, event.service_id, event.start_at)
                result = offer_waitlist(db, tenant.id, token)
                event = db.get(CapacityRelease, event_id)
                event.status, event.locked_until = "PROCESSED", None
                event.reason_code = result["status"]
                if result["status"] == "OFFERED":
                    event.offer_id = result["id"]
                    counts["automatic_offers"] += 1
                audit(
                    db,
                    tenant.id,
                    "auto-waitlist",
                    "waitlist.capacity_processed",
                    "capacity_release",
                    event.id,
                    outcome=result["status"],
                    offer_id=event.offer_id,
                    source_kind=event.source_kind,
                )
                db.commit()
            except HTTPException as exc:
                db.rollback()
                event = db.get(CapacityRelease, event_id)
                event.status, event.locked_until = "SKIPPED", None
                event.reason_code = (
                    exc.detail.get("code", "CAPACITY_NOT_AVAILABLE") if isinstance(exc.detail, dict) else "CAPACITY_NOT_AVAILABLE"
                )
                audit(db, tenant.id, "auto-waitlist", "waitlist.capacity_skipped", "capacity_release", event.id, code=event.reason_code)
                db.commit()
    return counts


class RejectWaitlistInput(StrictModel):
    confirmed: bool
    reason: Literal["declined", "unreachable", "timing", "no_longer_needed"]


@router.post("/operations/waitlist/offers/{offer_id}/reject")
def reject_waitlist_offer(offer_id: str, data: RejectWaitlistInput, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    if not data.confirmed:
        fail(422, "CONFIRMATION_REQUIRED", "رد پیشنهاد باید تایید شود.")
    lock_tenant(db, actor.tenant_id)
    offer = db.scalar(
        select(WaitlistOffer).where(WaitlistOffer.tenant_id == actor.tenant_id, WaitlistOffer.id == offer_id).with_for_update()
    )
    if offer is None:
        fail(404, "NOT_FOUND", "پیشنهاد پیدا نشد.")
    if offer.status == "REJECTED":
        return {"id": offer.id, "status": offer.status}
    if offer.status != "OFFERED" or offer.appointment_id:
        fail(409, "OFFER_NOT_ACTIVE", "فقط پیشنهاد فعال و پذیرفته‌نشده قابل رد است.")
    entry = db.scalar(select(WaitlistEntry).where(WaitlistEntry.id == offer.entry_id, WaitlistEntry.tenant_id == actor.tenant_id))
    hold = db.scalar(select(SlotHold).where(SlotHold.id == offer.hold_id, SlotHold.tenant_id == actor.tenant_id))
    offer.status, offer.token_encrypted = "REJECTED", encrypt("rejected")
    offer.token_hash = hashlib.sha256(("rejected:" + offer.id).encode()).hexdigest()
    entry.status = "WITHDRAWN" if data.reason == "no_longer_needed" else "WAITING" if entry.offer_attempts < 3 else "EXHAUSTED"
    if entry.status in {"WITHDRAWN", "EXHAUSTED"}:
        entry.active_key = None
    if entry.status == "WITHDRAWN":
        entry.consent = False
    if hold and hold.status == "HELD":
        hold.status = "RELEASED"
        db.execute(
            delete(Occupancy).where(Occupancy.tenant_id == actor.tenant_id, Occupancy.owner_type == "hold", Occupancy.owner_id == hold.id)
        )
        record_capacity_release(db, hold, "waitlist_rejected", 1)
    audit(db, actor.tenant_id, actor.id, "waitlist.rejected", "offer", offer.id, reason=data.reason, entry_status=entry.status)
    db.commit()
    return {"id": offer.id, "status": offer.status, "entry_status": entry.status}
