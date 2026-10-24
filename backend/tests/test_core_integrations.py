# ruff: noqa: F811 -- imported pytest fixture names are injected as arguments
"""Cross-module regressions for the completed core integration paths.

All provider responses below are synthetic protocol fixtures, never certification
of an external calendar, carrier or model.
"""
import asyncio
import hashlib
import hmac
import json
import time
from datetime import datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select

from receptionist import model_registry  # noqa: F401
from receptionist import api, bookings_ext, calendar_bridge, core_policy, provider_control, routing, sms_bridge, voice
from receptionist.access_controls import AccessControlMiddleware, retirement_policies
from receptionist.calendar_contract import HTTPPartnerCalendar, RemoteAppointment, RemoteSlot
from receptionist.config import validate_optional_providers, validate_origin
from receptionist.core import ReceptionService
from receptionist.core_runtime import drain_tasks, run_core_jobs
from receptionist.db import get_db, now_utc
from receptionist.locale import language_signal, number_words, spoken_administrative
from receptionist.models import Appointment, AuditEvent, MessageOutbox, Service, Tenant, User
from receptionist.models_core import (CalendarAuthority, CalendarSyncState, CatalogFact, CorePolicy, IntegrationCapability, PackageEntitlement, PackageUse, ProviderObservation, ServiceRule, SmsConversation)
from receptionist.models_finance import CostReservation, UsageCharge
from receptionist.models_privacy import PurposePolicy
from receptionist.models_voice import CallSession
from receptionist.providers import KavenegarSMS, ProviderError
from receptionist.security import Actor, decrypt, encrypt, hash_phone, issue_token
from receptionist.tool_gateway import ToolGateway, validate_model_tool_event
from test_core import create, database, future_day, slot_for  # noqa: F401


OWNER = Actor("demo-owner", "clinic-bahar", "owner", "Owner", "owner@example.test", "bahar")


def test_public_retention_notice_and_call_pin_use_strictest_published_cap(database):
    with database() as db:
        tenant = db.get(Tenant, OWNER.tenant_id)
        tenant.retention_days = 30
        db.add(PurposePolicy(tenant_id=tenant.id, purpose="processing", version=1, enabled=True,
            notice="پردازش ضروری برای پذیرش", retention_days=7, backup_expiry_days=14,
            consent_valid_days=30, evidence_reference="synthetic-review", approved_by=OWNER.id))
        db.commit()
        public = voice.public_clinic(tenant, db)
        assert public["transcript_retention_days"] == 7
        assert "۷ روز پس از پایان گفت‌وگو" in public["notice"]
        assert public["processing_policy_version"] == "processing:v1"
        call, _ = voice.new_session(db, tenant)
        assert call.policy_snapshot["retention_days"] == 7
        assert call.policy_snapshot["processing_notice"] == public["processing_notice"]
        tenant.retention_days = 3
        db.commit()
        assert voice.public_clinic(tenant, db)["transcript_retention_days"] == 3
        assert call.policy_snapshot["retention_days"] == 7


@pytest.fixture
def client(database):
    app = FastAPI()
    for router in (api.router, core_policy.router, bookings_ext.router, calendar_bridge.router, routing.router,
                   provider_control.router, sms_bridge.router, voice.router):
        app.include_router(router)
    app.add_middleware(AccessControlMiddleware, session_factory=database, policies=[])
    def dependency():
        with database() as db:
            yield db
    app.dependency_overrides[get_db] = dependency
    with TestClient(app) as value:
        yield value


def auth(database, tenant="clinic-bahar"):
    with database() as db:
        return {"Authorization": "Bearer " + issue_token(db.get(User, "demo-owner"), tenant)}


def remote_record(**changes):
    start = now_utc().replace(hour=6, minute=30, second=0, microsecond=0) + timedelta(days=3)
    value = {"id": "remote-1", "account_id": "account-bahar", "revision": "r1", "status": "CONFIRMED",
        "slot_id": "remote-slot", "provider_id": "provider-bahar-1", "service_id": "service-consultation",
        "patient_token": hash_phone("09123456789"), "start_at": start.isoformat(),
        "end_at": (start + timedelta(minutes=20)).isoformat(), "reference": "REMOTE-1234",
        "payment_url": None, "payment_expires_at": None}
    return {**value, **changes}


def external(db):
    row = db.get(CalendarAuthority, OWNER.tenant_id)
    row.kind, row.provider_key = "external", "calendar_primary"
    row.capabilities = {"account_id": "account-bahar"}
    row.version += 1
    row.expires_at = now_utc() + timedelta(days=30)
    db.commit()
    return row


def capabilities():
    return {"protocol": "hamava-calendar-v1", "account_id": "account-bahar", "revision": "v1",
        **{k: True for k in ("conditional_create", "conditional_update", "idempotency", "readback", "slots", "holds", "cancel", "update", "reconciliation", "changes")}}


