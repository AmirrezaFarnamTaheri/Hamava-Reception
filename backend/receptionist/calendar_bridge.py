"""Durable external-calendar authority and reconciliation.

Internal occupancy is never consulted for an external-authority tenant. A remote
write is sent at most once per operation; a lost response creates a durable
UNKNOWN state. Recovery performs provider lookup/readback, never a blind retry.
"""
import asyncio
import hashlib
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import Literal

import jwt
from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .calendar_contract import HTTPPartnerCalendar, RemoteHold
from .config import settings
from .core import ReceptionService, request_digest
from .core_policy import lock, revise, service_policy
from .db import get_db, now_utc
from .models import Appointment, AuditEvent, Practitioner, Service, SlotHold, StaffTask, Tenant
from .models_core import CalendarAuthority, CalendarChangeReceipt, CalendarSyncState, ExternalCalendarOperation
from .provider_control import ProviderContext, require_capability
from .providers import ProviderError, verify_webhook
from .schemas import StrictModel
from .security import Actor, decrypt, encrypt, fail, hash_phone, require_permissions

router = APIRouter(prefix="/api/v1")
WRITES = {"hold", "release", "create", "cancel", "update"}
PENDING = {"PENDING", "SENDING", "UNKNOWN"}
SAFE_STATES = {"CONFIRMED", "CANCELED", "PENDING_PAYMENT", "PENDING_STAFF_APPROVAL", "EXPIRED"}


def authority(db, tenant_id):
    row = db.get(CalendarAuthority, tenant_id)
    if not row:
        if settings.environment.lower() in {"prod", "production"}:
            fail(409, "CALENDAR_AUTHORITY_REQUIRED", "منبع معتبر تقویم مرکز باید تایید شود.")
        return None
    if row.expires_at <= now_utc():
        fail(409, "CALENDAR_AUTHORITY_EXPIRED", "تایید منبع تقویم منقضی شده است.")
    return row


def is_external(db, tenant_id):
    row = authority(db, tenant_id)
    return bool(row and row.kind == "external")


def require_internal(db, tenant_id):
    if is_external(db, tenant_id):
        fail(409, "EXTERNAL_CALENDAR_AUTHORITY", "ثبت باید از تقویم معتبر بیرونی انجام شود؛ تقویم محلی مجاز نیست.")


def connector_for(tenant_id, *, client=None):
    try:
        mapping = json.loads(os.getenv("CALENDAR_TENANT_CREDENTIALS_JSON", "{}"))
        item = mapping.get(tenant_id)
        if not isinstance(item, dict) or not item.get("account_id") or not item.get("token"):
            raise ValueError
    except (ValueError, TypeError):
        raise ProviderError("CALENDAR_TENANT_CREDENTIAL_REQUIRED") from None
    return HTTPPartnerCalendar(os.getenv("CALENDAR_PARTNER_URL", ""), item["token"], item["account_id"], client=client)


def profile_dict(row):
    return {"kind": row.kind if row else "internal", "provider_key": row.provider_key if row else "internal_calendar",
            "version": row.version if row else 0, "capabilities": row.capabilities if row else {},
            "approved_by": row.approved_by if row else None, "expires_at": row.expires_at.isoformat() if row else None,
            "connector_revision": row.connector_revision if row else "internal-v1",
            "verification": "operator_approved" if row else "development_default"}


class AuthorityInput(StrictModel):
    version: int = Field(ge=0)
    kind: Literal["internal", "external"]
    expires_at: datetime
    reason: str = Field(min_length=3, max_length=500)


@router.get("/calendar/authority")
def get_authority(actor: Actor = Depends(require_permissions("integration:read")), db: Session = Depends(get_db)):
    return profile_dict(db.get(CalendarAuthority, actor.tenant_id))


