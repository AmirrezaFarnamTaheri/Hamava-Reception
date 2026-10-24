"""Staff API. Tenant scope and role are reconstructed from active memberships."""

import re
from datetime import date as Date
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request
from starlette.concurrency import run_in_threadpool
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from .core import ReceptionService, audit_dict, call_minutes, iso, notification_dict, task_dict
from .db import get_db, now_utc
from .models import (
    Appointment,
    AuditEvent,
    Membership,
    MessageOutbox,
    Practitioner,
    Service,
    StaffTask,
    Tenant,
    UsageEvent,
    User,
)
from .models_voice import RateWindow  # noqa: F401 -- login limiter table registered before schema creation
from .schemas import (
    BookingInput,
    CancelInput,
    ClinicCreate,
    HoldInput,
    LoginInput,
    LogoutInput,
    OutcomeInput,
    PractitionerInput,
    RescheduleInput,
    SettingsInput,
    ServiceInput,
    SwitchInput,
    TaskResolution,
    VersionInput,
)
from .security import (
    Actor,
    actor_for,
    check_password,
    current_actor,
    fail,
    issue_token,
    require_roles,
    require_permissions,
    has_permission,
    ROLE_PERMISSIONS,
)

router = APIRouter(prefix="/api/v1")
STAFF = ("owner", "admin", "manager", "coordinator", "receptionist", "clinician")
staff_actor = require_permissions("appointment:write")


def _login_budget(request: Request, email: str, db: Session):
    # Shared durable buckets prevent replica/restart bypass; no raw email/IP is stored.
    from .voice import digest, rate_limit
    ip = request.client.host if request.client else "unknown"
    rate_limit(db, "login-ip:" + digest(ip), 12, 300)
    rate_limit(db, "login-user:" + digest(email.lower()), 12, 300)


