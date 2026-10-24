"""Actual durable event chains, on-call escalation and bounded outreach tests."""
from datetime import timedelta
import json
import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from receptionist.config import settings
from receptionist.db import now_utc
from receptionist.models import Appointment, Membership, MessageOutbox, StaffTask, Tenant
from receptionist.models_finance import CostReservation, UsageCharge
from receptionist.models_ops_control import AlertDelivery, OperationalAlert, SMSReceiptPoll, VoiceOutreach
from receptionist.models_voice import CallSession
from receptionist.messaging_controls import (VoiceReminderInput, poll_sms_receipts, queue_voice, run_voice_jobs, sms_segment_count)
from receptionist.operations import run_once
from receptionist.ops_controls import (AlertActionInput, OnCallInput, alert_action, append_trace, configure_oncall,
    dispatch_alerts, evaluate_alerts, raise_alert, reconstruct)
from receptionist.partners import ChannelInput, channel_permission
from receptionist.privacy_controls import ContactInput, contact_preference
from receptionist.providers import ProviderError
from receptionist.security import encrypt
from test_core import create, database as database
from test_finance_privacy_v2 import grant, owner, purpose, setup_costs


def synthetic_call(db, tenant="clinic-bahar"):
    row = CallSession(tenant_id=tenant, token_hash="0" * 64, channel="web", state="START", policy_version=1,
        policy_snapshot={}, context_encrypted=encrypt("{}"), expires_at=now_utc() + timedelta(hours=1))
    db.add(row)
    db.flush()
    return row


def test_durable_correlated_trace_reconstructs_in_new_session_without_content(database):
    with database() as db:
        call = synthetic_call(db)
        booking = create(db)
        message = db.scalar(select(MessageOutbox).where(MessageOutbox.appointment_id == booking["id"]))
        start = append_trace(db, "clinic-bahar", "trace-start", "call.started", call_id=call.id,
            versions={"app": "v2", "fsm": "state-v2"}, attributes={"status": "START"})
        tool = append_trace(db, "clinic-bahar", "trace-tool", "calendar.created", call_id=call.id,
            appointment_id=booking["id"], parent_id=start.id, versions={"calendar": "transactional-v2"}, attributes={"duration_ms": 42})
        append_trace(db, "clinic-bahar", "trace-job", "notification.queued", appointment_id=booking["id"],
            parent_id=tool.id, job_id=message.id, attributes={"status": "QUEUED"})
        call_id = call.id
        db.commit()
    with database() as restarted:
        result = reconstruct(call_id, owner(restarted), restarted)
        assert [event["event"] for event in result["events"]] == ["call.started", "calendar.created", "notification.queued"]
        assert "09123456789" not in json.dumps(result, default=str)
        with pytest.raises(HTTPException):
            append_trace(restarted, "clinic-bahar", "sensitive", "trace.bad", attributes={"text": "medical details"})
        with pytest.raises(HTTPException):
            append_trace(restarted, "clinic-bahar", "sensitive-phone", "trace.bad", attributes={"status": "09123456789"})
        with pytest.raises(HTTPException):
            append_trace(restarted, "clinic-niloufar", "cross-tenant", "trace.bad", call_id=call_id)


def test_trace_reservation_uuid_uses_real_scope_instead_of_sensitive_digit_heuristic(database):
    from receptionist.billing import reserve_cost
    from receptionist.privacy_controls import redact_text
    identifier = "11111111-1111-4111-8111-091234567890"
    assert redact_text(identifier) != identifier
    with database() as db:
        call = synthetic_call(db)
        ticket = reserve_cost(db, "clinic-bahar", "trace-reservation", "speech_primary", "stt_audio_seconds", 1, call_id=call.id)
        row = db.get(CostReservation, ticket["id"])
        row.id = identifier
        db.flush()
        trace = append_trace(db, "clinic-bahar", "known-cost-trace", "provider.reserved", call_id=call.id,
            provider="speech_primary", attributes={"reservation_id": identifier, "quantity": "1", "unit": "second"})
        assert trace.attributes["reservation_id"] == identifier
        with pytest.raises(HTTPException, match="TRACE_RESERVATION_NOT_FOUND"):
            append_trace(db, "clinic-niloufar", "foreign-cost-trace", "provider.reserved", attributes={"reservation_id": identifier})
        with pytest.raises(HTTPException, match="TRACE_RESERVATION_NOT_FOUND"):
            append_trace(db, "clinic-bahar", "wrong-provider-trace", "provider.reserved", provider="calendar_primary", attributes={"reservation_id": identifier})
        with pytest.raises(HTTPException, match="TRACE_RESERVATION_NOT_FOUND"):
            append_trace(db, "clinic-bahar", "missing-cost-trace", "provider.reserved", attributes={"reservation_id": "22222222-2222-4222-8222-091234567890"})
        with pytest.raises(HTTPException, match="INVALID_TRACE_RESERVATION"):
            append_trace(db, "clinic-bahar", "plain-phone-trace", "provider.reserved", attributes={"reservation_id": "09123456789"})
        with pytest.raises(HTTPException, match="SENSITIVE_TRACE_VALUE"):
            append_trace(db, "clinic-bahar", "phone-code-trace", "provider.reserved", attributes={"status": "09123456789"})


