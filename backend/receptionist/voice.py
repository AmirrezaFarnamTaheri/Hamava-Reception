"""A bounded Persian conversation engine over the authoritative calendar.

State and confirmation live on the server. Neither browser text nor an optional
speech/LLM provider can supply tenant claims, identity proof, or booking truth.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, literal, or_, select, union_all, update
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from . import __version__
from .config import settings
from . import models_partner  # noqa: F401 — register optional identity/thread tables before schema creation
from .core import CALL_DURATION_KINDS, ReceptionService
from .db import UTCDateTime, get_db, now_utc
from .locale import normalize_digits, normalize_phone, normalize_text, resolve_persian_datetime
from .models import (Appointment, AuditEvent, ConsentGrant, MessageOutbox, Occupancy,
                     Practitioner, Service, SlotHold, StaffTask, Tenant, UsageEvent, uid)
from .models_voice import CallSession, RateWindow, VerificationChallenge, VoiceTurn
from .providers import KavenegarSMS, ProviderError, SpeechGateway, enabled
from .security import bearer, decrypt, encrypt, fail, hash_phone
from .privacy_controls import effective_processing_retention, processing_notice
from .ops_controls import append_trace
from .provider_control import ProviderContext
from .tool_gateway import ToolGateway, persist_tool_spans

router = APIRouter(prefix="/api/v1", tags=["caller"])
GREETING = "سلام، من دستیار هوشمند پذیرش هستم. برای هماهنگی نوبت کمکتون می‌کنم؛ هر زمان بخواید می‌تونید از همکار انسانی کمک بگیرید. برای چه کاری تماس گرفتید؟"
SAFE_FAILURE = "الان انجام این کار ممکن نیست. درخواست پیگیری پذیرش را ثبت می‌کنم؛ نوبتی را بدون تأیید تقویم قطعی اعلام نمی‌کنم."
YES = {"بله", "آره", "اره", "تایید", "تأیید", "باشه", "ثبت کن", "تایید می کنم", "تأیید می کنم", "اوکی", "yes", "ok", "1"}
NO = {"نه", "خیر", "نخیر", "no", "0"}
HUMAN = ("منشی", "اپراتور", "انسان", "همکار انسانی", "پذیرش انسانی", "operator", "human")
URGENT = ("نفس نمی", "تنگی نفس شدید", "درد شدید قفسه", "بیهوش", "خونریزی شدید", "خودکشی", "اورژانس")
ACTIVE_TASK_STATUSES = {"OPEN", "IN_PROGRESS", "PENDING", "CALLBACK"}
BOOKING_STATUS_LABELS = {"CONFIRMED": "تأییدشده", "CANCELED": "لغوشده", "EXPIRED": "منقضی‌شده",
                         "PENDING_PAYMENT": "در انتظار پرداخت", "PENDING_STAFF_APPROVAL": "در انتظار تأیید پذیرش"}


@lru_cache(maxsize=4)
def _source_version(component: str) -> str:
    """Content identifiers describe the deployed code, without inventing tags."""
    try:
        return "sha256:" + hashlib.sha256(Path(__file__).with_name(component + ".py").read_bytes()).hexdigest()
    except OSError:
        return "not_recorded"


def configured_versions() -> dict:
    def configured(name):
        value = os.getenv(name, "")
        return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+:-]{0,119}", value) else "not_recorded"

    return {"app": __version__, "fsm": _source_version("voice"), "locale": _source_version("locale"),
            "calendar": _source_version("core"), "adapter": _source_version("providers"),
            "configured_asr": configured("SPEECH_ASR_VERSION"), "configured_tts": configured("SPEECH_VOICE_VERSION")}


def _approved_fact(fact: dict, at: datetime) -> bool:
    """Every spoken fact needs approved, dated provenance in this call's snapshot."""
    if not all(isinstance(fact.get(key), str) and fact[key].strip()
               for key in ("answer", "approved_by", "source", "effective_at", "expires_at")):
        return False
    try:
        effective = datetime.fromisoformat(fact["effective_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(fact["expires_at"].replace("Z", "+00:00"))
        return effective.tzinfo is not None and expires.tzinfo is not None and effective <= at < expires
    except (ValueError, TypeError):
        return False


def _requested_language(text: str) -> str | None:
    lowered = text.casefold().strip(" .!؟?،,")
    languages = (("english", ("english", "انگلیسی", "الانجلیزیة", "الإنجلیزیة")),
                 ("arabic", ("arabic", "عربی", "العربیة")))
    request = any(cue in lowered for cue in ("زبان", "صحبت", "حرف", "بگو", "می خوا", "می خو", "لطفا",
        "تتحدث", "تتکلم", "باللغة", "أرید", "ارید", "تکلم", "بالعربیة"))
    request = request or bool(re.search(r"\b(?:speak|talk|language|please|in|can)\b", lowered))
    for language, labels in languages:
        if lowered in labels or (request and any(label in lowered for label in labels)):
            return language
    return None


def _bookings_readback(db: Session, row: CallSession, data: dict) -> list[dict]:
    if data.get("external_booking_operation"):
        from .models_core import ExternalCalendarOperation
        from .calendar_bridge import external_booking
        operation = db.scalar(select(ExternalCalendarOperation).where(ExternalCalendarOperation.id == data["external_booking_operation"],
            ExternalCalendarOperation.tenant_id == row.tenant_id, ExternalCalendarOperation.call_id == row.id))
        if operation and operation.status == "SUCCEEDED":
            remote = json.loads(decrypt(operation.result_encrypted))
            value = external_booking(db, row.tenant_id, remote, patient_name=data.get("patient_name"))
            value.update(status="READBACK_REQUIRED", last_known_status=remote["status"], verified_at=operation.updated_at.isoformat())
            return [value]
    identifiers = data.get("booking_ids", [])[:2]
    if not identifiers:
        return []
    records = {record.id: record for record in db.scalars(select(Appointment).where(
        Appointment.tenant_id == row.tenant_id, Appointment.session_id == row.id, Appointment.id.in_(identifiers)))}
    service = ReceptionService(db, row.tenant_id, "caller:" + row.id)
    return [service.appointment_dict(records[key]) for key in identifiers if key in records]


def _booking_summary(bookings: list[dict]) -> str:
    return " ".join(f"نوبت با کد {item['reference']} در وضعیت {BOOKING_STATUS_LABELS.get(item['status'], item['status'])} است."
                    for item in bookings)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StartSession(StrictModel):
    clinic_slug: str = Field(min_length=1, max_length=100)
    processing_consent: bool
    processing_notice_fingerprint: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    recording_consent: bool = False
    training_consent: bool = False


class TurnInput(StrictModel):
    text: str = Field(min_length=1, max_length=2000)
    request_id: str = Field(min_length=8, max_length=100)


class HandoffInput(StrictModel):
    reason: str = Field(default="human_requested", max_length=80)


def digest(value: str) -> str:
    return hmac.new(settings.jwt_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def capabilities() -> dict:
    audio = SpeechGateway().configured
    return {"audio_input": audio, "audio_output": audio, "livekit": bool(os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY") and enabled("LIVEKIT_APPROVED")),
            "mode": "configured_speech" if audio else "text_demo", "configured": audio,
            "demo": settings.demo_mode, "recording": False, "training": False,
            "processing_location": os.getenv("SPEECH_PROCESSING_LOCATION", "not_configured")}


def rate_limit(db: Session, key: str, limit: int, window: int) -> None:
    """Database-backed fixed-window admission; shared across worker processes."""
    bucket = int(time.time()) // window
    full_key = f"{key}:{bucket}"
    factory = __import__("sqlalchemy.dialects.sqlite", fromlist=["insert"]).insert if db.bind.dialect.name == "sqlite" else __import__("sqlalchemy.dialects.postgresql", fromlist=["insert"]).insert
    stmt = factory(RateWindow).values(key=full_key, count=1, expires_at=now_utc() + timedelta(seconds=window * 2))
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"count": RateWindow.count + 1})
    db.execute(stmt)
    db.commit()
    count = db.scalar(select(RateWindow.count).where(RateWindow.key == full_key))
    if count > limit:
        fail(429, "RATE_LIMIT", "تعداد درخواست‌ها زیاد است؛ کمی بعد دوباره تلاش کنید.")


def _processing_disclosure(tenant: Tenant, db: Session | None, *, purpose_notice=None) -> dict:
    from .locale import PERSIAN_DIGITS
    if purpose_notice is None:
        purpose_notice = processing_notice(db, tenant.id) if db is not None else {"policy_version": "v1", "notice": None}
    retention_days = effective_processing_retention(db, tenant)
    retention_label = str(retention_days).translate(PERSIAN_DIGITS)
    notice = (
                "این گفت‌وگو با دستیار هوشمند است. صدای خام ذخیره نمی‌شود و گفت‌وگو برای آموزش استفاده نمی‌شود. "
                "متن و نتایج ضروری گفت‌وگو فقط برای پذیرش همین مرکز و بازیابی درخواست‌ها به‌صورت رمزگذاری‌شده نگهداری می‌شود. "
                f"دوره نگهداری طبق تنظیم مرکز، {retention_label} روز پس از پایان گفت‌وگو است؛ پس از آن پاک‌سازی در اجرای برنامه زمان‌بندی‌شده انجام می‌شود. "
                "برای درخواست حذف یا ادامه خدمت بدون گفت‌وگو با دستیار، با پذیرش مرکز تماس بگیرید. سوابق ضروری نوبت ممکن است جداگانه نگهداری شوند."
            )
    disclosure = {"notice": notice, "transcript_retention_days": retention_days,
                  "processing_policy_version": purpose_notice["policy_version"],
                  "processing_notice": purpose_notice["notice"]}
    disclosure["processing_notice_fingerprint"] = digest(json.dumps({"tenant_id": tenant.id, **disclosure}, sort_keys=True, ensure_ascii=False))
    return disclosure


def public_clinic(tenant: Tenant, db: Session | None = None) -> dict:
    from .partners import published_identity
    identity = published_identity(db, tenant.id) if db is not None else {}
    return {"id": tenant.id, "name": tenant.name, "slug": tenant.slug, "address": tenant.address,
            "phone": tenant.phone, "timezone": tenant.timezone, "mode": tenant.mode,
            **_processing_disclosure(tenant, db),
            "capabilities": capabilities(),
            "identity": {key: identity[key] for key in ("brand_name", "brand_color", "profile_version") if key in identity}}


@router.get("/public/clinics/{slug}")
def clinic(slug: str, db: Session = Depends(get_db)):
    row = db.scalar(select(Tenant).where(Tenant.slug == slug, Tenant.active.is_(True)))
    if not row:
        fail(404, "CLINIC_NOT_FOUND", "مرکز پیدا نشد.")
    return public_clinic(row, db)


def _automation_allowed(tenant: Tenant, started, routing_reason: str | None) -> bool:
    if tenant.mode in {"ai_primary", "supervised"}:
        return True
    if tenant.mode == "overflow":
        return routing_reason in {"busy", "no_answer"}
    if tenant.mode == "after_hours":
        local = started.astimezone(ZoneInfo(tenant.timezone))
        if local.date().isoformat() in tenant.holidays:
            return True
        local_time = local.strftime("%H:%M")
        return not any(start <= local_time < end for start, end in tenant.working_hours.get(str(local.weekday()), []))
    return False


def new_session(db: Session, tenant: Tenant, channel: str = "browser_text", *,
                routing_reason: str | None = None, commit: bool = True,
                processing_notice_fingerprint: str | None = None,
                require_notice_match: bool = False) -> tuple[CallSession, str]:
    """Serialize all channel admission and reserve a bounded duration budget.

    The no-op tenant update is a portable write lock, including on SQLite. A
    single UNION query reads completed usage and active reservations from one
    snapshot, so a simultaneous call-end cannot omit or double-count a call.
    """
    locked = db.execute(update(Tenant).where(Tenant.id == tenant.id, Tenant.active.is_(True))
                        .values(settings_version=Tenant.settings_version))
    if locked.rowcount != 1:
        fail(404, "CLINIC_NOT_FOUND", "مرکز پیدا نشد.")
    db.refresh(tenant)
    if tenant.mode == "paused":
        fail(503, "RECEPTION_PAUSED", "پذیرش خودکار موقتاً متوقف است. با مرکز تماس بگیرید.")
    from .operations_uat import require_current_uat
    require_current_uat(db, tenant)
    started = now_utc()
    concurrent = db.scalar(select(func.count()).select_from(CallSession).where(
        CallSession.tenant_id == tenant.id, CallSession.ended_at.is_(None), CallSession.expires_at > started))
    if concurrent >= max(1, int(os.getenv("MAX_CONCURRENT_CALLS_PER_TENANT", "20"))):
        fail(503, "CAPACITY", "پذیرش مشغول است؛ کمی بعد دوباره تلاش کنید یا با مرکز تماس بگیرید.")
    month_start = started.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = (month_start + timedelta(days=32)).replace(day=1)
    usage = select(UsageEvent.quantity, UsageEvent.unit, literal(None, UTCDateTime), literal(None, UTCDateTime)).where(
        UsageEvent.tenant_id == tenant.id, UsageEvent.kind.in_(CALL_DURATION_KINDS), UsageEvent.created_at >= month_start)
    reservations = select(literal(0.0), literal("reservation"), CallSession.started_at, CallSession.expires_at).where(
        CallSession.tenant_id == tenant.id, CallSession.ended_at.is_(None), CallSession.expires_at >= month_start)
    reserved_seconds = 0.0
    for quantity, unit, begin, finish in db.execute(union_all(usage, reservations)):
        if unit == "reservation":
            reserved_seconds += max(0, (finish - max(begin, month_start)).total_seconds())
        elif unit in {"minute", "minutes"}:
            reserved_seconds += quantity * 60
        elif unit in {"second", "seconds"}:
            reserved_seconds += quantity
    duration = min(float(os.getenv("MAX_CALL_SECONDS", "1800")), tenant.monthly_minute_budget * 60 - reserved_seconds,
                   (month_end - started).total_seconds())
    if duration < 1:
        fail(503, "BUDGET_LIMIT", "پذیرش خودکار فعلاً در دسترس نیست؛ با مرکز تماس بگیرید.")
    token = secrets.token_urlsafe(36)
    from .partners import published_identity
    from .core_policy import policy as core_policy
    from .routing import snapshot as routing_snapshot
    notice = processing_notice(db, tenant.id)
    disclosure = _processing_disclosure(tenant, db, purpose_notice=notice)
    # The same tenant fence protects purpose/retention publication and intake.
    # Legacy synthetic clients may omit this field only in explicit demo mode.
    if require_notice_match and (processing_notice_fingerprint is not None or not settings.demo_mode) and processing_notice_fingerprint != disclosure["processing_notice_fingerprint"]:
        fail(409, "PROCESSING_NOTICE_CHANGED", "متن یا شرایط پردازش تغییر کرده است؛ اطلاعیه تازه را بخوانید و رضایت را دوباره تأیید کنید.")
    snapshot = {"faq": tenant.faq, "address": tenant.address, "phone": tenant.phone,
                "name": tenant.name, "timezone": tenant.timezone, "mode": tenant.mode,
                "retention_days": disclosure["transcript_retention_days"], "settings_version": tenant.settings_version,
                "automation_allowed": _automation_allowed(tenant, started, routing_reason),
                "routing_reason": routing_reason, "identity": published_identity(db, tenant.id),
                "versions": configured_versions(), "core_policy": core_policy(db, tenant.id),
                "processing_policy_version": notice["policy_version"], "processing_notice": notice["notice"],
                "processing_notice_fingerprint": disclosure["processing_notice_fingerprint"],
                "routing": routing_snapshot(db, tenant.id)}
    row = CallSession(id=uid(), tenant_id=tenant.id, token_hash=digest(token), channel=channel,
        policy_version=tenant.settings_version, policy_snapshot=snapshot,
        context_encrypted=encrypt(json.dumps({"last_reply": GREETING, "family_remaining": 1}, ensure_ascii=False)),
        processing_consent=True, recording_consent=False, training_consent=False,
        started_at=started, expires_at=started + timedelta(seconds=duration), state="INTENT", intent="unknown")
    db.add(row)
    for purpose, granted in (("processing", True), ("recording", False), ("training", False)):
        db.add(ConsentGrant(tenant_id=tenant.id, subject_hash="session:" + row.id, purpose=purpose,
            granted=granted, policy_version=notice["policy_version"] if purpose == "processing" else str(tenant.settings_version),
            expires_at=notice.get("consent_expires_at") if purpose == "processing" else None,
            evidence={"source": channel, "call_id": row.id,
                      **({"notice_fingerprint": disclosure["processing_notice_fingerprint"],
                          "displayed_notice_bound": bool(require_notice_match and processing_notice_fingerprint)} if purpose == "processing" else {})}))
    db.flush()
    if channel in {"sip", "webrtc"} and snapshot["automation_allowed"]:
        from .media_cost import reserve_media_cost
        reserve_media_cost(db, row)
    append_trace(db, tenant.id, "call:" + row.id + ":started", "call.started", call_id=row.id, versions=snapshot["versions"], attributes={"status": "admitted"})
    db.add(AuditEvent(tenant_id=tenant.id, actor_id="caller:" + row.id, action="call.started", entity_type="call", entity_id=row.id, details={"channel": channel, "recording": False}))
    if not snapshot["automation_allowed"]:
        db.flush()
        request_handoff(db, row, "human_requested")
        save_context(row, {"last_reply": "درخواست شما برای پذیرش انسانی ثبت شد. هنوز اتصال انسانی برقرار نشده است؛ برای تماس مستقیم از شماره مرکز استفاده کنید.", "family_remaining": 1})
    if commit:
        db.commit()
    else:
        db.flush()
    return row, token


@router.post("/public/sessions", status_code=201)
def start_session(body: StartSession, request: Request, db: Session = Depends(get_db)):
    if not body.processing_consent:
        fail(422, "CONSENT_REQUIRED", "برای شروع، رضایت پردازش اطلاعات لازم است؛ می‌توانید با پذیرش تلفنی تماس بگیرید.")
    if body.recording_consent or body.training_consent:
        fail(422, "PURPOSE_DISABLED", "ذخیره صدا و استفاده آموزشی در این نسخه غیرفعال است.")
    tenant = db.scalar(select(Tenant).where(Tenant.slug == body.clinic_slug, Tenant.active.is_(True)))
    if not tenant:
        fail(404, "CLINIC_NOT_FOUND", "مرکز پیدا نشد.")
    rate_limit(db, "session:" + digest(request.client.host if request.client else "unknown"), 20 if settings.demo_mode else 6, 300)
    row, token = new_session(db, tenant, processing_notice_fingerprint=body.processing_notice_fingerprint, require_notice_match=True)
    return {"session_id": row.id, "token": token, "greeting": context(row)["last_reply"],
            "state": row.state, "capabilities": capabilities(), "expires_at": row.expires_at.isoformat(),
            "versions": row.policy_snapshot["versions"], "policy_version": row.policy_version}


def authenticated_call(session_id: str, credentials: HTTPAuthorizationCredentials | None, db: Session, *, allow_ended=False) -> CallSession:
    if credentials is None or credentials.scheme.lower() != "bearer":
        fail(401, "SESSION_TOKEN_REQUIRED", "نشست معتبر لازم است.")
    row = db.get(CallSession, session_id)
    if row is None:
        fail(404, "SESSION_NOT_FOUND", "نشست پیدا نشد.")
    if not hmac.compare_digest(row.token_hash, digest(credentials.credentials)):
        try:
            claims = jwt.decode(credentials.credentials, settings.jwt_secret, algorithms=["HS256"],
                audience="media-worker", issuer="persian-receptionist",
                options={"require": ["sub", "tenant", "worker", "lease", "iat", "exp"]})
        except jwt.PyJWTError:
            fail(404, "SESSION_NOT_FOUND", "نشست پیدا نشد.")
        if claims["sub"] != row.id or claims["tenant"] != row.tenant_id:
            fail(404, "SESSION_NOT_FOUND", "نشست پیدا نشد.")
        if (claims["worker"] != row.media_worker_id or claims["lease"] != row.media_worker_token
                or not row.media_worker_lease or row.media_worker_lease <= now_utc()):
            fail(409, "MEDIA_LEASE_LOST", "مالکیت رسانه پایان یافته است.")
        db.info["media_authority"] = (row.id, claims["worker"], claims["lease"])
    else:
        db.info.pop("media_authority", None)
    tenant = db.get(Tenant, row.tenant_id)
    if not tenant or not tenant.active:
        fail(404, "SESSION_NOT_FOUND", "نشست پیدا نشد.")
    if not allow_ended and (row.ended_at or row.expires_at <= now_utc()):
        fail(410, "SESSION_EXPIRED", "گفت‌وگو پایان یافته است؛ یک گفت‌وگوی تازه شروع کنید.")
    if row.channel == "voice_note":
        from .partners import authorized_voice_thread
        authorized_voice_thread(db, row)
    return row


def media_session_token(row: CallSession) -> str:
    return jwt.encode({"sub": row.id, "tenant": row.tenant_id, "worker": row.media_worker_id,
        "lease": row.media_worker_token, "iat": now_utc(), "exp": row.expires_at,
        "iss": "persian-receptionist", "aud": "media-worker"}, settings.jwt_secret, algorithm="HS256")


def context(row: CallSession) -> dict:
    return json.loads(decrypt(row.context_encrypted))


def save_context(row: CallSession, data: dict):
    row.context_encrypted = encrypt(json.dumps(data, ensure_ascii=False))


def ensure_ai_allowed(db: Session, row: CallSession) -> None:
    """Check again after provider latency and under the turn transaction lock."""
    db.refresh(row)
    _check_media_authority(db, row)
    if row.ended_at or row.expires_at <= now_utc():
        fail(410, "SESSION_EXPIRED", "گفت‌وگو پایان یافته است؛ یک گفت‌وگوی تازه شروع کنید.")
    if not row.processing_consent:
        fail(409, "PROCESSING_DISABLED", "رضایت پردازش این گفت‌وگو معتبر نیست؛ با پذیرش تماس بگیرید.")
    if row.state == "HUMAN_CONNECTED" or row.handoff_status == "CONNECTED":
        fail(409, "HUMAN_CONNECTED", "همکار انسانی به تماس وصل است؛ دستیار خودکار متوقف شده است.")
    tenant = db.get(Tenant, row.tenant_id, populate_existing=True)
    if not tenant or not tenant.active or tenant.mode == "paused":
        fail(503, "RECEPTION_PAUSED", "پذیرش خودکار متوقف است؛ با مرکز تماس بگیرید.")
    processing_notice(db, tenant.id)  # A disabled purpose also stops existing text/media turns.
    from .operations_uat import require_current_uat
    require_current_uat(db, tenant)
    if row.channel == "voice_note":
        from .partners import authorized_voice_thread
        authorized_voice_thread(db, row)


def _check_media_authority(db: Session, row: CallSession) -> None:
    authority = db.info.get("media_authority")
    if authority and (authority != (row.id, row.media_worker_id, row.media_worker_token)
                      or not row.media_worker_lease or row.media_worker_lease <= now_utc()):
        fail(409, "MEDIA_LEASE_LOST", "مالکیت رسانه پایان یافته است.")


def release_holds(db: Session, row: CallSession) -> None:
    holds = list(db.scalars(update(SlotHold).where(SlotHold.tenant_id == row.tenant_id,
        SlotHold.session_id == row.id, SlotHold.status == "HELD").values(status="RELEASED").returning(SlotHold.id)))
    if holds:
        db.execute(delete(Occupancy).where(Occupancy.tenant_id == row.tenant_id,
            Occupancy.owner_type == "hold", Occupancy.owner_id.in_(holds)))
    from .models_core import ExternalCalendarOperation
    from .calendar_bridge import queue_operation
    # A release is an outbox operation too; no network request runs under the
    # conversation transaction. TTL remains the remote safety backstop.
    for held in db.scalars(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == row.tenant_id,
            ExternalCalendarOperation.call_id == row.id, ExternalCalendarOperation.operation == "hold", ExternalCalendarOperation.status == "SUCCEEDED")):
        value = json.loads(decrypt(held.result_encrypted))
        if value.get("expires_at") and datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00")) > now_utc():
            queue_operation(db, row.tenant_id, "release", {"hold_id": value["id"]}, "release:" + held.id, "caller:" + row.id, call_id=row.id)


def request_handoff(db: Session, row: CallSession, reason: str) -> dict:
    # This serializes takeover/end with the entire synchronous booking turn.
    db.execute(update(Tenant).where(Tenant.id == row.tenant_id).values(settings_version=Tenant.settings_version))
    db.execute(update(CallSession).where(CallSession.id == row.id).values(state=CallSession.state))
    db.refresh(row)
    _check_media_authority(db, row)
    reason = reason if reason in {"human_requested", "urgent_concern", "low_confidence", "booking_exception", "billing_exception", "service_failure", "privacy_request", "unsupported_language", "faq_conflict"} else "human_requested"
    existing = db.scalar(select(StaffTask).where(StaffTask.tenant_id == row.tenant_id, StaffTask.call_id == row.id,
        StaffTask.status.in_(ACTIVE_TASK_STATUSES)).limit(1))
    if row.state == "HUMAN_CONNECTED" or row.handoff_status in {"CONNECTED", "DISCONNECTED"}:
        # After a verified staff/caller BridgeLeave, historical human takeover
        # must NOT be presented to patients as an active staffed connection.
        connected = row.handoff_status == "CONNECTED"
        return {"status": "CONNECTED" if connected else "DISCONNECTED", "task_id": existing.id if existing else None,
                "reason": reason, "phone": row.policy_snapshot.get("phone", ""), "connected": connected}
    if row.ended_at:
        fail(410, "SESSION_EXPIRED", "گفت‌وگو پایان یافته است.")
    if not existing:
        existing = StaffTask(id=uid(), tenant_id=row.tenant_id, call_id=row.id, reason=reason,
            summary="تماس‌گیرنده به کمک پذیرش نیاز دارد. وضعیت نوبت را پیش از هر وعده بررسی کنید.",
            priority="urgent" if reason == "urgent_concern" else "normal")
        db.add(existing)
    elif reason == "urgent_concern":
        existing.priority, existing.reason = "urgent", reason
    release_holds(db, row)
    row.handoff_status, row.state = "QUEUED", "HANDOFF_PENDING"
    db.add(AuditEvent(tenant_id=row.tenant_id, actor_id="caller:" + row.id, action="call.handoff_requested", entity_type="call", entity_id=row.id, details={"reason": reason}))
    return {"status": "QUEUED", "task_id": existing.id, "reason": reason,
            "phone": row.policy_snapshot.get("phone", ""), "connected": False}


class Conversation:
    def __init__(self, db: Session, row: CallSession, *, tool_spans=None):
        self.db, self.row, self.ctx = db, row, context(row)
        self.service = ReceptionService(db, row.tenant_id, "caller:" + row.id)
        self.tools = ToolGateway(db, row, self.ctx, spans=tool_spans)
        self.providers = list(db.scalars(select(Practitioner).where(Practitioner.tenant_id == row.tenant_id, Practitioner.active.is_(True))))
        self.services = list(db.scalars(select(Service).where(Service.tenant_id == row.tenant_id, Service.active.is_(True))))
        self.result: dict = {"offers": [], "booking": None, "handoff": None}

    def set_reply(self, reply: str, state: str | None = None, **extra) -> dict:
        if state:
            self.row.state = state
        self.ctx["last_reply"] = reply
        self.ctx["state_metadata"] = {"intent": self.row.intent, "policy_version": self.row.policy_version,
            "proof": "verified" if self.ctx.get("verified_phone") else "pending",
            "uncertainty": {"clarification_failures": self.row.failures, "language": self.ctx.get("requested_language", "fa")},
            "pending_tool": self.ctx.get("pending_tool"), "outcome": self.row.state}
        save_context(self.row, self.ctx)
        return {"reply": reply, "state": self.row.state, "capabilities": capabilities(),
                "versions": self.row.policy_snapshot.get("versions", {}), "policy_version": self.row.policy_version,
                "payment_terms": self.ctx.get("payment_terms") if self.row.state == "CONFIRM" else None,
                "conversation_state": self.ctx["state_metadata"],
                "bookings": _bookings_readback(self.db, self.row, self.ctx), **self.result, **extra}

    def partial_readback(self) -> str:
        bookings = _bookings_readback(self.db, self.row, self.ctx)
        if bookings and len(bookings) < self.ctx.get("family_total", 1):
            return " " + _booking_summary(bookings) + " برای نفر بعدی هنوز نوبتی ثبت نشده است."
        return ""

    def handoff(self, reason: str, reply: str | None = None) -> dict:
        self.result["handoff"] = request_handoff(self.db, self.row, reason)
        if self.result["handoff"]["connected"]:
            return {"reply": "", "state": "HUMAN_CONNECTED", "capabilities": capabilities(),
                    "versions": self.row.policy_snapshot.get("versions", {}), "policy_version": self.row.policy_version,
                    "bookings": _bookings_readback(self.db, self.row, self.ctx), **self.result}
        reply = reply or "درخواست کمک از پذیرش ثبت شد؛ هنوز به همکار انسانی وصل نشده‌اید. برای تماس مستقیم می‌توانید از شماره مرکز استفاده کنید."
        return self.set_reply(reply + self.partial_readback())

    def unclear(self, question: str) -> dict:
        self.row.failures += 1
        if self.row.failures >= 2:
            return self.handoff("low_confidence", "برای جلوگیری از ثبت اشتباه، درخواست پیگیری پذیرش ثبت شد. هنوز نوبت جدیدی قطعی نشده است.")
        return self.set_reply(question)

    @staticmethod
    def pick(text: str, items: list, name=lambda x: x.name):
        numeric = normalize_digits(text).strip()
        numbers = {"اول": 1, "اولی": 1, "یک": 1, "دوم": 2, "دومی": 2, "دو": 2, "سوم": 3, "سه": 3}
        index = int(numeric) if numeric.isdigit() else numbers.get(numeric)
        if index is not None and 1 <= index <= len(items):
            return items[index - 1]
        norm = normalize_text(text)
        matches = [x for x in items if normalize_text(name(x)) in norm or (len(norm) >= 3 and norm in normalize_text(name(x)))]
        return matches[0] if len(matches) == 1 else None

    def ask_service(self) -> dict:
        preferred = self.ctx.get("preferred_provider")
        services = [s for s in self.services if not preferred or preferred in s.provider_ids]
        self.ctx["service_options"] = [s.id for s in services]
        if not services:
            return self.handoff("booking_exception", "خدمت فعالی برای این پزشک پیدا نشد؛ پذیرش بررسی می‌کند.")
        return self.set_reply("برای کدام خدمت نوبت می‌خواهید؟ " + "، ".join(f"{i+1}. {s.name}" for i, s in enumerate(services)), "SERVICE")

    def ask_provider(self) -> dict:
        item = next((s for s in self.services if s.id == self.ctx.get("service_id")), None)
        available = [p for p in self.providers if item and p.id in item.provider_ids]
        self.ctx["provider_options"] = [p.id for p in available]
        preferred = self.ctx.pop("preferred_provider", None)
        if preferred and any(p.id == preferred for p in available):
            self.ctx["provider_id"] = preferred
            return self.ask_date()
        if len(available) == 1:
            self.ctx["provider_id"] = available[0].id
            return self.ask_date()
        return self.set_reply("برای کدام پزشک؟ " + "، ".join(f"{i+1}. {p.name}" for i, p in enumerate(available)), "PROVIDER")

    def clear_slot_selection(self):
        release_holds(self.db, self.row)
        for key in ("chosen", "hold_id", "all_offers", "offers", "offer_offset", "date_alternatives",
                    "date_phrase", "pending_date", "payment_terms", "payment_terms_version", "payment_terms_service_id"):
            self.ctx.pop(key, None)
        self.result["offers"] = []

    def change_provider(self, provider) -> dict:
        self.clear_slot_selection()
        self.ctx["provider_id"] = provider.id
        service = next((s for s in self.services if s.id == self.ctx.get("service_id")), None)
        if service and provider.id in service.provider_ids:
            return self.ask_date()
        if self.ctx.get("existing_id"):
            return self.handoff("booking_exception", "پزشک جدید برای خدمت فعلی قابل انتخاب نیست؛ نوبت قبلی تغییری نکرد و پذیرش بررسی می‌کند.")
        self.ctx.pop("service_id", None)
        self.ctx["preferred_provider"] = provider.id
        return self.ask_service()

    def correction(self, norm: str) -> dict | None:
        """Explicit corrections discard incompatible state before reconfirming.

        No input can select a different tenant. A committed patient's details
        require the staff correction workflow, not an accidental new booking.
        """
        target = None
        if self.row.state == "CORRECTION":
            target = {"1": "name", "2": "phone", "3": "service", "4": "provider", "5": "date"}.get(norm)
        explicit = any(word in norm for word in ("اصلاح", "اشتباه", "عوض", "تغییر", "دیگری", "دیگه", "دیگر")) or norm.startswith("نه ")
        if explicit or self.row.state == "CORRECTION":
            if any(word in norm for word in ("پزشک", "دکتر")):
                target = "provider"
            elif any(word in norm for word in ("شماره", "تلفن", "موبایل", "همراه")):
                target = "phone"
            elif any(word in norm for word in ("نام", "اسم")):
                target = "name"
            elif any(word in norm for word in ("خدمت", "ویزیت", "سرویس")):
                target = "service"
            elif any(word in norm for word in ("روز", "تاریخ", "ساعت", "زمان")):
                target = "date"
        if not target and not (explicit and "اطلاعات" in norm) and self.row.state != "CORRECTION":
            return None
        if self.row.intent not in {"book", "reschedule", "cancel"}:
            return None
        if self.row.state in {"COMPLETE", "REMINDER_CONSENT"}:
            return self.handoff("booking_exception", "برای اصلاح اطلاعات نوبت ثبت‌شده، پذیرش باید نتیجه فعلی تقویم را بررسی کند. نوبت دیگری ثبت نشده است.")
        if not target:
            return self.set_reply("کدام مورد اصلاح شود؟ ۱. نام، ۲. شماره همراه، ۳. خدمت، ۴. پزشک، ۵. تاریخ و ساعت.", "CORRECTION")
        self.row.failures = 0
        self.db.add(AuditEvent(tenant_id=self.row.tenant_id, actor_id="caller:" + self.row.id,
            action="call.field_correction_requested", entity_type="call", entity_id=self.row.id, details={"field": target}))
        if target == "phone":
            for key in ("phone", "verified_phone", "challenge_id"):
                self.ctx.pop(key, None)
            self.row.phone_hash = None
            challenges = list(self.db.scalars(select(VerificationChallenge.id).where(
                VerificationChallenge.call_id == self.row.id, VerificationChallenge.tenant_id == self.row.tenant_id)))
            self.db.execute(update(VerificationChallenge).where(VerificationChallenge.id.in_(challenges)).values(expires_at=now_utc()))
            self.db.execute(update(MessageOutbox).where(MessageOutbox.tenant_id == self.row.tenant_id,
                MessageOutbox.dedupe_key.in_(["otp:" + key for key in challenges]),
                MessageOutbox.status.in_({"QUEUED", "FAILED"})).values(status="SUPPRESSED"))
            return self.set_reply("شماره همراه صحیح را وارد کنید؛ شماره جدید باید جداگانه تأیید شود.", "PHONE")
        if target == "name":
            if self.row.intent != "book":
                return self.handoff("booking_exception", "اصلاح نام نوبت موجود باید توسط پذیرش بررسی شود؛ نوبت قبلی تغییری نکرده است.")
            self.ctx.pop("patient_name", None)
            self.ctx["correcting_name"] = True
            return self.set_reply("نام و نام خانوادگی صحیح مراجعه‌کننده را وارد کنید.", "NAME")
        self.clear_slot_selection()
        if target == "provider":
            self.ctx.pop("provider_id", None)
            self.ctx["provider_options"] = [p.id for p in self.providers]
            return self.set_reply("پزشک جدید را انتخاب کنید: " + "، ".join(f"{i+1}. {p.name}" for i, p in enumerate(self.providers)), "CHANGE_PROVIDER")
        if target == "service":
            if self.ctx.get("existing_id"):
                return self.handoff("booking_exception", "تغییر خدمت نوبت موجود نیاز به بررسی پذیرش دارد؛ نوبت قبلی تغییری نکرده است.")
            self.ctx.pop("service_id", None)
            self.ctx.pop("provider_id", None)
            self.ctx.pop("preferred_provider", None)
            return self.ask_service()
        if self.ctx.get("provider_id") and self.ctx.get("service_id"):
            return self.ask_date()
        return self.ask_service()

    def ask_date(self) -> dict:
        self.row.failures = 0
        pending = self.ctx.pop("pending_date", None)
        if pending:
            return self.find_slots(pending)
        return self.set_reply("چه روزی برای شما مناسب است؟ مثلاً فردا یا تاریخ دقیق شمسی را بگویید.", "DATE")

    def find_slots(self, phrase: str) -> dict:
        tenant = self.service.tenant()
        resolved = resolve_persian_datetime(phrase, self.row.started_at, tenant.booking_horizon_days,
            time_windows=self.row.policy_snapshot.get("core_policy", {}).get("time_windows"))
        if not resolved["alternatives"]:
            return self.unclear("روز مورد نظر روشن نیست یا خارج از بازه پذیرش است؛ تاریخ دقیق را بگویید.")
        if resolved["ambiguous"] and len(resolved["alternatives"]) > 1:
            self.ctx["date_alternatives"] = resolved["alternatives"]
            return self.set_reply("کدام تاریخ را منظورتان بود؟ " + "؛ ".join(f"{i+1}. {d['jalali_display']}" for i, d in enumerate(resolved["alternatives"][:7])), "DATE_CHOICE")
        if resolved["time_ambiguous"]:
            self.ctx["date_phrase"] = phrase
            return self.set_reply("ساعت صبح را می‌خواهید یا بعدازظهر؟", "TIME_CLARIFY")
        slots = []
        for day in resolved["alternatives"]:
            candidates = self.tools.call("slots", {"provider_id": self.ctx["provider_id"], "service_id": self.ctx["service_id"], "date": day["local_date"]})
            if isinstance(candidates, dict) and candidates.get("pending_tool"):
                self.ctx["external_resolved"] = resolved
                self.ctx["external_days_remaining"] = [d for d in resolved["alternatives"] if d["local_date"] > day["local_date"]]
                return self.wait_tool(candidates, "slots")
            if resolved["times"]:
                candidates = [s for s in candidates if s["local_time"] in resolved["times"]]
            if resolved["time_window"]:
                lower, upper = resolved["time_window"]
                candidates = [s for s in candidates if lower <= int(s["local_time"].split(":")[0]) + int(s["local_time"].split(":")[1])/60 < upper]
            slots.extend(candidates)
            if len(slots) >= 10:
                break
        if resolved.get("latest"):
            slots = sorted(slots, key=lambda item: item["start_at"], reverse=True)[:2]
        self.ctx["all_offers"] = slots[:40]
        self.ctx["offer_offset"] = 0
        self.row.failures = 0
        return self.offer()

    def wait_tool(self, result, phase):
        self.ctx["pending_tool"] = {**result["pending_tool"], "phase": phase}
        return self.set_reply("درخواست به تقویم معتبر ارسال شد و نتیجه هنوز در حال بررسی است. تا دریافت نتیجه، نوبت یا تغییر آن قطعی اعلام نمی‌شود.", "WAIT_CALENDAR")

    def resume_tool(self):
        from .models_core import ExternalCalendarOperation
        from .calendar_bridge import encode_slot, external_booking
        pending = self.ctx.get("pending_tool", {})
        operation = self.db.scalar(select(ExternalCalendarOperation).where(ExternalCalendarOperation.id == pending.get("id"),
            ExternalCalendarOperation.tenant_id == self.row.tenant_id, ExternalCalendarOperation.call_id == self.row.id))
        if not operation:
            return self.handoff("booking_exception")
        if operation.status in {"PENDING", "SENDING", "UNKNOWN"}:
            return self.set_reply("نتیجه تقویم هنوز روشن نیست؛ درخواست دوباره ثبت نمی‌شود. پذیرش می‌تواند وضعیت همین درخواست را بررسی کند.", "WAIT_CALENDAR")
        if operation.status != "SUCCEEDED":
            return self.handoff("booking_exception", "تقویم بیرونی این درخواست را تایید نکرد؛ پذیرش باید آن را بررسی کند. نوبت تازه‌ای قطعی نشده است.")
        value = json.loads(decrypt(operation.result_encrypted))
        self.ctx.pop("pending_tool", None)
        phase = pending.get("phase")
        if phase == "slots":
            candidates = [item for slot in value["slots"] if (item := encode_slot(self.db, self.row.tenant_id, slot))]
            resolved = self.ctx.get("external_resolved", {})
            if resolved.get("times"):
                candidates = [item for item in candidates if item["local_time"] in resolved["times"]]
            if resolved.get("time_window"):
                lower, upper = resolved["time_window"]
                candidates = [item for item in candidates if lower <= int(item["local_time"][:2]) + int(item["local_time"][3:])/60 < upper]
            if resolved.get("latest"):
                candidates = sorted(candidates, key=lambda item: item["start_at"], reverse=True)[:2]
            if not candidates and self.ctx.get("external_days_remaining"):
                day = self.ctx["external_days_remaining"].pop(0)
                result = self.tools.call("slots", {"provider_id": self.ctx["provider_id"], "service_id": self.ctx["service_id"], "date": day["local_date"]})
                return self.wait_tool(result, "slots")
            self.ctx.update(all_offers=candidates[:40], offer_offset=0)
            return self.offer()
        if phase == "hold":
            expiry = datetime.fromisoformat(str(value.get("expires_at", "")).replace("Z", "+00:00"))
            if expiry.tzinfo is None or expiry <= now_utc() or not isinstance(value.get("id"), str):
                return self.handoff("booking_exception")
            self.ctx["hold_id"] = value["id"]
            self.ctx["external_hold"] = True
            if self.row.intent == "reschedule" or self.ctx.get("patient_name") and self.ctx.get("verified_phone"):
                return self.confirmation()
            return self.set_reply("این نوبت به نام چه کسی باشد؟ نام و نام خانوادگی مراجعه‌کننده را وارد کنید.", "NAME")
        result = external_booking(self.db, self.row.tenant_id, value, patient_name=self.ctx.get("patient_name"))
        if phase == "existing":
            self.ctx.update(existing_id=result["id"], existing_version=result["version"], provider_id=result["provider_id"], service_id=result["service_id"])
            if self.row.intent == "cancel":
                return self.set_reply(f"لغو نوبت {result['jalali_display']} با کد {result['reference']} را تأیید می‌کنید؟", "CANCEL_CONFIRM")
            return self.ask_date()
        self.result["booking"] = result
        self.ctx["external_booking_operation"] = operation.id
        self.ctx["last_booking_id"] = result["id"]
        self.ctx.pop("hold_id", None)
        self.ctx.pop("external_hold", None)
        status = BOOKING_STATUS_LABELS.get(result["status"], "نیازمند بررسی")
        return self.set_reply(f"تقویم بیرونی نتیجه را بازخوانی کرد. درخواست با کد {result['reference']} در وضعیت {status} است. {result['jalali_display']}", "COMPLETE")

    def offer(self) -> dict:
        offset = self.ctx.get("offer_offset", 0)
        offers = self.ctx.get("all_offers", [])[offset:offset+2]
        if not offers:
            return self.set_reply("در این بازه وقت آزادی پیدا نشد. روز دیگری را بگویید یا از پذیرش کمک بگیرید.", "DATE")
        self.ctx["offers"] = offers
        self.result["offers"] = offers
        return self.set_reply("این زمان‌ها در تقویم آزادند: " + "؛ ".join(f"{i+1}. {s['display']}" for i, s in enumerate(offers)) + " . کدام مناسب است؟", "OFFER")

    def otp(self, phone: str) -> dict:
        recent = self.db.scalar(select(func.count()).select_from(VerificationChallenge).where(VerificationChallenge.call_id == self.row.id, VerificationChallenge.created_at > now_utc() - timedelta(minutes=10)))
        if recent >= 3:
            return self.handoff("low_confidence", "تعداد تلاش‌های تأیید شماره به سقف رسید. درخواست پیگیری پذیرش ثبت شد.")
        if not settings.demo_mode and not KavenegarSMS().configured:
            return self.handoff("service_failure", "تأیید شماره در حال حاضر در دسترس نیست؛ درخواست پیگیری پذیرش ثبت شد.")
        # Session creation cannot reset the clinic/subject allowance. This call
        # uses _TurnTransaction, so counters, challenge, outbox and receipt either
        # commit together or roll back together under the tenant/turn fence.
        rate_limit(self.db, "otp-tenant:" + self.row.tenant_id + ":" + hash_phone(phone), 3, 600)
        rate_limit(self.db, "otp:" + hash_phone(phone), 5, 3600)
        code = "246810" if settings.demo_mode else f"{secrets.randbelow(1_000_000):06d}"
        challenge = VerificationChallenge(id=uid(), tenant_id=self.row.tenant_id, call_id=self.row.id,
            phone_hash=hash_phone(phone), phone_encrypted=encrypt(phone), code_hash=digest(self.row.id + ":" + code),
            expires_at=now_utc() + timedelta(minutes=5))
        self.db.add(challenge)
        self.db.add(MessageOutbox(tenant_id=self.row.tenant_id, recipient_encrypted=encrypt(phone),
            purpose="verification", template="otp_v1", payload={"secret": encrypt(json.dumps({"code": code}))},
            dedupe_key="otp:" + challenge.id))
        self.ctx["challenge_id"], self.ctx["phone"] = challenge.id, phone
        self.row.phone_hash = hash_phone(phone)
        self.db.commit()
        return self.set_reply("کد تأیید شماره همراه را وارد کنید." + (" در محیط آزمایشی کد ۲۴۶۸۱۰ است؛ پیامکی ارسال نمی‌شود." if settings.demo_mode else " ارسال پیامک در صف قرار گرفت."),
            "VERIFY", **({"demo_otp": code} if settings.demo_mode else {}))

    def verify(self, text: str) -> dict:
        challenge = self.db.scalar(select(VerificationChallenge).where(VerificationChallenge.id == self.ctx.get("challenge_id"), VerificationChallenge.call_id == self.row.id, VerificationChallenge.tenant_id == self.row.tenant_id).with_for_update())
        if not challenge or challenge.expires_at <= now_utc() or challenge.attempts >= 5:
            return self.handoff("low_confidence", "مهلت یا تعداد تلاش تأیید تمام شده است. پذیرش درخواست را بررسی می‌کند.")
        challenge.attempts += 1
        code = normalize_digits(text).replace(" ", "")
        if not re.fullmatch(r"\d{6}", code) or not hmac.compare_digest(challenge.code_hash, digest(self.row.id + ":" + code)):
            return self.set_reply("کد تأیید درست نیست. دوباره آن را وارد کنید.")
        challenge.verified_at = now_utc()
        self.ctx["verified_phone"] = challenge.phone_hash
        self.row.failures = 0
        if self.ctx.pop("sms_pending", False):
            self.ctx.update(sms_enabled=True, sms_subject=challenge.phone_hash, sms_phone=decrypt(challenge.phone_encrypted))
            self.db.add(ConsentGrant(tenant_id=self.row.tenant_id, subject_hash=challenge.phone_hash, purpose="conversation_sms",
                granted=True, policy_version=str(self.row.policy_version), expires_at=self.row.expires_at,
                evidence={"call_id": self.row.id, "source": "explicit_sms_enrollment_and_otp"}))
            return self.set_reply(f"شماره شما تایید شد. ادامه همین گفت‌وگو با پیامک مجاز است؛ پیام را به {self.ctx['sms_receiver']} بفرستید. این انتخاب رضایت تبلیغاتی نیست.", self.ctx.pop("sms_return_state", "INTENT"))
        return self.verified_reference(challenge.phone_hash) if self.row.intent in {"cancel", "reschedule"} else self.confirmation()

    def verified_reference(self, subject):
        if self.row.intent in {"cancel", "reschedule"}:
            from .calendar_bridge import is_external, queue_operation
            if is_external(self.db, self.row.tenant_id):
                from .models_core import ExternalCalendarOperation
                candidates = self.db.scalars(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == self.row.tenant_id,
                    ExternalCalendarOperation.phone_hash == subject, ExternalCalendarOperation.operation == "create", ExternalCalendarOperation.status == "SUCCEEDED")
                    .order_by(ExternalCalendarOperation.created_at.desc()).limit(200))
                found = [item for item in candidates if json.loads(decrypt(item.result_encrypted)).get("reference", "").casefold() == self.ctx.get("reference", "").casefold()]
                if len(found) != 1:
                    return self.handoff("booking_exception", "نوبت با کد و شماره تاییدشده پیدا نشد؛ پذیرش بررسی می‌کند.")
                operation = queue_operation(self.db, self.row.tenant_id, "get", {"remote_id": found[0].remote_id, "patient_token": subject},
                    "voice-lookup:" + self.row.id + ":" + str(self.row.turn_count), "caller:" + self.row.id, call_id=self.row.id, phone_hash=subject)
                return self.wait_tool({"pending_tool": {"id": operation.id, "operation": "get", "status": operation.status}}, "existing")
            booking = self.db.scalar(select(Appointment).where(Appointment.tenant_id == self.row.tenant_id, Appointment.reference == self.ctx.get("reference"), Appointment.phone_hash == subject))
            if not booking:
                return self.handoff("booking_exception", "نوبتی با این کد و شماره تأییدشده پیدا نشد؛ پذیرش بررسی می‌کند.")
            self.ctx.update({"existing_id": booking.id, "existing_version": booking.version,
                             "provider_id": booking.provider_id, "service_id": booking.service_id})
            info = self.service.appointment_dict(booking)
            if self.row.intent == "cancel":
                return self.set_reply(f"لغو نوبت {info['jalali_display']} با کد {info['reference']} را تأیید می‌کنید؟", "CANCEL_CONFIRM")
            return self.ask_date()
        return self.confirmation()

    def confirmation(self) -> dict:
        chosen = self.ctx.get("chosen")
        if not chosen:
            return self.ask_date()
        if self.row.intent == "reschedule":
            return self.set_reply(f"جابه‌جایی نوبت به {chosen['display']} را تأیید می‌کنید؟", "CONFIRM")
        provider = next((p.name for p in self.providers if p.id == self.ctx.get("provider_id")), "")
        service = next((s for s in self.services if s.id == self.ctx.get("service_id")), None)
        if service is None:
            return self.handoff("booking_exception")
        from .core_policy import service_policy
        rules = service_policy(self.db, self.row.tenant_id, service.id, checked=True)
        preparation = ("آمادگی اعلام‌شده مرکز: " + rules["preparation"] + " ") if rules["preparation"] else ""
        insurance = ("اطلاعات بیمه اعلام‌شده مرکز: " + rules["insurance_notes"] + " ") if rules["insurance_notes"] else ""
        question = preparation + insurance + f"نوبت {service.name} با {provider}، {chosen['display']} به نام {self.ctx.get('patient_name', '')}"
        if service.deposit_toman:
            from .payment_policy import public_payment_policy
            terms = public_payment_policy(self.db, self.row.tenant_id)
            if not terms.get("enabled") or terms.get("currency") != "TOMAN":
                return self.handoff("billing_exception", "شرایط معتبر بیعانه این مرکز در دسترس نیست؛ هنوز نوبتی ثبت نشده و پذیرش بررسی می‌کند.")
            terms = {**terms, "deposit_toman": service.deposit_toman}
            explanation = (f"بیعانه {service.deposit_toman:,} تومان است. پس از ثبت، این درخواست حداکثر {terms['hold_minutes']} دقیقه و فقط تا پیش از شروع نوبت منتظر پرداخت می‌ماند؛ تا تأیید پرداخت قطعی نیست. "
                f"شرایط بیعانه: {terms['deposit_terms']} شرایط لغو: {terms['cancellation_terms']} شرایط بازپرداخت: {terms['refund_terms']} ")
            reply = explanation + question + " با قبول مبلغ و همه شرایط گفته‌شده ثبت شود؟ برای تأیید بله بگویید."
            # The speech adapter has a 2,000-character input bound. Never ask
            # for agreement to terms that would be silently cut off in speech.
            from .locale import spoken_administrative
            if len(spoken_administrative(reply)) > 1900:
                return self.handoff("billing_exception", "توضیح کامل شرایط بیعانه نیاز به بررسی با پذیرش دارد؛ هنوز نوبتی ثبت نشده است.")
            self.ctx.update(payment_terms=terms, payment_terms_version=terms["version"], payment_terms_service_id=service.id)
            return self.set_reply(reply, "CONFIRM", payment_terms=terms)
        for key in ("payment_terms", "payment_terms_version", "payment_terms_service_id"):
            self.ctx.pop(key, None)
        return self.set_reply(question + " ثبت شود؟ برای ثبت، بله بگویید.", "CONFIRM")

    def commit(self) -> dict:
        chosen = self.ctx.get("chosen")
        if not chosen or self.ctx.get("verified_phone") != hash_phone(self.ctx.get("phone", "")):
            return self.handoff("booking_exception")
        if self.row.intent == "reschedule":
            if self.row.policy_snapshot.get("mode") == "supervised":
                return self.review_change("reschedule")
            # Destination occupancy is claimed atomically with releasing the old slot.
            release_holds(self.db, self.row)
            self.db.commit()
            result = self.tools.call("reschedule", {"appointment_id": self.ctx["existing_id"], "slot_id": chosen["slot_id"],
                "idempotency_key": "voice-move:" + self.row.id + ":" + str(self.ctx["existing_version"]), "version": self.ctx["existing_version"]})
        else:
            service = next((s for s in self.services if s.id == self.ctx.get("service_id")), None)
            if service is None:
                return self.handoff("booking_exception")
            if service.deposit_toman:
                from .payment_policy import public_payment_policy
                current_terms = {**public_payment_policy(self.db, self.row.tenant_id), "deposit_toman": service.deposit_toman}
                if self.ctx.get("payment_terms_service_id") != service.id or self.ctx.get("payment_terms") != current_terms:
                    # A caller's yes applies only to the terms actually shown.
                    # Publish changes before any booking and obtain a new yes.
                    return self.confirmation()
            result = self.tools.call("book", {"slot_id": chosen["slot_id"], "patient_name": self.ctx["patient_name"], "phone": self.ctx["phone"],
                "idempotency_key": "voice-book:" + self.row.id + ":" + str(self.ctx.get("booking_cycle", 0)) + ":" + str(self.ctx.get("family_remaining", 1)),
                "confirmed": True, "hold_id": self.ctx.get("hold_id"), "session_id": self.row.id,
                "reminder_opt_in": self.ctx.get("reminder_opt_in", False),
                "payment_terms_version": self.ctx.get("payment_terms_version") if service.deposit_toman else None,
                "payment_terms_accepted": bool(service.deposit_toman)})
        if result.get("pending_tool"):
            return self.wait_tool(result, "booking")
        # Refresh persisted source-of-truth state even on replay.
        result = self.service.appointment_dict(self.service.get_appointment(result["id"]))
        self.result["booking"] = result
        self.ctx["last_booking_id"] = result["id"]
        self.ctx["booking_ids"] = list(dict.fromkeys([*self.ctx.get("booking_ids", []), result["id"]]))[-2:]
        self.ctx.pop("hold_id", None)
        if result["status"] == "CONFIRMED":
            phrase = f"نوبت ثبت و در تقویم تأیید شد. {result['jalali_display']}، کد پیگیری {result['reference']}. وضعیت ارسال پیامک جداگانه پیگیری می‌شود."
        elif result["status"] == "PENDING_PAYMENT":
            expiry = result.get("payment_expires_at")
            until = datetime.fromisoformat(expiry).astimezone(ZoneInfo(self.row.policy_snapshot["timezone"])).strftime("%H:%M") if expiry else None
            phrase = f"درخواست با کد {result['reference']} تا پرداخت بیعانه موقت است و هنوز قطعی نیست."
            if until:
                phrase += f" مهلت پرداخت به وقت مرکز ساعت {until} است."
        else:
            phrase = f"درخواست با کد {result['reference']} ثبت شد؛ وضعیت فعلی {result['status']} است و تأیید نهایی نیاز به پیگیری دارد."
        if self.ctx.get("family_remaining", 1) > 1:
            self.ctx["family_remaining"] -= 1
            for key in ("patient_name", "chosen", "verified_phone", "hold_id", "phone", "challenge_id",
                        "payment_terms", "payment_terms_version", "payment_terms_service_id"):
                self.ctx.pop(key, None)
            self.row.phone_hash = None
            return self.set_reply(phrase + " برای نفر بعدی، روز مورد نظر را بگویید؛ نوبت ایشان جداگانه تأیید خواهد شد.", "DATE")
        return self.set_reply(phrase + " آیا یادآوری نوبت با پیامک را می‌خواهید؟", "REMINDER_CONSENT")

    def review_change(self, action: str) -> dict:
        result = self.handoff("booking_exception", "درخواست تغییر برای بررسی پذیرش ثبت شد. نوبت قبلی هنوز تغییری نکرده و تغییر فقط پس از بررسی کارکنان انجام می‌شود.")
        task = self.db.get(StaffTask, result["handoff"]["task_id"])
        task.appointment_id = self.ctx.get("existing_id")
        task.summary = "درخواست تأییدشده تماس‌گیرنده برای " + ("لغو" if action == "cancel" else "جابه‌جایی")
        if action == "reschedule" and self.ctx.get("chosen"):
            task.summary += " به " + self.ctx["chosen"]["display"]
        return result

    def answer(self, text: str) -> dict:
        if self.row.state == "HUMAN_CONNECTED" or self.row.handoff_status == "CONNECTED":
            fail(409, "HUMAN_CONNECTED", "همکار انسانی به تماس وصل است؛ دستیار خودکار متوقف شده است.")
        norm = normalize_text(text)
        if any(word in norm for word in URGENT):
            return self.handoff("urgent_concern", "من فقط برای کارهای پذیرش کمک می‌کنم و وضعیت پزشکی را تشخیص نمی‌دهم. اگر احتمال خطر فوری وجود دارد، بدون منتظر ماندن برای پذیرش با خدمات اورژانس محل خود تماس بگیرید. درخواست کمک انسانی هم ثبت شد.")
        from .locale import language_signal
        language = language_signal(norm)
        if language["requires_clarification"]:
            self.ctx["language_signal"] = language
            return self.handoff("unsupported_language", "بخشی از پیام به زبان دیگری بود. برای جلوگیری از برداشت نادرست، درخواست کمک انسانی ثبت شد؛ هنوز اتصال برقرار نشده است.")
        requested_language = _requested_language(norm) or (language["language"] if language["language"] in {"english", "arabic"} else None)
        if requested_language:
            self.ctx["requested_language"] = requested_language
            label = "انگلیسی" if requested_language == "english" else "عربی"
            from .routing import language_route
            approved = language_route(self.row.policy_snapshot.get("routing", {}), requested_language)
            reply = approved["script"] if approved else f"این دستیار فقط برای گفت‌وگوی فارسی آماده است. درخواست زبان {label} برای پذیرش انسانی ثبت شد؛ هنوز اتصال برقرار نشده و توانایی زبان همکار باید بررسی شود."
            if approved:
                self.ctx["handoff_queue"] = approved["queue_id"]
            result = self.handoff("unsupported_language", reply)
            result["handoff"]["queue_id"] = approved["queue_id"] if approved else None
            result["handoff"]["language_qualification"] = "operator_attested" if approved else "unverified"
            task_id = result.get("handoff", {}).get("task_id")
            if task_id:
                self.db.get(StaffTask, task_id).summary = f"تماس‌گیرنده گفت‌وگو به زبان {label} می‌خواهد؛ پیش از تماس توانایی زبان همکار بررسی شود."
            return result
        if any(word in norm for word in HUMAN):
            return self.handoff("human_requested")
        if self.row.state == "HANDOFF_PENDING":
            return self.set_reply("درخواست شما در صف پذیرش است؛ هنوز اتصال انسانی برقرار نشده است. شماره تماس مستقیم مرکز در همین صفحه قرار دارد.", handoff={"status": self.row.handoff_status, "connected": self.row.handoff_status == "CONNECTED"})
        if any(word in norm for word in ("آرام تر", "آروم تر", "آهسته", "slower")):
            self.ctx["slow"] = True
            return self.set_reply(self.ctx.get("last_reply", GREETING))
        if norm in {"تکرار", "دوباره بگو", "repeat"}:
            return self.set_reply(self.ctx.get("last_reply", GREETING), offers=self.ctx.get("offers", []))
        if any(word in norm for word in ("پاک کردن اطلاعات", "حذف اطلاعات", "حریم خصوصی")):
            return self.handoff("privacy_request", "درخواست مربوط به حریم خصوصی برای مسئول مرکز ثبت شد. ضبط صدا و استفاده آموزشی در این گفت‌وگو غیرفعال است.")
        if any(word in norm for word in ("تشخیص", "چه دارویی", "دوز", "درمان کنم", "نسخه بده")):
            return self.handoff("booking_exception", "من مشاوره، تشخیص یا نسخه پزشکی ارائه نمی‌کنم. برای راهنمایی تخصصی درخواست ارتباط با کارکنان مرکز ثبت شد.")
        if self.row.state == "WAIT_CALENDAR":
            return self.resume_tool()
        correction = self.correction(norm)
        if correction is not None:
            return correction
        if self.row.state in {"INTENT", "COMPLETE"}:
            if "لغو" in norm or "کنسل" in norm:
                self.row.intent = "cancel"
                return self.set_reply("کد پیگیری نوبت را وارد کنید. پس از تأیید شماره همراه، درخواست لغو بررسی می‌شود.", "REFERENCE")
            if any(w in norm for w in ("جابه", "جابجا", "تغییر نوبت", "تغییر وقت")):
                self.row.intent = "reschedule"
                return self.set_reply("کد پیگیری نوبت را وارد کنید.", "REFERENCE")
            matches = []
            for fact in self.row.policy_snapshot.get("faq", []):
                keywords = fact.get("keywords") or [fact.get("question", "")]
                if any(normalize_text(k) and normalize_text(k) in norm for k in keywords):
                    matches.append(fact)
            if matches:
                valid = [fact for fact in matches if _approved_fact(fact, now_utc())]
                if len({normalize_text(fact["answer"]) for fact in valid}) > 1:
                    return self.handoff("faq_conflict", "اطلاعات تأییدشده مرکز برای این پرسش با هم سازگار نیست؛ پذیرش باید پاسخ درست را بررسی کند.")
                return self.set_reply(valid[0]["answer"]) if valid else self.handoff("booking_exception", "اطلاعات تأییدشده و به‌روز برای این پرسش ندارم؛ پذیرش بررسی می‌کند.")
            if "آدرس" in norm or "نشانی" in norm:
                return self.handoff("booking_exception", "نشانی با منبع تأییدشده و به‌روز برای پاسخ‌گویی ثبت نشده است؛ پذیرش بررسی می‌کند.")
            if any(w in norm for w in ("نوبت", "وقت", "رزرو", "book")):
                self.row.intent = "book"
                self.clear_slot_selection()
                for key in ("existing_id", "existing_version", "reference", "patient_name", "verified_phone",
                            "phone", "challenge_id", "provider_id", "service_id", "preferred_provider"):
                    self.ctx.pop(key, None)
                self.ctx["booking_cycle"] = self.ctx.get("booking_cycle", 0) + 1
                self.ctx["family_remaining"] = 2 if "دو نفر" in norm or "2 نفر" in norm else 1
                self.ctx["family_total"] = self.ctx["family_remaining"]
                self.ctx["booking_ids"] = []
                parsed = resolve_persian_datetime(norm, self.row.started_at)
                if parsed["alternatives"]:
                    self.ctx["pending_date"] = norm
                picked = self.pick(norm, self.services)
                if picked:
                    self.ctx["service_id"] = picked.id
                    return self.ask_provider()
                return self.ask_service()
            return self.set_reply("می‌تونم برای ثبت، جابه‌جایی یا لغو نوبت و پرسش‌های پذیرش کمک کنم. چه کاری می‌خواهید؟")
        if self.row.state == "REFERENCE":
            from .calendar_bridge import is_external
            external = is_external(self.db, self.row.tenant_id)
            match = re.fullmatch(r"[A-Za-z0-9_-]{3,100}", norm) if external else re.search(r"B-[A-Fa-f0-9]{8}", norm, re.I)
            if not match:
                return self.unclear("کد کامل پیگیری را با حروف و اعداد آن وارد کنید." if external else "کد پیگیری با B- شروع می‌شود. لطفاً کد کامل را وارد کنید.")
            self.ctx["reference"] = match[0].upper()
            if self.ctx.get("sms_enabled") and self.ctx.get("sms_subject") == self.ctx.get("verified_phone"):
                return self.verified_reference(self.ctx["sms_subject"])
            return self.set_reply("شماره همراه ثبت‌شده برای این نوبت را وارد کنید.", "PHONE")
        if self.row.state == "SERVICE":
            picked = self.pick(norm, [s for s in self.services if s.id in self.ctx.get("service_options", [s.id for s in self.services])])
            if not picked:
                return self.unclear("نام یا شماره یکی از خدمت‌های گفته‌شده را انتخاب کنید.")
            self.ctx["service_id"] = picked.id
            self.row.failures = 0
            return self.ask_provider()
        if self.row.state == "CHANGE_PROVIDER":
            picked = self.pick(norm, [p for p in self.providers if p.id in self.ctx.get("provider_options", [])])
            if not picked:
                return self.unclear("نام یا شماره پزشک جدید را از همین مرکز انتخاب کنید.")
            return self.change_provider(picked)
        if self.row.state == "PROVIDER":
            picked = self.pick(norm, [p for p in self.providers if p.id in self.ctx.get("provider_options", [])])
            if not picked:
                return self.unclear("نام یا شماره پزشک مورد نظر را از گزینه‌ها انتخاب کنید.")
            self.ctx["provider_id"] = picked.id
            return self.ask_date()
        if self.row.state == "DATE":
            return self.find_slots(norm)
        if self.row.state == "DATE_CHOICE":
            picked = self.pick(norm, self.ctx["date_alternatives"], lambda x: x["jalali_display"])
            if not picked:
                return self.unclear("شماره یکی از تاریخ‌های گفته‌شده را انتخاب کنید.")
            return self.find_slots(picked["local_date"])
        if self.row.state == "TIME_CLARIFY":
            if not any(w in norm for w in ("صبح", "عصر", "بعدازظهر", "بعد از ظهر", "شب")):
                return self.unclear("صبح یا بعدازظهر؟")
            return self.find_slots(self.ctx.get("date_phrase", "") + " " + norm)
        if self.row.state == "OFFER":
            if "بیشتر" in norm or "بعدی" in norm:
                self.ctx["offer_offset"] = self.ctx.get("offer_offset", 0) + 2
                return self.offer()
            selected = self.pick(norm, self.ctx.get("offers", []), lambda x: x["local_time"])
            if not selected:
                parsed = resolve_persian_datetime(norm, self.row.started_at)
                return self.find_slots(norm) if parsed["alternatives"] else self.unclear("گزینه یک یا دو را انتخاب کنید، یا روز دیگری بگویید.")
            hold = self.tools.call("hold", {"slot_id": selected["slot_id"], "session_id": self.row.id})
            self.ctx["chosen"] = selected
            if hold.get("pending_tool"):
                return self.wait_tool(hold, "hold")
            self.ctx["hold_id"] = hold["id"]
            self.row.failures = 0
            if self.row.intent == "reschedule":
                return self.confirmation()
            if self.ctx.get("patient_name") and self.ctx.get("phone") and self.ctx.get("verified_phone") == hash_phone(self.ctx["phone"]):
                return self.confirmation()
            return self.set_reply("این نوبت به نام چه کسی باشد؟ نام و نام خانوادگی همان مراجعه‌کننده را وارد کنید.", "NAME")
        if self.row.state == "NAME":
            if not 2 <= len(norm) <= 120 or re.search(r"[<>\d]", norm):
                return self.unclear("نام و نام خانوادگی مراجعه‌کننده را بنویسید.")
            self.ctx["patient_name"] = norm
            if self.ctx.get("sms_enabled") and self.ctx.get("sms_subject") == self.ctx.get("verified_phone"):
                return self.confirmation()
            if self.ctx.pop("correcting_name", False) and self.ctx.get("chosen") and self.ctx.get("phone") and self.ctx.get("verified_phone") == hash_phone(self.ctx["phone"]):
                return self.confirmation()
            return self.set_reply("شماره همراه را برای تأیید و دریافت نتیجه وارد کنید.", "PHONE")
        if self.row.state == "PHONE":
            try:
                phone = normalize_phone(norm)
            except ValueError:
                return self.unclear("شماره همراه ۱۱ رقمی را با ۰۹ وارد کنید.")
            if self.ctx.get("sms_enabled") and self.ctx.get("sms_subject") != hash_phone(phone):
                return self.handoff("booking_exception", "ادامه پیامکی فقط با همان شماره تاییدشده مجاز است؛ تغییر شماره به تایید مستقل پذیرش نیاز دارد.")
            return self.otp(phone)
        if self.row.state == "VERIFY":
            return self.verify(norm)
        if self.row.state == "CANCEL_CONFIRM":
            if norm in YES:
                if self.row.policy_snapshot.get("mode") == "supervised":
                    return self.review_change("cancel")
                result = self.tools.call("cancel", {"appointment_id": self.ctx["existing_id"], "idempotency_key": "voice-cancel:" + self.row.id,
                    "version": self.ctx["existing_version"], "reason": "caller_request"})
                if result.get("pending_tool"):
                    return self.wait_tool(result, "booking")
                self.result["booking"] = result
                return self.set_reply(f"نوبت با کد {result['reference']} در تقویم لغو شد.", "COMPLETE")
            if norm in NO:
                return self.set_reply("نوبت شما تغییری نکرد.", "COMPLETE")
            return self.unclear("لغو نوبت را تأیید می‌کنید؟ بله یا خیر.")
        if self.row.state == "CONFIRM":
            if norm in YES:
                return self.commit()
            if norm in NO:
                release_holds(self.db, self.row)
                self.ctx.pop("hold_id", None)
                return self.set_reply("هنوز نوبتی ثبت نشده است. روز دیگری را بگویید.", "DATE")
            return self.unclear("ثبت همین نوبت با اطلاعات گفته‌شده را تأیید می‌کنید؟ بله یا خیر.")
        if self.row.state == "REMINDER_CONSENT":
            if norm not in YES | NO:
                return self.unclear("یادآوری پیامکی می‌خواهید؟ بله یا خیر.")
            booking = self.service.get_appointment(self.ctx["last_booking_id"])
            booking.reminder_opt_in = norm in YES
            self.db.add(ConsentGrant(tenant_id=self.row.tenant_id, subject_hash=booking.phone_hash, purpose="reminders",
                granted=norm in YES, policy_version=str(self.row.policy_version), evidence={"call_id": self.row.id, "appointment_id": booking.id}))
            return self.set_reply("انتخاب شما ثبت شد. روز خوبی داشته باشید.", "COMPLETE")
        return self.handoff("service_failure")


