"""Approved, expiring catalog facts and tenant-specific administrative rules.

Evidence records state who approved a value and when; they never pretend that an
operator declaration is independent clinical or legal verification.
"""
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, now_utc
from .models import AuditEvent, Practitioner, Service, Tenant
from .models_core import CatalogFact, CorePolicy, ServiceRule, RoutingRevision, CalendarAuthority
from .schemas import StrictModel
from .security import Actor, encrypt, fail, require_permissions

router = APIRouter(prefix="/api/v1")
DEFAULT_WINDOWS = {"صبح": [6, 12], "ظهر": [12, 15], "بعدازظهر": [12, 19], "عصر": [15, 21], "غروب": [17, 21], "شب": [18, 24]}
FACT_FIELDS = {
    "tenant": ("name", "address", "phone", "website", "working_hours", "holidays", "lead_time_minutes", "booking_horizon_days", "cancellation_notice_hours"),
    "practitioner": ("name", "specialty", "working_hours", "active"),
    "service": ("name", "description", "provider_ids", "resource_ids", "duration_minutes", "buffer_minutes", "price_toman", "deposit_toman", "requires_approval", "active"),
    "service_rule": ("preparation", "insurance_notes", "visit_policy", "prerequisite_service_id", "follow_up_days", "package_units", "max_series"),
}


def production():
    return settings.environment.lower() in {"prod", "production"}


def lock(db, tenant_id):
    changed = db.execute(update(Tenant).where(Tenant.id == tenant_id, Tenant.active.is_(True)).values(settings_version=Tenant.settings_version))
    if not changed.rowcount:
        fail(404, "TENANT_NOT_FOUND", "مرکز پیدا نشد.")
    return db.scalar(select(Tenant).where(Tenant.id == tenant_id).execution_options(populate_existing=True))


def revise(db, actor, action, entity_type, entity_id, reason, **details):
    tenant = lock(db, actor.tenant_id)
    tenant.settings_version += 1
    db.add(AuditEvent(tenant_id=actor.tenant_id, actor_id=actor.id, action=action, entity_type=entity_type,
                      entity_id=entity_id, details={"reason_encrypted": encrypt(reason), "settings_version": tenant.settings_version, **details}))


def policy(db, tenant_id):
    row = db.get(CorePolicy, tenant_id)
    return {"version": row.version if row else 0, "time_windows": (row.settings if row else {}).get("time_windows", DEFAULT_WINDOWS),
            "catalog_provenance_required": production() or bool((row.settings if row else {}).get("catalog_provenance_required", False))}


class PolicyInput(StrictModel):
    version: int = Field(ge=0)
    time_windows: dict[str, list[float]] = Field(default_factory=lambda: dict(DEFAULT_WINDOWS), max_length=10)
    catalog_provenance_required: bool = True
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("time_windows")
    @classmethod
    def windows(cls, value):
        if set(value) != set(DEFAULT_WINDOWS):
            raise ValueError("Define every supported Persian time period")
        for bounds in value.values():
            if len(bounds) != 2 or not 0 <= bounds[0] < bounds[1] <= 24 or any(v * 4 != int(v * 4) for v in bounds):
                raise ValueError("Time windows must be increasing quarter-hour boundaries within 0..24")
        return value


@router.get("/core-policy")
def get_policy(actor: Actor = Depends(require_permissions("policy:read")), db: Session = Depends(get_db)):
    return policy(db, actor.tenant_id)


@router.put("/core-policy")
def put_policy(body: PolicyInput, actor: Actor = Depends(require_permissions("policy:write")), db: Session = Depends(get_db)):
    from .operations_uat import require_catalog_edit_safe
    require_catalog_edit_safe(db, actor.tenant_id)
    lock(db, actor.tenant_id)
    row = db.get(CorePolicy, actor.tenant_id)
    if body.version != (row.version if row else 0):
        fail(409, "VERSION_CONFLICT", "تنظیمات تغییر کرده است؛ دوباره بخوانید.")
    if production() and not body.catalog_provenance_required:
        fail(422, "PROVENANCE_REQUIRED", "در محیط عملیاتی، تایید و اعتبار داده‌ها الزامی است.")
    if not row:
        row = CorePolicy(tenant_id=actor.tenant_id, version=0, approved_by=actor.id)
        db.add(row)
    row.version += 1
    row.approved_by = actor.id
    row.settings = body.model_dump(exclude={"version", "reason"})
    revise(db, actor, "core.policy_published", "tenant", actor.tenant_id, body.reason, version=row.version)
    db.commit()
    return policy(db, actor.tenant_id)


