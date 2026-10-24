"""Explicitly scoped partner access and published clinic identity."""
from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, UTCDateTime, now_utc
from .models import uid


class ClinicProfile(Base):
    __tablename__ = "clinic_profiles"
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), primary_key=True)
    legal_operator: Mapped[str] = mapped_column(String(200), default="")
    location_label: Mapped[str] = mapped_column(String(200), default="")
    ownership_reference: Mapped[str] = mapped_column(String(200), default="")
    brand_name: Mapped[str] = mapped_column(String(160), default="")
    brand_color: Mapped[str] = mapped_column(String(7), default="#16796f")
    voice_identity: Mapped[str] = mapped_column(String(100), default="configured_processor")
    pronunciation: Mapped[list] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    approved_by: Mapped[str | None] = mapped_column(String(60), nullable=True)
    published_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class PartnerCredential(Base):
    __tablename__ = "partner_credentials"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    label: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(250))
    key_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    expires_at: Mapped[object] = mapped_column(UTCDateTime)


class PartnerVoiceThread(Base):
    __tablename__ = "partner_voice_threads"
    __table_args__ = (UniqueConstraint("credential_id", "thread_hash", name="uq_partner_voice_thread"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    credential_id: Mapped[str] = mapped_column(ForeignKey("partner_credentials.id"))
    thread_hash: Mapped[str] = mapped_column(String(64))
    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id"))
    token_encrypted: Mapped[str] = mapped_column(Text)
    request_hash: Mapped[str] = mapped_column(String(64))


class ChannelPermission(Base):
    __tablename__ = "channel_permissions"
    __table_args__ = (UniqueConstraint("tenant_id", "subject_hash", "channel", "purpose", name="uq_channel_permission"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    subject_hash: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(30))
    purpose: Mapped[str] = mapped_column(String(30))
    granted: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_reference: Mapped[str] = mapped_column(String(200))
    recorded_by: Mapped[str] = mapped_column(String(60))
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc, onupdate=now_utc)


class DigestDestination(Base):
    __tablename__ = "digest_destinations"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    channel: Mapped[str] = mapped_column(String(30))
    recipient_encrypted: Mapped[str] = mapped_column(Text)
    consent_reference: Mapped[str] = mapped_column(String(200))
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    automatic_daily: Mapped[bool] = mapped_column(Boolean, default=False)
    local_hour: Mapped[int] = mapped_column(Integer, default=8)
    created_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class DigestDelivery(Base):
    __tablename__ = "digest_deliveries"
    __table_args__ = (UniqueConstraint("destination_id", "period", name="uq_digest_period"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    destination_id: Mapped[str] = mapped_column(ForeignKey("digest_destinations.id"))
    period: Mapped[str] = mapped_column(String(10))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="QUEUED")
    provider_reference: Mapped[str | None] = mapped_column(String(160), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc, onupdate=now_utc)


class BuildingContract(Base):
    __tablename__ = "building_contracts"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_ids: Mapped[list] = mapped_column(JSON)
    building_id: Mapped[str] = mapped_column(String(100))
    contract_reference: Mapped[str] = mapped_column(String(200))
    included_minutes: Mapped[int] = mapped_column(Integer)
    overage_toman_per_minute: Mapped[int] = mapped_column(Integer)
    effective_period: Mapped[str] = mapped_column(String(7))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