class _TurnTransaction:
    """Compose existing calendar methods into one atomic conversation turn.

    Calendar methods are also used independently by staff HTTP requests. Their
    commit boundary becomes a flush here, so calendar changes, response/context,
    consent, outbox and the turn receipt either all commit or all roll back.
    """
    def __init__(self, db: Session):
        self.db = db

    def commit(self):
        self.db.flush()

    def __getattr__(self, name):
        return getattr(self.db, name)


def _replay_turn(db: Session, row: CallSession, request_id: str, request_hash: str) -> dict | None:
    existing = db.scalar(select(VoiceTurn).where(VoiceTurn.call_id == row.id,
        VoiceTurn.tenant_id == row.tenant_id, VoiceTurn.request_id == request_id))
    if existing:
        if existing.request_hash != request_hash:
            fail(409, "TURN_REPLAY_MISMATCH", "شناسه درخواست با متن دیگری استفاده شده است.")
        result = json.loads(decrypt(existing.result_encrypted))
        if result.get("booking"):
            service = ReceptionService(db, row.tenant_id, "caller:" + row.id)
            booking_record = service.get_appointment(result["booking"]["id"])
            db.refresh(booking_record)
            booking = service.appointment_dict(booking_record)
            if (booking["status"], booking["version"]) != (result["booking"]["status"], result["booking"]["version"]):
                status = BOOKING_STATUS_LABELS.get(booking["status"], booking["status"])
                result["reply"] = f"وضعیت فعلی نوبت با کد {booking['reference']}، {status} است. {booking['jalali_display']}"
            result["booking"] = booking
        if result["state"] != row.state:
            result["offers"] = []
        result["state"] = row.state
        result["bookings"] = _bookings_readback(db, row, context(row))
        result["versions"] = row.policy_snapshot.get("versions", {})
        return result
    return None


