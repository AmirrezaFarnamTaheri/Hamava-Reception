"""Deposit terms and immutable tenant/merchant binding use local fake providers."""

import json

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import func, select

from receptionist.api import router as core_router
from receptionist.config import settings
from receptionist.core import ReceptionService
from receptionist.db import get_db, now_utc
from receptionist.models import Appointment, Tenant, User
from receptionist.models_ops import PaymentIntent, TenantPaymentPolicy
from receptionist.operations import create_payment, payment_callback
from receptionist.operations_uat import get_uat, approve_uat
from receptionist.payment_policy import (
    PaymentPolicyInput,
    configured_merchant,
    get_public_policy,
    policy_dict,
    publish_payment_policy,
    router,
)
from receptionist.providers import ProviderError, ZarinpalGateway
from receptionist.security import actor_for, issue_token
from test_clinic_uat import approval
from test_core import database as database
from test_core import slot_for


def configure_operator(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setenv("PAYMENT_PROVIDER_APPROVED", "true")
    monkeypatch.setenv("PAYMENT_TENANT_MERCHANTS_JSON", json.dumps({"clinic-niloufar": "niloufar-v1"}))
    monkeypatch.setenv(
        "PAYMENT_MERCHANTS_JSON", json.dumps({"niloufar-v1": {"merchant_id": "SYNTHETIC-MERCHANT-A", "sandbox": True, "approved": True}})
    )
    monkeypatch.setenv("ZARINPAL_MERCHANT_ID", "WRONG-GLOBAL-MERCHANT")
    monkeypatch.setenv("ZARINPAL_SANDBOX", "false")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://clinic.example.test")


def owner(db):
    return actor_for(db, db.get(User, "demo-owner"), "clinic-niloufar")


def terms(version=1, **changes):
    return PaymentPolicyInput(
        **{
            "version": version,
            "enabled": True,
            "hold_minutes": 20,
            "deposit_terms": "مبلغ بیعانه همان مبلغ نمایش‌داده‌شده خدمت است.",
            "cancellation_terms": "لغو طبق پنجره اعلام‌شده مرکز بررسی می‌شود.",
            "refund_terms": "بازپرداخت پس از بررسی پذیرش و ثبت مدرک بانکی انجام می‌شود.",
            "confirmed": True,
            **changes,
        }
    )


def publish_real(db):
    current = db.get(TenantPaymentPolicy, "clinic-niloufar")
    return publish_payment_policy(terms(current.version if current else 1), owner(db), db)


def make_booking(db, version, **changes):
    return ReceptionService(db, "clinic-niloufar", "demo-owner").create_appointment(
        slot_for(db, "clinic-niloufar", "provider-niloufar-1", "service-salon"),
        "مراجع مالی آزمایشی",
        "09123456789",
        changes.pop("key", "merchant-test-booking"),
        True,
        payment_terms_version=changes.pop("payment_terms_version", version),
        payment_terms_accepted=changes.pop("payment_terms_accepted", True),
        **changes,
    )


class SyntheticGateway:
    async def create(self, amount_toman, callback_url, description):
        assert amount_toman == 100000 and callback_url.startswith("https://clinic.example.test/")
        return {"authority": "SYNTHETICAUTHORITY123", "url": "https://sandbox.zarinpal.com/pg/StartPay/SYNTHETICAUTHORITY123"}


async def make_intent(db):
    policy = publish_real(db)
    booking = make_booking(db, policy["version"])
    result = await create_payment(db, "clinic-niloufar", booking["id"], SyntheticGateway())
    return db.get(PaymentIntent, result["id"]), db.get(Appointment, booking["id"])


def test_global_merchant_is_not_a_tenant_binding(database, monkeypatch):
    configure_operator(monkeypatch)
    monkeypatch.setenv("PAYMENT_TENANT_MERCHANTS_JSON", "{}")
    with database() as db:
        with pytest.raises(HTTPException) as error:
            publish_real(db)
        assert error.value.detail["code"] == "TENANT_MERCHANT_REQUIRED"
        assert db.get(TenantPaymentPolicy, "clinic-niloufar") is None
        assert not policy_dict(db, "clinic-niloufar")["merchant_ready"]
        with pytest.raises(ProviderError):
            configured_merchant("clinic-bahar")


def test_real_deposit_rejected_before_policy_or_explicit_current_acceptance(database, monkeypatch):
    configure_operator(monkeypatch)
    with database() as db:
        before = db.scalar(select(func.count()).select_from(Appointment))
        with pytest.raises(HTTPException) as error:
            make_booking(db, 1)
        assert error.value.detail["code"] == "DEPOSIT_POLICY_NOT_PUBLISHED"
        policy = publish_real(db)
        for kwargs in [{"payment_terms_accepted": False}, {"payment_terms_version": policy["version"] - 1}]:
            with pytest.raises(HTTPException) as error:
                make_booking(db, policy["version"], **kwargs)
            assert error.value.detail["code"] == "PAYMENT_TERMS_CONFIRMATION_REQUIRED"
        assert db.scalar(select(func.count()).select_from(Appointment)) == before
        result = make_booking(db, policy["version"])
        assert result["status"] == "PENDING_PAYMENT"
        assert result["payment_terms"]["version"] == policy["version"]
        assert result["payment_terms"]["synthetic"] is False


@pytest.mark.asyncio
async def test_terms_expiry_and_merchant_are_pinned_before_hosted_link(database, monkeypatch):
    configure_operator(monkeypatch)
    with database() as db:
        payment, booking = await make_intent(db)
        original = dict(payment.terms_snapshot)
        assert payment.currency == "TOMAN" and payment.gateway_currency == "IRR"
        assert payment.merchant_alias == "niloufar-v1" and payment.merchant_sandbox is True
        assert payment.merchant_identity_hash == configured_merchant(booking.tenant_id).identity_hash
        assert 19 * 60 < (booking.expires_at - now_utc()).total_seconds() <= 20 * 60
        current = db.get(TenantPaymentPolicy, booking.tenant_id)
        publish_payment_policy(terms(current.version, refund_terms="شرایط اصلاح‌شده برای رزروهای جدید منتشر شد."), owner(db), db)
        db.refresh(payment)
        assert payment.terms_snapshot == original and booking.payment_terms_snapshot == original
        assert "merchant_identity_hash" not in get_public_policy("niloufar", db)


@pytest.mark.asyncio
async def test_callback_uses_original_merchant_even_after_tenant_maps_to_new_alias(database, monkeypatch):
    configure_operator(monkeypatch)
    with database() as db:
        payment, booking = await make_intent(db)
        monkeypatch.setenv("PAYMENT_TENANT_MERCHANTS_JSON", json.dumps({"clinic-niloufar": "niloufar-v2"}))
        monkeypatch.setenv(
            "PAYMENT_MERCHANTS_JSON",
            json.dumps(
                {
                    "niloufar-v1": {"merchant_id": "SYNTHETIC-MERCHANT-A", "sandbox": True, "approved": True},
                    "niloufar-v2": {"merchant_id": "SYNTHETIC-MERCHANT-B", "sandbox": False, "approved": True},
                }
            ),
        )
        seen = []

        class PinnedVerifier:
            def __init__(self, *, merchant_id, sandbox):
                seen.append((merchant_id, sandbox))

            async def verify(self, authority, amount_toman):
                assert not db.in_transaction()
                assert authority == payment.authority and amount_toman == 100000
                return {"verified": True, "reference": "SYNTHETIC-SETTLEMENT-123"}

        monkeypatch.setattr("receptionist.payment_policy.ZarinpalGateway", PinnedVerifier)
        assert (await payment_callback(payment.authority, "OK", db))["status"] == "SETTLED"
        assert seen == [("SYNTHETIC-MERCHANT-A", True)]
        assert booking.status == "CONFIRMED"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["merchant", "sandbox", "missing", "amount", "currency"])
