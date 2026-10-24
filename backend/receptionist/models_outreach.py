"""Published outreach policy and auditable patient response/capacity records."""

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, now_utc
from .models import uid


class OutreachPolicy(Base):
    __tablename__ = "outreach_policies"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    reminder_offsets_minutes: Mapped[list] = mapped_column(JSON, default=lambda: [1440])
    waitlist_auto_offer: Mapped[bool] = mapped_column(Boolean, default=False)
    waitlist_offer_limit_per_run: Mapped[int] = mapped_column(Integer, default=5)
    followup_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    followup_offsets_days: Mapped[list] = mapped_column(JSON, default=list)
    clinician_approved_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    clinician_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    clinician_approved_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class FollowupEnrollment(Base):
    __tablename__ = "followup_enrollments"
    __table_args__ = (UniqueConstraint("tenant_id", "appointment_id", "policy_version", name="uq_followup_enrollment"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"), index=True)
    subject_hash: Mapped[str] = mapped_column(String(64), index=True)
    policy_version: Mapped[int] = mapped_column(Integer)
    offsets_days: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    consent_grant_id: Mapped[str] = mapped_column(ForeignKey("consent_grants.id"))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class AppointmentResponse(Base):
    __tablename__ = "appointment_responses"
    __table_args__ = (UniqueConstraint("tenant_id", "appointment_id", "appointment_version", name="uq_appointment_response"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"), index=True)
    appointment_version: Mapped[int] = mapped_column(Integer)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_encrypted: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    action: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="AWAITING_RESPONSE")
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    responded_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class CapacityRelease(Base):
    __tablename__ = "capacity_releases"
    __table_args__ = (UniqueConstraint("tenant_id", "source_kind", "source_id", "source_version", name="uq_capacity_release"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("practitioners.id"))
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    start_at: Mapped[object] = mapped_column(UTCDateTime)
    end_at: Mapped[object] = mapped_column(UTCDateTime)
    source_kind: Mapped[str] = mapped_column(String(50))
    source_id: Mapped[str] = mapped_column(String(60))
    source_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    offer_id: Mapped[str | None] = mapped_column(ForeignKey("waitlist_offers.id"), nullable=True)
    available_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    locked_until: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    reason_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
