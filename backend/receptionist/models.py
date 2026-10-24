"""Tenant-scoped business state; PII values are encrypted by the service boundary."""

from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, now_utc


def uid() -> str:
    return str(uuid4())


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(160))
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    timezone: Mapped[str] = mapped_column(String(60), default="Asia/Tehran")
    building_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    settings_version: Mapped[int] = mapped_column(Integer, default=1)
    mode: Mapped[str] = mapped_column(String(30), default="after_hours")
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    website: Mapped[str] = mapped_column(String(300), default="")
    working_hours: Mapped[dict] = mapped_column(JSON, default=dict)
    holidays: Mapped[list] = mapped_column(JSON, default=list)
    faq: Mapped[list] = mapped_column(JSON, default=list)
    retention_days: Mapped[int] = mapped_column(Integer, default=30)
    lead_time_minutes: Mapped[int] = mapped_column(Integer, default=60)
    booking_horizon_days: Mapped[int] = mapped_column(Integer, default=60)
    cancellation_notice_hours: Mapped[int] = mapped_column(Integer, default=12)
    quiet_hours: Mapped[dict] = mapped_column(JSON, default=lambda: {"start": "21:00", "end": "09:00"})
    monthly_minute_budget: Mapped[int] = mapped_column(Integer, default=2000)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160))
    password_hash: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "tenant_id"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(30), default="receptionist")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Practitioner(Base):
    __tablename__ = "practitioners"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    specialty: Mapped[str] = mapped_column(String(100), default="")
    working_hours: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Service(Base):
    __tablename__ = "services"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text, default="")
    provider_ids: Mapped[list] = mapped_column(JSON, default=list)
    resource_ids: Mapped[list] = mapped_column(JSON, default=list)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    buffer_minutes: Mapped[int] = mapped_column(Integer, default=0)
    price_toman: Mapped[int] = mapped_column(Integer, default=0)
    deposit_toman: Mapped[int] = mapped_column(Integer, default=0)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class SlotHold(Base):
    __tablename__ = "slot_holds"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("practitioners.id"))
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    slot_id: Mapped[str] = mapped_column(Text)
    session_id: Mapped[str] = mapped_column(String(120), index=True)
    start_at: Mapped[object] = mapped_column(UTCDateTime)
    end_at: Mapped[object] = mapped_column(UTCDateTime)
    expires_at: Mapped[object] = mapped_column(UTCDateTime, index=True)
    status: Mapped[str] = mapped_column(String(30), default="HELD")
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (UniqueConstraint("tenant_id", "reference"), Index("ix_appointment_tenant_start", "tenant_id", "start_at"))
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("practitioners.id"))
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    reference: Mapped[str] = mapped_column(String(30))
    patient_name_encrypted: Mapped[str] = mapped_column(Text)
    phone_encrypted: Mapped[str] = mapped_column(Text)
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    session_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    start_at: Mapped[object] = mapped_column(UTCDateTime)
    end_at: Mapped[object] = mapped_column(UTCDateTime)
    occupied_until: Mapped[object] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(40), default="CONFIRMED", index=True)
    attendance: Mapped[str | None] = mapped_column(String(30), nullable=True)
    price_toman: Mapped[int] = mapped_column(Integer, default=0)
    deposit_toman: Mapped[int] = mapped_column(Integer, default=0)
    payment_status: Mapped[str] = mapped_column(String(30), default="NOT_REQUIRED")
    payment_terms_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    approval_required: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    reminder_opt_in: Mapped[bool] = mapped_column(Boolean, default=False)
    reminder_sent_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    settings_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc, onupdate=now_utc)


class Occupancy(Base):
    """Unique resource/minute claims are the underlying calendar write authority."""

    __tablename__ = "occupancy"
    __table_args__ = (
        UniqueConstraint("tenant_id", "resource_id", "minute", name="uq_resource_minute"),
        Index("ix_occupancy_owner", "tenant_id", "owner_id"),
    )
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    resource_id: Mapped[str] = mapped_column(String(140))
    minute: Mapped[int] = mapped_column(Integer)
    owner_type: Mapped[str] = mapped_column(String(20))
    owner_id: Mapped[str] = mapped_column(String(60))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("tenant_id", "operation", "key", name="uq_idempotency_scope"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))
    operation: Mapped[str] = mapped_column(String(50))
    key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(60))
    response: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class StaffTask(Base):
    __tablename__ = "staff_tasks"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    reason: Mapped[str] = mapped_column(String(60))
    summary: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(60), nullable=True)
    resolution: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    resolved_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class MessageOutbox(Base):
    __tablename__ = "message_outbox"
    __table_args__ = (UniqueConstraint("tenant_id", "dedupe_key", name="uq_message_dedupe"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), nullable=True)
    recipient_encrypted: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(String(50))
    template: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    provider_id: Mapped[str | None] = mapped_column(String(150), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    available_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    locked_until: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc, onupdate=now_utc)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(50))
    entity_id: Mapped[str] = mapped_column(String(120))
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class UsageEvent(Base):
    __tablename__ = "usage_events"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[float] = mapped_column(Float, default=0)
    unit: Mapped[str] = mapped_column(String(30), default="count")
    cost_toman: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class ConsentGrant(Base):
    __tablename__ = "consent_grants"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    subject_hash: Mapped[str] = mapped_column(String(100), index=True)
    purpose: Mapped[str] = mapped_column(String(50))
    granted: Mapped[bool] = mapped_column(Boolean)
    policy_version: Mapped[str] = mapped_column(String(60))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    expires_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