async def test_calendar_unknown_write_is_reconciled_once_and_replay_reads_current_authority(database, monkeypatch):
    monkeypatch.setenv("CALENDAR_PARTNER_APPROVED", "true")
    monkeypatch.setenv("APPROVED_PROVIDER_HOSTS", "calendar.example.test")
    seen = []
    current = remote_record()
    def handler(request):
        seen.append((request.method, request.url.path))
        assert request.headers["x-calendar-account"] == "account-bahar"
        if request.url.path == "/capabilities":
            return httpx.Response(200, json=capabilities())
        if request.method == "POST":
            assert request.headers["if-match"] == "r1"
            assert len(request.headers["idempotency-key"]) == 64
            raise httpx.ReadTimeout("synthetic committed response lost")
        if request.url.path == "/operations/by-idempotency-key":
            return httpx.Response(200, json={"account_id": "account-bahar", "state": "COMMITTED", "appointment_id": "remote-1"})
        return httpx.Response(200, json=current)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        connector = HTTPPartnerCalendar("https://calendar.example.test", "synthetic", "account-bahar", client=http)
        with database() as db:
            external(db)
            request = {k: current[k] for k in ("slot_id", "provider_id", "service_id", "patient_token")}
            request.update(revision="r1", patient_name="نمونه آزمایشی", phone="09123456789")
            row = calendar_bridge.queue_operation(db, OWNER.tenant_id, "create", request, "calendar-unknown-001", OWNER.id, phone_hash=current["patient_token"])
            db.commit()
            first = await calendar_bridge.execute_operation(db, row, connector=connector)
            assert first["status"] == "PENDING_CONFIRMATION" and first["operation_status"] == "UNKNOWN"
            assert first["result"] is None
            assert db.scalar(select(func.count()).select_from(CostReservation).where(CostReservation.status == "UNKNOWN")) == 1
            second = await calendar_bridge.execute_operation(db, row, connector=connector)
            assert second["result"]["status"] == "CONFIRMED"
            current["status"], current["revision"] = "CANCELED", "r2"
            replay = await calendar_bridge.execute_operation(db, row, connector=connector)
            assert replay["result"]["status"] == "CANCELED" and replay["result"]["revision"] == "r2"
            count = len(seen)
            connector.account_id = "changed-account"
            changed = await calendar_bridge.execute_operation(db, row, connector=connector)
            assert changed["result"] is None and changed["error_code"] == "CALENDAR_ACCOUNT_APPROVAL_CHANGED"
            assert len(seen) == count
            assert sum(method == "POST" for method, path in seen) == 1
            assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.reference == "REMOTE-1234")) == 0
            with pytest.raises(HTTPException, match="IDEMPOTENCY_MISMATCH"):
                calendar_bridge.queue_operation(db, OWNER.tenant_id, "create", {**request, "slot_id": "other"}, "calendar-unknown-001", OWNER.id)
            db.rollback()
            with pytest.raises(HTTPException) as rejected:
                calendar_bridge.owned_booking(db, "clinic-niloufar", "remote-1")
            assert rejected.value.status_code == 404