@router.put("/calendar/authority")
async def set_authority(body: AuthorityInput, actor: Actor = Depends(require_permissions("integration:write")), db: Session = Depends(get_db)):
    if body.expires_at.tzinfo is None or body.expires_at <= now_utc():
        fail(422, "INVALID_EXPIRY", "اعتبار باید در آینده باشد.")
    caps = {"read": True, "hold": True, "create": True, "cancel": True, "update": True, "atomic_conflict": True, "readback": True}
    revision = "internal-v1"
    if body.kind == "external":
        require_capability(db, actor.tenant_id, "calendar_primary", "get")
        db.commit()
        try:
            caps = await connector_for(actor.tenant_id).capabilities()
            revision = caps["revision"]
        except ProviderError as exc:
            fail(409, exc.code, "قابلیت یا دسترسی تقویم بیرونی تایید نشد.")
    tenant = lock(db, actor.tenant_id)
    if tenant.mode != "paused":
        fail(409, "PAUSE_REQUIRED", "پیش از تغییر منبع تقویم، پذیرش خودکار را متوقف کنید.")
    row = db.get(CalendarAuthority, actor.tenant_id)
    if body.version != (row.version if row else 0):
        fail(409, "VERSION_CONFLICT", "منبع تقویم تغییر کرده است.")
    if not row or row.kind != body.kind:
        active = db.scalar(select(Appointment.id).where(Appointment.tenant_id == actor.tenant_id,
            Appointment.status.in_(["CONFIRMED", "PENDING_PAYMENT", "PENDING_STAFF_APPROVAL"]), Appointment.occupied_until > now_utc()).limit(1))
        held = db.scalar(select(SlotHold.id).where(SlotHold.tenant_id == actor.tenant_id, SlotHold.status == "HELD", SlotHold.expires_at > now_utc()).limit(1))
        pending = db.scalar(select(ExternalCalendarOperation.id).where(ExternalCalendarOperation.tenant_id == actor.tenant_id,
            ExternalCalendarOperation.status.in_(PENDING)).limit(1))
        # Retained remote confirmations require an explicit migration/closure; no quiet switch to local truth.
        remote = db.scalar(select(ExternalCalendarOperation.id).where(ExternalCalendarOperation.tenant_id == actor.tenant_id,
            ExternalCalendarOperation.operation == "create", ExternalCalendarOperation.status == "SUCCEEDED").limit(1))
        if active or held or pending or remote:
            fail(409, "AUTHORITY_MIGRATION_REQUIRES_REVIEW", "نوبت یا عملیات باز وجود دارد؛ مهاجرت باید با تطبیق کامل انجام شود.")
    if not row:
        row = CalendarAuthority(tenant_id=actor.tenant_id, version=0, approved_by=actor.id, expires_at=body.expires_at)
        db.add(row)
    row.kind, row.provider_key = body.kind, "calendar_primary" if body.kind == "external" else "internal_calendar"
    row.version += 1
    row.capabilities, row.connector_revision, row.approved_by, row.approved_at, row.expires_at = caps, revision, actor.id, now_utc(), body.expires_at
    revise(db, actor, "calendar.authority_published", "calendar", actor.tenant_id, body.reason, version=row.version, kind=row.kind)
    db.commit()
    return profile_dict(row)


def remote_key(row):
    return hashlib.sha256(f"{row.tenant_id}:{row.operation}:{row.idempotency_key}".encode()).hexdigest()


def queue_operation(db, tenant_id, operation, request, key, actor_id, *, call_id=None, phone_hash=None):
    if operation not in {"slots", "get", "hold", "release", "create", "cancel", "update", "changes"}:
        fail(422, "INVALID_CALENDAR_OPERATION", "عملیات تقویم مجاز نیست.")
    profile = authority(db, tenant_id)
    if not profile or profile.kind != "external":
        fail(409, "EXTERNAL_AUTHORITY_REQUIRED", "مرکز از تقویم بیرونی استفاده نمی‌کند.")
    lock(db, tenant_id)
    checksum = request_digest(request)
    row = db.scalar(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == tenant_id,
        ExternalCalendarOperation.operation == operation, ExternalCalendarOperation.idempotency_key == key))
    if row:
        if row.request_hash != checksum:
            fail(409, "IDEMPOTENCY_MISMATCH", "کلید درخواست برای محتوای دیگری استفاده شده است.")
        return row
    row = ExternalCalendarOperation(tenant_id=tenant_id, authority_version=profile.version, operation=operation,
        idempotency_key=key, request_hash=checksum, request_encrypted=encrypt(json.dumps(request, ensure_ascii=False)),
        actor_id=actor_id, call_id=call_id, phone_hash=phone_hash, status="PENDING", attempts=0)
    db.add(row)
    db.flush()
    db.add(AuditEvent(tenant_id=tenant_id, actor_id=actor_id, action="calendar.operation_queued", entity_type="calendar_operation",
        entity_id=row.id, details={"operation": operation, "authority_version": profile.version}))
    return row


