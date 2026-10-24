"""Authenticated media admission and verified human room participation."""
from __future__ import annotations

import hmac
import json
import os
import secrets
import time
from datetime import timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import get_db, now_utc
from .models import AuditEvent, Membership, StaffTask, Tenant, UsageEvent, User
from .models_voice import CallSession, MediaHeartbeat, MediaRegistration
from .media.transfer_events import PBXObservation, record_pbx_registration, accept_pbx_observation
from .providers import SpeechGateway, enabled
from .provider_control import observe_activity
from .security import Actor, ROLE_PERMISSIONS, bearer, decrypt, encrypt, fail, mask_phone, require_permissions
from .voice import ACTIVE_TASK_STATUSES, StrictModel, authenticated_call, context, end_session, ensure_ai_allowed, media_session_token, new_session, release_holds, request_handoff

router = APIRouter(prefix="/api/v1", tags=["media"])


def media_auth(credentials=Depends(bearer)):
    secret = os.getenv("MEDIA_API_TOKEN", "")
    if not secret or len(secret) < 32 or not credentials or not hmac.compare_digest(credentials.credentials, secret):
        fail(401, "MEDIA_AUTH_REQUIRED", "دسترسی رسانه مجاز نیست.")
    return True


def livekit_configured() -> bool:
    return enabled("LIVEKIT_APPROVED") and all(os.getenv(k) for k in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"))


def room_token(room: str, identity: str, *, agent: bool = False) -> str:
    from livekit import api
    return api.AccessToken(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]).with_identity(identity).with_ttl(timedelta(minutes=35)).with_grants(
        api.VideoGrants(room_join=True, room=room, can_publish=True, can_subscribe=True,
                        can_publish_data=True, can_update_own_metadata=False,
                        can_publish_sources=["microphone"], agent=agent)).to_jwt()


def livekit_client():
    from livekit import api
    return api.LiveKitAPI(url=os.environ["LIVEKIT_URL"], api_key=os.environ["LIVEKIT_API_KEY"], api_secret=os.environ["LIVEKIT_API_SECRET"])


@router.post("/public/sessions/{session_id}/livekit")
async def join_browser_room(session_id: str, credentials=Depends(bearer), db: Session = Depends(get_db)):
    row = authenticated_call(session_id, credentials, db)
    ensure_ai_allowed(db, row)
    if not livekit_configured() or not SpeechGateway().configured:
        fail(503, "MEDIA_NOT_CONFIGURED", "تماس زنده هنوز فعال نیست؛ می‌توانید گفت‌وگو را با متن ادامه دهید.")
    heartbeat = db.scalar(select(MediaHeartbeat).where(MediaHeartbeat.updated_at > now_utc() - timedelta(seconds=20)).limit(1))
    if not heartbeat:
        fail(503, "MEDIA_WORKER_UNAVAILABLE", "پاسخ‌گویی زنده آماده نیست؛ از گفت‌وگوی متنی استفاده کنید.")
    from livekit import api
    room = row.media_room or "reception-" + row.id
    call_id, tenant_id = row.id, row.tenant_id
    from .media_cost import reserve_media_cost, finalize_media_cost
    ticket = reserve_media_cost(db, row)
    db.commit()  # Durable maximum liability before the first remote room operation.
    if not ticket["replayed"]:
        started, dispatched = time.monotonic(), False
        failure_code = "MEDIA_ROOM_CREATE_FAILED"
        try:
            async with livekit_client() as client:
                dispatched = True
                created = await client.room.create_room(api.CreateRoomRequest(name=room, empty_timeout=120, departure_timeout=30, max_participants=3,
                    metadata=json.dumps({"call_id": call_id, "tenant_id": tenant_id})))
                if getattr(created, "name", None) != room:
                    failure_code = "MEDIA_ROOM_INVALID_RESPONSE"
                    raise ValueError("Media room response did not match the requested room")
        except Exception:
            finalize_media_cost(db, row, reason="admission_failure")
            observe_activity(db, tenant_id, "telephony_primary", "start", outcome="unknown", code=failure_code,
                performed_io=dispatched, latency_ms=int((time.monotonic() - started) * 1000))
            db.commit()
            fail(503, "MEDIA_ADMISSION_UNKNOWN", "نتیجه ایجاد اتاق روشن نیست؛ وضعیت همین درخواست باید بررسی شود.")
        observe_activity(db, tenant_id, "telephony_primary", "start", outcome="succeeded", code="MEDIA_ROOM_CREATED",
            performed_io=True, latency_ms=int((time.monotonic() - started) * 1000))
    # Serialize registration only after the remote call. A duplicate browser
    # join reuses one registration, and revoked/ended callers cannot be revived
    # by a room creation that completed after their access changed.
    db.execute(update(CallSession).where(CallSession.id == call_id).values(state=CallSession.state))
    db.refresh(row)
    authenticated_call(session_id, credentials, db)
    row.media_room, row.channel, row.media_participant = room, "webrtc", "caller-" + row.id
    registration = db.get(MediaRegistration, row.id)
    if not registration:
        db.add(MediaRegistration(call_uuid=row.id, call_id=row.id, tenant_id=row.tenant_id,
            token_encrypted=encrypt(credentials.credentials), expires_at=row.expires_at))
    db.commit()
    return {"url": os.environ["LIVEKIT_URL"], "token": room_token(room, row.media_participant), "room": room}


