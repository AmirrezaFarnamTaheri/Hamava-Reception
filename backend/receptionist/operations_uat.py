"""Clinic-specific synthetic UAT attestation and production publication gates.

The application checks identity, completeness, expiry and configuration binding.
It does not certify that an operator's evidence proves a live carrier or clinical
qualification. Attestations are immutable audit facts, not inferred test results.
"""

from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import Field, StrictBool
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .core import iso, request_digest
from .db import get_db, now_utc
from .models import AuditEvent, Membership, Practitioner, Service, Tenant, User
from .operations import audit, lock_tenant
from .operations_extensions import POLICY_FIELDS
from .schemas import StrictModel
from .security import Actor, fail, require_roles

router = APIRouter(prefix="/api/v1")
admin = require_roles("owner", "admin")
ActiveMode = Literal["after_hours", "overflow", "human_primary", "supervised", "ai_primary"]
REQUIRED_CHECKS = ("booking", "cancellation", "conflict", "provider_failure", "handoff")


def enforced() -> bool:
    return settings.environment.lower() in {"production", "prod"}


def configuration_fingerprint(db: Session, tenant: Tenant, target_mode: str, overrides: dict | None = None) -> str:
    from .core_policy import configuration_snapshot
    policy = {key: getattr(tenant, key) for key in POLICY_FIELDS}
    policy.update({key: value for key, value in (overrides or {}).items() if key in POLICY_FIELDS})
    policy["mode"] = target_mode
    catalog = {
        "practitioners": [
            {"id": row.id, "name": row.name, "specialty": row.specialty, "working_hours": row.working_hours, "active": row.active}
            for row in db.scalars(select(Practitioner).where(Practitioner.tenant_id == tenant.id).order_by(Practitioner.id))
        ],
        "services": [
            {
                "id": row.id,
                "name": row.name,
                "description": row.description,
                "provider_ids": sorted(row.provider_ids),
                "resource_ids": sorted(row.resource_ids),
                "duration_minutes": row.duration_minutes,
                "buffer_minutes": row.buffer_minutes,
                "price_toman": row.price_toman,
                "deposit_toman": row.deposit_toman,
                "requires_approval": row.requires_approval,
                "active": row.active,
            }
            for row in db.scalars(select(Service).where(Service.tenant_id == tenant.id).order_by(Service.id))
        ],
    }
    payment_publication = db.scalar(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == tenant.id, AuditEvent.action == "payment.policy_published")
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    return request_digest(
        {
            "schema": 1,
            "tenant_id": tenant.id,
            "timezone": tenant.timezone,
            "slug": tenant.slug,
            "policy": policy,
            "catalog": catalog,
            "core_extensions": configuration_snapshot(db, tenant.id),
            "payment_publication": payment_publication.id if payment_publication else None,
        }
    )


def matching_attestation(db: Session, tenant_id: str, fingerprint: str, target_mode: str) -> AuditEvent | None:
    rows = db.scalars(
        select(AuditEvent)
        .where(
            AuditEvent.tenant_id == tenant_id,
            AuditEvent.action == "clinic.uat_attested",
            AuditEvent.details["configuration_fingerprint"].as_string() == fingerprint,
            AuditEvent.details["target_mode"].as_string() == target_mode,
        )
        .order_by(AuditEvent.created_at.desc())
    )
    for row in rows:
        try:
            valid_until = datetime.fromisoformat(row.details["valid_until"].replace("Z", "+00:00"))
        except (ValueError, TypeError, KeyError):
            continue
        if valid_until.tzinfo is None or valid_until <= now_utc():
            continue
        if not all(row.details.get("checks", {}).get(check) is True for check in REQUIRED_CHECKS):
            continue
        reviewer = db.scalar(
            select(Membership.id)
            .join(User, User.id == Membership.user_id)
            .where(
                Membership.tenant_id == tenant_id,
                Membership.user_id == row.actor_id,
                Membership.active.is_(True),
                Membership.role.in_(["owner", "admin"]),
                User.active.is_(True),
            )
        )
        if reviewer is not None:
            return row
    return None


def require_matching_uat(db: Session, tenant: Tenant, target_mode: str, overrides: dict | None = None) -> None:
    if not enforced() or target_mode == "paused":
        return
    fingerprint = configuration_fingerprint(db, tenant, target_mode, overrides)
    if matching_attestation(db, tenant.id, fingerprint, target_mode) is None:
        fail(
            409,
            "CLINIC_UAT_REQUIRED",
            "فعال‌سازی این نسخه به تایید آزمون‌های مصنوعی همین مرکز نیاز دارد؛ ابتدا مکث، تنظیم و ثبت شواهد آزمون انجام شود.",
        )