async def test_calendar_contract_scope_id_match_and_interval_fail_closed(monkeypatch):
    monkeypatch.setenv("CALENDAR_PARTNER_APPROVED", "true")
    monkeypatch.setenv("APPROVED_PROVIDER_HOSTS", "calendar.example.test")
    def handler(request):
        if request.url.path == "/capabilities":
            return httpx.Response(200, json=capabilities())
        if request.method == "POST":
            return httpx.Response(200, json={"account_id": "account-bahar", "id": "wrong-id"})
        return httpx.Response(200, json=remote_record(account_id="other-clinic"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        adapter = HTTPPartnerCalendar("https://calendar.example.test", "synthetic", "account-bahar", client=http)
        with pytest.raises(ProviderError, match="SCOPE"):
            await adapter.get("remote-1")
        with pytest.raises(ProviderError) as lost:
            await adapter.cancel("remote-1", "r1", "cancel-key")
        assert lost.value.unknown_outcome
    with pytest.raises(ValidationError):
        RemoteAppointment.model_validate(remote_record(end_at=now_utc().isoformat()))
    with pytest.raises(ValidationError):
        RemoteSlot.model_validate({"id": "x", "provider_id": "p", "service_id": "s", "start_at": "2026-01-01T00:00:00", "end_at": "2026-01-01T01:00:00Z", "expires_at": "2026-01-01T00:30:00Z", "revision": "1"})


def test_external_api_hold_pending_inventory_and_fresh_readback(client, database, monkeypatch):
    value = remote_record()
    class Connector:
        account_id = "account-bahar"
        async def hold(self, request, key):
            return {"account_id": "account-bahar", "id": "held-1", "slot_id": request["slot_id"], "status": "HELD", "expires_at": (now_utc() + timedelta(minutes=5)).isoformat()}
        async def create(self, request, key):
            return {**value, "patient_token": request["patient_token"]}
        async def get(self, remote_id):
            assert remote_id == value["id"]
            return value
    monkeypatch.setattr(calendar_bridge, "connector_for", lambda tenant: Connector())
    with database() as db:
        external(db)
        slot = {"id": "remote-slot", "provider_id": value["provider_id"], "service_id": value["service_id"], "start_at": value["start_at"], "end_at": value["end_at"], "revision": "r1", "expires_at": (now_utc() + timedelta(minutes=5)).isoformat()}
        signed = calendar_bridge.encode_slot(db, OWNER.tenant_id, slot)["slot_id"]
    headers = auth(database)
    held = client.post("/api/v1/holds", headers=headers, json={"slot_id": signed, "idempotency_key": "held-request-001"})
    assert held.status_code == 201, held.text
    assert held.json()["status"] == "HELD"
    booked = client.post("/api/v1/appointments", headers=headers, json={"slot_id": signed, "hold_id": held.json()["id"], "patient_name": "مراجع نمونه", "phone": "09123456789", "confirmed": True, "idempotency_key": "remote-booking-001"})
    assert booked.status_code == 201, booked.text
    item = booked.json()
    assert item["status"] == "CONFIRMED" and item["local_time"] == "10:00"
    assert item["attendance"] is None and item["notification_status"] == "UNKNOWN"
    listing = client.get("/api/v1/appointments", headers=headers).json()
    assert listing[0]["status"] == "READBACK_REQUIRED" and listing[0]["last_known_status"] == "CONFIRMED"
    assert client.get("/api/v1/appointments/" + item["id"], headers=headers).json()["status"] == "CONFIRMED"
    assert client.get("/api/v1/appointments/" + item["id"], headers=auth(database, "clinic-niloufar")).status_code == 404
    with database() as db:
        with pytest.raises(HTTPException, match="EXTERNAL_CALENDAR_AUTHORITY"):
            ReceptionService(db, OWNER.tenant_id).slots(value["provider_id"], value["service_id"], future_day())


def test_revision_event_replay_invalidates_confirmation_and_detects_gap(database):
    with database() as db:
        external(db)
        value = remote_record()
        row = calendar_bridge.queue_operation(db, OWNER.tenant_id, "create", {"phone": "09123456789"}, "revision-booking-001", OWNER.id)
        row.status, row.remote_id = "SUCCEEDED", value["id"]
        row.result_encrypted = encrypt(json.dumps(value))
        db.commit()
        event = {"event_id": "event-3", "remote_id": "remote-1", "revision": 3}
        assert calendar_bridge.apply_change(db, OWNER.tenant_id, event, "webhook")
        db.commit()
        assert db.get(CalendarSyncState, OWNER.tenant_id).status == "SYNC_REQUIRED"
        assert calendar_bridge.operation_dict(row)["operation_status"] == "READBACK_REQUIRED"
        assert not calendar_bridge.apply_change(db, OWNER.tenant_id, event, "poll")
        with pytest.raises(HTTPException, match="REPLAY_MISMATCH"):
            calendar_bridge.apply_change(db, OWNER.tenant_id, {**event, "remote_id": "different"}, "webhook")


def test_fact_approval_detects_expiry_and_catalog_mutation(database):
    with database() as db:
        db.add(CorePolicy(tenant_id=OWNER.tenant_id, settings={"catalog_provenance_required": True}, approved_by=OWNER.id))
        db.commit()
        service = db.get(Service, "service-consultation")
        core_policy.require_facts(db, OWNER.tenant_id, "service", service)
        service.price_toman += 1
        with pytest.raises(HTTPException, match="CATALOG_FACT_REVIEW_REQUIRED"):
            core_policy.require_facts(db, OWNER.tenant_id, "service", service)
        core_policy.publish_facts(db, OWNER.tenant_id, "service", service, OWNER.id, source="synthetic approved owner statement", fields=["price_toman"])
        db.commit()
        core_policy.require_facts(db, OWNER.tenant_id, "service", service)
        latest = db.scalar(select(CatalogFact).where(CatalogFact.subject_id == service.id, CatalogFact.field == "price_toman").order_by(CatalogFact.version.desc()))
        latest.expires_at = now_utc() - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HTTPException, match="CATALOG_FACT_REVIEW_REQUIRED"):
            core_policy.require_facts(db, OWNER.tenant_id, "service", service)
    with pytest.raises(ValidationError):
        core_policy.FactApproval(subject_type="service", subject_id="service-consultation", fields=["name", "name"], source="test", effective_at=now_utc(), expires_at=now_utc()+timedelta(days=1), reason="test")


def test_package_usage_replay_cancel_and_reschedule_expiry_are_atomic(database):
    with database() as db:
        db.add(ServiceRule(service_id="service-consultation", tenant_id=OWNER.tenant_id, visit_policy="package", package_units=1))
        entitlement = PackageEntitlement(tenant_id=OWNER.tenant_id, phone_hash=hash_phone("09123456789"), service_ids=["service-consultation"], total_units=1,
            used_units=0, expires_at=now_utc()+timedelta(days=4), idempotency_key="package-test-001", request_hash="x"*64, reason_encrypted=encrypt("synthetic authorized credit"), reference="SYNTHETIC", created_by=OWNER.id)
        db.add(entitlement)
        db.commit()
        signed = slot_for(db)
        first = create(db, signed, package_entitlement_id=entitlement.id)
        assert create(db, signed, package_entitlement_id=entitlement.id)["id"] == first["id"]
        db.refresh(entitlement)
        assert entitlement.used_units == 1
        with pytest.raises(HTTPException, match="PACKAGE_ENTITLEMENT_REQUIRED"):
            create(db, slot_for(db, index=4), key="package-overdraw-001", package_entitlement_id=entitlement.id)
        db.rollback()
        target = slot_for(db, days=5)
        with pytest.raises(HTTPException, match="PACKAGE_ENTITLEMENT_REQUIRED"):
            ReceptionService(db, OWNER.tenant_id).reschedule_appointment(first["id"], target, "package-move-001", 1, verified=True)
        db.rollback()
        assert db.get(Appointment, first["id"]).start_at == datetime.fromisoformat(first["start_at"].replace("Z", "+00:00"))
        ReceptionService(db, OWNER.tenant_id).cancel_appointment(first["id"], "package-cancel-001", 1, verified=True)
        db.refresh(entitlement)
        assert entitlement.used_units == 0 and db.get(PackageUse, first["id"]).released
        ReceptionService(db, OWNER.tenant_id).cancel_appointment(first["id"], "package-cancel-001", 1, verified=True)
        db.refresh(entitlement)
        assert entitlement.used_units == 0


def test_series_partial_success_resumes_without_duplicate_and_discloses_each_outcome(client, database):
    with database() as db:
        signed = slot_for(db)
    booking = {"slot_id": signed, "patient_name": "مراجع نمونه", "phone": "09123456789", "confirmed": True, "idempotency_key": "ignored-child-request"}
    body = {"idempotency_key": "series-test-001", "bookings": [booking, booking]}
    headers = auth(database)
    first = client.post("/api/v1/booking-series", json=body, headers=headers)
    assert first.status_code == 201, first.text
    value = first.json()
    assert value["status"] == "PARTIAL" and len(value["outcomes"]) == 2
    assert sum(bool(row.get("appointment_id")) for row in value["outcomes"]) == 1
    replay = client.post("/api/v1/booking-series", json=body, headers=headers)
    assert replay.status_code == 201 and replay.json()["id"] == value["id"]
    resumed = client.post(f"/api/v1/booking-series/{value['id']}/resume", headers=headers)
    assert resumed.json()["status"] == "PARTIAL"


def test_sms_enrollment_continues_after_intent_reset_and_signed_receipts_are_idempotent(client, database, monkeypatch):
    monkeypatch.setenv("SMS_INBOUND_TENANTS_JSON", json.dumps({"10002000": "bahar"}))
    monkeypatch.setenv("SMS_INBOUND_WEBHOOK_SECRET", "synthetic-sms-secret-for-tests-only-0001")
    start = client.post("/api/v1/public/sessions", json={"clinic_slug": "bahar", "processing_consent": True}).json()
    sid, headers = start["session_id"], {"Authorization": "Bearer " + start["token"]}
    request = client.post(f"/api/v1/public/sessions/{sid}/sms/request", headers=headers, json={"phone": "09123456789", "sms_consent": True})
    assert request.status_code == 200 and request.json()["state"] == "VERIFY"
    verify = client.post(f"/api/v1/public/sessions/{sid}/turn", headers=headers, json={"text": "246810", "request_id": str(uuid4())})
    assert verify.status_code == 200 and verify.json()["state"] == "INTENT", verify.text
    def inbound(message_id, text, sender="09123456789"):
        body = json.dumps({"receiver": "10002000", "sender": sender, "message_id": message_id, "text": text}, ensure_ascii=False).encode()
        ts = str(int(time.time()))
        signature = hmac.new(b"synthetic-sms-secret-for-tests-only-0001", ts.encode()+b"."+body, hashlib.sha256).hexdigest()
        return client.post("/api/v1/internal/sms/inbound", content=body, headers={"Content-Type": "application/json", "X-Timestamp": ts, "X-Signature": signature})
    assert inbound("sms-1", "نوبت می خواهم").status_code == 200
    assert inbound("sms-2", "1").status_code == 200
    assert inbound("sms-3", "1").status_code == 200
    assert inbound("sms-4", future_day()).status_code == 200
    assert inbound("sms-5", "1").status_code == 200
    assert inbound("sms-6", "مراجع آزمایشی").status_code == 200
    with database() as db:
        call = db.get(CallSession, sid)
        assert call.state == "CONFIRM"
        assert voice.context(call)["sms_subject"] == hash_phone("09123456789")
    result = inbound("sms-7", "بله")
    assert result.status_code == 200, result.text
    assert inbound("sms-7", "بله").json()["replayed"] is True
    assert inbound("sms-7", "خیر").status_code == 409
    assert inbound("sms-other", "نوبت می خواهم", sender="09125556666").status_code == 409
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.session_id == sid)) == 1
        assert db.scalar(select(func.count()).select_from(SmsConversation).where(SmsConversation.call_id == sid)) == 7
        outbox = list(db.scalars(select(MessageOutbox).where(MessageOutbox.purpose == "conversation_reply")))
        assert len(outbox) == 7 and all("text_encrypted" in row.payload for row in outbox)