class PBXRegister(StrictModel):
    call_uuid: str = Field(min_length=36, max_length=36)
    did: str = Field(max_length=80)
    processing_notice_played: bool
    pbx_linkedid: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,100}$")
    pbx_caller_uniqueid: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,100}$")
    routing_reason: Literal["incoming", "busy", "no_answer", "after_hours"] = "incoming"


@router.post("/internal/media/register", dependencies=[Depends(media_auth)])
def register_pbx(body: PBXRegister, db: Session = Depends(get_db)):
    try:
        call_uuid = str(UUID(body.call_uuid))
        routes = json.loads(os.getenv("MEDIA_DID_TENANTS_JSON", "{}"))
    except (ValueError, TypeError):
        fail(422, "INVALID_MEDIA_REQUEST", "پیکربندی رسانه معتبر نیست.")
    if not body.processing_notice_played:
        fail(422, "NOTICE_REQUIRED", "اعلان پردازش باید پیش از اتصال پخش شود.")
    from .routing import resolve_did
    approved_route = resolve_did(db, body.did)
    slug = routes.get(body.did)
    if not approved_route and not slug:
        fail(403, "DID_NOT_AUTHORIZED", "مسیر تماس مجاز نیست.")
    tenant = db.get(Tenant, approved_route["tenant_id"]) if approved_route else db.scalar(select(Tenant).where(Tenant.slug == slug, Tenant.active.is_(True)))
    if not tenant or tenant.mode == "paused":
        fail(503, "CLINIC_UNAVAILABLE", "پذیرش خودکار در دسترس نیست.")
    if db.get(MediaRegistration, call_uuid):
        fail(409, "MEDIA_UUID_REUSED", "شناسه تماس قبلاً استفاده شده است.")
    if not SpeechGateway().configured:
        fail(503, "SPEECH_NOT_CONFIGURED", "مسیر صوتی آماده نیست؛ تماس را به پذیرش برگردانید.")
    if bool(body.pbx_linkedid) != bool(body.pbx_caller_uniqueid):
        fail(422, "PBX_CORRELATION_INCOMPLETE", "شناسه رويدادهاي تماس ناقص است.")
    row, token = new_session(db, tenant, "sip", routing_reason=body.routing_reason, commit=False)
    if approved_route:
        row.policy_snapshot = {**row.policy_snapshot, "inbound_route": approved_route}
    if body.pbx_linkedid:
        record_pbx_registration(db, row, call_uuid, linkedid=body.pbx_linkedid,
                                caller_uniqueid=body.pbx_caller_uniqueid)
    db.add(MediaRegistration(call_uuid=call_uuid, call_id=row.id, tenant_id=tenant.id,
        token_encrypted=encrypt(token), expires_at=now_utc() + timedelta(seconds=60)))
    automated = row.policy_snapshot.get("automation_allowed", False)
    try:
        if automated:
            db.commit()
        else:
            end_session(db, row)
    except IntegrityError:
        db.rollback()
        fail(409, "MEDIA_UUID_REUSED", "شناسه تماس قبلاً استفاده شده است.")
    return {"call_uuid": call_uuid, "session_id": row.id, "registered": automated,
            "route": "ai" if automated else "human",
            "transfer_target": approved_route["transfer_target"] if approved_route else None,
            "queue_id": approved_route["queue_id"] if approved_route else None}


class MediaClaim(StrictModel):
    call_uuid: str = Field(min_length=36, max_length=36)


