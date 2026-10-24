"""Authoritative internal calendar, policy validation, and atomic booking writes.

Every mutation contains occupancy, appointment, audit and outbox changes in the
same transaction. Database uniqueness, rather than a preflight read, excludes
conflicting resource minutes. External calendars must use a separate adapter;
these records are the authoritative calendar only for the internal adapter.
"""

import hashlib
import json
import secrets
from datetime import UTC, datetime, time, timedelta
from datetime import date as Date
from zoneinfo import ZoneInfo

import jdatetime
import jwt
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from .config import settings
from .db import now_utc
from .models import (
    Appointment,
    AuditEvent,
    IdempotencyRecord,
    MessageOutbox,
    Occupancy,
    Practitioner,
    Service,
    SlotHold,
    StaffTask,
    Tenant,
    UsageEvent,
    uid,
)
from .security import decrypt, encrypt, fail, hash_phone, mask_phone, normalize_phone
from .models_ext import AppointmentImpact, Disruption
from .models_outreach import CapacityRelease  # noqa: F401 -- register durable capacity/outreach schema

WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
MONTHS = ["فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"]
ACTIVE_APPOINTMENTS = {"CONFIRMED", "PENDING_PAYMENT", "PENDING_STAFF_APPROVAL"}
CALL_DURATION_KINDS = {"call_seconds", "call_duration", "billable_call_duration", "demo_call_duration"}


def call_minutes(event: UsageEvent) -> float:
    """Customer call time excludes STT/TTS processing meters and token counts."""
    if event.kind not in CALL_DURATION_KINDS:
        return 0
    return event.quantity if event.unit in {"minute", "minutes"} else event.quantity / 60 if event.unit in {"second", "seconds"} else 0


def iso(value):
    return value.isoformat().replace("+00:00", "Z") if value else None


def jalali_label(value: datetime, timezone: str = "Asia/Tehran") -> str:
    local = value.astimezone(ZoneInfo(timezone))
    jalali = jdatetime.date.fromgregorian(date=local.date())
    return f"{WEEKDAYS[local.weekday()]}، {jalali.day} {MONTHS[jalali.month - 1]} {jalali.year}، ساعت {local:%H:%M}"


def request_digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def task_dict(row: StaffTask) -> dict:
    return {
        "id": row.id,
        "reason": row.reason,
        "summary": row.summary,
        "priority": row.priority,
        "status": row.status,
        "call_id": row.call_id,
        "appointment_id": row.appointment_id,
        "created_at": iso(row.created_at),
        "resolved_at": iso(row.resolved_at),
        "resolution": row.resolution,
    }


def notification_dict(row: MessageOutbox) -> dict:
    return {
        "id": row.id,
        "appointment_id": row.appointment_id,
        "purpose": row.purpose,
        "recipient_masked": mask_phone(decrypt(row.recipient_encrypted)),
        "status": row.status,
        "attempts": row.attempts,
        "provider_id": row.provider_id,
        "last_error_code": row.last_error_code,
        "created_at": iso(row.created_at),
        "updated_at": iso(row.updated_at),
    }


def audit_dict(row: AuditEvent) -> dict:
    return {
        "id": row.id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "actor_id": row.actor_id,
        "details": row.details,
        "created_at": iso(row.created_at),
    }


