"""Auditable staff operations: policy history, task ownership and schedule repair."""

from copy import deepcopy
from datetime import date, datetime, time, timedelta
import json
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from pydantic import Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .core import ReceptionService, call_minutes, iso, request_digest, task_dict
from .db import get_db, now_utc
from .models import (
    Appointment,
    AuditEvent,
    Membership,
    MessageOutbox,
    Occupancy,
    Practitioner,
    SlotHold,
    StaffTask,
    Tenant,
    UsageEvent,
    User,
)
from .models_ext import (
    AppointmentImpact,
    CorrectionRecord,
    Disruption,
    OperationReceipt,
    PaymentAdjustment,
    PaymentDispute,
    PolicyRevision,
    RefundReview,
    TaskControl,
)
from .models_ops import PaymentIntent, RefundLedger, WaitlistEntry, WaitlistOffer
from .operations import audit, enqueue, lock_tenant
from .schemas import SettingsInput, StrictModel
from .security import Actor, decrypt, encrypt, fail, hash_phone, normalize_phone, require_permissions

router = APIRouter(prefix="/api/v1")
admin = require_permissions("policy:write")
staff = require_permissions("appointment:write")
ACTIVE_TASKS = {"OPEN", "IN_PROGRESS", "PENDING", "CALLBACK"}
POLICY_FIELDS = (
    "name",
    "mode",
    "address",
    "phone",
    "website",
    "working_hours",
    "holidays",
    "faq",
    "retention_days",
    "lead_time_minutes",
    "booking_horizon_days",
    "cancellation_notice_hours",
    "quiet_hours",
    "monthly_minute_budget",
)


def policy_snapshot(tenant: Tenant) -> dict:
    return {key: deepcopy(getattr(tenant, key)) for key in POLICY_FIELDS}


def capture_policy(db: Session, tenant: Tenant, actor_id: str, reason: str, changed_fields: list[str], restored_from: int | None = None):
    existing = db.scalar(
        select(PolicyRevision).where(PolicyRevision.tenant_id == tenant.id, PolicyRevision.version == tenant.settings_version)
    )
    if existing is None:
        db.add(
            PolicyRevision(
                tenant_id=tenant.id,
                version=tenant.settings_version,
                snapshot=policy_snapshot(tenant),
                actor_id=actor_id,
                reason_encrypted=encrypt(reason),
                changed_fields=changed_fields,
                restored_from=restored_from,
            )
        )


@router.get("/operations/policies")
def policy_history(actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    tenant = ReceptionService(db, actor.tenant_id).tenant()
    rows = list(
        db.scalars(
            select(PolicyRevision).where(PolicyRevision.tenant_id == actor.tenant_id).order_by(PolicyRevision.version.desc()).limit(200)
        )
    )
    revisions = [
        {
            "version": row.version,
            "created_at": iso(row.created_at),
            "actor_id": row.actor_id,
            "changed_fields": row.changed_fields,
            "restored_from": row.restored_from,
            "reason": decrypt(row.reason_encrypted),
            "snapshot": row.snapshot,
        }
        for row in rows
    ]
    if not any(row["version"] == tenant.settings_version for row in revisions):
        revisions.insert(
            0,
            {
                "version": tenant.settings_version,
                "created_at": None,
                "actor_id": None,
                "changed_fields": [],
                "restored_from": None,
                "reason": "Current settings; the first publication preserves this baseline.",
                "snapshot": policy_snapshot(tenant),
            },
        )
    return {
        "current_version": tenant.settings_version,
        "revisions": revisions,
        "scope": "Tenant reception policy. Catalog prices, patient records and calendar transactions have their own audit history.",
    }


class RestorePolicyInput(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)
    confirmed: bool


@router.post("/operations/policies/{version}/restore")
def restore_policy(version: int, data: RestorePolicyInput, actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    if not data.confirmed:
        fail(422, "CONFIRMATION_REQUIRED", "تایید بازگردانی تنظیمات لازم است.")
    row = db.scalar(select(PolicyRevision).where(PolicyRevision.tenant_id == actor.tenant_id, PolicyRevision.version == version))
    if row is None:
        fail(404, "NOT_FOUND", "نسخه تنظیمات پیدا نشد.")
    changes = SettingsInput.model_validate({**deepcopy(row.snapshot), "version": data.expected_version}).model_dump(exclude_unset=True)
    return ReceptionService(db, actor.tenant_id, actor.id).update_settings(changes, reason=data.reason, restored_from=version)


def receipt(db: Session, actor: Actor, operation: str, key: str, payload: dict) -> OperationReceipt | None:
    old = db.scalar(
        select(OperationReceipt).where(
            OperationReceipt.tenant_id == actor.tenant_id, OperationReceipt.operation == operation, OperationReceipt.key == key
        )
    )
    if old and old.request_hash != request_digest(payload):
        fail(409, "IDEMPOTENCY_MISMATCH", "کلید تکرار با درخواست دیگری استفاده شده است.")
    return old


def record_receipt(db: Session, actor: Actor, operation: str, key: str, payload: dict, entity_id: str):
    db.add(
        OperationReceipt(tenant_id=actor.tenant_id, operation=operation, key=key, request_hash=request_digest(payload), entity_id=entity_id)
    )


def task_control(db: Session, row: StaffTask) -> TaskControl:
    control = db.scalar(select(TaskControl).where(TaskControl.task_id == row.id, TaskControl.tenant_id == row.tenant_id))
    if control is None:
        control = TaskControl(task_id=row.id, tenant_id=row.tenant_id, version=1)
        db.add(control)
        db.flush()
    return control


def extended_task(db: Session, row: StaffTask) -> dict:
    control = db.scalar(select(TaskControl).where(TaskControl.task_id == row.id, TaskControl.tenant_id == row.tenant_id))
    assignee = db.get(User, row.assigned_to) if row.assigned_to else None
    events = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == row.tenant_id, AuditEvent.entity_type == "task", AuditEvent.entity_id == row.id)
        .order_by(AuditEvent.created_at.desc())
        .limit(10)
    )
    last_note = next((decrypt(event.details["reason_encrypted"]) for event in events if event.details.get("reason_encrypted")), "")
    return {
        **task_dict(row),
        "assignee_id": row.assigned_to,
        "assignee_name": assignee.name if assignee else None,
        "assigned_to": row.assigned_to,
        "version": control.version if control else 1,
        "callback_at": iso(control.callback_at) if control and control.callback_at else None,
        "last_note": last_note,
    }


@router.get("/operations/tasks")
def operation_tasks(status: str | None = Query(default=None, max_length=30), actor: Actor = Depends(require_permissions("task:read")), db: Session = Depends(get_db)):
    query = select(StaffTask).where(StaffTask.tenant_id == actor.tenant_id)
    if status:
        if status not in ACTIVE_TASKS | {"RESOLVED"}:
            fail(422, "INVALID_TASK_STATUS", "وضعیت درخواست معتبر نیست.")
        query = query.where(StaffTask.status == status)
    return [extended_task(db, row) for row in db.scalars(query.order_by(StaffTask.created_at.desc()).limit(200))]


