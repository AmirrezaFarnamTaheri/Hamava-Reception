"""Provider health from actual adapter paths, using local HTTP mock transports.

No live supplier is contacted. These tests prove instrumentation semantics,
tenant scope and released database transactions, not supplier availability.
"""

from datetime import timedelta
import json
import time

from fastapi import HTTPException
import httpx
import pytest
from sqlalchemy import select, update

from receptionist.billing import mark_cost_started, reserve_cost
from receptionist.config import settings
from receptionist.db import now_utc
from receptionist.messaging_controls import poll_sms_receipts
from receptionist.models import Appointment, MessageOutbox, Tenant
from receptionist.models_core import ProviderObservation
from receptionist.models_finance import CostReservation, UsageCharge
from receptionist.models_ops import PaymentIntent
from receptionist.models_ops_control import SMSReceiptPoll
from receptionist.operations import create_payment, payment_callback, run_once
from receptionist.providers import CircuitBreaker, KavenegarSMS, ZarinpalGateway, _breakers
from test_core import create, database as database
from test_payment_policy import configure_operator, make_booking, publish_real


@pytest.fixture(autouse=True)
def local_adapters(database, monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setenv("SMS_PROVIDER_APPROVED", "true")
    monkeypatch.setenv("KAVENEGAR_API_KEY", "SYNTHETICKEY")
    monkeypatch.setenv("KAVENEGAR_SENDER", "100000000")
    _breakers.clear()
    yield
    _breakers.clear()


def observation(db, tenant, provider):
    return db.scalar(select(ProviderObservation).where(
        ProviderObservation.tenant_id == tenant, ProviderObservation.provider_key == provider))


def queued_sms(database):
    with database() as db:
        db.execute(update(MessageOutbox).values(status="SIMULATED"))
        booking = create(db, key="activity-sms-booking")
        db.execute(update(Appointment).values(reminder_opt_in=False))
        message = db.scalar(select(MessageOutbox).where(MessageOutbox.appointment_id == booking["id"]))
        message_id = message.id
        db.commit()
    return message_id


def assert_no_connection(database):
    assert database.kw["bind"].pool.checkedout() == 0, "Provider I/O must not hold a database connection"


@pytest.mark.asyncio
async def test_sms_send_and_status_connectivity_do_not_assert_delivery(database):
    message_id = queued_sms(database)
    delivery_code = 1
    calls = []

    def respond(request):
        assert_no_connection(database)
        calls.append(request.url.path)
        if request.url.path.endswith("send.json"):
            return httpx.Response(200, json={"return": {"status": 200}, "entries": [{"messageid": 12345}]})
        return httpx.Response(200, json={"return": {"status": 200}, "entries": [{"messageid": 12345, "status": delivery_code}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gateway = KavenegarSMS(client)
        assert (await run_once(database, gateway))["sent"] == 1
        with database() as db:
            row = observation(db, "clinic-bahar", "sms_kavenegar")
            assert (row.status, row.code) == ("healthy", "SMS_SEND_ACCEPTED")
            assert db.get(MessageOutbox, message_id).status == "SENT"
            assert observation(db, "clinic-niloufar", "sms_kavenegar") is None
            db.get(SMSReceiptPoll, message_id).next_poll_at = now_utc() - timedelta(seconds=1)
            db.commit()
        assert (await poll_sms_receipts(database, gateway))["checked"] == 1
        with database() as db:
            assert observation(db, "clinic-bahar", "sms_kavenegar").code == "SMS_DELIVERY_SENT"
            assert db.get(MessageOutbox, message_id).status == "SENT"
            db.get(SMSReceiptPoll, message_id).next_poll_at = now_utc() - timedelta(seconds=1)
            db.commit()
        delivery_code = 6
        assert (await poll_sms_receipts(database, gateway))["failed"] == 1
    with database() as db:
        row = observation(db, "clinic-bahar", "sms_kavenegar")
        assert (row.status, row.code) == ("healthy", "SMS_DELIVERY_FAILED")
        assert db.get(MessageOutbox, message_id).status == "FAILED"
        assert db.get(SMSReceiptPoll, message_id).stopped_at is not None
        assert type(row.latency_ms) is int and row.latency_ms >= 0
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_accepted_sms_settles_after_inflight_deactivation_but_new_work_is_denied(database):
    message_id = queued_sms(database)
    with database() as db:
        not_started = reserve_cost(db, "clinic-bahar", "not-started-before-disable", "sms_kavenegar", "sms_segments", 1)
        db.commit()
    calls = []

    def respond(request):
        assert_no_connection(database)
        calls.append(request.url.path)
        # The provider has already received the request; a separate committed
        # administration transaction disables the clinic before its response.
        with database() as admin_db:
            ticket = admin_db.scalar(select(CostReservation).where(
                CostReservation.operation_key == f"sms:{message_id}:1"))
            assert ticket.status == "STARTED" and ticket.started_at is not None
            admin_db.execute(update(Tenant).where(Tenant.id == "clinic-bahar").values(active=False))
            admin_db.commit()
        return httpx.Response(200, json={"return": {"status": 200}, "entries": [{"messageid": 1234567, "cost": 123}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gateway = KavenegarSMS(client)
        report = await run_once(database, gateway)
        assert report["sent"] == 1 and report["unknown"] == report["failed"] == 0
        with database() as db:
            assert not db.get(Tenant, "clinic-bahar").active
            message = db.get(MessageOutbox, message_id)
            assert (message.status, message.provider_id, message.locked_until) == ("SENT", "1234567", None)
            ticket = db.scalar(select(CostReservation).where(CostReservation.operation_key == f"sms:{message_id}:1"))
            assert ticket.status == "SETTLED" and ticket.settled_at is not None
            charges = list(db.scalars(select(UsageCharge).where(UsageCharge.tenant_id == "clinic-bahar", UsageCharge.provider == "sms_kavenegar")))
            assert len(charges) == 2
            base = next(row for row in charges if row.reservation_id == ticket.id)
            adjustment = next(row for row in charges if row.adjusts_charge_id == base.id)
            assert base.cost_micro_toman is None and base.evidence["basis"] == "unpriced_development"
            assert adjustment.cost_micro_toman == 12_300_000
            assert adjustment.evidence["vendor_total_micro_toman"] == 12_300_000
            assert observation(db, "clinic-bahar", "sms_kavenegar") is None
            next_message = MessageOutbox(tenant_id=message.tenant_id, appointment_id=message.appointment_id,
                recipient_encrypted=message.recipient_encrypted, purpose=message.purpose, template=message.template,
                payload=dict(message.payload), dedupe_key="after-clinic-disabled")
            db.add(next_message)
            db.commit()
            next_id = next_message.id
            with pytest.raises(HTTPException, match="TENANT_NOT_FOUND"):
                reserve_cost(db, "clinic-bahar", "new-after-disable", "sms_kavenegar", "sms_segments", 1)
            db.rollback()
            with pytest.raises(HTTPException, match="TENANT_NOT_FOUND"):
                mark_cost_started(db, not_started["id"])
            db.rollback()
        assert (await run_once(database, gateway))["suppressed"] == 1
    with database() as db:
        assert db.get(MessageOutbox, next_id).status == "SUPPRESSED"
        assert db.get(CostReservation, not_started["id"]).status == "UNPRICED"
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("case,expected,network_calls", [
    ("malformed", ("degraded", "INVALID_SMS_RESPONSE"), 1),
    ("timeout", ("degraded", "PROVIDER_TIMEOUT"), 1),
    ("decline", ("degraded", "SMS_REJECTED"), 1),
    ("configuration", None, 0),
    ("circuit", None, 0),
    ("demo", None, 0),
])
async def test_sms_send_health_excludes_local_and_synthetic_outcomes(database, monkeypatch, case, expected, network_calls):
    queued_sms(database)
    calls = []
    if case == "configuration":
        monkeypatch.delenv("KAVENEGAR_SENDER")
    elif case == "circuit":
        _breakers["sms-send"] = CircuitBreaker(failures=3, opened_at=time.monotonic())
    elif case == "demo":
        monkeypatch.setattr(settings, "demo_mode", True)

    def respond(request):
        assert_no_connection(database)
        calls.append(request.url.path)
        if case == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(200, json={"return": {"status": 400 if case == "decline" else 200}, "entries": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        result = await run_once(database, KavenegarSMS(client))
    with database() as db:
        row = observation(db, "clinic-bahar", "sms_kavenegar")
        assert ((row.status, row.code) if row else None) == expected
        assert observation(db, "clinic-niloufar", "sms_kavenegar") is None
    assert len(calls) == network_calls
    assert result["simulated" if case == "demo" else "unknown" if case in {"malformed", "timeout"} else "failed"] == 1


@pytest.mark.asyncio
async def test_mismatched_receipt_degrades_but_local_poll_rejection_does_not_refresh_health(database, monkeypatch):
    message_id = queued_sms(database)
    with database() as db:
        message = db.get(MessageOutbox, message_id)
        message.status, message.provider_id = "SENT", "12345"
        db.add(SMSReceiptPoll(message_id=message_id, tenant_id=message.tenant_id))
        db.commit()

    def respond(request):
        assert_no_connection(database)
        return httpx.Response(200, json={"return": {"status": 200}, "entries": [{"messageid": 99999, "status": 10}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gateway = KavenegarSMS(client)
        assert (await poll_sms_receipts(database, gateway))["errors"] == 1
        with database() as db:
            row = observation(db, "clinic-bahar", "sms_kavenegar")
            assert (row.status, row.code) == ("degraded", "INVALID_SMS_STATUS")
            checked_at = row.checked_at
            assert db.get(MessageOutbox, message_id).status == "SENT"
            db.get(SMSReceiptPoll, message_id).next_poll_at = now_utc() - timedelta(seconds=1)
            db.commit()
        monkeypatch.delenv("KAVENEGAR_API_KEY")
        assert (await poll_sms_receipts(database, gateway))["errors"] == 1
    with database() as db:
        assert observation(db, "clinic-bahar", "sms_kavenegar").checked_at == checked_at
        assert db.get(MessageOutbox, message_id).status == "SENT"


def payment_booking(db, monkeypatch, *, sandbox=False):
    configure_operator(monkeypatch)
    monkeypatch.setenv("PAYMENT_MERCHANTS_JSON", json.dumps({"niloufar-v1": {
        "merchant_id": "SYNTHETIC-MERCHANT-A", "sandbox": sandbox, "approved": True}}))
    policy = publish_real(db)
    return make_booking(db, policy["version"])


@pytest.mark.asyncio
async def test_payment_real_adapter_activity_is_scoped_and_callback_hint_is_not_evidence(database, monkeypatch):
    with database() as db:
        booking = payment_booking(db, monkeypatch)
        calls = []

        def respond(request):
            assert not db.in_transaction()
            assert_no_connection(database)
            calls.append(request.url.path)
            if request.url.path.endswith("request.json"):
                return httpx.Response(200, json={"data": {"code": 100, "authority": "MOCKAUTHORITY001"}})
            return httpx.Response(200, json={"data": {"code": 100, "ref_id": 123456}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            gateway = ZarinpalGateway(client, merchant_id="SYNTHETIC-MERCHANT-A", sandbox=False)
            monkeypatch.setattr("receptionist.payment_policy.gateway_for_intent", lambda intent: gateway)
            payment = await create_payment(db, "clinic-niloufar", booking["id"])
            row = observation(db, "clinic-niloufar", "payment_primary")
            assert (row.status, row.code) == ("healthy", "PAYMENT_REQUEST_ACCEPTED")
            checked_at = row.checked_at
            assert observation(db, "clinic-bahar", "payment_primary") is None
            authority = db.get(PaymentIntent, payment["id"]).authority
            assert (await payment_callback(authority, "NOK", db))["status"] == "NOT_COMPLETED"
            assert observation(db, "clinic-niloufar", "payment_primary").checked_at == checked_at
            assert len(calls) == 1
            assert (await payment_callback(authority, "OK", db))["status"] == "SETTLED"
            row = observation(db, "clinic-niloufar", "payment_primary")
            assert (row.status, row.code) == ("healthy", "PAYMENT_VERIFIED")
            assert db.get(Appointment, booking["id"]).status == "CONFIRMED"
        assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("case,expected_code,expected_health", [
    ("request_decline", "PAYMENT_REJECTED", "degraded"),
    ("request_malformed", "INVALID_PAYMENT_RESPONSE", "degraded"),
    ("verify_decline", "PAYMENT_NOT_SETTLED", "degraded"),
    ("verify_timeout", "PROVIDER_TIMEOUT", "degraded"),
])
async def test_payment_io_failures_persist_connectivity_without_claiming_settlement(database, monkeypatch, case, expected_code, expected_health):
    with database() as db:
        booking = payment_booking(db, monkeypatch)

        def respond(request):
            assert not db.in_transaction()
            if request.url.path.endswith("request.json"):
                if case == "request_decline":
                    return httpx.Response(200, json={"data": {"code": -1}})
                if case == "request_malformed":
                    return httpx.Response(200, json={"data": {"code": 100}})
                return httpx.Response(200, json={"data": {"code": 100, "authority": "MOCKAUTHORITY002"}})
            if case == "verify_timeout":
                raise httpx.ReadTimeout("synthetic timeout", request=request)
            return httpx.Response(200, json={"data": {"code": -21}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            gateway = ZarinpalGateway(client, merchant_id="SYNTHETIC-MERCHANT-A", sandbox=False)
            monkeypatch.setattr("receptionist.payment_policy.gateway_for_intent", lambda intent: gateway)
            payment = await create_payment(db, "clinic-niloufar", booking["id"])
            if case.startswith("verify"):
                authority = db.get(PaymentIntent, payment["id"]).authority
                with pytest.raises(HTTPException, match="PAYMENT_VERIFICATION_UNAVAILABLE"):
                    await payment_callback(authority, "OK", db)
                db.rollback()  # Request cleanup must not erase the committed observation.
    with database() as restarted:
        row = observation(restarted, "clinic-niloufar", "payment_primary")
        assert (row.status, row.code) == (expected_health, expected_code)
        assert restarted.get(Appointment, booking["id"]).status == "PENDING_PAYMENT"
        assert restarted.get(PaymentIntent, payment["id"]).status != "SETTLED"


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["sandbox", "local_configuration", "demo"])
async def test_payment_sandbox_simulation_and_pre_io_rejection_do_not_mark_live_provider(database, monkeypatch, case):
    with database() as db:
        booking = payment_booking(db, monkeypatch, sandbox=case == "sandbox")
        calls = []
        if case == "local_configuration":
            monkeypatch.setenv("PUBLIC_BASE_URL", "http://unsafe.example.test")
        elif case == "demo":
            monkeypatch.setattr(settings, "demo_mode", True)

        def respond(request):
            assert not db.in_transaction()
            calls.append(request.url.path)
            return httpx.Response(200, json={"data": {"code": 100, "authority": "MOCKAUTHORITY003", "ref_id": 654321}})

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            gateway = ZarinpalGateway(client, merchant_id="SYNTHETIC-MERCHANT-A", sandbox=case == "sandbox")
            monkeypatch.setattr("receptionist.payment_policy.gateway_for_intent", lambda intent: gateway)
            payment = await create_payment(db, "clinic-niloufar", booking["id"])
            if case == "sandbox":
                authority = db.get(PaymentIntent, payment["id"]).authority
                assert (await payment_callback(authority, "OK", db))["status"] == "SETTLED"
            else:
                assert payment["status"] == ("DEMO_PENDING" if case == "demo" else "FAILED")
            assert observation(db, "clinic-niloufar", "payment_primary") is None
        assert len(calls) == (2 if case == "sandbox" else 0)