def test_strict_tool_boundary_rejects_tenant_and_proof_injection_and_deadline_rolls_back(database, monkeypatch):
    with pytest.raises(ValidationError):
        validate_model_tool_event({"event": "tool_call", "request_id": "synthetic-request", "tool": "slots", "arguments": {"tenant_id": "other", "provider_id": "p", "service_id": "s", "date": "2026-10-25"}})
    with database() as db:
        row, _ = voice.new_session(db, db.get(Tenant, OWNER.tenant_id))
        signed = slot_for(db)
        proxy = voice._TurnTransaction(db)
        gateway = ToolGateway(proxy, row, {})
        args = {"slot_id": signed, "patient_name": "نمونه آزمایشی", "phone": "09123456789", "confirmed": True, "idempotency_key": "tool-test-001"}
        with pytest.raises(HTTPException, match="VERIFICATION_REQUIRED"):
            gateway.call("book", args)
        ctx = {"phone": "09123456789", "verified_phone": hash_phone("09123456789")}
        gateway = ToolGateway(proxy, row, ctx)
        before = db.scalar(select(func.count()).select_from(Appointment))
        monkeypatch.setenv("TOOL_TIMEOUT_MS", "0")
        with pytest.raises(HTTPException, match="TOOL_DEADLINE"):
            gateway.call("book", args)
        db.rollback()
        assert db.scalar(select(func.count()).select_from(Appointment)) == before


async def test_runtime_is_fair_bounded_and_explicitly_reports_timeout(database, monkeypatch):
    monkeypatch.setenv("SPEECH_PROCESSOR_APPROVED", "true")
    monkeypatch.setenv("SPEECH_GATEWAY_TOKEN", "synthetic-token")
    monkeypatch.setenv("SPEECH_GATEWAY_URL", "https://speech.example.test")
    with database() as db:
        for i in range(22):
            db.add(Tenant(id=f"fair-{i:02}", name="Synthetic", slug=f"fair-{i:02}", mode="paused", working_hours={}, faq=[], holidays=[]))
        db.flush()
        for tenant_id in ["clinic-bahar", "clinic-niloufar", *[f"fair-{i:02}" for i in range(21)]]:
            provider_control.observation(db, tenant_id, "speech_primary", "healthy", "SYNTHETIC")
        db.commit()
        seen = []
        async def probe(db, tenant_id, provider):
            seen.append(tenant_id)
            provider_control.observation(db, tenant_id, provider, "healthy", "SYNTHETIC")
            db.commit()
        monkeypatch.setattr(provider_control, "probe", probe)
        value = await run_core_jobs(db)
        assert seen == ["fair-21"] and value["examined"] == 1 and value["max_remote_operations"] == 3
        async def slow(db, tenant_id, provider):
            await asyncio.sleep(10)
        monkeypatch.setattr(provider_control, "probe", slow)
        db.get(ProviderObservation, db.scalar(select(ProviderObservation.id).where(ProviderObservation.tenant_id == "fair-21"))).checked_at = now_utc()-timedelta(days=1)
        db.commit()
        started = time.monotonic()
        result = await run_core_jobs(db, budget_seconds=1)
        assert result["deadline_reached"] and time.monotonic()-started < 3
    finished = asyncio.create_task(asyncio.sleep(0))
    pending = asyncio.create_task(asyncio.sleep(10))
    result = await drain_tasks([finished, pending], grace=.01)
    assert result == {"completed": 1, "cancelled": 1} and pending.cancelled()