def test_alert_delivers_once_escalates_and_resolves_linked_tasks(database):
    with database() as db:
        actor = owner(db)
        second = db.scalar(select(Membership).where(Membership.tenant_id == actor.tenant_id, Membership.user_id != actor.id))
        second.role = "technical"
        db.commit()
        configure_oncall(OnCallInput(enabled=True, user_ids=[actor.id, second.user_id], escalation_minutes=1), actor, db)
        alert = raise_alert(db, actor.tenant_id, "SPEND_SPIKE", "unique-spike", {"cost_micro_toman": 500000000}, "critical")
        assert dispatch_alerts(db, actor.tenant_id)["dispatched"] == 1
        assert dispatch_alerts(db, actor.tenant_id)["dispatched"] == 0
        alert.created_at = now_utc() - timedelta(minutes=2)
        db.commit()
        assert dispatch_alerts(db, actor.tenant_id)["dispatched"] == 1
        db.commit()
        deliveries = list(db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == alert.id)))
        assert len(deliveries) == 2 and {x.user_id for x in deliveries} == {actor.id, second.user_id}
        assert all(db.get(StaffTask, item.task_id).status == "OPEN" for item in deliveries)
        alert_action(alert.id, AlertActionInput(action="ACKNOWLEDGE", evidence_reference="fixture-investigation"), actor, db)
        assert dispatch_alerts(db, actor.tenant_id)["dispatched"] == 0
        alert_action(alert.id, AlertActionInput(action="RESOLVE", evidence_reference="fixture-resolution"), actor, db)
        assert all(db.get(StaffTask, item.task_id).status == "RESOLVED" for item in deliveries)


def test_cost_spike_uses_exact_charge_evidence(database):
    from receptionist.billing import reserve_cost, mark_cost_started, settle_cost
    with database() as db:
        actor = owner(db)
        setup_costs(db, cap=100)
        configure_oncall(OnCallInput(enabled=True, user_ids=[actor.id], spike_cap_toman=5), actor, db)
        ticket = reserve_cost(db, actor.tenant_id, "spike-source", "speech_primary", "stt_audio_seconds", 90)
        mark_cost_started(db, ticket["id"])
        settle_cost(db, ticket["id"], 85, "spike-receipt")
        db.commit()
        evaluate_alerts(db, actor.tenant_id)
        db.commit()
        kinds = set(db.scalars(select(OperationalAlert.kind).where(OperationalAlert.tenant_id == actor.tenant_id)))
        assert {"SPEND_SPIKE", "MONETARY_SOFT_CAP"}.issubset(kinds)


def test_sms_segments_charge_actual_unicode_transport_units():
    assert sms_segment_count("x" * 160) == 1
    assert sms_segment_count("x" * 161) == 2
    assert sms_segment_count("آ" * 70) == 1
    assert sms_segment_count("آ" * 71) == 2
    assert sms_segment_count("^" * 81) == 2
    assert sms_segment_count("😀" * 36) == 2
    with pytest.raises(HTTPException):
        sms_segment_count("آ" * 671)