def _claim_turn(db: Session, row: CallSession) -> str:
    ensure_ai_allowed(db, row)
    lease = secrets.token_hex(24)
    updated = db.execute(update(CallSession).where(CallSession.id == row.id, CallSession.ended_at.is_(None),
        CallSession.expires_at > now_utc(), CallSession.state != "HUMAN_CONNECTED",
        or_(CallSession.lease_until.is_(None), CallSession.lease_until < now_utc())).values(lease_token=lease, lease_until=now_utc() + timedelta(seconds=45)))
    db.commit()
    if updated.rowcount != 1:
        fail(409, "TURN_IN_PROGRESS", "در حال بررسی پیام قبلی هستم؛ کمی صبر کنید.")
    return lease


def _lock_turn(db: Session, row: CallSession, lease: str) -> None:
    # Keep this write lock until the actual turn transaction commits. Expiry can
    # never permit an old worker to overwrite a newer lease or staff takeover.
    # Shared ordering with calendar expiry, disruption and privacy: tenant first.
    db.execute(update(Tenant).where(Tenant.id == row.tenant_id).values(settings_version=Tenant.settings_version))
    locked = db.execute(update(CallSession).where(CallSession.id == row.id,
        CallSession.lease_token == lease, CallSession.lease_until > now_utc(),
        CallSession.ended_at.is_(None), CallSession.expires_at > now_utc())
        .values(lease_token=lease))
    if locked.rowcount != 1:
        db.rollback()
        fail(409, "TURN_LEASE_LOST", "این درخواست دیگر فعال نیست؛ وضعیت گفت‌وگو را دوباره دریافت کنید.")
    ensure_ai_allowed(db, row)


