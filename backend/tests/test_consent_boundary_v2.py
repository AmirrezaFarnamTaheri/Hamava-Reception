# ruff: noqa: F811 -- imported pytest fixtures
"""The displayed processing notice binds real intake and can be disabled live."""
from sqlalchemy import func, select

from receptionist.config import settings
from receptionist.models import ConsentGrant, Tenant
from receptionist.models_privacy import PurposePolicy
from receptionist.models_voice import CallSession, VoiceTurn
from test_core_integrations import client, database  # noqa: F401


def test_real_intake_binds_displayed_notice_and_disabled_purpose_stops_existing_turn(client, database, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    notice = client.get("/api/v1/public/clinics/bahar").json()
    fingerprint = notice["processing_notice_fingerprint"]
    assert len(fingerprint) == 64
    body = {"clinic_slug": "bahar", "processing_consent": True}
    missing = client.post("/api/v1/public/sessions", json=body)
    assert missing.status_code == 409 and missing.json()["detail"]["code"] == "PROCESSING_NOTICE_CHANGED"
    result = client.post("/api/v1/public/sessions", json={**body, "processing_notice_fingerprint": fingerprint})
    assert result.status_code == 201, result.text
    session = result.json()
    with database() as db:
        call = db.get(CallSession, session["session_id"])
        assert call.policy_snapshot["processing_notice_fingerprint"] == fingerprint
        grant = db.scalar(select(ConsentGrant).where(ConsentGrant.subject_hash == "session:" + call.id, ConsentGrant.purpose == "processing"))
        assert grant.evidence["notice_fingerprint"] == fingerprint and grant.evidence["displayed_notice_bound"]
        tenant = db.get(Tenant, "clinic-bahar")
        tenant.retention_days = 15
        db.commit()
    stale = client.post("/api/v1/public/sessions", json={**body, "processing_notice_fingerprint": fingerprint})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "PROCESSING_NOTICE_CHANGED"
    current = client.get("/api/v1/public/clinics/bahar").json()
    assert current["processing_notice_fingerprint"] != fingerprint
    foreign = client.post("/api/v1/public/sessions", json={**body, "clinic_slug": "niloufar", "processing_notice_fingerprint": current["processing_notice_fingerprint"]})
    assert foreign.status_code == 409
    with database() as db:
        assert db.scalar(select(func.count()).select_from(CallSession)) == 1
        db.add(PurposePolicy(tenant_id="clinic-bahar", purpose="processing", version=1, enabled=False,
            notice="این مرکز پردازش خودکار را متوقف کرده است.", retention_days=15, backup_expiry_days=30,
            consent_valid_days=30, evidence_reference="synthetic-owner-choice", approved_by="demo-owner"))
        db.commit()
    stopped = client.post(f"/api/v1/public/sessions/{session['session_id']}/turn",
        headers={"Authorization": "Bearer " + session["token"]}, json={"text": "نوبت می خواهم", "request_id": "disabled-purpose-turn"})
    assert stopped.status_code == 409 and stopped.json()["detail"]["code"] == "PROCESSING_DISABLED"
    with database() as db:
        assert db.scalar(select(func.count()).select_from(VoiceTurn)) == 0


def test_demo_omission_is_explicit_compatibility_but_present_stale_notice_still_rejects(client, database):
    assert settings.demo_mode
    old = client.get("/api/v1/public/clinics/bahar").json()["processing_notice_fingerprint"]
    with database() as db:
        db.get(Tenant, "clinic-bahar").retention_days = 2
        db.commit()
    body = {"clinic_slug": "bahar", "processing_consent": True}
    assert client.post("/api/v1/public/sessions", json={**body, "processing_notice_fingerprint": old}).status_code == 409
    synthetic = client.post("/api/v1/public/sessions", json=body)
    assert synthetic.status_code == 201
    with database() as db:
        grant = db.scalar(select(ConsentGrant).where(ConsentGrant.subject_hash == "session:" + synthetic.json()["session_id"], ConsentGrant.purpose == "processing"))
        assert not grant.evidence["displayed_notice_bound"]
    latest = client.get("/api/v1/public/clinics/bahar").json()["processing_notice_fingerprint"]
    assert client.post("/api/v1/public/sessions", json={**body, "processing_notice_fingerprint": latest}).status_code == 201
