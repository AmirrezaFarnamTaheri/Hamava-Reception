"""Versioned core policy and external-authority state, never a shadow calendar."""
from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base, UTCDateTime, now_utc
from .models import uid


class StaffTokenRevocation(Base):
    __tablename__ = "staff_token_revocations"
    session_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    expires_at: Mapped[object] = mapped_column(UTCDateTime, index=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class CorePolicy(Base):
    __tablename__ = "core_policies"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    settings: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc, onupdate=now_utc)


class CatalogFact(Base):
    __tablename__ = "catalog_facts"
    __table_args__ = (UniqueConstraint("tenant_id", "subject_type", "subject_id", "field", "version", name="uq_catalog_fact_version"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    subject_type: Mapped[str] = mapped_column(String(30))
    subject_id: Mapped[str] = mapped_column(String(60))
    field: Mapped[str] = mapped_column(String(60))
    version: Mapped[int] = mapped_column(Integer)
    value: Mapped[dict] = mapped_column(JSON)
    value_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(500))
    approved_by: Mapped[str] = mapped_column(String(120))
    effective_at: Mapped[object] = mapped_column(UTCDateTime)
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class ServiceRule(Base):
    __tablename__ = "service_rules"
    service_id: Mapped[str] = mapped_column(ForeignKey("services.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    preparation: Mapped[str] = mapped_column(Text, default="")
    insurance_notes: Mapped[str] = mapped_column(Text, default="")
    visit_policy: Mapped[str] = mapped_column(String(30), default="any")
    prerequisite_service_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    follow_up_days: Mapped[int] = mapped_column(Integer, default=30)
    package_units: Mapped[int] = mapped_column(Integer, default=0)
    max_series: Mapped[int] = mapped_column(Integer, default=12)


class PackageEntitlement(Base):
    __tablename__ = "package_entitlements"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_package_issue_key"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    phone_hash: Mapped[str] = mapped_column(String(100), index=True)
    service_ids: Mapped[list] = mapped_column(JSON)
    total_units: Mapped[int] = mapped_column(Integer)
    used_units: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    reason_encrypted: Mapped[str] = mapped_column(Text)
    reference: Mapped[str] = mapped_column(String(100))
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class PackageUse(Base):
    __tablename__ = "package_uses"
    appointment_id: Mapped[str] = mapped_column(ForeignKey("appointments.id"), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    entitlement_id: Mapped[str] = mapped_column(ForeignKey("package_entitlements.id"))
    units: Mapped[int] = mapped_column(Integer)
    released: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class BookingSeries(Base):
    __tablename__ = "booking_series"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_booking_series_key"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    request_encrypted: Mapped[str] = mapped_column(Text)
    phone_hash: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[str] = mapped_column(String(30), default="RUNNING")
    outcomes: Mapped[list] = mapped_column(JSON, default=list)
    lease_until: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_by: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class RoutingRevision(Base):
    __tablename__ = "routing_revisions"
    __table_args__ = (UniqueConstraint("tenant_id", "version", name="uq_routing_version"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    routes: Mapped[list] = mapped_column(JSON)
    language_routes: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str] = mapped_column(String(120))
    reason_encrypted: Mapped[str] = mapped_column(Text)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class IntegrationCapability(Base):
    __tablename__ = "integration_capabilities"
    __table_args__ = (UniqueConstraint("tenant_id", "provider_key", name="uq_integration_capability"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider_key: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(30))
    operations: Mapped[list] = mapped_column(JSON)
    endpoint_version: Mapped[str] = mapped_column(String(120))
    model_version: Mapped[str] = mapped_column(String(120), default="not_applicable")
    region: Mapped[str] = mapped_column(String(80))
    data_terms_reference: Mapped[str] = mapped_column(String(500))
    verification_state: Mapped[str] = mapped_column(String(40), default="declared_unverified")
    evidence_reference: Mapped[str] = mapped_column(String(500))
    approved_by: Mapped[str] = mapped_column(String(120))
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc, onupdate=now_utc)


class ProviderObservation(Base):
    __tablename__ = "provider_observations"
    __table_args__ = (UniqueConstraint("tenant_id", "provider_key", name="uq_provider_observation"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider_key: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40))
    code: Mapped[str] = mapped_column(String(80))
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    checked_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class CalendarAuthority(Base):
    __tablename__ = "calendar_authorities"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    kind: Mapped[str] = mapped_column(String(30), default="internal")
    provider_key: Mapped[str] = mapped_column(String(80), default="internal_calendar")
    version: Mapped[int] = mapped_column(Integer, default=1)
    capabilities: Mapped[dict] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str] = mapped_column(String(120))
    approved_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    connector_revision: Mapped[str] = mapped_column(String(120), default="internal-v1")


class ExternalCalendarOperation(Base):
    __tablename__ = "external_calendar_operations"
    __table_args__ = (UniqueConstraint("tenant_id", "operation", "idempotency_key", name="uq_external_operation_key"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    authority_version: Mapped[int] = mapped_column(Integer)
    operation: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    request_hash: Mapped[str] = mapped_column(String(64))
    request_encrypted: Mapped[str] = mapped_column(Text)
    result_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="PENDING")
    remote_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    remote_revision: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(String(100), nullable=True)
    call_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    actor_id: Mapped[str] = mapped_column(String(120))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_until: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc, onupdate=now_utc)


class CalendarSyncState(Base):
    __tablename__ = "calendar_sync_states"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    cursor: Mapped[str | None] = mapped_column(String(200), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    last_event_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    last_poll_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="NOT_SYNCED")
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class CalendarChangeReceipt(Base):
    __tablename__ = "calendar_change_receipts"
    __table_args__ = (UniqueConstraint("tenant_id", "event_id", name="uq_calendar_event"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    event_id: Mapped[str] = mapped_column(String(120))
    revision: Mapped[int] = mapped_column(Integer)
    remote_id: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(30))
    payload_hash: Mapped[str] = mapped_column(String(64))
    observed_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class SmsConversation(Base):
    __tablename__ = "sms_conversations"
    __table_args__ = (UniqueConstraint("tenant_id", "inbound_reference", name="uq_sms_inbound_reference"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id"), index=True)
    phone_hash: Mapped[str] = mapped_column(String(100), index=True)
    inbound_reference: Mapped[str] = mapped_column(String(120))
    request_hash: Mapped[str] = mapped_column(String(64))
    turn_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class RoutingBinding(Base):
    """One globally unique inbound DID; JSON revisions alone cannot enforce this."""
    __tablename__ = "routing_bindings"
    did: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("routing_revisions.id"))
    provider: Mapped[str] = mapped_column(String(30))
    queue_id: Mapped[str] = mapped_column(String(80))
    transfer_target: Mapped[str] = mapped_column(String(120))
