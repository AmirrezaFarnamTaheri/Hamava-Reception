"""Scope, credential, meaning-preservation, delivery and accounting regressions."""
from datetime import timedelta
import importlib.util
import json
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from receptionist.api import router as staff_router
from receptionist.config import settings
from receptionist.db import Base, get_db, make_engine, now_utc
from receptionist.models import Tenant, UsageEvent, User
from receptionist.models_ops import OutreachSuppression
from receptionist.models_partner import DigestDelivery, DigestDestination, PartnerCredential
from receptionist.partners import (channel_allowed, dispatch_digest, pronounce, router,
                                   safe_pronunciation)
from receptionist.security import encrypt, hash_phone
from receptionist.seed import seed_demo
from receptionist.telemetry import SafeJSONFormatter, router as telemetry_router
from receptionist.voice import router as caller_router


@pytest.fixture
def extension_app(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'extension.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed_demo(db)
    app = FastAPI()
    app.include_router(staff_router)
    app.include_router(caller_router)
    app.include_router(router)
    app.include_router(telemetry_router)
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client, factory
    engine.dispose()


def login(client, email="owner@example.test", password="DemoReception2026!"):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": "Bearer "+response.json()["access_token"]}


def key(client, headers, scopes):
    response = client.post("/api/v1/operations/partner-keys", headers=headers,
        json={"label": "Synthetic partner", "purpose": "Authorized fixture integration", "scopes": scopes, "expires_days": 1})
    assert response.status_code == 201, response.text
    return response.json()


def test_partner_key_scope_masking_revocation_and_authority(extension_app):
    client, factory = extension_app
    owner = login(client)
    issued = key(client, owner, ["summary:read"])
    partner = {"Authorization": "Bearer "+issued["api_key"]}
    response = client.get("/api/v1/partner/v1/summary", headers=partner)
    assert response.status_code == 200
    assert response.json()["contains_patient_records"] is False
    assert "phone" not in response.text and "patient_name" not in response.text
    assert client.get("/api/v1/partner/v1/appointments?from_date=2026-01-01&to_date=2026-01-02", headers=partner).status_code == 403
    assert client.get("/api/v1/appointments", headers=partner).status_code == 401
    listed = client.get("/api/v1/operations/partner-keys", headers=owner)
    assert issued["api_key"] not in listed.text
    with factory() as db:
        record = db.get(PartnerCredential, issued["id"])
        assert record.key_hash != issued["api_key"]
        record.expires_at = now_utc()-timedelta(seconds=1)
        db.commit()
    assert client.get("/api/v1/partner/v1/summary", headers=partner).status_code == 401
    second = key(client, owner, ["summary:read"])
    second_headers = {"Authorization": "Bearer "+second["api_key"]}
    assert client.delete("/api/v1/operations/partner-keys/"+second["id"], headers=owner).status_code == 200
    assert client.get("/api/v1/partner/v1/summary", headers=second_headers).status_code == 401


def test_partner_voice_thread_idempotency_and_revocation(extension_app):
    client, factory = extension_app
    owner = login(client)
    issued = key(client, owner, ["voice_notes:write"])
    partner = {"Authorization": "Bearer "+issued["api_key"]}
    body = {"external_thread_id": "fictional-thread-001", "processing_consent": True}
    first = client.post("/api/v1/partner/v1/voice-sessions", headers=partner, json=body)
    assert first.status_code == 201, first.text
    second = client.post("/api/v1/partner/v1/voice-sessions", headers=partner, json=body)
    assert first.json()["session_id"] == second.json()["session_id"]
    assert second.json()["replayed"] is True
    session = first.json()
    call_headers = {"Authorization": "Bearer "+session["token"]}
    assert client.get("/api/v1/public/sessions/"+session["session_id"], headers=call_headers).status_code == 200
    assert client.delete("/api/v1/operations/partner-keys/"+issued["id"], headers=owner).status_code == 200
    revoked = client.post("/api/v1/public/sessions/"+session["session_id"]+"/turn", headers=call_headers,
                          json={"text": "سلام", "request_id": "revoked-thread-turn"})
    assert revoked.status_code in {401, 410}


def test_owner_team_grant_immediate_revoke_and_partner_no_staff_access(extension_app):
    client, factory = extension_app
    owner = login(client)
    created = client.post("/api/v1/operations/team", headers=owner, json={"email": "partner@example.test",
        "name": "همکار آزمایشی", "role": "partner", "initial_password": "SyntheticPartnerPassword!2026"})
    assert created.status_code == 201, created.text
    partner = login(client, "partner@example.test", "SyntheticPartnerPassword!2026")
    assert client.get("/api/v1/operations/partner-summary", headers=partner).status_code == 200
    assert client.get("/api/v1/appointments", headers=partner).status_code == 403
    assert client.get("/api/v1/operations/team", headers=partner).status_code == 403
    members = client.get("/api/v1/operations/team", headers=owner).json()
    member = next(x for x in members if x["email"] == "partner@example.test")
    assert client.delete("/api/v1/operations/team/"+member["membership_id"], headers=owner).status_code == 200
    assert client.get("/api/v1/operations/partner-summary", headers=partner).status_code == 403


def test_profile_publication_version_and_pronunciation_cannot_change_truth(extension_app):
    client, _ = extension_app
    owner = login(client)
    body = {"version": 0, "legal_operator": "مالک آزمایشی", "location_label": "واحد آزمایشی",
            "ownership_reference": "fictional-record", "brand_name": "پذیرش نمونه", "brand_color": "#174c46",
            "pronunciation": [{"written": "فاطمی", "spoken": "فاطِمی", "asr_aliases": ["فاتمی"]}], "publication_approved": True}
    created = client.put("/api/v1/operations/profile", headers=owner, json=body)
    assert created.status_code == 200, created.text
    assert created.json()["version"] == 1
    assert client.put("/api/v1/operations/profile", headers=owner, json=body).status_code == 409
    body["version"] = 1
    body["pronunciation"] = [{"written": "تأیید", "spoken": "لغو", "asr_aliases": []}]
    assert client.put("/api/v1/operations/profile", headers=owner, json=body).status_code == 422
    assert pronounce("فاطمی، ساعت ۱۲:۰۰ تأیید شد", [{"written": "فاطمی", "spoken": "فاطِمی"},
        {"written": "تأیید", "spoken": "لغو"}, {"written": "۱۲", "spoken": "۱۳"}]) == "فاطِمی، ساعت ۱۲:۰۰ تأیید شد"
    assert not safe_pronunciation("فاطمی", "فاطمی نوبت لغو شد")


def test_channel_consent_is_specific_and_cannot_override_withdrawal(extension_app):
    client, factory = extension_app
    owner = login(client)
    body = {"phone": "09123456789", "channel": "telegram", "purpose": "reminder", "granted": True,
            "evidence_reference": "synthetic-consent-only"}
    assert client.post("/api/v1/operations/channel-permissions", headers=owner, json=body).status_code == 200
    with factory() as db:
        assert channel_allowed(db, "clinic-bahar", body["phone"], "telegram", "reminder")
        assert not channel_allowed(db, "clinic-bahar", body["phone"], "sms", "reminder")
        assert not channel_allowed(db, "clinic-bahar", body["phone"], "telegram", "waitlist")
        db.add(OutreachSuppression(tenant_id="clinic-bahar", subject_hash=hash_phone(body["phone"]), purpose="reminder"))
        db.commit()
        assert not channel_allowed(db, "clinic-bahar", body["phone"], "telegram", "reminder")


@pytest.mark.asyncio
async def test_digest_timeout_unknown_and_acceptance_not_delivery(extension_app, monkeypatch):
    _, factory = extension_app
    with factory() as db:
        user = db.scalar(select(User).where(User.email == "owner@example.test"))
        destination = DigestDestination(tenant_id="clinic-bahar", channel="telegram", recipient_encrypted=encrypt("synthetic-owner-id"),
            consent_reference="synthetic-approved-destination", enabled=True, created_by=user.id)
        db.add(destination)
        db.flush()
        row = DigestDelivery(tenant_id="clinic-bahar", destination_id=destination.id, period="2026-01-01", payload={"verified": 1})
        db.add(row)
        db.commit()
        delivery_id, destination_id = row.id, destination.id
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setenv("DIGEST_PROCESSOR_APPROVED", "true")
    monkeypatch.setenv("DIGEST_GATEWAY_URL", "https://digest.example.test/send")
    monkeypatch.setenv("APPROVED_PROVIDER_HOSTS", "digest.example.test")
    monkeypatch.setenv("DIGEST_GATEWAY_TOKEN", "x"*40)
    calls = []
    from receptionist import partners
    from receptionist.providers import ProviderError
    async def uncertain(*args, **kwargs):
        calls.append(kwargs)
        raise ProviderError("PROVIDER_TIMEOUT", unknown_outcome=True)
    monkeypatch.setattr(partners, "provider_request", uncertain)
    with factory() as db:
        assert (await dispatch_digest(db, delivery_id))["status"] == "UNKNOWN"
        assert (await dispatch_digest(db, delivery_id))["status"] == "UNKNOWN"
        assert len(calls) == 1
        row = DigestDelivery(tenant_id="clinic-bahar", destination_id=destination_id, period="2026-01-02", payload={"verified": 2})
        db.add(row)
        db.commit()
        async def accepted(*args, **kwargs):
            return httpx.Response(200, json={"status": "delivered", "reference": "proxy-acceptance"})
        monkeypatch.setattr(partners, "provider_request", accepted)
        assert (await dispatch_digest(db, row.id))["status"] == "SENT"


def test_building_pool_exact_money_and_access_scope(extension_app):
    client, factory = extension_app
    owner = login(client)
    period = now_utc().strftime("%Y-%m")
    with factory() as db:
        for tenant in db.scalars(select(Tenant)):
            tenant.building_id = "synthetic-building"
        db.add_all([UsageEvent(tenant_id="clinic-bahar", kind="call_seconds", unit="second", quantity=125),
                    UsageEvent(tenant_id="clinic-niloufar", kind="call_seconds", unit="second", quantity=95),
                    UsageEvent(tenant_id="clinic-bahar", kind="stt_seconds", unit="second", quantity=99999)])
        db.commit()
    created = client.post("/api/v1/operations/building-contracts", headers=owner,
        json={"building_id": "synthetic-building", "tenant_ids": ["clinic-bahar", "clinic-niloufar"],
              "contract_reference": "fictional-authority-record", "included_minutes": 1,
              "overage_toman_per_minute": 1001, "effective_period": period})
    assert created.status_code == 201, created.text
    allocation = client.get(f'/api/v1/operations/building-contracts/{created.json()["id"]}/allocation?period={period}', headers=owner)
    assert allocation.status_code == 200, allocation.text
    data = allocation.json()
    assert sum(x["overage_toman"] for x in data["items"]) == data["overage_toman"]
    assert data["total_minutes"] < 200  # Fixture seed + actual call usage; ASR processing is excluded.
    listed = client.get("/api/v1/operations/building-contracts", headers=owner)
    assert listed.status_code == 200 and listed.json()[0]["id"] == created.json()["id"]
    other = login(client, "other@example.test")
    assert client.get(f'/api/v1/operations/building-contracts/{created.json()["id"]}/allocation?period={period}', headers=other).status_code == 403


@pytest.mark.asyncio
async def test_daily_digest_requires_opt_in_and_queues_each_closed_day_once(extension_app):
    client, factory = extension_app
    owner = login(client)
    for automatic in (False, True):
        response = client.post("/api/v1/operations/digest-destinations", headers=owner, json={
            "channel": "email", "recipient": "synthetic@example.test", "consent_reference": "synthetic-authority-only",
            "enabled": True, "automatic_daily": automatic, "local_hour": 0})
        assert response.status_code == 201, response.text
    from receptionist.partners import run_partner_jobs
    await run_partner_jobs(factory)
    await run_partner_jobs(factory)
    with factory() as db:
        deliveries = list(db.scalars(select(DigestDelivery)))
        assert len(deliveries) == 1 and deliveries[0].status == "SIMULATED"
        destination = db.get(DigestDestination, deliveries[0].destination_id)
        assert destination.automatic_daily


def test_metrics_require_separate_secret_and_logs_drop_patient_text(extension_app, monkeypatch):
    client, _ = extension_app
    monkeypatch.setenv("METRICS_TOKEN", "m"*40)
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers=login(client)).status_code == 401
    response = client.get("/metrics", headers={"Authorization": "Bearer "+"m"*40})
    assert response.status_code == 200
    assert "hamava_active_calls" in response.text
    assert "09123456789" not in response.text and "clinic-bahar" not in response.text
    record = logging.LogRecord("receptionist", logging.ERROR, "x", 1, "Patient name 09123456789", (), None)
    record.request_id = "request-123"
    record.patient_name = "فرد آزمایشی"
    record.error_type = "ValueError"
    formatted = SafeJSONFormatter().format(record)
    assert "09123456789" not in formatted and "فرد" not in formatted
    assert json.loads(formatted)["event"] == "redacted_log_event"