def operation_dict(row):
    value = json.loads(decrypt(row.result_encrypted)) if row.result_encrypted else None
    if value and value.get("requires_readback"):
        return {"operation_id": row.id, "operation": row.operation, "operation_status": "READBACK_REQUIRED",
                "status": "PENDING_CONFIRMATION", "result": None, "error_code": "REMOTE_REVISION_CHANGED",
                "verified_at": None, "requires_reconciliation": True}
    pending_label = {"create": "PENDING_CONFIRMATION", "cancel": "CANCEL_PENDING", "update": "RESCHEDULE_PENDING"}.get(row.operation, "PENDING")
    return {"operation_id": row.id, "operation": row.operation, "operation_status": row.status,
            "status": (value or {}).get("status", "SUCCEEDED") if row.status == "SUCCEEDED" else pending_label if row.status in PENDING else "FAILED_REVIEW",
            "result": value if row.status == "SUCCEEDED" else None, "error_code": row.last_error,
            "verified_at": row.updated_at.isoformat() if row.status == "SUCCEEDED" else None,
            "requires_reconciliation": row.status in {"UNKNOWN", "SENDING"}}


def operation_view(db, row):
    value = operation_dict(row)
    if value["operation_status"] == "SUCCEEDED" and row.operation in {"create", "update", "cancel", "get"}:
        request = json.loads(decrypt(row.request_encrypted))
        value["booking"] = external_booking(db, row.tenant_id, value["result"], patient_name=request.get("patient_name"))
    return value


def review_task(db, row):
    if not db.scalar(select(StaffTask.id).where(StaffTask.tenant_id == row.tenant_id,
        StaffTask.reason == "CALENDAR_RECONCILIATION", StaffTask.resolution == "operation:" + row.id,
        StaffTask.status.in_(["OPEN", "IN_PROGRESS", "PENDING", "CALLBACK"]))):
        db.add(StaffTask(tenant_id=row.tenant_id, call_id=row.call_id, reason="CALENDAR_RECONCILIATION",
            summary="نتیجه عملیات تقویم بیرونی نیاز به تطبیق دارد؛ درخواست را دوباره ارسال نکنید.",
            resolution="operation:" + row.id, priority="high"))


