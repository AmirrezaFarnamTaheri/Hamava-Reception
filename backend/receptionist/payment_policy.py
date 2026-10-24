"""Published deposit terms and explicit tenant-bound gateway identities.

Two operator environment registries map tenant -> alias and alias -> approved
merchant configuration. Payment intents pin the alias, identity hash, sandbox
and accepted terms. Existing intents never silently switch to a new merchant.
"""

from dataclasses import dataclass
import hashlib
import json
import os
import re

from fastapi import APIRouter, Depends
from pydantic import Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .core import iso, request_digest
from .db import get_db, now_utc
from .models import Service, Tenant
from .models_ops import PaymentIntent, TenantPaymentPolicy
from .operations import audit
from .providers import ProviderError, ZarinpalGateway, enabled
from .schemas import StrictModel
from .security import Actor, current_actor, fail, has_permission, require_permissions

router = APIRouter(prefix="/api/v1")
def staff(actor: Actor = Depends(current_actor)):
    if not (has_permission(actor, "policy:read") or has_permission(actor, "billing:read")):
        fail(403, "PERMISSION_REQUIRED", "Published payment terms require policy or billing read access.")
    return actor


admin = require_permissions("billing:write")
TERM_FIELDS = ("deposit_terms", "cancellation_terms", "refund_terms")