def test_readiness_needs_current_observation_and_privileged_access_has_no_raw_path(client, database, monkeypatch):
    monkeypatch.setenv("SPEECH_PROCESSOR_APPROVED", "true")
    monkeypatch.setenv("SPEECH_GATEWAY_TOKEN", "synthetic-token")
    with database() as db:
        result = provider_control.dependency_readiness(db, OWNER.tenant_id)
        assert not result["ready"]
        db.add(IntegrationCapability(tenant_id=OWNER.tenant_id, provider_key="speech_primary", kind="speech", operations=["transcribe_final"],
            endpoint_version="test-v1", model_version="test-model", region="IR", data_terms_reference="synthetic", verification_state="operator_attested", evidence_reference="synthetic", approved_by=OWNER.id, expires_at=now_utc()+timedelta(days=1)))
        provider_control.observation(db, OWNER.tenant_id, "speech_primary", "healthy", "HEALTH_OK")
        db.commit()
        assert provider_control.dependency_readiness(db, OWNER.tenant_id)["ready"]
        observed = db.scalar(select(ProviderObservation).where(ProviderObservation.tenant_id == OWNER.tenant_id))
        observed.checked_at -= timedelta(hours=1)
        db.commit()
        assert not provider_control.dependency_readiness(db, OWNER.tenant_id)["ready"]
    response = client.get("/api/v1/appointments/patient-specific-secret", headers={**auth(database), "X-Action-Reason": "synthetic authorized reception review"})
    assert response.status_code == 404
    with database() as db:
        receipt = db.scalar(select(AuditEvent).where(AuditEvent.action == "privileged.access").order_by(AuditEvent.created_at.desc()))
        assert receipt.details["route"] == "/api/v1/appointments/{appointment_id}"
        assert "patient-specific-secret" not in json.dumps(receipt.details)
        assert decrypt(receipt.details["reason_encrypted"]) == "synthetic authorized reception review"


def test_native_origins_configuration_and_version_retirement_fail_closed(monkeypatch):
    validate_origin("app://hamava", True)
    validate_origin("https://localhost", True)
    for origin in ("app://other", "https://*.example.test", "http://localhost", "https://example.test/path"):
        with pytest.raises(ValueError):
            validate_origin(origin, True)
    monkeypatch.setenv("SPEECH_PROCESSOR_APPROVED", "tru")
    with pytest.raises(ValueError, match="true or false"):
        validate_optional_providers(False)
    monkeypatch.delenv("SPEECH_PROCESSOR_APPROVED")
    monkeypatch.setenv("SMS_INBOUND_TENANTS_JSON", '{"10002000":"bahar"}')
    with pytest.raises(ValueError, match="SMS_INBOUND_WEBHOOK_SECRET"):
        validate_optional_providers(False)
    monkeypatch.delenv("SMS_INBOUND_TENANTS_JSON")
    policies = [{"prefix": "/api/v1", "successor": "/api/v2", "deprecated_at": "2020-01-01T00:00:00Z", "sunset_at": "2021-01-01T00:00:00Z"}]
    app = FastAPI()
    app.add_middleware(AccessControlMiddleware, policies=policies)
    with TestClient(app) as local:
        response = local.get("/api/v1/example")
        assert response.status_code == 410 and response.headers["Deprecation"].startswith("@")
        assert "GMT" in response.headers["Sunset"] and "successor-version" in response.headers["Link"]
    with pytest.raises(ValueError):
        retirement_policies(json.dumps([{**policies[0], "successor": "/api/v1"}]))


