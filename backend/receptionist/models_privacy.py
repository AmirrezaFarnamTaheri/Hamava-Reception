"""Versioned purposes, processor permissions and expiring encrypted artifacts."""
from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, UTCDateTime, now_utc
from .models import uid


class PurposePolicy(Base):
    __tablename__ = "purpose_policies"
    __table_args__ = (UniqueConstraint("tenant_id", "purpose", "version", name="uq_purpose_policy_version"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    purpose: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    notice: Mapped[str] = mapped_column(Text)
    retention_days: Mapped[int] = mapped_column(Integer)
    backup_expiry_days: Mapped[int] = mapped_column(Integer)
    consent_valid_days: Mapped[int] = mapped_column(Integer)
    evidence_reference: Mapped[str] = mapped_column(String(160))
    approved_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class ProcessorApproval(Base):
    __tablename__ = "processor_approvals"
    __table_args__ = (UniqueConstraint("tenant_id", "provider_key", "version", name="uq_processor_approval_version"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    provider_key: Mapped[str] = mapped_column(String(80))
    version: Mapped[int] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    purposes: Mapped[list] = mapped_column(JSON)
    regions: Mapped[list] = mapped_column(JSON)
    origin_region: Mapped[str] = mapped_column(String(40), default="IR")
    retention_days: Mapped[int] = mapped_column(Integer)
    fallback_eligible: Mapped[bool] = mapped_column(Boolean, default=False)
    contract_reference: Mapped[str] = mapped_column(String(160))
    contract_sha256: Mapped[str] = mapped_column(String(64))
    reviewed_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class GovernedArtifact(Base):
    __tablename__ = "governed_artifacts"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uq_governed_artifact_key"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    subject_hash: Mapped[str] = mapped_column(String(100), index=True)
    purpose: Mapped[str] = mapped_column(String(40))
    policy_version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    idempotency_key: Mapped[str] = mapped_column(String(160))
    content_sha256: Mapped[str] = mapped_column(String(64))
    payload_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_safe: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    expires_at: Mapped[object] = mapped_column(UTCDateTime, index=True)
    backup_expiry_days: Mapped[int] = mapped_column(Integer)
    hold_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    hold_until: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class ErasureEvidence(Base):
    __tablename__ = "erasure_evidence"
    __table_args__ = (UniqueConstraint("tenant_id", "object_type", "object_id", name="uq_erasure_object"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    object_type: Mapped[str] = mapped_column(String(50))
    object_id: Mapped[str] = mapped_column(String(120))
    subject_hash: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(40))
    previous_content_sha256: Mapped[str] = mapped_column(String(64))
    backup_delete_by: Mapped[object] = mapped_column(UTCDateTime)
    backup_status: Mapped[str] = mapped_column(String(30), default="PENDING_EXPIRY")
    backup_evidence_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class RedactionPolicy(Base):
    __tablename__ = "redaction_policies"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    terms_encrypted: Mapped[str] = mapped_column(Text)
    reviewed_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class ContactPreference(Base):
    __tablename__ = "contact_preferences"
    __table_args__ = (UniqueConstraint("tenant_id", "subject_hash", name="uq_contact_preference"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    subject_hash: Mapped[str] = mapped_column(String(64), index=True)
    shared_phone: Mapped[bool] = mapped_column(Boolean, default=True)
    name_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    voicemail_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    clinic_name_allowed: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_reference: Mapped[str] = mapped_column(String(160))
    recorded_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
