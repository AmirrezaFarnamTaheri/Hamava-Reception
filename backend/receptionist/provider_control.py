"""Tenant-scoped provider approval, money reservation, observations and capability registry."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
import json
import os
import re
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from .config import settings
from .core_policy import lock, revise
from .db import get_db, now_utc
from .models import Tenant
from .models_core import IntegrationCapability, ProviderObservation, RoutingBinding
from .schemas import StrictModel
from .security import Actor, fail, require_permissions

router = APIRouter(prefix="/api/v1/operations")
PROVIDERS = {"speech_primary": ("SPEECH_PROCESSOR_APPROVED", "SPEECH_GATEWAY_URL", "SPEECH_GATEWAY_TOKEN", "SPEECH_PROCESSOR_REGION"),
             "speech_fallback": ("SPEECH_FALLBACK_APPROVED", "SPEECH_FALLBACK_URL", "SPEECH_FALLBACK_TOKEN", "SPEECH_FALLBACK_REGION"),
             "calendar_primary": ("CALENDAR_PARTNER_APPROVED", "CALENDAR_PARTNER_URL", "CALENDAR_TENANT_CREDENTIALS_JSON", "CALENDAR_PROCESSOR_REGION"),
             "telephony_primary": ("LIVEKIT_APPROVED", "LIVEKIT_URL", "LIVEKIT_API_KEY", "TELEPHONY_PROCESSOR_REGION"),
             "sms_kavenegar": ("SMS_PROVIDER_APPROVED", None, "KAVENEGAR_API_KEY", "SMS_PROCESSOR_REGION"),
             "payment_primary": ("PAYMENT_PROVIDER_APPROVED", None, "PAYMENT_TENANT_MERCHANTS_JSON", "PAYMENT_PROCESSOR_REGION"),
             "digest_gateway": ("DIGEST_PROCESSOR_APPROVED", "DIGEST_GATEWAY_URL", "DIGEST_GATEWAY_TOKEN", "DIGEST_PROCESSOR_REGION")}
OPERATIONS = {"speech": {"transcribe_final", "transcribe_partial", "keyterms", "synthesize_wav", "synthesize_stream"},
              "calendar": {"slots", "get", "hold", "release", "create", "cancel", "update", "reconcile", "changes", "webhook"},
              "telephony": {"start", "send_audio", "interrupt", "transfer", "hangup"},
              "sms": {"send", "delivery", "inbound"}, "payment": {"request", "verify", "refund_review"}, "digest": {"generate"}}
PROVIDER_KINDS = {"speech_primary": "speech", "speech_fallback": "speech", "calendar_primary": "calendar",
                  "telephony_primary": "telephony", "sms_kavenegar": "sms", "payment_primary": "payment", "digest_gateway": "digest"}


def configured_scopes(provider):
    variable = {"calendar_primary": "CALENDAR_TENANT_CREDENTIALS_JSON", "payment_primary": "PAYMENT_TENANT_MERCHANTS_JSON"}.get(provider)
    if not variable:
        return None
    try:
        value = json.loads(os.getenv(variable, "{}"))
        return set(value) if isinstance(value, dict) else set()
    except ValueError:
        return set()


def configuration_condition(provider):
    """SQL tenant predicate for actual configured credentials and routing."""
    from .providers import enabled
    gate, _, credential, _ = PROVIDERS[provider]
    if provider == "telephony_primary":
        if enabled(gate) and all(os.getenv(key) for key in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "MEDIA_API_TOKEN")):
            return True
        if not os.getenv("MEDIA_API_TOKEN"):
            return False
        try:
            routes = json.loads(os.getenv("MEDIA_DID_TENANTS_JSON", "{}"))
            slugs = list(routes.values()) if isinstance(routes, dict) else []
        except ValueError:
            slugs = []
        return or_(Tenant.id.in_(select(RoutingBinding.tenant_id)), Tenant.slug.in_(slugs))
    if not enabled(gate) or not os.getenv(credential):
        return False
    scopes = configured_scopes(provider)
    return True if scopes is None else Tenant.id.in_(scopes)


def observation(db, tenant_id, provider, status, code, latency_ms=None):
    lock(db, tenant_id)
    row = db.scalar(select(ProviderObservation).where(ProviderObservation.tenant_id == tenant_id, ProviderObservation.provider_key == provider))
    if not row:
        row = ProviderObservation(tenant_id=tenant_id, provider_key=provider)
        db.add(row)
    row.status, row.code, row.latency_ms, row.checked_at = status, code, latency_ms, now_utc()


def observe_activity(db, tenant_id, provider, operation, *, outcome, code,
                     performed_io: bool, synthetic: bool = False, latency_ms=None):
    """Record a scoped adapter result, without committing its caller's transaction.

    Configuration, local policy rejection, simulation and rejected authentication
    are not supplier evidence. A validated business decline proves connectivity,
    while malformed, failed or uncertain provider I/O degrades readiness. Codes
    are fixed machine identifiers; response bodies and subject identifiers must
    never enter this non-content health record.
    """
    if performed_io is not True or synthetic is not False:
        return False
    if (provider not in PROVIDERS or operation not in OPERATIONS[PROVIDER_KINDS[provider]]
            or outcome not in {"succeeded", "declined", "failed", "unknown"}):
        raise ValueError("Invalid provider activity")
    if not isinstance(code, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", code):
        raise ValueError("Provider activity requires a fixed machine code")
    if latency_ms is not None and (type(latency_ms) is not int or not 0 <= latency_ms <= 3_600_000):
        raise ValueError("Invalid provider activity latency")
    # A clinic can be disabled while the provider is completing accepted work.
    # Instrumentation must not turn that known result into an application error.
    # Fence the existing tenant without requiring it to remain active, then skip
    # readiness for inactive scopes. The fence prevents a revoke racing the
    # active-only observation helper below.
    with db.no_autoflush:
        changed = db.execute(update(Tenant).where(Tenant.id == tenant_id).values(settings_version=Tenant.settings_version))
        if not changed.rowcount or not db.scalar(select(Tenant.active).where(Tenant.id == tenant_id)):
            return False
    observation(db, tenant_id, provider, "healthy" if outcome in {"succeeded", "declined"} else "degraded", code, latency_ms)
    return True


def capability(db, tenant_id, provider):
    return db.scalar(select(IntegrationCapability).where(IntegrationCapability.tenant_id == tenant_id,
                                                        IntegrationCapability.provider_key == provider))


def require_capability(db, tenant_id, provider, operation):
    row = capability(db, tenant_id, provider)
    if not row and settings.environment.lower() not in {"prod", "production"}:
        return {"version": None, "verification": "unverified_development"}
    if not row or row.expires_at <= now_utc() or operation not in row.operations or row.verification_state != "operator_attested":
        fail(409, "CAPABILITY_APPROVAL_REQUIRED", "This operation has no current clinic capability approval.")
    return {"version": row.version, "endpoint_version": row.endpoint_version, "model_version": row.model_version,
            "region": row.region, "verification": row.verification_state}


@dataclass(frozen=True)
class ProviderContext:
    tenant_id: str
    operation_key: str
    session_factory: object
    call_id: str | None = None
    subject_hash: str | None = None
    turn_id: str | None = None

    @classmethod
    def from_session(cls, db, tenant_id, operation_key, *, call_id=None, subject_hash=None, turn_id=None):
        return cls(tenant_id, operation_key, sessionmaker(bind=db.get_bind(), expire_on_commit=False), call_id, subject_hash, turn_id)

    def authorize(self, provider, operation, *, fallback=False):
        from .privacy_controls import require_processor
        from .providers import ProviderError
        try:
            with self.session_factory() as db:
                # Capability/processor publications use the same tenant fence.
                # A concurrent revoke cannot slip between policy reads and the
                # durable dispatch reservation.
                lock(db, self.tenant_id)
                require_capability(db, self.tenant_id, provider, operation)
                return require_processor(db, self.tenant_id, provider, "processing", os.getenv(PROVIDERS[provider][3], "not_recorded"),
                                         subject_hash=self.subject_hash, is_fallback=fallback)
        except HTTPException as exc:
            raise ProviderError(exc.detail.get("code", "PROVIDER_POLICY_REJECTED")) from None

    def start(self, provider, meter, quantity, operation, *, fallback=False):
        from .billing import reserve_cost, mark_cost_started
        from .privacy_controls import require_processor
        from .providers import ProviderError
        from .ops_controls import append_trace
        region = os.getenv(PROVIDERS[provider][3], "not_recorded")
        try:
            with self.session_factory() as db:
                lock(db, self.tenant_id)
                require_capability(db, self.tenant_id, provider, operation)
                require_processor(db, self.tenant_id, provider, "processing", region,
                                  subject_hash=self.subject_hash, is_fallback=fallback)
                ticket = reserve_cost(db, self.tenant_id, f"{self.operation_key}:{provider}:{meter}", provider, meter,
                                      Decimal(str(quantity)), call_id=self.call_id)
                mark_cost_started(db, ticket["id"])
                append_trace(db, self.tenant_id, f"{ticket['id']}:started", "provider.started", call_id=self.call_id,
                    turn_id=self.turn_id, provider=provider, attributes={"reservation_id": ticket["id"], "quantity": str(quantity), "unit": meter})
                db.commit()  # No lock/connection spans external I/O.
                return ticket
        except HTTPException as exc:
            code = exc.detail.get("code", "PROVIDER_POLICY_REJECTED") if isinstance(exc.detail, dict) else "PROVIDER_POLICY_REJECTED"
            raise ProviderError(code) from None

    def finish(self, ticket, quantity, *, outcome="confirmed", code="OK", duration_ms=None, healthy=None):
        from .billing import settle_cost
        from .ops_controls import append_trace
        with self.session_factory() as db:
            settle_cost(db, ticket["id"], Decimal(str(quantity)), f"{self.operation_key}:{code}", outcome=outcome)
            observed_healthy = outcome == "confirmed" if healthy is None else healthy
            # Settlement retains the tenant fence even if the clinic was
            # disabled after dispatch. Keep accepted work and its trace durable;
            # a readiness write must not roll that evidence back or reactivate it.
            if db.scalar(select(Tenant.active).where(Tenant.id == self.tenant_id)):
                observation(db, self.tenant_id, ticket["provider"], "healthy" if observed_healthy else "degraded", code, duration_ms)
            append_trace(db, self.tenant_id, f"{ticket['id']}:{outcome}", "provider.completed" if outcome == "confirmed" else "provider.failed",
                call_id=self.call_id, turn_id=self.turn_id, provider=ticket["provider"],
                attributes={"reservation_id": ticket["id"], "outcome": outcome, "error_code": code, "duration_ms": duration_ms or 0})
            db.commit()


class CapabilityInput(StrictModel):
    version: int = Field(ge=0)
    kind: Literal["speech", "calendar", "telephony", "sms", "payment", "digest"]
    operations: list[str] = Field(min_length=1, max_length=15)
    endpoint_version: str = Field(min_length=1, max_length=120)
    model_version: str = Field(default="not_applicable", min_length=1, max_length=120)
    region: str = Field(min_length=2, max_length=80)
    data_terms_reference: str = Field(min_length=3, max_length=500)
    verification_state: Literal["declared_unverified", "operator_attested"] = "declared_unverified"
    evidence_reference: str = Field(min_length=3, max_length=500)
    expires_at: datetime
    reason: str = Field(min_length=3, max_length=500)


def capability_dict(db, tenant_id, provider):
    row = capability(db, tenant_id, provider)
    seen = db.scalar(select(ProviderObservation).where(ProviderObservation.tenant_id == tenant_id, ProviderObservation.provider_key == provider))
    configured = bool(db.scalar(select(Tenant.id).where(Tenant.id == tenant_id, configuration_condition(provider))))
    stale = not seen or seen.checked_at <= now_utc() - timedelta(seconds=int(os.getenv("PROVIDER_HEALTH_STALE_SECONDS", "120")))
    return {"provider_key": provider, "configured": configured, "version": row.version if row else 0,
        "kind": row.kind if row else None, "operations": row.operations if row else [],
        "endpoint_version": row.endpoint_version if row else "not_recorded", "model_version": row.model_version if row else "not_recorded",
        "region": row.region if row else "not_recorded", "data_terms_reference": row.data_terms_reference if row else None,
        "verification_state": row.verification_state if row else "not_approved", "evidence_reference": row.evidence_reference if row else None,
        "expires_at": row.expires_at.isoformat() if row else None,
        "health": {"status": "disabled" if not configured else "unknown" if not seen else "stale" if stale else seen.status,
            "code": seen.code if seen else "NOT_OBSERVED", "checked_at": seen.checked_at.isoformat() if seen else None,
            "latency_ms": seen.latency_ms if seen else None}}


@router.get("/integration-capabilities")
def list_capabilities(actor: Actor = Depends(require_permissions("integration:read")), db: Session = Depends(get_db)):
    return {"items": [capability_dict(db, actor.tenant_id, key) for key in PROVIDERS]}


@router.put("/integration-capabilities/{provider}")
def publish_capability(provider: str, body: CapabilityInput, actor: Actor = Depends(require_permissions("integration:write")), db: Session = Depends(get_db)):
    if provider not in PROVIDERS or PROVIDER_KINDS[provider] != body.kind or not set(body.operations) <= OPERATIONS[body.kind] or len(set(body.operations)) != len(body.operations):
        fail(422, "INVALID_CAPABILITY", "Unknown provider or unsupported capability declaration.")
    if body.expires_at.tzinfo is None or body.expires_at <= now_utc():
        fail(422, "INVALID_EXPIRY", "Approval must have a future timezone-aware expiry.")
    lock(db, actor.tenant_id)
    row = capability(db, actor.tenant_id, provider)
    if body.version != (row.version if row else 0):
        fail(409, "VERSION_CONFLICT", "Capability approval changed; read it again.")
    if not row:
        row = IntegrationCapability(tenant_id=actor.tenant_id, provider_key=provider, version=0, approved_by=actor.id)
        db.add(row)
    for key, value in body.model_dump(exclude={"version", "reason"}).items():
        setattr(row, key, value)
    row.version += 1
    row.approved_by = actor.id
    revise(db, actor, "integration.capability_published", "provider", provider, body.reason, version=row.version,
           verification_state=row.verification_state)
    db.commit()
    return capability_dict(db, actor.tenant_id, provider)


async def probe(db, tenant_id, provider):
    from .providers import ProviderError, approved_url, enabled, provider_request
    if provider not in PROVIDERS:
        fail(404, "PROVIDER_NOT_FOUND", "Provider not found.")
    gate, url_env, token_env, _ = PROVIDERS[provider]
    if provider not in {"speech_primary", "speech_fallback", "calendar_primary", "digest_gateway"}:
        # No invented carrier/SMS/payment health route and no paid health probe.
        return capability_dict(db, tenant_id, provider)
    if not enabled(gate):
        observation(db, tenant_id, provider, "disabled", "DISABLED")
        db.commit()
        return capability_dict(db, tenant_id, provider)
    base = approved_url(os.getenv(url_env, ""), gate, allow_local=True)
    token = os.getenv(token_env, "")
    db.commit()
    started = time.monotonic()
    status, code = "healthy", "HEALTH_OK"
    try:
        if provider == "calendar_primary":
            import asyncio
            from .calendar_bridge import connector_for
            async with asyncio.timeout(float(os.getenv("PROVIDER_HEALTH_TIMEOUT_SECONDS", "5"))):
                value = await connector_for(tenant_id).capabilities()
        else:
            result = await provider_request("GET", base + "/health", operation=f"health:{provider}",
                headers={"Authorization": "Bearer " + token}, timeout=float(os.getenv("PROVIDER_HEALTH_TIMEOUT_SECONDS", "5")))
            value = result.json()
        if not isinstance(value, dict) or (provider != "calendar_primary" and value.get("status") not in {"ok", "healthy", "ready"}):
            raise ProviderError("INVALID_HEALTH_RESPONSE")
    except (ProviderError, ValueError, TimeoutError) as exc:
        status, code = "degraded", getattr(exc, "code", "INVALID_HEALTH_RESPONSE")
    observation(db, tenant_id, provider, status, code, int((time.monotonic() - started) * 1000))
    db.commit()
    return capability_dict(db, tenant_id, provider)


@router.post("/integration-capabilities/{provider}/probe")
async def probe_endpoint(provider: str, actor: Actor = Depends(require_permissions("integration:write")), db: Session = Depends(get_db)):
    return await probe(db, actor.tenant_id, provider)


def dependency_readiness(db, tenant_id=None):
    # Seven bounded aggregate queries, independent of tenant count. No patient data
    # or unbounded tenant-by-provider materialization reaches a readiness probe.
    from sqlalchemy import and_, case, func
    current = now_utc()
    fresh = current - timedelta(seconds=int(os.getenv("PROVIDER_HEALTH_STALE_SECONDS", "120")))
    items = []
    for provider in PROVIDERS:
        configured = configuration_condition(provider)
        if configured is False:
            continue
        good = and_(IntegrationCapability.verification_state == "operator_attested",
            IntegrationCapability.expires_at > current, ProviderObservation.checked_at > fresh,
            ProviderObservation.status == "healthy")
        query = select(func.count(Tenant.id), func.sum(case((good, 1), else_=0))).select_from(Tenant).outerjoin(
            IntegrationCapability, and_(IntegrationCapability.tenant_id == Tenant.id, IntegrationCapability.provider_key == provider)).outerjoin(
            ProviderObservation, and_(ProviderObservation.tenant_id == Tenant.id, ProviderObservation.provider_key == provider)).where(Tenant.active.is_(True), configured)
        if tenant_id:
            query = query.where(Tenant.id == tenant_id)
        total, healthy = db.execute(query).one()
        if total == 0:
            continue
        items.append({"provider_key": provider, "configured": True, "scopes": total, "ready_scopes": healthy or 0,
                      "ready": total > 0 and total == (healthy or 0)})
    return {"ready": all(item["ready"] for item in items), "observations": items,
            "boundary": "Recent dependency observations and operator capability attestations; not clinical or carrier acceptance."}