@pytest.mark.asyncio
async def test_real_sms_worker_records_vendor_charge_and_neutral_body(database, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    with database() as db:
        db.execute(update(MessageOutbox).values(status="SIMULATED"))
        booking = create(db, key="sms-new-one")
        db.execute(update(Appointment).values(reminder_opt_in=False))
        db.commit()
    class Gateway:
        bodies = []
        async def send(self, phone, body, **kwargs):
            self.bodies.append(body)
            return {"provider_id": "synthetic-provider-1", "cost_rial": 123}
    gateway = Gateway()
    result = await run_once(database, gateway)
    assert result["sent"] == 1
    with database() as db:
        message = db.scalar(select(MessageOutbox).where(MessageOutbox.appointment_id == booking["id"]))
        assert db.get(Tenant, "clinic-bahar").name not in gateway.bodies[0]
        assert db.get(SMSReceiptPoll, message.id)
        charges = list(db.scalars(select(UsageCharge).where(UsageCharge.provider == "sms_kavenegar")))
        assert sum(c.cost_micro_toman or 0 for c in charges) == 12_300_000


@pytest.mark.asyncio
async def test_trusted_sms_receipt_poller_stops_terminal_and_avoids_duplicate_delivery(database, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    with database() as db:
        message = db.scalar(select(MessageOutbox).limit(1))
        message.status, message.provider_id = "SENT", "synthetic-status-1"
        db.add(SMSReceiptPoll(tenant_id=message.tenant_id, message_id=message.id))
        db.commit()
        message_id = message.id
    class Gateway:
        calls = 0
        async def delivery(self, provider_id):
            self.calls += 1
            return "DELIVERED"
    gateway = Gateway()
    assert (await poll_sms_receipts(database, gateway))["delivered"] == 1
    assert (await poll_sms_receipts(database, gateway))["checked"] == 0
    assert gateway.calls == 1
    with database() as db:
        assert db.get(MessageOutbox, message_id).status == "DELIVERED"
        assert db.get(SMSReceiptPoll, message_id).stopped_at


def voice_fixture(db):
    actor = owner(db)
    purpose(db, "reminder")
    grant(db, "reminder")
    channel_permission(ChannelInput(phone="09123456789", channel="voice", purpose="reminder", granted=True, evidence_reference="patient-request-fixture"), actor, db)
    booking = create(db, key="voice-reminder-fixture", reminder_opt_in=True)
    return actor, booking


@pytest.mark.asyncio
async def test_outbound_unknown_is_read_back_never_redialed_and_voicemail_default_off(database, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr("receptionist.messaging_controls.next_permitted_time", lambda tenant, moment: moment)
    with database() as db:
        actor, booking = voice_fixture(db)
        result = queue_voice(VoiceReminderInput(appointment_id=booking["id"], idempotency_key="voice-job-one", patient_voice_request_confirmed=True), actor, db)
    class Gateway:
        configured = True
        origins = reads = 0
        async def originate(self, job, phone, seconds, voicemail):
            self.origins += 1
            assert voicemail is False and seconds == 60
            raise ProviderError("NETWORK_TIMEOUT", unknown_outcome=True)
        async def read(self, job):
            self.reads += 1
            return {"reference": "voice-result-one", "status": "COMPLETED", "billable_seconds": 22}
    gateway = Gateway()
    assert (await run_voice_jobs(database, gateway))["unknown"] == 1
    with database() as db:
        job = db.get(VoiceOutreach, result["id"])
        assert db.get(CostReservation, job.reservation_id).status == "UNKNOWN"
        job.not_before = now_utc() - timedelta(seconds=1)
        db.commit()
    assert (await run_voice_jobs(database, gateway))["reconciled"] == 1
    assert gateway.origins == 1 and gateway.reads == 1
    with database() as db:
        job = db.get(VoiceOutreach, result["id"])
        assert job.status == "COMPLETED" and db.get(CostReservation, job.reservation_id).status == "SETTLED"


@pytest.mark.asyncio
async def test_voice_withdrawal_and_quiet_hours_suppress_before_adapter(database, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    with database() as db:
        actor, booking = voice_fixture(db)
        result = queue_voice(VoiceReminderInput(appointment_id=booking["id"], idempotency_key="voice-withdrawn", patient_voice_request_confirmed=True), actor, db)
        grant(db, "reminder", False)
    class Never:
        configured = True
        async def originate(self, *args):
            raise AssertionError("Withdrawn job must not call the provider")
    assert (await run_voice_jobs(database, Never()))["suppressed"] == 1
    with database() as db:
        assert db.get(VoiceOutreach, result["id"]).status == "SUPPRESSED"


def test_contact_preferences_do_not_reveal_names_or_clinic_without_permission(database):
    from receptionist.privacy_controls import neutral_message
    with database() as db:
        actor = owner(db)
        phone = "09123456789"
        from receptionist.security import hash_phone
        contact_preference(ContactInput(phone=phone, shared_phone=False, clinic_name_allowed=True, evidence_reference="confirmed-private-phone"), actor, db)
        assert neutral_message(db, actor.tenant_id, hash_phone(phone), "کلینیک نمونه: پیام پذیرش", "کلینیک نمونه").startswith("کلینیک نمونه")
        contact_preference(ContactInput(phone=phone, shared_phone=True, clinic_name_allowed=True, evidence_reference="confirmed-shared-phone"), actor, db)
        assert "کلینیک نمونه" not in neutral_message(db, actor.tenant_id, hash_phone(phone), "کلینیک نمونه: پیام پذیرش", "کلینیک نمونه")