async def test_sms_missing_price_is_unknown_and_delivery_identifier_must_match(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER_APPROVED", "true")
    monkeypatch.setenv("KAVENEGAR_API_KEY", "synthetickey")
    monkeypatch.setenv("KAVENEGAR_SENDER", "test")
    def handler(request):
        return httpx.Response(200, json={"return": {"status": 200}, "entries": [{"messageid": 999, "status": 10}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        sms = KavenegarSMS(http)
        assert (await sms.send("09123456789", "synthetic"))["cost_rial"] is None
        with pytest.raises(ProviderError, match="INVALID_SMS_STATUS"):
            await sms.delivery("123")


def test_spoken_numbers_ids_and_language_routing_are_deterministic():
    assert number_words(1205) == "هزار و دویست و پنج"
    spoken = spoken_administrative("ساعت 16:30، مبلغ 1,250,000 تومان، کد B-1234ABCD و شماره 09123456789")
    assert not any(char.isdigit() for char in spoken)
    assert "تومان" in spoken and "سی" in spoken and "بی" in spoken
    assert language_signal("Please speak English")["language"] == "english"
    assert language_signal("مرحبا أريد موعد طبيب")["language"] == "arabic"


async def test_external_voice_booking_and_cancel_resume_only_verified_remote_results(database):
    value = remote_record()
    class Connector:
        account_id = "account-bahar"
        async def slots(self, provider, service, day):
            return [{"id": "remote-slot", "provider_id": provider, "service_id": service, "start_at": value["start_at"], "end_at": value["end_at"], "revision": "r1", "expires_at": (now_utc()+timedelta(minutes=5)).isoformat()}]
        async def hold(self, request, key):
            return {"id": "hold-1", "account_id": "account-bahar", "slot_id": "remote-slot", "status": "HELD", "expires_at": (now_utc()+timedelta(minutes=5)).isoformat()}
        async def create(self, request, key):
            assert request["patient_token"] == value["patient_token"]
            return value
        async def get(self, remote_id):
            return value
        async def cancel(self, remote_id, revision, key):
            value.update(status="CANCELED", revision="r2")
            return value
    with database() as db:
        external(db)
        row, _ = voice.new_session(db, db.get(Tenant, OWNER.tenant_id))
        def turn(text):
            return voice.execute_turn(db, row, voice.TurnInput(text=text, request_id=str(uuid4())))
        async def recover():
            from receptionist.models_core import ExternalCalendarOperation
            pending = voice.context(row)["pending_tool"]
            await calendar_bridge.execute_operation(db, db.get(ExternalCalendarOperation, pending["id"]), connector=Connector())
            return turn("ادامه بررسی")
        assert turn("نوبت می خواهم")["state"] == "SERVICE"
        assert turn("1")["state"] == "PROVIDER"
        assert turn("1")["state"] == "DATE"
        result = turn(future_day())
        assert result["state"] == "WAIT_CALENDAR" and result["conversation_state"]["pending_tool"]["operation"] == "slots"
        assert result["booking"] is None
        assert (await recover())["state"] == "OFFER"
        assert turn("1")["state"] == "WAIT_CALENDAR"
        assert (await recover())["state"] == "NAME"
        assert turn("مراجع آزمایشی")["state"] == "PHONE"
        assert turn("09123456789")["state"] == "VERIFY"
        assert turn("246810")["state"] == "CONFIRM"
        queued = turn("بله")
        assert queued["state"] == "WAIT_CALENDAR" and queued["booking"] is None
        result = await recover()
        assert result["booking"]["status"] == "CONFIRMED" and result["conversation_state"]["pending_tool"] is None
        assert turn("لغو نوبت")["state"] == "REFERENCE"
        assert turn("REMOTE-1234")["state"] == "PHONE"
        assert turn("09123456789")["state"] == "VERIFY"
        assert turn("246810")["state"] == "WAIT_CALENDAR"
        assert (await recover())["state"] == "CANCEL_CONFIRM"
        assert turn("بله")["state"] == "WAIT_CALENDAR"
        assert (await recover())["booking"]["status"] == "CANCELED"
        assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.session_id == row.id)) == 0


def test_first_followup_policy_service_specific_readback_and_configured_last_slot(database):
    with database() as db:
        prior = create(db)
        appointment = db.get(Appointment, prior["id"])
        appointment.attendance = "ATTENDED"
        appointment.start_at = now_utc()-timedelta(days=3)
        rule = ServiceRule(service_id="service-consultation", tenant_id=OWNER.tenant_id, visit_policy="first_visit",
                           preparation="اصل مدرک شناسایی همراه باشد.", insurance_notes="پوشش بیمه توسط پذیرش تایید می‌شود.")
        db.add(rule)
        db.commit()
        service = db.get(Service, rule.service_id)
        with pytest.raises(HTTPException, match="FIRST_VISIT_ONLY"):
            bookings_ext.check_eligibility(db, OWNER.tenant_id, service, appointment.phone_hash, at=now_utc()+timedelta(days=3))
        rule.visit_policy, rule.follow_up_days = "follow_up", 10
        db.commit()
        assert bookings_ext.check_eligibility(db, OWNER.tenant_id, service, appointment.phone_hash, at=now_utc()+timedelta(days=3)) == (None, 0)
        with pytest.raises(HTTPException, match="FOLLOW_UP_NOT_ELIGIBLE"):
            bookings_ext.check_eligibility(db, OWNER.tenant_id, service, appointment.phone_hash, at=now_utc()+timedelta(days=30))
        row, _ = voice.new_session(db, db.get(Tenant, OWNER.tenant_id))
        windows = {**core_policy.DEFAULT_WINDOWS, "غروب": [16.25, 17.25]}
        snapshot = {**row.policy_snapshot, "core_policy": {"version": 1, "time_windows": windows}}
        row.policy_snapshot = snapshot
        data = voice.context(row)
        data.update(provider_id="provider-bahar-1", service_id=service.id, patient_name="مراجع آزمایشی", phone="09123456789", verified_phone=appointment.phone_hash)
        voice.save_context(row, data)
        row.intent, row.state = "book", "DATE"
        db.commit()
        conversation = voice.Conversation(voice._TurnTransaction(db), row)
        result = conversation.find_slots(future_day()+" آخر وقت")
        actual = ReceptionService(db, OWNER.tenant_id).slots("provider-bahar-1", service.id, future_day())
        assert result["offers"][0]["start_at"] == actual[-1]["start_at"]
        conversation.ctx["chosen"] = result["offers"][0]
        confirmed = conversation.confirmation()
        assert rule.preparation in confirmed["reply"] and rule.insurance_notes in confirmed["reply"]
        from receptionist.locale import resolve_persian_datetime
        resolved = resolve_persian_datetime(future_day()+" غروب", row.started_at, time_windows=windows)
        assert resolved["time_window"] == [16.25, 17.25]


def test_versioned_routing_enforces_global_did_and_current_language_attestation(client, database, monkeypatch):
    monkeypatch.setenv("HUMAN_TRANSFER_TARGETS", "PJSIP/frontdesk")
    with database() as db:
        db.get(Tenant, OWNER.tenant_id).mode = "paused"
        db.get(Tenant, "clinic-niloufar").mode = "paused"
        db.commit()
    body = {"version": 0, "routes": [{"did": "02110002000", "provider": "audiosocket", "queue_id": "frontdesk", "transfer_target": "PJSIP/frontdesk"}],
        "language_routes": {"english": {"enabled": True, "script": "Your request is queued for staff. No person has joined yet.", "queue_id": "frontdesk", "qualified_staff_attested": True,
            "source": "Synthetic qualification fixture", "effective_at": (now_utc()-timedelta(days=1)).isoformat(), "expires_at": (now_utc()+timedelta(days=1)).isoformat()}}, "reason": "Synthetic route publication"}
    first = client.put("/api/v1/routing", headers=auth(database), json=body)
    assert first.status_code == 200, first.text
    other = client.put("/api/v1/routing", headers=auth(database, "clinic-niloufar"), json=body)
    assert other.status_code == 409 and other.json()["detail"]["code"] == "DID_ALREADY_ASSIGNED"
    with database() as db:
        route = routing.resolve_did(db, "02110002000")
        assert route["tenant_id"] == OWNER.tenant_id
        assert routing.language_route(first.json(), "english")["queue_id"] == "frontdesk"
        stale = first.json()
        stale["language_routes"]["english"]["expires_at"] = (now_utc()-timedelta(seconds=1)).isoformat()
        assert routing.language_route(stale, "english") is None
    invalid = {**body, "version": 1, "routes": [{**body["routes"][0], "transfer_target": "PJSIP/unapproved"}]}
    assert client.put("/api/v1/routing", headers=auth(database), json=invalid).status_code == 422


async def test_shared_transport_contract_interrupt_transfer_and_hangup_are_truthful():
    from receptionist.media.contracts import AudioSocketTransport, LiveKitTransport
    from types import SimpleNamespace
    frames, events = [], []
    class Writer:
        closed = False
        def write(self, value): frames.append(value)
        async def drain(self): pass
        def is_closing(self): return self.closed
        def close(self): self.closed = True
    async def transfer(reason):
        events.append(reason)
        return True
    writer = Writer()
    socket = AudioSocketTransport(writer, transfer)
    await socket.start("synthetic-call")
    await socket.send_audio(b"\0"*320, 8000)
    with pytest.raises(ValueError):
        await socket.send_audio(b"\0"*640, 16000)
    result = await socket.transfer("human_requested")
    assert result.requested and not result.connected and writer.closed
    assert frames[0][:3] == b"\x10\x01\x40" and frames[-1] == b"\0\0\0"
    await socket.hangup()
    async def disconnect(): events.append("disconnect")
    livekit = LiveKitTransport(SimpleNamespace(clear_queue=lambda: events.append("clear")), SimpleNamespace(disconnect=disconnect), transfer)
    await livekit.start("synthetic-call")
    assert livekit.interrupt() == 1
    result = await livekit.transfer("human_requested")
    assert result.requested and not result.connected and not livekit.closed
    await livekit.hangup()
    await livekit.hangup()
    assert events.count("disconnect") == 1


async def test_speech_meter_uses_submitted_pcm_and_malformed_tts_degrades_without_erasing_charge(database, monkeypatch):
    from receptionist.media.audio import wav_bytes
    from receptionist.providers import SpeechGateway
    monkeypatch.setenv("SPEECH_PROCESSOR_APPROVED", "true")
    monkeypatch.setenv("SPEECH_GATEWAY_URL", "https://speech.example.test")
    monkeypatch.setenv("SPEECH_GATEWAY_TOKEN", "synthetic-token")
    monkeypatch.setenv("APPROVED_PROVIDER_HOSTS", "speech.example.test")
    def handler(request):
        if request.url.path == "/transcribe":
            return httpx.Response(200, json={"text": "نمونه آزمایشی", "audio_seconds": 0, "confidence": .9})
        return httpx.Response(200, content=b"not-valid-wav")
    with database() as db:
        context = provider_control.ProviderContext.from_session(db, OWNER.tenant_id, "speech-test-001")
        db.commit()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        speech = SpeechGateway(http, context=context)
        result = await speech.transcribe(wav_bytes(b"\0"*32000, 16000), "audio/wav")
        assert result["audio_seconds"] == 1 and result["duration_source"] == "submitted_pcm"
        with pytest.raises(ProviderError, match="INVALID_TTS_AUDIO"):
            await speech.synthesize("متن آزمایشی")
    with database() as db:
        rows = list(db.scalars(select(CostReservation).where(CostReservation.tenant_id == OWNER.tenant_id)))
        stt = next(r for r in rows if r.meter == "stt_audio_seconds")
        tts = next(r for r in rows if r.meter == "tts_characters")
        stt_charge = db.scalar(select(UsageCharge).where(UsageCharge.reservation_id == stt.id))
        tts_charge = db.scalar(select(UsageCharge).where(UsageCharge.reservation_id == tts.id))
        assert stt_charge.quantity == "1"
        assert tts.status == "SETTLED" and float(tts_charge.quantity) > 0
        observed = db.scalar(select(ProviderObservation).where(ProviderObservation.tenant_id == OWNER.tenant_id, ProviderObservation.provider_key == "speech_primary"))
        assert observed.status == "degraded" and observed.code == "INVALID_TTS_AUDIO"


def test_automated_media_reserves_maximum_before_admission_and_keeps_unknown_liability(database, monkeypatch):
    from receptionist.billing import BudgetInput, RateInput, publish_budget, publish_rate, settle_cost, spending
    from receptionist.media_cost import finalize_media_cost, reserve_media_cost
    from receptionist.operations import run_jobs
    monkeypatch.setenv("MAX_CALL_SECONDS", "60")
    with database() as db:
        publish_budget(BudgetInput(monthly_cap_toman=90, call_cap_toman=90, operation_cap_toman=90), OWNER, db)
        publish_rate(RateInput(provider="telephony_primary", meter="telephony_seconds", unit="second", currency="TOMAN", price_per_unit="1",
            fx_toman_per_currency="1", evidence_reference="synthetic:carrier-rate", evidence_sha256="a"*64,
            effective_at=now_utc()-timedelta(days=1), expires_at=now_utc()+timedelta(days=1)), OWNER, db)
        call, _ = voice.new_session(db, db.get(Tenant, OWNER.tenant_id), channel="sip")
        ticket = db.scalar(select(CostReservation).where(CostReservation.call_id == call.id))
        assert ticket.status == "STARTED" and 59 <= float(ticket.max_quantity) <= 60
        assert db.scalar(select(func.count()).select_from(UsageCharge).where(UsageCharge.call_id == call.id)) == 0
        with pytest.raises(HTTPException, match="MONETARY_BUDGET_EXCEEDED"):
            voice.new_session(db, db.get(Tenant, OWNER.tenant_id), channel="sip")
        db.rollback()
        voice.end_session(db, call)
        db.refresh(ticket)
        assert ticket.status == "UNKNOWN" and spending(db, OWNER.tenant_id)["reserved_micro_toman"] > 59_000_000
        finalize_media_cost(db, call)
        db.commit()
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action == "media.cost_reconciliation_required", AuditEvent.entity_id == call.id)) == 1
        # Only explicit, separately evidenced reconciliation settles the bill.
        settle_cost(db, ticket.id, "1", "synthetic:verified-carrier-receipt", outcome="confirmed")
        db.commit()
        expiring, _ = voice.new_session(db, db.get(Tenant, OWNER.tenant_id), channel="sip")
        expiring.expires_at = now_utc()-timedelta(seconds=1)
        db.commit()
        run_jobs(db)
        db.commit()
        pending = db.scalar(select(CostReservation).where(CostReservation.call_id == expiring.id))
        assert pending.status == "UNKNOWN"
        evidence = db.scalar(select(AuditEvent).where(AuditEvent.action == "media.cost_reconciliation_required", AuditEvent.entity_id == expiring.id))
        assert evidence.details["reason"] == "expiry" and evidence.details["scope"] == "automated_media_only"
    with database() as db:
        row, _ = voice.new_session(db, db.get(Tenant, "clinic-niloufar"))
        # Browser text is free of an invented telephony bill. Production media
        # admission itself fails closed on missing policy/rate.
        assert db.scalar(select(CostReservation).where(CostReservation.call_id == row.id)) is None
        from receptionist.config import settings
        monkeypatch.setattr(settings, "environment", "production")
        monkeypatch.setattr(provider_control, "require_capability", lambda *a, **kw: {})
        import receptionist.media_cost as cost_module
        monkeypatch.setattr(cost_module, "require_capability", lambda *a, **kw: {})
        monkeypatch.setattr(cost_module, "require_processor", lambda *a, **kw: {})
        with pytest.raises(HTTPException, match="MONETARY_POLICY_REQUIRED"):
            reserve_media_cost(db, row)