@dataclass(frozen=True)
class MerchantBinding:
    alias: str
    merchant_id: str
    sandbox: bool

    @property
    def identity_hash(self) -> str:
        return hashlib.sha256(
            json.dumps(
                {"provider": "zarinpal", "merchant_id": self.merchant_id, "sandbox": self.sandbox}, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest()


def registry(name: str) -> dict:
    raw = os.getenv(name, "{}")
    if len(raw) > 65536:
        raise ProviderError("MERCHANT_CONFIGURATION_INVALID")
    try:
        result = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ProviderError("MERCHANT_CONFIGURATION_INVALID") from exc
    if not isinstance(result, dict):
        raise ProviderError("MERCHANT_CONFIGURATION_INVALID")
    return result


def configured_merchant(tenant_id: str, *, pinned: dict | None = None) -> MerchantBinding:
    if not enabled("PAYMENT_PROVIDER_APPROVED"):
        raise ProviderError("PAYMENT_NOT_APPROVED")
    if pinned is None:
        alias = registry("PAYMENT_TENANT_MERCHANTS_JSON").get(tenant_id)
    else:
        if pinned.get("tenant_id") != tenant_id or pinned.get("synthetic") is not False:
            raise ProviderError("PAYMENT_BINDING_INVALID")
        alias = pinned.get("merchant_alias")
    if not isinstance(alias, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", alias):
        raise ProviderError("TENANT_MERCHANT_NOT_CONFIGURED")
    value = registry("PAYMENT_MERCHANTS_JSON").get(alias)
    if not isinstance(value, dict) or value.get("approved") is not True:
        raise ProviderError("TENANT_MERCHANT_NOT_APPROVED")
    merchant_id, sandbox = value.get("merchant_id"), value.get("sandbox")
    if not isinstance(merchant_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{6,120}", merchant_id) or not isinstance(sandbox, bool):
        raise ProviderError("MERCHANT_CONFIGURATION_INVALID")
    binding = MerchantBinding(alias, merchant_id, sandbox)
    if pinned is not None and (
        pinned.get("merchant_identity_hash") != binding.identity_hash or pinned.get("merchant_sandbox") is not sandbox
    ):
        raise ProviderError("PAYMENT_MERCHANT_CHANGED")
    return binding


def synthetic_policy(tenant_id: str) -> dict:
    return {
        "tenant_id": tenant_id,
        "version": 0,
        "enabled": True,
        "synthetic": True,
        "currency": "TOMAN",
        "gateway_currency": "IRR",
        "hold_minutes": settings.payment_hold_minutes,
        "deposit_terms": "فقط نمایش آزمایشی است؛ هیچ پول واقعی منتقل نمی‌شود.",
        "cancellation_terms": "لغو آزمایشی تابع بازه لغو ثبت‌شده مرکز است.",
        "refund_terms": "بازپرداخت در این نمایش فقط سابقه آزمایشی است و انتقال بانکی ندارد.",
        "merchant_alias": "DEMO-" + tenant_id,
        "merchant_identity_hash": hashlib.sha256(("synthetic:" + tenant_id).encode()).hexdigest(),
        "merchant_sandbox": True,
        "published_at": None,
        "published_by": None,
    }


def public_snapshot(snapshot: dict | None) -> dict | None:
    if not snapshot:
        return None
    fields = (
        "version",
        "enabled",
        "synthetic",
        "currency",
        "hold_minutes",
        "deposit_terms",
        "cancellation_terms",
        "refund_terms",
        "deposit_toman",
        "published_at",
    )
    return {key: snapshot.get(key) for key in fields if key in snapshot}


def public_payment_policy(db: Session, tenant_id: str) -> dict:
    row = db.get(TenantPaymentPolicy, tenant_id)
    if row is None:
        return (
            public_snapshot(synthetic_policy(tenant_id))
            if settings.demo_mode
            else {
                "version": 1,
                "enabled": False,
                "synthetic": False,
                "currency": "TOMAN",
                "hold_minutes": 60,
                "deposit_terms": "",
                "cancellation_terms": "",
                "refund_terms": "",
                "published_at": None,
            }
        )
    return {
        "version": row.version,
        "enabled": row.enabled,
        "synthetic": settings.demo_mode,
        "currency": row.currency,
        "hold_minutes": row.hold_minutes,
        **{key: getattr(row, key) for key in TERM_FIELDS},
        "published_at": iso(row.published_at),
    }


def policy_dict(db: Session, tenant_id: str) -> dict:
    row = db.get(TenantPaymentPolicy, tenant_id)
    binding, error = None, None
    try:
        binding = configured_merchant(tenant_id)
        if (
            row
            and row.enabled
            and (
                row.merchant_alias != binding.alias
                or row.merchant_identity_hash != binding.identity_hash
                or row.merchant_sandbox is not binding.sandbox
            )
        ):
            binding, error = None, "PUBLISHED_MERCHANT_CHANGED"
    except ProviderError as exc:
        error = exc.code
    return {
        "version": row.version if row else 1,
        "enabled": row.enabled if row else False,
        "currency": "TOMAN",
        "hold_minutes": row.hold_minutes if row else 60,
        **{key: getattr(row, key) if row else "" for key in TERM_FIELDS},
        "merchant_alias": binding.alias if binding else row.merchant_alias if row else None,
        "merchant_ready": binding is not None,
        "merchant_configuration_status": "CONFIGURED_NOT_LIVE_VERIFIED" if binding else error,
        "demonstration": settings.demo_mode,
        "published_at": iso(row.published_at) if row else None,
        "published_by": row.published_by if row else None,
    }


@router.get("/operations/payment-policy")
def get_payment_policy(actor: Actor = Depends(staff), db: Session = Depends(get_db)):
    return policy_dict(db, actor.tenant_id)


class PaymentPolicyInput(StrictModel):
    version: int = Field(ge=1)
    enabled: StrictBool
    hold_minutes: int = Field(default=60, ge=5, le=1440)
    deposit_terms: str = Field(default="", max_length=2000)
    cancellation_terms: str = Field(default="", max_length=2000)
    refund_terms: str = Field(default="", max_length=2000)
    confirmed: StrictBool


@router.put("/operations/payment-policy")
def publish_payment_policy(data: PaymentPolicyInput, actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    from .operations_uat import require_catalog_edit_safe

    if not data.confirmed:
        fail(422, "CONFIRMATION_REQUIRED", "انتشار شرایط پرداخت باید توسط مسئول مرکز تایید شود.")
    if data.enabled and any(len(getattr(data, key).strip()) < 10 for key in TERM_FIELDS):
        fail(422, "PAYMENT_TERMS_REQUIRED", "شرایط بیعانه، لغو و بازپرداخت باید روشن و کامل منتشر شود.")
    if any(any(ord(char) < 32 and char not in "\n\t" for char in getattr(data, key)) for key in TERM_FIELDS):
        fail(422, "INVALID_PAYMENT_TERMS", "متن شرایط دارای نویسه نامعتبر است.")
    require_catalog_edit_safe(db, actor.tenant_id)
    row = db.get(TenantPaymentPolicy, actor.tenant_id, populate_existing=True)
    current = row.version if row else 1
    if data.version != current:
        fail(409, "STALE_VERSION", "شرایط پرداخت هم‌زمان تغییر کرده است.")
    alias, binding = None, None
    if data.enabled and not settings.demo_mode:
        try:
            binding = configured_merchant(actor.tenant_id)
            alias = binding.alias
        except ProviderError:
            fail(409, "TENANT_MERCHANT_REQUIRED", "پیش از فعال‌سازی بیعانه، پیکربندی تاییدشده درگاه مخصوص همین مرکز لازم است.")
    if row is None:
        row = TenantPaymentPolicy(tenant_id=actor.tenant_id)
        db.add(row)
    row.version, row.enabled, row.hold_minutes = current + 1, data.enabled, data.hold_minutes
    row.currency = "TOMAN"
    for key in TERM_FIELDS:
        setattr(row, key, getattr(data, key))
    row.merchant_alias, row.published_by, row.published_at = alias, actor.id, now_utc()
    row.merchant_identity_hash = binding.identity_hash if binding else None
    row.merchant_sandbox = binding.sandbox if binding else None
    audit(
        db,
        actor.tenant_id,
        actor.id,
        "payment.policy_published",
        "tenant",
        actor.tenant_id,
        version=row.version,
        enabled=row.enabled,
        currency=row.currency,
        hold_minutes=row.hold_minutes,
        merchant_alias=alias,
        terms={key: getattr(row, key) for key in TERM_FIELDS},
        terms_digest=request_digest({key: getattr(row, key) for key in TERM_FIELDS}),
        verification="operator_published_terms_require_independent_legal_and_provider_review",
    )
    db.commit()
    return policy_dict(db, actor.tenant_id)


@router.get("/public/clinics/{slug}/payment-policy")
def get_public_policy(slug: str, db: Session = Depends(get_db)):
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug, Tenant.active.is_(True)))
    if tenant is None:
        fail(404, "NOT_FOUND", "مرکز پیدا نشد.")
    return public_payment_policy(db, tenant.id)


def booking_payment_terms(db: Session, tenant_id: str, service: Service, accepted_version: int | None, accepted: bool) -> dict | None:
    if not service.deposit_toman:
        return None
    row = db.get(TenantPaymentPolicy, tenant_id)
    if row is None and settings.demo_mode:
        return {**synthetic_policy(tenant_id), "deposit_toman": service.deposit_toman}
    if row is None or not row.enabled or any(len(getattr(row, key).strip()) < 10 for key in TERM_FIELDS):
        fail(409, "DEPOSIT_POLICY_NOT_PUBLISHED", "بیعانه تا انتشار شرایط معتبر این مرکز غیرفعال است؛ پذیرش باید بررسی کند.")
    if not settings.demo_mode and (accepted is not True or accepted_version != row.version):
        fail(
            409,
            "PAYMENT_TERMS_CONFIRMATION_REQUIRED",
            "شرایط جاری بیعانه، لغو و بازپرداخت باید پیش از رزرو به مراجعه‌کننده ارائه و تایید شود.",
        )
    snapshot = {
        "tenant_id": tenant_id,
        **public_payment_policy(db, tenant_id),
        "deposit_toman": service.deposit_toman,
        "gateway_currency": "IRR",
        "published_by": row.published_by,
    }
    if settings.demo_mode:
        synthetic = synthetic_policy(tenant_id)
        snapshot.update({key: synthetic[key] for key in ("merchant_alias", "merchant_identity_hash", "merchant_sandbox")})
    else:
        try:
            binding = configured_merchant(tenant_id)
        except ProviderError:
            fail(503, "TENANT_MERCHANT_UNAVAILABLE", "درگاه همین مرکز در دسترس تاییدشده نیست؛ نوبت پرداختی ثبت نشد.")
        if (
            row.merchant_alias != binding.alias
            or row.merchant_identity_hash != binding.identity_hash
            or row.merchant_sandbox is not binding.sandbox
        ):
            fail(409, "PAYMENT_POLICY_MERCHANT_CHANGED", "درگاه مرکز تغییر کرده است؛ شرایط پرداخت باید دوباره منتشر و تایید شود.")
        snapshot.update(merchant_alias=binding.alias, merchant_identity_hash=binding.identity_hash, merchant_sandbox=binding.sandbox)
    return snapshot


def gateway_for_intent(intent: PaymentIntent) -> ZarinpalGateway:
    snapshot = intent.terms_snapshot or {}
    if (
        intent.currency != "TOMAN"
        or intent.gateway_currency != "IRR"
        or snapshot.get("currency") != "TOMAN"
        or snapshot.get("gateway_currency") != "IRR"
        or snapshot.get("deposit_toman") != intent.amount_toman
        or snapshot.get("version") != intent.terms_version
        or snapshot.get("merchant_alias") != intent.merchant_alias
        or snapshot.get("merchant_identity_hash") != intent.merchant_identity_hash
        or snapshot.get("merchant_sandbox") is not intent.merchant_sandbox
    ):
        raise ProviderError("PAYMENT_BINDING_INVALID")
    binding = configured_merchant(intent.tenant_id, pinned=snapshot)
    return ZarinpalGateway(merchant_id=binding.merchant_id, sandbox=binding.sandbox)