def require_current_uat(db: Session, tenant: Tenant) -> None:
    """Fail closed on drift before AI admission/continuation in production."""
    require_matching_uat(db, tenant, tenant.mode)


def require_catalog_edit_safe(db: Session, tenant_id: str) -> None:
    lock_tenant(db, tenant_id)
    tenant = db.get(Tenant, tenant_id, populate_existing=True)
    if enforced() and tenant.mode != "paused":
        fail(
            409,
            "PAUSE_BEFORE_CATALOG_CHANGE",
            "برای تغییر فهرست خدمات یا پزشکان در محیط عملیاتی ابتدا پذیرش خودکار را مکث کنید؛ پس از تغییر آزمون مرکز لازم است.",
        )


def uat_review(db: Session, tenant: Tenant, target_mode: str) -> dict:
    fingerprint = configuration_fingerprint(db, tenant, target_mode)
    row = matching_attestation(db, tenant.id, fingerprint, target_mode)
    reviewer = db.get(User, row.actor_id) if row else None
    return {
        "current_mode": tenant.mode,
        "target_mode": target_mode,
        "configuration_fingerprint": fingerprint,
        "approved": row is not None,
        "production_enforced": enforced(),
        "required_checks": list(REQUIRED_CHECKS),
        "verification_kind": "clinic_synthetic_checks_attested",
        "attestation": {
            "id": row.id,
            "created_at": iso(row.created_at),
            "valid_until": row.details["valid_until"],
            "reviewer_user_id": row.actor_id,
            "reviewer_name": reviewer.name if reviewer else None,
            "checks": row.details["checks"],
            "evidence_refs": row.details["evidence_refs"],
        }
        if row
        else None,
        "scope": "Named operator attestation for this clinic configuration and mode. Live carrier, clinical, legal and provider approval remain separate gates.",
    }


@router.get("/operations/uat")
def get_uat(target_mode: ActiveMode = Query(default="after_hours"), actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    tenant = db.get(Tenant, actor.tenant_id)
    return uat_review(db, tenant, target_mode)


class UATChecks(StrictModel):
    booking: StrictBool
    cancellation: StrictBool
    conflict: StrictBool
    provider_failure: StrictBool
    handoff: StrictBool


class UATApproval(StrictModel):
    target_mode: ActiveMode
    configuration_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: UATChecks
    evidence_refs: dict[str, str]
    confirmed: StrictBool


@router.post("/operations/uat/approve")
def approve_uat(data: UATApproval, actor: Actor = Depends(admin), db: Session = Depends(get_db)):
    if data.confirmed is not True or not all(data.checks.model_dump().values()):
        fail(422, "UAT_CHECKS_INCOMPLETE", "هر پنج آزمون باید با شواهد مستقل توسط مسئول مرکز تایید شده باشد.")
    if set(data.evidence_refs) != set(REQUIRED_CHECKS) or any(not 3 <= len(value.strip()) <= 300 for value in data.evidence_refs.values()):
        fail(422, "UAT_EVIDENCE_REQUIRED", "برای هر آزمون شناسه یا نشانی مدرک مشخص بدون اطلاعات بیمار ثبت کنید.")
    lock_tenant(db, actor.tenant_id)
    tenant = db.get(Tenant, actor.tenant_id, populate_existing=True)
    fingerprint = configuration_fingerprint(db, tenant, data.target_mode)
    if fingerprint != data.configuration_fingerprint:
        fail(409, "STALE_UAT_CONFIGURATION", "تنظیمات یا فهرست خدمات پس از بازبینی تغییر کرده است؛ آزمون نسخه جاری لازم است.")
    if matching_attestation(db, actor.tenant_id, fingerprint, data.target_mode) is None:
        audit(
            db,
            actor.tenant_id,
            actor.id,
            "clinic.uat_attested",
            "tenant",
            tenant.id,
            configuration_fingerprint=fingerprint,
            target_mode=data.target_mode,
            checks=data.checks.model_dump(),
            evidence_refs={key: value.strip() for key, value in data.evidence_refs.items()},
            verification_kind="clinic_synthetic_checks_attested",
            valid_until=iso(now_utc() + timedelta(days=30)),
        )
        db.commit()
    return uat_review(db, tenant, data.target_mode)
