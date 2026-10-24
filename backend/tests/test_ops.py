"""Operational invariants: no duplicate dispatch, safe offers, privacy, settlement."""

from datetime import timedelta
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import delete, func, select, update
from receptionist.config import settings
from receptionist.core import ReceptionService
from receptionist.db import now_utc
from receptionist.models import Appointment, ConsentGrant, MessageOutbox, Occupancy, Tenant, User
from receptionist.models_ops import PaymentIntent, PrivacyTombstone, RefundLedger, WaitlistEntry, WaitlistOffer
from receptionist.models_voice import CallSession, VoiceTurn, VerificationChallenge  # Register tables for fixtures.
from receptionist.operations import (
    AdjustmentInput,
    InvoiceInput,
    ReceiptInput,
    RefundInput,
    WaitlistInput,
    accept_offer,
    add_waitlist,
    apply_receipt,
    billing_adjustment,
    create_invoice,
    create_payment,
    delete_subject,
    export_subject,
    next_permitted_time,
    offer_waitlist,
    request_refund,
    retry_notification,
    run_jobs,
    run_once,
    settle_verified_payment,
)
from receptionist.providers import ProviderError
from receptionist.security import actor_for, decrypt, encrypt, hash_phone
from test_core import database as database
from test_core import create, future_day, slot_for


@pytest.mark.asyncio
async def test_demo_worker_never_calls_provider(database):
    class NeverSend:
        async def send(self, *args, **kwargs):
            raise AssertionError("Demo must not transmit")

    result = await run_once(database, NeverSend())
    assert result["simulated"] > 0 and result["sent"] == 0
    with database() as db:
        assert db.scalar(select(func.count()).select_from(MessageOutbox).where(MessageOutbox.status == "SIMULATED")) > 0


@pytest.mark.asyncio
async def test_unknown_send_not_retried_or_claimed_twice(database, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    with database() as db:
        db.execute(delete(MessageOutbox))
        db.execute(update(Appointment).values(reminder_opt_in=False))
        booking = create(db)

    class UncertainGateway:
        calls = 0

        async def send(self, *args, **kwargs):
            self.calls += 1
            raise ProviderError("NETWORK_TIMEOUT", unknown_outcome=True)

    gateway = UncertainGateway()
    first = await run_once(database, gateway)
    await run_once(database, gateway)
    assert first["unknown"] == 1 and gateway.calls == 1
    with database() as db:
        msg = db.scalar(select(MessageOutbox).where(MessageOutbox.appointment_id == booking["id"]))
        actor = actor_for(db, db.get(User, "demo-owner"), "clinic-bahar")
        with pytest.raises(HTTPException) as error:
            retry_notification(msg.id, actor, db)
        assert error.value.detail["code"] == "RETRY_NOT_SAFE"


def test_stalled_dispatch_becomes_unknown(database):
    with database() as db:
        msg = db.scalar(select(MessageOutbox).where(MessageOutbox.status == "QUEUED").limit(1))
        msg.status, msg.locked_until = "SENDING", now_utc() - timedelta(seconds=1)
        db.commit()
        result = run_jobs(db)
        assert result["uncertain_sends"] == 1
        db.refresh(msg)
        assert msg.status == "UNKNOWN"


def test_receipt_deduplication_and_terminal_delivered(database):
    with database() as db:
        msg = db.scalar(select(MessageOutbox).limit(1))
        msg.status, msg.provider_id = "SENT", "provider-123"
        db.commit()
        data = ReceiptInput(event_id="receipt-event-001", message_id=msg.id, provider_id=msg.provider_id, status="DELIVERED")
        assert apply_receipt(db, data)["status"] == "processed"
        assert apply_receipt(db, data)["status"] == "already_processed"
        with pytest.raises(HTTPException):
            apply_receipt(db, data.model_copy(update={"status": "FAILED"}))
        apply_receipt(db, data.model_copy(update={"event_id": "receipt-event-002", "status": "FAILED"}))
        db.refresh(msg)
        assert msg.status == "DELIVERED"


def _waitlist(db, phone="09123456789"):
    tenant = db.get(Tenant, "clinic-bahar")
    tenant.quiet_hours = {"start": "00:00", "end": "00:01"}
    db.commit()
    return add_waitlist(
        db,
        tenant.id,
        WaitlistInput(
            provider_id="provider-bahar-1",
            service_id="service-consultation",
            patient_name="منتظر نمونه",
            phone=phone,
            date_from=future_day(),
            date_to=future_day(5),
            consent=True,
        ),
    )


def test_waitlist_exclusive_hold_and_idempotent_acceptance(database):
    with database() as db:
        first_entry = _waitlist(db)
        assert _waitlist(db)["id"] == first_entry["id"]
        _waitlist(db, "09123456788")
        slot = slot_for(db)
        offer = offer_waitlist(db, "clinic-bahar", slot)
        assert offer["status"] == "OFFERED"
        with pytest.raises(HTTPException) as error:
            offer_waitlist(db, "clinic-bahar", slot)
        assert error.value.detail["code"] == "SLOT_TAKEN"
        result = accept_offer(db, offer["id"], offer["accept_token"], True)
        replay = accept_offer(db, offer["id"], offer["accept_token"], True)
        assert result["id"] == replay["id"] and result["status"] == "CONFIRMED"
        assert db.scalar(select(func.count()).select_from(WaitlistEntry).where(WaitlistEntry.status == "BOOKED")) == 1


def test_waitlist_expiry_releases_slot_and_honors_attempt_cap(database):
    with database() as db:
        _waitlist(db)
        slot = slot_for(db)
        offer = offer_waitlist(db, "clinic-bahar", slot)
        row = db.get(WaitlistOffer, offer["id"])
        row.expires_at = now_utc() - timedelta(seconds=1)
        entry = db.get(WaitlistEntry, row.entry_id)
        entry.offer_attempts = 3
        db.commit()
        run_jobs(db)
        db.refresh(entry)
        assert entry.status == "EXHAUSTED"
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == row.hold_id)) == 0
        assert create(db, slot, key="after-waitlist-expiry")["status"] == "CONFIRMED"


