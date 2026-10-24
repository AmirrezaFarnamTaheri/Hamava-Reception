"""Regression evidence from the independent payment/privacy/outreach review."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import json

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import delete, func, select, update

from receptionist.core import ReceptionService
from receptionist.config import settings
from receptionist.db import get_db, now_utc
from receptionist.models import Appointment, AuditEvent, ConsentGrant, MessageOutbox, Occupancy, SlotHold, Tenant, User
from receptionist.models_ops import PaymentIntent, RefundLedger, WaitlistOffer
from receptionist.models_voice import CallSession
from receptionist.operations import (
    RefundEvidence,
    RefundInput,
    WaitlistInput,
    accept_offer,
    add_waitlist,
    create_payment,
    delete_subject,
    integrations,
    offer_waitlist,
    record_refund,
    refunds,
    request_refund,
    router,
    run_once,
    settle_verified_payment,
)
from receptionist.operations import RevokeConsentInput, revoke_consent, suppressed
from receptionist.security import Actor, actor_for, current_actor, encrypt, hash_phone
from test_core import database as database
from test_core import create, future_day, slot_for
from test_ops import _waitlist


async def settled_payment(db):
    service = ReceptionService(db, "clinic-niloufar")
    slot = slot_for(db, "clinic-niloufar", "provider-niloufar-1", "service-salon")
    booking = service.create_appointment(slot, "پرداخت آزمایشی", "09123456789", "review-payment-001", True)
    payment = await create_payment(db, "clinic-niloufar", booking["id"])
    intent = db.get(PaymentIntent, payment["id"])
    settle_verified_payment(db, intent, "VERIFIED-PAYMENT-REVIEW")
    actor = actor_for(db, db.get(User, "demo-owner"), "clinic-niloufar")
    return intent, actor


@pytest.mark.asyncio
async def test_replayed_settlement_after_refund_preserves_terminal_ledger(database):
    with database() as db:
        intent, actor = await settled_payment(db)
        refund = request_refund(
            intent.id, RefundInput(amount_toman=100000, reason="لغو درخواست", idempotency_key="review-refund-001"), actor, db
        )
        record_refund(refund["id"], RefundEvidence(provider_reference="PROVIDER-REFUND-001", confirmed=True), actor, db)
        result = settle_verified_payment(db, intent, "VERIFIED-PAYMENT-REVIEW")
        assert result["status"] == "REFUNDED"
        assert db.get(Appointment, intent.appointment_id).payment_status == "PAID"
        assert db.scalar(select(func.count()).select_from(RefundLedger)) == 1


@pytest.mark.asyncio
async def test_completed_refund_replay_rejects_changed_evidence(database):
    with database() as db:
        intent, actor = await settled_payment(db)
        refund = request_refund(
            intent.id, RefundInput(amount_toman=40000, reason="اصلاح مبلغ", idempotency_key="review-refund-002"), actor, db
        )
        record_refund(refund["id"], RefundEvidence(provider_reference="PROVIDER-REFUND-002", confirmed=True), actor, db)
        with pytest.raises(HTTPException) as error:
            record_refund(refund["id"], RefundEvidence(provider_reference="DIFFERENT-REFERENCE", confirmed=True), actor, db)
        assert error.value.detail["code"] == "REFUND_EVIDENCE_MISMATCH"


@pytest.mark.asyncio
async def test_one_provider_refund_reference_cannot_complete_two_ledgers(database):
    with database() as db:
        intent, actor = await settled_payment(db)
        rows = [
            request_refund(
                intent.id, RefundInput(amount_toman=50000, reason="اصلاح مبلغ", idempotency_key=f"review-refund-dup-{i}"), actor, db
            )
            for i in range(2)
        ]
        evidence = RefundEvidence(provider_reference="PROVIDER-SINGLE-TRANSFER", confirmed=True)
        record_refund(rows[0]["id"], evidence, actor, db)
        with pytest.raises(HTTPException) as error:
            record_refund(rows[1]["id"], evidence, actor, db)
        assert error.value.detail["code"] == "REFUND_REFERENCE_REUSED"
        assert db.get(RefundLedger, rows[1]["id"]).status == "REQUESTED"


@pytest.mark.asyncio
async def test_expired_waitlist_offer_message_is_suppressed_before_dispatch(database):
    with database() as db:
        _waitlist(db)
        offer = offer_waitlist(db, "clinic-bahar", slot_for(db))
        row = db.get(WaitlistOffer, offer["id"])
        row.expires_at = now_utc() - timedelta(seconds=1)
        db.commit()
    await run_once(database)
    with database() as db:
        msg = db.scalar(select(MessageOutbox).where(MessageOutbox.dedupe_key == "waitlist:" + offer["id"]))
        assert msg.status == "SUPPRESSED"


def test_erasure_revokes_accepted_offer_token_without_canceling_booking(database):
    with database() as db:
        _waitlist(db)
        offer = offer_waitlist(db, "clinic-bahar", slot_for(db))
        booking = accept_offer(db, offer["id"], offer["accept_token"], True)
        delete_subject(db, "clinic-bahar", "09123456789")
        with pytest.raises(HTTPException) as error:
            accept_offer(db, offer["id"], offer["accept_token"], True)
        assert error.value.status_code == 404
        assert db.get(Appointment, booking["id"]).status == "CONFIRMED"


def test_erasure_releases_call_hold_immediately(database):
    with database() as db:
        call = CallSession(
            id="review-privacy-call",
            tenant_id="clinic-bahar",
            token_hash=hashlib.sha256(b"synthetic-review-token").hexdigest(),
            policy_version=1,
            policy_snapshot={},
            context_encrypted=encrypt("{}"),
            phone_hash=hash_phone("09123456789"),
            expires_at=now_utc() + timedelta(minutes=20),
        )
        db.add(call)
        db.commit()
        hold = ReceptionService(db, "clinic-bahar").hold(slot_for(db), call.id)
        delete_subject(db, "clinic-bahar", "09123456789")
        assert db.get(SlotHold, hold["id"]).status == "RELEASED"
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == hold["id"])) == 0


@pytest.mark.parametrize("start,end", [("09:00:01", "20:00"), ("09:00+03:30", "20:00+03:30")])
def test_waitlist_requires_canonical_local_minute_times(database, start, end):
    with database() as db:
        with pytest.raises(HTTPException) as error:
            add_waitlist(
                db,
                "clinic-bahar",
                WaitlistInput(
                    provider_id="provider-bahar-1",
                    service_id="service-consultation",
                    patient_name="نام آزمایشی",
                    phone="09123456789",
                    date_from=future_day(),
                    date_to=future_day(5),
                    time_from=start,
                    time_to=end,
                    consent=True,
                ),
            )
        assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_reminder_that_waited_past_appointment_is_suppressed(database):
    with database() as db:
        db.execute(delete(MessageOutbox))
        db.execute(update(Appointment).values(reminder_opt_in=False))
        booking = create(db, reminder_opt_in=True)
        row = db.get(Appointment, booking["id"])
        row.start_at = now_utc() - timedelta(minutes=5)
        msg = db.scalar(select(MessageOutbox).where(MessageOutbox.appointment_id == row.id))
        msg.purpose, msg.template = "reminder", "appointment_reminder_v1"
        msg.payload = {"start_at": row.start_at.isoformat(), "reference": row.reference, "status": "CONFIRMED"}
        db.get(Tenant, "clinic-bahar").quiet_hours = {"start": "00:00", "end": "00:01"}
        db.commit()
        message_id = msg.id
    await run_once(database)
    with database() as db:
        assert db.get(MessageOutbox, message_id).status == "SUPPRESSED"


def test_outreach_withdrawal_is_scoped_idempotent_and_keeps_booking(database):
    from receptionist.models_ops import OutreachSuppression

    with database() as db:
        actor = actor_for(db, db.get(User, "demo-owner"), "clinic-bahar")
        booking = create(db, reminder_opt_in=True)
        _waitlist(db)
        offer = offer_waitlist(db, "clinic-bahar", slot_for(db, index=3))
        db.add_all(
            [
                ConsentGrant(
                    tenant_id="clinic-bahar",
                    subject_hash=hash_phone("09123456789"),
                    purpose="reminder",
                    granted=True,
                    policy_version="test",
                ),
                ConsentGrant(
                    tenant_id="clinic-bahar",
                    subject_hash=hash_phone("09123456789"),
                    purpose="processing",
                    granted=True,
                    policy_version="test",
                ),
            ]
        )
        for purpose in ["reminder", "followup"]:
            db.add(
                MessageOutbox(
                    tenant_id="clinic-bahar",
                    recipient_encrypted=encrypt("09123456789"),
                    purpose=purpose,
                    template="test",
                    dedupe_key="review-outreach-" + purpose,
                )
            )
        db.commit()
        data = RevokeConsentInput(phone="+98 9123456789", purposes=["waitlist", "reminder"])
        result = revoke_consent(data, actor, db)
        assert result["released_holds"] == 1 and result["canceled_waitlist_entries"] == 1
        assert result["revoked_grants"] == 1 and result["suppressed_messages"] == 2
        assert db.get(Appointment, booking["id"]).status == "CONFIRMED"
        assert not db.get(Appointment, booking["id"]).reminder_opt_in
        assert suppressed(db, "clinic-bahar", "09123456789", "waitlist")
        assert not suppressed(db, "clinic-bahar", "09123456789", "followup")
        assert not suppressed(db, "clinic-niloufar", "09123456789", "waitlist")
        assert db.scalar(select(ConsentGrant.granted).where(ConsentGrant.purpose == "processing"))
        assert db.scalar(select(MessageOutbox.status).where(MessageOutbox.dedupe_key == "review-outreach-followup")) == "QUEUED"
        assert db.scalar(select(MessageOutbox.status).where(MessageOutbox.appointment_id == booking["id"])) == "QUEUED"
        again = revoke_consent(data, actor, db)
        assert again["released_holds"] == 0 and again["suppressed_messages"] == 0
        assert db.scalar(select(func.count()).select_from(OutreachSuppression)) == 2
        with pytest.raises(HTTPException):
            accept_offer(db, offer["id"], offer["accept_token"], True)
        logs = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "consent.outreach_revoked")))
        assert all("09123456789" not in json.dumps(row.details) and row.entity_id != "09123456789" for row in logs)


@pytest.mark.asyncio
async def test_new_outreach_after_revocation_is_checked_at_send_time(database):
    with database() as db:
        actor = actor_for(db, db.get(User, "demo-owner"), "clinic-bahar")
        revoke_consent(RevokeConsentInput(phone="09123456789", purposes=["reminder"]), actor, db)
        booking = create(db, reminder_opt_in=True)
        row = db.get(Appointment, booking["id"])
        db.add(
            MessageOutbox(
                tenant_id="clinic-bahar",
                appointment_id=row.id,
                recipient_encrypted=encrypt("09123456789"),
                purpose="reminder",
                template="appointment_reminder_v1",
                dedupe_key="queued-after-revocation",
                payload={"start_at": row.start_at.isoformat()},
            )
        )
        db.commit()
    await run_once(database)
    with database() as db:
        assert db.scalar(select(MessageOutbox.status).where(MessageOutbox.dedupe_key == "queued-after-revocation")) == "SUPPRESSED"


@pytest.mark.asyncio
async def test_revoke_route_authentication_role_and_server_tenant_scope(database):
    app = FastAPI()
    app.include_router(router)

    def db_override():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    body = {"phone": "09123456789", "purposes": ["reminder"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test.invalid") as client:
        assert (await client.post("/api/v1/operations/consents/revoke", json=body)).status_code == 401
        actor = Actor("test-user", "clinic-bahar", "viewer", "test", "test@example.invalid", "test")
        app.dependency_overrides[current_actor] = lambda: actor
        assert (await client.post("/api/v1/operations/consents/revoke", json=body)).status_code == 403
        actor = Actor("test-user", "clinic-bahar", "receptionist", "test", "test@example.invalid", "test")
        assert (await client.post("/api/v1/operations/consents/revoke", json={**body, "tenant_id": "clinic-niloufar"})).status_code == 422
        response = await client.post("/api/v1/operations/consents/revoke", json=body)
        assert response.status_code == 200 and response.json()["status"] == "REVOKED"
    with database() as db:
        assert suppressed(db, "clinic-bahar", "09123456789", "reminder")
        assert not suppressed(db, "clinic-niloufar", "09123456789", "reminder")


@pytest.mark.asyncio
async def test_concurrent_partial_refunds_converge_to_full_refund(database):
    with database() as db:
        intent, actor = await settled_payment(db)
        payment_id = intent.id
        rows = [
            request_refund(
                payment_id, RefundInput(amount_toman=25000, reason="درخواست نمونه", idempotency_key=f"concurrent-refund-{i}"), actor, db
            )
            for i in range(4)
        ]

    def complete(pair):
        i, row = pair
        with database() as db:
            return record_refund(row["id"], RefundEvidence(provider_reference=f"PARALLEL-TRANSFER-{i}", confirmed=True), actor, db)

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(complete, enumerate(rows)))
    assert all(result["status"] == "COMPLETED" for result in results)
    with database() as db:
        assert db.get(PaymentIntent, payment_id).status == "REFUNDED"
        assert db.scalar(select(func.sum(RefundLedger.amount_toman)).where(RefundLedger.status == "COMPLETED")) == 100000


@pytest.mark.asyncio
async def test_concurrent_identical_refund_request_reserves_once(database):
    with database() as db:
        intent, actor = await settled_payment(db)
        payment_id = intent.id
    payload = RefundInput(amount_toman=70000, reason="درخواست نمونه", idempotency_key="concurrent-identical-refund")

    def reserve(_):
        with database() as db:
            return request_refund(payment_id, payload, actor, db)["id"]

    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(reserve, range(4)))
    assert len(set(ids)) == 1
    with database() as db:
        assert db.get(PaymentIntent, payment_id).refund_reserved_toman == 70000


@pytest.mark.asyncio
async def test_refund_free_text_is_encrypted_without_breaking_authorized_read_or_replay(database):
    with database() as db:
        intent, actor = await settled_payment(db)
        reason = "درخواست بیمار نمونه 09123456789 برای بررسی اختصاصی"
        payload = RefundInput(amount_toman=30000, reason=reason, idempotency_key="encrypted-refund-request")
        result = request_refund(intent.id, payload, actor, db)
        row = db.get(RefundLedger, result["id"])
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "refund.requested", AuditEvent.entity_id == row.id))
        assert row.reason == "staff_request"
        assert reason not in json.dumps(event.details, ensure_ascii=False)
        assert "09123456789" not in json.dumps(event.details)
        assert refunds(actor, db)[0]["reason"] == reason
        assert request_refund(intent.id, payload, actor, db)["id"] == row.id
        with pytest.raises(HTTPException) as error:
            request_refund(intent.id, payload.model_copy(update={"reason": "درخواست دیگر"}), actor, db)
        assert error.value.detail["code"] == "IDEMPOTENCY_MISMATCH"
        assert db.get(PaymentIntent, intent.id).refund_reserved_toman == 30000


def test_integration_configuration_distinguishes_demo_sends_from_working_media(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr("receptionist.payment_policy.configured_merchant", lambda tenant_id: object())
    for key, value in {
        "SPEECH_GATEWAY_URL": "https://speech.example.test",
        "SPEECH_GATEWAY_TOKEN": "synthetic-token",
        "SPEECH_PROCESSOR_APPROVED": "true",
        "APPROVED_PROVIDER_HOSTS": "speech.example.test",
        "KAVENEGAR_API_KEY": "synthetic",
        "SMS_PROVIDER_APPROVED": "true",
        "LIVEKIT_URL": "wss://livekit.example.test",
        "LIVEKIT_API_KEY": "synthetic-key",
        "LIVEKIT_API_SECRET": "synthetic-secret",
        "LIVEKIT_APPROVED": "true",
        "MEDIA_API_TOKEN": "synthetic-token",
    }.items():
        monkeypatch.setenv(key, value)
    actor = Actor("test-user", "clinic-bahar", "owner", "test", "test@example.invalid", "test")
    states = {row["id"]: row for row in integrations(actor)["items"]}
    assert all(states[key]["status"] == "configured_unverified" for key in ("speech", "livekit", "audiosocket"))
    assert all(states[key]["status"] == "demo_disabled" for key in ("sms", "payments"))
    monkeypatch.setenv("LIVEKIT_APPROVED", "false")
    monkeypatch.delenv("MEDIA_API_TOKEN")
    monkeypatch.setenv("MEDIA_CONTROL_TOKEN", "obsolete-unused-token")
    states = {row["id"]: row for row in integrations(actor)["items"]}
    assert states["livekit"]["status"] == "not_configured"
    assert states["audiosocket"]["status"] == "not_configured"