@router.get("/operations/assignees")
def eligible_assignees(actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    return [
        {"user_id": user.id, "name": user.name, "role": member.role}
        for user, member in db.execute(
            select(User, Membership)
            .join(Membership, Membership.user_id == User.id)
            .where(
                Membership.tenant_id == actor.tenant_id,
                Membership.active.is_(True),
                User.active.is_(True),
                Membership.role.in_(["owner", "admin", "manager", "coordinator", "receptionist", "clinician"]),
            )
            .order_by(User.name)
        )
    ]


class TaskActionInput(StrictModel):
    action: Literal["claim", "reassign", "pending", "callback", "resolve", "reopen", "reject", "redirect"]
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=160)
    reason: str = Field(default="", max_length=500)
    assignee_id: str | None = Field(default=None, max_length=60)
    callback_at: datetime | None = None


def apply_task_action(db: Session, actor: Actor, task_id: str, data: TaskActionInput) -> dict:
    lock_tenant(db, actor.tenant_id)
    payload = {"task_id": task_id, **data.model_dump(mode="json")}
    previous = receipt(db, actor, "task_action", data.idempotency_key, payload)
    row = db.scalar(
        select(StaffTask)
        .where(StaffTask.id == task_id, StaffTask.tenant_id == actor.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        fail(404, "NOT_FOUND", "درخواست پیدا نشد.")
    if previous:
        return extended_task(db, row)
    control = task_control(db, row)
    if control.version != data.version:
        fail(409, "STALE_VERSION", "درخواست هم‌زمان تغییر کرده است.")
    if data.action != "claim" and len(data.reason.strip()) < 2:
        fail(422, "REASON_REQUIRED", "دلیل روشن برای تغییر درخواست لازم است.")
    is_admin = actor.role in {"owner", "admin", "manager"}
    if data.action in {"reassign", "redirect"}:
        if not is_admin:
            fail(403, "ROLE_REQUIRED", "واگذاری به همکار دیگر به دسترسی مدیر نیاز دارد.")
        member = db.scalar(
            select(Membership)
            .join(User, Membership.user_id == User.id)
            .where(
                Membership.tenant_id == actor.tenant_id,
                Membership.user_id == data.assignee_id,
                Membership.active.is_(True),
                User.active.is_(True),
                Membership.role.in_(["owner", "admin", "manager", "coordinator", "receptionist", "clinician"]),
            )
        )
        if member is None:
            fail(422, "INVALID_ASSIGNEE", "همکار فعال و مجاز همین مرکز را انتخاب کنید.")
    if data.action == "claim":
        if row.status not in ACTIVE_TASKS or (row.assigned_to and row.assigned_to != actor.id):
            fail(409, "TASK_ALREADY_CLAIMED", "این درخواست در اختیار همکار دیگری است یا بسته شده است.")
        row.assigned_to, row.status = actor.id, "IN_PROGRESS"
        control.callback_at = None
    elif data.action == "reopen":
        if row.status != "RESOLVED":
            fail(409, "INVALID_TASK_TRANSITION", "فقط درخواست بسته‌شده دوباره باز می‌شود.")
        if row.assigned_to != actor.id and not is_admin:
            fail(403, "TASK_OWNER_REQUIRED", "بازگشایی به مسئول درخواست یا مدیر نیاز دارد.")
        row.status, row.assigned_to, row.resolved_at, row.resolution = "OPEN", None, None, ""
        control.callback_at = None
    else:
        if row.status not in ACTIVE_TASKS:
            fail(409, "INVALID_TASK_TRANSITION", "درخواست بسته‌شده باید ابتدا بازگشایی شود.")
        if row.assigned_to != actor.id and not is_admin:
            fail(403, "TASK_OWNER_REQUIRED", "ابتدا درخواست را بپذیرید؛ مسئول دیگر مجاز به تغییر آن نیست.")
        if data.action in {"reassign", "redirect"}:
            row.assigned_to, row.status = data.assignee_id, "IN_PROGRESS"
            control.callback_at = None
        elif data.action == "reject":
            row.assigned_to, row.status = None, "OPEN"
            control.callback_at = None
        elif data.action == "pending":
            row.status, control.callback_at = "PENDING", None
        elif data.action == "callback":
            if (
                data.callback_at is None
                or data.callback_at.tzinfo is None
                or not now_utc() < data.callback_at <= now_utc() + timedelta(days=90)
            ):
                fail(422, "INVALID_CALLBACK_TIME", "زمان تماس مجدد باید در آینده و با منطقه زمانی باشد.")
            row.status, control.callback_at = "CALLBACK", data.callback_at
        elif data.action == "resolve":
            row.status, row.resolved_at = "RESOLVED", now_utc()
            if not row.assigned_to:
                row.assigned_to = actor.id
            row.resolution = "کار توسط مسئول درخواست بسته شد؛ یادداشت محافظت‌شده در سابقه ثبت است."
            control.callback_at = None
    control.version += 1
    audit(
        db,
        actor.tenant_id,
        actor.id,
        "task." + data.action,
        "task",
        row.id,
        status=row.status,
        version=control.version,
        assignee_id=row.assigned_to,
        reason_hash=request_digest({"reason": data.reason}),
        reason_encrypted=encrypt(data.reason) if data.reason else None,
        callback_at=iso(control.callback_at),
    )
    record_receipt(db, actor, "task_action", data.idempotency_key, payload, row.id)
    db.commit()
    return extended_task(db, row)


@router.post("/operations/tasks/{task_id}/actions")
def task_action(task_id: str, data: TaskActionInput, actor: Actor = Depends(require_permissions("task:write")), db: Session = Depends(get_db)):
    return apply_task_action(db, actor, task_id, data)


def legacy_resolve_task(db: Session, actor: Actor, task_id: str, reason: str) -> dict:
    """Keep the original route while sharing the same ownership enforcement."""
    lock_tenant(db, actor.tenant_id)
    row = db.scalar(
        select(StaffTask)
        .where(StaffTask.id == task_id, StaffTask.tenant_id == actor.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        fail(404, "NOT_FOUND", "درخواست پیدا نشد.")
    if row.assigned_to and row.assigned_to != actor.id and actor.role not in {"owner", "admin"}:
        fail(403, "TASK_OWNER_REQUIRED", "این درخواست در اختیار همکار دیگری است.")
    if row.status == "RESOLVED":
        return extended_task(db, row)
    control = task_control(db, row)
    if not row.assigned_to:
        row.assigned_to = actor.id
    return apply_task_action(
        db,
        actor,
        task_id,
        TaskActionInput(
            action="resolve",
            version=control.version,
            idempotency_key="legacy-resolve:" + task_id + ":" + str(control.version),
            reason=reason,
        ),
    )


class CorrectionInput(StrictModel):
    version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=160)
    reason: str = Field(min_length=3, max_length=500)
    confirmed: bool
    patient_name: str | None = Field(default=None, min_length=2, max_length=120)
    phone: str | None = Field(default=None, max_length=30)
    slot_id: str | None = Field(default=None, min_length=10, max_length=3000)
    accept_price_change: bool = False


def resolve_schedule_tasks(db: Session, tenant_id: str, appointment_id: str) -> None:
    db.flush()
    if (
        db.scalar(
            select(AppointmentImpact.id)
            .where(
                AppointmentImpact.tenant_id == tenant_id,
                AppointmentImpact.appointment_id == appointment_id,
                AppointmentImpact.state != "RESOLVED",
            )
            .limit(1)
        )
        is not None
    ):
        return
    for task in db.scalars(
        select(StaffTask).where(
            StaffTask.tenant_id == tenant_id,
            StaffTask.appointment_id == appointment_id,
            StaffTask.reason == "SCHEDULE_DISRUPTION",
            StaffTask.status.in_(ACTIVE_TASKS),
        )
    ):
        task.status, task.resolved_at, task.resolution = "RESOLVED", now_utc(), "تصمیم برنامه نوبت در سابقه رسمی ثبت شد."
        control = db.scalar(select(TaskControl).where(TaskControl.task_id == task.id, TaskControl.tenant_id == tenant_id))
        if control:
            control.version += 1
            control.callback_at = None


@router.get("/operations/appointments/{appointment_id}")
def operation_appointment(appointment_id: str, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    service = ReceptionService(db, actor.tenant_id, actor.id)
    return service.appointment_dict(service.get_appointment(appointment_id))


def correct_appointment(db: Session, actor: Actor, appointment_id: str, data: CorrectionInput) -> dict:
    if data.confirmed is not True:
        fail(422, "CONFIRMATION_REQUIRED", "هویت و اصلاح درخواست‌شده باید به‌صراحت تایید شود.")
    if data.patient_name is None and data.phone is None and data.slot_id is None:
        fail(422, "CORRECTION_REQUIRED", "حداقل یک اصلاح مشخص لازم است.")
    if data.patient_name is not None and (len(data.patient_name.strip()) < 2 or any(ord(char) < 32 for char in data.patient_name)):
        fail(422, "INVALID_NAME", "نام معتبر وارد کنید.")
    phone = normalize_phone(data.phone) if data.phone is not None else None
    lock_tenant(db, actor.tenant_id)
    payload = {"appointment_id": appointment_id, **data.model_dump()}
    previous = receipt(db, actor, "appointment_correction", data.idempotency_key, payload)
    service = ReceptionService(db, actor.tenant_id, actor.id)
    booking = service.get_appointment(appointment_id, lock=True)
    db.refresh(booking)
    if previous:
        return service.appointment_dict(booking)
    service._version(booking, data.version)
    if booking.status not in {"CONFIRMED", "PENDING_STAFF_APPROVAL", "PENDING_PAYMENT"} or booking.attendance:
        fail(409, "INVALID_STATE", "سابقه بسته‌شده با اصلاح جاری بازنویسی نمی‌شود.")
    before = {
        "patient_name": decrypt(booking.patient_name_encrypted),
        "phone": decrypt(booking.phone_encrypted),
        "provider_id": booking.provider_id,
        "service_id": booking.service_id,
        "start_at": iso(booking.start_at),
        "price_toman": booking.price_toman,
        "deposit_toman": booking.deposit_toman,
    }
    previous_subject = booking.phone_hash
    changes = []
    try:
        if data.slot_id is not None:
            if booking.status == "PENDING_PAYMENT":
                fail(409, "PAYMENT_REVIEW_REQUIRED", "نوبت منتظر پرداخت پیش از تغییر خدمت یا زمان باید تعیین تکلیف شود.")
            tenant, provider, catalog, start, occupied_end = service._decode_slot(data.slot_id)
            if catalog.deposit_toman != booking.deposit_toman:
                fail(409, "PAYMENT_REVIEW_REQUIRED", "تغییر بیعانه به تطبیق پرداخت و فرایند رزرو جدید نیاز دارد.")
            if catalog.price_toman != booking.price_toman and not data.accept_price_change:
                fail(409, "PRICE_CONFIRMATION_REQUIRED", "تغییر قیمت خدمت باید صریحاً تایید شود.")
            if provider.id != booking.provider_id or start != booking.start_at:
                from .operations_outreach import record_capacity_release

                record_capacity_release(db, booking, "appointment_corrected", booking.version + 1)
            db.execute(
                delete(Occupancy).where(
                    Occupancy.tenant_id == actor.tenant_id, Occupancy.owner_type == "appointment", Occupancy.owner_id == booking.id
                )
            )
            service._claims(provider.id, catalog, start, occupied_end, "appointment", booking.id)
            db.flush()  # A collision restores the old claim when this transaction rolls back.
            booking.provider_id, booking.service_id = provider.id, catalog.id
            booking.start_at, booking.end_at, booking.occupied_until = (
                start,
                start + timedelta(minutes=catalog.duration_minutes),
                occupied_end,
            )
            booking.price_toman, booking.settings_version = catalog.price_toman, tenant.settings_version
            if catalog.requires_approval:
                booking.status, booking.approval_required = "PENDING_STAFF_APPROVAL", True
                db.add(
                    StaffTask(
                        tenant_id=actor.tenant_id,
                        reason="BOOKING_APPROVAL",
                        appointment_id=booking.id,
                        summary="خدمت اصلاح‌شده برای تایید نهایی نیاز به بررسی پذیرش دارد.",
                    )
                )
            db.execute(
                update(AppointmentImpact)
                .where(
                    AppointmentImpact.tenant_id == actor.tenant_id,
                    AppointmentImpact.appointment_id == booking.id,
                    AppointmentImpact.state != "RESOLVED",
                )
                .values(state="RESOLVED", resolved_at=now_utc())
            )
            resolve_schedule_tasks(db, actor.tenant_id, booking.id)
            changes.extend(["provider_id", "service_id", "start_at", "price_toman"])
        if data.patient_name is not None:
            booking.patient_name_encrypted = encrypt(data.patient_name.strip())
            changes.append("patient_name")
        if phone is not None:
            if booking.phone_hash != hash_phone(phone):
                # An unverified old recipient must not receive a corrected patient's notice.
                db.execute(
                    update(MessageOutbox)
                    .where(
                        MessageOutbox.tenant_id == actor.tenant_id,
                        MessageOutbox.appointment_id == booking.id,
                        MessageOutbox.status.in_(["QUEUED", "FAILED"]),
                    )
                    .values(status="SUPPRESSED", last_error_code="CONTACT_CORRECTED", locked_until=None)
                )
                booking.reminder_opt_in = False
            booking.phone_encrypted, booking.phone_hash = encrypt(phone), hash_phone(phone)
            changes.append("phone")
        booking.version += 1
        booking.updated_at = now_utc()
        after = {
            "patient_name": decrypt(booking.patient_name_encrypted),
            "phone": decrypt(booking.phone_encrypted),
            "provider_id": booking.provider_id,
            "service_id": booking.service_id,
            "start_at": iso(booking.start_at),
            "price_toman": booking.price_toman,
            "deposit_toman": booking.deposit_toman,
        }
        record = CorrectionRecord(
            tenant_id=actor.tenant_id,
            appointment_id=booking.id,
            actor_id=actor.id,
            subject_hash=booking.phone_hash,
            previous_subject_hash=previous_subject,
            reason_encrypted=encrypt(data.reason),
            changes_encrypted=encrypt(json.dumps({"before": before, "after": after}, ensure_ascii=False)),
        )
        db.add(record)
        db.flush()
        if data.slot_id is not None or phone is not None:
            service._notice(
                booking,
                "rescheduled"
                if data.slot_id and booking.status == "CONFIRMED"
                else "confirmed"
                if booking.status == "CONFIRMED"
                else "pending",
            )
        audit(
            db,
            actor.tenant_id,
            actor.id,
            "appointment.corrected",
            "appointment",
            booking.id,
            changed_fields=sorted(set(changes)),
            correction_id=record.id,
            previous_version=data.version,
        )
        record_receipt(db, actor, "appointment_correction", data.idempotency_key, payload, booking.id)
        db.commit()
        db.refresh(booking)
        return service.appointment_dict(booking)
    except IntegrityError:
        db.rollback()
        fail(409, "SLOT_TAKEN", "زمان جدید در دسترس نیست؛ نوبت و اطلاعات قبلی حفظ شد.")


@router.patch("/operations/appointments/{appointment_id}/details")
def appointment_correction(appointment_id: str, data: CorrectionInput, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    return correct_appointment(db, actor, appointment_id, data)


class DisruptionInput(StrictModel):
    kind: Literal["LATE_ARRIVAL", "PROVIDER_DELAY", "EMERGENCY_CLOSURE"]
    provider_id: str | None = Field(default=None, max_length=60)
    appointment_id: str | None = Field(default=None, max_length=60)
    start_at: datetime | None = None
    end_at: datetime | None = None
    delay_minutes: int = Field(default=0, ge=0, le=720)
    reason: str = Field(min_length=3, max_length=500)
    expected_policy_version: int = Field(ge=1)
    idempotency_key: str = Field(min_length=8, max_length=160)
    confirmed: bool = False


def disruption_scope(db: Session, actor: Actor, data: DisruptionInput):
    tenant = ReceptionService(db, actor.tenant_id).tenant()
    if data.kind == "LATE_ARRIVAL":
        if not data.appointment_id or not data.delay_minutes:
            fail(422, "ARRIVAL_DETAILS_REQUIRED", "نوبت و مدت تاخیر لازم است.")
        booking = ReceptionService(db, actor.tenant_id).get_appointment(data.appointment_id)
        if booking.status != "CONFIRMED" or booking.attendance:
            fail(409, "INVALID_STATE", "تاخیر فقط برای نوبت تاییدشده و تعیین‌تکلیف‌نشده ثبت می‌شود.")
        return tenant, booking.provider_id, booking.start_at, booking.end_at, [booking]
    if data.appointment_id:
        fail(422, "INVALID_DISRUPTION_SCOPE", "تعطیلی یا تاخیر پزشک با بازه زمانی تعیین می‌شود.")
    if (
        data.provider_id
        and db.scalar(select(Practitioner.id).where(Practitioner.id == data.provider_id, Practitioner.tenant_id == actor.tenant_id)) is None
    ):
        fail(404, "NOT_FOUND", "ارائه‌دهنده این مرکز پیدا نشد.")
    if data.kind == "PROVIDER_DELAY" and (not data.provider_id or not data.delay_minutes):
        fail(422, "PROVIDER_DELAY_REQUIRED", "پزشک و مدت تاخیر را مشخص کنید.")
    start, end = data.start_at, data.end_at
    if (
        start is None
        or end is None
        or start.tzinfo is None
        or end.tzinfo is None
        or end <= start
        or end <= now_utc()
        or end - start > timedelta(days=31)
    ):
        fail(422, "INVALID_DISRUPTION_WINDOW", "بازه معتبر با منطقه زمانی و پایان در آینده لازم است.")
    query = select(Appointment).where(
        Appointment.tenant_id == actor.tenant_id,
        Appointment.status.in_(["CONFIRMED", "PENDING_PAYMENT", "PENDING_STAFF_APPROVAL"]),
        Appointment.start_at < end,
        Appointment.occupied_until > start,
    )
    if data.provider_id:
        query = query.where(Appointment.provider_id == data.provider_id)
    return tenant, data.provider_id, start, end, list(db.scalars(query.order_by(Appointment.start_at)))


@router.post("/operations/disruptions/preview")
def preview_disruption(data: DisruptionInput, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    tenant, provider_id, start, end, bookings = disruption_scope(db, actor, data)
    service = ReceptionService(db, actor.tenant_id)
    return {
        "policy_version": tenant.settings_version,
        "kind": data.kind,
        "provider_id": provider_id,
        "start_at": iso(start),
        "end_at": iso(end),
        "affected_count": len(bookings),
        "appointments": [service.appointment_dict(row) for row in bookings],
        "effect": "New bookings in the affected window are blocked. Existing appointments keep their times and require staff review.",
    }


def disruption_dict(db: Session, row: Disruption) -> dict:
    impacts = list(
        db.scalars(select(AppointmentImpact).where(AppointmentImpact.tenant_id == row.tenant_id, AppointmentImpact.disruption_id == row.id))
    )
    return {
        "id": row.id,
        "kind": row.kind,
        "provider_id": row.provider_id,
        "start_at": iso(row.start_at),
        "end_at": iso(row.end_at),
        "delay_minutes": row.delay_minutes,
        "status": row.status,
        "version": row.version,
        "reason": decrypt(row.reason_encrypted),
        "created_at": iso(row.created_at),
        "resolved_at": iso(row.resolved_at),
        "impacts": [
            {
                "id": impact.id,
                "appointment_id": impact.appointment_id,
                "state": impact.state,
                "original_start_at": iso(impact.original_start_at),
            }
            for impact in impacts
        ],
    }


@router.get("/operations/disruptions")
def list_disruptions(actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    return [
        disruption_dict(db, row)
        for row in db.scalars(
            select(Disruption).where(Disruption.tenant_id == actor.tenant_id).order_by(Disruption.created_at.desc()).limit(100)
        )
    ]


@router.post("/operations/disruptions", status_code=201)
def create_disruption(data: DisruptionInput, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    if data.kind != "LATE_ARRIVAL" and actor.role not in {"owner", "admin"}:
        fail(403, "ROLE_REQUIRED", "تغییر برنامه پزشک یا تعطیلی به تایید مدیر نیاز دارد.")
    if data.confirmed is not True:
        fail(422, "CONFIRMATION_REQUIRED", "اثر اختلال بر نوبت‌ها باید تایید شود.")
    lock_tenant(db, actor.tenant_id)
    payload = data.model_dump(mode="json")
    previous = receipt(db, actor, "disruption", data.idempotency_key, payload)
    if previous:
        row = db.scalar(select(Disruption).where(Disruption.tenant_id == actor.tenant_id, Disruption.id == previous.entity_id))
        return disruption_dict(db, row)
    tenant, provider_id, start, end, bookings = disruption_scope(db, actor, data)
    db.refresh(tenant)
    if tenant.settings_version != data.expected_policy_version:
        fail(409, "STALE_VERSION", "برنامه مرکز تغییر کرده است؛ اثر اختلال را دوباره بررسی کنید.")
    row = Disruption(
        tenant_id=actor.tenant_id,
        provider_id=provider_id,
        kind=data.kind,
        start_at=start,
        end_at=end,
        delay_minutes=data.delay_minutes,
        actor_id=actor.id,
        reason_encrypted=encrypt(data.reason),
    )
    db.add(row)
    db.flush()
    state = {"LATE_ARRIVAL": "ARRIVAL_REVIEW", "PROVIDER_DELAY": "DELAY_REVIEW", "EMERGENCY_CLOSURE": "CLOSURE_REVIEW"}[data.kind]
    for booking in bookings:
        booking.version += 1
        impact = AppointmentImpact(
            tenant_id=actor.tenant_id,
            disruption_id=row.id,
            appointment_id=booking.id,
            state=state,
            original_start_at=booking.start_at,
            original_end_at=booking.end_at,
            original_status=booking.status,
        )
        db.add(impact)
        db.add(
            StaffTask(
                tenant_id=actor.tenant_id,
                reason="SCHEDULE_DISRUPTION",
                priority="high",
                appointment_id=booking.id,
                summary="برنامه نوبت دچار اختلال شده است؛ زمان جایگزین یا لغو باید با مراجعه‌کننده تعیین تکلیف شود.",
            )
        )
        enqueue(
            db,
            tenant_id=actor.tenant_id,
            appointment_id=booking.id,
            recipient_encrypted=booking.phone_encrypted,
            purpose="disruption",
            template="appointment_disruption_v1",
            dedupe_key=f"disruption:{row.id}:{booking.id}",
            payload={"disruption_id": row.id, "kind": row.kind, "start_at": iso(booking.start_at), "reference": booking.reference},
        )
    if data.kind != "LATE_ARRIVAL":
        held = select(SlotHold).where(
            SlotHold.tenant_id == actor.tenant_id, SlotHold.status == "HELD", SlotHold.start_at < end, SlotHold.end_at > start
        )
        if provider_id:
            held = held.where(SlotHold.provider_id == provider_id)
        for hold in db.scalars(held.with_for_update()):
            hold.status = "RELEASED"
            db.execute(
                delete(Occupancy).where(
                    Occupancy.tenant_id == actor.tenant_id, Occupancy.owner_type == "hold", Occupancy.owner_id == hold.id
                )
            )
            for offer in db.scalars(
                select(WaitlistOffer).where(
                    WaitlistOffer.tenant_id == actor.tenant_id, WaitlistOffer.hold_id == hold.id, WaitlistOffer.status == "OFFERED"
                )
            ):
                offer.status = "WITHDRAWN"
                entry = db.scalar(
                    select(WaitlistEntry).where(WaitlistEntry.tenant_id == actor.tenant_id, WaitlistEntry.id == offer.entry_id)
                )
                if entry and entry.status == "OFFERED":
                    entry.status = "WAITING" if entry.offer_attempts < 3 else "EXHAUSTED"
                    if entry.status == "EXHAUSTED":
                        entry.active_key = None
        capture_policy(db, tenant, actor.id, "baseline_before_disruption", [])
        tenant.settings_version += 1
        capture_policy(db, tenant, actor.id, "schedule_disruption", ["disruption:" + row.kind])
    audit(
        db,
        actor.tenant_id,
        actor.id,
        "schedule.disrupted",
        "disruption",
        row.id,
        kind=row.kind,
        affected_count=len(bookings),
        start_at=iso(start),
        end_at=iso(end),
        settings_version=tenant.settings_version,
    )
    record_receipt(db, actor, "disruption", data.idempotency_key, payload, row.id)
    db.commit()
    return disruption_dict(db, row)


class ResolveDisruptionInput(StrictModel):
    version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=500)
    confirmed: bool


@router.post("/operations/disruptions/{disruption_id}/resolve")
def resolve_disruption(disruption_id: str, data: ResolveDisruptionInput, actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    if not data.confirmed:
        fail(422, "CONFIRMATION_REQUIRED", "رفع محدودیت برنامه باید تایید شود.")
    lock_tenant(db, actor.tenant_id)
    row = db.scalar(
        select(Disruption)
        .where(Disruption.tenant_id == actor.tenant_id, Disruption.id == disruption_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        fail(404, "NOT_FOUND", "اختلال برنامه پیدا نشد.")
    if row.version != data.version:
        fail(409, "STALE_VERSION", "وضعیت اختلال هم‌زمان تغییر کرده است.")
    if row.status != "ACTIVE":
        fail(409, "INVALID_STATE", "این اختلال قبلاً پایان یافته است.")
    row.status, row.resolved_at, row.version = "RESOLVED", now_utc(), row.version + 1
    tenant = ReceptionService(db, actor.tenant_id).tenant()
    capture_policy(db, tenant, actor.id, "baseline_before_disruption_resolution", [])
    tenant.settings_version += 1
    capture_policy(db, tenant, actor.id, data.reason, ["disruption_resolved"])
    audit(
        db,
        actor.tenant_id,
        actor.id,
        "schedule.disruption_resolved",
        "disruption",
        row.id,
        reason_hash=request_digest({"reason": data.reason}),
    )
    db.commit()
    return {
        **disruption_dict(db, row),
        "message": "Schedule block removed; each affected patient's appointment still requires its own recorded decision.",
    }


class ImpactDecisionInput(StrictModel):
    version: int = Field(ge=1)
    decision: Literal["KEEP_ORIGINAL", "CANCEL"]
    reason: str = Field(min_length=3, max_length=500)
    confirmed: bool
    idempotency_key: str = Field(min_length=8, max_length=160)


@router.post("/operations/disruptions/impacts/{impact_id}/decision")
def decide_impact(impact_id: str, data: ImpactDecisionInput, actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    if not data.confirmed:
        fail(422, "CONFIRMATION_REQUIRED", "تصمیم نوبت باید با مراجعه‌کننده تایید شود.")
    lock_tenant(db, actor.tenant_id)
    payload = {"impact_id": impact_id, **data.model_dump()}
    previous = receipt(db, actor, "impact_decision", data.idempotency_key, payload)
    impact = db.scalar(
        select(AppointmentImpact).where(AppointmentImpact.id == impact_id, AppointmentImpact.tenant_id == actor.tenant_id).with_for_update()
    )
    if impact is None:
        fail(404, "NOT_FOUND", "نوبت متاثر پیدا نشد.")
    service = ReceptionService(db, actor.tenant_id, actor.id)
    booking = service.get_appointment(impact.appointment_id, lock=True)
    if previous:
        return service.appointment_dict(booking)
    service._version(booking, data.version)
    if impact.state == "RESOLVED" or booking.attendance or booking.status not in {"CONFIRMED", "PENDING_STAFF_APPROVAL", "PENDING_PAYMENT"}:
        fail(409, "INVALID_STATE", "این تصمیم با وضعیت جاری نوبت سازگار نیست.")
    disruption = db.scalar(select(Disruption).where(Disruption.id == impact.disruption_id, Disruption.tenant_id == actor.tenant_id))
    if data.decision == "KEEP_ORIGINAL":
        if disruption.kind != "LATE_ARRIVAL" and disruption.status != "RESOLVED":
            fail(409, "DISRUPTION_STILL_ACTIVE", "پیش از تایید زمان قبلی، محدودیت برنامه باید رفع شود.")
        if booking.status != "CONFIRMED":
            fail(409, "BOOKING_NOT_CONFIRMED", "پرداخت یا تایید نوبت هنوز کامل نشده است.")
    else:
        booking.status = "CANCELED"
        from .operations_outreach import record_capacity_release

        record_capacity_release(db, booking, "disruption_canceled", booking.version + 1)
        db.execute(
            update(AppointmentImpact)
            .where(
                AppointmentImpact.tenant_id == actor.tenant_id,
                AppointmentImpact.appointment_id == booking.id,
                AppointmentImpact.state != "RESOLVED",
            )
            .values(state="RESOLVED", resolved_at=now_utc())
        )
        db.execute(
            delete(Occupancy).where(
                Occupancy.tenant_id == actor.tenant_id, Occupancy.owner_type == "appointment", Occupancy.owner_id == booking.id
            )
        )
        if booking.payment_status == "PAID":
            db.add(
                StaffTask(
                    tenant_id=actor.tenant_id,
                    reason="REFUND_REVIEW",
                    appointment_id=booking.id,
                    summary="لغو ناشی از اختلال برای نوبت پرداخت‌شده ثبت شد؛ بازپرداخت نیاز به بررسی و اجرای مستقل دارد.",
                )
            )
    booking.version += 1
    impact.state, impact.resolved_at = "RESOLVED", now_utc()
    resolve_schedule_tasks(db, actor.tenant_id, booking.id)
    service._notice(booking, "canceled" if data.decision == "CANCEL" else "confirmed")
    audit(
        db,
        actor.tenant_id,
        actor.id,
        "schedule.patient_decision",
        "appointment",
        booking.id,
        impact_id=impact.id,
        decision=data.decision,
        reason_hash=request_digest({"reason": data.reason}),
    )
    record_receipt(db, actor, "impact_decision", data.idempotency_key, payload, booking.id)
    db.commit()
    return service.appointment_dict(booking)


@router.get("/operations/digest")
def daily_digest(day: date | None = None, actor: Actor = Depends(require_permissions("reports:read")), db: Session = Depends(get_db)):
    from .models_voice import CallSession

    tenant = ReceptionService(db, actor.tenant_id).tenant()
    zone = ZoneInfo(tenant.timezone)
    day = day or now_utc().astimezone(zone).date()
    if day > now_utc().astimezone(zone).date():
        fail(422, "FUTURE_DIGEST", "گزارش روز آینده قابل اندازه‌گیری نیست.")
    begin = datetime.combine(day, time.min, zone)
    end = datetime.combine(day + timedelta(days=1), time.min, zone)
    created = list(
        db.scalars(
            select(Appointment).where(Appointment.tenant_id == tenant.id, Appointment.created_at >= begin, Appointment.created_at < end)
        )
    )
    scheduled = list(
        db.scalars(select(Appointment).where(Appointment.tenant_id == tenant.id, Appointment.start_at >= begin, Appointment.start_at < end))
    )
    events = list(
        db.scalars(select(UsageEvent).where(UsageEvent.tenant_id == tenant.id, UsageEvent.created_at >= begin, UsageEvent.created_at < end))
    )
    cancellations = set(
        db.scalars(
            select(AuditEvent.entity_id).where(
                AuditEvent.tenant_id == tenant.id,
                AuditEvent.action == "appointment.canceled",
                AuditEvent.created_at >= begin,
                AuditEvent.created_at < end,
            )
        )
    )
    for event in db.scalars(
        select(AuditEvent).where(
            AuditEvent.tenant_id == tenant.id,
            AuditEvent.action == "schedule.patient_decision",
            AuditEvent.created_at >= begin,
            AuditEvent.created_at < end,
        )
    ):
        if event.details.get("decision") == "CANCEL":
            cancellations.add(event.entity_id)
    fills = db.scalar(
        select(func.count())
        .select_from(WaitlistOffer)
        .join(Appointment, WaitlistOffer.appointment_id == Appointment.id)
        .where(
            WaitlistOffer.tenant_id == tenant.id,
            Appointment.tenant_id == tenant.id,
            WaitlistOffer.status == "ACCEPTED",
            Appointment.created_at >= begin,
            Appointment.created_at < end,
            Appointment.status == "CONFIRMED",
        )
    )
    open_cases = db.scalar(
        select(func.count()).select_from(StaffTask).where(StaffTask.tenant_id == tenant.id, StaffTask.status.in_(ACTIVE_TASKS))
    )
    call_count = db.scalar(
        select(func.count())
        .select_from(CallSession)
        .where(CallSession.tenant_id == tenant.id, CallSession.started_at >= begin, CallSession.started_at < end)
    )
    minutes = round(sum(call_minutes(event) for event in events), 4)
    metrics = {
        "verified_bookings": sum(row.status == "CONFIRMED" and row.payment_status in {"NOT_REQUIRED", "PAID"} for row in created),
        "attended": sum(row.attendance == "ATTENDED" for row in scheduled),
        "no_shows": sum(row.attendance == "NO_SHOW" for row in scheduled),
        "attendance_unknown": sum(row.attendance is None and row.status == "CONFIRMED" for row in scheduled),
        "cancellations": len(cancellations),
        "waitlist_fills": fills,
        "open_cases": open_cases,
        "call_sessions": call_count,
        "billable_minutes": minutes,
        "sms_submissions": sum(event.quantity for event in events if event.kind == "sms" and event.unit == "message"),
    }
    return {
        "day": day.isoformat(),
        "timezone": tenant.timezone,
        "generated_at": iso(now_utc()),
        "metrics": metrics,
        "usage": {"billable_minutes": minutes, "provider_cost_toman": round(sum(event.cost_toman for event in events), 2)},
        "definitions": {
            "verified_bookings": "Created in this local day and currently confirmed after required settlement/approval; excludes pending and canceled.",
            "attendance": "Appointments scheduled in this local day; unrecorded outcomes remain unknown.",
            "waitlist_fills": "Accepted waitlist appointments created in this local day and currently confirmed.",
            "open_cases": "Unresolved cases as of report generation, not a reconstructed historical backlog.",
            "usage": "Recorded billable call duration only; speech-processing seconds excluded. Provider cost is recorded cost, not a tariff estimate.",
            "delivery": "SMS submissions do not imply delivery. No digest is sent externally by this endpoint.",
        },
    }


class RefundReviewInput(StrictModel):
    action: Literal["REFUSE", "RECONCILE_PENDING", "RECONCILE_FAILED"]
    reason: str = Field(min_length=3, max_length=500)
    provider_reference: str | None = Field(default=None, min_length=6, max_length=120)
    confirmed: bool
    idempotency_key: str = Field(min_length=8, max_length=160)


def resolve_refund_tasks(db: Session, tenant_id: str, payment: PaymentIntent):
    db.flush()
    pending = db.scalar(
        select(RefundLedger.id)
        .where(
            RefundLedger.tenant_id == tenant_id,
            RefundLedger.payment_id == payment.id,
            RefundLedger.status.in_(["REQUESTED", "RECONCILING", "RECONCILIATION_REQUIRED"]),
        )
        .limit(1)
    )
    if pending is not None:
        return
    for task in db.scalars(
        select(StaffTask).where(
            StaffTask.tenant_id == tenant_id,
            StaffTask.appointment_id == payment.appointment_id,
            StaffTask.reason == "REFUND_EXECUTION",
            StaffTask.status.in_(ACTIVE_TASKS),
        )
    ):
        task.status, task.resolved_at, task.resolution = "RESOLVED", now_utc(), "وضعیت درخواست‌های بازپرداخت در دفتر مالی ثبت شد."
        control = db.scalar(select(TaskControl).where(TaskControl.task_id == task.id, TaskControl.tenant_id == tenant_id))
        if control:
            control.version += 1
            control.callback_at = None


@router.post("/operations/refunds/{refund_id}/review")
def review_refund(refund_id: str, data: RefundReviewInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    if not data.confirmed:
        fail(422, "CONFIRMATION_REQUIRED", "نتیجه بررسی مالی باید صریحاً تایید شود.")
    if data.action.startswith("RECONCILE") and not data.provider_reference:
        fail(422, "PROVIDER_EVIDENCE_REQUIRED", "شماره پیگیری واقعی برای تطبیق درگاه لازم است.")
    lock_tenant(db, actor.tenant_id)
    payload = {"refund_id": refund_id, **data.model_dump()}
    previous = receipt(db, actor, "refund_review", data.idempotency_key, payload)
    row = db.scalar(
        select(RefundLedger)
        .where(RefundLedger.id == refund_id, RefundLedger.tenant_id == actor.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        fail(404, "NOT_FOUND", "درخواست بازپرداخت پیدا نشد.")
    if previous:
        return {"id": row.id, "status": row.status, "amount_toman": row.amount_toman}
    if row.status not in {"REQUESTED", "RECONCILING", "RECONCILIATION_REQUIRED"}:
        fail(409, "REFUND_STATE_INVALID", "سابقه نهایی بازپرداخت با این بررسی بازنویسی نمی‌شود.")
    if data.action == "REFUSE" and row.status != "REQUESTED":
        fail(409, "REFUND_OUTCOME_UNCERTAIN", "بازپرداخت در حال تطبیق را بدون مدرک نتیجه نمی‌توان رد یا آزاد کرد.")
    payment = db.scalar(
        select(PaymentIntent).where(PaymentIntent.id == row.payment_id, PaymentIntent.tenant_id == actor.tenant_id).with_for_update()
    )
    row.status = {"REFUSE": "REFUSED", "RECONCILE_PENDING": "RECONCILING", "RECONCILE_FAILED": "FAILED"}[data.action]
    if row.status in {"REFUSED", "FAILED"}:
        reserved = db.execute(
            update(PaymentIntent)
            .where(
                PaymentIntent.tenant_id == actor.tenant_id,
                PaymentIntent.id == payment.id,
                PaymentIntent.refund_reserved_toman >= row.amount_toman,
            )
            .values(refund_reserved_toman=PaymentIntent.refund_reserved_toman - row.amount_toman)
        )
        if reserved.rowcount != 1:
            fail(409, "REFUND_LEDGER_INCONSISTENT", "رزرو مبلغ با دفتر بازپرداخت سازگار نیست؛ بررسی مالی لازم است.")
    db.add(
        RefundReview(
            tenant_id=actor.tenant_id,
            refund_id=row.id,
            actor_id=actor.id,
            action=data.action,
            reason_encrypted=encrypt(data.reason),
            provider_reference=data.provider_reference,
        )
    )
    audit(
        db,
        actor.tenant_id,
        actor.id,
        "refund.reviewed",
        "refund",
        row.id,
        review_action=data.action,
        status=row.status,
        amount_toman=row.amount_toman,
        reason_hash=request_digest({"reason": data.reason}),
    )
    record_receipt(db, actor, "refund_review", data.idempotency_key, payload, row.id)
    resolve_refund_tasks(db, actor.tenant_id, payment)
    db.commit()
    return {
        "id": row.id,
        "status": row.status,
        "amount_toman": row.amount_toman,
        "evidence_type": "staff_recorded_provider_review",
        "external_transfer_performed": False,
    }


class DisputeInput(StrictModel):
    amount_toman: int = Field(gt=0, le=1000000000)
    provider_case_reference: str = Field(min_length=6, max_length=120)
    reason: str = Field(min_length=3, max_length=500)
    confirmed: bool
    idempotency_key: str = Field(min_length=8, max_length=160)


def dispute_dict(db: Session, row: PaymentDispute) -> dict:
    correction = db.scalar(
        select(PaymentAdjustment).where(PaymentAdjustment.tenant_id == row.tenant_id, PaymentAdjustment.dispute_id == row.id)
    )
    return {
        "id": row.id,
        "payment_id": row.payment_id,
        "amount_toman": row.amount_toman,
        "provider_case_reference": row.provider_case_reference,
        "status": row.status,
        "version": row.version,
        "reason": decrypt(row.reason_encrypted),
        "created_at": iso(row.created_at),
        "closed_at": iso(row.closed_at),
        "adjustment": {"id": correction.id, "amount_toman": correction.amount_toman, "kind": correction.kind} if correction else None,
        "verification": "staff_recorded_evidence",
    }


@router.get("/operations/disputes")
def disputes(actor: Actor = Depends(require_permissions("billing:read")), db: Session = Depends(get_db)):
    return [
        dispute_dict(db, row)
        for row in db.scalars(
            select(PaymentDispute).where(PaymentDispute.tenant_id == actor.tenant_id).order_by(PaymentDispute.created_at.desc()).limit(200)
        )
    ]


@router.post("/operations/payments/{payment_id}/disputes", status_code=201)
def create_dispute(payment_id: str, data: DisputeInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    if not data.confirmed:
        fail(422, "CONFIRMATION_REQUIRED", "ثبت اختلاف مالی نیاز به تایید مدارک دارد.")
    lock_tenant(db, actor.tenant_id)
    payload = {"payment_id": payment_id, **data.model_dump()}
    previous = receipt(db, actor, "payment_dispute", data.idempotency_key, payload)
    if previous:
        return dispute_dict(
            db,
            db.scalar(select(PaymentDispute).where(PaymentDispute.id == previous.entity_id, PaymentDispute.tenant_id == actor.tenant_id)),
        )
    payment = db.scalar(
        select(PaymentIntent).where(PaymentIntent.id == payment_id, PaymentIntent.tenant_id == actor.tenant_id).with_for_update()
    )
    if payment is None or payment.settled_at is None or data.amount_toman > payment.amount_toman:
        fail(409, "INVALID_DISPUTE_AMOUNT", "اختلاف باید به پرداخت تسویه‌شده و مبلغ معتبر آن مربوط باشد.")
    if db.scalar(
        select(PaymentDispute.id).where(
            PaymentDispute.tenant_id == actor.tenant_id, PaymentDispute.provider_case_reference == data.provider_case_reference
        )
    ):
        fail(409, "DISPUTE_REFERENCE_REUSED", "این شماره پرونده اختلاف قبلاً ثبت شده است.")
    row = PaymentDispute(
        tenant_id=actor.tenant_id,
        payment_id=payment.id,
        amount_toman=data.amount_toman,
        provider_case_reference=data.provider_case_reference,
        reason_encrypted=encrypt(data.reason),
    )
    db.add(row)
    db.flush()
    db.add(
        StaffTask(
            tenant_id=actor.tenant_id,
            appointment_id=payment.appointment_id,
            reason="PAYMENT_DISPUTE",
            priority="high",
            summary="اختلاف درگاه ثبت شده است؛ تطبیق دفتر مالی و مدارک واقعی ارائه‌دهنده لازم است.",
        )
    )
    audit(db, actor.tenant_id, actor.id, "payment.dispute_opened", "dispute", row.id, payment_id=payment.id, amount_toman=row.amount_toman)
    record_receipt(db, actor, "payment_dispute", data.idempotency_key, payload, row.id)
    db.commit()
    return dispute_dict(db, row)


class DisputeUpdateInput(StrictModel):
    version: int = Field(ge=1)
    status: Literal["UNDER_REVIEW", "WON", "LOST", "CLOSED"]
    reason: str = Field(min_length=3, max_length=500)
    confirmed: bool
    idempotency_key: str = Field(min_length=8, max_length=160)


@router.patch("/operations/disputes/{dispute_id}")
def update_dispute(dispute_id: str, data: DisputeUpdateInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    if not data.confirmed:
        fail(422, "CONFIRMATION_REQUIRED", "نتیجه تطبیق مالی باید تایید شود.")
    lock_tenant(db, actor.tenant_id)
    payload = {"dispute_id": dispute_id, **data.model_dump()}
    previous = receipt(db, actor, "dispute_update", data.idempotency_key, payload)
    row = db.scalar(
        select(PaymentDispute)
        .where(PaymentDispute.id == dispute_id, PaymentDispute.tenant_id == actor.tenant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        fail(404, "NOT_FOUND", "پرونده اختلاف پیدا نشد.")
    if previous:
        return dispute_dict(db, row)
    if row.version != data.version:
        fail(409, "STALE_VERSION", "پرونده اختلاف هم‌زمان تغییر کرده است.")
    transitions = {
        "OPEN": {"UNDER_REVIEW", "WON", "LOST"},
        "UNDER_REVIEW": {"WON", "LOST"},
        "WON": {"CLOSED"},
        "LOST": {"CLOSED"},
        "CLOSED": set(),
    }
    if data.status not in transitions.get(row.status, set()):
        fail(409, "INVALID_DISPUTE_TRANSITION", "نتیجه نهایی مالی با تغییر وضعیت بازنویسی نمی‌شود.")
    if data.status == "LOST":
        payment = db.scalar(select(PaymentIntent).where(PaymentIntent.id == row.payment_id, PaymentIntent.tenant_id == actor.tenant_id))
        prior = db.scalar(
            select(func.coalesce(func.sum(PaymentAdjustment.amount_toman), 0)).where(
                PaymentAdjustment.tenant_id == actor.tenant_id, PaymentAdjustment.payment_id == payment.id
            )
        )
        if -prior + row.amount_toman > payment.amount_toman:
            fail(409, "CHARGEBACK_EXCEEDS_PAYMENT", "مجموع اصلاحات اصل پرداخت از مبلغ آن بیشتر است؛ پرونده باید بررسی شود.")
        db.add(
            PaymentAdjustment(
                tenant_id=actor.tenant_id,
                payment_id=row.payment_id,
                dispute_id=row.id,
                amount_toman=-row.amount_toman,
                actor_id=actor.id,
                reason_encrypted=encrypt(data.reason),
            )
        )
    row.status, row.version = data.status, row.version + 1
    if data.status == "CLOSED":
        row.closed_at = now_utc()
        db.flush()
        remaining = db.scalar(
            select(PaymentDispute.id)
            .where(
                PaymentDispute.tenant_id == actor.tenant_id, PaymentDispute.payment_id == row.payment_id, PaymentDispute.status != "CLOSED"
            )
            .limit(1)
        )
        if remaining is None:
            payment = db.scalar(select(PaymentIntent).where(PaymentIntent.id == row.payment_id, PaymentIntent.tenant_id == actor.tenant_id))
            for task in db.scalars(
                select(StaffTask).where(
                    StaffTask.tenant_id == actor.tenant_id,
                    StaffTask.appointment_id == payment.appointment_id,
                    StaffTask.reason == "PAYMENT_DISPUTE",
                    StaffTask.status.in_(ACTIVE_TASKS),
                )
            ):
                task.status, task.resolved_at, task.resolution = (
                    "RESOLVED",
                    now_utc(),
                    "تمام پرونده‌های اختلاف این پرداخت در دفتر مالی بسته شد.",
                )
                control = db.scalar(select(TaskControl).where(TaskControl.task_id == task.id, TaskControl.tenant_id == actor.tenant_id))
                if control:
                    control.version += 1
                    control.callback_at = None
    audit(
        db,
        actor.tenant_id,
        actor.id,
        "payment.dispute_updated",
        "dispute",
        row.id,
        status=row.status,
        version=row.version,
        reason_encrypted=encrypt(data.reason),
        reason_hash=request_digest({"reason": data.reason}),
    )
    record_receipt(db, actor, "dispute_update", data.idempotency_key, payload, row.id)
    db.commit()
    return dispute_dict(db, row)
