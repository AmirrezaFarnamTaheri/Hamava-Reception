"""Versioned inbound routing and explicitly approved human-language scripts."""
import os
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .core_policy import lock, revise
from .db import get_db, now_utc
from .models_core import RoutingBinding, RoutingRevision
from .schemas import StrictModel
from .security import Actor, encrypt, fail, require_permissions

router = APIRouter(prefix="/api/v1")


def target_allowlist():
    return {value.strip() for value in os.getenv("HUMAN_TRANSFER_TARGETS", "").split(",") if value.strip()}


class Route(StrictModel):
    did: str = Field(pattern=r"^\+?[0-9]{3,20}$")
    provider: Literal["audiosocket", "livekit"]
    queue_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    transfer_target: str = Field(pattern=r"^[A-Za-z0-9_@.:+/-]{1,120}$")


class LanguageRoute(StrictModel):
    enabled: bool = False
    script: str = Field(min_length=10, max_length=1000)
    queue_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,80}$")
    qualified_staff_attested: bool = False
    source: str = Field(min_length=3, max_length=500)
    effective_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def period(self):
        if self.effective_at.tzinfo is None or self.expires_at.tzinfo is None or self.expires_at <= self.effective_at or self.expires_at <= now_utc():
            raise ValueError("A future, timezone-aware approval interval is required")
        if self.enabled and not self.qualified_staff_attested:
            raise ValueError("Enabled human language routing requires an explicit staff qualification attestation")
        return self


class RoutingInput(StrictModel):
    version: int = Field(ge=0)
    routes: list[Route] = Field(default_factory=list, max_length=40)
    language_routes: dict[Literal["english", "arabic"], LanguageRoute] = Field(default_factory=dict)
    reason: str = Field(min_length=3, max_length=500)


def current(db, tenant_id):
    return db.scalar(select(RoutingRevision).where(RoutingRevision.tenant_id == tenant_id).order_by(RoutingRevision.version.desc()).limit(1))


def snapshot(db, tenant_id):
    row = current(db, tenant_id)
    return {"version": row.version if row else 0, "routes": row.routes if row else [],
            "language_routes": row.language_routes if row else {}, "approved_by": row.approved_by if row else None}


@router.get("/routing")
def get_routing(actor: Actor = Depends(require_permissions("integration:read")), db: Session = Depends(get_db)):
    return {**snapshot(db, actor.tenant_id), "allowed_transfer_targets": sorted(target_allowlist())}


@router.put("/routing")
def publish(body: RoutingInput, actor: Actor = Depends(require_permissions("routing:write")), db: Session = Depends(get_db)):
    tenant = lock(db, actor.tenant_id)
    if tenant.mode != "paused":
        fail(409, "PAUSE_REQUIRED", "پیش از تغییر مسیر تماس، پذیرش خودکار را متوقف کنید.")
    old = current(db, actor.tenant_id)
    if body.version != (old.version if old else 0):
        fail(409, "VERSION_CONFLICT", "مسیر تماس تغییر کرده است.")
    if len({route.did for route in body.routes}) != len(body.routes):
        fail(422, "DUPLICATE_DID", "هر شماره ورودی باید فقط یک مسیر داشته باشد.")
    if any(route.transfer_target not in target_allowlist() for route in body.routes):
        fail(422, "TRANSFER_TARGET_NOT_APPROVED", "مقصد انتقال باید در فهرست مجاز استقرار باشد.")
    queues = {route.queue_id for route in body.routes}
    if any(value.enabled and value.queue_id not in queues for value in body.language_routes.values()):
        fail(422, "LANGUAGE_QUEUE_NOT_FOUND", "صف زبان باید در مسیرهای همین مرکز تعریف شود.")
    row = RoutingRevision(tenant_id=actor.tenant_id, version=body.version + 1,
        routes=[route.model_dump() for route in body.routes], language_routes={key: value.model_dump(mode="json") for key,value in body.language_routes.items()},
        approved_by=actor.id, reason_encrypted=encrypt(body.reason))
    db.add(row)
    db.flush()
    db.execute(delete(RoutingBinding).where(RoutingBinding.tenant_id == actor.tenant_id))
    for route in body.routes:
        db.add(RoutingBinding(tenant_id=actor.tenant_id, revision_id=row.id, **route.model_dump()))
    try:
        # revise() issues a query and can autoflush the globally unique DID
        # bindings. Its conflict is part of the same atomic publication.
        revise(db, actor, "routing.published", "routing", row.id, body.reason, version=row.version)
        db.commit()
    except IntegrityError:
        db.rollback()
        fail(409, "DID_ALREADY_ASSIGNED", "شماره ورودی در مسیر مرکز دیگری ثبت شده است.")
    return {**snapshot(db, actor.tenant_id), "allowed_transfer_targets": sorted(target_allowlist())}


def resolve_did(db, did, provider="audiosocket"):
    row = db.get(RoutingBinding, did)
    if row and row.provider == provider and row.transfer_target in target_allowlist():
        return {"tenant_id": row.tenant_id, "queue_id": row.queue_id, "transfer_target": row.transfer_target, "revision_id": row.revision_id}
    return None


def language_route(snapshot_value, language):
    row = snapshot_value.get("language_routes", {}).get(language)
    if not row or not row.get("enabled") or not row.get("qualified_staff_attested"):
        return None
    try:
        start, end = datetime.fromisoformat(row["effective_at"]), datetime.fromisoformat(row["expires_at"])
        return row if start.tzinfo and end.tzinfo and start <= now_utc() < end else None
    except (ValueError, KeyError, TypeError):
        return None
