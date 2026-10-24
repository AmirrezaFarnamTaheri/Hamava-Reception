"""Durable privacy-minimized traces, operational escalation and outreach jobs."""
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, UTCDateTime, now_utc
from .models import uid


class TraceEvent(Base):
    __tablename__ = "trace_events"
    __table_args__ = (UniqueConstraint("tenant_id", "event_key", name="uq_trace_event_key"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    event_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("trace_events.id"), nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    turn_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(80), nullable=True)
    event: Mapped[str] = mapped_column(String(80))
    versions: Mapped[dict] = mapped_column(JSON)
    attributes: Mapped[dict] = mapped_column(JSON)
    occurred_at: Mapped[object] = mapped_column(UTCDateTime)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class OperationalAlert(Base):
    __tablename__ = "operational_alerts"
    __table_args__ = (UniqueConstraint("tenant_id", "dedupe_key", name="uq_operational_alert_key"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(80))
    severity: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="OPEN")
    evidence: Mapped[dict] = mapped_column(JSON)
    acknowledged_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    acknowledged_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    resolved_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    resolution_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class OnCallPolicy(Base):
    __tablename__ = "oncall_policies"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    user_ids: Mapped[list] = mapped_column(JSON)
    escalation_minutes: Mapped[int] = mapped_column(Integer, default=10)
    spike_window_minutes: Mapped[int] = mapped_column(Integer, default=10)
    spike_cap_toman: Mapped[int] = mapped_column(Integer, default=100000)
    provider_failure_threshold: Mapped[int] = mapped_column(Integer, default=5)
    updated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"
    __table_args__ = (UniqueConstraint("alert_id", "level", name="uq_alert_escalation_level"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    alert_id: Mapped[str] = mapped_column(ForeignKey("operational_alerts.id"))
    level: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    task_id: Mapped[str] = mapped_column(ForeignKey("staff_tasks.id"))
    status: Mapped[str] = mapped_column(String(30), default="IN_APP_DISPATCHED")
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class SMSReceiptPoll(Base):
    __tablename__ = "sms_receipt_polls"
    message_id: Mapped[str] = mapped_column(ForeignKey("message_outbox.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_poll_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc, index=True)
    lease_until: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    last_status: Mapped[str] = mapped_column(String(40), default="PENDING")
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    stopped_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class VoiceOutreach(Base):
    __tablename__ = "voice_outreach_jobs"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_voice_outreach_key"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"))
    subject_hash: Mapped[str] = mapped_column(String(64))
    recipient_encrypted: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30), default="QUEUED", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_seconds: Mapped[int] = mapped_column(Integer, default=60)
    provider_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    reservation_id: Mapped[str | None] = mapped_column(ForeignKey("cost_reservations.id"), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    not_before: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    lease_until: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    voicemail_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