class ReceptionService:
    def __init__(self, db: Session, tenant_id: str, actor_id: str = "system"):
        self.db = db
        self.tenant_id = tenant_id
        self.actor_id = actor_id

    def tenant(self) -> Tenant:
        tenant = self.db.get(Tenant, self.tenant_id)
        if tenant is None or not tenant.active:
            fail(404, "NOT_FOUND", "مرکز موردنظر پیدا نشد.")
        return tenant

    def _catalog(self, provider_id: str, service_id: str):
        provider = self.db.scalar(
            select(Practitioner).where(
                Practitioner.id == provider_id, Practitioner.tenant_id == self.tenant_id, Practitioner.active.is_(True)
            )
        )
        service = self.db.scalar(
            select(Service).where(Service.id == service_id, Service.tenant_id == self.tenant_id, Service.active.is_(True))
        )
        if not provider or not service or provider_id not in service.provider_ids:
            fail(404, "CATALOG_NOT_FOUND", "پزشک یا خدمت در این مرکز در دسترس نیست.")
        if not 1 <= service.duration_minutes <= 480 or not 0 <= service.buffer_minutes <= 120:
            fail(409, "INVALID_POLICY", "تنظیم زمان خدمت نیاز به بررسی دارد.")
        from .core_policy import require_facts

        require_facts(self.db, self.tenant_id, "tenant", self.tenant())
        require_facts(self.db, self.tenant_id, "practitioner", provider)
        require_facts(self.db, self.tenant_id, "service", service)
        return provider, service

    def _audit(self, action: str, entity_type: str, entity_id: str, **details):
        self.db.add(
            AuditEvent(
                tenant_id=self.tenant_id,
                actor_id=self.actor_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
            )
        )

    def _expire(self):
        # All calendar writes acquire the tenant policy lock before row locks.
        self.db.execute(update(Tenant).where(Tenant.id == self.tenant_id).values(settings_version=Tenant.settings_version))
        now = now_utc()
        expired_holds = list(
            self.db.scalars(
                update(SlotHold)
                .where(SlotHold.tenant_id == self.tenant_id, SlotHold.status == "HELD", SlotHold.expires_at <= now)
                .values(status="EXPIRED")
                .returning(SlotHold.id)
            )
        )
        if expired_holds:
            self.db.execute(
                delete(Occupancy).where(
                    Occupancy.tenant_id == self.tenant_id, Occupancy.owner_type == "hold", Occupancy.owner_id.in_(expired_holds)
                )
            )
            from .operations_outreach import record_capacity_release

            for hold in self.db.scalars(select(SlotHold).where(SlotHold.tenant_id == self.tenant_id, SlotHold.id.in_(expired_holds))):
                if not hold.session_id.startswith("waitlist:"):
                    record_capacity_release(self.db, hold, "hold_expired", 1)
        expired_bookings = list(
            self.db.scalars(
                update(Appointment)
                .where(Appointment.tenant_id == self.tenant_id, Appointment.status == "PENDING_PAYMENT", Appointment.expires_at <= now)
                .values(status="EXPIRED", version=Appointment.version + 1)
                .returning(Appointment.id)
            )
        )
        if expired_bookings:
            self.db.execute(
                delete(Occupancy).where(
                    Occupancy.tenant_id == self.tenant_id, Occupancy.owner_type == "appointment", Occupancy.owner_id.in_(expired_bookings)
                )
            )
            for booking_id in expired_bookings:
                from .bookings_ext import release_package

                release_package(self.db, self.tenant_id, booking_id)
                self._audit("appointment.expired", "appointment", booking_id, reason="deposit_deadline")
                from .operations_outreach import record_capacity_release

                booking = self.db.scalar(select(Appointment).where(Appointment.id == booking_id, Appointment.tenant_id == self.tenant_id))
                record_capacity_release(self.db, booking, "payment_hold_expired", booking.version)

    def expire(self):
        self._expire()
        self.db.commit()

    @staticmethod
    def _resources(provider_id: str, service: Service):
        return [f"provider:{provider_id}"] + [f"resource:{r}" for r in sorted(set(service.resource_ids))]

    def _claims(self, provider_id: str, service: Service, start: datetime, end: datetime, owner_type: str, owner_id: str):
        first, last = int(start.timestamp() // 60), int(end.timestamp() // 60)
        for resource_id in self._resources(provider_id, service):
            for minute in range(first, last):
                self.db.add(
                    Occupancy(tenant_id=self.tenant_id, resource_id=resource_id, minute=minute, owner_type=owner_type, owner_id=owner_id)
                )

    def _conflict(self, provider_id: str, service: Service, start: datetime, end: datetime, ignore_owner: str | None = None) -> bool:
        query = select(Occupancy.id).where(
            Occupancy.tenant_id == self.tenant_id,
            Occupancy.resource_id.in_(self._resources(provider_id, service)),
            Occupancy.minute >= int(start.timestamp() // 60),
            Occupancy.minute < int(end.timestamp() // 60),
        )
        if ignore_owner:
            query = query.where(Occupancy.owner_id != ignore_owner)
        return self.db.scalar(query.limit(1)) is not None

    def _disrupted(self, provider_id: str, start: datetime, end: datetime) -> bool:
        return self.db.scalar(select(Disruption.id).where(
            Disruption.tenant_id == self.tenant_id, Disruption.status == "ACTIVE",
            Disruption.kind.in_(["PROVIDER_DELAY", "EMERGENCY_CLOSURE"]),
            (Disruption.provider_id.is_(None) | (Disruption.provider_id == provider_id)),
            Disruption.start_at < end, Disruption.end_at > start,
        ).limit(1)) is not None

    @staticmethod
    def _intervals(hours: dict, local_date: Date):
        return hours.get(str(local_date.weekday()), [])

    def _within_hours(self, tenant: Tenant, provider: Practitioner, local_start: datetime, occupied_end: datetime) -> bool:
        local_date = local_start.date()
        if local_date.isoformat() in tenant.holidays or occupied_end.date() != local_date:
            return False
        for hours in [tenant.working_hours] + ([provider.working_hours] if provider.working_hours is not None else []):
            if not any(
                datetime.combine(local_date, time.fromisoformat(a), local_start.tzinfo) <= local_start
                and occupied_end <= datetime.combine(local_date, time.fromisoformat(b), local_start.tzinfo)
                for a, b in self._intervals(hours, local_date)
            ):
                return False
        return True

    def _valid_start(self, tenant: Tenant, provider: Practitioner, service: Service, start: datetime):
        now = now_utc()
        local = start.astimezone(ZoneInfo(tenant.timezone))
        end = start + timedelta(minutes=service.duration_minutes + service.buffer_minutes)
        if start.second or start.microsecond or start < now + timedelta(minutes=tenant.lead_time_minutes):
            fail(409, "SLOT_NOT_AVAILABLE", "این زمان دیگر قابل رزرو نیست.")
        if local.date() > now.astimezone(local.tzinfo).date() + timedelta(days=tenant.booking_horizon_days):
            fail(422, "OUTSIDE_BOOKING_HORIZON", "زمان انتخابی خارج از بازه رزرو است.")
        if not self._within_hours(tenant, provider, local, end.astimezone(local.tzinfo)):
            fail(409, "OUTSIDE_WORKING_HOURS", "این زمان با ساعت کاری مرکز سازگار نیست.")
        if self._disrupted(provider.id, start, end):
            fail(409, "SCHEDULE_DISRUPTED", "این بازه به دلیل اختلال برنامه فعلاً قابل رزرو نیست.")
        return end

    def _encode_slot(self, tenant: Tenant, provider_id: str, service_id: str, start: datetime):
        return jwt.encode(
            {
                "tenant": tenant.id,
                "provider": provider_id,
                "service": service_id,
                "start": iso(start),
                "version": tenant.settings_version,
                "aud": "slot",
                "exp": now_utc() + timedelta(minutes=15),
            },
            settings.jwt_secret,
            algorithm="HS256",
        )

    def _decode_slot(self, slot_id: str):
        from .calendar_bridge import require_internal

        require_internal(self.db, self.tenant_id)
        try:
            payload = jwt.decode(
                slot_id,
                settings.jwt_secret,
                algorithms=["HS256"],
                audience="slot",
                options={"require": ["tenant", "provider", "service", "start", "version", "exp"]},
            )
            start = datetime.fromisoformat(payload["start"].replace("Z", "+00:00"))
        except (jwt.PyJWTError, KeyError, ValueError, TypeError):
            fail(409, "STALE_SLOT", "زمان‌ها را دوباره دریافت و انتخاب کنید.")
        tenant = self.tenant()
        if payload["tenant"] != tenant.id:
            fail(404, "NOT_FOUND", "زمان موردنظر پیدا نشد.")
        # Share the policy/disruption lock before validating or consuming a slot.
        # This serializes closure publication with in-flight calendar writes.
        locked = self.db.execute(update(Tenant).where(
            Tenant.id == self.tenant_id, Tenant.active.is_(True), Tenant.settings_version == payload["version"]
        ).values(settings_version=Tenant.settings_version))
        if locked.rowcount != 1:
            fail(409, "STALE_POLICY", "برنامه مرکز تغییر کرده است؛ زمان‌ها را دوباره دریافت کنید.")
        self.db.refresh(tenant)
        if payload["version"] != tenant.settings_version:
            fail(409, "STALE_POLICY", "برنامه مرکز تغییر کرده است؛ زمان‌ها را دوباره دریافت کنید.")
        provider, service = self._catalog(payload["provider"], payload["service"])
        occupied_end = self._valid_start(tenant, provider, service, start)
        return tenant, provider, service, start, occupied_end

    def slots(self, provider_id: str, service_id: str, date: str | Date) -> list[dict]:
        from .calendar_bridge import require_internal

        require_internal(self.db, self.tenant_id)
        tenant = self.tenant()
        provider, service = self._catalog(provider_id, service_id)
        try:
            local_date = Date.fromisoformat(date) if isinstance(date, str) else date
        except ValueError:
            fail(422, "INVALID_DATE", "تاریخ معتبر نیست.")
        timezone = ZoneInfo(tenant.timezone)
        today = now_utc().astimezone(timezone).date()
        if local_date < today or local_date > today + timedelta(days=tenant.booking_horizon_days):
            return []
        self._expire()
        self.db.commit()
        if local_date.isoformat() in tenant.holidays:
            return []
        result = []
        for opening, closing in self._intervals(tenant.working_hours, local_date):
            start = datetime.combine(local_date, time.fromisoformat(opening), timezone)
            close = datetime.combine(local_date, time.fromisoformat(closing), timezone)
            while start + timedelta(minutes=service.duration_minutes + service.buffer_minutes) <= close:
                end = start + timedelta(minutes=service.duration_minutes)
                occupied = end + timedelta(minutes=service.buffer_minutes)
                if (
                    start.astimezone(UTC) >= now_utc() + timedelta(minutes=tenant.lead_time_minutes)
                    and self._within_hours(tenant, provider, start, occupied)
                    and not self._disrupted(provider_id, start, occupied)
                    and not self._conflict(provider_id, service, start, occupied)
                ):
                    result.append(
                        {
                            "slot_id": self._encode_slot(tenant, provider_id, service_id, start.astimezone(UTC)),
                            "provider_id": provider_id,
                            "service_id": service_id,
                            "start_at": iso(start.astimezone(UTC)),
                            "end_at": iso(end.astimezone(UTC)),
                            "local_date": local_date.isoformat(),
                            "local_time": start.strftime("%H:%M"),
                            "display": jalali_label(start, tenant.timezone),
                            "timezone": tenant.timezone,
                            "available": True,
                            "settings_version": tenant.settings_version,
                        }
                    )
                start += timedelta(minutes=15)
        return result

    def hold(self, slot_id: str, session_id: str) -> dict:
        if not session_id or len(session_id) > 120:
            fail(422, "SESSION_REQUIRED", "شناسه نشست معتبر لازم است.")
        try:
            self._expire()
            tenant, provider, service, start, occupied_end = self._decode_slot(slot_id)
            existing = self.db.scalar(
                select(SlotHold).where(
                    SlotHold.tenant_id == self.tenant_id,
                    SlotHold.session_id == session_id,
                    SlotHold.provider_id == provider.id,
                    SlotHold.service_id == service.id,
                    SlotHold.start_at == start,
                    SlotHold.status == "HELD",
                )
            )
            if existing:
                return {"id": existing.id, "slot_id": existing.slot_id, "expires_at": iso(existing.expires_at), "status": existing.status}
            hold = SlotHold(
                id=uid(),
                tenant_id=tenant.id,
                provider_id=provider.id,
                service_id=service.id,
                slot_id=slot_id,
                session_id=session_id,
                start_at=start,
                end_at=occupied_end,
                expires_at=now_utc() + timedelta(minutes=settings.hold_minutes),
            )
            self.db.add(hold)
            self.db.flush()
            self._claims(provider.id, service, start, occupied_end, "hold", hold.id)
            self._audit("slot.held", "hold", hold.id, provider_id=provider.id)
            self.db.commit()
            return {"id": hold.id, "slot_id": slot_id, "expires_at": iso(hold.expires_at), "status": hold.status}
        except IntegrityError:
            self.db.rollback()
            fail(409, "SLOT_TAKEN", "این زمان همین حالا رزرو شد. زمان دیگری انتخاب کنید.")
        except OperationalError:
            self.db.rollback()
            fail(503, "CALENDAR_BUSY", "تقویم موقتاً مشغول است؛ دوباره تلاش کنید.")

    def _idempotent(self, operation: str, key: str, request: dict) -> dict | None:
        if not 8 <= len(key) <= 160:
            fail(422, "IDEMPOTENCY_KEY_REQUIRED", "کلید معتبر برای جلوگیری از ثبت تکراری لازم است.")
        row = self.db.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == self.tenant_id, IdempotencyRecord.operation == operation, IdempotencyRecord.key == key
            )
        )
        if row:
            if row.request_hash != request_digest(request):
                fail(409, "IDEMPOTENCY_MISMATCH", "کلید تکرار با درخواست دیگری استفاده شده است.")
            booking = self.db.scalar(
                select(Appointment)
                .where(Appointment.id == row.entity_id, Appointment.tenant_id == self.tenant_id)
                .execution_options(populate_existing=True)
            )
            if booking is None:
                fail(410, "BOOKING_NO_LONGER_AVAILABLE", "این سابقه دیگر در دسترس نیست؛ پذیرش باید آن را بررسی کند.")
            # Replays suppress a second write while reporting current authority.
            # A previously confirmed booking may since have been canceled.
            return self.appointment_dict(booking)
        return None

    def _record(self, operation: str, key: str, request: dict, result: dict):
        self.db.add(
            IdempotencyRecord(
                tenant_id=self.tenant_id,
                operation=operation,
                key=key,
                request_hash=request_digest(request),
                entity_id=result["id"],
                response={"encrypted": encrypt(json.dumps(result, ensure_ascii=False))},
            )
        )

    def _notice(self, booking: Appointment, purpose: str):
        self.db.add(
            MessageOutbox(
                tenant_id=self.tenant_id,
                appointment_id=booking.id,
                recipient_encrypted=booking.phone_encrypted,
                purpose=purpose,
                template=f"appointment_{purpose}_v1",
                dedupe_key=f"{booking.id}:{purpose}:v{booking.version}",
                payload={"reference": booking.reference, "start_at": iso(booking.start_at), "status": booking.status},
            )
        )

    def create_appointment(
        self,
        slot_id: str,
        patient_name: str,
        phone: str,
        idempotency_key: str,
        confirmed: bool,
        hold_id: str | None = None,
        session_id: str | None = None,
        reminder_opt_in: bool = False,
        force_approval: bool = False,
        payment_terms_version: int | None = None,
        payment_terms_accepted: bool = False,
        package_entitlement_id: str | None = None,
    ) -> dict:
        if confirmed is not True:
            fail(422, "CONFIRMATION_REQUIRED", "پیش از ثبت، تایید صریح تماس‌گیرنده لازم است.")
        name = patient_name.strip()
        if not 2 <= len(name) <= 120 or any(ord(c) < 32 for c in name):
            fail(422, "INVALID_NAME", "نام معتبر وارد کنید.")
        phone = normalize_phone(phone)
        request = {
            "slot_id": slot_id,
            "patient_name": name,
            "phone_hash": hash_phone(phone),
            "confirmed": confirmed,
            "hold_id": hold_id,
            "session_id": session_id,
            "reminder_opt_in": reminder_opt_in,
            "force_approval": force_approval,
            "payment_terms_version": payment_terms_version,
            "payment_terms_accepted": payment_terms_accepted,
            "package_entitlement_id": package_entitlement_id,
        }
        previous = self._idempotent("create", idempotency_key, request)
        if previous:
            return previous
        try:
            self._expire()
            tenant, provider, service, start, occupied_end = self._decode_slot(slot_id)
            from .payment_policy import booking_payment_terms

            payment_terms = booking_payment_terms(self.db, tenant.id, service, payment_terms_version, payment_terms_accepted)
            from .bookings_ext import check_eligibility, consume_package

            entitlement, package_units = check_eligibility(self.db, tenant.id, service, hash_phone(phone), at=start, entitlement_id=package_entitlement_id)
            hold = None
            if hold_id:
                hold = self.db.scalar(
                    select(SlotHold).where(SlotHold.id == hold_id, SlotHold.tenant_id == self.tenant_id).with_for_update()
                )
                if (
                    not hold
                    or hold.status != "HELD"
                    or hold.expires_at <= now_utc()
                    or hold.session_id != session_id
                    or hold.start_at != start
                    or hold.provider_id != provider.id
                    or hold.service_id != service.id
                ):
                    fail(409, "INVALID_HOLD", "مهلت نگه‌داری زمان تمام شده یا با این نشست سازگار نیست.")
            booking = Appointment(
                id=uid(),
                tenant_id=self.tenant_id,
                provider_id=provider.id,
                service_id=service.id,
                reference="B-" + secrets.token_hex(4).upper(),
                patient_name_encrypted=encrypt(name),
                phone_encrypted=encrypt(phone),
                phone_hash=hash_phone(phone),
                session_id=session_id,
                start_at=start,
                end_at=start + timedelta(minutes=service.duration_minutes),
                occupied_until=occupied_end,
                status="PENDING_PAYMENT"
                if service.deposit_toman
                else "PENDING_STAFF_APPROVAL"
                if service.requires_approval or force_approval
                else "CONFIRMED",
                price_toman=service.price_toman,
                deposit_toman=service.deposit_toman,
                payment_terms_snapshot=payment_terms,
                payment_status="PENDING" if service.deposit_toman else "NOT_REQUIRED",
                approval_required=service.requires_approval or force_approval,
                expires_at=min(start, now_utc() + timedelta(minutes=payment_terms["hold_minutes"])) if payment_terms else None,
                reminder_opt_in=reminder_opt_in,
                settings_version=tenant.settings_version,
                version=1,
            )
            self.db.add(booking)
            self.db.flush()
            consume_package(self.db, booking, entitlement, package_units)
            if hold:
                self.db.execute(
                    update(Occupancy)
                    .where(Occupancy.tenant_id == self.tenant_id, Occupancy.owner_type == "hold", Occupancy.owner_id == hold.id)
                    .values(owner_type="appointment", owner_id=booking.id)
                )
                hold.status = "CONSUMED"
            else:
                self._claims(provider.id, service, start, occupied_end, "appointment", booking.id)
            self._notice(booking, "confirmed" if booking.status == "CONFIRMED" else "pending")
            if booking.status == "PENDING_STAFF_APPROVAL":
                self.db.add(
                    StaffTask(
                        tenant_id=self.tenant_id,
                        reason="BOOKING_APPROVAL",
                        summary="نوبت برای تایید نهایی نیاز به بررسی پذیرش دارد.",
                        appointment_id=booking.id,
                    )
                )
            self._audit("appointment.created", "appointment", booking.id, status=booking.status, provider_id=provider.id)
            self.db.add(UsageEvent(tenant_id=self.tenant_id, call_id=session_id, kind="booking", quantity=1, unit="count", cost_toman=0))
            self.db.flush()
            result = self.appointment_dict(booking)
            self._record("create", idempotency_key, request, result)
            self.db.commit()
            # Reading the committed row establishes the authoritative response.
            self.db.refresh(booking)
            return self.appointment_dict(booking)
        except IntegrityError:
            self.db.rollback()
            replay = self._idempotent("create", idempotency_key, request)
            if replay:
                return replay
            fail(409, "SLOT_TAKEN", "این زمان همین حالا رزرو شد. زمان دیگری انتخاب کنید.")
        except OperationalError:
            self.db.rollback()
            fail(503, "CALENDAR_BUSY", "ثبت نوبت فعلاً ممکن نیست. پیش از تلاش دوباره، نتیجه بررسی می‌شود.")

    def get_appointment(self, appointment_id: str, lock: bool = False) -> Appointment:
        query = select(Appointment).where(Appointment.id == appointment_id, Appointment.tenant_id == self.tenant_id)
        if lock:
            query = query.with_for_update()
        booking = self.db.scalar(query)
        if not booking:
            fail(404, "NOT_FOUND", "نوبت پیدا نشد.")
        return booking

    def appointment_dict(self, booking: Appointment) -> dict:
        from .payment_policy import public_snapshot

        if booking.tenant_id != self.tenant_id:
            fail(404, "NOT_FOUND", "نوبت پیدا نشد.")
        tenant = self.tenant()
        local = booking.start_at.astimezone(ZoneInfo(tenant.timezone))
        provider = self.db.get(Practitioner, booking.provider_id)
        service = self.db.get(Service, booking.service_id)
        message = self.db.scalar(
            select(MessageOutbox)
            .where(MessageOutbox.tenant_id == self.tenant_id, MessageOutbox.appointment_id == booking.id)
            .order_by(MessageOutbox.created_at.desc())
            .limit(1)
        )
        return {
            "id": booking.id,
            "reference": booking.reference,
            "provider_id": booking.provider_id,
            "provider_name": provider.name,
            "service_id": booking.service_id,
            "service_name": service.name,
            "patient_name": decrypt(booking.patient_name_encrypted),
            "phone_masked": mask_phone(decrypt(booking.phone_encrypted)),
            "start_at": iso(booking.start_at),
            "end_at": iso(booking.end_at),
            "local_date": local.date().isoformat(),
            "local_time": local.strftime("%H:%M"),
            "jalali_display": jalali_label(booking.start_at, tenant.timezone),
            "status": booking.status,
            "attendance": booking.attendance,
            "price_toman": booking.price_toman,
            "deposit_toman": booking.deposit_toman,
            "payment_status": booking.payment_status,
            "payment_terms": public_snapshot(booking.payment_terms_snapshot),
            "payment_expires_at": iso(booking.expires_at),
            "notification_status": message.status if message else "NOT_QUEUED",
            "version": booking.version,
            "created_at": iso(booking.created_at),
            "reminder_opt_in": booking.reminder_opt_in,
            "disruptions": [{"id": impact.disruption_id, "state": impact.state} for impact in self.db.scalars(
                select(AppointmentImpact).where(AppointmentImpact.tenant_id == self.tenant_id,
                                               AppointmentImpact.appointment_id == booking.id, AppointmentImpact.state != "RESOLVED")
            )],
        }

    def _version(self, booking: Appointment, version: int):
        if booking.version != version:
            fail(409, "STALE_VERSION", "این نوبت تغییر کرده است. اطلاعات را تازه کنید.")

    def cancel_appointment(self, appointment_id: str, idempotency_key: str, version: int, reason: str = "", verified: bool = False) -> dict:
        if not verified:
            fail(403, "VERIFICATION_REQUIRED", "برای تغییر نوبت، احراز هویت لازم است.")
        request = {"id": appointment_id, "version": version, "reason_hash": request_digest({"reason": reason})}
        previous = self._idempotent("cancel", idempotency_key, request)
        if previous:
            return previous
        self.db.execute(update(Tenant).where(Tenant.id == self.tenant_id).values(settings_version=Tenant.settings_version))
        booking = self.get_appointment(appointment_id, lock=True)
        self._version(booking, version)
        if booking.status not in ACTIVE_APPOINTMENTS or booking.attendance is not None:
            fail(409, "INVALID_STATE", "این نوبت قابل لغو نیست.")
        if booking.start_at <= now_utc():
            fail(409, "APPOINTMENT_STARTED", "نوبت گذشته نیاز به بررسی پذیرش دارد.")
        if booking.status == "CONFIRMED" and booking.start_at < now_utc() + timedelta(hours=self.tenant().cancellation_notice_hours):
            fail(409, "CANCELLATION_WINDOW", "لغو نزدیک به زمان نوبت نیاز به بررسی پذیرش دارد.")
        try:
            # Conditional version write also protects SQLite where FOR UPDATE is ignored.
            updated = self.db.execute(
                update(Appointment)
                .where(
                    Appointment.id == booking.id,
                    Appointment.tenant_id == self.tenant_id,
                    Appointment.version == version,
                    Appointment.status.in_(ACTIVE_APPOINTMENTS),
                )
                .values(status="CANCELED", version=version + 1, updated_at=now_utc())
            )
            if updated.rowcount != 1:
                fail(409, "STALE_VERSION", "نوبت هم‌زمان تغییر کرده است.")
            self.db.execute(
                delete(Occupancy).where(
                    Occupancy.tenant_id == self.tenant_id, Occupancy.owner_id == booking.id, Occupancy.owner_type == "appointment"
                )
            )
            self.db.refresh(booking)
            from .bookings_ext import release_package

            release_package(self.db, self.tenant_id, booking.id)
            self._notice(booking, "canceled")
            from .operations_outreach import record_capacity_release

            record_capacity_release(self.db, booking, "appointment_canceled", booking.version)
            if booking.payment_status == "PAID":
                self.db.add(
                    StaffTask(
                        tenant_id=self.tenant_id,
                        reason="REFUND_REVIEW",
                        summary="نوبت پرداخت‌شده لغو شد؛ بازپرداخت طبق سیاست مرکز بررسی شود.",
                        appointment_id=booking.id,
                    )
                )
            self._audit("appointment.canceled", "appointment", booking.id, previous_version=version, reason_provided=bool(reason))
            self.db.flush()
            result = self.appointment_dict(booking)
            self._record("cancel", idempotency_key, request, result)
            self.db.commit()
            return result
        except IntegrityError:
            self.db.rollback()
            replay = self._idempotent("cancel", idempotency_key, request)
            if replay:
                return replay
            fail(409, "CONCURRENT_CHANGE", "اطلاعات نوبت تغییر کرده است.")

    def reschedule_appointment(self, appointment_id: str, slot_id: str, idempotency_key: str, version: int, verified: bool = False) -> dict:
        if not verified:
            fail(403, "VERIFICATION_REQUIRED", "برای تغییر نوبت، احراز هویت لازم است.")
        request = {"id": appointment_id, "slot_id": slot_id, "version": version}
        previous = self._idempotent("reschedule", idempotency_key, request)
        if previous:
            return previous
        try:
            self._expire()
            booking = self.get_appointment(appointment_id, lock=True)
            self._version(booking, version)
            if booking.status not in {"CONFIRMED", "PENDING_STAFF_APPROVAL"} or booking.attendance:
                fail(409, "INVALID_STATE", "این نوبت قابل جابه‌جایی نیست.")
            if booking.start_at < now_utc() + timedelta(hours=self.tenant().cancellation_notice_hours):
                fail(409, "CANCELLATION_WINDOW", "تغییر نزدیک به زمان نوبت نیاز به بررسی پذیرش دارد.")
            tenant, provider, service, start, occupied_end = self._decode_slot(slot_id)
            if service.id != booking.service_id:
                fail(422, "SERVICE_CHANGE_REQUIRES_REVIEW", "تغییر نوع خدمت باید توسط پذیرش بررسی شود.")
            from .bookings_ext import check_eligibility
            from .models_core import PackageUse

            package_use = self.db.get(PackageUse, booking.id)
            entitlement, units = check_eligibility(self.db, tenant.id, service, booking.phone_hash, at=start,
                entitlement_id=package_use.entitlement_id if package_use and not package_use.released else None,
                existing_units=package_use.units if package_use and not package_use.released else 0)
            if (package_use and not package_use.released and units != package_use.units) or (entitlement and not package_use):
                fail(409, "PACKAGE_POLICY_CHANGED", "شرایط بسته تغییر کرده است؛ پذیرش باید اعتبار جلسه را بررسی کند.")
            old_start = booking.start_at
            if provider.id != booking.provider_id or start != booking.start_at:
                from .operations_outreach import record_capacity_release

                record_capacity_release(self.db, booking, "appointment_rescheduled", version + 1)
            updated = self.db.execute(
                update(Appointment)
                .where(Appointment.id == booking.id, Appointment.tenant_id == self.tenant_id, Appointment.version == version)
                .values(
                    provider_id=provider.id,
                    start_at=start,
                    end_at=start + timedelta(minutes=service.duration_minutes),
                    occupied_until=occupied_end,
                    version=version + 1,
                    settings_version=tenant.settings_version,
                    updated_at=now_utc(),
                )
            )
            if updated.rowcount != 1:
                fail(409, "STALE_VERSION", "نوبت هم‌زمان تغییر کرده است.")
            self.db.execute(
                delete(Occupancy).where(
                    Occupancy.tenant_id == self.tenant_id, Occupancy.owner_id == booking.id, Occupancy.owner_type == "appointment"
                )
            )
            self._claims(provider.id, service, start, occupied_end, "appointment", booking.id)
            self.db.flush()  # A collision rolls back BOTH old-slot release and new-slot claim.
            self.db.refresh(booking)
            self._notice(booking, "rescheduled")
            self._audit("appointment.rescheduled", "appointment", booking.id, old_start=iso(old_start), new_start=iso(start))
            self.db.flush()
            result = self.appointment_dict(booking)
            self._record("reschedule", idempotency_key, request, result)
            self.db.commit()
            return result
        except IntegrityError:
            self.db.rollback()
            replay = self._idempotent("reschedule", idempotency_key, request)
            if replay:
                return replay
            fail(409, "SLOT_TAKEN", "زمان جدید در دسترس نیست؛ نوبت قبلی شما حفظ شد.")

    def approve(self, appointment_id: str, version: int) -> dict:
        booking = self.get_appointment(appointment_id, lock=True)
        self._version(booking, version)
        if booking.status != "PENDING_STAFF_APPROVAL" or booking.payment_status not in {"NOT_REQUIRED", "PAID"}:
            fail(409, "INVALID_STATE", "این نوبت اکنون قابل تایید نیست.")
        updated = self.db.execute(
            update(Appointment)
            .where(
                Appointment.id == booking.id,
                Appointment.tenant_id == self.tenant_id,
                Appointment.version == version,
                Appointment.status == "PENDING_STAFF_APPROVAL",
            )
            .values(status="CONFIRMED", version=version + 1)
        )
        if updated.rowcount != 1:
            fail(409, "STALE_VERSION", "نوبت هم‌زمان تغییر کرده است.")
        self.db.refresh(booking)
        self._notice(booking, "confirmed")
        self.db.execute(
            update(StaffTask)
            .where(
                StaffTask.tenant_id == self.tenant_id,
                StaffTask.appointment_id == booking.id,
                StaffTask.reason == "BOOKING_APPROVAL",
                StaffTask.status == "OPEN",
            )
            .values(status="RESOLVED", resolved_at=now_utc(), resolution="نوبت توسط پذیرش تایید شد.")
        )
        self._audit("appointment.approved", "appointment", booking.id)
        self.db.commit()
        return self.appointment_dict(booking)

    def settle_payment(self, appointment_id: str, amount_toman: int, payment_reference: str) -> dict:
        """Only a verified gateway callback may invoke this internal method."""
        self._expire()
        booking = self.get_appointment(appointment_id, lock=True)
        if booking.payment_status == "PAID":
            return self.appointment_dict(booking)
        if booking.status != "PENDING_PAYMENT" or booking.expires_at is None or booking.expires_at <= now_utc():
            fail(409, "PAYMENT_HOLD_EXPIRED", "پرداخت دیرهنگام نیاز به بررسی و بازپرداخت دارد.")
        if amount_toman != booking.deposit_toman:
            fail(409, "PAYMENT_AMOUNT_MISMATCH", "مبلغ پرداخت با بیعانه سازگار نیست.")
        new_status = "PENDING_STAFF_APPROVAL" if booking.approval_required else "CONFIRMED"
        updated = self.db.execute(
            update(Appointment)
            .where(
                Appointment.id == booking.id,
                Appointment.tenant_id == self.tenant_id,
                Appointment.status == "PENDING_PAYMENT",
                Appointment.version == booking.version,
                Appointment.expires_at > now_utc(),
            )
            .values(payment_status="PAID", status=new_status, expires_at=None, version=Appointment.version + 1)
        )
        if updated.rowcount != 1:
            fail(409, "PAYMENT_RACE", "نتیجه پرداخت نیاز به تطبیق دارد.")
        self.db.refresh(booking)
        self._notice(booking, "confirmed" if new_status == "CONFIRMED" else "pending")
        if new_status == "PENDING_STAFF_APPROVAL":
            self.db.add(
                StaffTask(
                    tenant_id=self.tenant_id,
                    reason="BOOKING_APPROVAL",
                    summary="بیعانه دریافت شد؛ نوبت نیاز به تایید پذیرش دارد.",
                    appointment_id=booking.id,
                )
            )
        self._audit("payment.settled", "appointment", booking.id, amount_toman=amount_toman, payment_reference=payment_reference)
        # Caller owns the gateway-ledger commit; no commit here, to keep it atomic.
        self.db.flush()
        return self.appointment_dict(booking)

    def outcome(self, appointment_id: str, outcome: str, version: int) -> dict:
        if outcome not in {"ATTENDED", "NO_SHOW"}:
            fail(422, "INVALID_OUTCOME", "وضعیت مراجعه معتبر نیست.")
        booking = self.get_appointment(appointment_id, lock=True)
        self._version(booking, version)
        if booking.status != "CONFIRMED" or booking.start_at > now_utc():
            fail(409, "INVALID_STATE", "نتیجه مراجعه فقط بعد از شروع نوبت تاییدشده ثبت می‌شود.")
        if booking.attendance:
            fail(409, "OUTCOME_ALREADY_RECORDED", "نتیجه مراجعه قبلاً ثبت شده است.")
        changed = self.db.execute(
            update(Appointment)
            .where(
                Appointment.id == booking.id,
                Appointment.tenant_id == self.tenant_id,
                Appointment.version == version,
                Appointment.attendance.is_(None),
            )
            .values(attendance=outcome, version=version + 1)
        )
        if changed.rowcount != 1:
            fail(409, "STALE_VERSION", "اطلاعات نوبت تغییر کرده است.")
        self._audit("appointment.attendance", "appointment", booking.id, outcome=outcome)
        self.db.commit()
        self.db.refresh(booking)
        return self.appointment_dict(booking)

    def settings_dict(self):
        tenant = self.tenant()
        keys = [
            "id",
            "name",
            "slug",
            "timezone",
            "mode",
            "settings_version",
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
        ]
        return {key: getattr(tenant, key) for key in keys}

    def update_settings(self, changes: dict, *, reason: str = "settings_changed", restored_from: int | None = None):
        from .operations_extensions import capture_policy
        from .operations_uat import require_matching_uat

        changes = dict(changes)
        tenant = self.tenant()
        self.db.execute(update(Tenant).where(Tenant.id == self.tenant_id).values(settings_version=Tenant.settings_version))
        self.db.refresh(tenant)
        version = changes.pop("version")
        if tenant.settings_version != version:
            fail(409, "STALE_VERSION", "تنظیمات توسط شخص دیگری تغییر کرده است.")
        hours = changes.get("working_hours")
        if hours is not None:
            try:
                if any(k not in {str(n) for n in range(7)} for k in hours):
                    raise ValueError
                for intervals in hours.values():
                    previous_end = None
                    for interval in intervals:
                        if len(interval) != 2:
                            raise ValueError
                        begin, end = map(time.fromisoformat, interval)
                        if begin >= end or begin.second or end.second or (previous_end and begin < previous_end):
                            raise ValueError
                        previous_end = end
            except (ValueError, TypeError):
                fail(422, "INVALID_HOURS", "ساعت‌های کاری باید مرتب، بدون هم‌پوشانی و در یک روز باشند.")
        if changes.get("holidays") is not None:
            try:
                for holiday in changes["holidays"]:
                    Date.fromisoformat(holiday)
            except ValueError:
                fail(422, "INVALID_HOLIDAYS", "تاریخ تعطیلی معتبر نیست.")
        if changes.get("quiet_hours") is not None:
            try:
                quiet = changes["quiet_hours"]
                if set(quiet) != {"start", "end"}:
                    raise ValueError
                time.fromisoformat(quiet["start"])
                time.fromisoformat(quiet["end"])
                if quiet["start"] == quiet["end"]:
                    raise ValueError
            except (ValueError, TypeError):
                fail(422, "INVALID_QUIET_HOURS", "بازه سکوت پیام‌ها معتبر نیست.")
        values = {key: value for key, value in changes.items() if value is not None}
        if "faq" in values:
            default_keywords = {
                "hours": ["ساعت کاری", "کی باز", "چه ساعتی", "ساعت کار"],
                "address": ["آدرس", "نشانی", "کجاست", "کجا هست"],
                "insurance": ["بیمه"],
                "parking": ["پارکینگ", "پارک ماشین"],
            }
            for fact in values["faq"]:
                fact["approved_by"] = self.actor_id
                fact["source"] = fact.get("source") or "owner-approved clinic policy"
                fact["effective_at"] = fact.get("effective_at") or iso(now_utc())
                fact["expires_at"] = fact.get("expires_at") or iso(now_utc() + timedelta(days=30))
                fact["keywords"] = fact.get("keywords") or default_keywords.get(fact.get("category"), [fact["question"]])
                try:
                    effective = datetime.fromisoformat(fact["effective_at"].replace("Z", "+00:00"))
                    expiry = datetime.fromisoformat(fact["expires_at"].replace("Z", "+00:00"))
                    if effective.tzinfo is None or expiry.tzinfo is None or expiry <= effective:
                        raise ValueError
                except (ValueError, TypeError):
                    fail(422, "INVALID_FAQ_VALIDITY", "زمان اعتبار اطلاعات مرکز معتبر نیست.")
        require_matching_uat(self.db, tenant, values.get("mode", tenant.mode), values)
        capture_policy(self.db, tenant, self.actor_id, "baseline_before_publication", [])
        changed = self.db.execute(
            update(Tenant)
            .where(Tenant.id == self.tenant_id, Tenant.settings_version == version)
            .values(**values, settings_version=version + 1)
        )
        if changed.rowcount != 1:
            fail(409, "STALE_VERSION", "تنظیمات هم‌زمان تغییر کرده است.")
        self.db.refresh(tenant)
        from .core_policy import FACT_FIELDS, publish_facts

        approved_fields = [key for key in values if key in FACT_FIELDS["tenant"]]
        if approved_fields:
            publish_facts(self.db, self.tenant_id, "tenant", tenant, self.actor_id, fields=approved_fields)
        capture_policy(self.db, tenant, self.actor_id, reason, sorted(values), restored_from)
        self._audit("policy.published", "tenant", tenant.id, version=version + 1, changed_fields=sorted(values))
        self.db.commit()
        self.db.refresh(tenant)
        return self.settings_dict()
