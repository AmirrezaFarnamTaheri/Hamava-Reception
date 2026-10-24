# ruff: noqa: F811 -- imported pytest fixtures are injected as arguments
"""Scoped handler observations using synthetic media/provider responses.

These fixtures verify control-plane bookkeeping, not carrier or acoustic health.
"""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select

from receptionist import media_api, model_registry  # noqa: F401
from receptionist.db import now_utc
from receptionist.models import Tenant, User
from receptionist.models_core import IntegrationCapability, ProviderObservation
from receptionist.models_finance import CostReservation, UsageCharge
from receptionist.models_voice import CallSession
from receptionist.provider_control import ProviderContext, capability_dict, dependency_readiness, observe_activity
from receptionist.providers import ProviderError
from receptionist.security import issue_token
from test_core import database  # noqa: F401
from test_voice import start
from test_voice_integrity import add_room, application, configure_media  # noqa: F401


def configured(monkeypatch):
    headers = configure_media(monkeypatch)
    monkeypatch.setenv("LIVEKIT_APPROVED", "true")
    monkeypatch.setenv("LIVEKIT_API_KEY", "synthetic-key")
    monkeypatch.setenv("LIVEKIT_API_SECRET", "synthetic-secret-with-32-characters")
    monkeypatch.setattr(media_api, "SpeechGateway", lambda: SimpleNamespace(configured=True))
    return headers


def seen(factory, tenant="clinic-bahar"):
    with factory() as db:
        return db.scalar(select(ProviderObservation).where(
            ProviderObservation.tenant_id == tenant, ProviderObservation.provider_key == "telephony_primary"))