def _release_turn(db: Session, row_id: str, lease: str) -> None:
    db.rollback()
    db.execute(update(CallSession).where(CallSession.id == row_id, CallSession.lease_token == lease)
               .values(lease_token=None, lease_until=None))
    db.commit()


def execute_turn(db: Session, row: CallSession, body: TurnInput, *, request_hash: str | None = None,
                 lease: str | None = None, transcript: str | None = None) -> dict:
    request_hash = request_hash or digest(body.text)
    ensure_ai_allowed(db, row)
    replay = _replay_turn(db, row, body.request_id, request_hash)
    if replay:
        if lease:
            _release_turn(db, row.id, lease)
        return replay
    lease = lease or _claim_turn(db, row)
    started = time.perf_counter()
    row_id = row.id
    tool_spans, spans_committed = [], False
    try:
        _lock_turn(db, row, lease)
        replay = _replay_turn(db, row, body.request_id, request_hash)
        if replay:
            return replay
        if row.turn_count >= 80:
            fail(429, "TURN_LIMIT", "گفت‌وگو طولانی شده است؛ از پذیرش کمک بگیرید.")
        conversation = Conversation(_TurnTransaction(db), row, tool_spans=tool_spans)
        try:
            result = conversation.answer(body.text)
        except HTTPException as exc:
            for span in tool_spans:
                span["rolled_back"] = True
            db.rollback()
            _lock_turn(db, row, lease)
            conversation = Conversation(_TurnTransaction(db), row, tool_spans=tool_spans)
            code = exc.detail.get("code", "") if isinstance(exc.detail, dict) else ""
            if code in {"SLOT_TAKEN", "INVALID_HOLD", "STALE_SLOT", "STALE_POLICY"}:
                release_holds(db, row)
                result = conversation.set_reply("این زمان دیگر قابل ثبت نیست؛ نوبت جدیدی قطعی نشده است. روز دیگری را انتخاب کنید." + conversation.partial_readback(), "DATE")
            else:
                result = conversation.handoff("booking_exception", SAFE_FAILURE)
        if transcript is not None:
            result["transcript"] = transcript
        if row.expires_at <= now_utc():
            fail(410, "SESSION_EXPIRED", "مهلت گفت‌وگو پایان یافته است؛ نوبت تازه‌ای ثبت نشده است.")
        _check_media_authority(db, row)
        result["turn_id"] = uid()
        row.turn_count += 1
        row.lease_token, row.lease_until = None, None
        db.add(VoiceTurn(id=result["turn_id"], tenant_id=row.tenant_id, call_id=row.id,
            request_id=body.request_id, request_hash=request_hash, result_encrypted=encrypt(json.dumps(result, ensure_ascii=False)),
            latency_ms=int((time.perf_counter() - started) * 1000)))
        db.add(UsageEvent(tenant_id=row.tenant_id, call_id=row.id, kind="conversation_turn", quantity=1, unit="turn", cost_toman=0))
        db.flush()
        turn_trace = append_trace(db, row.tenant_id, "turn:" + result["turn_id"], "conversation.turn_completed", call_id=row.id, turn_id=result["turn_id"],
            versions=row.policy_snapshot.get("versions", {}), attributes={"status": row.state, "duration_ms": int((time.perf_counter()-started)*1000)})
        persist_tool_spans(db, row, tool_spans, turn_id=result["turn_id"], parent_id=turn_trace.id)
        db.commit()
        spans_committed = True
        return result
    finally:
        _release_turn(db, row_id, lease)
        if tool_spans and not spans_committed:
            # A failed turn has no receipt to attach to. After rollback/release,
            # retain only its metadata; never commit its calendar side effects.
            try:
                persist_tool_spans(db, row, tool_spans, attempt_id=str(uuid4()), rolled_back=True)
                db.commit()
            except Exception:
                db.rollback()
                logging.getLogger("receptionist").warning("tool_trace_persistence_failed")