def test_enabled_payment_is_explicitly_unknown_without_an_observation(database, monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER_APPROVED", "true")
    monkeypatch.setenv("PAYMENT_TENANT_MERCHANTS_JSON", '{"clinic-bahar":"synthetic"}')
    with database() as db:
        registry = provider_control.capability_dict(db, OWNER.tenant_id, "payment_primary")
        assert registry["configured"] and registry["health"]["status"] == "unknown"
        readiness = provider_control.dependency_readiness(db, OWNER.tenant_id)
        assert not readiness["ready"] and readiness["observations"][0]["provider_key"] == "payment_primary"


def test_sip_only_configuration_is_scoped_and_unknown_until_observed(database, monkeypatch):
    monkeypatch.setenv("LIVEKIT_APPROVED", "false")
    monkeypatch.setenv("MEDIA_API_TOKEN", "synthetic-media-secret-0123456789abcdef")
    monkeypatch.setenv("MEDIA_DID_TENANTS_JSON", '{"02110002000":"bahar"}')
    with database() as db:
        configured = provider_control.capability_dict(db, OWNER.tenant_id, "telephony_primary")
        assert configured["configured"] and configured["health"]["status"] == "unknown"
        assert not provider_control.capability_dict(db, "clinic-niloufar", "telephony_primary")["configured"]
        result = provider_control.dependency_readiness(db)
        row = next(item for item in result["observations"] if item["provider_key"] == "telephony_primary")
        assert row["scopes"] == 1 and not row["ready"]


@pytest.mark.parametrize("flag,region,config", [
    ("SMS_PROVIDER_APPROVED", "SMS_PROCESSOR_REGION", {"KAVENEGAR_API_KEY": "syntheticApiKey", "KAVENEGAR_OTP_TEMPLATE": "verified", "KAVENEGAR_SENDER": "10002000", "NOTIFICATION_WEBHOOK_SECRET": "s"*40}),
    ("LIVEKIT_APPROVED", "TELEPHONY_PROCESSOR_REGION", {"LIVEKIT_URL": "wss://media.example.test", "LIVEKIT_API_KEY": "synthetic", "LIVEKIT_API_SECRET": "s"*40, "MEDIA_API_TOKEN": "m"*40}),
    ("DIGEST_PROCESSOR_APPROVED", "DIGEST_PROCESSOR_REGION", {"DIGEST_GATEWAY_URL": "https://digest.example.test", "DIGEST_GATEWAY_TOKEN": "d"*40}),
    ("PAYMENT_PROVIDER_APPROVED", "PAYMENT_PROCESSOR_REGION", {}),
])
def test_production_enabled_provider_requires_declared_region(monkeypatch, flag, region, config):
    for gate, *_ in provider_control.PROVIDERS.values():
        monkeypatch.setenv(gate, "false")
    monkeypatch.setenv(flag, "true")
    monkeypatch.setenv("APPROVED_PROVIDER_HOSTS", "media.example.test,digest.example.test")
    monkeypatch.delenv(region, raising=False)
    for key, value in config.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(ValueError, match=region):
        validate_optional_providers(True)
