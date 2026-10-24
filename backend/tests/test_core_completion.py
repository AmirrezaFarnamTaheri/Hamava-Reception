# ruff: noqa: F811 -- imported pytest fixture names are injected as arguments
"""Integrated core completion: privilege boundaries, recovery, policy and locale."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from receptionist import models_ops, models_outreach, models_partner  # noqa: F401
from receptionist.api import router
from receptionist.db import get_db
from receptionist.models import AuditEvent, Membership, User
from receptionist.security import ROLE_PERMISSIONS, issue_token
from test_core import database  # noqa: F401 -- isolated seeded database fixture


@pytest.fixture
def client(database):
    app = FastAPI()
    app.include_router(router)
    def override():
        with database() as db:
            yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client


def token(database, user="demo-owner", tenant="clinic-bahar"):
    with database() as db:
        return issue_token(db.get(User, user), tenant)


def auth(value):
    return {"Authorization": f"Bearer {value}"}


def test_exact_device_logout_revokes_switched_tokens_but_not_other_device(client, database):
    first, other = token(database), token(database)
    switched = client.post("/api/v1/auth/switch", headers=auth(first), json={"tenant_id": "clinic-niloufar"})
    assert switched.status_code == 200
    assert "billing:write" in switched.json()["user"]["permissions"]
    changed = switched.json()["access_token"]
    response = client.post("/api/v1/auth/logout", headers=auth(changed), json={})
    assert response.status_code == 200 and response.json()["scope"] == "session"
    assert client.get("/api/v1/me", headers=auth(first)).status_code == 401
    assert client.get("/api/v1/me", headers=auth(changed)).status_code == 401
    assert client.get("/api/v1/me", headers=auth(other)).status_code == 200
    with database() as db:
        assert db.scalar(select(AuditEvent).where(AuditEvent.action == "auth.logout")).details == {"scope": "session"}


def test_explicit_all_devices_logout_invalidates_parallel_device(client, database):
    first, other = token(database), token(database)
    assert client.post("/api/v1/auth/logout", headers=auth(first), json={"all_devices": True}).status_code == 200
    assert client.get("/api/v1/me", headers=auth(other)).status_code == 401
    assert client.get("/api/v1/me", headers=auth(token(database))).status_code == 200


@pytest.mark.parametrize("role,allowed,denied", [
    ("manager", "/settings", "/usage"),
    ("coordinator", "/appointments", "/audit"),
    ("billing", "/usage", "/appointments"),
    ("technical", "/audit", "/appointments"),
])
def test_new_roles_have_distinct_server_enforced_permissions(client, database, role, allowed, denied):
    with database() as db:
        db.execute(update(Membership).where(Membership.user_id == "demo-receptionist").values(role=role))
        db.commit()
    headers = auth(token(database, "demo-receptionist"))
    me = client.get("/api/v1/me", headers=headers)
    assert me.status_code == 200 and set(me.json()["permissions"]) == ROLE_PERMISSIONS[role]
    assert client.get("/api/v1" + allowed, headers=headers).status_code == 200
    assert client.get("/api/v1" + denied, headers=headers).status_code == 403
