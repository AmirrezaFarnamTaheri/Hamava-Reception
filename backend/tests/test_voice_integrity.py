"""State, transaction, admission and media lease regressions from the audit."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update
from sqlalchemy.orm import sessionmaker

from receptionist import media_api, voice
from receptionist.api import router as staff_router
from receptionist.core import ReceptionService
from receptionist.db import Base, get_db, make_engine, now_utc
from receptionist.models import Appointment, AuditEvent, MessageOutbox, Occupancy, StaffTask, Tenant, UsageEvent, User
from receptionist.models_voice import CallSession, MediaHeartbeat, MediaRegistration, VerificationChallenge, VoiceTurn
from receptionist.security import decrypt, encrypt, issue_token
from receptionist.seed import seed_demo
from test_voice import say, start, until_confirm


@pytest.fixture
def application(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'integrity.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed_demo(db)
    app = FastAPI()
    for router in (voice.router, staff_router, media_api.router):
        app.include_router(router)

    def dependency():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = dependency
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def test_human_connected_stops_text_audio_speech_and_cannot_be_downgraded(application, monkeypatch):
    client, factory = application
    sid, headers = start(client)
    with factory() as db:
        row = db.get(CallSession, sid)
        row.state, row.handoff_status = "HUMAN_CONNECTED", "CONNECTED"
        db.commit()

    class ForbiddenSpeech:
        async def transcribe(self, *args, **kwargs):
            pytest.fail("Human-connected audio reached the speech processor")

        async def synthesize(self, *args, **kwargs):
            pytest.fail("Human-connected conversation continued speaking")

        configured = True

    monkeypatch.setattr(voice, "SpeechGateway", ForbiddenSpeech)
    for endpoint, kwargs in (("turn", {"json": {"text": "بله", "request_id": str(uuid4())}}),
                             ("audio", {"content": b"a" * 100, "headers": {**headers, "Content-Type": "audio/wav"}})):
        response = client.post(f"/api/v1/public/sessions/{sid}/{endpoint}", **({"headers": headers} | kwargs))
        assert response.status_code == 409 and response.json()["detail"]["code"] == "HUMAN_CONNECTED"
    assert client.get(f"/api/v1/public/sessions/{sid}/speech?turn_id=greeting", headers=headers).status_code == 409
    response = client.post(f"/api/v1/public/sessions/{sid}/handoff", headers=headers, json={"reason": "human_requested"})
    assert response.json()["handoff"]["connected"] is True
    assert response.json()["reply"] == ""
    with factory() as db:
        assert db.get(CallSession, sid).state == "HUMAN_CONNECTED"
        assert db.scalar(select(func.count()).select_from(VoiceTurn).where(VoiceTurn.call_id == sid)) == 0


def test_booking_context_and_turn_receipt_roll_back_together(application, monkeypatch):
    client, factory = application
    sid, headers = start(client)
    until_confirm(client, sid, headers)
    request_id = str(uuid4())

    def lost_process():
        raise RuntimeError("synthetic failure before turn receipt")

    with monkeypatch.context() as changes:
        changes.setattr(voice, "uid", lost_process)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            client.post(f"/api/v1/public/sessions/{sid}/turn", headers=headers,
                json={"text": "بله", "request_id": request_id})
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.session_id == sid)) == 0
        assert db.get(CallSession, sid).state == "CONFIRM"
        assert db.get(CallSession, sid).lease_token is None
        assert db.scalar(select(VoiceTurn).where(VoiceTurn.call_id == sid, VoiceTurn.request_id == request_id)) is None
    result = say(client, sid, headers, "بله", request_id)
    assert result["booking"]["status"] == "CONFIRMED"


def test_expired_turn_lease_cannot_overwrite_its_successor(application):
    client, factory = application
    sid, _ = start(client)
    with factory() as original:
        row = original.get(CallSession, sid)
        old_lease = voice._claim_turn(original, row)
        with factory() as successor:
            successor.execute(update(CallSession).where(CallSession.id == sid)
                .values(lease_token="successor", lease_until=now_utc() + timedelta(seconds=45)))
            successor.commit()
        with pytest.raises(HTTPException) as error:
            voice.execute_turn(original, row, voice.TurnInput(text="نوبت", request_id=str(uuid4())), lease=old_lease)
        assert error.value.detail["code"] == "TURN_LEASE_LOST"
    with factory() as db:
        row = db.get(CallSession, sid)
        assert row.state == "INTENT" and row.lease_token == "successor"
        assert db.scalar(select(func.count()).select_from(VoiceTurn).where(VoiceTurn.call_id == sid)) == 0


def test_voice_retry_reports_current_canceled_booking(application):
    client, factory = application
    sid, headers = start(client)
    until_confirm(client, sid, headers)
    request_id = str(uuid4())
    result = say(client, sid, headers, "بله", request_id)
    with factory() as db:
        ReceptionService(db, "clinic-bahar", "demo-owner").cancel_appointment(result["booking"]["id"],
            "cancel-after-lost-response", result["booking"]["version"], verified=True)
    replay = say(client, sid, headers, "بله", request_id)
    assert replay["turn_id"] == result["turn_id"]
    assert replay["booking"]["status"] == "CANCELED"
    assert "لغوشده" in replay["reply"]


def test_all_channel_admission_is_serialized_and_budget_reserves_inflight_calls(application, monkeypatch):
    _, factory = application
    monkeypatch.setenv("MAX_CONCURRENT_CALLS_PER_TENANT", "2")

    def admit(index):
        with factory() as db:
            try:
                row, _ = voice.new_session(db, db.get(Tenant, "clinic-bahar"), "sip" if index % 2 else "browser_text")
                return row.id
            except HTTPException as error:
                assert error.detail["code"] == "CAPACITY"
                return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        admitted = list(pool.map(admit, range(8)))
    assert sum(value is not None for value in admitted) == 2
    with factory() as db:
        tenant = db.get(Tenant, "clinic-niloufar")
        tenant.monthly_minute_budget = 1
        db.add(UsageEvent(tenant_id=tenant.id, kind="stt_audio_seconds", quantity=100000, unit="second"))
        db.commit()
        call, _ = voice.new_session(db, tenant)
        assert 0 < (call.expires_at - call.started_at).total_seconds() <= 60
    with factory() as db, pytest.raises(HTTPException) as error:
        voice.new_session(db, db.get(Tenant, "clinic-niloufar"), "sip")
    assert error.value.detail["code"] == "BUDGET_LIMIT"


def test_audio_retry_is_payload_bound_and_skips_duplicate_transcription(application, monkeypatch):
    client, _ = application
    sid, headers = start(client)
    calls = []

    class Speech:
        configured = True

        async def transcribe(self, audio, mime, keyterms):
            calls.append(audio)
            return {"text": "سلام", "audio_seconds": 1.25}

    monkeypatch.setattr(voice, "SpeechGateway", Speech)
    audio_headers = {**headers, "Content-Type": "audio/wav", "X-Request-ID": str(uuid4())}
    endpoint = f"/api/v1/public/sessions/{sid}/audio"
    first = client.post(endpoint, headers=audio_headers, content=b"first audio" * 10)
    replay = client.post(endpoint, headers=audio_headers, content=b"first audio" * 10)
    mismatch = client.post(endpoint, headers=audio_headers, content=b"other audio" * 10)
    assert first.status_code == replay.status_code == 200
    assert first.json()["turn_id"] == replay.json()["turn_id"]
    assert mismatch.status_code == 409 and len(calls) == 1


def test_human_connect_during_transcription_prevents_late_ai_turn(application, monkeypatch):
    client, factory = application
    sid, headers = start(client)

    class Speech:
        configured = True

        async def transcribe(self, *args):
            with factory() as db:
                db.execute(update(CallSession).where(CallSession.id == sid)
                    .values(state="HUMAN_CONNECTED", handoff_status="CONNECTED"))
                db.commit()
            return {"text": "نوبت می خواهم", "audio_seconds": 1}

    monkeypatch.setattr(voice, "SpeechGateway", Speech)
    result = client.post(f"/api/v1/public/sessions/{sid}/audio", content=b"audio" * 20,
        headers={**headers, "Content-Type": "audio/wav", "X-Request-ID": str(uuid4())})
    assert result.status_code == 409
    with factory() as db:
        assert db.get(CallSession, sid).state == "HUMAN_CONNECTED"
        assert db.get(CallSession, sid).lease_token is None
        assert db.scalar(select(func.count()).select_from(VoiceTurn).where(VoiceTurn.call_id == sid)) == 0


def test_caller_can_correct_doctor_contact_and_name_before_reconfirmation(application):
    client, factory = application
    sid, headers = start(client)
    until_confirm(client, sid, headers)
    assert say(client, sid, headers, "پزشک را عوض کن")["state"] == "CHANGE_PROVIDER"
    with factory() as db:
        row = db.get(CallSession, sid)
        assert "chosen" not in voice.context(row) and "offers" not in voice.context(row)
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_type == "hold")) == 0
    assert say(client, sid, headers, "2")["state"] == "DATE"
    assert say(client, sid, headers, (now_utc() + timedelta(days=4)).date().isoformat())["state"] == "OFFER"
    assert say(client, sid, headers, "1")["state"] == "CONFIRM"
    assert say(client, sid, headers, "شماره همراه اشتباه است")["state"] == "PHONE"
    with factory() as db:
        assert "verified_phone" not in voice.context(db.get(CallSession, sid))
        old_challenge = db.scalar(select(VerificationChallenge).where(VerificationChallenge.call_id == sid))
        assert old_challenge.expires_at <= now_utc()
        assert db.scalar(select(MessageOutbox.status).where(MessageOutbox.dedupe_key == "otp:" + old_challenge.id)) == "SUPPRESSED"
    assert say(client, sid, headers, "09351234567")["state"] == "VERIFY"
    assert say(client, sid, headers, "246810")["state"] == "CONFIRM"
    assert say(client, sid, headers, "نام را اصلاح کن")["state"] == "NAME"
    corrected = say(client, sid, headers, "مراجع اصلاح شده")
    assert corrected["state"] == "CONFIRM" and "آرش" in corrected["reply"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.session_id == sid)) == 0
    result = say(client, sid, headers, "بله")
    with factory() as db:
        row = db.get(Appointment, result["booking"]["id"])
        assert row.provider_id == "provider-bahar-2"
        assert decrypt(row.phone_encrypted) == "09351234567"
        assert decrypt(row.patient_name_encrypted) == "مراجع اصلاح شده"


def test_modes_have_explicit_behavior_and_supervised_booking_needs_approval(application):
    client, factory = application
    with factory() as db:
        tenant = db.get(Tenant, "clinic-bahar")
        tenant.mode = "after_hours"
        tenant.working_hours = {str(day): [["09:00", "20:00"]] for day in range(7)}
        assert voice._automation_allowed(tenant, datetime(2030, 1, 1, 1, tzinfo=timezone.utc), None)
        assert not voice._automation_allowed(tenant, datetime(2030, 1, 1, 6, tzinfo=timezone.utc), None)
        tenant.mode = "overflow"
        assert not voice._automation_allowed(tenant, now_utc(), "incoming")
        assert voice._automation_allowed(tenant, now_utc(), "busy")
        tenant.mode = "human_primary"
        db.commit()
    sid, headers = start(client)
    assert client.get(f"/api/v1/public/sessions/{sid}", headers=headers).json()["state"] == "HANDOFF_PENDING"
    assert say(client, sid, headers, "نوبت می خواهم")["state"] == "HANDOFF_PENDING"
    with factory() as db:
        db.get(Tenant, "clinic-bahar").mode = "supervised"
        db.commit()
    sid, headers = start(client)
    until_confirm(client, sid, headers)
    result = say(client, sid, headers, "بله")
    assert result["booking"]["status"] == "PENDING_STAFF_APPROVAL"
    with factory() as db:
        assert db.get(Appointment, result["booking"]["id"]).approval_required
        db.get(Tenant, "clinic-bahar").mode = "paused"
        db.commit()
    assert client.post("/api/v1/public/sessions", json={"clinic_slug": "bahar", "processing_consent": True}).status_code == 503
    assert client.post(f"/api/v1/public/sessions/{sid}/turn", headers=headers,
        json={"text": "بله", "request_id": str(uuid4())}).status_code == 503


def configure_media(monkeypatch):
    monkeypatch.setenv("MEDIA_API_TOKEN", "synthetic-private-media-token-32-characters")
    monkeypatch.setenv("LIVEKIT_URL", "wss://media.example.test")
    monkeypatch.setattr(media_api, "livekit_configured", lambda: True)
    monkeypatch.setattr(media_api, "room_token", lambda *args, **kwargs: "synthetic-room-token")
    return {"Authorization": "Bearer synthetic-private-media-token-32-characters"}


def add_room(factory):
    with factory() as db:
        row, token = voice.new_session(db, db.get(Tenant, "clinic-bahar"))
        row.channel, row.media_room, row.media_participant = "webrtc", "reception-" + row.id, "caller-" + row.id
        db.add(MediaRegistration(call_uuid=row.id, call_id=row.id, tenant_id=row.tenant_id,
            token_encrypted=encrypt(token), expires_at=row.expires_at))
        db.commit()
        return row.id


def test_worker_capacity_and_lease_generation_fence_stale_worker(application, monkeypatch):
    client, factory = application
    media_headers = configure_media(monkeypatch)
    room_ids = [add_room(factory) for _ in range(4)]
    poll = "/api/v1/internal/media/rooms"
    first = client.post(poll, headers=media_headers, json={"worker_id": "worker-original", "capacity": 2}).json()
    active = [record["session_id"] for record in first["rooms"]]
    assert len(active) == 2
    second = client.post(poll, headers=media_headers,
        json={"worker_id": "worker-original", "capacity": 2, "active_sessions": active}).json()
    assert second["rooms"] == [] and set(second["renewed_sessions"]) == set(active)
    third = client.post(poll, headers=media_headers, json={"worker_id": "worker-other", "capacity": 2}).json()
    assert len(third["rooms"]) == 2
    sid = active[0]
    stale_headers = {"Authorization": "Bearer " + next(record["token"] for record in first["rooms"] if record["session_id"] == sid)}
    with factory() as db:
        db.get(CallSession, sid).media_worker_lease = now_utc() - timedelta(seconds=1)
        db.commit()
    revoked = client.post(poll, headers=media_headers,
        json={"worker_id": "worker-original", "capacity": 2, "active_sessions": active}).json()
    assert sid in revoked["revoked_sessions"]
    successor = client.post(poll, headers=media_headers, json={"worker_id": "worker-successor", "capacity": 1}).json()
    assert successor["rooms"][0]["session_id"] == sid
    for endpoint in ("turn", "end"):
        kwargs = {"json": {"text": "نوبت", "request_id": str(uuid4())}} if endpoint == "turn" else {}
        response = client.post(f"/api/v1/public/sessions/{sid}/{endpoint}", headers=stale_headers, **kwargs)
        assert response.status_code == 409 and response.json()["detail"]["code"] == "MEDIA_LEASE_LOST"
    with factory() as db:
        assert db.get(CallSession, sid).ended_at is None
        assert db.get(CallSession, sid).media_worker_id == "worker-successor"
        assert set(room_ids) == set(db.scalars(select(CallSession.id)))


def test_verified_human_webhook_requires_live_tenant_membership_and_is_idempotent(application, monkeypatch):
    from livekit import api

    client, factory = application
    configure_media(monkeypatch)
    monkeypatch.setenv("LIVEKIT_API_KEY", "synthetic-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "synthetic-secret-with-32-characters")
    sid = add_room(factory)
    with factory() as db:
        token = issue_token(db.get(User, "demo-owner"), "clinic-bahar")
    takeover = client.post(f"/api/v1/operations/calls/{sid}/takeover", headers={"Authorization": "Bearer " + token})
    assert takeover.status_code == 200
    event = SimpleNamespace(event="participant_joined", room=SimpleNamespace(name="reception-" + sid),
        participant=SimpleNamespace(identity="staff-demo-other"))
    monkeypatch.setattr(api, "WebhookReceiver", lambda verifier: SimpleNamespace(receive=lambda *args: event))
    assert client.post("/api/v1/webhooks/livekit", content=b"{}").status_code == 403
    event.participant.identity = "staff-demo-owner"
    assert client.post("/api/v1/webhooks/livekit", content=b"{}").status_code == 200
    assert client.post("/api/v1/webhooks/livekit", content=b"{}").status_code == 200
    with factory() as db:
        assert db.get(CallSession, sid).state == "HUMAN_CONNECTED"
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_id == sid, AuditEvent.action == "call.human_connected")) == 1


def test_claimed_handoff_task_is_reused_and_urgent_request_is_promoted(application):
    client, factory = application
    sid, headers = start(client)
    endpoint = f"/api/v1/public/sessions/{sid}/handoff"
    first = client.post(endpoint, headers=headers, json={"reason": "human_requested"}).json()
    task_id = first["handoff"]["task_id"]
    for status in ("IN_PROGRESS", "PENDING", "CALLBACK"):
        with factory() as db:
            db.get(StaffTask, task_id).status = status
            db.commit()
        result = client.post(endpoint, headers=headers, json={"reason": "urgent_concern"})
        assert result.status_code == 200 and result.json()["handoff"]["task_id"] == task_id
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(StaffTask).where(StaffTask.call_id == sid)) == 1
        assert db.get(StaffTask, task_id).priority == "urgent"
        assert db.get(StaffTask, task_id).status == "CALLBACK"


def test_only_static_greeting_uses_cache_and_hits_are_not_provider_characters(application, monkeypatch):
    client, factory = application
    sid, headers = start(client)
    synthesis = []
    cached = set()

    class Speech:
        configured = True
        last_cache_hit = False

        async def synthesize(self, text, **options):
            synthesis.append((text, options))
            scope = options.get("cache_scope")
            self.last_cache_hit = bool(scope and (scope, text) in cached)
            if scope:
                cached.add((scope, text))
            return b"synthetic-wave"

    monkeypatch.setattr(voice, "SpeechGateway", Speech)
    endpoint = f"/api/v1/public/sessions/{sid}/speech"
    for _ in range(2):
        assert client.get(endpoint, params={"turn_id": "greeting"}, headers=headers).status_code == 200
    result = say(client, sid, headers, "نوبت می خواهم")
    for _ in range(2):
        assert client.get(endpoint, params={"turn_id": result["turn_id"]}, headers=headers).status_code == 200
    assert all(options.get("cache_scope") == "clinic-bahar:policy1" for _, options in synthesis[:2])
    assert all("cache_scope" not in options for _, options in synthesis[2:])
    with factory() as db:
        units = list(db.scalars(select(UsageEvent).where(UsageEvent.call_id == sid, UsageEvent.kind.in_(["tts_cache_hit", "tts_characters"]))))
        assert sum(event.quantity for event in units if event.kind == "tts_cache_hit") == 1
        assert synthesis[0][0] == voice.GREETING
        assert not any(char.isdigit() for char in synthesis[2][0])
        assert sum(event.quantity for event in units if event.kind == "tts_characters") == len(synthesis[0][0]) + sum(len(text) for text, _ in synthesis[2:])


def test_booking_canceled_during_synthesis_never_returns_stale_confirmation_audio(application, monkeypatch):
    client, factory = application
    sid, headers = start(client)
    until_confirm(client, sid, headers)
    result = say(client, sid, headers, "بله")
    submitted = []

    class Speech:
        configured = True
        last_cache_hit = False

        async def synthesize(self, text, **options):
            submitted.append(text)
            with factory() as db:
                ReceptionService(db, "clinic-bahar", "demo-owner").cancel_appointment(
                    result["booking"]["id"], "cancel-during-synthetic-tts", result["booking"]["version"], verified=True)
            return b"must-not-be-played"

    monkeypatch.setattr(voice, "SpeechGateway", Speech)
    response = client.get(f"/api/v1/public/sessions/{sid}/speech", params={"turn_id": result["turn_id"]}, headers=headers)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "STALE_SPEECH"
    with factory() as db:
        assert len(submitted) == 1 and not any(char.isdigit() for char in submitted[0])
        assert db.scalar(select(UsageEvent.quantity).where(UsageEvent.call_id == sid, UsageEvent.kind == "tts_characters")) == len(submitted[0])


def test_provider_waits_release_database_connections_and_allow_unrelated_writes(application, monkeypatch):
    client, factory = application
    sid, headers = start(client)
    checks = []

    def concurrent_writer(kind):
        assert factory.kw["bind"].pool.checkedout() == 0
        with factory() as db:
            db.add(AuditEvent(tenant_id="clinic-niloufar", actor_id="synthetic-worker", action=kind,
                entity_type="test", entity_id="no-patient-data", details={}))
            db.commit()
        checks.append(kind)

    class Speech:
        configured = True

        async def synthesize(self, text, **options):
            concurrent_writer("during.synthesis")
            return b"synthetic-wave"

        async def transcribe(self, *args):
            concurrent_writer("during.transcription")
            return {"text": "سلام", "audio_seconds": 1}

    monkeypatch.setattr(voice, "SpeechGateway", Speech)
    assert client.get(f"/api/v1/public/sessions/{sid}/speech", params={"turn_id": "greeting"}, headers=headers).status_code == 200
    assert client.post(f"/api/v1/public/sessions/{sid}/audio", content=b"audio" * 20,
        headers={**headers, "Content-Type": "audio/wav", "X-Request-ID": str(uuid4())}).status_code == 200
    assert checks == ["during.synthesis", "during.transcription"]


def test_pbx_duplicate_registration_is_atomic_and_human_primary_falls_back(application, monkeypatch):
    client, factory = application
    media_headers = configure_media(monkeypatch)
    monkeypatch.setenv("MEDIA_DID_TENANTS_JSON", '{"02100000000":"bahar"}')
    monkeypatch.setattr(media_api, "SpeechGateway", lambda: SimpleNamespace(configured=True))
    endpoint = "/api/v1/internal/media/register"
    body = {"call_uuid": str(uuid4()), "did": "02100000000", "processing_notice_played": True}
    # Independent requests contend for the same registration while admission is
    # serialized. A duplicate must not leave an extra reserved session behind.
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _: client.post(endpoint, headers=media_headers, json=body), range(2)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(CallSession)) == 1
        assert db.scalar(select(func.count()).select_from(MediaRegistration)) == 1
        db.get(Tenant, "clinic-bahar").mode = "human_primary"
        db.commit()
    human = client.post(endpoint, headers=media_headers, json={**body, "call_uuid": str(uuid4())})
    assert human.status_code == 200 and human.json()["registered"] is False and human.json()["route"] == "human"
    with factory() as db:
        row = db.get(CallSession, human.json()["session_id"])
        assert row.ended_at is not None
        assert db.scalar(select(StaffTask).where(StaffTask.call_id == row.id)) is not None


def test_browser_cannot_assert_overflow_authority(application):
    client, factory = application
    with factory() as db:
        db.get(Tenant, "clinic-bahar").mode = "overflow"
        db.commit()
    assert client.post("/api/v1/public/sessions", json={"clinic_slug": "bahar", "processing_consent": True, "routing_reason": "busy"}).status_code == 422
    sid, headers = start(client)
    assert say(client, sid, headers, "نوبت می خواهم")["state"] == "HANDOFF_PENDING"


def test_simultaneous_browser_room_joins_reuse_one_registration(application, monkeypatch, request):
    from receptionist.models_finance import CostReservation

    client, factory = application
    configure_media(monkeypatch)
    monkeypatch.setattr(media_api, "SpeechGateway", lambda: SimpleNamespace(configured=True))
    with factory() as db:
        db.add(MediaHeartbeat(id="synthetic-healthy-worker", updated_at=now_utc()))
        db.commit()

    created_rooms = []
    creation_entered, allow_creation = Event(), Event()

    class LiveRoom:
        room = None

        def __init__(self):
            self.room = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def create_room(self, request):
            created_rooms.append(request.name)
            creation_entered.set()
            assert await asyncio.to_thread(allow_creation.wait, 10), "Test did not release the synthetic room creation"
            return SimpleNamespace(name=request.name)

    monkeypatch.setattr(media_api, "livekit_client", LiveRoom)
    sid, headers = start(client)
    endpoint = f"/api/v1/public/sessions/{sid}/livekit"
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(client.post, endpoint, headers=headers)
        try:
            assert creation_entered.wait(10), "First join did not reach the synthetic provider"
            # Admission liability is durable while the external result is still
            # pending. A duplicate must neither dispatch nor reserve again.
            duplicate = pool.submit(client.post, endpoint, headers=headers).result(timeout=10)
            assert duplicate.status_code == 409
            assert duplicate.json()["detail"]["code"] == "MEDIA_ADMISSION_PENDING"
            with factory() as db:
                reservations = db.scalars(select(CostReservation).where(CostReservation.call_id == sid)).all()
                assert len(reservations) == 1 and reservations[0].status == "STARTED"
                reservation_id = reservations[0].id
                assert db.scalar(select(func.count()).select_from(MediaRegistration).where(MediaRegistration.call_id == sid)) == 0
                assert db.get(CallSession, sid).media_room is None
        finally:
            allow_creation.set()
        admitted = first.result(timeout=10)
    assert admitted.status_code == 200 and admitted.json()["room"] == "reception-" + sid
    replay = client.post(endpoint, headers=headers)
    assert replay.status_code == 200 and replay.json()["room"] == "reception-" + sid
    assert created_rooms == ["reception-" + sid]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(MediaRegistration).where(MediaRegistration.call_id == sid)) == 1
        reservations = db.scalars(select(CostReservation).where(CostReservation.call_id == sid)).all()
        assert len(reservations) == 1 and reservations[0].id == reservation_id
        assert reservations[0].status == "STARTED"
    request.node.user_properties.extend([
        ("initial_statuses", "200,409"),
        ("inflight_error", "MEDIA_ADMISSION_PENDING"),
        ("remote_room_creates", 1),
        ("durable_registrations", 1),
        ("durable_cost_reservations", 1),
        ("replay_status", 200),
        ("runtime_changed", False),
    ])