@router.post("/auth/login")
def login(payload: LoginInput, request: Request, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    _login_budget(request, email, db)
    user = db.scalar(select(User).where(User.email == email))
    if not check_password(payload.password, user.password_hash if user else None) or not user or not user.active:
        fail(401, "INVALID_CREDENTIALS", "ایمیل یا رمز عبور درست نیست.")
    membership = db.scalar(
        select(Membership)
        .join(Tenant)
        .where(Membership.user_id == user.id, Membership.active.is_(True), Tenant.active.is_(True))
        .order_by(Membership.tenant_id)
        .limit(1)
    )
    if not membership:
        fail(403, "MEMBERSHIP_REQUIRED", "دسترسی فعالی برای این حساب وجود ندارد.")
    actor = actor_for(db, user, membership.tenant_id)
    return {"access_token": issue_token(user, membership.tenant_id), "token_type": "bearer", "user": actor.as_dict()}


@router.get("/me")
def me(actor: Actor = Depends(current_actor)):
    return actor.as_dict()


@router.get("/permissions")
def permissions(actor: Actor = Depends(current_actor)):
    return {"role": actor.role, "permissions": sorted(ROLE_PERMISSIONS.get(actor.role, ())),
            "roles": [{"role": role, "permissions": sorted(values)} for role, values in ROLE_PERMISSIONS.items()]}


@router.post("/auth/switch")
def switch_tenant(payload: SwitchInput, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    user = db.get(User, actor.user_id)
    new_actor = actor_for(db, user, payload.tenant_id)
    return {"access_token": issue_token(user, payload.tenant_id, session_id=actor.session_id, expires_at=actor.token_expires_at), "token_type": "bearer", "user": new_actor.as_dict()}


@router.post("/auth/logout")
def logout(payload: LogoutInput, actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    from .models_core import StaffTokenRevocation

    # Lock the account to serialize simultaneous sign-outs and all-device revocation.
    db.execute(update(User).where(User.id == actor.id).values(token_version=User.token_version))
    if payload.all_devices:
        db.execute(update(User).where(User.id == actor.id).values(token_version=User.token_version + 1))
    elif not db.get(StaffTokenRevocation, actor.session_id):
        db.add(StaffTokenRevocation(session_id=actor.session_id, user_id=actor.id, expires_at=actor.token_expires_at))
    db.add(AuditEvent(tenant_id=actor.tenant_id, actor_id=actor.id, action="auth.logout",
                      entity_type="user", entity_id=actor.id, details={"scope": "all_devices" if payload.all_devices else "session"}))
    db.commit()
    return {"status": "SIGNED_OUT", "scope": "all_devices" if payload.all_devices else "session"}


@router.get("/clinics")
def clinics(actor: Actor = Depends(current_actor), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Tenant, Membership)
        .join(Membership, Membership.tenant_id == Tenant.id)
        .where(Membership.user_id == actor.user_id, Membership.active.is_(True), Tenant.active.is_(True))
    ).all()
    return [
        {"id": t.id, "name": t.name, "slug": t.slug, "role": m.role, "timezone": t.timezone,
         "settings_version": t.settings_version, "building_id": t.building_id if m.role == "owner" else None}
        for t, m in rows
    ]


@router.get("/practitioners")
def practitioners(include_inactive: bool = False, actor: Actor = Depends(require_permissions("catalog:read")), db: Session = Depends(get_db)):
    if include_inactive and not has_permission(actor, "catalog:write"):
        fail(403, "ROLE_REQUIRED", "مشاهده فهرست کامل نیاز به دسترسی مدیر دارد.")
    query = select(Practitioner).where(Practitioner.tenant_id == actor.tenant_id)
    if not include_inactive:
        query = query.where(Practitioner.active.is_(True))
    return [
        {"id": r.id, "name": r.name, "specialty": r.specialty, "active": r.active, "working_hours": r.working_hours}
        for r in db.scalars(query.order_by(Practitioner.name))
    ]


@router.get("/services")
def services(include_inactive: bool = False, actor: Actor = Depends(require_permissions("catalog:read")), db: Session = Depends(get_db)):
    if include_inactive and not has_permission(actor, "catalog:write"):
        fail(403, "ROLE_REQUIRED", "مشاهده فهرست کامل نیاز به دسترسی مدیر دارد.")
    query = select(Service).where(Service.tenant_id == actor.tenant_id)
    if not include_inactive:
        query = query.where(Service.active.is_(True))
    return [
        {
            "id": r.id,
            "name": r.name,
            "provider_ids": r.provider_ids,
            "resource_ids": r.resource_ids,
            "active": r.active,
            "duration_minutes": r.duration_minutes,
            "buffer_minutes": r.buffer_minutes,
            "price_toman": r.price_toman,
            "deposit_toman": r.deposit_toman,
            "requires_approval": r.requires_approval,
            "description": r.description,
        }
        for r in db.scalars(query.order_by(Service.name))
    ]


@router.get("/slots")
async def slots(provider_id: str, service_id: str, date: Date, actor: Actor = Depends(staff_actor), db: Session = Depends(get_db)):
    from .calendar_bridge import is_external, slots as external_slots
    if is_external(db, actor.tenant_id):
        return await external_slots(db, actor, provider_id, service_id, date)
    return await run_in_threadpool(ReceptionService(db, actor.tenant_id, actor.id).slots, provider_id, service_id, date)


@router.post("/holds", status_code=201)
async def hold(payload: HoldInput, actor: Actor = Depends(staff_actor), db: Session = Depends(get_db)):
    from .calendar_bridge import is_external, hold_slot
    if is_external(db, actor.tenant_id):
        import hashlib
        value = payload.model_dump()
        value["idempotency_key"] = payload.idempotency_key or "staff-hold:" + actor.id + ":" + hashlib.sha256(payload.slot_id.encode()).hexdigest()[:40]
        return await hold_slot(db, actor, value)
    return await run_in_threadpool(ReceptionService(db, actor.tenant_id, actor.id).hold, payload.slot_id, payload.session_id or f"staff:{actor.id}")


@router.get("/appointments")
def appointments(
    date: Date | None = None,
    status: str | None = Query(default=None, max_length=40),
    actor: Actor = Depends(staff_actor),
    db: Session = Depends(get_db),
):
    from .calendar_bridge import is_external, list_bookings
    if is_external(db, actor.tenant_id):
        return list_bookings(db, actor.tenant_id, day=date, status=status)
    service = ReceptionService(db, actor.tenant_id, actor.id)
    service.expire()
    query = select(Appointment).where(Appointment.tenant_id == actor.tenant_id)
    if date:
        zone = ZoneInfo(service.tenant().timezone)
        start = datetime.combine(date, time.min, zone)
        query = query.where(Appointment.start_at >= start, Appointment.start_at < start + timedelta(days=1))
    if status:
        query = query.where(Appointment.status == status)
    return [service.appointment_dict(row) for row in db.scalars(query.order_by(Appointment.start_at.desc()).limit(250))]


@router.get("/appointments/{appointment_id}")
async def read_appointment(appointment_id: str, actor: Actor = Depends(require_permissions("appointment:read")), db: Session = Depends(get_db)):
    from .calendar_bridge import is_external, read_booking
    if is_external(db, actor.tenant_id):
        return await read_booking(db, actor, appointment_id.removeprefix("external:"))
    service = ReceptionService(db, actor.tenant_id, actor.id)
    return service.appointment_dict(service.get_appointment(appointment_id))


@router.post("/appointments", status_code=201)
async def create_appointment(payload: BookingInput, actor: Actor = Depends(staff_actor), db: Session = Depends(get_db)):
    from .calendar_bridge import is_external, create_booking
    if is_external(db, actor.tenant_id):
        return await create_booking(db, actor, payload.model_dump())
    return await run_in_threadpool(ReceptionService(db, actor.tenant_id, actor.id).create_appointment, **payload.model_dump())


@router.post("/appointments/{appointment_id}/cancel")
async def cancel(appointment_id: str, payload: CancelInput, actor: Actor = Depends(staff_actor), db: Session = Depends(get_db)):
    from .calendar_bridge import is_external, change_booking
    if is_external(db, actor.tenant_id):
        return await change_booking(db, actor, appointment_id.removeprefix("external:"), "cancel", payload.model_dump())
    return await run_in_threadpool(ReceptionService(db, actor.tenant_id, actor.id).cancel_appointment, appointment_id, **payload.model_dump(), verified=True)


@router.post("/appointments/{appointment_id}/reschedule")
async def reschedule(appointment_id: str, payload: RescheduleInput, actor: Actor = Depends(staff_actor), db: Session = Depends(get_db)):
    from .calendar_bridge import is_external, change_booking
    values = payload.model_dump(exclude={"reason"})
    if is_external(db, actor.tenant_id):
        return await change_booking(db, actor, appointment_id.removeprefix("external:"), "update", values)
    return await run_in_threadpool(ReceptionService(db, actor.tenant_id, actor.id).reschedule_appointment, appointment_id, **values, verified=True)


@router.post("/appointments/{appointment_id}/approve")
def approve(appointment_id: str, payload: VersionInput, actor: Actor = Depends(staff_actor), db: Session = Depends(get_db)):
    return ReceptionService(db, actor.tenant_id, actor.id).approve(appointment_id, payload.version)


@router.patch("/appointments/{appointment_id}/outcome")
def outcome(appointment_id: str, payload: OutcomeInput, actor: Actor = Depends(staff_actor), db: Session = Depends(get_db)):
    return ReceptionService(db, actor.tenant_id, actor.id).outcome(appointment_id, **payload.model_dump())


@router.get("/tasks")
def tasks(status: str | None = Query(default=None, max_length=30), actor: Actor = Depends(staff_actor), db: Session = Depends(get_db)):
    query = select(StaffTask).where(StaffTask.tenant_id == actor.tenant_id)
    if status:
        query = query.where(StaffTask.status == status)
    return [task_dict(row) for row in db.scalars(query.order_by(StaffTask.created_at.desc()).limit(200))]


@router.post("/tasks/{task_id}/resolve")
def resolve_task(task_id: str, payload: TaskResolution, actor: Actor = Depends(staff_actor), db: Session = Depends(get_db)):
    from .operations_extensions import legacy_resolve_task

    return legacy_resolve_task(db, actor, task_id, payload.resolution)


@router.get("/notifications")
def notifications(actor: Actor = Depends(staff_actor), db: Session = Depends(get_db)):
    return [
        notification_dict(row)
        for row in db.scalars(
            select(MessageOutbox).where(MessageOutbox.tenant_id == actor.tenant_id).order_by(MessageOutbox.created_at.desc()).limit(200)
        )
    ]


@router.get("/audit")
def audit(actor: Actor = Depends(require_permissions("audit:read")), db: Session = Depends(get_db)):
    return [
        audit_dict(row)
        for row in db.scalars(
            select(AuditEvent).where(AuditEvent.tenant_id == actor.tenant_id).order_by(AuditEvent.created_at.desc()).limit(200)
        )
    ]


@router.get("/settings")
def get_settings(actor: Actor = Depends(require_permissions("policy:read")), db: Session = Depends(get_db)):
    return ReceptionService(db, actor.tenant_id, actor.id).settings_dict()


@router.put("/settings")
def save_settings(payload: SettingsInput, actor: Actor = Depends(require_permissions("policy:write")), db: Session = Depends(get_db)):
    return ReceptionService(db, actor.tenant_id, actor.id).update_settings(payload.model_dump(exclude_unset=True))


@router.get("/usage")
def usage(actor: Actor = Depends(require_permissions("billing:read")), db: Session = Depends(get_db)):
    start = now_utc().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = list(
        db.scalars(
            select(UsageEvent)
            .where(UsageEvent.tenant_id == actor.tenant_id, UsageEvent.created_at >= start)
            .order_by(UsageEvent.created_at.desc())
        )
    )
    return {
        "period": start.strftime("%Y-%m"),
        "minutes": round(sum(call_minutes(r) for r in rows), 2),
        "calls": sum(r.quantity for r in rows if r.kind == "call" and r.unit == "count"),
        "bookings": sum(r.quantity for r in rows if r.kind == "booking"),
        "events": [
            {
                "id": r.id,
                "kind": r.kind,
                "quantity": r.quantity,
                "unit": r.unit,
                "cost_toman": r.cost_toman,
                "created_at": iso(r.created_at),
            }
            for r in rows[:200]
        ],
    }


@router.get("/dashboard")
def dashboard(actor: Actor = Depends(staff_actor), db: Session = Depends(get_db)):
    from .models_voice import CallSession
    from .operations_extensions import ACTIVE_TASKS, extended_task

    service = ReceptionService(db, actor.tenant_id, actor.id)
    service.expire()
    tenant = service.tenant()
    local_now = now_utc().astimezone(ZoneInfo(tenant.timezone))
    begin = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    todays = list(
        db.scalars(
            select(Appointment)
            .where(Appointment.tenant_id == tenant.id, Appointment.start_at >= begin, Appointment.start_at < begin + timedelta(days=1))
            .order_by(Appointment.start_at)
        )
    )
    open_tasks = list(
        db.scalars(
            select(StaffTask)
            .where(StaffTask.tenant_id == tenant.id, StaffTask.status.in_(ACTIVE_TASKS))
            .order_by(StaffTask.created_at.desc())
            .limit(50)
        )
    )
    failed = list(
        db.scalars(
            select(MessageOutbox)
            .where(MessageOutbox.tenant_id == tenant.id, MessageOutbox.status.in_(["FAILED", "UNKNOWN"]))
            .order_by(MessageOutbox.created_at.desc())
            .limit(20)
        )
    )
    activity = list(
        db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant.id).order_by(AuditEvent.created_at.desc()).limit(12))
    )
    minute_events = list(db.scalars(select(UsageEvent).where(UsageEvent.tenant_id == tenant.id, UsageEvent.created_at >= begin)))
    return {
        "clinic": {
            "id": tenant.id,
            "name": tenant.name,
            "timezone": tenant.timezone,
            "mode": tenant.mode,
            "settings_version": tenant.settings_version,
        },
        "date": local_now.date().isoformat(),
        "metrics": {
            "appointments_today": len(todays),
            "confirmed_today": sum(r.status == "CONFIRMED" for r in todays),
            "pending_tasks": db.scalar(select(func.count()).select_from(StaffTask).where(StaffTask.tenant_id == tenant.id, StaffTask.status.in_(ACTIVE_TASKS))),
            "active_calls": db.scalar(select(func.count()).select_from(CallSession).where(CallSession.tenant_id == tenant.id,
                CallSession.ended_at.is_(None), CallSession.expires_at > now_utc())),
            "notifications_failed": len(failed),
            "minutes_used": round(sum(call_minutes(r) for r in minute_events), 2),
        },
        "appointments": [service.appointment_dict(r) for r in todays],
        "tasks": [extended_task(db, r) for r in open_tasks],
        "notifications": [notification_dict(r) for r in failed],
        "recent_activity": [audit_dict(r) for r in activity],
    }