@router.post("/public/sessions/{session_id}/turn")
def turn(session_id: str, body: TurnInput, credentials=Depends(bearer), db: Session = Depends(get_db)):
    row = authenticated_call(session_id, credentials, db)
    rate_limit(db, "turn:" + row.id, 30, 60)
    return execute_turn(db, row, body)


@router.get("/public/sessions/{session_id}")
def session_state(session_id: str, credentials=Depends(bearer), db: Session = Depends(get_db)):
    row = authenticated_call(session_id, credentials, db, allow_ended=True)
    data = context(row)
    bookings = _bookings_readback(db, row, data)
    reply = data.get("last_reply")
    if data.get("family_total", 1) > 1 and bookings:
        prompt = {"DATE": "برای نفر بعدی روز مورد نظر را بگویید.", "DATE_CHOICE": "تاریخ نفر بعدی را از گزینه‌ها انتخاب کنید.",
                  "OFFER": "زمان نفر بعدی را از گزینه‌ها انتخاب کنید.", "NAME": "نام و نام خانوادگی نفر بعدی را بگویید.",
                  "PHONE": "شماره همراه نفر بعدی را برای تأیید وارد کنید.", "VERIFY": "کد تأیید نفر بعدی را وارد کنید.",
                  "CONFIRM": "برای ادامه تأیید نوبت نفر بعدی، تکرار را بگویید تا همه اطلاعات دوباره خوانده شود.",
                  "REMINDER_CONSENT": "آیا یادآوری آخرین نوبت با پیامک را می‌خواهید؟",
                  "HANDOFF_PENDING": "درخواست شما در صف پذیرش است؛ هنوز اتصال انسانی برقرار نشده است.",
                  "HUMAN_CONNECTED": "همکار انسانی متصل است و دستیار خودکار متوقف شده است."}.get(row.state, "")
        reply = _booking_summary(bookings) + " " + prompt
        if len(bookings) < data["family_total"]:
            reply += " برای نفر بعدی هنوز نوبتی ثبت نشده است."
    return {"session_id": row.id, "state": row.state, "reply": reply,
            "handoff_status": row.handoff_status, "ended": row.ended_at is not None,
            "capabilities": capabilities(), "policy_version": row.policy_version,
            "versions": row.policy_snapshot.get("versions", {}), "bookings": bookings,
            "booking": next((item for item in bookings if item["id"] == data.get("last_booking_id")), None),
            "offers": data.get("offers", []) if row.state == "OFFER" else [],
            "conversation_state": data.get("state_metadata", {}),
            "payment_terms": data.get("payment_terms") if row.state == "CONFIRM" else None}