def subject(db, tenant_id, subject_type, subject_id):
    table = {"tenant": Tenant, "practitioner": Practitioner, "service": Service, "service_rule": ServiceRule}.get(subject_type)
    row = db.get(table, subject_id) if table else None
    if not row or (row.id if subject_type == "tenant" else row.tenant_id) != tenant_id:
        fail(404, "CATALOG_SUBJECT_NOT_FOUND", "داده متعلق به این مرکز پیدا نشد.")
    return row


def publish_facts(db, tenant_id, subject_type, row, actor_id, *, source="Clinic operator declaration", effective_at=None, expires_at=None, fields=None):
    """Flush-only; callers serialize under the tenant row and commit with catalog mutation."""
    from .core import request_digest
    now = now_utc()
    effective_at = effective_at or now
    expires_at = expires_at or now + timedelta(days=365)
    if effective_at.tzinfo is None or expires_at.tzinfo is None or expires_at <= effective_at or expires_at <= now:
        fail(422, "INVALID_FACT_VALIDITY", "بازه اعتبار تایید داده درست نیست.")
    selected = fields or FACT_FIELDS[subject_type]
    if any(f not in FACT_FIELDS[subject_type] for f in selected):
        fail(422, "INVALID_CATALOG_FIELD", "فیلد قابل تایید نیست.")
    subject_id = row.service_id if subject_type == "service_rule" else row.id
    for field in selected:
        latest = db.scalar(select(CatalogFact.version).where(CatalogFact.tenant_id == tenant_id,
            CatalogFact.subject_type == subject_type, CatalogFact.subject_id == subject_id, CatalogFact.field == field)
            .order_by(CatalogFact.version.desc()).limit(1)) or 0
        value = {"value": getattr(row, field)}
        db.add(CatalogFact(tenant_id=tenant_id, subject_type=subject_type, subject_id=subject_id, field=field,
            version=latest + 1, value=value, value_hash=request_digest(value), source=source, approved_by=actor_id,
            effective_at=effective_at, expires_at=expires_at))
    db.flush()


def fact_dict(row):
    return {"id": row.id, "subject_type": row.subject_type, "subject_id": row.subject_id, "field": row.field,
            "version": row.version, "value": row.value["value"], "source": row.source, "approved_by": row.approved_by,
            "effective_at": row.effective_at.isoformat(), "expires_at": row.expires_at.isoformat(),
            "current": row.effective_at <= now_utc() < row.expires_at}


def require_facts(db, tenant_id, subject_type, row, fields=None):
    if not policy(db, tenant_id)["catalog_provenance_required"]:
        return
    from .core import request_digest
    subject_id = row.service_id if subject_type == "service_rule" else row.id
    required = set(fields or FACT_FIELDS[subject_type])
    latest = {}
    for fact in db.scalars(select(CatalogFact).where(CatalogFact.tenant_id == tenant_id,
        CatalogFact.subject_type == subject_type, CatalogFact.subject_id == subject_id, CatalogFact.field.in_(required))
        .order_by(CatalogFact.version.desc())):
        latest.setdefault(fact.field, fact)
    now = now_utc()
    for field in required:
        fact = latest.get(field)
        if (not fact or not fact.source or not fact.approved_by or not fact.effective_at <= now < fact.expires_at
                or fact.value_hash != request_digest({"value": getattr(row, field)})):
            fail(409, "CATALOG_FACT_REVIEW_REQUIRED", "داده مرکز تایید معتبر ندارد؛ پذیرش باید آن را بررسی کند.")


class FactApproval(StrictModel):
    subject_type: Literal["tenant", "practitioner", "service", "service_rule"]
    subject_id: str = Field(min_length=1, max_length=60)
    fields: list[str] = Field(min_length=1, max_length=20)
    source: str = Field(min_length=3, max_length=500)
    effective_at: datetime
    expires_at: datetime
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def unique_fields(self):
        if len(self.fields) != len(set(self.fields)):
            raise ValueError("Fact fields must be unique")
        return self


@router.get("/catalog/facts")
def list_facts(subject_type: str | None = None, subject_id: str | None = None,
               actor: Actor = Depends(require_permissions("catalog:read")), db: Session = Depends(get_db)):
    query = select(CatalogFact).where(CatalogFact.tenant_id == actor.tenant_id)
    if subject_type:
        query = query.where(CatalogFact.subject_type == subject_type)
    if subject_id:
        query = query.where(CatalogFact.subject_id == subject_id)
    return [fact_dict(r) for r in db.scalars(query.order_by(CatalogFact.created_at.desc(), CatalogFact.version.desc()).limit(500))]


