"""Permissioned extensions. No partnership or platform access is implied.

External applications receive a clinic-scoped, expiring capability with named
scopes. Voice notes enter the same consent and booking state machine. Digests
contain aggregate values and require a separately approved delivery gateway.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import hmac
import json
import os
import re
import secrets
import unicodedata
from typing import Literal

from fastapi import APIRouter, Depends, Response, HTTPException
from pydantic import Field, field_validator, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .config import settings
from .core import call_minutes, iso
from .db import get_db, now_utc
from .models import Appointment, AuditEvent, Membership, StaffTask, Tenant, UsageEvent, User
from .models_partner import (BuildingContract, ChannelPermission, ClinicProfile, DigestDelivery,
                             DigestDestination, PartnerCredential, PartnerVoiceThread)
from .models_voice import CallSession
from .providers import ProviderError, approved_url, enabled, provider_request
from .schemas import StrictModel
from .security import (Actor, bearer, decrypt, encrypt, fail, hash_password, hash_phone,
                       require_roles, require_permissions)

router = APIRouter(prefix="/api/v1", tags=["controlled extensions"])
admin = require_roles("owner", "admin")
owner = require_roles("owner")
SCOPES = {"summary:read", "appointments:read", "voice_notes:write"}


def _hash(value: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def audit(db, actor, action, entity_type, entity_id, **details):
    db.add(AuditEvent(tenant_id=actor.tenant_id, actor_id=actor.user_id,
        action=action, entity_type=entity_type, entity_id=entity_id, details=details))


class Pronunciation(StrictModel):
    written: str = Field(min_length=1, max_length=100)
    asr_aliases: list[str] = Field(default_factory=list, max_length=10)
    spoken: str = Field(min_length=1, max_length=150)

    @field_validator("written", "spoken", "asr_aliases", mode="before")
    @classmethod
    def no_controls_before_normalization(cls, value):
        items = value if isinstance(value, list) else [value]
        if any(isinstance(item, str) and any(unicodedata.category(c).startswith("C") for c in item) for item in items):
            raise ValueError("Pronunciation and ASR hints cannot include control characters")
        return value

    @field_validator("asr_aliases")
    @classmethod
    def bounded_aliases(cls, value):
        if any(not 1 <= len(x) <= 100 or any(unicodedata.category(c).startswith("C") for c in x) for x in value):
            raise ValueError("Each alias must be 1–100 characters without control characters")
        return value

    @model_validator(mode="after")
    def preserve_spoken_identity(self):
        if not safe_pronunciation(self.written, self.spoken):
            raise ValueError("Spoken pronunciation may add vowel marks only; words, numbers and meaning must stay identical")
        return self


def safe_pronunciation(written: str, spoken: str) -> bool:
    # Conversation normalization intentionally removes bidi controls and
    # collapses whitespace; using it here would hide unsafe substitutions.
    if any(c.isdigit() or unicodedata.category(c).startswith("C") for c in written + spoken):
        return False

    def letters(value):
        value = unicodedata.normalize("NFC", value).translate(str.maketrans({"ي": "ی", "ك": "ک", "ۀ": "ه"}))
        return re.sub(r"[\u064b-\u065f\u0670]", "", value)

    return letters(written) == letters(spoken)


class ProfileInput(StrictModel):
    version: int = Field(ge=0)
    legal_operator: str = Field(default="", max_length=200)
    location_label: str = Field(default="", max_length=200)
    ownership_reference: str = Field(default="", max_length=200)
    brand_name: str = Field(default="", max_length=160)
    brand_color: str = Field(default="#16796f", pattern=r"^#[0-9a-fA-F]{6}$")
    pronunciation: list[Pronunciation] = Field(default_factory=list, max_length=100)
    publication_approved: bool


def profile_dict(row):
    if not row:
        return {"version": 0, "legal_operator": "", "location_label": "", "ownership_reference": "",
                "brand_name": "", "brand_color": "#16796f", "pronunciation": [], "published_at": None,
                "voice_identity": "configured_processor"}
    return {key: getattr(row, key) for key in ("version", "legal_operator", "location_label", "ownership_reference",
        "brand_name", "brand_color", "pronunciation", "voice_identity", "approved_by")} | {"published_at": iso(row.published_at)}


@router.get("/operations/profile")
def get_profile(actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    return profile_dict(db.get(ClinicProfile, actor.tenant_id))


@router.put("/operations/profile")
def publish_profile(data: ProfileInput, actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    if not data.publication_approved:
        fail(422, "APPROVAL_REQUIRED", "انتشار هویت و تلفظ‌های مرکز باید تأیید شود.")
    # Tenant lock serializes first creation, publication and policy revision.
    db.execute(update(Tenant).where(Tenant.id == actor.tenant_id).values(settings_version=Tenant.settings_version))
    row = db.get(ClinicProfile, actor.tenant_id)
    if data.version != (row.version if row else 0):
        fail(409, "STALE_VERSION", "اطلاعات مرکز تغییر کرده است؛ دوباره دریافت کنید.")
    if not row:
        row = ClinicProfile(tenant_id=actor.tenant_id, version=0)
        db.add(row)
    for key, value in data.model_dump(exclude={"version", "publication_approved"}).items():
        setattr(row, key, value)
    row.version += 1
    row.approved_by, row.published_at = actor.user_id, now_utc()
    tenant = db.get(Tenant, actor.tenant_id)
    tenant.settings_version += 1
    audit(db, actor, "profile.published", "clinic", actor.tenant_id, profile_version=row.version)
    db.commit()
    return profile_dict(row)


def published_identity(db: Session, tenant_id: str) -> dict:
    row = db.get(ClinicProfile, tenant_id)
    return {"brand_name": row.brand_name, "brand_color": row.brand_color, "voice_identity": row.voice_identity,
            "pronunciation": row.pronunciation, "profile_version": row.version} if row and row.published_at else {}


def pronounce(text: str, dictionary: list[dict]) -> str:
    """Whole-token vowel marks only; stored words and numeric truth cannot change."""
    for entry in sorted(dictionary, key=lambda x: len(x["written"]), reverse=True):
        if not safe_pronunciation(entry["written"], entry["spoken"]):
            continue
        text = re.sub(r"(?<!\w)" + re.escape(entry["written"]) + r"(?!\w)", lambda _: entry["spoken"], text)
    return text


class TeamInput(StrictModel):
    email: str = Field(min_length=5, max_length=254)
    name: str = Field(min_length=2, max_length=160)
    role: Literal["admin", "manager", "coordinator", "receptionist", "clinician", "billing", "technical", "partner"]
    initial_password: str | None = Field(default=None, min_length=14, max_length=256)


@router.get("/operations/team")
def team(actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    rows = db.execute(select(User, Membership).join(Membership).where(Membership.tenant_id == actor.tenant_id)).all()
    return [{"user_id": user.id, "membership_id": member.id, "name": user.name, "email": user.email,
             "role": member.role, "active": member.active and user.active} for user, member in rows]


@router.post("/operations/team", status_code=201)
def grant_team(data: TeamInput, actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    email = data.email.strip().lower()
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        fail(422, "INVALID_EMAIL", "ایمیل معتبر لازم است.")
    # Expensive hashing precedes the short write transaction. Tenant-scoped
    # grants serialize; the global email constraint handles cross-tenant races.
    password_hash = hash_password(data.initial_password) if data.initial_password else None
    try:
        db.execute(update(Tenant).where(Tenant.id == actor.tenant_id).values(settings_version=Tenant.settings_version))
        user = db.scalar(select(User).where(User.email == email).execution_options(populate_existing=True))
        if user and data.initial_password:
            fail(409, "EXISTING_USER", "حساب موجود است؛ رمز آن در این عملیات تغییر نمی‌کند.")
        if not user:
            if not password_hash:
                fail(422, "PASSWORD_REQUIRED", "برای حساب جدید یک رمز امن لازم است.")
            user = User(email=email, name=data.name, password_hash=password_hash)
            db.add(user)
            db.flush()
        if not user.active:
            fail(409, "INACTIVE_USER", "حساب غیرفعال نیاز به بررسی مدیر دارد.")
        membership = db.scalar(select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == actor.tenant_id)
                               .execution_options(populate_existing=True))
        if membership and membership.role == "owner":
            fail(409, "OWNER_PROTECTED", "تغییر مالک از این مسیر مجاز نیست.")
        if not membership:
            membership = Membership(user_id=user.id, tenant_id=actor.tenant_id)
            db.add(membership)
        membership.role, membership.active = data.role, True
        db.flush()
        audit(db, actor, "membership.granted", "membership", membership.id, role=data.role)
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "TEAM_UPDATE_CONFLICT", "حساب یا عضویت هم‌زمان تغییر کرد؛ اطلاعات تازه را دریافت و دوباره بررسی کنید.")
    return {"user_id": user.id, "membership_id": membership.id, "role": membership.role, "active": True}


@router.delete("/operations/team/{membership_id}")
def revoke_team(membership_id: str, actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    member = db.scalar(select(Membership).where(Membership.id == membership_id, Membership.tenant_id == actor.tenant_id))
    if not member or member.role == "owner":
        fail(404, "MEMBERSHIP_NOT_FOUND", "عضویت قابل تغییر پیدا نشد.")
    member.active = False
    audit(db, actor, "membership.revoked", "membership", member.id)
    db.commit()
    return {"active": False}


class CredentialInput(StrictModel):
    label: str = Field(min_length=2, max_length=100)
    purpose: str = Field(min_length=5, max_length=250)
    scopes: list[str] = Field(min_length=1, max_length=3)
    expires_days: int = Field(default=30, ge=1, le=90)


def credential_dict(row):
    return {"id": row.id, "label": row.label, "purpose": row.purpose, "scopes": row.scopes,
            "active": row.active, "expires_at": iso(row.expires_at)}


@router.post("/operations/partner-keys", status_code=201)
def issue_partner_key(data: CredentialInput, actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    if not set(data.scopes) <= SCOPES:
        fail(422, "INVALID_SCOPE", "مجوز درخواستی معتبر نیست.")
    token = "hmp_" + secrets.token_urlsafe(40)
    row = PartnerCredential(tenant_id=actor.tenant_id, label=data.label, purpose=data.purpose,
        scopes=sorted(set(data.scopes)), key_hash=_hash(token), created_by=actor.user_id,
        expires_at=now_utc()+timedelta(days=data.expires_days))
    db.add(row)
    db.flush()
    audit(db, actor, "partner.key_issued", "partner_key", row.id, scopes=row.scopes)
    db.commit()
    return credential_dict(row) | {"api_key": token, "shown_once": True, "api_version": "v1"}


@router.get("/operations/partner-keys")
def partner_keys(actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    return [credential_dict(row) for row in db.scalars(select(PartnerCredential).where(PartnerCredential.tenant_id == actor.tenant_id))]


@router.delete("/operations/partner-keys/{key_id}")
def revoke_partner_key(key_id: str, actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    db.execute(update(PartnerCredential).where(PartnerCredential.id == key_id, PartnerCredential.tenant_id == actor.tenant_id)
               .values(active=False))
    row = db.scalar(select(PartnerCredential).where(PartnerCredential.id == key_id, PartnerCredential.tenant_id == actor.tenant_id))
    if not row:
        fail(404, "KEY_NOT_FOUND", "کلید پیدا نشد.")
    row.active = False
    # Existing asynchronous threads must not retain write access after revocation.
    for thread in db.scalars(select(PartnerVoiceThread).where(PartnerVoiceThread.credential_id == row.id)):
        call = db.get(CallSession, thread.call_id)
        if call and not call.ended_at:
            from .voice import end_session
            end_session(db, call)
        thread.token_encrypted = encrypt("")
    audit(db, actor, "partner.key_revoked", "partner_key", row.id)
    db.commit()
    return {"active": False}


def authorized_voice_thread(db: Session, call: CallSession) -> None:
    thread = db.scalar(select(PartnerVoiceThread).where(PartnerVoiceThread.call_id == call.id,
                                                       PartnerVoiceThread.tenant_id == call.tenant_id))
    credential = db.get(PartnerCredential, thread.credential_id, populate_existing=True) if thread else None
    if not credential or not credential.active or credential.expires_at <= now_utc() or "voice_notes:write" not in credential.scopes:
        fail(401, "PARTNER_AUTHORITY_REVOKED", "مجوز این گفت‌وگوی صوتی پایان یافته است.")
    issuer = db.get(User, credential.created_by, populate_existing=True)
    authority = db.scalar(select(Membership.id).where(Membership.user_id == credential.created_by,
        Membership.tenant_id == call.tenant_id, Membership.active.is_(True), Membership.role == "owner"))
    if not issuer or not issuer.active or not authority:
        fail(401, "PARTNER_AUTHORITY_REVOKED", "مجوز این گفت‌وگوی صوتی پایان یافته است.")


def partner(scope):
    def dependency(credentials=Depends(bearer), db: Session = Depends(get_db)):
        token = credentials.credentials if credentials else ""
        row = db.scalar(select(PartnerCredential).where(PartnerCredential.key_hash == _hash(token), PartnerCredential.active.is_(True)))
        if not row or row.expires_at <= now_utc():
            fail(401, "INVALID_PARTNER_KEY", "کلید همکاری معتبر نیست.")
        tenant = db.get(Tenant, row.tenant_id)
        issuer = db.get(User, row.created_by)
        membership = db.scalar(select(Membership).where(Membership.user_id == row.created_by,
            Membership.tenant_id == row.tenant_id, Membership.active.is_(True), Membership.role == "owner"))
        if not tenant or not tenant.active or not issuer or not issuer.active or not membership:
            fail(403, "PARTNER_AUTHORITY_REVOKED", "مجوز همکاری دیگر فعال نیست.")
        if scope not in row.scopes:
            fail(403, "PARTNER_SCOPE_REQUIRED", "مجوز لازم فعال نیست.")
        from .voice import rate_limit
        rate_limit(db, "partner:" + row.id, 60, 60)
        return row
    return dependency


def summary(db, tenant_id: str) -> dict:
    statuses = dict(db.execute(select(Appointment.status, func.count()).where(Appointment.tenant_id == tenant_id).group_by(Appointment.status)).all())
    return {"schema_version": "1.0", "tenant_id": tenant_id, "appointment_counts": statuses,
            "open_tasks": db.scalar(select(func.count()).select_from(StaffTask).where(StaffTask.tenant_id == tenant_id, StaffTask.status != "RESOLVED")),
            "as_of": iso(now_utc()), "contains_patient_records": False}


@router.get("/partner/v1/summary")
def api_summary(response: Response, key: PartnerCredential = Depends(partner("summary:read")), db: Session = Depends(get_db)):
    response.headers["X-Hamava-API-Version"] = "1"
    db.add(AuditEvent(tenant_id=key.tenant_id, actor_id="partner:"+key.id, action="partner.summary_exported",
        entity_type="partner_key", entity_id=key.id, details={"version": 1}))
    db.commit()
    return summary(db, key.tenant_id)


@router.get("/operations/partner-summary")
def partner_dashboard(actor: Actor = Depends(require_roles("owner", "admin", "partner")), db: Session = Depends(get_db)):
    return summary(db, actor.tenant_id)


@router.get("/partner/v1/appointments")
def partner_appointments(from_date: date, to_date: date, response: Response,
                         key: PartnerCredential = Depends(partner("appointments:read")), db: Session = Depends(get_db)):
    from datetime import datetime, time, UTC
    from zoneinfo import ZoneInfo
    if not 0 <= (to_date-from_date).days <= 31:
        fail(422, "EXPORT_RANGE", "بازه خروجی باید حداکثر ۳۱ روز باشد.")
    zone = ZoneInfo(db.get(Tenant, key.tenant_id).timezone)
    start = datetime.combine(from_date, time.min, zone).astimezone(UTC)
    end = datetime.combine(to_date+timedelta(days=1), time.min, zone).astimezone(UTC)
    rows = db.scalars(select(Appointment).where(Appointment.tenant_id == key.tenant_id,
        Appointment.start_at >= start, Appointment.start_at < end).order_by(Appointment.start_at).limit(5001)).all()
    if len(rows) > 5000:
        fail(422, "EXPORT_TOO_LARGE", "بازه کوچک‌تری انتخاب کنید.")
    # No names, phones, free text or clinical details in this partner contract.
    values = [{"id": row.id, "reference": row.reference, "start_at": iso(row.start_at),
               "end_at": iso(row.end_at), "provider_id": row.provider_id, "service_id": row.service_id,
               "status": row.status, "attendance": row.attendance, "version": row.version} for row in rows]
    db.add(AuditEvent(tenant_id=key.tenant_id, actor_id="partner:"+key.id, action="partner.appointments_exported",
        entity_type="partner_key", entity_id=key.id, details={"rows": len(values), "version": 1}))
    db.commit()
    response.headers["X-Hamava-API-Version"] = "1"
    return {"schema_version": "1.0", "items": values, "deprecation": None}


class VoiceThreadInput(StrictModel):
    external_thread_id: str = Field(min_length=8, max_length=160)
    processing_consent: bool
    recording_consent: Literal[False] = False
    training_consent: Literal[False] = False


@router.post("/partner/v1/voice-sessions", status_code=201)
def voice_note_session(data: VoiceThreadInput, key: PartnerCredential = Depends(partner("voice_notes:write")), db: Session = Depends(get_db)):
    if not data.processing_consent:
        fail(422, "CONSENT_REQUIRED", "پردازش پیام صوتی نیاز به رضایت دارد.")
    # Serialize on the credential, including on SQLite, before idempotent creation.
    db.execute(update(PartnerCredential).where(PartnerCredential.id == key.id, PartnerCredential.active.is_(True))
               .values(active=PartnerCredential.active))
    key = db.scalar(select(PartnerCredential).where(PartnerCredential.id == key.id).execution_options(populate_existing=True))
    if not key.active or key.expires_at <= now_utc():
        fail(401, "INVALID_PARTNER_KEY", "کلید همکاری معتبر نیست.")
    thread_hash = _hash(data.external_thread_id)
    request_hash = _hash(json.dumps(data.model_dump(), sort_keys=True))
    previous = db.scalar(select(PartnerVoiceThread).where(PartnerVoiceThread.credential_id == key.id, PartnerVoiceThread.thread_hash == thread_hash))
    if previous:
        call = db.get(CallSession, previous.call_id)
        if previous.request_hash != request_hash:
            fail(409, "IDEMPOTENCY_MISMATCH", "شناسه پیام با درخواست دیگری استفاده شده است.")
        if call.ended_at or call.expires_at <= now_utc():
            fail(410, "THREAD_ENDED", "این گفت‌وگو پایان یافته است؛ برای پیام جدید شناسه تازه لازم است.")
        return {"session_id": call.id, "token": decrypt(previous.token_encrypted), "channel": "voice_note", "replayed": True}
    from .voice import new_session
    tenant = db.get(Tenant, key.tenant_id)
    call, token = new_session(db, tenant, "voice_note", commit=False)
    db.add(PartnerVoiceThread(tenant_id=key.tenant_id, credential_id=key.id, thread_hash=thread_hash,
        call_id=call.id, token_encrypted=encrypt(token), request_hash=request_hash))
    db.commit()
    return {"session_id": call.id, "token": token, "channel": "voice_note", "replayed": False,
            "audio_endpoint": f"/api/v1/public/sessions/{call.id}/audio", "recording": False, "training": False}


class ChannelInput(StrictModel):
    phone: str = Field(max_length=30)
    channel: Literal["sms", "voice", "telegram", "bale", "eitaa", "whatsapp", "email"]
    purpose: Literal["reminder", "waitlist", "followup"]
    granted: bool
    evidence_reference: str = Field(min_length=3, max_length=200)


@router.post("/operations/channel-permissions")
def channel_permission(data: ChannelInput, actor: Actor = Depends(require_permissions("appointment:write")), db: Session = Depends(get_db)):
    subject = hash_phone(data.phone)
    db.execute(update(Tenant).where(Tenant.id == actor.tenant_id).values(settings_version=Tenant.settings_version))
    row = db.scalar(select(ChannelPermission).where(ChannelPermission.tenant_id == actor.tenant_id,
        ChannelPermission.subject_hash == subject, ChannelPermission.channel == data.channel, ChannelPermission.purpose == data.purpose))
    if not row:
        row = ChannelPermission(tenant_id=actor.tenant_id, subject_hash=subject, channel=data.channel, purpose=data.purpose)
        db.add(row)
    row.granted, row.evidence_reference, row.recorded_by = data.granted, data.evidence_reference, actor.user_id
    db.flush()
    audit(db, actor, "channel.permission_recorded", "channel_permission", row.id,
          channel=data.channel, purpose=data.purpose, granted=data.granted)
    db.commit()
    return {"id": row.id, "channel": row.channel, "purpose": row.purpose, "granted": row.granted}


def channel_allowed(db, tenant_id, phone, channel, purpose) -> bool:
    from .operations import suppressed
    if suppressed(db, tenant_id, phone, purpose):
        return False
    row = db.scalar(select(ChannelPermission).where(ChannelPermission.tenant_id == tenant_id,
        ChannelPermission.subject_hash == hash_phone(phone), ChannelPermission.channel == channel, ChannelPermission.purpose == purpose))
    return bool(row and row.granted)


class DestinationInput(StrictModel):
    channel: Literal["telegram", "bale", "eitaa", "email"]
    recipient: str = Field(min_length=3, max_length=250)
    consent_reference: str = Field(min_length=5, max_length=200)
    enabled: bool = False
    automatic_daily: bool = False
    local_hour: int = Field(default=8, ge=0, le=23)


@router.post("/operations/digest-destinations", status_code=201)
def destination(data: DestinationInput, actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    row = DigestDestination(tenant_id=actor.tenant_id, channel=data.channel, recipient_encrypted=encrypt(data.recipient),
        consent_reference=data.consent_reference, enabled=data.enabled, created_by=actor.user_id,
        automatic_daily=data.automatic_daily, local_hour=data.local_hour)
    db.add(row)
    db.flush()
    audit(db, actor, "digest.destination_created", "digest_destination", row.id, channel=data.channel, enabled=data.enabled)
    db.commit()
    return {"id": row.id, "channel": row.channel, "enabled": row.enabled,
            "automatic_daily": row.automatic_daily, "local_hour": row.local_hour,
            "delivery_configured": enabled("DIGEST_PROCESSOR_APPROVED")}


@router.delete("/operations/digest-destinations/{destination_id}")
def disable_destination(destination_id: str, actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    row = db.scalar(select(DigestDestination).where(DigestDestination.id == destination_id, DigestDestination.tenant_id == actor.tenant_id))
    if not row:
        fail(404, "DESTINATION_NOT_FOUND", "مقصد پیدا نشد.")
    row.enabled = False
    db.execute(update(DigestDelivery).where(DigestDelivery.destination_id == row.id, DigestDelivery.status == "QUEUED").values(status="SUPPRESSED"))
    audit(db, actor, "digest.destination_disabled", "digest_destination", row.id)
    db.commit()
    return {"enabled": False}


@router.get("/operations/digest-destinations")
def digest_destinations(actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    return [{"id": row.id, "channel": row.channel, "enabled": row.enabled,
             "automatic_daily": row.automatic_daily, "local_hour": row.local_hour,
             "created_at": iso(row.created_at), "consent_reference": row.consent_reference}
            for row in db.scalars(select(DigestDestination).where(DigestDestination.tenant_id == actor.tenant_id))]


def daily_aggregate(db, tenant_id: str, day: date) -> dict:
    from datetime import datetime, time, UTC
    from zoneinfo import ZoneInfo
    from .models_ops import WaitlistOffer
    zone = ZoneInfo(db.get(Tenant, tenant_id).timezone)
    start = datetime.combine(day, time.min, zone).astimezone(UTC)
    end = datetime.combine(day+timedelta(days=1), time.min, zone).astimezone(UTC)
    booked = db.scalar(select(func.count()).select_from(Appointment).where(Appointment.tenant_id == tenant_id,
        Appointment.created_at >= start, Appointment.created_at < end, Appointment.status == "CONFIRMED"))
    attendance = dict(db.execute(select(Appointment.attendance, func.count()).where(Appointment.tenant_id == tenant_id,
        Appointment.start_at >= start, Appointment.start_at < end).group_by(Appointment.attendance)).all())
    cancellation_count = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.tenant_id == tenant_id,
        AuditEvent.action == "appointment.canceled", AuditEvent.created_at >= start, AuditEvent.created_at < end))
    minutes = sum(call_minutes(e) for e in db.scalars(select(UsageEvent).where(UsageEvent.tenant_id == tenant_id,
        UsageEvent.created_at >= start, UsageEvent.created_at < end)))
    filled = db.scalar(select(func.count()).select_from(WaitlistOffer).join(Appointment, Appointment.id == WaitlistOffer.appointment_id)
        .where(WaitlistOffer.tenant_id == tenant_id, Appointment.created_at >= start, Appointment.created_at < end,
               WaitlistOffer.status == "ACCEPTED"))
    return {"schema_version": "1.0", "day": day.isoformat(), "timezone": str(zone),
        "verified_new_bookings_still_confirmed": booked, "attended": attendance.get("ATTENDED", 0),
        "no_show": attendance.get("NO_SHOW", 0), "attendance_unknown": attendance.get(None, 0),
        "cancellations_recorded": cancellation_count, "waitlist_fills": filled,
        "open_tasks_now": db.scalar(select(func.count()).select_from(StaffTask).where(StaffTask.tenant_id == tenant_id,
            StaffTask.status.in_(["OPEN", "IN_PROGRESS", "PENDING", "CALLBACK"]))),
        "metered_call_minutes": round(minutes, 3), "as_of": iso(now_utc()),
        "contains_patient_records": False, "financial_value": "not_inferred"}


def enqueue_digest(db, destination: DigestDestination, day: date):
    existing = db.scalar(select(DigestDelivery).where(DigestDelivery.destination_id == destination.id,
                                                     DigestDelivery.period == day.isoformat()))
    if existing:
        return existing
    row = DigestDelivery(tenant_id=destination.tenant_id, destination_id=destination.id, period=day.isoformat(),
                         payload=daily_aggregate(db, destination.tenant_id, day))
    db.add(row)
    db.flush()
    return row


class DigestRequest(StrictModel):
    day: date


@router.post("/operations/digest-destinations/{destination_id}/queue")
def queue_digest(destination_id: str, data: DigestRequest, actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    from zoneinfo import ZoneInfo
    # One queue record per destination/day, including concurrent SQLite calls.
    db.execute(update(Tenant).where(Tenant.id == actor.tenant_id).values(settings_version=Tenant.settings_version))
    destination = db.scalar(select(DigestDestination).where(DigestDestination.id == destination_id,
        DigestDestination.tenant_id == actor.tenant_id).with_for_update())
    if not destination or not destination.enabled:
        fail(404, "DESTINATION_NOT_FOUND", "مقصد فعال پیدا نشد.")
    today = now_utc().astimezone(ZoneInfo(db.get(Tenant, actor.tenant_id).timezone)).date()
    if not today-timedelta(days=31) <= data.day < today:
        fail(422, "CLOSED_DAY_REQUIRED", "یک روز پایان‌یافته در ۳۱ روز گذشته انتخاب کنید.")
    row = enqueue_digest(db, destination, data.day)
    audit(db, actor, "digest.queued", "digest_delivery", row.id, day=data.day.isoformat())
    db.commit()
    return {"id": row.id, "status": row.status, "summary": row.payload}


@router.get("/operations/digest-deliveries")
def digest_deliveries(actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    return [{"id": r.id, "destination_id": r.destination_id, "day": r.period, "status": r.status,
             "error_code": r.error_code, "summary": r.payload, "created_at": iso(r.created_at)}
            for r in db.scalars(select(DigestDelivery).where(DigestDelivery.tenant_id == actor.tenant_id)
                .order_by(DigestDelivery.created_at.desc()).limit(100))]


async def dispatch_digest(db: Session, delivery_id: str) -> dict:
    row = db.get(DigestDelivery, delivery_id)
    destination = db.get(DigestDestination, row.destination_id) if row else None
    if not row or not destination:
        raise ValueError("Digest delivery not found")
    if row.status != "QUEUED":
        return {"status": row.status}
    if not destination.enabled:
        row.status = "SUPPRESSED"
        db.commit()
        return {"status": row.status}
    authority = db.scalar(select(Membership.id).join(User, User.id == Membership.user_id).where(
        Membership.tenant_id == row.tenant_id, Membership.user_id == destination.created_by,
        Membership.active.is_(True), Membership.role == "owner", User.active.is_(True)))
    if not authority or not db.get(Tenant, row.tenant_id).active:
        row.status = "SUPPRESSED"
        db.commit()
        return {"status": row.status}
    if settings.demo_mode:
        row.status = "SIMULATED"
        db.commit()
        return {"status": row.status}
    url = approved_url(os.getenv("DIGEST_GATEWAY_URL", ""), "DIGEST_PROCESSOR_APPROVED")
    secret = os.getenv("DIGEST_GATEWAY_TOKEN", "")
    if len(secret) < 32:
        raise ProviderError("DIGEST_NOT_CONFIGURED")
    from .billing import reserve_cost, mark_cost_started, settle_cost
    from .privacy_controls import require_processor
    try:
        require_processor(db, row.tenant_id, "digest_gateway", "processing", os.getenv("DIGEST_PROCESSOR_REGION", "not_recorded"))
        ticket = reserve_cost(db, row.tenant_id, "digest:" + row.id, "digest_gateway", "digest_delivery", 1)
        mark_cost_started(db, ticket["id"])
    except HTTPException as exc:
        row.status, row.error_code = "FAILED", exc.detail["code"]
        db.commit()
        return {"status": row.status, "error_code": row.error_code}
    claimed = db.execute(update(DigestDelivery).where(DigestDelivery.id == row.id,
        DigestDelivery.status == "QUEUED").values(status="DISPATCHING"))
    db.commit()
    if not claimed.rowcount:
        return {"status": "ALREADY_CLAIMED"}
    try:
        response = await provider_request("POST", url, operation="owner-digest", write=True,
            headers={"Authorization": "Bearer "+secret, "Idempotency-Key": row.id},
            json={"schema_version": "1.0", "delivery_id": row.id, "channel": destination.channel,
                  "recipient": decrypt(destination.recipient_encrypted), "summary": row.payload})
        body = response.json()
        if body.get("status") not in {"accepted", "delivered"} or not isinstance(body.get("reference"), str):
            raise ProviderError("INVALID_DIGEST_RECEIPT", unknown_outcome=True)
        # A proxy's acceptance is not end-user delivery evidence.
        row.status, row.provider_reference = "SENT", body["reference"][:160]
        settle_cost(db, ticket["id"], 1, "digest-receipt:" + row.id)
    except (ProviderError, ValueError) as exc:
        row.status = "UNKNOWN" if not isinstance(exc, ProviderError) or exc.unknown_outcome else "FAILED"
        row.error_code = exc.code if isinstance(exc, ProviderError) else "INVALID_DIGEST_RECEIPT"
        settle_cost(db, ticket["id"], 0, "digest-failure:" + row.id, "unknown" if row.status == "UNKNOWN" else "no_charge")
    db.commit()
    return {"status": row.status}


async def run_partner_jobs(session_factory):
    """Queue opted-in daily aggregates and send once; unknowns are never resent."""
    from zoneinfo import ZoneInfo
    with session_factory() as db:
        db.execute(update(DigestDelivery).where(DigestDelivery.status == "DISPATCHING",
            DigestDelivery.updated_at < now_utc()-timedelta(minutes=2)).values(status="UNKNOWN", error_code="WORKER_INTERRUPTED"))
        db.commit()
        destination_ids = list(db.scalars(select(DigestDestination.id).where(
            DigestDestination.enabled.is_(True), DigestDestination.automatic_daily.is_(True))))
    for destination_id in destination_ids:
        with session_factory() as db:
            destination = db.get(DigestDestination, destination_id)
            tenant = db.get(Tenant, destination.tenant_id)
            local_now = now_utc().astimezone(ZoneInfo(tenant.timezone))
            if not tenant.active or local_now.hour < destination.local_hour:
                continue
            db.execute(update(Tenant).where(Tenant.id == tenant.id).values(settings_version=Tenant.settings_version))
            db.refresh(destination)
            if destination.enabled and destination.automatic_daily:
                enqueue_digest(db, destination, local_now.date()-timedelta(days=1))
            db.commit()
    with session_factory() as db:
        ids = list(db.scalars(select(DigestDelivery.id).where(DigestDelivery.status == "QUEUED")
                             .order_by(DigestDelivery.created_at).limit(10)))
    for delivery_id in ids:
        with session_factory() as db:
            try:
                await dispatch_digest(db, delivery_id)
            except ProviderError as exc:
                row = db.get(DigestDelivery, delivery_id)
                row.error_code = exc.code
                db.commit()


class PoolInput(StrictModel):
    building_id: str = Field(min_length=1, max_length=100)
    tenant_ids: list[str] = Field(min_length=1, max_length=50)
    contract_reference: str = Field(min_length=5, max_length=200)
    included_minutes: int = Field(ge=0, le=10000000)
    overage_toman_per_minute: int = Field(ge=0, le=100000000)
    effective_period: str = Field(pattern=r"^\d{4}-\d{2}$")


def authorized_pool(db, actor, tenant_ids, building_id=None):
    ids = sorted(set(tenant_ids))
    rows = db.execute(select(Tenant, Membership).join(Membership).where(Tenant.id.in_(ids), Tenant.active.is_(True),
        Membership.user_id == actor.user_id, Membership.active.is_(True), Membership.role == "owner")).all()
    if len(rows) != len(ids) or (building_id and any(t.building_id != building_id for t, _ in rows)):
        fail(403, "POOL_AUTHORITY_REQUIRED", "اختیار مالک و عضویت همان ساختمان برای همه مراکز لازم است.")
    return ids


@router.get("/operations/building-contracts")
def list_pools(actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    owned = {tenant.id: tenant for tenant in db.scalars(select(Tenant).join(Membership).where(
        Membership.user_id == actor.user_id, Membership.active.is_(True), Membership.role == "owner",
        Tenant.active.is_(True)))}
    records = []
    for row in db.scalars(select(BuildingContract).where(BuildingContract.active.is_(True)).order_by(BuildingContract.created_at.desc())):
        if actor.tenant_id not in row.tenant_ids or any(
                tenant_id not in owned or owned[tenant_id].building_id != row.building_id for tenant_id in row.tenant_ids):
            continue
        records.append({"id": row.id, "building_id": row.building_id, "tenant_ids": row.tenant_ids,
            "tenants": [{"id": tenant_id, "name": owned[tenant_id].name} for tenant_id in row.tenant_ids],
            "contract_reference": row.contract_reference, "included_minutes": row.included_minutes,
            "overage_toman_per_minute": row.overage_toman_per_minute, "effective_period": row.effective_period,
            "created_at": iso(row.created_at), "draft": True})
        if len(records) >= 100:
            break
    return records


@router.post("/operations/building-contracts", status_code=201)
def create_pool(data: PoolInput, actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    from .operations import period_bounds
    period_bounds(data.effective_period)
    ids = authorized_pool(db, actor, data.tenant_ids, data.building_id)
    row = BuildingContract(**data.model_dump(exclude={"tenant_ids"}), tenant_ids=ids, created_by=actor.user_id)
    db.add(row)
    db.flush()
    audit(db, actor, "billing.pool_created", "building_contract", row.id, tenant_count=len(ids))
    db.commit()
    return {"id": row.id, "tenant_ids": row.tenant_ids, "effective_period": row.effective_period}


@router.get("/operations/building-contracts/{contract_id}/allocation")
def pool_allocation(contract_id: str, period: str, actor: Actor = Depends(owner), db: Session = Depends(get_db)):
    from .operations import period_bounds
    row = db.get(BuildingContract, contract_id)
    if not row or not row.active:
        fail(404, "POOL_NOT_FOUND", "قرارداد فعال پیدا نشد.")
    ids = authorized_pool(db, actor, row.tenant_ids, row.building_id)
    if period < row.effective_period:
        fail(422, "POOL_NOT_EFFECTIVE", "قرارداد در این دوره فعال نیست.")
    start, end = period_bounds(period)
    used = {tenant_id: Decimal(0) for tenant_id in ids}
    for event in db.scalars(select(UsageEvent).where(UsageEvent.tenant_id.in_(ids), UsageEvent.created_at >= start, UsageEvent.created_at < end)):
        used[event.tenant_id] += Decimal(str(call_minutes(event)))
    total = sum(used.values())
    included = min(total, Decimal(row.included_minutes))
    overage = max(Decimal(0), total-included)
    due = int((overage * row.overage_toman_per_minute).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    # Largest remainder allocation keeps the sum of integer toman charges exact.
    exact = {tenant_id: (Decimal(due)*amount/total if total else Decimal(0)) for tenant_id, amount in used.items()}
    allocation = {tenant_id: int(value) for tenant_id, value in exact.items()}
    remainder = due-sum(allocation.values())
    for tenant_id in sorted(ids, key=lambda i: (-(exact[i]-allocation[i]), i))[:remainder]:
        allocation[tenant_id] += 1
    return {"contract_id": row.id, "period": period, "allocation_rule": "proportional_usage_largest_remainder_toman",
        "total_minutes": float(total), "included_minutes_used": float(included), "overage_minutes": float(overage),
        "overage_toman": due, "items": [{"tenant_id": i, "minutes": float(used[i]),
            "included_minutes": float(included*used[i]/total) if total else 0, "overage_toman": allocation[i]} for i in ids],
        "draft": True, "notes": "Contract allocation only; tax and base subscription remain separate. No charge was made."}