@router.post("/public/sessions/{session_id}/handoff")
def handoff(session_id: str, body: HandoffInput, credentials=Depends(bearer), db: Session = Depends(get_db)):
    row = authenticated_call(session_id, credentials, db)
    result = Conversation(db, row).handoff(body.reason)
    db.commit()
    return result


def end_session(db: Session, row: CallSession) -> None:
    ended = now_utc()
    db.execute(update(Tenant).where(Tenant.id == row.tenant_id).values(settings_version=Tenant.settings_version))
    statement = update(CallSession).where(CallSession.id == row.id, CallSession.ended_at.is_(None))
    authority = db.info.get("media_authority")
    if authority:
        statement = statement.where(CallSession.media_worker_id == authority[1],
            CallSession.media_worker_token == authority[2], CallSession.media_worker_lease > ended)
    updated = db.execute(statement.values(ended_at=ended, state="ENDED", lease_token=None, lease_until=None))
    if updated.rowcount:
        release_holds(db, row)
        from .media_cost import finalize_media_cost
        finalize_media_cost(db, row)
        seconds = max(0, (min(ended, row.expires_at) - row.started_at).total_seconds())
        db.add(UsageEvent(tenant_id=row.tenant_id, call_id=row.id, kind="call_seconds", quantity=seconds, unit="second", cost_toman=0))
        db.add(AuditEvent(tenant_id=row.tenant_id, actor_id="caller:" + row.id, action="call.ended", entity_type="call", entity_id=row.id, details={"seconds": round(seconds, 2)}))
    db.commit()