def test_activity_requires_actual_io_and_current_scope_and_approval(database, monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER_APPROVED", "true")
    monkeypatch.setenv("PAYMENT_TENANT_MERCHANTS_JSON", '{"clinic-bahar":"synthetic-merchant"}')
    with database() as db:
        def record(**changes):
            return observe_activity(db, "clinic-bahar", "payment_primary", "verify", outcome="declined",
                code="VALIDATED_BUSINESS_DECLINE", **changes)

        assert not record(performed_io=False)
        assert not record(performed_io=True, synthetic=True)
        assert db.scalar(select(ProviderObservation)) is None
        assert capability_dict(db, "clinic-bahar", "payment_primary")["health"]["status"] == "unknown"
        assert record(performed_io=True)
        db.commit()
        assert capability_dict(db, "clinic-bahar", "payment_primary")["health"]["status"] == "healthy"
        assert not dependency_readiness(db, "clinic-bahar")["ready"]  # no current approval
        db.add(IntegrationCapability(tenant_id="clinic-bahar", provider_key="payment_primary", version=1,
            kind="payment", operations=["request", "verify"], endpoint_version="synthetic-v1", region="IR",
            data_terms_reference="synthetic", evidence_reference="synthetic", approved_by="demo-owner",
            verification_state="operator_attested", expires_at=now_utc() + timedelta(days=1)))
        db.commit()
        assert dependency_readiness(db, "clinic-bahar")["ready"]
        assert db.scalar(select(ProviderObservation).where(ProviderObservation.tenant_id == "clinic-niloufar")) is None
        row = db.scalar(select(ProviderObservation))
        row.checked_at = now_utc() - timedelta(hours=1)
        db.commit()
        assert capability_dict(db, "clinic-bahar", "payment_primary")["health"]["status"] == "stale"
        assert not dependency_readiness(db, "clinic-bahar")["ready"]
        prior = row.checked_at
        db.get(Tenant, "clinic-bahar").active = False
        db.commit()
        assert not record(performed_io=True)  # result instrumentation cannot reject an inactive clinic
        db.commit()
        db.refresh(row)
        assert row.checked_at == prior
        with pytest.raises(ValueError, match="machine code"):
            observe_activity(db, "clinic-niloufar", "payment_primary", "verify", outcome="failed",
                code="private subject text", performed_io=True)


def test_dispatched_provider_context_keeps_settlement_after_clinic_disable(database):
    with database() as db:
        context = ProviderContext.from_session(db, "clinic-bahar", "synthetic-context-inflight")
    ticket = context.start("speech_primary", "tts_characters", 5, "synthesize_wav")
    with database() as db:
        db.get(Tenant, "clinic-bahar").active = False
        db.commit()
    context.finish(ticket, 5, outcome="confirmed", code="TTS_COMPLETE")
    with database() as db:
        assert db.get(CostReservation, ticket["id"]).status == "SETTLED"
        charge = db.scalar(select(UsageCharge).where(UsageCharge.reservation_id == ticket["id"]))
        assert charge is not None and Decimal(charge.quantity) == 5
        assert db.scalar(select(ProviderObservation).where(ProviderObservation.tenant_id == "clinic-bahar")) is None
    with pytest.raises(ProviderError, match="TENANT_NOT_FOUND"):
        context.start("speech_primary", "tts_characters", 5, "synthesize_wav")


@pytest.mark.parametrize("failure", ["timeout", "wrong_room"])
def test_room_creation_observes_valid_response_and_degrades_uncertain_io(application, monkeypatch, failure):
    client, factory = application
    media_headers = configured(monkeypatch)
    sid, headers = start(client)
    endpoint = f"/api/v1/public/sessions/{sid}/livekit"
    # Preflight rejection is a local condition, and an idle worker heartbeat
    # cannot establish a healthy provider for any clinic.
    assert client.post(endpoint, headers=headers).status_code == 503
    assert seen(factory) is None
    assert client.post("/api/v1/internal/media/rooms", headers=media_headers,
        json={"worker_id": "worker-observation"}).status_code == 200
    assert seen(factory) is None
    mode = "success"

    class Client:
        def __init__(self):
            self.room = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def create_room(self, request):
            if mode == "timeout":
                raise TimeoutError("synthetic request outcome is unknown")
            return SimpleNamespace(name="different-room" if mode == "wrong_room" else request.name)

    monkeypatch.setattr(media_api, "livekit_client", Client)
    assert client.post(endpoint, headers=headers).status_code == 200
    observed = seen(factory)
    assert (observed.status, observed.code) == ("healthy", "MEDIA_ROOM_CREATED")
    assert observed.latency_ms >= 0
    assert seen(factory, "clinic-niloufar") is None
    # A caller with the wrong token cannot degrade or refresh provider health.
    assert client.post(endpoint, headers={"Authorization": "Bearer forged"}).status_code == 404
    assert seen(factory).checked_at == observed.checked_at
    mode = failure
    other_id, other_headers = start(client)
    failed = client.post(f"/api/v1/public/sessions/{other_id}/livekit", headers=other_headers)
    assert failed.status_code == 503 and failed.json()["detail"]["code"] == "MEDIA_ADMISSION_UNKNOWN"
    assert (seen(factory).status, seen(factory).code) == (
        "degraded", "MEDIA_ROOM_CREATE_FAILED" if failure == "timeout" else "MEDIA_ROOM_INVALID_RESPONSE")


def test_worker_renewal_only_refreshes_a_scoped_live_lease(application, monkeypatch):
    client, factory = application
    headers = configured(monkeypatch)
    sid = add_room(factory)
    route = "/api/v1/internal/media/rooms"
    body = {"worker_id": "worker-observed", "capacity": 1}
    assert client.post(route, json=body).status_code == 401
    claim = client.post(route, headers=headers, json=body)
    assert claim.status_code == 200 and claim.json()["rooms"][0]["session_id"] == sid
    assert seen(factory) is None
    renew = client.post(route, headers=headers, json={**body, "active_sessions": [sid]})
    assert renew.status_code == 200 and renew.json()["renewed_sessions"] == [sid]
    observed = seen(factory)
    assert (observed.status, observed.code) == ("healthy", "MEDIA_WORKER_LEASE_RENEWED")
    assert seen(factory, "clinic-niloufar") is None
    wrong_worker = client.post(route, headers=headers,
        json={**body, "worker_id": "worker-unauthorized", "active_sessions": [sid]})
    assert wrong_worker.json()["renewed_sessions"] == []
    assert seen(factory).checked_at == observed.checked_at
    with factory() as db:
        db.get(CallSession, sid).media_worker_lease = now_utc() - timedelta(seconds=1)
        db.commit()
    expired = client.post(route, headers=headers, json={**body, "active_sessions": [sid]})
    assert expired.json()["revoked_sessions"] == [sid]
    assert seen(factory).checked_at == observed.checked_at


def test_pbx_claim_and_verified_human_join_observe_only_authorized_actual_events(application, monkeypatch):
    from livekit import api

    client, factory = application
    headers = configured(monkeypatch)
    monkeypatch.setenv("MEDIA_DID_TENANTS_JSON", '{"02100000000":"bahar"}')
    call_uuid = str(uuid4())
    registered = client.post("/api/v1/internal/media/register", headers=headers,
        json={"call_uuid": call_uuid, "did": "02100000000", "processing_notice_played": True})
    assert registered.status_code == 200 and seen(factory) is None
    endpoint = "/api/v1/internal/media/claim"
    assert client.post(endpoint, json={"call_uuid": call_uuid}).status_code == 401
    assert seen(factory) is None
    assert client.post(endpoint, headers=headers, json={"call_uuid": call_uuid}).status_code == 200
    observed = seen(factory)
    assert (observed.status, observed.code) == ("healthy", "SIP_WORKER_CLAIMED")
    assert client.post(endpoint, headers=headers, json={"call_uuid": call_uuid}).status_code == 409
    assert seen(factory).checked_at == observed.checked_at

    sid = add_room(factory)
    with factory() as db:
        staff_token = issue_token(db.get(User, "demo-owner"), "clinic-bahar")
    assert client.post(f"/api/v1/operations/calls/{sid}/takeover",
        headers={"Authorization": "Bearer " + staff_token}).status_code == 200
    assert client.post("/api/v1/webhooks/livekit", content=b"{}").status_code == 401
    assert seen(factory).checked_at == observed.checked_at
    event = SimpleNamespace(event="participant_joined", room=SimpleNamespace(name="reception-" + sid),
        participant=SimpleNamespace(identity="staff-demo-other"))
    monkeypatch.setattr(api, "WebhookReceiver", lambda verifier: SimpleNamespace(receive=lambda *args: event))
    assert client.post("/api/v1/webhooks/livekit", content=b"{}").status_code == 403
    assert seen(factory).checked_at == observed.checked_at
    event.participant.identity = "staff-demo-owner"
    assert client.post("/api/v1/webhooks/livekit", content=b"{}").status_code == 200
    observed = seen(factory)
    assert (observed.status, observed.code) == ("healthy", "MEDIA_HUMAN_JOIN_VERIFIED")
    assert client.post("/api/v1/webhooks/livekit", content=b"{}").status_code == 200
    assert seen(factory).checked_at == observed.checked_at
    assert seen(factory, "clinic-niloufar") is None