async def execute_operation(db, row, *, connector=None):
    tenant_id, operation_id = row.tenant_id, row.id
    lock(db, tenant_id)
    db.refresh(row)
    profile = authority(db, tenant_id)
    readback_only = row.status == "SUCCEEDED" and row.operation in {"create", "update", "cancel", "get"} and bool(row.remote_id)
    remote_id = row.remote_id
    if row.status == "FAILED_REVIEW" or row.status == "SUCCEEDED" and not readback_only:
        result = operation_dict(row)
        db.commit()
        return result
    if row.lease_until and row.lease_until > now_utc():
        result = operation_dict(row)
        db.commit()
        return result
    reconcile = not readback_only and (row.status in {"SENDING", "UNKNOWN"} or row.attempts > 0 and row.operation in WRITES)
    if profile.version != row.authority_version:
        row.status, row.last_error = "FAILED_REVIEW", "AUTHORITY_VERSION_CHANGED"
        review_task(db, row)
        db.commit()
        return operation_dict(row)
    lease = secrets.token_urlsafe(24)
    row.lease_token, row.lease_until = lease, now_utc() + timedelta(seconds=90)
    row.status = "UNKNOWN" if reconcile else "SENDING"
    if not reconcile:
        row.attempts += 1
    operation, request, key = row.operation, json.loads(decrypt(row.request_encrypted)), remote_key(row)
    ctx = ProviderContext.from_session(db, tenant_id, f"calendar:{row.id}:{'reconcile' if reconcile else 'send'}:{lease[:8]}",
                                       call_id=row.call_id, subject_hash="session:" + row.call_id if row.call_id else row.phone_hash)
    db.commit()
    result, failure, unknown = None, None, False
    ticket = None
    try:
        adapter = connector or connector_for(tenant_id)
        if not profile.capabilities.get("account_id") or getattr(adapter, "account_id", None) != profile.capabilities["account_id"]:
            raise ProviderError("CALENDAR_ACCOUNT_APPROVAL_CHANGED")
        count_before = getattr(adapter, "request_count", 0)
        ticket = ctx.start("calendar_primary", "calendar_requests", 4, "get" if readback_only else "reconcile" if reconcile else operation)
        if readback_only:
            result = await adapter.get(remote_id)
        elif reconcile:
            checked = await adapter.reconcile(key)
            if checked["state"] == "PENDING":
                raise ProviderError("CALENDAR_UNKNOWN_OUTCOME", unknown_outcome=True)
            if checked["state"] == "NOT_COMMITTED":
                raise ProviderError("CALENDAR_NOT_COMMITTED")
            result = checked.get("appointment") or checked.get("result")
            if not isinstance(result, dict):
                raise ProviderError("CALENDAR_UNKNOWN_OUTCOME", unknown_outcome=True)
        elif operation == "slots":
            result = {"slots": await adapter.slots(request["provider_id"], request["service_id"], request["date"])}
        elif operation == "get":
            result = await adapter.get(request["remote_id"])
        elif operation == "hold":
            result = await adapter.hold(request, key)
        elif operation == "release":
            result = await adapter.release(request["hold_id"], key)
        elif operation == "create":
            result = await adapter.create(request, key)
        elif operation == "cancel":
            result = await adapter.cancel(request["remote_id"], request["revision"], key)
        elif operation == "update":
            result = await adapter.update(request["remote_id"], request, request["revision"], key)
        elif operation == "changes":
            result = await adapter.changes(request.get("cursor"))
        if operation == "hold":
            try:
                result = RemoteHold.model_validate(result).model_dump()
                if result["slot_id"] != request["slot_id"] or datetime.fromisoformat(result["expires_at"].replace("Z", "+00:00")) <= now_utc():
                    raise ValueError
            except ValueError as exc:
                raise ProviderError("CALENDAR_INVALID_HOLD", unknown_outcome=True) from exc
        if operation in {"create", "update", "cancel", "get"}:
            if not result or result.get("status") not in SAFE_STATES:
                raise ProviderError("CALENDAR_READBACK_MISMATCH", unknown_outcome=operation in WRITES)
            expected = "CANCELED" if operation == "cancel" and not readback_only else None
            match_fields = ("patient_token",) if readback_only else ("patient_token", "slot_id", "provider_id", "service_id")
            if expected and result["status"] != expected or any(result.get(k) != request[k] for k in match_fields if k in request):
                raise ProviderError("CALENDAR_READBACK_MISMATCH", unknown_outcome=True)
        if ticket:
            ctx.finish(ticket, max(1, getattr(adapter, "request_count", count_before + 1) - count_before), outcome="confirmed")
    except ProviderError as exc:
        failure, unknown = exc.code, exc.unknown_outcome or (reconcile or readback_only) and exc.code != "CALENDAR_NOT_COMMITTED" or operation in WRITES and exc.code in {"PROVIDER_TIMEOUT", "PROVIDER_UNAVAILABLE"}
        if ticket:
            ctx.finish(ticket, 0, outcome="unknown" if unknown or exc.code not in {"PROCESSOR_NOT_APPROVED", "PROVIDER_CIRCUIT_OPEN"} else "no_charge", code=exc.code)
    lock(db, tenant_id)
    row = db.scalar(select(ExternalCalendarOperation).where(ExternalCalendarOperation.id == operation_id,
        ExternalCalendarOperation.tenant_id == tenant_id).execution_options(populate_existing=True))
    if row.lease_token != lease:
        db.commit()
        return operation_dict(row)
    row.lease_token = row.lease_until = None
    if failure:
        row.status, row.last_error = "UNKNOWN" if unknown else "FAILED_REVIEW", failure
        review_task(db, row)
    else:
        row.status, row.last_error = "SUCCEEDED", None
        row.result_encrypted = encrypt(json.dumps(result, ensure_ascii=False))
        row.remote_id, row.remote_revision = result.get("id"), result.get("revision")
    db.add(AuditEvent(tenant_id=tenant_id, actor_id=row.actor_id, action="calendar.operation_reconciled" if reconcile else "calendar.operation_completed",
        entity_type="calendar_operation", entity_id=row.id, details={"status": row.status, "operation": row.operation, "error_code": row.last_error}))
    db.commit()
    return operation_dict(row)