@router.post("/public/sessions/{session_id}/end")
def end(session_id: str, credentials=Depends(bearer), db: Session = Depends(get_db)):
    row = authenticated_call(session_id, credentials, db, allow_ended=True)
    end_session(db, row)
    return {"state": "ENDED"}


@router.post("/public/sessions/{session_id}/audio")
async def audio_turn(session_id: str, request: Request, credentials=Depends(bearer), db: Session = Depends(get_db)):
    row = authenticated_call(session_id, credentials, db)
    ensure_ai_allowed(db, row)
    rate_limit(db, "audio:" + row.id, 15, 60)
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    if not 8 <= len(request_id) <= 100:
        fail(422, "INVALID_REQUEST_ID", "شناسه درخواست معتبر نیست.")
    mime = request.headers.get("content-type", "").split(";")[0]
    if mime not in {"audio/wav", "audio/wave", "audio/x-wav", "audio/webm", "audio/ogg", "audio/mp4"}:
        fail(415, "UNSUPPORTED_AUDIO", "نوع فایل صوتی پشتیبانی نمی‌شود.")
    # No connection/transaction stays checked out while an untrusted client is
    # uploading. State and authority are checked again after the upload.
    db.rollback()
    data = bytearray()
    try:
        async with asyncio.timeout(15):
            async for chunk in request.stream():
                if len(data) + len(chunk) > 5_000_000:
                    fail(413, "AUDIO_TOO_LARGE", "پیام صوتی باید کوتاه‌تر باشد.")
                data.extend(chunk)
    except TimeoutError:
        fail(408, "AUDIO_UPLOAD_TIMEOUT", "ارسال پیام صوتی طول کشید؛ دوباره تلاش کنید.")
    if len(data) < 32:
        fail(422, "EMPTY_AUDIO", "صدایی دریافت نشد.")
    request_hash = digest("audio:" + mime + ":" + hashlib.sha256(data).hexdigest())
    ensure_ai_allowed(db, row)
    replay = _replay_turn(db, row, request_id, request_hash)
    if replay:
        return replay
    keyterms = list(db.scalars(select(Practitioner.name).where(Practitioner.tenant_id == row.tenant_id)))
    for entry in row.policy_snapshot.get("identity", {}).get("pronunciation", []):
        keyterms.append(entry["written"])
        keyterms.extend(entry.get("asr_aliases", []))
    keyterms = list(dict.fromkeys(keyterms))[:30]
    lease = _claim_turn(db, row)
    try:
        try:
            speech_started = time.perf_counter()
            gateway = SpeechGateway()
            gateway.context = ProviderContext.from_session(db, row.tenant_id, "stt:" + row.id + ":" + lease[:16],
                call_id=row.id, subject_hash="session:" + row.id)
            result = await gateway.transcribe(bytes(data), mime, keyterms)
        except ProviderError:
            fail(503, "SPEECH_UNAVAILABLE", "پاسخ‌گویی صوتی در دسترس نیست؛ پیام را بنویسید یا از پذیرش کمک بگیرید.")
        ensure_ai_allowed(db, row)
        row.channel = "browser_audio" if row.channel.startswith("browser") else row.channel
        db.add(UsageEvent(tenant_id=row.tenant_id, call_id=row.id, kind="stt_audio_seconds", quantity=result["audio_seconds"], unit="second", cost_toman=0))
        db.add(UsageEvent(tenant_id=row.tenant_id, call_id=row.id, kind="latency_stt_ms",
            quantity=round((time.perf_counter()-speech_started)*1000, 3), unit="millisecond", cost_toman=0))
        db.commit()
        if not result["text"].strip():
            return {"reply": "صدای واضحی دریافت نشد؛ دوباره بگویید یا پیام را بنویسید.", "state": row.state, "offers": [], "booking": None, "handoff": None, "capabilities": capabilities()}
        return await run_in_threadpool(execute_turn, db, row, TurnInput(text=result["text"], request_id=request_id),
            request_hash=request_hash, lease=lease, transcript=result["text"])
    finally:
        _release_turn(db, row.id, lease)