@pytest.mark.asyncio
async def test_payment_verified_late_settlement_does_not_resurrect(database):
    with database() as db:
        svc = ReceptionService(db, "clinic-niloufar")
        slot = slot_for(db, "clinic-niloufar", "provider-niloufar-1", "service-salon")
        booking = svc.create_appointment(slot, "پرداخت نمونه", "09123456789", "payment-ops-test", True)
        payment = await create_payment(db, "clinic-niloufar", booking["id"])
        assert payment["status"] == "DEMO_PENDING" and payment["payment_url"] is None
        row = db.get(Appointment, booking["id"])
        row.expires_at = now_utc() - timedelta(seconds=1)
        db.commit()
        intent = db.get(PaymentIntent, payment["id"])
        settled = settle_verified_payment(db, intent, "DEMO-verified-late")
        assert settled["status"] == "LATE_REQUIRES_REFUND"
        assert db.get(Appointment, booking["id"]).status == "EXPIRED"
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == booking["id"])) == 0


@pytest.mark.asyncio
async def test_refund_reservations_cannot_exceed_paid_amount(database):
    with database() as db:
        svc = ReceptionService(db, "clinic-niloufar")
        slot = slot_for(db, "clinic-niloufar", "provider-niloufar-1", "service-salon")
        booking = svc.create_appointment(slot, "بازپرداخت نمونه", "09123456789", "refund-ops-test", True)
        payment = await create_payment(db, "clinic-niloufar", booking["id"])
        settle_verified_payment(db, db.get(PaymentIntent, payment["id"]), "DEMO-verified")
        actor = actor_for(db, db.get(User, "demo-owner"), "clinic-niloufar")
        refund = request_refund(
            payment["id"], RefundInput(amount_toman=60000, reason="درخواست نمونه", idempotency_key="refund-test-first"), actor, db
        )
        assert refund["status"] == "REQUESTED"
        with pytest.raises(HTTPException) as error:
            request_refund(
                payment["id"], RefundInput(amount_toman=50000, reason="درخواست دوم", idempotency_key="refund-test-second"), actor, db
            )
        assert error.value.detail["code"] == "REFUND_EXCEEDS_PAYMENT"
        assert db.scalar(select(func.count()).select_from(RefundLedger)) == 1


def test_privacy_retains_active_business_record_without_silent_cancel(database):
    with database() as db:
        booking = create(db)
        result = delete_subject(db, "clinic-bahar", "09123456789", "demo-owner")
        assert result["status"] == "REVIEW_REQUIRED" and result["active_bookings_retained"] == 1
        row = db.get(Appointment, booking["id"])
        assert row.status == "CONFIRMED" and not row.reminder_opt_in
        assert db.scalar(select(PrivacyTombstone.id).where(PrivacyTombstone.tenant_id == "clinic-bahar"))
        msg = db.scalar(select(MessageOutbox).where(MessageOutbox.appointment_id == booking["id"]))
        assert msg.status == "SUPPRESSED" and decrypt(msg.recipient_encrypted) == "deleted"
        other = export_subject(db, "clinic-niloufar", "09123456789")
        assert other["appointments"] == [] and other["calls"] == []