@router.post("/catalog/facts/approve")
def approve_facts(body: FactApproval, actor: Actor = Depends(require_permissions("catalog:write")), db: Session = Depends(get_db)):
    from .operations_uat import require_catalog_edit_safe
    require_catalog_edit_safe(db, actor.tenant_id)
    lock(db, actor.tenant_id)
    row = subject(db, actor.tenant_id, body.subject_type, body.subject_id)
    publish_facts(db, actor.tenant_id, body.subject_type, row, actor.id, source=body.source,
                  effective_at=body.effective_at, expires_at=body.expires_at, fields=body.fields)
    revise(db, actor, "catalog.facts_approved", body.subject_type, body.subject_id, body.reason, fields=body.fields)
    db.commit()
    return {"status": "APPROVED", "subject_id": body.subject_id}


class ServicePolicyInput(StrictModel):
    version: int = Field(ge=0)
    preparation: str = Field(default="", max_length=2000)
    insurance_notes: str = Field(default="", max_length=2000)
    visit_policy: Literal["any", "first_visit", "follow_up", "package"] = "any"
    prerequisite_service_id: str | None = Field(default=None, max_length=60)
    follow_up_days: int = Field(default=30, ge=1, le=730)
    package_units: int = Field(default=0, ge=0, le=100)
    max_series: int = Field(default=12, ge=1, le=12)
    source: str = Field(min_length=3, max_length=500)
    effective_at: datetime | None = None
    expires_at: datetime
    reason: str = Field(min_length=3, max_length=500)

    @model_validator(mode="after")
    def package_rules(self):
        if (self.visit_policy == "package") != (self.package_units > 0):
            raise ValueError("Package services require positive units; other visit policies must use zero units")
        return self


def service_policy(db, tenant_id, service_id, *, checked=False):
    row = db.get(ServiceRule, service_id)
    if row and row.tenant_id != tenant_id:
        fail(404, "SERVICE_NOT_FOUND", "خدمت پیدا نشد.")
    if row and checked:
        require_facts(db, tenant_id, "service_rule", row)
    return {"service_id": service_id, "version": row.version if row else 0,
        "preparation": row.preparation if row else "", "insurance_notes": row.insurance_notes if row else "",
        "visit_policy": row.visit_policy if row else "any", "prerequisite_service_id": row.prerequisite_service_id if row else None,
        "follow_up_days": row.follow_up_days if row else 30, "package_units": row.package_units if row else 0,
        "max_series": row.max_series if row else 12}


@router.get("/services/{service_id}/policy")
def get_service_policy(service_id: str, actor: Actor = Depends(require_permissions("catalog:read")), db: Session = Depends(get_db)):
    subject(db, actor.tenant_id, "service", service_id)
    return service_policy(db, actor.tenant_id, service_id)


@router.put("/services/{service_id}/policy")
def put_service_policy(service_id: str, body: ServicePolicyInput, actor: Actor = Depends(require_permissions("catalog:write")), db: Session = Depends(get_db)):
    from .operations_uat import require_catalog_edit_safe
    require_catalog_edit_safe(db, actor.tenant_id)
    lock(db, actor.tenant_id)
    subject(db, actor.tenant_id, "service", service_id)
    if body.prerequisite_service_id:
        subject(db, actor.tenant_id, "service", body.prerequisite_service_id)
    row = db.get(ServiceRule, service_id)
    if body.version != (row.version if row else 0):
        fail(409, "VERSION_CONFLICT", "سیاست خدمت تغییر کرده است.")
    if not row:
        row = ServiceRule(service_id=service_id, tenant_id=actor.tenant_id, version=0)
        db.add(row)
    for field in FACT_FIELDS["service_rule"]:
        setattr(row, field, getattr(body, field))
    row.version += 1
    db.flush()
    publish_facts(db, actor.tenant_id, "service_rule", row, actor.id, source=body.source,
                  effective_at=body.effective_at, expires_at=body.expires_at)
    revise(db, actor, "service.policy_published", "service", service_id, body.reason, version=row.version)
    db.commit()
    return service_policy(db, actor.tenant_id, service_id)


def configuration_snapshot(db, tenant_id):
    """Public, deterministic settings digest input for clinic UAT; contains no patient data."""
    facts = list(db.execute(select(CatalogFact.id, CatalogFact.value_hash, CatalogFact.expires_at)
                           .where(CatalogFact.tenant_id == tenant_id).order_by(CatalogFact.id)))
    route = db.scalar(select(RoutingRevision).where(RoutingRevision.tenant_id == tenant_id).order_by(RoutingRevision.version.desc()).limit(1))
    authority = db.get(CalendarAuthority, tenant_id)
    return {"core_policy": policy(db, tenant_id), "facts": [(r.id, r.value_hash, r.expires_at.isoformat()) for r in facts],
            "routing_version": route.version if route else 0,
            "calendar_authority": {"version": authority.version, "kind": authority.kind, "capabilities": authority.capabilities,
                "expires_at": authority.expires_at.isoformat()} if authority else None}