@router.get("/public/sessions/{session_id}/speech")
async def speech(session_id: str, turn_id: str, credentials=Depends(bearer), db: Session = Depends(get_db)):
    row = authenticated_call(session_id, credentials, db)
    ensure_ai_allowed(db, row)
    rate_limit(db, "tts:" + row.id, 20, 60)
    if turn_id == "greeting":
        reply = context(row).get("last_reply", GREETING) if row.turn_count == 0 else GREETING
    else:
        previous = db.scalar(select(VoiceTurn).where(VoiceTurn.id == turn_id, VoiceTurn.call_id == row.id, VoiceTurn.tenant_id == row.tenant_id))
        if not previous:
            fail(404, "TURN_NOT_FOUND", "پاسخ پیدا نشد.")
        reply = _replay_turn(db, row, previous.request_id, previous.request_hash)["reply"]
    receipt_key = None if turn_id == "greeting" else (previous.request_id, previous.request_hash)
    call_id, tenant_id = row.id, row.tenant_id
    try:
        from .partners import pronounce
        from .locale import spoken_administrative
        spoken = pronounce(spoken_administrative(reply), row.policy_snapshot.get("identity", {}).get("pronunciation", []))
        gateway = SpeechGateway()
        gateway.context = ProviderContext.from_session(db, row.tenant_id, "tts:" + row.id + ":" + secrets.token_hex(8),
            call_id=row.id, subject_hash="session:" + row.id, turn_id=None if turn_id == "greeting" else turn_id)
        synthesis_options = {"slow": context(row).get("slow", False)}
        if turn_id == "greeting" and spoken == GREETING:
            synthesis_options["cache_scope"] = f"{row.tenant_id}:policy{row.policy_version}"
        # Release the read snapshot and pooled connection before provider I/O.
        # Live state and the booking readback are revalidated afterward.
        db.rollback()
        speech_started = time.perf_counter()
        content_bytes = await gateway.synthesize(spoken, **synthesis_options)
    except ProviderError:
        fail(503, "SPEECH_UNAVAILABLE", "پخش صدا در دسترس نیست؛ متن پاسخ نمایش داده می‌شود.")
    cache_hit = getattr(gateway, "last_cache_hit", False)
    db.add(UsageEvent(tenant_id=tenant_id, call_id=call_id,
        kind="tts_cache_hit" if cache_hit else "tts_characters",
        quantity=1 if cache_hit else len(spoken), unit="hit" if cache_hit else "characters", cost_toman=0))
    db.add(UsageEvent(tenant_id=tenant_id, call_id=call_id, kind="latency_tts_ms",
        quantity=round((time.perf_counter()-speech_started)*1000, 3), unit="millisecond", cost_toman=0))
    db.commit()
    ensure_ai_allowed(db, row)
    if receipt_key:
        current = _replay_turn(db, row, *receipt_key)
        if not current or current["reply"] != reply:
            fail(409, "STALE_SPEECH", "وضعیت نوبت هنگام آماده‌سازی صدا تغییر کرد؛ وضعیت تازه را بررسی کنید.")
    return Response(content_bytes, media_type="audio/wav", headers={"Cache-Control": "no-store"})
