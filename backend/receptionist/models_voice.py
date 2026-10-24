"""Durable conversation state, without raw audio or plaintext transcripts."""
from sqlalchemy import Boolean, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, UTCDateTime, now_utc
from .models import uid


class CallSession(Base):
    __tablename__ = "call_sessions"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    channel: Mapped[str] = mapped_column(String(30), default="browser_text")
    state: Mapped[str] = mapped_column(String(40), default="INTENT")
    intent: Mapped[str] = mapped_column(String(40), default="unknown")
    policy_version: Mapped[int] = mapped_column(Integer)
    policy_snapshot: Mapped[dict] = mapped_column(JSON)
    context_encrypted: Mapped[str] = mapped_column(Text)
    processing_consent: Mapped[bool] = mapped_column(Boolean, default=True)
    recording_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    training_consent: Mapped[bool] = mapped_column(Boolean, default=False)
    handoff_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    media_room: Mapped[str | None] = mapped_column(String(150), nullable=True)
    media_participant: Mapped[str | None] = mapped_column(String(150), nullable=True)
    media_worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_worker_token: Mapped[str | None] = mapped_column(String(80), nullable=True)
    media_worker_lease: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    phone_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_until: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    ended_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class VoiceTurn(Base):
    __tablename__ = "voice_turns"
    __table_args__ = (UniqueConstraint("call_id", "request_id", name="uq_voice_turn_request"),)
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    result_encrypted: Mapped[str] = mapped_column(Text)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class VerificationChallenge(Base):
    __tablename__ = "verification_challenges"
    id: Mapped[str] = mapped_column(String(60), primary_key=True, default=uid)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id"), index=True)
    phone_hash: Mapped[str] = mapped_column(String(64))
    phone_encrypted: Mapped[str] = mapped_column(Text)
    code_hash: Mapped[str] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    verified_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)


class RateWindow(Base):
    __tablename__ = "rate_windows"
    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[object] = mapped_column(UTCDateTime, index=True)


class MediaRegistration(Base):
    __tablename__ = "media_registrations"
    call_uuid: Mapped[str] = mapped_column(String(60), primary_key=True)
    call_id: Mapped[str] = mapped_column(ForeignKey("call_sessions.id"), unique=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    token_encrypted: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[object] = mapped_column(UTCDateTime)
    claimed_at: Mapped[object | None] = mapped_column(UTCDateTime, nullable=True)


class MediaHeartbeat(Base):
    __tablename__ = "media_heartbeats"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    updated_at: Mapped[object] = mapped_column(UTCDateTime, default=now_utc)