@router.post("/internal/media/claim", dependencies=[Depends(media_auth)])
def claim_pbx(body: MediaClaim, db: Session = Depends(get_db)):
    registration = db.get(MediaRegistration, body.call_uuid)
    if not registration or registration.expires_at <= now_utc():
        fail(404, "MEDIA_REGISTRATION_EXPIRED", "تماس ثبت‌شده پیدا نشد.")
    call = db.get(CallSession, registration.call_id)
    tenant = db.get(Tenant, registration.tenant_id)
    if not call or call.ended_at or call.expires_at <= now_utc() or not tenant or not tenant.active:
        fail(404, "MEDIA_REGISTRATION_EXPIRED", "تماس ثبت‌شده پیدا نشد.")
    updated = db.execute(update(MediaRegistration).where(MediaRegistration.call_uuid == body.call_uuid,
        MediaRegistration.claimed_at.is_(None), MediaRegistration.expires_at > now_utc()).values(claimed_at=now_utc()))
    if updated.rowcount != 1:
        db.rollback()
        fail(409, "MEDIA_ALREADY_CLAIMED", "تماس پیش‌تر متصل شده است.")
    db.commit()
    # The private worker has claimed a registered, authenticated PBX connection.
    # Observe in a new short transaction so no Tenant lock follows a Call lock.
    observe_activity(db, registration.tenant_id, "telephony_primary", "start", outcome="succeeded",
        code="SIP_WORKER_CLAIMED", performed_io=True)
    db.commit()
    return {"session_id": registration.call_id, "token": decrypt(registration.token_encrypted),
            "expires_at": call.expires_at.isoformat()}


class WorkerPoll(StrictModel):
    worker_id: str = Field(min_length=8, max_length=100)
    active_sessions: list[str] = Field(default_factory=list, max_length=100)
    capacity: int = Field(default=8, ge=1, le=100)


@router.post("/internal/media/rooms", dependencies=[Depends(media_auth)])
def media_rooms(body: WorkerPoll, db: Session = Depends(get_db)):
    if not livekit_configured():
        return {"rooms": [], "renewed_sessions": [], "revoked_sessions": body.active_sessions, "lease_seconds": 30}
    now = now_utc()
    factory = __import__("sqlalchemy.dialects.sqlite", fromlist=["insert"]).insert if db.bind.dialect.name == "sqlite" else __import__("sqlalchemy.dialects.postgresql", fromlist=["insert"]).insert
    # Serializes concurrent polls for the same worker, including first admission.
    db.execute(factory(MediaHeartbeat).values(id=body.worker_id, updated_at=now)
        .on_conflict_do_update(index_elements=["id"], set_={"updated_at": now}))
    renewed = list(db.scalars(update(CallSession).where(CallSession.id.in_(body.active_sessions),
        CallSession.media_worker_id == body.worker_id, CallSession.media_worker_lease > now,
        CallSession.ended_at.is_(None), CallSession.expires_at > now)
        .values(media_worker_lease=now + timedelta(seconds=30)).returning(CallSession.id)))
    capacity = min(body.capacity, max(1, int(os.getenv("MAX_LIVEKIT_ROOMS_PER_WORKER", "8"))))
    owned = db.scalar(select(func.count()).select_from(CallSession).where(
        CallSession.media_worker_id == body.worker_id, CallSession.media_worker_lease > now,
        CallSession.ended_at.is_(None), CallSession.expires_at > now))
    available = max(0, capacity - owned)
    calls = db.scalars(select(CallSession).where(CallSession.channel == "webrtc", CallSession.media_room.is_not(None),
        CallSession.ended_at.is_(None), CallSession.expires_at > now, CallSession.state != "HUMAN_CONNECTED",
        CallSession.id.not_in(body.active_sessions),
        or_(CallSession.media_worker_lease.is_(None), CallSession.media_worker_lease <= now))
        .order_by(CallSession.started_at).limit(available)).all() if available else []
    rooms = []
    for row in calls:
        registration = db.get(MediaRegistration, row.id)
        if not registration or registration.expires_at <= now or registration.tenant_id != row.tenant_id:
            continue
        claimed = db.execute(update(CallSession).where(CallSession.id == row.id,
            CallSession.ended_at.is_(None), CallSession.expires_at > now, CallSession.state != "HUMAN_CONNECTED",
            or_(CallSession.media_worker_lease.is_(None), CallSession.media_worker_lease <= now)).values(
            media_worker_id=body.worker_id, media_worker_token=secrets.token_hex(24),
            media_worker_lease=now + timedelta(seconds=30)))
        if claimed.rowcount:
            db.refresh(row)
            rooms.append({"session_id": row.id, "token": media_session_token(row), "expires_at": row.expires_at.isoformat(),
                "livekit": {"room": row.media_room, "url": os.environ["LIVEKIT_URL"],
                    "token": room_token(row.media_room, "agent-" + row.id, agent=True)}})
    db.commit()
    # An idle global poll proves no tenant's media path. Only renewals belonging
    # to this authenticated worker are scoped activity; rejected/stolen leases
    # and initial queue claims do not refresh an observation.
    if renewed:
        tenants = sorted(set(db.scalars(select(CallSession.tenant_id).where(CallSession.id.in_(renewed)))))
        for tenant_id in tenants:
            observe_activity(db, tenant_id, "telephony_primary", "start", outcome="succeeded",
                code="MEDIA_WORKER_LEASE_RENEWED", performed_io=True)
        db.commit()
    return {"rooms": rooms, "renewed_sessions": renewed,
            "revoked_sessions": sorted(set(body.active_sessions) - set(renewed)), "lease_seconds": 30,
            "capacity": capacity}


