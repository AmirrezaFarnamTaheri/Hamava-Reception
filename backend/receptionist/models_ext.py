"""Versioned operational controls without rewriting booking/payment history."""

from sqlalchemy import ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, now_utc
from .models import uid


class PolicyRevision(Base):
    __tablename__ = "policy_revisions"
    __table_args__ = (UniqueConstraint("tenant_id", "version", name="uq_policy_revision"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    snapshot: Mapped[dict] = mapped_column(JSON)
    changed_fields: Mapped[list] = mapped_column(JSON, default=list)
    actor_id: Mapped[str] = mapped_column(String(120))
    reason_encrypted: Mapped[str] = mapped_column(Text)
    restored_from: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class TaskControl(Base):
    __tablename__ = "task_controls"
    task_id: Mapped[str] = mapped_column(ForeignKey("staff_tasks.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    callback_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class OperationReceipt(Base):
    __tablename__ = "operation_receipts"
    __table_args__ = (UniqueConstraint("tenant_id", "operation", "key", name="uq_operation_receipt"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    operation: Mapped[str] = mapped_column(String(60))
    key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class CorrectionRecord(Base):
    __tablename__ = "correction_records"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(120))
    subject_hash: Mapped[str] = mapped_column(String(64), index=True)
    previous_subject_hash: Mapped[str] = mapped_column(String(64), index=True)
    reason_encrypted: Mapped[str] = mapped_column(Text)
    changes_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class Disruption(Base):
    __tablename__ = "disruptions"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider_id: Mapped[str | None] = mapped_column(ForeignKey("practitioners.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(40))
    start_at: Mapped[object] = mapped_column(UTCDateTime)
    end_at: Mapped[object] = mapped_column(UTCDateTime)
    delay_minutes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    version: Mapped[int] = mapped_column(Integer, default=1)
    actor_id: Mapped[str] = mapped_column(String(120))
    reason_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    resolved_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class AppointmentImpact(Base):
    __tablename__ = "appointment_impacts"
    __table_args__ = (UniqueConstraint("disruption_id", "appointment_id", name="uq_appointment_impact"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    disruption_id: Mapped[str] = mapped_column(ForeignKey("disruptions.id"), index=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"), index=True)
    state: Mapped[str] = mapped_column(String(40), default="REVIEW_REQUIRED")
    original_start_at: Mapped[object] = mapped_column(UTCDateTime)
    original_end_at: Mapped[object] = mapped_column(UTCDateTime)
    original_status: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    resolved_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class RefundReview(Base):
    __tablename__ = "refund_reviews"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    refund_id: Mapped[str] = mapped_column(ForeignKey("refund_ledger.id"), index=True)
    actor_id: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(40))
    reason_encrypted: Mapped[str] = mapped_column(Text)
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class PaymentDispute(Base):
    __tablename__ = "payment_disputes"
    __table_args__ = (UniqueConstraint("tenant_id", "provider_case_reference", name="uq_payment_dispute_reference"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payment_intents.id"), index=True)
    provider_case_reference: Mapped[str] = mapped_column(String(120))
    amount_toman: Mapped[int] = mapped_column(Integer)
    reason_encrypted: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="OPEN")
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    closed_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class PaymentAdjustment(Base):
    __tablename__ = "payment_adjustments"
    __table_args__ = (UniqueConstraint("tenant_id", "dispute_id", name="uq_dispute_adjustment"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payment_intents.id"))
    dispute_id: Mapped[str] = mapped_column(ForeignKey("payment_disputes.id"))
    kind: Mapped[str] = mapped_column(String(40), default="STAFF_RECORDED_CHARGEBACK")
    amount_toman: Mapped[int] = mapped_column(Integer)
    actor_id: Mapped[str] = mapped_column(String(120))
    reason_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
