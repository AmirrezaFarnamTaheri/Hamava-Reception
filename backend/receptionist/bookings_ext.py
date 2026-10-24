"""Patient eligibility, package entitlements and resumable bounded booking series."""
import json
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .core import ReceptionService, request_digest
from .core_policy import lock, service_policy
from .db import get_db, now_utc
from .models import Appointment, AuditEvent, Service
from .models_core import BookingSeries, PackageEntitlement, PackageUse
from .schemas import BookingInput, StrictModel
from .security import Actor, decrypt, encrypt, fail, hash_phone, require_permissions

router = APIRouter(prefix="/api/v1")


def check_eligibility(db, tenant_id, service, phone_hash, *, at, entitlement_id=None, existing_units=0):
    rules = service_policy(db, tenant_id, service.id, checked=True)
    prior_service = rules["prerequisite_service_id"] or service.id
    prior = db.scalar(select(Appointment).where(Appointment.tenant_id == tenant_id,
        Appointment.phone_hash == phone_hash, Appointment.service_id == prior_service,
        Appointment.attendance == "ATTENDED", Appointment.start_at < at)
        .order_by(Appointment.start_at.desc()).limit(1))
    if rules["visit_policy"] == "first_visit" and prior:
        fail(409, "FIRST_VISIT_ONLY", "این خدمت مخصوص مراجعه اول است؛ نوع خدمت را با پذیرش بررسی کنید.")
    if rules["visit_policy"] == "follow_up" and (not prior or at - prior.start_at > timedelta(days=rules["follow_up_days"])):
        fail(409, "FOLLOW_UP_NOT_ELIGIBLE", "مراجعه قبلی واجد شرایط پیگیری پیدا نشد؛ پذیرش باید بررسی کند.")
    if rules["visit_policy"] != "package":
        if entitlement_id:
            fail(422, "PACKAGE_NOT_APPLICABLE", "این خدمت از بسته جلسه استفاده نمی‌کند.")
        return None, 0
    query = select(PackageEntitlement).where(PackageEntitlement.tenant_id == tenant_id,
        PackageEntitlement.phone_hash == phone_hash, PackageEntitlement.status == "ACTIVE",
        PackageEntitlement.expires_at > max(now_utc(), at)).order_by(PackageEntitlement.expires_at, PackageEntitlement.id)
    if entitlement_id:
        query = query.where(PackageEntitlement.id == entitlement_id)
    for entitlement in db.scalars(query.with_for_update().execution_options(populate_existing=True)):
        if service.id in entitlement.service_ids and entitlement.total_units - entitlement.used_units + existing_units >= rules["package_units"]:
            return entitlement, rules["package_units"]
    fail(409, "PACKAGE_ENTITLEMENT_REQUIRED", "اعتبار کافی و معتبر برای این جلسه پیدا نشد؛ پذیرش باید بررسی کند.")


def consume_package(db, booking, entitlement, units):
    if not entitlement:
        return
    changed = db.execute(update(PackageEntitlement).where(PackageEntitlement.id == entitlement.id,
        PackageEntitlement.tenant_id == booking.tenant_id, PackageEntitlement.status == "ACTIVE",
        PackageEntitlement.used_units + units <= PackageEntitlement.total_units)
        .values(used_units=PackageEntitlement.used_units + units))
    if changed.rowcount != 1:
        fail(409, "PACKAGE_ENTITLEMENT_REQUIRED", "اعتبار بسته هم‌زمان استفاده شد؛ پذیرش باید بررسی کند.")
    db.add(PackageUse(appointment_id=booking.id, tenant_id=booking.tenant_id, entitlement_id=entitlement.id, units=units))


def release_package(db, tenant_id, appointment_id):
    use = db.scalar(select(PackageUse).where(PackageUse.appointment_id == appointment_id, PackageUse.tenant_id == tenant_id).with_for_update())
    if not use or use.released:
        return
    use.released = True
    db.execute(update(PackageEntitlement).where(PackageEntitlement.id == use.entitlement_id,
        PackageEntitlement.tenant_id == tenant_id, PackageEntitlement.used_units >= use.units)
        .values(used_units=PackageEntitlement.used_units - use.units))


class EntitlementInput(StrictModel):
    phone: str = Field(min_length=8, max_length=30)
    service_ids: list[str] = Field(min_length=1, max_length=50)
    total_units: int = Field(ge=1, le=1000)
    expires_at: datetime
    reference: str = Field(min_length=2, max_length=100)
    reason: str = Field(min_length=3, max_length=500)
    idempotency_key: str = Field(min_length=8, max_length=160)


