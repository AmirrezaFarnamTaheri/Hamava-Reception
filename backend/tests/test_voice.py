from datetime import timedelta
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from receptionist import models_ops  # noqa: F401
from receptionist.db import Base, get_db, make_engine, now_utc
from receptionist.models import Appointment, ConsentGrant, Occupancy, StaffTask, Tenant, UsageEvent
from receptionist.models_voice import CallSession, VerificationChallenge, VoiceTurn
from receptionist.seed import seed_demo
from receptionist.voice import router


@pytest.fixture
def caller_app(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'voice.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed_demo(db)
    app = FastAPI()
    app.include_router(router)
    def db_dependency():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = db_dependency
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def start(client, slug="bahar"):
    result = client.post("/api/v1/public/sessions", json={"clinic_slug": slug, "processing_consent": True})
    assert result.status_code == 201, result.text
    data = result.json()
    return data["session_id"], {"Authorization": "Bearer " + data["token"]}


def say(client, sid, headers, text, request_id=None):
    result = client.post(f"/api/v1/public/sessions/{sid}/turn", json={"text": text, "request_id": request_id or str(uuid4())}, headers=headers)
    assert result.status_code == 200, result.text
    return result.json()


def until_confirm(client, sid, headers):
    assert say(client, sid, headers, "نوبت می خواهم")["state"] == "SERVICE"
    assert say(client, sid, headers, "1")["state"] == "PROVIDER"
    assert say(client, sid, headers, "1")["state"] == "DATE"
    result = say(client, sid, headers, (now_utc() + timedelta(days=3)).date().isoformat())
    assert result["state"] == "OFFER" and len(result["offers"]) == 2
    assert say(client, sid, headers, "1")["state"] == "NAME"
    assert say(client, sid, headers, "مراجع آزمایشی")["state"] == "PHONE"
    assert say(client, sid, headers, "۰۹۱۲۳۴۵۶۷۸۹")["state"] == "VERIFY"
    result = say(client, sid, headers, "246810")
    assert result["state"] == "CONFIRM", result


def test_real_caller_booking_flow_idempotency_and_opt_in(caller_app):
    client, factory = caller_app
    sid, headers = start(client)
    until_confirm(client, sid, headers)
    request_id = str(uuid4())
    result = say(client, sid, headers, "بله", request_id)
    assert result["booking"]["status"] == "CONFIRMED"
    assert result["state"] == "REMINDER_CONSENT"
    assert result["booking"]["notification_status"] == "QUEUED"
    replay = say(client, sid, headers, "بله", request_id)
    assert replay["turn_id"] == result["turn_id"]
    assert say(client, sid, headers, "بله")["state"] == "COMPLETE"
    with factory() as db:
        booking = db.get(Appointment, result["booking"]["id"])
        assert booking.reminder_opt_in
        assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.session_id == sid)) == 1
        turns = db.scalars(select(VoiceTurn).where(VoiceTurn.call_id == sid)).all()
        assert all("مراجع آزمایشی" not in turn.result_encrypted for turn in turns)


def test_no_commit_without_explicit_confirmation(caller_app):
    client, factory = caller_app
    sid, headers = start(client)
    until_confirm(client, sid, headers)
    result = say(client, sid, headers, "خیر")
    assert result["state"] == "DATE"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.session_id == sid)) == 0
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_type == "hold")) == 0


def test_human_request_works_during_phone_verification(caller_app):
    client, factory = caller_app
    sid, headers = start(client)
    until_confirm(client, sid, headers)
    result = say(client, sid, headers, "منشی می خواهم")
    assert result["state"] == "HANDOFF_PENDING"
    assert result["handoff"]["connected"] is False
    with factory() as db:
        assert db.scalar(select(StaffTask).where(StaffTask.call_id == sid))
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_type == "hold")) == 0


def test_urgency_never_enters_booking_or_claims_triage(caller_app):
    client, factory = caller_app
    sid, headers = start(client)
    result = say(client, sid, headers, "نفس نمی کشد")
    assert result["handoff"]["reason"] == "urgent_concern"
    assert "بدون منتظر ماندن" in result["reply"]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.session_id == sid)) == 0


def test_session_scope_recording_disabled_and_replay_mismatch(caller_app):
    client, factory = caller_app
    with factory() as db:
        tenant = db.scalar(select(Tenant).where(Tenant.slug == "bahar"))
        tenant.retention_days = 14
        db.commit()
    public = client.get("/api/v1/public/clinics/bahar")
    assert public.status_code == 200
    disclosure = public.json()
    assert disclosure["transcript_retention_days"] == 14
    assert "صدای خام ذخیره نمی‌شود" in disclosure["notice"]
    assert "متن و نتایج ضروری گفت‌وگو" in disclosure["notice"]
    assert "رمزگذاری‌شده" in disclosure["notice"]
    assert "۱۴ روز پس از پایان گفت‌وگو" in disclosure["notice"]
    assert "برنامه زمان‌بندی‌شده" in disclosure["notice"]
    assert client.get("/api/v1/public/clinics/niloufar").json()["transcript_retention_days"] == 30
    result = client.post("/api/v1/public/sessions", json={"clinic_slug": "bahar", "processing_consent": True, "training_consent": True})
    assert result.status_code == 422
    sid, headers = start(client)
    other, other_headers = start(client, "niloufar")
    assert client.get(f"/api/v1/public/sessions/{sid}", headers=other_headers).status_code == 404
    request_id = str(uuid4())
    say(client, sid, headers, "سلام", request_id)
    mismatch = client.post(f"/api/v1/public/sessions/{sid}/turn", headers=headers, json={"text": "متن دیگر", "request_id": request_id})
    assert mismatch.status_code == 409
    with factory() as db:
        assert not db.get(CallSession, sid).recording_consent
        grants = list(db.scalars(select(ConsentGrant).where(ConsentGrant.subject_hash == "session:" + sid)))
        assert {g.purpose: g.granted for g in grants} == {"processing": True, "recording": False, "training": False}


def test_otp_attempt_limit_and_no_raw_identifier(caller_app):
    client, factory = caller_app
    sid, headers = start(client)
    for text in ("نوبت", "1", "1", (now_utc() + timedelta(days=3)).date().isoformat(), "1", "مراجع آزمایشی", "09123456789"):
        say(client, sid, headers, text)
    for _ in range(5):
        say(client, sid, headers, "999999")
    result = say(client, sid, headers, "246810")
    assert result["state"] == "HANDOFF_PENDING"
    with factory() as db:
        row = db.scalar(select(VerificationChallenge).where(VerificationChallenge.call_id == sid))
        assert "246810" not in row.code_hash and "09123456789" not in row.phone_encrypted


def test_call_end_metered_once_releases_holds(caller_app):
    client, factory = caller_app
    sid, headers = start(client)
    assert client.post(f"/api/v1/public/sessions/{sid}/end", headers=headers).status_code == 200
    assert client.post(f"/api/v1/public/sessions/{sid}/end", headers=headers).status_code == 200
    assert client.post(f"/api/v1/public/sessions/{sid}/turn", headers=headers, json={"text": "سلام", "request_id": str(uuid4())}).status_code == 410
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(UsageEvent).where(UsageEvent.call_id == sid, UsageEvent.kind == "call_seconds")) == 1