async def test_callback_fails_closed_on_binding_change_without_verifying(database, monkeypatch, change):
    configure_operator(monkeypatch)
    with database() as db:
        payment, booking = await make_intent(db)
        if change in {"merchant", "sandbox", "missing"}:
            configuration = {
                "merchant_id": "SYNTHETIC-MERCHANT-X" if change == "merchant" else "SYNTHETIC-MERCHANT-A",
                "sandbox": change != "sandbox",
                "approved": True,
            }
            monkeypatch.setenv("PAYMENT_MERCHANTS_JSON", json.dumps({} if change == "missing" else {"niloufar-v1": configuration}))
        elif change == "amount":
            payment.amount_toman += 1
            db.commit()
        else:
            payment.currency = "USD"
            db.commit()

        class NeverVerify:
            def __init__(self, **kwargs):
                raise AssertionError("Invalid binding must fail before gateway construction")

        monkeypatch.setattr("receptionist.payment_policy.ZarinpalGateway", NeverVerify)
        with pytest.raises(HTTPException) as error:
            await payment_callback(payment.authority, "OK", db)
        assert error.value.detail["code"] == "PAYMENT_MERCHANT_UNAVAILABLE"
        assert payment.status == "PENDING" and booking.status == "PENDING_PAYMENT"


def test_changed_identity_under_same_alias_requires_policy_republication(database, monkeypatch):
    configure_operator(monkeypatch)
    with database() as db:
        policy = publish_real(db)
        monkeypatch.setenv(
            "PAYMENT_MERCHANTS_JSON",
            json.dumps({"niloufar-v1": {"merchant_id": "SYNTHETIC-MERCHANT-CHANGED", "sandbox": True, "approved": True}}),
        )
        assert policy_dict(db, "clinic-niloufar")["merchant_configuration_status"] == "PUBLISHED_MERCHANT_CHANGED"
        with pytest.raises(HTTPException) as error:
            make_booking(db, policy["version"])
        assert error.value.detail["code"] == "PAYMENT_POLICY_MERCHANT_CHANGED"