def encode_slot(db, tenant_id, slot):
    profile = authority(db, tenant_id)
    start = datetime.fromisoformat(slot["start_at"].replace("Z", "+00:00"))
    expiry = min(datetime.fromisoformat(slot["expires_at"].replace("Z", "+00:00")), now_utc() + timedelta(minutes=10))
    if expiry <= now_utc() or start <= now_utc():
        return None
    token = jwt.encode({"iss": "persian-receptionist", "aud": "external-slot", "tenant": tenant_id,
        "authority": profile.version, "iat": now_utc(), "exp": expiry, "slot": slot}, settings.jwt_secret, algorithm="HS256")
    from .locale import jalali_label
    from zoneinfo import ZoneInfo
    local = start.astimezone(ZoneInfo("Asia/Tehran"))
    return {"slot_id": token, "provider_id": slot["provider_id"], "service_id": slot["service_id"], "start_at": slot["start_at"],
            "end_at": slot["end_at"], "local_date": local.date().isoformat(), "local_time": local.strftime("%H:%M"),
            "jalali_label": jalali_label(local.date(), local.strftime("%H:%M")), "display": jalali_label(local.date(), local.strftime("%H:%M")), "label": jalali_label(local.date(), local.strftime("%H:%M")),
            "authority": "external", "revision": slot["revision"], "expires_at": expiry.isoformat()}


def decode_slot(db, tenant_id, value):
    try:
        claims = jwt.decode(value, settings.jwt_secret, algorithms=["HS256"], audience="external-slot", issuer="persian-receptionist",
            options={"require": ["exp", "iat", "tenant", "authority", "slot"]})
        profile = authority(db, tenant_id)
        if claims["tenant"] != tenant_id or claims["authority"] != profile.version:
            raise ValueError
        return claims["slot"]
    except (jwt.PyJWTError, ValueError, TypeError):
        fail(409, "INVALID_EXTERNAL_SLOT", "زمان پیشنهادشده منقضی یا تغییر کرده است؛ دوباره بررسی کنید.")


def external_booking(db, tenant_id, remote, *, patient_name=None):
    provider = db.scalar(select(Practitioner).where(Practitioner.tenant_id == tenant_id, Practitioner.id == remote["provider_id"]))
    service = db.scalar(select(Service).where(Service.tenant_id == tenant_id, Service.id == remote["service_id"]))
    if not provider or not service:
        fail(409, "EXTERNAL_CATALOG_MISMATCH", "تطبیق خدمت تقویم بیرونی نیاز به بررسی دارد.")
    from .locale import jalali_label
    from zoneinfo import ZoneInfo
    start = datetime.fromisoformat(remote["start_at"].replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Tehran"))
    return {"id": "external:" + remote["id"], "reference": remote["reference"], "status": remote["status"],
            "provider_id": provider.id, "provider_name": provider.name, "service_id": service.id, "service_name": service.name,
            "patient_name": patient_name or "", "phone_masked": "••••", "start_at": remote["start_at"], "end_at": remote["end_at"],
            "local_date": start.date().isoformat(), "local_time": start.strftime("%H:%M"),
            "jalali_label": jalali_label(start.date(), start.strftime("%H:%M")), "jalali_display": jalali_label(start.date(), start.strftime("%H:%M")), "version": remote["revision"],
            "attendance": None, "notification_status": "UNKNOWN", "created_at": None, "reminder_opt_in": None,
            "price_toman": service.price_toman, "deposit_toman": service.deposit_toman, "authority": "external",
            "payment_status": "PENDING" if remote["status"] == "PENDING_PAYMENT" else "EXTERNAL_AUTHORITY",
            "payment_url": None, "payment_expires_at": remote.get("payment_expires_at")}


def owned_booking(db, tenant_id, remote_id):
    row = db.scalar(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == tenant_id,
        ExternalCalendarOperation.remote_id == remote_id, ExternalCalendarOperation.operation == "create", ExternalCalendarOperation.status == "SUCCEEDED"))
    if not row:
        fail(404, "NOT_FOUND", "نوبت بیرونی متعلق به این مرکز پیدا نشد.")
    return row


def list_bookings(db, tenant_id, *, day=None, status=None):
    """Inventory of known remote identities; every row explicitly needs fresh readback."""
    rows = db.scalars(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == tenant_id,
        ExternalCalendarOperation.operation == "create", ExternalCalendarOperation.status == "SUCCEEDED")
        .order_by(ExternalCalendarOperation.created_at.desc()).limit(200))
    result = []
    for row in rows:
        remote = json.loads(decrypt(row.result_encrypted))
        value = external_booking(db, tenant_id, remote, patient_name=json.loads(decrypt(row.request_encrypted)).get("patient_name"))
        if day and value["local_date"] != str(day) or status and value["status"] != status:
            continue
        value.update(status="READBACK_REQUIRED", last_known_status=remote["status"], verified_at=row.updated_at.isoformat(), operation_id=row.id)
        result.append(value)
    return result