def pbx_event_auth(credentials=Depends(bearer)):
    secret = os.getenv("PBX_EVENT_TOKEN", "")
    if len(secret) < 32 or not credentials or not hmac.compare_digest(credentials.credentials, secret):
        fail(401, "PBX_EVENT_AUTH_REQUIRED", "رويداد تلفني مجاز نيست.")
    return True


@router.post("/internal/media/pbx-transfer", dependencies=[Depends(pbx_event_auth)])
def pbx_transfer_event(body: PBXObservation, db: Session = Depends(get_db)):
    from .models import AuditEvent
    from .media_cost import finalize_media_cost
    from .voice import release_holds
    registration = db.get(MediaRegistration, body.call_uuid)
    if not registration:
        fail(404, "PBX_REGISTRATION_NOT_FOUND", "تماس مجاز پيدا نشد.")
    call = db.get(CallSession, registration.call_id)
    if not call or call.tenant_id != registration.tenant_id:
        fail(404, "PBX_REGISTRATION_NOT_FOUND", "تماس مجاز پيدا نشد.")
    # Lock the tenant consistently with call booking/handoff operations. Events
    # stay durable and cannot race accepted/failed connection decisions.
    db.execute(update(Tenant).where(Tenant.id == call.tenant_id).values(settings_version=Tenant.settings_version))
    db.refresh(call)
    try:
        result = accept_pbx_observation(db, body)
    except ValueError as exc:
        fail(409, str(exc), "رويداد تلفني با تماس معتبر سازگار نيست.")
    if not result["replayed"] and result["transitioned"]:
        db.add(AuditEvent(tenant_id=call.tenant_id, actor_id="pbx:ami", action="call.transfer_" + result["status"].lower(),
            entity_type="call", entity_id=call.id, details={"source": "authenticated_pbx_ami", "bridge_observed": result["connected"]}))
        if result["connected"] and not call.ended_at:
            release_holds(db, call)
            finalize_media_cost(db, call, reason="human_takeover")
        elif result["status"] in {"FAILED", "DISCONNECTED"}:
            task = db.scalar(select(StaffTask).where(StaffTask.call_id == call.id,
                StaffTask.tenant_id == call.tenant_id, StaffTask.status.in_(["OPEN", "IN_PROGRESS", "PENDING"])))
            if task and task.status == "OPEN":
                task.status = "CALLBACK"
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "PBX_EVENT_CONCURRENT_RETRY", "رويداد تكراري بايد دوباره بررسي شود.")
    return {"status": result["status"], "connected": result["connected"], "replayed": result["replayed"]}



@router.get("/operations/calls")
def calls(actor: Actor = Depends(require_permissions("appointment:read")), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, actor.tenant_id)
    rows = db.scalars(select(CallSession).where(CallSession.tenant_id == actor.tenant_id, CallSession.ended_at.is_(None),
        CallSession.expires_at > now_utc()).order_by(CallSession.started_at.desc()).limit(100)).all()
    return [{"id": row.id, "clinic_name": tenant.name, "channel": row.channel, "state": row.state,
        "intent": row.intent, "started_at": row.started_at.isoformat(),
        "duration_seconds": int((now_utc() - row.started_at).total_seconds()),
        "phone_masked": mask_phone(context(row).get("phone", "")), "handoff_status": row.handoff_status,
        "policy_version": row.policy_version} for row in rows]