def entitlement_dict(row):
    return {"id": row.id, "service_ids": row.service_ids, "total_units": row.total_units,
            "used_units": row.used_units, "remaining_units": row.total_units - row.used_units,
            "expires_at": row.expires_at.isoformat(), "status": row.status, "reference": row.reference,
            "source": "authorized_entitlement", "payment_verified": False}


@router.post("/package-entitlements", status_code=201)
def issue_entitlement(body: EntitlementInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    lock(db, actor.tenant_id)
    request = body.model_dump(mode="json")
    request["phone"] = hash_phone(body.phone)
    checksum = request_digest(request)
    row = db.scalar(select(PackageEntitlement).where(PackageEntitlement.tenant_id == actor.tenant_id,
        PackageEntitlement.idempotency_key == body.idempotency_key))
    if row:
        if row.request_hash != checksum:
            fail(409, "IDEMPOTENCY_MISMATCH", "کلید درخواست قبلاً برای محتوای دیگری استفاده شده است.")
        return entitlement_dict(row)
    if body.expires_at.tzinfo is None or body.expires_at <= now_utc():
        fail(422, "INVALID_EXPIRY", "تاریخ اعتبار باید در آینده و دارای منطقه زمانی باشد.")
    services = set(db.scalars(select(Service.id).where(Service.tenant_id == actor.tenant_id, Service.id.in_(body.service_ids))))
    if services != set(body.service_ids):
        fail(422, "INVALID_SERVICE", "خدمت بسته باید متعلق به همین مرکز باشد.")
    row = PackageEntitlement(tenant_id=actor.tenant_id, phone_hash=hash_phone(body.phone), service_ids=sorted(services),
        total_units=body.total_units, used_units=0, expires_at=body.expires_at, status="ACTIVE", reference=body.reference,
        reason_encrypted=encrypt(body.reason), idempotency_key=body.idempotency_key, request_hash=checksum, created_by=actor.id)
    db.add(row)
    db.flush()
    db.add(AuditEvent(tenant_id=actor.tenant_id, actor_id=actor.id, action="package.entitlement_issued", entity_type="package",
        entity_id=row.id, details={"units": row.total_units, "reason_encrypted": encrypt(body.reason), "payment_verified": False}))
    db.commit()
    return entitlement_dict(row)


@router.get("/package-entitlements")
def entitlements(phone: str, actor: Actor = Depends(require_permissions("billing:read")), db: Session = Depends(get_db)):
    return [entitlement_dict(row) for row in db.scalars(select(PackageEntitlement).where(
        PackageEntitlement.tenant_id == actor.tenant_id, PackageEntitlement.phone_hash == hash_phone(phone)).order_by(PackageEntitlement.expires_at).limit(100))]


class SeriesInput(StrictModel):
    idempotency_key: str = Field(min_length=8, max_length=140)
    bookings: list[BookingInput] = Field(min_length=1, max_length=12)


def series_dict(db, row):
    outcomes = []
    for item in row.outcomes:
        current = dict(item)
        if current.get("appointment_id"):
            appointment = db.scalar(select(Appointment).where(Appointment.tenant_id == row.tenant_id, Appointment.id == current["appointment_id"]))
            if appointment:
                current["booking"] = ReceptionService(db, row.tenant_id).appointment_dict(appointment)
                current["status"] = appointment.status
        outcomes.append(current)
    return {"id": row.id, "status": row.status, "outcomes": outcomes,
            "requested": len(json.loads(decrypt(row.request_encrypted))["bookings"]),
            "completed": sum(bool(item.get("appointment_id")) for item in outcomes), "created_at": row.created_at.isoformat()}


def run_series(db, actor, row):
    lock(db, actor.tenant_id)
    db.refresh(row)
    if row.status in {"COMPLETED", "PARTIAL", "FAILED"}:
        result = series_dict(db, row)
        db.commit()
        return result
    if row.lease_until and row.lease_until > now_utc():
        fail(409, "SERIES_BUSY", "ثبت جلسه‌ها در حال بررسی است؛ نتیجه را دوباره بخوانید.")
    lease = secrets.token_urlsafe(24)
    row.lease_token, row.lease_until = lease, now_utc() + timedelta(minutes=2)
    db.commit()
    request = json.loads(decrypt(row.request_encrypted))
    for index, item in enumerate(request["bookings"]):
        db.refresh(row)
        if any(outcome["index"] == index for outcome in row.outcomes):
            continue
        values = dict(item)
        # Child identity is owned by the durable parent, never by client retry timing.
        values["idempotency_key"] = f"series:{row.id}:{index}"
        try:
            result = ReceptionService(db, actor.tenant_id, actor.id).create_appointment(**values)
            outcome = {"index": index, "appointment_id": result["id"], "status": result["status"]}
        except HTTPException as exc:
            db.rollback()
            code = exc.detail.get("code", "BOOKING_REJECTED") if isinstance(exc.detail, dict) else "BOOKING_REJECTED"
            if exc.status_code >= 500:
                # An interrupted series resumes with the same child key; never assume failure means no booking.
                lock(db, actor.tenant_id)
                db.refresh(row)
                if row.lease_token == lease:
                    row.lease_until = None
                    db.commit()
                return series_dict(db, row)
            outcome = {"index": index, "appointment_id": None, "status": "REJECTED", "code": code}
        lock(db, actor.tenant_id)
        db.refresh(row)
        if row.lease_token != lease:
            fail(409, "SERIES_LEASE_LOST", "بررسی جلسه‌ها در نشست دیگری ادامه دارد.")
        row.outcomes = [*row.outcomes, outcome]
        row.lease_until = now_utc() + timedelta(minutes=2)
        db.commit()
    lock(db, actor.tenant_id)
    db.refresh(row)
    if row.lease_token != lease:
        fail(409, "SERIES_LEASE_LOST", "بررسی جلسه‌ها در نشست دیگری ادامه دارد.")
    successes = sum(bool(item.get("appointment_id")) for item in row.outcomes)
    row.status = "COMPLETED" if successes == len(request["bookings"]) else "PARTIAL" if successes else "FAILED"
    row.lease_token = row.lease_until = None
    db.add(AuditEvent(tenant_id=actor.tenant_id, actor_id=actor.id, action="booking.series_completed", entity_type="series",
        entity_id=row.id, details={"status": row.status, "requested": len(request["bookings"]), "succeeded": successes}))
    db.commit()
    return series_dict(db, row)


@router.post("/booking-series", status_code=201)
def create_series(body: SeriesInput, actor: Actor = Depends(require_permissions("appointment:write")), db: Session = Depends(get_db)):
    lock(db, actor.tenant_id)
    from .models_core import CalendarAuthority
    authority = db.get(CalendarAuthority, actor.tenant_id)
    if authority and authority.kind != "internal":
        fail(409, "EXTERNAL_SERIES_REQUIRES_INDIVIDUAL_CONFIRMATION", "تقویم بیرونی باید هر جلسه را جداگانه تایید کند.")
    request = body.model_dump(mode="json")
    checksum = request_digest(request)
    row = db.scalar(select(BookingSeries).where(BookingSeries.tenant_id == actor.tenant_id, BookingSeries.idempotency_key == body.idempotency_key))
    if row:
        if row.request_hash != checksum:
            fail(409, "IDEMPOTENCY_MISMATCH", "محتوای مجموعه جلسات تغییر کرده است.")
    else:
        phones = {hash_phone(b.phone) for b in body.bookings}
        if len(phones) != 1:
            fail(422, "SERIES_SUBJECT_MISMATCH", "مجموعه جلسه‌ها باید برای یک شماره تاییدشده باشد.")
        for booking in body.bookings:
            _, _, service, _, _ = ReceptionService(db, actor.tenant_id)._decode_slot(booking.slot_id)
            if len(body.bookings) > service_policy(db, actor.tenant_id, service.id, checked=True)["max_series"]:
                fail(422, "SERIES_LIMIT", "تعداد جلسه‌ها از سیاست این خدمت بیشتر است.")
        row = BookingSeries(tenant_id=actor.tenant_id, idempotency_key=body.idempotency_key,
            request_hash=checksum, request_encrypted=encrypt(json.dumps(request, ensure_ascii=False)), phone_hash=phones.pop(),
            status="RUNNING", outcomes=[], created_by=actor.id)
        db.add(row)
    db.commit()
    return run_series(db, actor, row)


@router.get("/booking-series/{series_id}")
def get_series(series_id: str, actor: Actor = Depends(require_permissions("appointment:read")), db: Session = Depends(get_db)):
    row = db.scalar(select(BookingSeries).where(BookingSeries.id == series_id, BookingSeries.tenant_id == actor.tenant_id))
    if not row:
        fail(404, "SERIES_NOT_FOUND", "مجموعه جلسه‌ها پیدا نشد.")
    return series_dict(db, row)


@router.post("/booking-series/{series_id}/resume")
def resume_series(series_id: str, actor: Actor = Depends(require_permissions("appointment:write")), db: Session = Depends(get_db)):
    row = db.scalar(select(BookingSeries).where(BookingSeries.id == series_id, BookingSeries.tenant_id == actor.tenant_id))
    if not row:
        fail(404, "SERIES_NOT_FOUND", "مجموعه جلسه‌ها پیدا نشد.")
    return run_series(db, actor, row)