async def read_booking(db, actor, remote_id):
    row = owned_booking(db, actor.tenant_id, remote_id)
    result = await execute_operation(db, row)
    if result["operation_status"] == "SUCCEEDED":
        return external_booking(db, actor.tenant_id, result["result"], patient_name=json.loads(decrypt(row.request_encrypted)).get("patient_name"))
    return result


async def hold_slot(db, actor, payload, *, call_id=None):
    slot = decode_slot(db, actor.tenant_id, payload["slot_id"])
    ReceptionService(db, actor.tenant_id, actor.id)._catalog(slot["provider_id"], slot["service_id"])
    row = queue_operation(db, actor.tenant_id, "hold", {"slot_id": slot["id"], "revision": slot["revision"]},
                          payload["idempotency_key"], actor.id, call_id=call_id)
    db.commit()
    result = await execute_operation(db, row)
    if result["operation_status"] == "SUCCEEDED":
        return {"id": result["result"]["id"], "hold_id": result["result"]["id"], "status": "HELD", "expires_at": result["result"]["expires_at"], "authority": "external"}
    return result


async def slots(db, actor, provider_id, service_id, day, *, call_id=None, key=None):
    ReceptionService(db, actor.tenant_id, actor.id)._catalog(provider_id, service_id)
    row = queue_operation(db, actor.tenant_id, "slots", {"provider_id": provider_id, "service_id": service_id, "date": str(day)},
                          key or secrets.token_urlsafe(20), actor.id, call_id=call_id)
    db.commit()
    outcome = await execute_operation(db, row)
    if outcome["operation_status"] != "SUCCEEDED":
        fail(503, "EXTERNAL_CALENDAR_UNAVAILABLE", "بررسی تقویم معتبر ممکن نشد؛ پذیرش پیگیری می‌کند.")
    return [value for slot in outcome["result"]["slots"] if (value := encode_slot(db, actor.tenant_id, slot))]


def prepare_booking(db, actor, payload, *, call_id=None):
    if payload.get("confirmed") is not True:
        fail(422, "CONFIRMATION_REQUIRED", "تایید صریح ثبت لازم است.")
    slot = decode_slot(db, actor.tenant_id, payload["slot_id"])
    _, service = ReceptionService(db, actor.tenant_id, actor.id)._catalog(slot["provider_id"], slot["service_id"])
    rules = service_policy(db, actor.tenant_id, service.id, checked=True)
    if rules["visit_policy"] != "any":
        fail(409, "EXTERNAL_ELIGIBILITY_REVIEW_REQUIRED", "شرایط مراجعه یا بسته باید در منبع تقویم بیرونی تایید شود.")
    if service.deposit_toman:
        fail(409, "EXTERNAL_PAYMENT_REVIEW_REQUIRED", "پرداخت خدمت بیرونی باید در گردش کار تاییدشده همان مرکز بررسی شود.")
    request = {"slot_id": slot["id"], "revision": slot["revision"], "provider_id": slot["provider_id"], "service_id": slot["service_id"],
               "start_at": slot["start_at"], "patient_token": hash_phone(payload["phone"]),
               "patient_name": payload["patient_name"], "phone": payload["phone"],
               "approval_required": bool(service.requires_approval or db.get(Tenant, actor.tenant_id).mode == "supervised"), "hold_id": payload.get("hold_id")}
    if request["hold_id"]:
        held = db.scalar(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == actor.tenant_id,
            ExternalCalendarOperation.operation == "hold", ExternalCalendarOperation.remote_id == request["hold_id"], ExternalCalendarOperation.status == "SUCCEEDED"))
        value = json.loads(decrypt(held.result_encrypted)) if held else {}
        if not held or value.get("slot_id") != slot["id"] or datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00")) <= now_utc() or call_id and held.call_id != call_id:
            fail(409, "HOLD_EXPIRED_OR_MISMATCH", "نگه‌داشت زمان معتبر نیست؛ زمان را دوباره بررسی کنید.")
    return queue_operation(db, actor.tenant_id, "create", request, payload["idempotency_key"], actor.id,
                           call_id=call_id, phone_hash=hash_phone(payload["phone"]))