@router.post("/clinics", status_code=201)
def create_clinic(payload: ClinicCreate, actor: Actor = Depends(require_roles("owner")), db: Session = Depends(get_db)):
    from .operations_uat import enforced

    tenant = Tenant(**payload.model_dump(), timezone="Asia/Tehran", mode="paused" if enforced() else "human_primary", working_hours={}, faq=[], holidays=[])
    db.add(tenant)
    try:
        db.flush()
        db.add(Membership(user_id=actor.id, tenant_id=tenant.id, role="owner"))
        db.add(
            AuditEvent(
                tenant_id=tenant.id,
                actor_id=actor.id,
                action="clinic.created",
                entity_type="tenant",
                entity_id=tenant.id,
                details={"onboarding_required": True},
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "SLUG_IN_USE", "این نشانی مرکز قبلاً انتخاب شده است.")
    return {
        "id": tenant.id,
        "name": tenant.name,
        "slug": tenant.slug,
        "role": "owner",
        "timezone": tenant.timezone,
        "settings_version": tenant.settings_version,
        "mode": tenant.mode,
    }


def _catalog_revision(db: Session, actor: Actor, entity: str, entity_id: str):
    from .core_policy import publish_facts, subject

    tenant = db.get(Tenant, actor.tenant_id)
    publish_facts(db, actor.tenant_id, entity, subject(db, actor.tenant_id, entity, entity_id), actor.id)
    db.execute(update(Tenant).where(Tenant.id == actor.tenant_id).values(settings_version=Tenant.settings_version + 1))
    db.refresh(tenant)
    db.add(
        AuditEvent(
            tenant_id=actor.tenant_id,
            actor_id=actor.id,
            action="catalog.published",
            entity_type=entity,
            entity_id=entity_id,
            details={"settings_version": tenant.settings_version},
        )
    )


@router.post("/practitioners", status_code=201)
def create_practitioner(data: PractitionerInput, actor: Actor = Depends(require_permissions("catalog:write")), db: Session = Depends(get_db)):
    from .operations_uat import require_catalog_edit_safe

    require_catalog_edit_safe(db, actor.tenant_id)
    db.execute(update(Tenant).where(Tenant.id == actor.tenant_id).values(settings_version=Tenant.settings_version))
    row = Practitioner(tenant_id=actor.tenant_id, **data.model_dump())
    db.add(row)
    db.flush()
    _catalog_revision(db, actor, "practitioner", row.id)
    db.commit()
    return {"id": row.id, **data.model_dump()}


@router.put("/practitioners/{provider_id}")
def update_practitioner(
    provider_id: str, data: PractitionerInput, actor: Actor = Depends(require_permissions("catalog:write")), db: Session = Depends(get_db)
):
    from .operations_uat import require_catalog_edit_safe

    require_catalog_edit_safe(db, actor.tenant_id)
    db.execute(update(Tenant).where(Tenant.id == actor.tenant_id).values(settings_version=Tenant.settings_version))
    row = db.scalar(select(Practitioner).where(Practitioner.id == provider_id, Practitioner.tenant_id == actor.tenant_id))
    if not row:
        fail(404, "NOT_FOUND", "پزشک پیدا نشد.")
    if not data.active and db.scalar(
        select(Appointment.id)
        .where(
            Appointment.tenant_id == actor.tenant_id,
            Appointment.provider_id == row.id,
            Appointment.status.in_(["CONFIRMED", "PENDING_PAYMENT", "PENDING_STAFF_APPROVAL"]),
            Appointment.start_at > now_utc(),
        )
        .limit(1)
    ):
        fail(409, "FUTURE_BOOKINGS_REQUIRE_REVIEW", "پزشک نوبت آینده دارد؛ ابتدا جابه‌جایی آن‌ها را هماهنگ کنید.")
    changes = data.model_dump(exclude_unset=True)
    if "working_hours" in changes and changes["working_hours"] is not None and changes["working_hours"] != row.working_hours:
        zone = ZoneInfo(db.get(Tenant, actor.tenant_id).timezone)
        future = db.scalars(select(Appointment).where(Appointment.tenant_id == actor.tenant_id,
            Appointment.provider_id == row.id, Appointment.status.in_(["CONFIRMED", "PENDING_PAYMENT", "PENDING_STAFF_APPROVAL"]),
            Appointment.occupied_until > now_utc())).all()
        for appointment in future:
            start, end = appointment.start_at.astimezone(zone), appointment.occupied_until.astimezone(zone)
            covered = start.date() == end.date() and any(
                datetime.combine(start.date(), time.fromisoformat(opening), zone) <= start
                and end <= datetime.combine(start.date(), time.fromisoformat(closing), zone)
                for opening, closing in changes["working_hours"].get(str(start.weekday()), []))
            if not covered:
                fail(409, "FUTURE_BOOKINGS_REQUIRE_REVIEW", "ساعت جدید با نوبت ثبت‌شده ناسازگار است؛ ابتدا جابه‌جایی آن را هماهنگ کنید.")
    for key, value in changes.items():
        setattr(row, key, value)
    _catalog_revision(db, actor, "practitioner", row.id)
    db.commit()
    return {"id": row.id, "name": row.name, "specialty": row.specialty, "active": row.active, "working_hours": row.working_hours}


def _validate_service(db: Session, tenant_id: str, data: ServiceInput):
    ids = set(
        db.scalars(
            select(Practitioner.id).where(
                Practitioner.tenant_id == tenant_id, Practitioner.id.in_(data.provider_ids), Practitioner.active.is_(True)
            )
        )
    )
    if ids != set(data.provider_ids) or data.deposit_toman > data.price_toman:
        fail(422, "INVALID_SERVICE_POLICY", "پزشکان باید متعلق به مرکز باشند و بیعانه از قیمت بیشتر نباشد.")
    if any(not re.fullmatch(r"[a-zA-Z0-9_-]{1,60}", r) for r in data.resource_ids):
        fail(422, "INVALID_RESOURCE", "شناسه اتاق یا تجهیزات باید کوتاه و بدون فاصله باشد.")


@router.post("/services", status_code=201)
def create_service(data: ServiceInput, actor: Actor = Depends(require_permissions("catalog:write")), db: Session = Depends(get_db)):
    from .operations_uat import require_catalog_edit_safe

    require_catalog_edit_safe(db, actor.tenant_id)
    _validate_service(db, actor.tenant_id, data)
    row = Service(tenant_id=actor.tenant_id, **data.model_dump())
    db.add(row)
    db.flush()
    _catalog_revision(db, actor, "service", row.id)
    db.commit()
    return {"id": row.id, **data.model_dump()}


@router.put("/services/{service_id}")
def update_service(
    service_id: str, data: ServiceInput, actor: Actor = Depends(require_permissions("catalog:write")), db: Session = Depends(get_db)
):
    from .operations_uat import require_catalog_edit_safe

    require_catalog_edit_safe(db, actor.tenant_id)
    _validate_service(db, actor.tenant_id, data)
    row = db.scalar(select(Service).where(Service.id == service_id, Service.tenant_id == actor.tenant_id))
    if not row:
        fail(404, "NOT_FOUND", "خدمت پیدا نشد.")
    future = db.scalar(
        select(Appointment.id)
        .where(
            Appointment.tenant_id == actor.tenant_id,
            Appointment.service_id == row.id,
            Appointment.status.in_(["CONFIRMED", "PENDING_PAYMENT", "PENDING_STAFF_APPROVAL"]),
            Appointment.start_at > now_utc(),
        )
        .limit(1)
    )
    if future and (not data.active or set(data.resource_ids) != set(row.resource_ids)):
        fail(409, "FUTURE_BOOKINGS_REQUIRE_REVIEW", "تغییر تجهیزات یا حذف خدمت دارای نوبت آینده نیاز به بررسی دارد.")
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    _catalog_revision(db, actor, "service", row.id)
    db.commit()
    return {"id": row.id, **data.model_dump()}
