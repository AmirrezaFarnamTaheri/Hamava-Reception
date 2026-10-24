"""Real-deposit waitlist acceptance requires explicitly reviewed current terms.

All identities, clinics and merchant configuration are synthetic. No gateway or
SMS is called; accepting an offer creates a pending-payment booking only.
"""

from datetime import timedelta
import json

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import func, select

from receptionist.db import get_db, now_utc
from receptionist.models import Appointment, Tenant, User
from receptionist.models_ops import PaymentIntent, WaitlistOffer
from receptionist.operations import (
    OfferViewInput,
    WaitlistInput,
    accept_offer,
    add_waitlist,
    offer_waitlist,
    public_offer_view,
    router,
    staff_offer_terms,
)
from receptionist.security import issue_token
from test_core import database as database
from test_core import future_day, slot_for
from test_payment_policy import configure_operator, owner, publish_real


def deposit_offer(db):
    tenant = db.get(Tenant, "clinic-niloufar")
    tenant.quiet_hours = {"start": "00:00", "end": "00:00"}
    db.commit()
    policy = publish_real(db)
    add_waitlist(
        db,
        tenant.id,
        WaitlistInput(
            provider_id="provider-niloufar-1",
            service_id="service-salon",
            patient_name="مراجع انتظار آزمایشی",
            phone="09123456789",
            date_from=future_day(),
            date_to=future_day(5),
            consent=True,
        ),
    )
    offer = offer_waitlist(db, tenant.id, slot_for(db, tenant.id, "provider-niloufar-1", "service-salon"))
    return offer, policy


@pytest.mark.parametrize("acceptance", [None, False])
def test_actual_deposit_offer_needs_separate_terms_acceptance(database, monkeypatch, acceptance):
    configure_operator(monkeypatch)
    with database() as db:
        offer, policy = deposit_offer(db)
        before = db.scalar(select(func.count()).select_from(Appointment))
        assert offer["deposit_toman"] == 100000 and offer["payment_terms"]["version"] == policy["version"]
        arguments = {} if acceptance is None else {"payment_terms_version": policy["version"], "payment_terms_accepted": False}
        with pytest.raises(HTTPException) as error:
            accept_offer(db, offer["id"], offer["accept_token"], True, **arguments)
        assert error.value.detail["code"] == "PAYMENT_TERMS_CONFIRMATION_REQUIRED"
        assert db.scalar(select(func.count()).select_from(Appointment)) == before
        assert db.get(WaitlistOffer, offer["id"]).status == "OFFERED"


def test_policy_change_requires_readback_and_fresh_acceptance_before_waitlist_booking(database, monkeypatch):
    configure_operator(monkeypatch)

    class NeverGateway:
        def __init__(self, *args, **kwargs):
            raise AssertionError("Offer acceptance must not create or verify a payment")

    monkeypatch.setattr("receptionist.payment_policy.ZarinpalGateway", NeverGateway)
    with database() as db:
        offer, initial = deposit_offer(db)
        updated = publish_real(db)
        with pytest.raises(HTTPException) as error:
            accept_offer(
                db,
                offer["id"],
                offer["accept_token"],
                True,
                payment_terms_version=initial["version"],
                payment_terms_accepted=True,
            )
        assert error.value.detail["code"] == "PAYMENT_TERMS_CONFIRMATION_REQUIRED"
        view = public_offer_view(offer["id"], OfferViewInput(token=offer["accept_token"]), db)
        assert view["payment_terms"]["version"] == updated["version"]
        assert view == staff_offer_terms(offer["id"], owner(db), db)
        assert "merchant" not in json.dumps(view)
        assert "09123456789" not in json.dumps(view)
        result = accept_offer(
            db,
            offer["id"],
            offer["accept_token"],
            True,
            payment_terms_version=updated["version"],
            payment_terms_accepted=True,
        )
        assert result["status"] == "PENDING_PAYMENT"
        assert result["payment_terms"]["version"] == updated["version"]
        assert db.get(WaitlistOffer, offer["id"]).status == "ACCEPTED"
        assert db.scalar(select(func.count()).select_from(PaymentIntent)) == 0
        assert accept_offer(db, offer["id"], offer["accept_token"], True)["id"] == result["id"]


@pytest.mark.asyncio
async def test_waitlist_terms_http_capability_scope_and_explicit_acceptance(database, monkeypatch):
    configure_operator(monkeypatch)
    app = FastAPI()
    app.include_router(router)

    def db_override():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = db_override
    with database() as db:
        offer, policy = deposit_offer(db)
        token = issue_token(db.get(User, "demo-owner"), "clinic-niloufar")
        wrong_tenant_token = issue_token(db.get(User, "demo-owner"), "clinic-bahar")
    path = "/api/v1/operations/waitlist/offers/" + offer["id"]
    public = "/api/v1/public/waitlist/" + offer["id"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test.invalid") as client:
        assert (await client.get(path + "/terms")).status_code == 401
        assert (await client.get(path + "/terms", headers={"Authorization": "Bearer " + wrong_tenant_token})).status_code == 404
        assert (await client.post(public + "/view", json={"token": "incorrect-capability-value"})).status_code == 404
        response = await client.post(public + "/view", json={"token": offer["accept_token"]})
        assert response.status_code == 200
        assert response.json()["payment_terms"]["version"] == policy["version"]
        assert "patient_name" not in response.json() and "phone_masked" not in response.json()
        assert (
            await client.post(path + "/accept", json={"confirmed": True}, headers={"Authorization": "Bearer " + token})
        ).status_code == 409
        response = await client.post(
            public + "/accept",
            json={
                "token": offer["accept_token"],
                "confirmed": True,
                "payment_terms_version": policy["version"],
                "payment_terms_accepted": True,
            },
        )
        assert response.status_code == 200 and response.json()["status"] == "PENDING_PAYMENT"


def test_expired_offer_cannot_reveal_actionable_terms(database, monkeypatch):
    configure_operator(monkeypatch)
    with database() as db:
        offer, _ = deposit_offer(db)
        db.get(WaitlistOffer, offer["id"]).expires_at = now_utc() - timedelta(seconds=1)
        db.commit()
        with pytest.raises(HTTPException) as error:
            public_offer_view(offer["id"], OfferViewInput(token=offer["accept_token"]), db)
        assert error.value.detail["code"] == "OFFER_EXPIRED"