async def create_booking(db, actor, payload, *, call_id=None):
    row = prepare_booking(db, actor, payload, call_id=call_id)
    db.commit()
    result = await execute_operation(db, row)
    if result["operation_status"] == "SUCCEEDED":
        return external_booking(db, actor.tenant_id, result["result"], patient_name=payload["patient_name"])
    return result


async def change_booking(db, actor, remote_id, operation, payload, *, call_id=None):
    owned = owned_booking(db, actor.tenant_id, remote_id)
    request = {"remote_id": remote_id, "revision": str(payload["version"])}
    if operation == "update":
        slot = decode_slot(db, actor.tenant_id, payload["slot_id"])
        previous = json.loads(decrypt(owned.result_encrypted))
        if slot["service_id"] != previous["service_id"]:
            fail(422, "SERVICE_CHANGE_REQUIRES_REVIEW", "تغییر خدمت نیاز به بررسی پذیرش دارد.")
        request.update(slot_id=slot["id"], provider_id=slot["provider_id"], service_id=slot["service_id"],
                       slot_revision=slot["revision"], patient_token=previous["patient_token"])
    row = queue_operation(db, actor.tenant_id, operation, request, payload["idempotency_key"], actor.id,
                          call_id=call_id, phone_hash=owned.phone_hash)
    db.commit()
    result = await execute_operation(db, row)
    return external_booking(db, actor.tenant_id, result["result"]) if result["operation_status"] == "SUCCEEDED" else result


@router.get("/calendar/operations")
def operations(actor: Actor = Depends(require_permissions("appointment:read")), db: Session = Depends(get_db)):
    return [operation_view(db, row) for row in db.scalars(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == actor.tenant_id)
            .order_by(ExternalCalendarOperation.created_at.desc()).limit(200))]


@router.get("/calendar/operations/{operation_id}")
def operation_state(operation_id: str, actor: Actor = Depends(require_permissions("appointment:read")), db: Session = Depends(get_db)):
    row = db.scalar(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == actor.tenant_id, ExternalCalendarOperation.id == operation_id))
    if not row:
        fail(404, "NOT_FOUND", "عملیات پیدا نشد.")
    return operation_view(db, row)


@router.post("/calendar/operations/{operation_id}/reconcile")
async def reconcile_operation(operation_id: str, actor: Actor = Depends(require_permissions("appointment:write")), db: Session = Depends(get_db)):
    row = db.scalar(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == actor.tenant_id, ExternalCalendarOperation.id == operation_id))
    if not row:
        fail(404, "NOT_FOUND", "عملیات پیدا نشد.")
    await execute_operation(db, row)
    return operation_view(db, row)


def apply_change(db, tenant_id, event, source):
    lock(db, tenant_id)
    if not isinstance(event, dict) or set(event) != {"event_id", "revision", "remote_id"} or not isinstance(event["revision"], int) or event["revision"] < 1:
        fail(422, "INVALID_CALENDAR_EVENT", "Calendar change must contain an event id, positive revision and remote id.")
    if any(not isinstance(event[k], str) or not 1 <= len(event[k]) <= 120 for k in ("event_id", "remote_id")):
        fail(422, "INVALID_CALENDAR_EVENT", "Invalid calendar change identifier.")
    checksum = request_digest(event)
    previous = db.scalar(select(CalendarChangeReceipt).where(CalendarChangeReceipt.tenant_id == tenant_id, CalendarChangeReceipt.event_id == event["event_id"]))
    if previous:
        if previous.payload_hash != checksum:
            fail(409, "CALENDAR_EVENT_REPLAY_MISMATCH", "Replayed event content differs.")
        return False
    state = db.get(CalendarSyncState, tenant_id)
    if not state:
        state = CalendarSyncState(tenant_id=tenant_id, revision=0, status="NOT_SYNCED")
        db.add(state)
    gap = event["revision"] > state.revision + 1
    state.status = "SYNC_REQUIRED" if gap else "CURRENT" if event["revision"] >= state.revision else state.status
    state.revision = max(state.revision, event["revision"])
    state.last_event_at = now_utc()
    state.error_code = "REVISION_GAP" if gap else state.error_code
    db.add(CalendarChangeReceipt(tenant_id=tenant_id, event_id=event["event_id"], revision=event["revision"],
        remote_id=event["remote_id"], source=source, payload_hash=checksum))
    # Invalidate stale confirmation snapshots. Next access requires authoritative readback.
    for row in db.scalars(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == tenant_id,
        ExternalCalendarOperation.remote_id == event["remote_id"], ExternalCalendarOperation.status == "SUCCEEDED")):
        value = json.loads(decrypt(row.result_encrypted))
        value["requires_readback"] = True
        row.result_encrypted = encrypt(json.dumps(value, ensure_ascii=False))
    return True


