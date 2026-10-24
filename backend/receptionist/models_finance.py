"""Additive v2 financial evidence. Money is integer micro-Toman, never float.

Rates, charges, transport events and signed-off observations are append-only at
the application boundary. Corrections are separate, linked adjustment records.
"""
from sqlalchemy import JSON, BigInteger, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, UTCDateTime, now_utc
from .models import uid


class CostRate(Base):
    __tablename__ = "cost_rates"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "meter", "version", name="uq_cost_rate_version"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(80))
    meter: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(10))
    price_per_unit: Mapped[str] = mapped_column(String(60))
    fx_toman_per_currency: Mapped[str] = mapped_column(String(60))
    quantum: Mapped[str] = mapped_column(String(60))
    minimum_quantity: Mapped[str] = mapped_column(String(60))
    evidence_reference: Mapped[str] = mapped_column(String(160))
    evidence_sha256: Mapped[str] = mapped_column(String(64))
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    effective_at: Mapped[object] = mapped_column(UTCDateTime)
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class MonetaryPolicy(Base):
    __tablename__ = "monetary_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "version", name="uq_monetary_policy_version"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    monthly_cap_micro_toman: Mapped[int] = mapped_column(BigInteger)
    call_cap_micro_toman: Mapped[int] = mapped_column(BigInteger)
    operation_cap_micro_toman: Mapped[int] = mapped_column(BigInteger)
    soft_percent: Mapped[int] = mapped_column(Integer, default=80)
    provider_caps: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class CostReservation(Base):
    __tablename__ = "cost_reservations"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "meter", "operation_key", name="uq_cost_operation"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    call_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    operation_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    provider: Mapped[str] = mapped_column(String(80))
    meter: Mapped[str] = mapped_column(String(80))
    max_quantity: Mapped[str] = mapped_column(String(60))
    rate_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reserved_micro_toman: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(30), default="RESERVED", index=True)
    started_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    settled_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    expires_at: Mapped[object] = mapped_column(UTCDateTime, index=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class UsageCharge(Base):
    __tablename__ = "usage_charges"
    __table_args__ = (UniqueConstraint("tenant_id", "source_key", name="uq_usage_source_key"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    reservation_id: Mapped[str | None] = mapped_column(ForeignKey("cost_reservations.id"), nullable=True)
    adjusts_charge_id: Mapped[str | None] = mapped_column(ForeignKey("usage_charges.id"), nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(80))
    meter: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[str] = mapped_column(String(60))
    unit: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(10))
    rate_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_micro_toman: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    source_key: Mapped[str] = mapped_column(String(64))
    source_reference: Mapped[str] = mapped_column(String(160))
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[object] = mapped_column(UTCDateTime)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class VendorStatement(Base):
    __tablename__ = "vendor_statements"
    __table_args__ = (UniqueConstraint("tenant_id", "provider", "reference", name="uq_vendor_statement"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider: Mapped[str] = mapped_column(String(80))
    reference: Mapped[str] = mapped_column(String(160))
    period: Mapped[str] = mapped_column(String(7))
    evidence_sha256: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    submitted_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class VendorStatementLine(Base):
    __tablename__ = "vendor_statement_lines"
    __table_args__ = (UniqueConstraint("statement_id", "reference", name="uq_vendor_statement_line"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    statement_id: Mapped[str] = mapped_column(ForeignKey("vendor_statements.id"))
    reference: Mapped[str] = mapped_column(String(160))
    charge_id: Mapped[str | None] = mapped_column(ForeignKey("usage_charges.id"), nullable=True)
    meter: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[str] = mapped_column(String(60))
    unit: Mapped[str] = mapped_column(String(30))
    currency: Mapped[str] = mapped_column(String(10))
    billed_amount: Mapped[str] = mapped_column(String(60))
    fx_toman_per_currency: Mapped[str] = mapped_column(String(60))
    billed_micro_toman: Mapped[int] = mapped_column(BigInteger)
    discrepancy_micro_toman: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    resolution_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    resolved_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class TransportEvent(Base):
    __tablename__ = "transport_events"
    __table_args__ = (UniqueConstraint("tenant_id", "source", "event_key", name="uq_transport_event"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    source: Mapped[str] = mapped_column(String(80))
    event_key: Mapped[str] = mapped_column(String(160))
    attempt_key: Mapped[str] = mapped_column(String(160), index=True)
    call_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    stage: Mapped[str] = mapped_column(String(30))
    request_hash: Mapped[str] = mapped_column(String(64))
    evidence_reference: Mapped[str] = mapped_column(String(160))
    occurred_at: Mapped[object] = mapped_column(UTCDateTime)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class DemandAttribution(Base):
    __tablename__ = "demand_attributions"
    __table_args__ = (UniqueConstraint("tenant_id", "appointment_id", name="uq_booking_attribution"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"))
    episode_key: Mapped[str] = mapped_column(String(64), index=True)
    channel: Mapped[str] = mapped_column(String(30))
    classification: Mapped[str] = mapped_column(String(40))
    related_appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), nullable=True)
    evidence_reference: Mapped[str] = mapped_column(String(160))
    reviewed_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class StaffWorkSession(Base):
    __tablename__ = "staff_work_sessions"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_staff_work_key"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("staff_tasks.id"), nullable=True)
    category: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    rate_micro_toman_per_hour: Mapped[int] = mapped_column(BigInteger)
    started_at: Mapped[object] = mapped_column(UTCDateTime)
    ended_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_micro_toman: Mapped[int | None] = mapped_column(BigInteger, nullable=True)


class StaffTimeObservation(Base):
    __tablename__ = "staff_time_observations"
    __table_args__ = (UniqueConstraint("tenant_id", "period", "evidence_reference", name="uq_staff_observation"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))
    released_minutes: Mapped[int] = mapped_column(Integer)
    avoidable_minutes: Mapped[int] = mapped_column(Integer)
    reassigned_minutes: Mapped[int] = mapped_column(Integer)
    rate_micro_toman_per_hour: Mapped[int] = mapped_column(BigInteger)
    evidence_reference: Mapped[str] = mapped_column(String(160))
    evidence_sha256: Mapped[str] = mapped_column(String(64))
    reviewed_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


def _immutable_evidence(mapper, connection, target):
    raise ValueError("Financial evidence is append-only; publish a new version or linked adjustment")


for _evidence_class in (CostRate, MonetaryPolicy, UsageCharge, VendorStatement, TransportEvent, DemandAttribution, StaffTimeObservation):
    event.listen(_evidence_class, "before_update", _immutable_evidence)
    event.listen(_evidence_class, "before_delete", _immutable_evidence)