@pytest.mark.asyncio
async def test_explicit_provider_binding_overrides_legacy_global_environment(monkeypatch):
    configure_operator(monkeypatch)
    seen = []

    def handler(request):
        payload = json.loads(request.content)
        seen.append((str(request.url), payload))
        if request.url.path.endswith("request.json"):
            return httpx.Response(200, json={"data": {"code": 100, "authority": "SYNTHETICAUTHORITY"}})
        return httpx.Response(200, json={"data": {"code": 101, "ref_id": "SYNTHETIC-REF"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        gateway = ZarinpalGateway(client, merchant_id="EXPLICIT-MERCHANT", sandbox=True)
        await gateway.create(12345, "https://clinic.example.test/callback", "بیعانه")
        await gateway.verify("SYNTHETICAUTHORITY", 12345)
    assert all(
        "sandbox.zarinpal.com" in url and data["merchant_id"] == "EXPLICIT-MERCHANT" and data["amount"] == 123450 for url, data in seen
    )
    assert seen[0][1]["currency"] == "IRR"


def test_payment_policy_changes_invalidate_production_clinic_uat(database, monkeypatch):
    configure_operator(monkeypatch)
    monkeypatch.setattr(settings, "environment", "production")
    with database() as db:
        tenant = db.get(Tenant, "clinic-niloufar")
        ReceptionService(db, tenant.id, "demo-owner").update_settings({"version": tenant.settings_version, "mode": "paused"})
        publish_real(db)
        approve_uat(approval(db, tenant=tenant.id), owner(db), db)
        assert get_uat("ai_primary", owner(db), db)["approved"]
        publish_real(db)
        assert get_uat("ai_primary", owner(db), db)["approved"] is False


@pytest.mark.asyncio
async def test_payment_policy_http_auth_and_actual_booking_acceptance(database, monkeypatch):
    configure_operator(monkeypatch)
    app = FastAPI()
    app.include_router(core_router)
    app.include_router(router)

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with database() as db:
        token = issue_token(db.get(User, "demo-owner"), "clinic-niloufar")
        staff_token = issue_token(db.get(User, "demo-receptionist"), "clinic-bahar")
        slot = slot_for(db, "clinic-niloufar", "provider-niloufar-1", "service-salon")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/operations/payment-policy")).status_code == 401
        assert (
            await client.put(
                "/api/v1/operations/payment-policy", json=terms().model_dump(), headers={"Authorization": "Bearer " + staff_token}
            )
        ).status_code == 403
        response = await client.put(
            "/api/v1/operations/payment-policy", json=terms().model_dump(), headers={"Authorization": "Bearer " + token}
        )
        assert response.status_code == 200 and response.json()["merchant_ready"]
        version = response.json()["version"]
        public = await client.get("/api/v1/public/clinics/niloufar/payment-policy")
        assert public.status_code == 200 and public.json()["version"] == version
        assert "merchant_alias" not in public.json() and "merchant_identity_hash" not in public.json()
        body = {
            "slot_id": slot,
            "patient_name": "مراجع مالی آزمایشی",
            "phone": "09123456789",
            "confirmed": True,
            "idempotency_key": "http-terms-booking",
        }
        headers = {"Authorization": "Bearer " + token}
        assert (await client.post("/api/v1/appointments", json=body, headers=headers)).status_code == 409
        accepted = await client.post(
            "/api/v1/appointments", json={**body, "payment_terms_version": version, "payment_terms_accepted": True}, headers=headers
        )
        assert accepted.status_code == 201 and accepted.json()["payment_terms"]["version"] == version