@router.post("/calendar/webhooks/{tenant_id}")
async def calendar_webhook(tenant_id: str, request: Request, db: Session = Depends(get_db)):
    db.rollback()
    raw = bytearray()
    try:
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 16_000:
                    fail(413, "RECEIPT_TOO_LARGE", "Receipt exceeds the byte limit.")
                raw.extend(chunk)
    except TimeoutError:
        fail(408, "RECEIPT_TIMEOUT", "Receipt exceeded the time limit.")
    if not verify_webhook(bytes(raw), request.headers.get("X-Timestamp", ""), request.headers.get("X-Signature", ""), os.getenv("CALENDAR_WEBHOOK_SECRET", "")):
        fail(401, "INVALID_SIGNATURE", "Signed calendar receipt required.")
    if not is_external(db, tenant_id):
        fail(409, "EXTERNAL_AUTHORITY_REQUIRED", "External calendar not configured.")
    try:
        body = json.loads(raw)
    except ValueError:
        fail(422, "INVALID_CALENDAR_EVENT", "Invalid JSON.")
    # Bind the signed body to the tenant so a path rewrite cannot cross scopes.
    if not isinstance(body, dict) or body.get("tenant_id") != tenant_id:
        fail(403, "CALENDAR_SCOPE_MISMATCH", "Calendar tenant mismatch.")
    changed = apply_change(db, tenant_id, body.get("event"), "webhook")
    db.commit()
    return {"status": "ACCEPTED", "replayed": not changed}


async def poll_changes(db, tenant_id, *, connector=None):
    profile = authority(db, tenant_id)
    state = db.get(CalendarSyncState, tenant_id)
    cursor = state.cursor if state else None
    ctx = ProviderContext.from_session(db, tenant_id, "calendar-poll:" + secrets.token_urlsafe(18))
    db.commit()
    adapter = connector or connector_for(tenant_id)
    if not profile or not profile.capabilities.get("account_id") or getattr(adapter, "account_id", None) != profile.capabilities["account_id"]:
        raise ProviderError("CALENDAR_ACCOUNT_APPROVAL_CHANGED")
    before = getattr(adapter, "request_count", 0)
    ticket = ctx.start("calendar_primary", "calendar_requests", 2, "changes")
    try:
        result = await adapter.changes(cursor)
    except ProviderError as exc:
        ctx.finish(ticket, 0, outcome="unknown", code=exc.code)
        raise
    ctx.finish(ticket, max(1, getattr(adapter, "request_count", before + 1) - before), outcome="confirmed")
    for event in result["events"]:
        apply_change(db, tenant_id, event, "poll")
    lock(db, tenant_id)
    state = db.get(CalendarSyncState, tenant_id)
    if not state:
        state = CalendarSyncState(tenant_id=tenant_id, revision=0, status="CURRENT")
        db.add(state)
    state.cursor, state.last_poll_at = result["cursor"], now_utc()
    if result.get("complete") is True:
        state.status, state.error_code = "CURRENT", None
    db.commit()
    return {"status": state.status, "revision": state.revision, "last_poll_at": state.last_poll_at.isoformat()}


@router.get("/calendar/sync")
def sync_state(actor: Actor = Depends(require_permissions("integration:read")), db: Session = Depends(get_db)):
    state = db.get(CalendarSyncState, actor.tenant_id)
    return {"status": state.status if state else "NOT_SYNCED", "revision": state.revision if state else 0,
            "last_event_at": state.last_event_at.isoformat() if state and state.last_event_at else None,
            "last_poll_at": state.last_poll_at.isoformat() if state and state.last_poll_at else None,
            "lag_seconds": max(0, (now_utc() - state.last_poll_at).total_seconds()) if state and state.last_poll_at else None,
            "error_code": state.error_code if state else None}
