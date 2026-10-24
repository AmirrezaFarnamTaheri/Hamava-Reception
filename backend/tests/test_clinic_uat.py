"""Production UAT gates bind a named review to exact clinic configuration."""

from datetime import timedelta

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import select

from receptionist.api import create_service
from receptionist.config import settings
from receptionist.core import ReceptionService, iso
from receptionist.db import get_db, now_utc
from receptionist.models import AuditEvent, Service, Tenant, User
from receptionist.operations_uat import (
    REQUIRED_CHECKS,
    UATApproval,
    approve_uat,
    get_uat,
    require_current_uat,
    router,
)
from receptionist.schemas import ServiceInput
from receptionist.security import actor_for, issue_token
from test_core import database as database


def actor(db, tenant="clinic-bahar"):
    return actor_for(db, db.get(User, "demo-owner"), tenant)


def approval(db, target="ai_primary", tenant="clinic-bahar"):
    reviewer = actor(db, tenant)
    review = get_uat(target, reviewer, db)
    return UATApproval(
        target_mode=target,
        configuration_fingerprint=review["configuration_fingerprint"],
        checks={key: True for key in REQUIRED_CHECKS},
        evidence_refs={key: "synthetic-evidence/" + key + ".json" for key in REQUIRED_CHECKS},
        confirmed=True,
    )


def test_production_activation_needs_exact_attestation_but_pause_always_works(database, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    with database() as db:
        service = ReceptionService(db, "clinic-bahar", "demo-owner")
        paused = service.update_settings({"version": 1, "mode": "paused"})
        with pytest.raises(HTTPException) as error:
            service.update_settings({"version": paused["settings_version"], "mode": "ai_primary"})
        assert error.value.detail["code"] == "CLINIC_UAT_REQUIRED"
        review = approve_uat(approval(db), actor(db), db)
        assert review["approved"] and review["attestation"]["reviewer_user_id"] == "demo-owner"
        active = service.update_settings({"version": paused["settings_version"], "mode": "ai_primary"})
        require_current_uat(db, db.get(Tenant, "clinic-bahar"))
        with pytest.raises(HTTPException):
            service.update_settings({"version": active["settings_version"], "name": "نسخه جدید نیازمند آزمون"})
        result = service.update_settings({"version": active["settings_version"], "mode": "paused"})
        assert result["mode"] == "paused"


def test_catalog_drift_invalidates_uat_and_active_production_edit_requires_pause(database, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    with database() as db:
        tenant = db.get(Tenant, "clinic-bahar")
        with pytest.raises(HTTPException) as error:
            create_service(ServiceInput(name="خدمت آزمایشی", provider_ids=["provider-bahar-1"], duration_minutes=30), actor(db), db)
        assert error.value.detail["code"] == "PAUSE_BEFORE_CATALOG_CHANGE"
        ReceptionService(db, tenant.id, "demo-owner").update_settings({"version": tenant.settings_version, "mode": "paused"})
        previous = approval(db)
        approve_uat(previous, actor(db), db)
        create_service(ServiceInput(name="خدمت آزمایشی", provider_ids=["provider-bahar-1"], duration_minutes=30), actor(db), db)
        assert get_uat("ai_primary", actor(db), db)["approved"] is False
        with pytest.raises(HTTPException) as error:
            approve_uat(previous, actor(db), db)
        assert error.value.detail["code"] == "STALE_UAT_CONFIGURATION"


@pytest.mark.parametrize("missing", ["check", "reference", "confirmation"])
def test_partial_uat_cannot_be_attested(database, missing):
    with database() as db:
        data = approval(db)
        values = data.model_dump()
        if missing == "check":
            values["checks"]["handoff"] = False
        elif missing == "reference":
            del values["evidence_refs"]["conflict"]
        else:
            values["confirmed"] = False
        with pytest.raises(HTTPException) as error:
            approve_uat(UATApproval(**values), actor(db), db)
        assert error.value.status_code == 422
        assert db.scalar(select(AuditEvent.id).where(AuditEvent.action == "clinic.uat_attested")) is None


def test_uat_is_tenant_mode_expiry_and_reviewer_bound(database, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    with database() as db:
        approve_uat(approval(db), actor(db), db)
        assert get_uat("overflow", actor(db), db)["approved"] is False
        assert get_uat("ai_primary", actor(db, "clinic-niloufar"), db)["approved"] is False
        db.get(User, "demo-owner").active = False
        db.flush()
        with pytest.raises(HTTPException):
            require_current_uat(db, db.get(Tenant, "clinic-bahar"))
        db.get(User, "demo-owner").active = True
        row = db.scalar(select(AuditEvent).where(AuditEvent.action == "clinic.uat_attested"))
        row.details = {**row.details, "valid_until": iso(now_utc() - timedelta(seconds=1))}
        db.commit()
        assert get_uat("ai_primary", actor(db), db)["approved"] is False


def test_direct_catalog_drift_is_rejected_at_runtime(database, monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    with database() as db:
        approve_uat(approval(db), actor(db), db)
        db.get(Service, "service-consultation").duration_minutes += 5
        db.commit()
        with pytest.raises(HTTPException) as error:
            require_current_uat(db, db.get(Tenant, "clinic-bahar"))
        assert error.value.detail["code"] == "CLINIC_UAT_REQUIRED"


@pytest.mark.asyncio
async def test_uat_http_requires_owner_and_rejects_client_tenant_scope(database):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with database() as db:
        data = approval(db).model_dump()
        staff_token = issue_token(db.get(User, "demo-receptionist"), "clinic-bahar")
        owner_token = issue_token(db.get(User, "demo-owner"), "clinic-bahar")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/operations/uat")).status_code == 401
        assert (
            await client.post("/api/v1/operations/uat/approve", json=data, headers={"Authorization": "Bearer " + staff_token})
        ).status_code == 403
        result = await client.post(
            "/api/v1/operations/uat/approve",
            json={**data, "tenant_id": "clinic-niloufar"},
            headers={"Authorization": "Bearer " + owner_token},
        )
        assert result.status_code == 422
        result = await client.post("/api/v1/operations/uat/approve", json=data, headers={"Authorization": "Bearer " + owner_token})
        assert result.status_code == 200 and result.json()["approved"]
