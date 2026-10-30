"""Business-invariant regression tests against a real transactional database."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from receptionist.api import router
from receptionist.core import ReceptionService
from receptionist.db import Base, get_db, make_engine, now_utc
from receptionist.models import (
    Appointment,
    AuditEvent,
    IdempotencyRecord,
    Membership,
    MessageOutbox,
    Occupancy,
    Service,
    SlotHold,
)
from receptionist.security import decrypt, normalize_phone
from receptionist.seed import seed_demo
from sqlalchemy import func, select, update
from sqlalchemy.orm import sessionmaker


@pytest.fixture
def database(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        seed_demo(db)
    yield factory
    engine.dispose()


def future_day(days=3):
    return (now_utc().astimezone(ZoneInfo("Asia/Tehran")) + timedelta(days=days)).date().isoformat()


def slot_for(db, tenant="clinic-bahar", provider="provider-bahar-1", service="service-consultation", index=0, days=3):
    return ReceptionService(db, tenant).slots(provider, service, future_day(days))[index]["slot_id"]


def create(db, slot=None, key="create-test-001", name="مراجع آزمایشی", **kwargs):
    return ReceptionService(db, "clinic-bahar", "test").create_appointment(slot or slot_for(db), name, "۰۹۱۲۳۴۵۶۷۸۹", key, True, **kwargs)


def test_booking_atomic_outbox_and_encrypted_pii(database):
    with database() as db:
        result = create(db)
        booking = db.get(Appointment, result["id"])
        assert result["status"] == "CONFIRMED"
        assert decrypt(booking.patient_name_encrypted) == "مراجع آزمایشی"
        assert "مراجع" not in booking.patient_name_encrypted
        assert "09123456789" not in booking.phone_encrypted
        assert result["phone_masked"] == "091•••••789"
        assert db.scalar(select(func.count()).select_from(MessageOutbox).where(MessageOutbox.appointment_id == booking.id)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(AuditEvent.entity_id == booking.id, AuditEvent.action == "appointment.created")
            )
            == 1
        )
        record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.entity_id == booking.id))
        assert "مراجع" not in json.dumps(record.response, ensure_ascii=False)


def test_idempotency_replay_and_mismatched_body(database):
    with database() as db:
        slot = slot_for(db)
        first = create(db, slot)
        second = create(db, slot)
        assert first["id"] == second["id"]
        with pytest.raises(HTTPException) as error:
            create(db, slot, name="شخص دیگر")
        assert error.value.status_code == 409
        assert error.value.detail["code"] == "IDEMPOTENCY_MISMATCH"
        assert db.scalar(select(func.count()).select_from(Appointment).where(Appointment.id == first["id"])) == 1


def test_replay_reads_current_authority_after_cancellation(database):
    with database() as db:
        slot = slot_for(db)
        booking = create(db, slot)
        ReceptionService(db, "clinic-bahar").cancel_appointment(booking["id"], "cancel-replay-001", booking["version"], verified=True)
        replay = create(db, slot)
        assert replay["id"] == booking["id"]
        assert replay["status"] == "CANCELED"


def test_simultaneous_same_slot_has_exactly_one_winner(database):
    with database() as db:
        slot = slot_for(db)
    barrier = threading.Barrier(2)

    def contender(n):
        with database() as db:
            barrier.wait()
            try:
                return create(db, slot, key=f"concurrent-{n:03}")["status"]
            except HTTPException as error:
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, [1, 2]))
    assert results.count("CONFIRMED") == 1
    assert results.count(409) + results.count(503) == 1
    with database() as db:
        assert db.scalar(select(func.count()).select_from(IdempotencyRecord).where(IdempotencyRecord.key.like("concurrent-%"))) == 1


def test_overlap_not_only_equal_start_and_shared_resource(database):
    with database() as db:
        service = db.get(Service, "service-consultation")
        service.resource_ids = ["shared-chair"]
        db.commit()
        first = slot_for(db, index=0)
        overlapping = slot_for(db, provider="provider-bahar-2", index=1)
        create(db, first)
        with pytest.raises(HTTPException) as error:
            create(db, overlapping, key="shared-resource-002")
        assert error.value.status_code == 409


def test_hold_ownership_expiry_and_consumption(database):
    with database() as db:
        service = ReceptionService(db, "clinic-bahar")
        slot = slot_for(db)
        hold = service.hold(slot, "call-a")
        with pytest.raises(HTTPException) as error:
            create(db, slot, key="hold-wrong-owner", hold_id=hold["id"], session_id="call-b")
        assert error.value.detail["code"] == "INVALID_HOLD"
        db.rollback()
        result = create(db, slot, key="hold-right-owner", hold_id=hold["id"], session_id="call-a")
        assert result["status"] == "CONFIRMED"
        assert db.get(SlotHold, hold["id"]).status == "CONSUMED"
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == hold["id"])) == 0
        next_slot = slot_for(db, index=4)
        expired = service.hold(next_slot, "call-c")
        db.execute(update(SlotHold).where(SlotHold.id == expired["id"]).values(expires_at=now_utc() - timedelta(seconds=1)))
        db.commit()
        service.expire()
        assert db.get(SlotHold, expired["id"]).status == "EXPIRED"
        assert create(db, next_slot, key="expired-reuse-001")["status"] == "CONFIRMED"


def test_failed_reschedule_preserves_original_claims(database):
    with database() as db:
        service = ReceptionService(db, "clinic-bahar")
        original_slot = slot_for(db, index=0)
        target_slot = slot_for(db, index=4)
        a = create(db, original_slot, key="reschedule-first")
        create(db, target_slot, key="reschedule-second")
        before = list(db.scalars(select(Occupancy.minute).where(Occupancy.owner_id == a["id"])))
        with pytest.raises(HTTPException) as error:
            service.reschedule_appointment(a["id"], target_slot, "reschedule-collision", a["version"], verified=True)
        assert error.value.detail["code"] == "SLOT_TAKEN"
        preserved = service.appointment_dict(service.get_appointment(a["id"]))
        assert preserved["start_at"] == a["start_at"]
        assert list(db.scalars(select(Occupancy.minute).where(Occupancy.owner_id == a["id"]))) == before


def test_successful_reschedule_and_stale_version(database):
    with database() as db:
        a = create(db)
        destination = slot_for(db, index=6)
        service = ReceptionService(db, "clinic-bahar")
        moved = service.reschedule_appointment(a["id"], destination, "reschedule-success", a["version"], verified=True)
        assert moved["id"] == a["id"] and moved["version"] == a["version"] + 1
        assert moved["start_at"] != a["start_at"]
        with pytest.raises(HTTPException) as error:
            service.cancel_appointment(a["id"], "cancel-stale-001", a["version"], verified=True)
        assert error.value.detail["code"] == "STALE_VERSION"


def test_phone_and_explicit_confirmation_required(database):
    assert normalize_phone("+۹۸ ۹۱۲ ۳۴۵ ۶۷۸۹") == "09123456789"
    with database() as db:
        service = ReceptionService(db, "clinic-bahar")
        slot = slot_for(db)
        with pytest.raises(HTTPException) as error:
            service.create_appointment(slot, "آزمون نمونه", "09123456789", "no-confirmation", False)
        assert error.value.detail["code"] == "CONFIRMATION_REQUIRED"
        with pytest.raises(HTTPException):
            service.create_appointment(slot, "آزمون نمونه", "invalid", "invalid-phone-001", True)


def test_cancellation_requires_verified_identity(database):
    with database() as db:
        booking = create(db)
        with pytest.raises(HTTPException) as error:
            ReceptionService(db, "clinic-bahar").cancel_appointment(booking["id"], "cancel-no-proof", booking["version"])
        assert error.value.status_code == 403
        assert db.get(Appointment, booking["id"]).status == "CONFIRMED"


def test_tenant_isolation_and_signed_slot_scope(database):
    with database() as db:
        slot = slot_for(db)
        booking = create(db, slot)
        other = ReceptionService(db, "clinic-niloufar")
        with pytest.raises(HTTPException) as error:
            other.get_appointment(booking["id"])
        assert error.value.status_code == 404
        with pytest.raises(HTTPException) as error:
            other.hold(slot, "other-tenant")
        assert error.value.status_code == 404


def test_policy_version_holidays_and_hours(database):
    with database() as db:
        service = ReceptionService(db, "clinic-bahar")
        stale_slot = slot_for(db)
        updated = service.update_settings({"version": 1, "holidays": [future_day()]})
        assert updated["settings_version"] == 2
        assert service.slots("provider-bahar-1", "service-consultation", future_day()) == []
        with pytest.raises(HTTPException) as error:
            create(db, stale_slot)
        assert error.value.detail["code"] == "STALE_POLICY"
        with pytest.raises(HTTPException) as error:
            service.update_settings({"version": 2, "working_hours": {"0": [["09:00", "13:00"], ["12:00", "16:00"]]}})
        assert error.value.status_code == 422


def test_pending_payment_amount_late_payment_and_approval(database):
    with database() as db:
        service = ReceptionService(db, "clinic-niloufar")
        slot = slot_for(db, "clinic-niloufar", "provider-niloufar-1", "service-salon")
        booking = service.create_appointment(slot, "نمونه سالن", "09123456789", "salon-deposit-001", True)
        assert booking["status"] == "PENDING_PAYMENT"
        with pytest.raises(HTTPException) as error:
            service.settle_payment(booking["id"], 1, "verified-test-reference")
        assert error.value.detail["code"] == "PAYMENT_AMOUNT_MISMATCH"
        db.rollback()
        paid = service.settle_payment(booking["id"], 100000, "verified-test-reference")
        db.commit()
        assert paid["status"] == "CONFIRMED" and paid["payment_status"] == "PAID"
        late_slot = slot_for(db, "clinic-niloufar", "provider-niloufar-1", "service-salon", index=4)
        late = service.create_appointment(late_slot, "نمونه دوم", "09123456789", "salon-deposit-002", True)
        db.execute(update(Appointment).where(Appointment.id == late["id"]).values(expires_at=now_utc() - timedelta(seconds=1)))
        db.commit()
        with pytest.raises(HTTPException) as error:
            service.settle_payment(late["id"], 100000, "late-payment")
        assert error.value.detail["code"] == "PAYMENT_HOLD_EXPIRED"
        db.commit()
        assert db.get(Appointment, late["id"]).status == "EXPIRED"
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == late["id"])) == 0


def test_staff_approval_not_false_confirmation(database):
    with database() as db:
        slot = slot_for(db, provider="provider-bahar-2", service="service-specialist")
        booking = create(db, slot, key="staff-approval-test")
        assert booking["status"] == "PENDING_STAFF_APPROVAL"
        service = ReceptionService(db, "clinic-bahar")
        result = service.approve(booking["id"], booking["version"])
        assert result["status"] == "CONFIRMED"
        with pytest.raises(HTTPException):
            service.outcome(result["id"], "ATTENDED", result["version"])


def test_http_auth_membership_roles_and_cross_tenant_isolation(database):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    client = TestClient(app)
    assert client.get("/api/v1/appointments").status_code == 401
    response = client.post("/api/v1/auth/login", json={"email": "other@example.test", "password": "DemoReception2026!"})
    assert response.status_code == 200
    headers = {"Authorization": "Bearer " + response.json()["access_token"]}
    assert client.get("/api/v1/me", headers=headers).json()["tenant_id"] == "clinic-niloufar"
    assert client.get("/api/v1/appointments", headers=headers).json() == []
    assert client.post("/api/v1/auth/switch", headers=headers, json={"tenant_id": "clinic-bahar"}).status_code == 403
    assert client.put("/api/v1/settings", headers=headers, json={"version": 1, "name": "forbidden"}).status_code == 403
    # Revoked membership takes effect immediately despite an otherwise-valid JWT.
    with database() as db:
        membership = db.scalar(select(Membership).where(Membership.user_id == "demo-other"))
        membership.active = False
        db.commit()
    assert client.get("/api/v1/me", headers=headers).status_code == 403


def test_expired_or_wrong_audience_jwt_rejected(database):
    import jwt
    from receptionist.config import settings

    app = FastAPI()
    app.include_router(router)

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    claims = {
        "sub": "demo-owner",
        "tenant": "clinic-bahar",
        "ver": 1,
        "iat": now_utc(),
        "exp": now_utc() + timedelta(minutes=5),
        "iss": "persian-receptionist",
        "aud": "slot",
    }
    token = jwt.encode(claims, settings.jwt_secret, algorithm="HS256")
    assert TestClient(app).get("/api/v1/me", headers={"Authorization": "Bearer " + token}).status_code == 401


def test_onboarding_catalog_scopes_inactive_restoration_and_faq_approval(database):
    from receptionist.models import User
    from receptionist.security import issue_token

    app = FastAPI()
    app.include_router(router)

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with database() as db:
        token = issue_token(db.get(User, "demo-owner"), "clinic-bahar")
    headers = {"Authorization": "Bearer " + token}
    client = TestClient(app)
    created = client.post("/api/v1/clinics", headers=headers, json={"name": "مرکز جدید", "slug": "new-clinic"})
    assert created.status_code == 201 and created.json()["mode"] == "human_primary"
    switch = client.post("/api/v1/auth/switch", headers=headers, json={"tenant_id": created.json()["id"]})
    headers = {"Authorization": "Bearer " + switch.json()["access_token"]}
    practitioner = client.post("/api/v1/practitioners", headers=headers, json={"name": "پزشک نمونه"}).json()
    assert (
        client.post(
            "/api/v1/services", headers=headers, json={"name": "خدمت نامعتبر", "provider_ids": ["provider-bahar-1"], "duration_minutes": 30}
        ).status_code
        == 422
    )
    service = client.post(
        "/api/v1/services",
        headers=headers,
        json={
            "name": "خدمت نمونه",
            "provider_ids": [practitioner["id"]],
            "resource_ids": ["room-1"],
            "duration_minutes": 30,
            "price_toman": 100000,
        },
    )
    assert service.status_code == 201
    listed = client.get("/api/v1/services", headers=headers).json()
    assert listed[0]["resource_ids"] == ["room-1"] and listed[0]["active"]
    disabled = client.put("/api/v1/practitioners/" + practitioner["id"], headers=headers, json={"name": "پزشک نمونه", "active": False})
    assert disabled.status_code == 200
    assert client.get("/api/v1/practitioners", headers=headers).json() == []
    assert len(client.get("/api/v1/practitioners?include_inactive=true", headers=headers).json()) == 1
    version = client.get("/api/v1/settings", headers=headers).json()["settings_version"]
    changed = client.put(
        "/api/v1/settings",
        headers=headers,
        json={
            "version": version,
            "faq": [{"question": "آدرس؟", "answer": "نشانی نمونه", "category": "address", "approved_by": "forged-person"}],
        },
    )
    assert changed.status_code == 200
    fact = changed.json()["faq"][0]
    assert fact["approved_by"] == "demo-owner" and fact["source"] and fact["expires_at"]


def test_practitioner_shifts_validate_preserve_and_protect_existing_bookings(database):
    from receptionist.models import User
    from receptionist.security import issue_token

    app = FastAPI()
    app.include_router(router)

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with database() as db:
        token = issue_token(db.get(User, "demo-owner"), "clinic-bahar")
    headers = {"Authorization": "Bearer " + token}
    client = TestClient(app)
    endpoint = "/api/v1/practitioners/provider-bahar-1"
    # The demo seed has a 09:00 appointment today. Before 09:00 Tehran time it
    # is still in the future, so the test's initial schedule must cover it.
    shifts = {str(day): [["09:00", "13:00"], ["14:00", "17:00"]] for day in range(7)}
    changed = client.put(endpoint, headers=headers, json={"name": "پزشک با شیفت", "working_hours": shifts})
    assert changed.status_code == 200 and changed.json()["working_hours"] == shifts
    unchanged = client.put(endpoint, headers=headers, json={"name": "نام اصلاح‌شده"})
    assert unchanged.status_code == 200 and unchanged.json()["working_hours"] == shifts
    for invalid in ({"7": [["09:00", "12:00"]]}, {"0": [["09:00", "13:00"], ["12:00", "14:00"]]},
                    {"0": [["09:00+03:30", "12:00+03:30"]]}, {"0": [["18:00", "09:00"]]}):
        assert client.put(endpoint, headers=headers, json={"name": "شیفت نامعتبر", "working_hours": invalid}).status_code == 422
    with database() as db:
        booking = create(db, key="shift-booking-protection")
    conflict = client.put(endpoint, headers=headers, json={"name": "تلاش بستن شیفت", "working_hours": {}})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "FUTURE_BOOKINGS_REQUIRE_REVIEW"
    inherited = client.put(endpoint, headers=headers, json={"name": "برنامه مرکز", "working_hours": None})
    assert inherited.status_code == 200 and inherited.json()["working_hours"] is None
    with database() as db:
        assert db.get(Appointment, booking["id"]).status == "CONFIRMED"
