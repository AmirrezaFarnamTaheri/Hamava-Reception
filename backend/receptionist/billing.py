"""Exact usage, reservation-before-I/O budgets, and auditable reconciliation.

These helpers flush but do not commit. Commit a reservation and its STARTED
marker before outbound I/O. A timeout is UNKNOWN, not a free failed request.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import hashlib
import json
import re
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, now_utc
from .models import Appointment, StaffTask, Tenant
from .models_finance import (CostRate, CostReservation, DemandAttribution, MonetaryPolicy, StaffTimeObservation,
    StaffWorkSession, TransportEvent, UsageCharge, VendorStatement, VendorStatementLine)
from .operations import audit
from .schemas import StrictModel
from .security import Actor, encrypt, fail, require_permissions

router = APIRouter(prefix="/api/v1/operations")
MICRO = 1_000_000
IDENTIFIER = r"^[A-Za-z0-9_.:/@-]{1,160}$"
ACTIVE_RESERVATIONS = {"RESERVED", "STARTED", "UNKNOWN", "UNPRICED"}


def number(value, *, positive=False) -> Decimal:
    if isinstance(value, bool):
        fail(422, "INVALID_DECIMAL", "An exact finite decimal is required.")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        fail(422, "INVALID_DECIMAL", "An exact finite decimal is required.")
    if not result.is_finite() or result < 0 or result > Decimal("1000000000000") or (positive and result <= 0):
        fail(422, "INVALID_DECIMAL", "Decimal is outside the permitted nonnegative range.")
    if result.as_tuple().exponent < -12:
        fail(422, "INVALID_DECIMAL", "Use at most 12 decimal places.")
    return result


def canonical(value) -> str:
    return format(number(value).normalize(), "f")


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(IDENTIFIER, value):
        fail(422, "INVALID_REFERENCE", "Use an opaque identifier, not patient details.")
    return value


def lock_tenant(db: Session, tenant_id: str, *, active_required: bool = True):
    query = update(Tenant).where(Tenant.id == tenant_id)
    if active_required:
        query = query.where(Tenant.active.is_(True))
    if db.execute(query.values(settings_version=Tenant.settings_version)).rowcount != 1:
        fail(404, "TENANT_NOT_FOUND", "Clinic is not available.")


def month_bounds(period: str | None = None):
    if period is None:
        period = now_utc().strftime("%Y-%m")
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", period):
        fail(422, "INVALID_PERIOD", "Use a Gregorian UTC accounting month YYYY-MM.")
    year, month = map(int, period.split("-"))
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(year + (month == 12), 1 if month == 12 else month + 1, 1, tzinfo=timezone.utc)
    return start, end


def current_policy(db, tenant_id):
    return db.scalar(select(MonetaryPolicy).where(MonetaryPolicy.tenant_id == tenant_id).order_by(MonetaryPolicy.version.desc()).limit(1))


def rate_dict(row: CostRate):
    return {k: getattr(row, k) for k in ("id", "provider", "meter", "version", "unit", "currency", "price_per_unit", "fx_toman_per_currency", "quantum", "minimum_quantity", "evidence_reference", "evidence_sha256")}


def calculate_cost(snapshot: dict, quantity) -> int:
    amount = number(quantity)
    if amount == 0:
        return 0
    quantum = number(snapshot["quantum"], positive=True)
    billable = max(number(snapshot["minimum_quantity"]), (amount / quantum).to_integral_value(rounding=ROUND_CEILING) * quantum)
    cost = billable * number(snapshot["price_per_unit"]) * number(snapshot["fx_toman_per_currency"], positive=True) * MICRO
    if cost > 9_000_000_000_000_000_000:
        fail(422, "COST_OVERFLOW", "Computed cost exceeds the supported range.")
    return int(cost.to_integral_value(rounding=ROUND_CEILING))


def spending(db, tenant_id, *, call_id=None, provider=None, period=None):
    start, end = month_bounds(period)
    charges = [UsageCharge.tenant_id == tenant_id, UsageCharge.occurred_at >= start, UsageCharge.occurred_at < end]
    reserves = [CostReservation.tenant_id == tenant_id, CostReservation.status.in_(ACTIVE_RESERVATIONS)]
    # Outstanding unknown charges from older months remain a liability. They
    # cannot disappear from admission simply because the UTC month changed.
    if call_id:
        charges = [UsageCharge.tenant_id == tenant_id, UsageCharge.call_id == call_id]
        reserves.append(CostReservation.call_id == call_id)
    if provider:
        charges.append(UsageCharge.provider == provider)
        reserves.append(CostReservation.provider == provider)
    charged = db.scalar(select(func.coalesce(func.sum(UsageCharge.cost_micro_toman), 0)).where(*charges)) or 0
    reserved = db.scalar(select(func.coalesce(func.sum(CostReservation.reserved_micro_toman), 0)).where(*reserves)) or 0
    unpriced = db.scalar(select(func.count()).select_from(UsageCharge).where(*charges, UsageCharge.cost_micro_toman.is_(None))) or 0
    return {"charged_micro_toman": int(charged), "reserved_micro_toman": int(reserved), "exposure_micro_toman": int(charged + reserved), "unpriced_events": unpriced}


def ticket_dict(row):
    return {"id": row.id, "status": row.status, "max_quantity": row.max_quantity,
        "reserved_micro_toman": row.reserved_micro_toman, "rate_version": row.rate_snapshot.get("version"),
        "provider": row.provider, "meter": row.meter}


def exact_toman(micro):
    return format(Decimal(micro) / MICRO, "f") if micro is not None else None


def reserve_cost(db: Session, tenant_id: str, operation_key: str, provider: str, meter: str, max_quantity, call_id: str | None = None) -> dict:
    for value in (operation_key, provider, meter):
        identifier(value)
    quantity = canonical(max_quantity)
    number(quantity, positive=True)
    if call_id:
        from .models_voice import CallSession
        call = db.get(CallSession, call_id)
        if not call or call.tenant_id != tenant_id:
            fail(404, "CALL_NOT_FOUND", "Call is not available in this clinic.")
    lock_tenant(db, tenant_id)
    request_hash = digest({"quantity": quantity, "call_id": call_id})
    existing = db.scalar(select(CostReservation).where(CostReservation.tenant_id == tenant_id,
        CostReservation.provider == provider, CostReservation.meter == meter, CostReservation.operation_key == operation_key))
    if existing:
        if existing.request_hash != request_hash:
            fail(409, "COST_IDEMPOTENCY_CONFLICT", "This operation has a different cost reservation.")
        if existing.status in {"RELEASED", "EXPIRED"}:
            fail(409, "COST_OPERATION_CLOSED", "Use a new attempt identifier after a safely closed attempt.")
        return ticket_dict(existing)
    expire_unused_reservations(db, tenant_id)
    policy = current_policy(db, tenant_id)
    rate = db.scalar(select(CostRate).where(CostRate.tenant_id == tenant_id, CostRate.provider == provider,
        CostRate.meter == meter, CostRate.effective_at <= now_utc(), CostRate.expires_at > now_utc()).order_by(CostRate.version.desc()).limit(1))
    enforced = settings.environment.lower() in {"prod", "production"} or bool(policy)
    if enforced and (not policy or not policy.enabled or not rate):
        fail(409, "MONETARY_POLICY_REQUIRED", "An enabled spending policy and current approved rate are required.")
    snapshot = rate_dict(rate) if rate else {}
    cost = calculate_cost(snapshot, quantity) if snapshot else 0
    if policy:
        exposure = spending(db, tenant_id)["exposure_micro_toman"]
        if cost > policy.operation_cap_micro_toman or exposure + cost > policy.monthly_cap_micro_toman:
            fail(429, "MONETARY_BUDGET_EXCEEDED", "The clinic spending limit cannot admit this operation.")
        if call_id and spending(db, tenant_id, call_id=call_id)["exposure_micro_toman"] + cost > policy.call_cap_micro_toman:
            fail(429, "CALL_COST_LIMIT", "The maximum cost for this call has been reached.")
        provider_cap = policy.provider_caps.get(provider)
        if provider_cap is not None and spending(db, tenant_id, provider=provider)["exposure_micro_toman"] + cost > provider_cap:
            fail(429, "PROVIDER_COST_LIMIT", "This provider spending limit has been reached.")
    row = CostReservation(tenant_id=tenant_id, call_id=call_id, operation_key=operation_key, request_hash=request_hash,
        provider=provider, meter=meter, max_quantity=quantity, rate_snapshot=snapshot,
        policy_version=policy.version if policy else None, reserved_micro_toman=cost,
        status="RESERVED" if snapshot else "UNPRICED", expires_at=now_utc() + timedelta(minutes=5))
    db.add(row)
    db.flush()
    return ticket_dict(row)


def expire_unused_reservations(db, tenant_id):
    return db.execute(update(CostReservation).where(CostReservation.tenant_id == tenant_id,
        CostReservation.status.in_(["RESERVED", "UNPRICED"]), CostReservation.started_at.is_(None),
        CostReservation.expires_at <= now_utc()).values(status="EXPIRED")).rowcount


def mark_cost_started(db, ticket_id: str):
    row = db.get(CostReservation, ticket_id)
    if row is None:
        fail(404, "COST_RESERVATION_NOT_FOUND", "Cost reservation is unavailable.")
    lock_tenant(db, row.tenant_id)
    db.refresh(row)
    if row.status == "STARTED":
        fail(409, "COST_ALREADY_STARTED", "This attempt already crossed the provider dispatch boundary; reconcile it before retrying.")
    if row.status not in {"RESERVED", "UNPRICED"} or row.expires_at <= now_utc():
        fail(409, "COST_RESERVATION_NOT_STARTABLE", "This attempt cannot start.")
    policy = current_policy(db, row.tenant_id)
    if policy:
        rate = db.get(CostRate, row.rate_snapshot.get("id")) if row.rate_snapshot else None
        if not policy.enabled or not rate or rate.expires_at <= now_utc():
            fail(409, "MONETARY_POLICY_CHANGED", "The approved spending policy or rate no longer permits starting this request.")
        if spending(db, row.tenant_id)["exposure_micro_toman"] > policy.monthly_cap_micro_toman or row.reserved_micro_toman > policy.operation_cap_micro_toman:
            fail(429, "MONETARY_BUDGET_EXCEEDED", "The current spending policy cannot admit this reserved operation.")
        if row.call_id and spending(db, row.tenant_id, call_id=row.call_id)["exposure_micro_toman"] > policy.call_cap_micro_toman:
            fail(429, "CALL_COST_LIMIT", "The current call cost limit cannot admit this operation.")
        provider_cap = policy.provider_caps.get(row.provider)
        if provider_cap is not None and spending(db, row.tenant_id, provider=row.provider)["exposure_micro_toman"] > provider_cap:
            fail(429, "PROVIDER_COST_LIMIT", "The current provider limit cannot admit this operation.")
    elif settings.environment.lower() in {"prod", "production"}:
        fail(409, "MONETARY_POLICY_REQUIRED", "Production dispatch requires an enabled current monetary policy.")
    row.status, row.started_at = "STARTED", now_utc()
    db.flush()
    return ticket_dict(row)


def settle_cost(db, ticket_id: str, quantity, source_reference: str, outcome="confirmed"):
    if outcome not in {"confirmed", "unknown", "no_charge"}:
        fail(422, "INVALID_COST_OUTCOME", "Unsupported settlement outcome.")
    identifier(source_reference)
    quantity = canonical(quantity)
    row = db.get(CostReservation, ticket_id)
    if not row:
        fail(404, "COST_RESERVATION_NOT_FOUND", "Cost reservation is unavailable.")
    # Deactivation prevents new dispatch, but cannot erase evidence returned
    # for an existing authorized attempt. Lock its original tenant and record.
    tenant_id = row.tenant_id
    lock_tenant(db, tenant_id, active_required=False)
    row = db.scalar(select(CostReservation).where(CostReservation.id == ticket_id,
        CostReservation.tenant_id == tenant_id).with_for_update().execution_options(populate_existing=True))
    if row is None:
        fail(404, "COST_RESERVATION_NOT_FOUND", "Cost reservation is unavailable.")
    if outcome == "unknown":
        if row.status in {"SETTLED", "RELEASED", "EXPIRED"}:
            fail(409, "COST_ALREADY_CLOSED", "Settled costs cannot become unknown.")
        row.status = "UNKNOWN"
        db.flush()
        return ticket_dict(row)
    key = digest({"provider": row.provider, "meter": row.meter, "source": source_reference})
    existing = db.scalar(select(UsageCharge).where(UsageCharge.tenant_id == row.tenant_id, UsageCharge.source_key == key))
    if existing:
        if existing.reservation_id != row.id or existing.quantity != quantity or existing.evidence.get("outcome") != outcome:
            fail(409, "COST_RECEIPT_CONFLICT", "A cost receipt cannot be reused with different evidence.")
        return {**ticket_dict(row), "charge_id": existing.id, "cost_micro_toman": existing.cost_micro_toman}
    if row.status not in ACTIVE_RESERVATIONS:
        fail(409, "COST_ALREADY_CLOSED", "This cost reservation is already closed.")
    if outcome == "no_charge" and number(quantity) != 0:
        fail(422, "NO_CHARGE_QUANTITY", "A no-charge result must have zero quantity.")
    cost = 0 if outcome == "no_charge" else calculate_cost(row.rate_snapshot, quantity) if row.rate_snapshot else None
    overrun = number(quantity) > number(row.max_quantity) or (cost is not None and cost > row.reserved_micro_toman and bool(row.rate_snapshot))
    charge = UsageCharge(tenant_id=row.tenant_id, reservation_id=row.id, call_id=row.call_id, provider=row.provider,
        meter=row.meter, quantity=quantity, unit=row.rate_snapshot.get("unit", "unpriced_unit"),
        currency=row.rate_snapshot.get("currency", "UNKNOWN"), rate_version=row.rate_snapshot.get("version"),
        cost_micro_toman=cost, source_key=key, source_reference=source_reference,
        evidence={"outcome": outcome, "basis": "approved_rate_calculation" if row.rate_snapshot else "unpriced_development",
            "overrun": overrun, "rate_snapshot": row.rate_snapshot}, occurred_at=now_utc())
    db.add(charge)
    row.status, row.settled_at = ("RELEASED" if outcome == "no_charge" else "SETTLED"), now_utc()
    if overrun:
        db.add(StaffTask(tenant_id=row.tenant_id, reason="COST_RESERVATION_OVERRUN", priority="urgent",
            summary="A provider result exceeded its authorized maximum; review the exact usage ledger before further work."))
        audit(db, row.tenant_id, "cost-ledger", "cost.reservation_overrun", "cost_reservation", row.id,
            provider=row.provider, meter=row.meter, reserved_micro_toman=row.reserved_micro_toman, actual_micro_toman=cost)
    db.flush()
    return {**ticket_dict(row), "charge_id": charge.id, "cost_micro_toman": cost, "overrun": overrun}


def record_vendor_cost(db, charge_id: str, billed_amount, currency: str, source_reference: str):
    """Append a cost adjustment only from an authenticated provider reply."""
    charge = db.get(UsageCharge, charge_id)
    if not charge or charge.adjusts_charge_id:
        fail(404, "CHARGE_NOT_FOUND", "Original usage charge is required.")
    identifier(source_reference)
    # This adjusts an existing charge from the same accepted provider reply;
    # it neither creates a reservation nor authorizes another provider request.
    lock_tenant(db, charge.tenant_id, active_required=False)
    amount = number(billed_amount)
    snapshot = charge.evidence.get("rate_snapshot", {})
    fx = Decimal("1") if currency == "TOMAN" else Decimal("0.1") if currency == "IRR" else number(snapshot.get("fx_toman_per_currency"), positive=True) if currency == snapshot.get("currency") else None
    if fx is None:
        fail(422, "UNAPPROVED_RECEIPT_CURRENCY", "Receipt currency has no approved pinned conversion rate.")
    exact = int((amount * fx * MICRO).to_integral_value(rounding=ROUND_CEILING))
    key = digest({"vendor_receipt": source_reference, "provider": charge.provider, "charge_id": charge.id})
    old = db.scalar(select(UsageCharge).where(UsageCharge.tenant_id == charge.tenant_id, UsageCharge.source_key == key))
    if old:
        if old.evidence.get("vendor_total_micro_toman") != exact or old.currency != currency:
            fail(409, "VENDOR_COST_CONFLICT", "A provider receipt cannot change the reported cost.")
        return old.id
    if db.scalar(select(UsageCharge.id).where(UsageCharge.tenant_id == charge.tenant_id, UsageCharge.adjusts_charge_id == charge.id)):
        fail(409, "VENDOR_COST_ALREADY_ADJUSTED", "This usage already has an adjustment and needs statement review.")
    row = UsageCharge(tenant_id=charge.tenant_id, adjusts_charge_id=charge.id, call_id=charge.call_id, provider=charge.provider,
        meter=charge.meter, quantity="0", unit=charge.unit, currency=currency, rate_version=charge.rate_version,
        cost_micro_toman=exact - (charge.cost_micro_toman or 0), source_key=key, source_reference=source_reference,
        evidence={"basis": "authenticated_provider_response", "vendor_total_micro_toman": exact, "vendor_amount": canonical(amount)}, occurred_at=charge.occurred_at)
    db.add(row)
    db.flush()
    return row.id


class RateInput(StrictModel):
    provider: str = Field(pattern=IDENTIFIER, max_length=80)
    meter: str = Field(pattern=IDENTIFIER, max_length=80)
    unit: str = Field(pattern=IDENTIFIER, max_length=30)
    currency: Literal["TOMAN", "IRR", "USD"]
    price_per_unit: str
    fx_toman_per_currency: str
    quantum: str = "1"
    minimum_quantity: str = "0"
    evidence_reference: str = Field(pattern=IDENTIFIER, max_length=160)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    effective_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_rate(self):
        for value in (self.price_per_unit, self.fx_toman_per_currency, self.quantum, self.minimum_quantity):
            number(value)
        number(self.quantum, positive=True)
        number(self.fx_toman_per_currency, positive=True)
        if self.currency == "TOMAN" and number(self.fx_toman_per_currency) != 1 or self.currency == "IRR" and number(self.fx_toman_per_currency) != Decimal("0.1"):
            raise ValueError("TOMAN FX must equal 1; IRR FX must equal 0.1")
        if not self.effective_at.tzinfo or not self.expires_at.tzinfo or self.expires_at <= self.effective_at or self.expires_at - self.effective_at > timedelta(days=366):
            raise ValueError("Supply timezone-aware effective/expiry dates no more than 366 days apart")
        return self


@router.post("/costs/rates")
def publish_rate(data: RateInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    version = (db.scalar(select(func.max(CostRate.version)).where(CostRate.tenant_id == actor.tenant_id, CostRate.provider == data.provider, CostRate.meter == data.meter)) or 0) + 1
    row = CostRate(tenant_id=actor.tenant_id, version=version, approved_by=actor.id, **data.model_dump())
    db.add(row)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "cost.rate_published", "cost_rate", row.id, version=version, provider=data.provider, meter=data.meter, evidence_sha256=data.evidence_sha256)
    db.commit()
    return {**rate_dict(row), "effective_at": row.effective_at, "expires_at": row.expires_at, "verification": "operator_attested"}


class BudgetInput(StrictModel):
    enabled: bool = True
    monthly_cap_toman: int = Field(ge=1, le=1_000_000_000_000)
    call_cap_toman: int = Field(ge=1, le=1_000_000_000)
    operation_cap_toman: int = Field(ge=1, le=1_000_000_000)
    soft_percent: int = Field(default=80, ge=1, le=99)
    provider_caps_toman: dict[str, int] = Field(default_factory=dict, max_length=30)

    @model_validator(mode="after")
    def validate_limits(self):
        if self.call_cap_toman > self.monthly_cap_toman or self.operation_cap_toman > self.call_cap_toman:
            raise ValueError("operation <= call <= monthly caps are required")
        if any(not re.fullmatch(IDENTIFIER, key) or value <= 0 or value > self.monthly_cap_toman for key, value in self.provider_caps_toman.items()):
            raise ValueError("Provider caps must be positive and no greater than monthly cap")
        return self


def policy_dict(row):
    if not row:
        return None
    return {"version": row.version, "enabled": row.enabled, "monthly_cap_toman": row.monthly_cap_micro_toman // MICRO,
        "call_cap_toman": row.call_cap_micro_toman // MICRO, "operation_cap_toman": row.operation_cap_micro_toman // MICRO,
        "soft_percent": row.soft_percent, "provider_caps_toman": {k: v // MICRO for k, v in row.provider_caps.items()}, "created_at": row.created_at}


@router.put("/costs/policy")
def publish_budget(data: BudgetInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    old = current_policy(db, actor.tenant_id)
    row = MonetaryPolicy(tenant_id=actor.tenant_id, version=(old.version if old else 0) + 1, enabled=data.enabled,
        monthly_cap_micro_toman=data.monthly_cap_toman * MICRO, call_cap_micro_toman=data.call_cap_toman * MICRO,
        operation_cap_micro_toman=data.operation_cap_toman * MICRO, soft_percent=data.soft_percent,
        provider_caps={k: v * MICRO for k, v in data.provider_caps_toman.items()}, approved_by=actor.id)
    db.add(row)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "cost.policy_published", "monetary_policy", row.id, version=row.version, enabled=row.enabled)
    db.commit()
    return policy_dict(row)


@router.get("/costs")
def costs(actor: Actor = Depends(require_permissions("billing:read")), db: Session = Depends(get_db)):
    policy = current_policy(db, actor.tenant_id)
    value = spending(db, actor.tenant_id)
    return {"policy": policy_dict(policy), "period": now_utc().strftime("%Y-%m"), "period_timezone": "UTC", **value,
        "charged_toman": exact_toman(value["charged_micro_toman"]), "reserved_toman": exact_toman(value["reserved_micro_toman"]), "exposure_toman": exact_toman(value["exposure_micro_toman"]),
        "soft_limit_reached": bool(policy and value["exposure_micro_toman"] * 100 >= policy.monthly_cap_micro_toman * policy.soft_percent),
        "rates": [{**rate_dict(r), "effective_at": r.effective_at, "expires_at": r.expires_at} for r in db.scalars(select(CostRate).where(CostRate.tenant_id == actor.tenant_id).order_by(CostRate.created_at.desc()).limit(100))],
        "currency": "TOMAN", "money_scale": MICRO, "unknown_reservations": db.scalar(select(func.count()).select_from(CostReservation).where(CostReservation.tenant_id == actor.tenant_id, CostReservation.status == "UNKNOWN"))}


@router.get("/costs/ledger")
def ledger(limit: int = 100, actor: Actor = Depends(require_permissions("billing:read")), db: Session = Depends(get_db)):
    if not 1 <= limit <= 500:
        fail(422, "INVALID_LIMIT", "Limit must be between 1 and 500.")
    return [{**{k: getattr(r, k) for k in ("id", "reservation_id", "call_id", "provider", "meter", "quantity", "unit", "currency", "rate_version", "cost_micro_toman", "source_reference", "adjusts_charge_id", "occurred_at")}, "cost_toman_exact": exact_toman(r.cost_micro_toman)} for r in db.scalars(select(UsageCharge).where(UsageCharge.tenant_id == actor.tenant_id).order_by(UsageCharge.created_at.desc()).limit(limit))]


@router.get("/costs/reservations")
def reservations(actor: Actor = Depends(require_permissions("billing:read")), db: Session = Depends(get_db)):
    return [{**ticket_dict(row), "call_id": row.call_id, "created_at": row.created_at,
        "reserved_toman_exact": exact_toman(row.reserved_micro_toman), "started_at": row.started_at}
        for row in db.scalars(select(CostReservation).where(CostReservation.tenant_id == actor.tenant_id,
            CostReservation.status.in_(["STARTED", "UNKNOWN"])).order_by(CostReservation.created_at).limit(200))]


class ReservationReconcileInput(StrictModel):
    outcome: Literal["confirmed", "no_charge"]
    quantity: str
    source_reference: str = Field(pattern=IDENTIFIER)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    provider_result_verified: bool


@router.post("/costs/reservations/{reservation_id}/reconcile")
def reconcile_reservation(reservation_id: str, data: ReservationReconcileInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    if not data.provider_result_verified:
        fail(422, "VERIFIED_PROVIDER_RESULT_REQUIRED", "Reconcile only after checking authoritative provider evidence.")
    lock_tenant(db, actor.tenant_id)
    row = db.get(CostReservation, reservation_id)
    if not row or row.tenant_id != actor.tenant_id:
        fail(404, "COST_RESERVATION_NOT_FOUND", "Cost reservation is not available in this clinic.")
    if row.status not in {"STARTED", "UNKNOWN"}:
        fail(409, "RESERVATION_RECONCILIATION_NOT_REQUIRED", "Only unfinished provider operations can be reconciled.")
    result = settle_cost(db, row.id, data.quantity, data.source_reference, data.outcome)
    audit(db, actor.tenant_id, actor.id, "cost.reservation_reconciled", "cost_reservation", row.id,
        outcome=data.outcome, evidence_sha256=data.evidence_sha256, evidence_verification="operator_attested_provider_result")
    db.commit()
    return {**result, "cost_toman_exact": exact_toman(result.get("cost_micro_toman")), "verification": "operator_attested_provider_result"}


class StatementLineInput(StrictModel):
    reference: str = Field(pattern=IDENTIFIER)
    charge_id: str | None = None
    meter: str = Field(pattern=IDENTIFIER, max_length=80)
    quantity: str
    unit: str = Field(pattern=IDENTIFIER, max_length=30)
    currency: Literal["TOMAN", "IRR", "USD"]
    billed_amount: str
    fx_toman_per_currency: str


class StatementInput(StrictModel):
    provider: str = Field(pattern=IDENTIFIER, max_length=80)
    reference: str = Field(pattern=IDENTIFIER)
    period: str
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    lines: list[StatementLineInput] = Field(min_length=1, max_length=500)


def statement_dict(db, row):
    return {"id": row.id, "provider": row.provider, "reference": row.reference, "period": row.period,
        "verification": "operator_submitted_document", "evidence_sha256": row.evidence_sha256,
        "lines": [{**{k: getattr(line, k) for k in ("id", "reference", "charge_id", "meter", "quantity", "unit", "currency", "billed_amount", "billed_micro_toman", "discrepancy_micro_toman", "status")}, "billed_toman_exact": exact_toman(line.billed_micro_toman), "discrepancy_toman_exact": exact_toman(line.discrepancy_micro_toman)} for line in db.scalars(select(VendorStatementLine).where(VendorStatementLine.statement_id == row.id))]}


@router.post("/costs/statements")
def import_statement(data: StatementInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    month_bounds(data.period)
    lock_tenant(db, actor.tenant_id)
    request_hash = digest(data.model_dump())
    old = db.scalar(select(VendorStatement).where(VendorStatement.tenant_id == actor.tenant_id, VendorStatement.provider == data.provider, VendorStatement.reference == data.reference))
    if old:
        if old.payload_hash != request_hash:
            fail(409, "STATEMENT_CONFLICT", "This statement reference already has different contents.")
        return statement_dict(db, old)
    if len({line.reference for line in data.lines}) != len(data.lines) or len({line.charge_id for line in data.lines if line.charge_id}) != sum(line.charge_id is not None for line in data.lines):
        fail(422, "DUPLICATE_STATEMENT_LINE", "A statement cannot count the same line or charge twice.")
    row = VendorStatement(tenant_id=actor.tenant_id, provider=data.provider, reference=data.reference, period=data.period,
        evidence_sha256=data.evidence_sha256, payload_hash=request_hash, submitted_by=actor.id)
    db.add(row)
    db.flush()
    for item in data.lines:
        quantity, amount, fx = canonical(item.quantity), number(item.billed_amount), number(item.fx_toman_per_currency, positive=True)
        if item.currency == "TOMAN" and fx != 1 or item.currency == "IRR" and fx != Decimal("0.1"):
            fail(422, "INVALID_FX", "Rial/Toman conversion must use exact units.")
        charge = db.get(UsageCharge, item.charge_id) if item.charge_id else None
        if item.charge_id and (not charge or charge.tenant_id != actor.tenant_id or charge.provider != data.provider):
            fail(404, "CHARGE_NOT_FOUND", "The charge does not belong to this clinic and provider.")
        if charge and db.scalar(select(VendorStatementLine.id).where(VendorStatementLine.tenant_id == actor.tenant_id, VendorStatementLine.charge_id == charge.id)):
            fail(409, "CHARGE_ALREADY_RECONCILED", "This charge already appears in an imported statement.")
        billed = int((amount * fx * MICRO).to_integral_value(rounding=ROUND_CEILING))
        if billed > 9_000_000_000_000_000_000:
            fail(422, "COST_OVERFLOW", "Statement line exceeds supported range.")
        previous_adjustments = list(db.scalars(select(UsageCharge).where(UsageCharge.tenant_id == actor.tenant_id, UsageCharge.adjusts_charge_id == charge.id))) if charge else []
        known = bool(charge and (charge.cost_micro_toman is not None or any(r.evidence.get("basis") == "authenticated_provider_response" for r in previous_adjustments)))
        effective_cost = (charge.cost_micro_toman or 0) + sum(r.cost_micro_toman or 0 for r in previous_adjustments) if charge else None
        difference = billed - effective_cost if known else None
        exact = charge and charge.meter == item.meter and charge.unit == item.unit and number(charge.quantity) == number(quantity) and difference == 0 and charge.currency == item.currency
        db.add(VendorStatementLine(tenant_id=actor.tenant_id, statement_id=row.id, reference=item.reference,
            charge_id=item.charge_id, meter=item.meter, quantity=quantity, unit=item.unit, currency=item.currency,
            billed_amount=canonical(item.billed_amount), fx_toman_per_currency=canonical(fx), billed_micro_toman=billed,
            discrepancy_micro_toman=difference, status="MATCHED" if exact else "DISCREPANCY" if charge else "UNMATCHED"))
    db.flush()
    audit(db, actor.tenant_id, actor.id, "cost.statement_imported", "vendor_statement", row.id, evidence_sha256=row.evidence_sha256, line_count=len(data.lines))
    db.commit()
    return statement_dict(db, row)


@router.get("/costs/statements")
def statements(actor: Actor = Depends(require_permissions("billing:read")), db: Session = Depends(get_db)):
    return [statement_dict(db, row) for row in db.scalars(select(VendorStatement).where(VendorStatement.tenant_id == actor.tenant_id).order_by(VendorStatement.created_at.desc()).limit(40))]


class ReconcileInput(StrictModel):
    action: Literal["DISPUTE", "ACCEPT_VENDOR", "RESOLVE_NO_CHANGE"]
    evidence_reference: str = Field(pattern=IDENTIFIER)
    explanation: str = Field(min_length=10, max_length=1000)


@router.post("/costs/statement-lines/{line_id}/review")
def review_line(line_id: str, data: ReconcileInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    line = db.get(VendorStatementLine, line_id)
    if not line or line.tenant_id != actor.tenant_id:
        fail(404, "STATEMENT_LINE_NOT_FOUND", "Statement line is not available.")
    if line.status in {"ACCEPTED_VENDOR", "RESOLVED_NO_CHANGE", "MATCHED"}:
        fail(409, "STATEMENT_LINE_CLOSED", "This line is already reconciled.")
    if data.action == "ACCEPT_VENDOR":
        statement = db.get(VendorStatement, line.statement_id)
        original = db.get(UsageCharge, line.charge_id) if line.charge_id else None
        adjustment = line.discrepancy_micro_toman if line.discrepancy_micro_toman is not None else line.billed_micro_toman
        db.add(UsageCharge(tenant_id=actor.tenant_id, adjusts_charge_id=line.charge_id, call_id=original.call_id if original else None,
            provider=statement.provider, meter=line.meter, quantity="0" if original else line.quantity, unit=line.unit, currency=line.currency,
            rate_version=original.rate_version if original else None, cost_micro_toman=adjustment,
            source_key=digest({"statement_line": line.id}), source_reference=data.evidence_reference,
            evidence={"basis": "operator_accepted_vendor_statement", "statement_line_id": line.id}, occurred_at=month_bounds(statement.period)[0]))
        line.status = "ACCEPTED_VENDOR"
    elif data.action == "DISPUTE":
        line.status = "DISPUTED"
    else:
        line.status = "RESOLVED_NO_CHANGE"
    line.resolution_encrypted = encrypt(json.dumps(data.model_dump()))
    line.resolved_by, line.resolved_at = actor.id, now_utc()
    audit(db, actor.tenant_id, actor.id, "cost.statement_reviewed", "vendor_statement_line", line.id, decision=data.action, evidence_reference=data.evidence_reference)
    db.commit()
    return {"id": line.id, "status": line.status}


class TransportInput(StrictModel):
    source: str = Field(pattern=IDENTIFIER, max_length=80)
    event_key: str = Field(pattern=IDENTIFIER)
    attempt_key: str = Field(pattern=IDENTIFIER)
    call_id: str | None = None
    stage: Literal["ATTEMPTED", "CONNECTED", "ANSWERED", "ELIGIBLE", "RESOLVED", "BUSY", "REJECTED", "ABANDONED"]
    occurred_at: datetime
    evidence_reference: str = Field(pattern=IDENTIFIER)


def record_transport(db, tenant_id: str, data: TransportInput):
    if data.occurred_at.tzinfo is None or data.occurred_at > now_utc() + timedelta(minutes=5):
        fail(422, "INVALID_TRANSPORT_TIME", "Supply a valid timezone-aware transport timestamp.")
    if data.call_id:
        from .models_voice import CallSession
        call = db.get(CallSession, data.call_id)
        if not call or call.tenant_id != tenant_id:
            fail(404, "CALL_NOT_FOUND", "Call is not available in this clinic.")
    lock_tenant(db, tenant_id)
    request_hash = digest(data.model_dump())
    existing = db.scalar(select(TransportEvent).where(TransportEvent.tenant_id == tenant_id, TransportEvent.source == data.source, TransportEvent.event_key == data.event_key))
    if existing:
        if existing.request_hash != request_hash:
            fail(409, "TRANSPORT_EVENT_CONFLICT", "An event identifier cannot change its meaning.")
        return existing
    row = TransportEvent(tenant_id=tenant_id, request_hash=request_hash, **data.model_dump())
    db.add(row)
    db.flush()
    return row


@router.post("/costs/transport-events")
def ingest_transport(data: TransportInput, actor: Actor = Depends(require_permissions("integration:write")), db: Session = Depends(get_db)):
    row = record_transport(db, actor.tenant_id, data)
    audit(db, actor.tenant_id, actor.id, "transport.event_recorded", "transport_event", row.id, source=data.source)
    db.commit()
    return {"id": row.id, "stage": row.stage, "provenance": "authenticated_operator_or_adapter"}


@router.get("/costs/outcomes")
def outcomes(period: str | None = None, actor: Actor = Depends(require_permissions("reports:read")), db: Session = Depends(get_db)):
    start, end = month_bounds(period)
    rows = list(db.scalars(select(TransportEvent).where(TransportEvent.tenant_id == actor.tenant_id, TransportEvent.occurred_at >= start, TransportEvent.occurred_at < end)))
    stages = {stage: len({(r.source, r.attempt_key) for r in rows if r.stage == stage}) for stage in ("ATTEMPTED", "CONNECTED", "ANSWERED", "ELIGIBLE", "RESOLVED", "BUSY", "REJECTED", "ABANDONED")}
    appointments = list(db.scalars(select(Appointment).where(Appointment.tenant_id == actor.tenant_id, Appointment.created_at >= start, Appointment.created_at < end)))
    return {"period": start.strftime("%Y-%m"), "transport": stages if rows else None,
        "transport_coverage": "reported_events_only" if rows else "not_reported", "confirmed_or_kept": sum(a.status in {"CONFIRMED", "ATTENDED"} for a in appointments),
        "kept": sum(a.status == "ATTENDED" for a in appointments), "booking_cohort": "created_in_UTC_month",
        "definition": "Carrier attempts require authenticated ingress evidence. Application sessions alone do not establish answer rate."}


class AttributionInput(StrictModel):
    appointment_id: str
    episode_reference: str = Field(pattern=IDENTIFIER)
    channel: Literal["ai", "staff", "waitlist", "web", "partner"]
    classification: Literal["NEW_DEMAND", "REPLACEMENT", "MOVED_EXISTING", "DUPLICATE_INQUIRY", "DISPLACED_OTHER_CHANNEL", "UNASSESSED"]
    related_appointment_id: str | None = None
    evidence_reference: str = Field(pattern=IDENTIFIER)


@router.post("/costs/attribution")
def attribute(data: AttributionInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    appointment = db.get(Appointment, data.appointment_id)
    related = db.get(Appointment, data.related_appointment_id) if data.related_appointment_id else None
    if not appointment or appointment.tenant_id != actor.tenant_id or data.related_appointment_id and (not related or related.tenant_id != actor.tenant_id):
        fail(404, "APPOINTMENT_NOT_FOUND", "The appointment is not in this clinic.")
    if data.related_appointment_id == data.appointment_id:
        fail(422, "SELF_ATTRIBUTION", "A replacement cannot refer to itself.")
    if data.classification in {"REPLACEMENT", "MOVED_EXISTING", "DISPLACED_OTHER_CHANNEL"} and not related:
        fail(422, "RELATED_BOOKING_REQUIRED", "An existing booking must explain the displaced or moved demand.")
    from .models_ops import WaitlistOffer
    if data.classification == "NEW_DEMAND" and (data.channel == "waitlist" or db.scalar(select(WaitlistOffer.id).where(WaitlistOffer.tenant_id == actor.tenant_id, WaitlistOffer.appointment_id == appointment.id))):
        fail(422, "WAITLIST_IS_RECOVERY", "A waitlist fill must be reported as capacity recovery, not new demand.")
    episode = digest({"tenant": actor.tenant_id, "episode": data.episode_reference})
    old = db.scalar(select(DemandAttribution).where(DemandAttribution.tenant_id == actor.tenant_id, DemandAttribution.appointment_id == appointment.id))
    if old:
        if any(getattr(old, key) != value for key, value in {"episode_key": episode, "classification": data.classification, "channel": data.channel, "related_appointment_id": data.related_appointment_id, "evidence_reference": data.evidence_reference}.items()):
            fail(409, "ATTRIBUTION_ALREADY_REVIEWED", "An observed attribution cannot be silently overwritten.")
        return {"id": old.id, "classification": old.classification}
    row = DemandAttribution(tenant_id=actor.tenant_id, appointment_id=appointment.id, episode_key=episode,
        classification=data.classification, channel=data.channel, related_appointment_id=data.related_appointment_id,
        evidence_reference=data.evidence_reference, reviewed_by=actor.id)
    db.add(row)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "demand.attributed", "demand_attribution", row.id, classification=row.classification)
    db.commit()
    return {"id": row.id, "classification": row.classification}


@router.get("/costs/attribution")
def attribution_report(period: str | None = None, actor: Actor = Depends(require_permissions("reports:read")), db: Session = Depends(get_db)):
    start, end = month_bounds(period)
    appointments = {a.id: a for a in db.scalars(select(Appointment).where(Appointment.tenant_id == actor.tenant_id, Appointment.created_at >= start, Appointment.created_at < end))}
    rows = list(db.scalars(select(DemandAttribution).where(DemandAttribution.tenant_id == actor.tenant_id, DemandAttribution.appointment_id.in_(list(appointments))))) if appointments else []
    episodes = {row.episode_key for row in rows if row.classification == "NEW_DEMAND" and appointments[row.appointment_id].status == "ATTENDED"}
    counts = {name: sum(row.classification == name for row in rows) for name in ("NEW_DEMAND", "REPLACEMENT", "MOVED_EXISTING", "DUPLICATE_INQUIRY", "DISPLACED_OTHER_CHANNEL", "UNASSESSED")}
    return {"period": start.strftime("%Y-%m"), "classifications": counts, "unreviewed_bookings": len(appointments) - len(rows),
        "observed_new_demand_kept_episodes": len(episodes), "causal_incremental_kept": None,
        "definition": "Distinct reviewed demand episodes, not phones, are counted once. Observed attribution is not a causal estimate."}


class WorkStartInput(StrictModel):
    category: Literal["RECEPTION", "HANDOFF", "SUPERVISION", "REWORK"]
    task_id: str | None = None
    hourly_rate_toman: int = Field(ge=0, le=10_000_000)
    idempotency_key: str = Field(pattern=IDENTIFIER)


@router.post("/staff-time/start")
def start_work(data: WorkStartInput, actor: Actor = Depends(require_permissions("task:write")), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    if data.task_id:
        task = db.get(StaffTask, data.task_id)
        if not task or task.tenant_id != actor.tenant_id:
            fail(404, "TASK_NOT_FOUND", "Task is not available.")
    old = db.scalar(select(StaffWorkSession).where(StaffWorkSession.tenant_id == actor.tenant_id, StaffWorkSession.idempotency_key == data.idempotency_key))
    if old:
        if (old.user_id, old.category, old.task_id, old.rate_micro_toman_per_hour) != (actor.id, data.category, data.task_id, data.hourly_rate_toman * MICRO):
            fail(409, "WORK_SESSION_CONFLICT", "This work identifier already has different details.")
        return {"id": old.id, "started_at": old.started_at, "ended_at": old.ended_at}
    # Shared staff cannot charge concurrent time in another clinic either.
    from .models import User
    db.execute(update(User).where(User.id == actor.id).values(token_version=User.token_version))
    if db.scalar(select(StaffWorkSession.id).where(StaffWorkSession.user_id == actor.id, StaffWorkSession.ended_at.is_(None))):
        fail(409, "WORK_SESSION_ACTIVE", "Stop the existing work session before starting another.")
    row = StaffWorkSession(tenant_id=actor.tenant_id, user_id=actor.id, category=data.category, task_id=data.task_id,
        idempotency_key=data.idempotency_key, rate_micro_toman_per_hour=data.hourly_rate_toman * MICRO, started_at=now_utc())
    db.add(row)
    db.commit()
    return {"id": row.id, "started_at": row.started_at, "ended_at": None}


@router.post("/staff-time/{session_id}/stop")
def stop_work(session_id: str, actor: Actor = Depends(require_permissions("task:write")), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    row = db.get(StaffWorkSession, session_id)
    if not row or row.tenant_id != actor.tenant_id or row.user_id != actor.id:
        fail(404, "WORK_SESSION_NOT_FOUND", "Work session is not available for this user.")
    if not row.ended_at:
        elapsed = int((now_utc() - row.started_at).total_seconds())
        if elapsed > 16 * 3600:
            fail(409, "WORK_SESSION_REVIEW_REQUIRED", "A session longer than 16 hours needs documented correction; it is not automatically valued.")
        row.ended_at, row.seconds = now_utc(), max(0, elapsed)
        row.cost_micro_toman = int((Decimal(row.seconds) * row.rate_micro_toman_per_hour / 3600).to_integral_value(rounding=ROUND_CEILING))
    db.commit()
    return {"id": row.id, "seconds": row.seconds, "cost_micro_toman": row.cost_micro_toman, "basis": "observed_timer_at_declared_rate"}


class WorkReviewInput(StrictModel):
    reviewed_seconds: int = Field(ge=0, le=57600)
    evidence_reference: str = Field(pattern=IDENTIFIER)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    observation_verified: bool


@router.post("/staff-time/{session_id}/review")
def review_work(session_id: str, data: WorkReviewInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    if not data.observation_verified:
        fail(422, "WORK_REVIEW_EVIDENCE_REQUIRED", "Correct an abandoned timer only after verifying its actual work interval.")
    lock_tenant(db, actor.tenant_id)
    row = db.get(StaffWorkSession, session_id)
    if not row or row.tenant_id != actor.tenant_id:
        fail(404, "WORK_SESSION_NOT_FOUND", "Work session is not available in this clinic.")
    if row.ended_at or (now_utc() - row.started_at).total_seconds() <= 16 * 3600:
        fail(409, "WORK_SESSION_REVIEW_NOT_REQUIRED", "Only an unfinished timer older than 16 hours can use documented correction.")
    elapsed = int((now_utc() - row.started_at).total_seconds())
    row.ended_at, row.seconds = now_utc(), data.reviewed_seconds
    row.cost_micro_toman = int((Decimal(row.seconds) * row.rate_micro_toman_per_hour / 3600).to_integral_value(rounding=ROUND_CEILING))
    audit(db, actor.tenant_id, actor.id, "staff.timer_reviewed", "staff_work_session", row.id,
        observed_wall_seconds=elapsed, reviewed_seconds=row.seconds, evidence_reference=data.evidence_reference,
        evidence_sha256=data.evidence_sha256, basis="operator_attested_abandoned_timer_correction")
    db.commit()
    return {"id": row.id, "seconds": row.seconds, "cost_micro_toman": row.cost_micro_toman,
        "cost_toman_exact": exact_toman(row.cost_micro_toman), "basis": "operator_attested_abandoned_timer_correction"}


class TimeObservationInput(StrictModel):
    period: str
    released_minutes: int = Field(ge=0, le=1_000_000)
    avoidable_minutes: int = Field(ge=0, le=1_000_000)
    reassigned_minutes: int = Field(ge=0, le=1_000_000)
    hourly_rate_toman: int = Field(ge=0, le=10_000_000)
    evidence_reference: str = Field(pattern=IDENTIFIER)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_allocation(self):
        if self.avoidable_minutes + self.reassigned_minutes > self.released_minutes:
            raise ValueError("Avoidable plus reassigned minutes cannot exceed released minutes")
        return self


@router.post("/staff-time/observations")
def record_time_observation(data: TimeObservationInput, actor: Actor = Depends(require_permissions("billing:write")), db: Session = Depends(get_db)):
    month_bounds(data.period)
    lock_tenant(db, actor.tenant_id)
    old = db.scalar(select(StaffTimeObservation).where(StaffTimeObservation.tenant_id == actor.tenant_id, StaffTimeObservation.period == data.period, StaffTimeObservation.evidence_reference == data.evidence_reference))
    if old:
        values = {**data.model_dump(exclude={"hourly_rate_toman"}), "rate_micro_toman_per_hour": data.hourly_rate_toman * MICRO}
        if any(getattr(old, key) != value for key, value in values.items()):
            fail(409, "TIME_OBSERVATION_CONFLICT", "This observation already has different evidence.")
        return {"id": old.id}
    row = StaffTimeObservation(tenant_id=actor.tenant_id, reviewed_by=actor.id, rate_micro_toman_per_hour=data.hourly_rate_toman * MICRO,
        **data.model_dump(exclude={"hourly_rate_toman"}))
    db.add(row)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "staff.time_observed", "staff_time_observation", row.id, evidence_sha256=data.evidence_sha256)
    db.commit()
    return {"id": row.id, "basis": "operator_attested_observation"}


@router.get("/staff-time")
def time_report(period: str | None = None, actor: Actor = Depends(require_permissions("reports:read")), db: Session = Depends(get_db)):
    start, end = month_bounds(period)
    period = start.strftime("%Y-%m")
    work = list(db.scalars(select(StaffWorkSession).where(StaffWorkSession.tenant_id == actor.tenant_id, StaffWorkSession.started_at >= start, StaffWorkSession.started_at < end)))
    observations = list(db.scalars(select(StaffTimeObservation).where(StaffTimeObservation.tenant_id == actor.tenant_id, StaffTimeObservation.period == period)))
    extra = sum(r.cost_micro_toman or 0 for r in work if r.category in {"SUPERVISION", "REWORK"})
    avoidable = sum(int(Decimal(r.avoidable_minutes) * r.rate_micro_toman_per_hour / 60) for r in observations)
    return {"period": period, "seconds_by_category": {c: sum(r.seconds or 0 for r in work if r.category == c) for c in ("RECEPTION", "HANDOFF", "SUPERVISION", "REWORK")},
        "incomplete_sessions": sum(r.ended_at is None for r in work), "released_minutes": sum(r.released_minutes for r in observations),
        "review_required_sessions": [{"id": r.id, "user_id": r.user_id, "category": r.category, "started_at": r.started_at}
            for r in db.scalars(select(StaffWorkSession).where(StaffWorkSession.tenant_id == actor.tenant_id,
                StaffWorkSession.ended_at.is_(None), StaffWorkSession.started_at < now_utc() - timedelta(hours=16)).limit(100))],
        "avoidable_minutes": sum(r.avoidable_minutes for r in observations), "reassigned_minutes": sum(r.reassigned_minutes for r in observations),
        "avoidable_value_micro_toman": avoidable if observations else None, "supervision_rework_micro_toman": extra,
        "net_avoidable_value_micro_toman": avoidable - extra if observations else None,
        "basis": "attested_release_minus_observed_supervision_rework", "coverage_complete": False}
