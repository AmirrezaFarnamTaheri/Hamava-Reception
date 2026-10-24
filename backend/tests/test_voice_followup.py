"""Synthetic regressions for provenance, language, consent and partial recovery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from receptionist import voice
from receptionist.config import settings
from receptionist.db import now_utc
from receptionist.models import Appointment, MessageOutbox, Occupancy, SlotHold, StaffTask, Tenant
from receptionist.models_voice import CallSession, RateWindow, VerificationChallenge, VoiceTurn
from receptionist.payment_policy import publish_payment_policy
from receptionist.security import decrypt
from test_payment_policy import configure_operator, owner, publish_real, terms
from test_voice import caller_app as caller_app, say, start, until_confirm


def fact(answer="نشانی تأییدشده آزمایشی", **changes):
    return {"question": "نشانی کجاست؟", "keywords": ["نشانی", "آدرس"], "answer": answer,
        "category": "address", "approved_by": "demo-owner", "source": "synthetic clinic evidence",
        "effective_at": (now_utc() - timedelta(days=1)).isoformat(),
        "expires_at": (now_utc() + timedelta(days=1)).isoformat(), **changes}


def set_faq(factory, facts):
    with factory() as db:
        tenant = db.get(Tenant, "clinic-bahar")
        tenant.address = "نشانی بدون مدرک که نباید پاسخ داده شود"
        tenant.faq = facts
        db.commit()


def test_conflicting_current_facts_handoff_without_selecting_first(caller_app):
    client, factory = caller_app
    set_faq(factory, [fact("نشانی اول"), fact("نشانی دوم")])
    sid, headers = start(client)
    result = say(client, sid, headers, "آدرس کجاست؟")
    assert result["handoff"]["reason"] == "faq_conflict"
    assert not result["handoff"]["connected"]
    assert "نشانی اول" not in result["reply"] and "نشانی دوم" not in result["reply"]
    with factory() as db:
        assert db.scalar(select(StaffTask).where(StaffTask.call_id == sid)).reason == "faq_conflict"


def test_duplicate_equivalent_and_expired_facts_do_not_override_current_answer(caller_app):
    client, factory = caller_app
    set_faq(factory, [fact("نشانی قدیمی", expires_at=(now_utc() - timedelta(seconds=1)).isoformat()),
                      fact("نشانی معتبر"), fact("نشانی  معتبر")])
    sid, headers = start(client)
    result = say(client, sid, headers, "نشانی")
    assert result["reply"] == "نشانی معتبر" and result["handoff"] is None


@pytest.mark.parametrize("changes", [None, {"source": ""}, {"approved_by": None}, {"effective_at": None},
    {"expires_at": None}, {"effective_at": "2099-01-01T00:00:00+00:00"}, {"expires_at": "2001-01-01T00:00:00+00:00"}])
def test_address_never_falls_back_to_unapproved_tenant_field(caller_app, changes):
    client, factory = caller_app
    set_faq(factory, [] if changes is None else [fact(**changes)])
    sid, headers = start(client)
    result = say(client, sid, headers, "آدرس مرکز؟")
    assert result["state"] == "HANDOFF_PENDING"
    assert "نشانی بدون مدرک" not in result["reply"]


@pytest.mark.parametrize("phrase,language", [("English, please", "english"), ("Can you speak English?", "english"),
    ("لطفاً انگلیسی صحبت کنید", "english"), ("هل تتكلم العربية؟", "arabic"), ("عربی", "arabic"),
    ("Please book an appointment in Arabic", "arabic")])
def test_explicit_unsupported_language_gets_truthful_human_route(caller_app, phrase, language):
    client, factory = caller_app
    sid, headers = start(client)
    result = say(client, sid, headers, phrase)
    assert result["state"] == "HANDOFF_PENDING" and result["handoff"]["reason"] == "unsupported_language"
    assert result["handoff"]["connected"] is False and "توانایی زبان همکار باید بررسی شود" in result["reply"]
    with factory() as db:
        assert voice.context(db.get(CallSession, sid))["requested_language"] == language


def test_language_switch_releases_uncommitted_slot(caller_app):
    client, factory = caller_app
    sid, headers = start(client)
    until_confirm(client, sid, headers)
    assert say(client, sid, headers, "speak English please")["state"] == "HANDOFF_PENDING"
    with factory() as db:
        holds = list(db.scalars(select(SlotHold).where(SlotHold.session_id == sid)))
        assert holds and all(row.status == "RELEASED" for row in holds)
        assert not db.scalar(select(Occupancy).where(Occupancy.owner_id.in_([row.id for row in holds])))
        assert not db.scalar(select(Appointment).where(Appointment.session_id == sid))


def test_pinned_versions_survive_configuration_change_and_reconnect(caller_app, monkeypatch):
    client, factory = caller_app
    monkeypatch.setenv("SPEECH_ASR_VERSION", "synthetic-asr-test1")
    monkeypatch.delenv("SPEECH_VOICE_VERSION", raising=False)
    sid, headers = start(client)
    with factory() as db:
        pinned = db.get(CallSession, sid).policy_snapshot["versions"]
        assert pinned["configured_asr"] == "synthetic-asr-test1" and pinned["configured_tts"] == "not_recorded"
        assert pinned["app"] == "0.1.0"
        assert all(pinned[key].startswith("sha256:") for key in ("fsm", "locale", "calendar", "adapter"))
    monkeypatch.setenv("SPEECH_ASR_VERSION", "different-after-admission")
    monkeypatch.setenv("SPEECH_VOICE_VERSION", "different-after-admission")
    request_id = str(uuid4())
    first = say(client, sid, headers, "سلام", request_id)
    replay = say(client, sid, headers, "سلام", request_id)
    resumed = client.get(f"/api/v1/public/sessions/{sid}", headers=headers).json()
    assert first["versions"] == replay["versions"] == resumed["versions"] == pinned
    with factory() as db:
        receipt = db.get(VoiceTurn, first["turn_id"])
        assert json.loads(decrypt(receipt.result_encrypted))["versions"] == pinned
    assert not any("llm" in key or "generative" in key for key in pinned)


def phone_session(factory, tenant_id="clinic-bahar"):
    with factory() as db:
        row, _ = voice.new_session(db, db.get(Tenant, tenant_id))
        row.state, row.intent = "PHONE", "book"
        db.commit()
        return row.id


def test_otp_limit_survives_concurrent_new_sessions_and_is_tenant_scoped(caller_app, monkeypatch):
    _, factory = caller_app
    monkeypatch.setattr(voice.time, "time", lambda: 1700000000.0)
    sessions = [phone_session(factory) for _ in range(4)]

    def attempt(sid):
        with factory() as db:
            return voice.execute_turn(db, db.get(CallSession, sid),
                voice.TurnInput(text="09123456789", request_id=str(uuid4())))

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(attempt, sessions))
    assert sum(result["state"] == "VERIFY" for result in results) == 3
    assert sum(result["state"] == "HANDOFF_PENDING" for result in results) == 1
    other = attempt(phone_session(factory, "clinic-niloufar"))
    assert other["state"] == "VERIFY"
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(VerificationChallenge).where(VerificationChallenge.tenant_id == "clinic-bahar")) == 3
        assert db.scalar(select(func.count()).select_from(MessageOutbox).where(MessageOutbox.tenant_id == "clinic-bahar", MessageOutbox.purpose == "verification")) == 3
        counter = db.scalar(select(RateWindow).where(RateWindow.key.like("otp-tenant:clinic-bahar:%")))
        assert counter.count == 3 and "09123456789" not in counter.key


def test_otp_budget_and_outbox_roll_back_with_failed_turn_receipt(caller_app, monkeypatch):
    _, factory = caller_app
    sid = phone_session(factory)
    request = voice.TurnInput(text="09123456789", request_id=str(uuid4()))
    calls = 0

    def fail_receipt():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("synthetic receipt failure")
        return str(uuid4())

    with monkeypatch.context() as local:
        local.setattr(voice, "uid", fail_receipt)
        with factory() as db, pytest.raises(RuntimeError, match="synthetic receipt failure"):
            voice.execute_turn(db, db.get(CallSession, sid), request)
    with factory() as db:
        assert db.get(CallSession, sid).state == "PHONE"
        assert not db.scalar(select(VerificationChallenge).where(VerificationChallenge.call_id == sid))
        assert not db.scalar(select(MessageOutbox).where(MessageOutbox.purpose == "verification"))
        assert not db.scalar(select(RateWindow).where(RateWindow.key.like("otp%")))
        assert not db.scalar(select(VoiceTurn).where(VoiceTurn.call_id == sid))
        assert voice.execute_turn(db, db.get(CallSession, sid), request)["state"] == "VERIFY"


def test_two_relatives_partial_success_reconnect_and_independent_confirmation(caller_app):
    client, factory = caller_app
    sid, headers = start(client)
    day = (now_utc() + timedelta(days=3)).date().isoformat()
    for text in ("برای دو نفر نوبت می خواهم", "1", "1", day, "1", "مراجع اول آزمایشی", "09123456789", "246810"):
        result = say(client, sid, headers, text)
    assert result["state"] == "CONFIRM"
    first_request = str(uuid4())
    first = say(client, sid, headers, "بله", first_request)
    assert first["state"] == "DATE" and first["booking"]["status"] == "CONFIRMED"
    first_id = first["booking"]["id"]
    with TestClient(client.app) as reconnected:
        restored = reconnected.get(f"/api/v1/public/sessions/{sid}", headers=headers).json()
        assert restored["state"] == "DATE" and [row["id"] for row in restored["bookings"]] == [first_id]
        assert "برای نفر بعدی هنوز نوبتی ثبت نشده" in restored["reply"]
        assert say(reconnected, sid, headers, "بله", first_request)["turn_id"] == first["turn_id"]
        for text in (day, "1", "مراجع دوم آزمایشی", "09123456780", "246810"):
            result = say(reconnected, sid, headers, text)
        assert result["state"] == "CONFIRM"
        with factory() as db:
            call = db.get(CallSession, sid)
            second_hold = db.get(SlotHold, voice.context(call)["hold_id"])
            second_hold.expires_at = now_utc() - timedelta(seconds=1)
            db.commit()
        failed = say(reconnected, sid, headers, "بله")
        assert failed["state"] == "DATE" and failed["booking"] is None
        assert [row["id"] for row in failed["bookings"]] == [first_id]
        assert first["booking"]["reference"] in failed["reply"]
        assert "برای نفر بعدی هنوز نوبتی ثبت نشده" in failed["reply"]
        recovered = reconnected.get(f"/api/v1/public/sessions/{sid}", headers=headers).json()
        assert recovered["bookings"][0]["status"] == "CONFIRMED"
        assert say(reconnected, sid, headers, day)["state"] == "OFFER"
        assert say(reconnected, sid, headers, "1")["state"] == "CONFIRM"
        second_request = str(uuid4())
        second = say(reconnected, sid, headers, "بله", second_request)
        assert second["state"] == "REMINDER_CONSENT" and len(second["bookings"]) == 2
        assert second["booking"]["id"] != first_id
        assert say(reconnected, sid, headers, "بله", second_request)["turn_id"] == second["turn_id"]
    with factory() as db:
        bookings = list(db.scalars(select(Appointment).where(Appointment.session_id == sid)))
        assert len(bookings) == 2 and all(row.status == "CONFIRMED" for row in bookings)
        assert len({row.phone_hash for row in bookings}) == 2 and len({row.start_at for row in bookings}) == 2
        assert {decrypt(row.patient_name_encrypted) for row in bookings} == {"مراجع اول آزمایشی", "مراجع دوم آزمایشی"}
        holds = list(db.scalars(select(SlotHold).where(SlotHold.session_id == sid)))
        assert sum(row.status == "CONSUMED" for row in holds) == 2
        assert not db.scalar(select(Occupancy).where(Occupancy.owner_type == "hold", Occupancy.owner_id.in_([row.id for row in holds])))


def deposit_confirmation(client, factory, monkeypatch):
    configure_operator(monkeypatch)
    # Only the approved/configured check is synthetic. No send worker is run.
    monkeypatch.setattr(voice, "KavenegarSMS", lambda: SimpleNamespace(configured=True))
    with factory() as db:
        published = publish_real(db)
    disclosure = client.get("/api/v1/public/clinics/niloufar")
    assert disclosure.status_code == 200, disclosure.text
    intake = client.post("/api/v1/public/sessions", json={
        "clinic_slug": "niloufar", "processing_consent": True,
        "processing_notice_fingerprint": disclosure.json()["processing_notice_fingerprint"],
    })
    assert intake.status_code == 201, intake.text
    session = intake.json()
    sid, headers = session["session_id"], {"Authorization": "Bearer " + session["token"]}
    for text in ("نوبت", "1", (now_utc() + timedelta(days=3)).date().isoformat(), "1", "مراجع بیعانه آزمایشی", "09123456789"):
        result = say(client, sid, headers, text)
    assert result["state"] == "VERIFY" and "demo_otp" not in result and not settings.demo_mode
    with factory() as db:
        challenge = db.scalar(select(VerificationChallenge).where(VerificationChallenge.call_id == sid))
        queued = db.scalar(select(MessageOutbox).where(MessageOutbox.dedupe_key == "otp:" + challenge.id))
        code = json.loads(decrypt(queued.payload["secret"]))["code"]
    result = say(client, sid, headers, code)
    return sid, headers, published, result


def test_real_deposit_terms_are_read_before_yes_and_changed_terms_require_new_yes(caller_app, monkeypatch):
    client, factory = caller_app
    sid, headers, published, confirmation = deposit_confirmation(client, factory, monkeypatch)
    assert confirmation["state"] == "CONFIRM" and confirmation["payment_terms"]["version"] == published["version"]
    for key in ("deposit_terms", "cancellation_terms", "refund_terms"):
        assert confirmation["payment_terms"][key] in confirmation["reply"]
    assert "100,000 تومان" in confirmation["reply"] and "20 دقیقه" in confirmation["reply"]
    repeated = say(client, sid, headers, "تکرار")
    assert repeated["state"] == "CONFIRM" and repeated["payment_terms"] == confirmation["payment_terms"]
    with factory() as db:
        assert not db.scalar(select(Appointment).where(Appointment.session_id == sid))
        revised = publish_payment_policy(terms(published["version"], refund_terms="بازپرداخت طبق شرایط جدید فقط پس از بررسی پذیرش و مدرک بانکی انجام می‌شود."), owner(db), db)
    stale_yes = say(client, sid, headers, "بله")
    assert stale_yes["state"] == "CONFIRM" and stale_yes["booking"] is None
    assert stale_yes["payment_terms"]["version"] == revised["version"]
    with factory() as db:
        assert not db.scalar(select(Appointment).where(Appointment.session_id == sid))
    confirmed = say(client, sid, headers, "بله")
    assert confirmed["booking"]["status"] == "PENDING_PAYMENT" and "هنوز قطعی نیست" in confirmed["reply"]
    assert confirmed["booking"]["payment_terms"]["version"] == revised["version"]
    with factory() as db:
        booking = db.get(Appointment, confirmed["booking"]["id"])
        assert booking.payment_terms_snapshot["synthetic"] is False
        assert booking.payment_terms_snapshot["version"] == revised["version"]
        assert booking.expires_at > now_utc()


def test_long_deposit_terms_handoff_without_silent_speech_truncation(caller_app, monkeypatch):
    client, factory = caller_app
    sid, headers, published, _ = deposit_confirmation(client, factory, monkeypatch)
    with factory() as db:
        publish_payment_policy(terms(published["version"], deposit_terms="شرایط بیعانه آزمایشی " * 90), owner(db), db)
    result = say(client, sid, headers, "بله")
    assert result["state"] == "HANDOFF_PENDING" and result["handoff"]["reason"] == "billing_exception"
    with factory() as db:
        assert not db.scalar(select(Appointment).where(Appointment.session_id == sid))