@router.post("/operations/calls/{call_id}/takeover")
def takeover(call_id: str, actor: Actor = Depends(require_permissions("task:write")), db: Session = Depends(get_db)):
    row = db.scalar(select(CallSession).where(CallSession.id == call_id, CallSession.tenant_id == actor.tenant_id,
        CallSession.ended_at.is_(None), CallSession.expires_at > now_utc()))
    if not row:
        fail(404, "CALL_NOT_FOUND", "تماس فعال پیدا نشد.")
    result = request_handoff(db, row, "human_requested")
    if result["connected"]:
        db.commit()
        return {"status": "HUMAN_CONNECTED", "task_id": result["task_id"]}
    task = db.get(StaffTask, result["task_id"])
    if task.assigned_to and task.assigned_to != actor.user_id:
        fail(409, "TAKEOVER_ALREADY_CLAIMED", "این تماس در حال اتصال به همکار دیگری است.")
    task.assigned_to = actor.user_id
    db.add(AuditEvent(tenant_id=actor.tenant_id, actor_id=actor.user_id, action="call.takeover_requested", entity_type="call", entity_id=row.id, details={}))
    db.commit()
    if row.media_room and livekit_configured():
        return {"status": "ROOM_READY", "task_id": task.id, "livekit": {"url": os.environ["LIVEKIT_URL"],
            "token": room_token(row.media_room, "staff-" + actor.user_id), "room": row.media_room}}
    return {"status": "CALLBACK_QUEUED", "task_id": task.id}


@router.post("/webhooks/livekit")
async def livekit_webhook(request: Request, db: Session = Depends(get_db)):
    if not livekit_configured():
        fail(503, "MEDIA_NOT_CONFIGURED", "رسانه فعال نیست.")
    from livekit import api
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 65536:
            fail(413, "WEBHOOK_TOO_LARGE", "درخواست بزرگ است.")
    try:
        receiver = api.WebhookReceiver(api.TokenVerifier(os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]))
        event = receiver.receive(body.decode(), request.headers.get("Authorization", ""))
    except Exception:
        fail(401, "INVALID_WEBHOOK", "امضای رویداد معتبر نیست.")
    row = db.scalar(select(CallSession).where(CallSession.media_room == event.room.name,
        CallSession.ended_at.is_(None), CallSession.expires_at > now_utc()))
    if row and event.event == "participant_joined" and event.participant.identity.startswith("staff-"):
        staff_id = event.participant.identity.removeprefix("staff-")
        membership = db.scalar(select(Membership).join(User, User.id == Membership.user_id).where(
            Membership.user_id == staff_id, Membership.tenant_id == row.tenant_id,
            Membership.active.is_(True), Membership.role.in_([role for role, permissions in ROLE_PERMISSIONS.items() if "task:write" in permissions]), User.active.is_(True)))
        task = db.scalar(select(StaffTask).where(StaffTask.call_id == row.id, StaffTask.tenant_id == row.tenant_id,
            StaffTask.assigned_to == staff_id, StaffTask.status.in_(ACTIVE_TASK_STATUSES)))
        if not membership or not task:
            fail(403, "STAFF_NOT_AUTHORIZED", "عضویت و پذیرش این تماس برای همکار انسانی تأیید نشده است.")
        db.execute(update(Tenant).where(Tenant.id == row.tenant_id).values(settings_version=Tenant.settings_version))
        changed = db.execute(update(CallSession).where(CallSession.id == row.id,
            CallSession.ended_at.is_(None), CallSession.expires_at > now_utc(),
            CallSession.handoff_status == "QUEUED").values(handoff_status="CONNECTED", state="HUMAN_CONNECTED",
            lease_token=None, lease_until=None))
        if changed.rowcount:
            release_holds(db, row)
            from .media_cost import finalize_media_cost
            finalize_media_cost(db, row, reason="human_takeover")
            db.add(UsageEvent(tenant_id=row.tenant_id, call_id=row.id, kind="latency_handoff_ms",
                quantity=max(0, (now_utc()-task.created_at).total_seconds()*1000), unit="millisecond", cost_toman=0))
            db.add(AuditEvent(tenant_id=row.tenant_id, actor_id=event.participant.identity,
                action="call.human_connected", entity_type="call", entity_id=row.id,
                details={"evidence": "verified_livekit_webhook"}))
            observe_activity(db, row.tenant_id, "telephony_primary", "transfer", outcome="succeeded",
                code="MEDIA_HUMAN_JOIN_VERIFIED", performed_io=True)
        db.commit()
    return {"accepted": True}
