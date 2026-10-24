"""Partner pronunciation boundaries and concurrent team-grant invariants."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from receptionist import partners
from receptionist.api import router as staff_router
from receptionist.db import Base, get_db, make_engine
from receptionist.models import AuditEvent, Membership, User
from receptionist.security import actor_for, check_password, hash_password, issue_token
from receptionist.seed import seed_demo


@pytest.fixture
def partner_app(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'partner-integrity.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed_demo(db)
        token = issue_token(db.get(User, "demo-owner"), "clinic-bahar")
    app = FastAPI()
    app.include_router(staff_router)
    app.include_router(partners.router)

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_db] = database
    with TestClient(app) as client:
        yield client, factory, {"Authorization": "Bearer " + token}
    engine.dispose()


@pytest.mark.parametrize("control", ["\u202e", "\u202c", "\u2067", "\u2069", "\u200f", "\u200b", "\u007f", "\u0085", "\ud800"])
def test_unicode_controls_cannot_enter_pronunciation_or_asr_hints(control):
    word = "فاطمی"
    assert not partners.safe_pronunciation(word, word + control)
    assert not partners.safe_pronunciation(word + control, word)
    assert partners.pronounce(word, [{"written": word, "spoken": word + control}]) == word
    with pytest.raises(ValidationError):
        partners.Pronunciation(written=word, spoken=word + control)
    with pytest.raises(ValidationError):
        partners.Pronunciation(written=word, spoken="فاطِمی", asr_aliases=[word + control])


def test_pronunciation_only_preserves_letters_and_deliberate_spacing():
    assert partners.safe_pronunciation("فاطمی", "فاطِمی")
    assert partners.safe_pronunciation("علی", "عَلي")
    assert not partners.safe_pronunciation("فاطمی", "فاطمی  ")
    assert not partners.safe_pronunciation("علی رضا", "علی  رضا")
    assert not partners.safe_pronunciation("تأیید", "تأیید؟")
    assert not partners.safe_pronunciation("۱۲", "۱۳")


def test_profile_http_rejects_control_dictionary_without_publication(partner_app):
    client, _, headers = partner_app
    payload = {"version": 0, "publication_approved": True,
               "pronunciation": [{"written": "فاطمی", "spoken": "فاطمی\u202e", "asr_aliases": []}]}
    response = client.put("/api/v1/operations/profile", headers=headers, json=payload)
    assert response.status_code == 422
    profile = client.get("/api/v1/operations/profile", headers=headers)
    assert profile.json()["version"] == 0 and profile.json()["published_at"] is None


def test_concurrent_new_email_grants_create_one_user_and_one_membership(partner_app):
    client, factory, headers = partner_app

    def grant(index):
        return client.post("/api/v1/operations/team", headers=headers, json={
            "email": "Concurrent@Example.Test" if index % 2 else "concurrent@example.test",
            "name": "همکار آزمایشی", "role": "receptionist",
            "initial_password": f"SyntheticStaffPassword!{index}"})

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(grant, range(4)))
    assert sorted(response.status_code for response in responses) == [201, 409, 409, 409]
    winner = next(index for index, response in enumerate(responses) if response.status_code == 201)
    with factory() as db:
        user = db.scalar(select(User).where(User.email == "concurrent@example.test"))
        assert db.scalar(select(func.count()).select_from(User).where(User.email == user.email)) == 1
        assert check_password(f"SyntheticStaffPassword!{winner}", user.password_hash)
        members = list(db.scalars(select(Membership).where(Membership.user_id == user.id)))
        assert len(members) == 1 and members[0].tenant_id == "clinic-bahar"
        assert db.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.entity_id == members[0].id, AuditEvent.action == "membership.granted")) == 1


def test_concurrent_existing_account_grants_reuse_one_membership(partner_app):
    client, factory, headers = partner_app
    password = "SyntheticExistingPassword!2026"
    with factory() as db:
        user = User(email="existing-concurrent@example.test", name="حساب موجود", password_hash=hash_password(password))
        db.add(user)
        db.commit()
        user_id = user.id
    payload = {"email": "existing-concurrent@example.test", "name": "همکار موجود", "role": "clinician"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: client.post("/api/v1/operations/team", headers=headers, json=payload), range(4)))
    assert all(response.status_code == 201 for response in responses)
    assert len({response.json()["membership_id"] for response in responses}) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Membership).where(Membership.user_id == user_id)) == 1
        assert check_password(password, db.get(User, user_id).password_hash)


def test_global_email_unique_conflict_is_recoverable_and_does_not_reset_account(partner_app, monkeypatch):
    _, factory, _ = partner_app
    with factory() as db:
        user = User(email="cross-tenant-race@example.test", name="حساب قبلی", password_hash=hash_password("OriginalSyntheticPassword!"))
        db.add(user)
        db.commit()
        user_id = user.id
        actor = actor_for(db, db.get(User, "demo-owner"), "clinic-bahar")
        scalar = db.scalar
        stale_once = True

        def stale_lookup(statement, *args, **kwargs):
            nonlocal stale_once
            if stale_once and any(column.get("entity") is User for column in getattr(statement, "column_descriptions", [])):
                # Model a cross-tenant PostgreSQL race where both lookups saw
                # absence before one transaction won the global unique key.
                stale_once = False
                return None
            return scalar(statement, *args, **kwargs)

        monkeypatch.setattr(db, "scalar", stale_lookup)
        with pytest.raises(HTTPException) as error:
            partners.grant_team(partners.TeamInput(email=user.email, name="رقیب آزمایشی", role="admin",
                initial_password="ReplacementSyntheticPassword!"), actor, db)
        assert error.value.status_code == 409 and error.value.detail["code"] == "TEAM_UPDATE_CONFLICT"
        assert db.scalar(select(func.count()).select_from(Membership).where(Membership.user_id == user_id)) == 0
        assert check_password("OriginalSyntheticPassword!", db.get(User, user_id).password_hash)