def test_privacy_erases_turns_challenges_and_revokes_consent(database):
    with database() as db:
        subject = hash_phone("09123456789")
        call = CallSession(
            id="privacy-call",
            tenant_id="clinic-bahar",
            token_hash="test-token-hash",
            policy_version=1,
            policy_snapshot={},
            context_encrypted=encrypt(json.dumps({"patient": "نام شخص"})),
            phone_hash=subject,
            expires_at=now_utc() + timedelta(minutes=20),
        )
        db.add(call)
        db.flush()
        db.add(
            VoiceTurn(
                tenant_id="clinic-bahar",
                call_id=call.id,
                request_id="privacy-turn",
                request_hash="hash",
                result_encrypted=encrypt(json.dumps({"reply": "متن شخصی"})),
            )
        )
        db.add(
            VerificationChallenge(
                tenant_id="clinic-bahar",
                call_id=call.id,
                phone_hash=subject,
                phone_encrypted=encrypt("09123456789"),
                code_hash="code-hash",
                expires_at=now_utc() + timedelta(minutes=5),
            )
        )
        consent = ConsentGrant(tenant_id="clinic-bahar", subject_hash=subject, purpose="training", granted=True, policy_version="test")
        db.add(consent)
        db.commit()
        assert export_subject(db, "clinic-bahar", "09123456789")["calls"][0]["context"]["patient"] == "نام شخص"
        result = delete_subject(db, "clinic-bahar", "09123456789")
        assert result["calls_erased"] == 1
        db.refresh(call)
        db.refresh(consent)
        assert call.state == "DELETED" and call.phone_hash is None and decrypt(call.context_encrypted) == "{}"
        assert not consent.granted
        assert db.scalar(select(func.count()).select_from(VoiceTurn).where(VoiceTurn.call_id == call.id)) == 0
        assert db.scalar(select(func.count()).select_from(VerificationChallenge).where(VerificationChallenge.call_id == call.id)) == 0


def test_reminders_are_quiet_hour_aware_and_deduplicated(database):
    with database() as db:
        db.execute(delete(MessageOutbox))
        run_jobs(db)
        first = db.scalar(select(func.count()).select_from(MessageOutbox).where(MessageOutbox.purpose == "reminder"))
        run_jobs(db)
        second = db.scalar(select(func.count()).select_from(MessageOutbox).where(MessageOutbox.purpose == "reminder"))
        assert first == second
        tenant = db.get(Tenant, "clinic-bahar")
        tenant.quiet_hours = {"start": "21:00", "end": "09:00"}
        moment = now_utc().astimezone(__import__("zoneinfo").ZoneInfo("Asia/Tehran")).replace(hour=23, minute=0)
        permitted = next_permitted_time(tenant, moment)
        assert permitted.hour == 9 and permitted.date() == moment.date() + timedelta(days=1)


def test_invoice_snapshots_are_closed_period_and_not_silent_charges(database):
    with database() as db:
        actor = actor_for(db, db.get(User, "demo-owner"), "clinic-bahar")
        prior = (now_utc().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        billing_adjustment(
            AdjustmentInput(period=prior, amount_toman=-10000, reason="اعتبار نمونه", idempotency_key="billing-credit-test"), actor, db
        )
        data = InvoiceInput(period=prior, base_fee_toman=100000, included_minutes=30, per_minute_toman=100, pricing_approved=True)
        result = create_invoice(data, actor, db)
        assert result["status"] == "DRAFT" and result["amount_toman"] == 90000
        assert create_invoice(data, actor, db)["id"] == result["id"]
        with pytest.raises(HTTPException):
            create_invoice(data.model_copy(update={"base_fee_toman": 200000}), actor, db)
        with pytest.raises(HTTPException) as error:
            create_invoice(data.model_copy(update={"period": now_utc().strftime("%Y-%m")}), actor, db)
        assert error.value.detail["code"] == "PERIOD_NOT_CLOSED"


def test_stt_processing_meter_never_inflates_billable_call_minutes(database):
    from receptionist.models import UsageEvent
    from receptionist.api import usage
    from receptionist.operations import building

    with database() as db:
        actor = actor_for(db, db.get(User, "demo-owner"), "clinic-bahar")
        db.execute(delete(UsageEvent))
        db.add_all(
            [
                UsageEvent(tenant_id=actor.tenant_id, kind="call_seconds", quantity=120, unit="second", cost_toman=3),
                UsageEvent(tenant_id=actor.tenant_id, kind="stt_audio_seconds", quantity=90, unit="second", cost_toman=7),
            ]
        )
        db.commit()
        assert usage(actor, db)["minutes"] == 2
        assert building(actor, db)["totals"]["minutes_used"] == 2
