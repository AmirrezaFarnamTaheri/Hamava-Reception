"""Durable outbound, waitlist, payment, privacy, and accounting records."""

from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, UTCDateTime, now_utc
from .models import uid


class WaitlistEntry(Base):
    __tablename__ = "waitlist_entries"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("practitioners.id"))
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"))
    name_encrypted: Mapped[str] = mapped_column(Text)
    phone_encrypted: Mapped[str] = mapped_column(Text)
    phone_hash: Mapped[str] = mapped_column(String(64), index=True)
    active_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    date_from: Mapped[str] = mapped_column(String(10))
    date_to: Mapped[str] = mapped_column(String(10))
    time_from: Mapped[str] = mapped_column(String(5), default="09:00")
    time_to: Mapped[str] = mapped_column(String(5), default="20:00")
    travel_minutes: Mapped[int] = mapped_column(Integer, default=60)
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="WAITING")
    offer_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_offered_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class WaitlistOffer(Base):
    __tablename__ = "waitlist_offers"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    entry_id: Mapped[str] = mapped_column(ForeignKey("waitlist_entries.id"), index=True)
    hold_id: Mapped[str] = mapped_column(ForeignKey("slot_holds.id"))
    slot_id: Mapped[str] = mapped_column(Text)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    token_encrypted: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="OFFERED")
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    appointment_id: Mapped[str | None] = mapped_column(ForeignKey("appointments.id"), nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class PaymentIntent(Base):
    __tablename__ = "payment_intents"
    __table_args__ = (UniqueConstraint("tenant_id", "appointment_id", name="uq_payment_appointment"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"))
    amount_toman: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(10), default="TOMAN")
    gateway_currency: Mapped[str] = mapped_column(String(10), default="IRR")
    merchant_alias: Mapped[str | None] = mapped_column(String(100), nullable=True)
    merchant_identity_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    merchant_sandbox: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    terms_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    terms_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    refund_reserved_toman: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(40), default="CREATING")
    authority: Mapped[str | None] = mapped_column(String(100), unique=True, nullable=True)
    payment_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    settled_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class TenantPaymentPolicy(Base):
    __tablename__ = "tenant_payment_policies"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    currency: Mapped[str] = mapped_column(String(10), default="TOMAN")
    hold_minutes: Mapped[int] = mapped_column(Integer, default=60)
    deposit_terms: Mapped[str] = mapped_column(Text, default="")
    cancellation_terms: Mapped[str] = mapped_column(Text, default="")
    refund_terms: Mapped[str] = mapped_column(Text, default="")
    merchant_alias: Mapped[str | None] = mapped_column(String(100), nullable=True)
    merchant_identity_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    merchant_sandbox: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    published_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    published_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class RefundLedger(Base):
    __tablename__ = "refund_ledger"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_refund_key"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    payment_id: Mapped[str] = mapped_column(ForeignKey("payment_intents.id"))
    amount_toman: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(30), default="REQUESTED")
    idempotency_key: Mapped[str] = mapped_column(String(160))
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    completed_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class DeliveryReceipt(Base):
    __tablename__ = "delivery_receipts"
    __table_args__ = (UniqueConstraint("event_id", name="uq_receipt_event"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(150))
    message_id: Mapped[str] = mapped_column(ForeignKey("message_outbox.id"))
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(30))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class PrivacyTombstone(Base):
    __tablename__ = "privacy_tombstones"
    __table_args__ = (UniqueConstraint("tenant_id", "subject_hash", name="uq_privacy_subject"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    subject_hash: Mapped[str] = mapped_column(String(64))
    retained_business_records: Mapped[bool] = mapped_column(Boolean, default=False)
    reason: Mapped[str] = mapped_column(String(100), default="subject_request")
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class OutreachSuppression(Base):
    """Purpose-specific withdrawal, distinct from an erasure request."""

    __tablename__ = "outreach_suppressions"
    __table_args__ = (UniqueConstraint("tenant_id", "subject_hash", "purpose", name="uq_outreach_suppression"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    subject_hash: Mapped[str] = mapped_column(String(64), index=True)
    purpose: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class BillingAdjustment(Base):
    __tablename__ = "billing_adjustments"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_billing_adjustment_key"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))
    amount_toman: Mapped[int] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(String(200))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("tenant_id", "period", name="uq_invoice_period"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    period: Mapped[str] = mapped_column(String(7))
    status: Mapped[str] = mapped_column(String(30), default="DRAFT")
    snapshot: Mapped[dict] = mapped_column(JSON)
    amount_toman: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
