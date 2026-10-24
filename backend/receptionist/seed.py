"""Explicit synthetic demonstration fixtures, forbidden in production."""

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .core import ReceptionService
from .db import now_utc
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
from .security import encrypt, hash_password, hash_phone

DEMO_PASSWORD = "DemoReception2026!"


def seed_demo(db: Session):
    if not settings.demo_mode or settings.environment.lower() in {"production", "prod"}:
        raise RuntimeError("Demo fixtures may only be seeded in explicit development demo mode")
    if db.get(Tenant, "clinic-bahar"):
        return
    hours = {str(i): [["09:00", "13:00"], ["16:00", "20:00"]] for i in range(7)}
    bahar = Tenant(
        id="clinic-bahar",
        slug="bahar",
        name="کلینیک نمایشی بهار",
        building_id="demo-building",
        working_hours=hours,
        address="تهران، خیابان نمونه، ساختمان بهار، طبقه دوم — نشانی نمایشی",
        phone="۰۲۱-۰۰۰۰۰۰۰۰",
        timezone="Asia/Tehran",
        lead_time_minutes=30,
        faq=[
            {
                "question": "ساعت کاری شما چه زمانی است؟",
                "answer": "در برنامه نمایشی، هر روز از ۹ تا ۱۳ و ۱۶ تا ۲۰ باز هستیم.",
                "category": "hours",
            },
            {
                "question": "آدرس کلینیک کجاست؟",
                "answer": "تهران، خیابان نمونه، ساختمان بهار، طبقه دوم. این نشانی برای نمایش است.",
                "category": "address",
            },
            {"question": "بیمه قبول می‌کنید؟", "answer": "برای بررسی پوشش بیمه، پذیرش با شما هماهنگ می‌کند.", "category": "insurance"},
        ],
        cancellation_notice_hours=2,
    )
    niloufar = Tenant(
        id="clinic-niloufar",
        slug="niloufar",
        name="سالن نمایشی نیلوفر",
        working_hours=hours,
        address="تهران، خیابان نمونه دوم — نشانی نمایشی",
        phone="۰۲۱-۰۰۰۰۰۰۰۰",
        lead_time_minutes=30,
        faq=[{"question": "ساعت کاری؟", "answer": "ساعت کاری برنامه نمایشی ۹ تا ۱۳ و ۱۶ تا ۲۰ است.", "category": "hours"}],
        cancellation_notice_hours=2,
    )
    keywords = {
        "hours": ["ساعت کاری", "کی باز", "چه ساعتی", "ساعت کار"],
        "address": ["آدرس", "نشانی", "کجاست", "کجا هست"],
        "insurance": ["بیمه"],
    }
    for tenant in (bahar, niloufar):
        tenant.mode = "ai_primary"
        tenant.faq = [
            {
                **fact,
                "approved_by": "demo-owner",
                "source": "synthetic demonstration clinic policy",
                "effective_at": now_utc().isoformat(),
                "expires_at": (now_utc() + timedelta(days=30)).isoformat(),
                "keywords": keywords.get(fact["category"], [fact["question"]]),
            }
            for fact in tenant.faq
        ]
    db.add_all([bahar, niloufar])
    db.flush()
    owner = User(id="demo-owner", email="owner@example.test", name="مدیر نمونه", password_hash=hash_password(DEMO_PASSWORD))
    other = User(id="demo-other", email="other@example.test", name="پذیرش نیلوفر", password_hash=hash_password(DEMO_PASSWORD))
    receptionist = User(
        id="demo-receptionist", email="receptionist@demo.local", name="پذیرش بهار", password_hash=hash_password(DEMO_PASSWORD)
    )
    db.add_all([owner, other, receptionist])
    db.flush()
    db.add_all(
        [
            Membership(user_id=owner.id, tenant_id=bahar.id, role="owner"),
            Membership(user_id=owner.id, tenant_id=niloufar.id, role="owner"),
            Membership(user_id=other.id, tenant_id=niloufar.id, role="receptionist"),
            Membership(user_id=receptionist.id, tenant_id=bahar.id, role="receptionist"),
        ]
    )
    p1 = Practitioner(id="provider-bahar-1", tenant_id=bahar.id, name="دکتر مهتاب رضایی (نمونه)", specialty="دندان‌پزشکی")
    p2 = Practitioner(id="provider-bahar-2", tenant_id=bahar.id, name="دکتر آرش زمانی (نمونه)", specialty="مشاوره تخصصی")
    p3 = Practitioner(id="provider-niloufar-1", tenant_id=niloufar.id, name="نرگس پارسا (نمونه)", specialty="خدمات زیبایی")
    db.add_all([p1, p2, p3])
    db.flush()
    s1 = Service(
        id="service-consultation",
        tenant_id=bahar.id,
        name="ویزیت دندان‌پزشکی",
        description="ویزیت اداری نمونه؛ بدون توصیه پزشکی.",
        provider_ids=[p1.id, p2.id],
        duration_minutes=30,
        buffer_minutes=0,
        price_toman=650000,
    )
    s2 = Service(
        id="service-specialist",
        tenant_id=bahar.id,
        name="مشاوره تخصصی",
        description="نیازمند تایید پذیرش",
        provider_ids=[p2.id],
        resource_ids=["consultation-room"],
        duration_minutes=45,
        buffer_minutes=15,
        price_toman=900000,
        requires_approval=True,
    )
    s3 = Service(
        id="service-salon",
        tenant_id=niloufar.id,
        name="خدمت زیبایی نمونه",
        description="برای تمرین گردش کار بیعانه",
        provider_ids=[p3.id],
        resource_ids=["chair-1"],
        duration_minutes=60,
        buffer_minutes=15,
        price_toman=1200000,
        deposit_toman=100000,
    )
    db.add_all([s1, s2, s3])
    db.commit()

    zone = ZoneInfo("Asia/Tehran")
    today = now_utc().astimezone(zone).date()
    specs = [
        ("demo-appt-1", today, "09:00", p1, s1, "سارا نمونه", "CONFIRMED"),
        ("demo-appt-2", today, "10:00", p1, s1, "علی نمونه", "CONFIRMED"),
        ("demo-appt-3", today, "16:00", p2, s2, "مریم نمونه", "PENDING_STAFF_APPROVAL"),
        ("demo-appt-4", today + timedelta(days=1), "10:00", p1, s1, "نگار نمونه", "CONFIRMED"),
    ]
    for n, (booking_id, day, clock, provider, service, name, status) in enumerate(specs, 1):
        start = datetime.combine(day, time.fromisoformat(clock), zone)
        end = start + timedelta(minutes=service.duration_minutes)
        phone = f"0912000000{n}"
        booking = Appointment(
            id=booking_id,
            tenant_id=bahar.id,
            provider_id=provider.id,
            service_id=service.id,
            reference=f"DEMO-{n:04}",
            patient_name_encrypted=encrypt(name),
            phone_encrypted=encrypt(phone),
            phone_hash=hash_phone(phone),
            start_at=start,
            end_at=end,
            occupied_until=end + timedelta(minutes=service.buffer_minutes),
            status=status,
            price_toman=service.price_toman,
            deposit_toman=0,
            payment_status="NOT_REQUIRED",
            approval_required=service.requires_approval,
            version=1,
            settings_version=1,
            reminder_opt_in=True,
            attendance="ATTENDED" if n == 1 and start < now_utc() else None,
        )
        db.add(booking)
        db.flush()
        ReceptionService(db, bahar.id)._claims(provider.id, service, start, booking.occupied_until, "appointment", booking.id)
        db.add(
            MessageOutbox(
                tenant_id=bahar.id,
                appointment_id=booking.id,
                recipient_encrypted=booking.phone_encrypted,
                purpose="confirmed" if status == "CONFIRMED" else "pending",
                template="appointment_demo_v1",
                payload={"reference": booking.reference, "start_at": start.isoformat(), "demo": True},
                dedupe_key=f"seed:{booking.id}",
                status="FAILED" if n == 2 else "QUEUED",
                attempts=1 if n == 2 else 0,
                last_error_code="DEMO_SIMULATED_FAILURE" if n == 2 else None,
            )
        )
    db.add_all(
        [
            StaffTask(
                tenant_id=bahar.id,
                reason="BOOKING_APPROVAL",
                summary="درخواست مشاوره تخصصی برای تایید نهایی آماده است. داده نمایشی.",
                appointment_id="demo-appt-3",
                priority="normal",
            ),
            StaffTask(
                tenant_id=bahar.id,
                reason="CALLBACK_REQUEST",
                summary="تماس‌گیرنده نمونه درخواست کرده پذیرش درباره زمان مراجعه هماهنگ کند.",
                priority="high",
            ),
            AuditEvent(
                tenant_id=bahar.id,
                actor_id="demo-seed",
                action="demo.initialized",
                entity_type="tenant",
                entity_id=bahar.id,
                details={"synthetic": True, "message": "تمام اطلاعات این مرکز نمونه است."},
            ),
            UsageEvent(tenant_id=bahar.id, kind="demo_call_duration", quantity=23.5, unit="minute", cost_toman=0),
            UsageEvent(tenant_id=bahar.id, kind="call", quantity=9, unit="count", cost_toman=0),
            UsageEvent(tenant_id=bahar.id, kind="booking", quantity=4, unit="count", cost_toman=0),
        ]
    )
    # Fictional demo approvals are explicitly labelled synthetic; no live clinic attestation.
    from .core_policy import publish_facts
    from .models_core import CalendarAuthority

    for tenant in (bahar, niloufar):
        publish_facts(db, tenant.id, "tenant", tenant, "demo-seed", source="Synthetic clinic fixture; not real clinical evidence")
        db.add(CalendarAuthority(tenant_id=tenant.id, kind="internal", provider_key="internal_calendar",
            version=1, capabilities={"read": True, "hold": True, "create": True, "cancel": True, "update": True,
                                    "atomic_conflict": True, "readback": True}, approved_by="demo-seed",
            expires_at=now_utc() + timedelta(days=365)))
    for row in db.scalars(select(Practitioner)):
        publish_facts(db, row.tenant_id, "practitioner", row, "demo-seed", source="Synthetic practitioner fixture")
    for row in db.scalars(select(Service)):
        publish_facts(db, row.tenant_id, "service", row, "demo-seed", source="Synthetic service fixture")
    db.commit()