def test_latency_report_is_scoped_and_does_not_invent_audible_measurement(extension_app):
    client, factory = extension_app
    owner = login(client)
    with factory() as db:
        for value in (10, 20, 100):
            db.add(UsageEvent(tenant_id="clinic-bahar", kind="latency_stt_ms", quantity=value, unit="millisecond"))
        db.add(UsageEvent(tenant_id="clinic-niloufar", kind="latency_stt_ms", quantity=99999, unit="millisecond"))
        db.commit()
    result = client.get("/api/v1/operations/latency?hours=24", headers=owner)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["stages"]["stt_provider"] == {"count":3,"p50_ms":20.0,"p95_ms":100.0,"p99_ms":100.0}
    assert body["stages"]["tts_or_static_cache"]["p50_ms"] is None
    assert body["cost_meter"] is False
    assert "caller receiver" in body["end_to_first_audible"]


def capacity_module():
    path = Path(__file__).resolve().parents[2]/"scripts"/"capacity.py"
    spec = importlib.util.spec_from_file_location("capacity_tools", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_staff_simulation_denominators_and_reassigned_time():
    capacity = capacity_module()
    config = {"calls_per_hour": 60, "handoff_fraction": .5, "handling_mean_minutes": 6,
              "scheduled_staff": 1, "duration_hours": 4, "trials": 15, "seed": 45,
              "shrinkage_fraction": 0, "abandon_after_seconds": 120}
    one = capacity.simulate(config)
    more = capacity.simulate(config | {"scheduled_staff": 5})
    assert one["mean_arrivals"] == more["mean_arrivals"]
    assert more["mean_service_level_of_all_arrivals"] > one["mean_service_level_of_all_arrivals"]
    assert more["mean_abandoned"] < one["mean_abandoned"]
    empty = capacity.simulate(config | {"calls_per_hour": 0})
    assert empty["mean_service_level_of_all_arrivals"] is None
    accounting = capacity.workload({"baseline_reception_minutes": 100, "comparable_automated_minutes": 80,
        "supervision_minutes": 20, "rework_minutes": 10})
    assert accounting["net_released_minutes"] == 50
    assert accounting["avoidable_cost_toman"] == 0
    assert accounting["reassigned_capacity_minutes"] == 50
    with pytest.raises(ValueError):
        capacity.workload({"baseline_reception_minutes": 100, "comparable_automated_minutes": 80,
            "documented_avoidable_paid_minutes": 50, "loaded_toman_per_minute": 100})
