"""Independent purpose evidence and fail-closed processor/data lifecycle gates."""
from __future__ import annotations

import base64
from datetime import datetime, timedelta
import hashlib
import io
import json
import re
from typing import Literal
import wave

from fastapi import APIRouter, Depends
from pydantic import Field, model_validator
from sqlalchemy import String, case, cast, delete, exists, func, or_, select, update
from sqlalchemy.orm import Session

from .billing import IDENTIFIER, lock_tenant
from .config import settings
from .db import get_db, now_utc
from .models import ConsentGrant, Tenant
from .models_ops import OutreachSuppression, PrivacyTombstone
from .models_privacy import (ContactPreference, ErasureEvidence, GovernedArtifact, ProcessorApproval, PurposePolicy, RedactionPolicy)
from .operations import audit
from .schemas import StrictModel
from .security import Actor, decrypt, encrypt, fail, hash_phone, mask_phone, normalize_phone, require_permissions

router = APIRouter(prefix="/api/v1/operations/privacy-controls")
Purpose = Literal["processing", "recording", "qa", "marketing", "training", "cross_border", "memory", "reminder", "waitlist", "followup"]
PURPOSES = {"processing", "recording", "qa", "marketing", "training", "cross_border", "memory", "reminder", "waitlist", "followup"}
PURPOSE_ALIASES = {"live_speech": "processing", "transcription": "processing", "synthesis": "processing", "calendar": "processing", "transactional_sms": "processing", "owner_digest": "processing"}


def purpose_policy(db, tenant_id, purpose):
    return db.scalar(select(PurposePolicy).where(PurposePolicy.tenant_id == tenant_id, PurposePolicy.purpose == purpose).order_by(PurposePolicy.version.desc()).limit(1))


def effective_processing_retention(db, tenant, pinned_days=None):
    """An administrative transcript never outlives a stricter applicable cap."""
    def bounded(value):
        return min(value, 365) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0
    limits = [bounded(tenant.retention_days)]
    policy = purpose_policy(db, tenant.id, "processing") if db is not None else None
    if policy:
        limits.append(bounded(policy.retention_days))
    if pinned_days is not None:
        limits.append(bounded(pinned_days))
    return min(limits)


def purge_administrative_transcripts(db, tenant, *, moment=None, limit=100):
    """Delete only ended-call conversational content; preserve business/audit truth.

    The SQL cutoff considers the original per-call retention pin, so a short
    promise cannot be extended by publishing a later longer policy. The CASE
    avoids backend-specific timestamp interval arithmetic on SQLite/PostgreSQL.
    """
    from .models_voice import CallSession, MediaRegistration, VerificationChallenge, VoiceTurn
    if not 1 <= limit <= 1000:
        raise ValueError("transcript_expiry_batch_out_of_range")
    moment = moment or now_utc()
    db.execute(update(Tenant).where(Tenant.id == tenant.id).values(settings_version=Tenant.settings_version))
    db.refresh(tenant)
    current_days = effective_processing_retention(db, tenant)
    policy = purpose_policy(db, tenant.id, "processing")
    pinned = cast(CallSession.policy_snapshot["retention_days"].as_string(), String)
    cutoff = case({str(days): moment - timedelta(days=min(current_days, days)) for days in range(366)}, value=pinned,
        else_=case((pinned.is_(None), moment - timedelta(days=current_days)), else_=moment))
    already_erased = exists(select(ErasureEvidence.id).where(ErasureEvidence.tenant_id == tenant.id,
        ErasureEvidence.object_type == "call_transcript", ErasureEvidence.object_id == CallSession.id))
    calls = list(db.scalars(select(CallSession).where(CallSession.tenant_id == tenant.id,
        CallSession.ended_at.is_not(None), CallSession.ended_at <= cutoff, ~already_erased)
        .order_by(CallSession.ended_at, CallSession.id).limit(limit)))
    for call in calls:
        original_days = call.policy_snapshot.get("retention_days")
        applied_days = current_days if original_days is None else min(current_days, original_days) if isinstance(original_days, int) and not isinstance(original_days, bool) and original_days >= 0 else 0
        original = hashlib.sha256(call.context_encrypted.encode())
        for encrypted in db.scalars(select(VoiceTurn.result_encrypted).where(VoiceTurn.tenant_id == tenant.id, VoiceTurn.call_id == call.id).order_by(VoiceTurn.id)):
            original.update(encrypted.encode())
        retained_subject = call.phone_hash or "session:" + call.id
        for model in (VoiceTurn, VerificationChallenge, MediaRegistration):
            db.execute(delete(model).where(model.tenant_id == tenant.id, model.call_id == call.id))
        call.context_encrypted, call.phone_hash, call.policy_snapshot = encrypt("{}"), None, {}
        call.token_hash = hashlib.sha256(("retired:" + call.id).encode()).hexdigest()
        db.add(ErasureEvidence(tenant_id=tenant.id, object_type="call_transcript", object_id=call.id,
            subject_hash=retained_subject, purpose="processing", reason="administrative_retention",
            previous_content_sha256=original.hexdigest(), backup_delete_by=moment + timedelta(days=policy.backup_expiry_days if policy else 30)))
        audit(db, tenant.id, "privacy-worker", "privacy.transcript_erased", "call_session", call.id,
            retention_days=applied_days, original_limit_respected=True, hash_basis="encrypted_retired_records")
    db.flush()
    return len(calls)


def processing_notice(db, tenant_id):
    """Public-safe notice and the version to bind to explicit session consent."""
    policy = purpose_policy(db, tenant_id, "processing")
    if policy and not policy.enabled:
        fail(409, "PROCESSING_DISABLED", "The clinic has disabled automated processing.")
    return {"purpose": "processing", "policy_version": f"processing:v{policy.version}" if policy else "v1",
        "notice": policy.notice if policy else None, "retention_days": policy.retention_days if policy else None,
        "consent_expires_at": now_utc() + timedelta(days=policy.consent_valid_days) if policy else None}


def purpose_allowed(db, tenant_id, subject_hash, purpose, *, require_current_policy=True):
    if purpose not in PURPOSES or not subject_hash:
        return False
    if db.scalar(select(PrivacyTombstone.id).where(PrivacyTombstone.tenant_id == tenant_id, PrivacyTombstone.subject_hash == subject_hash)):
        return False
    if db.scalar(select(OutreachSuppression.id).where(OutreachSuppression.tenant_id == tenant_id, OutreachSuppression.subject_hash == subject_hash, OutreachSuppression.purpose == purpose)):
        return False
    policy = purpose_policy(db, tenant_id, purpose)
    grant = db.scalar(select(ConsentGrant).where(ConsentGrant.tenant_id == tenant_id, ConsentGrant.subject_hash == subject_hash,
        ConsentGrant.purpose == purpose).order_by(ConsentGrant.created_at.desc(), ConsentGrant.id.desc()).limit(1))
    if not grant or not grant.granted or grant.expires_at and grant.expires_at <= now_utc():
        return False
    if require_current_policy:
        return bool(policy and policy.enabled and grant.policy_version == f"{purpose}:v{policy.version}")
    return True


def require_processor(db, tenant_id: str, provider_key: str, purpose: str, region: str,
                      subject_hash: str | None = None, is_fallback=False) -> dict:
    purpose = PURPOSE_ALIASES.get(purpose, purpose)
    row = db.scalar(select(ProcessorApproval).where(ProcessorApproval.tenant_id == tenant_id,
        ProcessorApproval.provider_key == provider_key).order_by(ProcessorApproval.version.desc()).limit(1))
    production = settings.environment.lower() in {"prod", "production"}
    if not row and not production:
        return {"provider_key": provider_key, "verification": "unapproved_development", "version": None, "region": region}
    if not row or not row.enabled or row.expires_at <= now_utc() or purpose not in row.purposes or region not in row.regions or is_fallback and not row.fallback_eligible:
        fail(409, "PROCESSOR_NOT_APPROVED", "No current clinic approval permits this provider, purpose, region and fallback path.")
    if region != row.origin_region and not purpose_allowed(db, tenant_id, subject_hash, "cross_border"):
        fail(403, "CROSS_BORDER_PERMISSION_REQUIRED", "This subject has not authorized the approved cross-border processing purpose.")
    if subject_hash:
        policy = purpose_policy(db, tenant_id, purpose)
        # Existing live-call processing evidence remains compatible until the
        # clinic publishes a versioned purpose notice. Optional uses always
        # require an enabled, current independently recorded purpose grant.
        required = purpose != "processing" or policy is not None
        if required and not purpose_allowed(db, tenant_id, subject_hash, purpose):
            fail(403, "PURPOSE_PERMISSION_REQUIRED", "The current independent purpose permission is missing or withdrawn.")
    return {"provider_key": row.provider_key, "version": row.version, "region": region,
        "purpose": purpose, "retention_days": row.retention_days, "fallback_eligible": row.fallback_eligible,
        "contract_sha256": row.contract_sha256, "verification": "operator_attested_contract"}


class PurposeInput(StrictModel):
    purpose: Purpose
    enabled: bool = False
    notice: str = Field(min_length=20, max_length=4000)
    retention_days: int = Field(ge=0, le=365)
    backup_expiry_days: int = Field(ge=1, le=365)
    consent_valid_days: int = Field(ge=1, le=365)
    evidence_reference: str = Field(pattern=IDENTIFIER)


@router.put("/purposes")
def publish_purpose(data: PurposeInput, actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    old = purpose_policy(db, actor.tenant_id, data.purpose)
    row = PurposePolicy(tenant_id=actor.tenant_id, version=(old.version if old else 0) + 1, approved_by=actor.id, **data.model_dump())
    db.add(row)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "privacy.purpose_published", "purpose_policy", row.id,
        purpose=row.purpose, version=row.version, enabled=row.enabled)
    db.commit()
    return {"purpose": row.purpose, "version": row.version, "policy_version": f"{row.purpose}:v{row.version}", "enabled": row.enabled}


@router.get("/purposes")
def purposes(actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    rows = []
    for purpose in sorted(PURPOSES):
        row = purpose_policy(db, actor.tenant_id, purpose)
        rows.append({"purpose": purpose, "version": row.version if row else None, "enabled": bool(row and row.enabled),
            "notice": row.notice if row else None, "retention_days": row.retention_days if row else None,
            "backup_expiry_days": row.backup_expiry_days if row else None, "consent_valid_days": row.consent_valid_days if row else None})
    return rows


class PermissionInput(StrictModel):
    phone: str = Field(max_length=30)
    purpose: Purpose
    granted: bool
    policy_version: int = Field(ge=1)
    evidence_reference: str = Field(pattern=IDENTIFIER)
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    method: Literal["signed_form", "recorded_verbal_request", "verified_subject_request"]
    subject_request_confirmed: bool


@router.post("/permissions")
def record_permission(data: PermissionInput, actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    if not data.subject_request_confirmed:
        fail(422, "SUBJECT_REQUEST_REQUIRED", "Record only the subject's actual independent choice.")
    phone, subject = normalize_phone(data.phone), hash_phone(data.phone)
    lock_tenant(db, actor.tenant_id)
    policy = purpose_policy(db, actor.tenant_id, data.purpose)
    if not policy or policy.version != data.policy_version or data.granted and not policy.enabled:
        fail(409, "PURPOSE_POLICY_CHANGED", "Review the current purpose notice before recording this choice.")
    if data.granted and db.scalar(select(PrivacyTombstone.id).where(PrivacyTombstone.tenant_id == actor.tenant_id, PrivacyTombstone.subject_hash == subject)):
        fail(409, "SUBJECT_ERASED", "A deletion tombstone cannot be overridden by a consent form.")
    row = ConsentGrant(tenant_id=actor.tenant_id, subject_hash=subject, purpose=data.purpose, granted=data.granted,
        policy_version=f"{data.purpose}:v{policy.version}", expires_at=now_utc() + timedelta(days=policy.consent_valid_days),
        evidence={"reference": data.evidence_reference, "sha256": data.evidence_sha256, "method": data.method,
            "recorded_by": actor.id, "verification": "staff_attested_subject_request"})
    db.add(row)
    db.flush()
    revoked_artifacts = ended_calls = 0
    if not data.granted:
        revoked_artifacts = db.execute(update(GovernedArtifact).where(GovernedArtifact.tenant_id == actor.tenant_id,
            GovernedArtifact.subject_hash == subject, GovernedArtifact.purpose == data.purpose, GovernedArtifact.status == "ACTIVE").values(expires_at=now_utc())).rowcount
        if data.purpose in {"reminder", "waitlist", "followup"}:
            from .operations import revoke_outreach
            revoke_outreach(db, actor.tenant_id, phone, [data.purpose], actor.id, commit=False)
        elif data.purpose == "processing":
            from .models_voice import CallSession
            from .voice import release_holds
            for call in db.scalars(select(CallSession).where(CallSession.tenant_id == actor.tenant_id, CallSession.phone_hash == subject, CallSession.ended_at.is_(None))):
                call.processing_consent, call.state, call.ended_at = False, "CONSENT_WITHDRAWN", now_utc()
                call.lease_token, call.lease_until = None, None
                release_holds(db, call)
                ended_calls += 1
    audit(db, actor.tenant_id, actor.id, "privacy.permission_recorded", "subject", subject,
        purpose=data.purpose, granted=data.granted, policy_version=row.policy_version, evidence_sha256=data.evidence_sha256)
    db.commit()
    return {"id": row.id, "purpose": data.purpose, "granted": data.granted, "phone_masked": mask_phone(phone),
        "policy_version": row.policy_version, "expires_at": row.expires_at, "expiring_artifacts": revoked_artifacts,
        "ended_calls": ended_calls, "evidence_verification": "staff_attested_subject_request"}


class ProcessorInput(StrictModel):
    provider_key: str = Field(pattern=IDENTIFIER, max_length=80)
    enabled: bool = False
    purposes: list[Purpose] = Field(min_length=1, max_length=10)
    regions: list[str] = Field(min_length=1, max_length=10)
    origin_region: str = Field(default="IR", pattern=r"^[A-Za-z0-9_-]{2,40}$")
    retention_days: int = Field(ge=0, le=365)
    fallback_eligible: bool = False
    contract_reference: str = Field(pattern=IDENTIFIER)
    contract_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    expires_at: datetime

    @model_validator(mode="after")
    def validate_approval(self):
        if any(not re.fullmatch(r"[A-Za-z0-9_-]{2,40}", region) for region in self.regions):
            raise ValueError("Supply explicit region identifiers")
        if not self.expires_at.tzinfo or not now_utc() < self.expires_at <= now_utc() + timedelta(days=366):
            raise ValueError("Approval expiry must be within the next year")
        return self


@router.put("/processors")
def approve_processor(data: ProcessorInput, actor: Actor = Depends(require_permissions("privacy:manage", "integration:write")), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    version = (db.scalar(select(func.max(ProcessorApproval.version)).where(ProcessorApproval.tenant_id == actor.tenant_id, ProcessorApproval.provider_key == data.provider_key)) or 0) + 1
    row = ProcessorApproval(tenant_id=actor.tenant_id, version=version, reviewed_by=actor.id, **data.model_dump())
    db.add(row)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "privacy.processor_approved", "processor_approval", row.id,
        provider_key=row.provider_key, version=version, enabled=row.enabled, contract_sha256=row.contract_sha256)
    db.commit()
    return {"provider_key": row.provider_key, "version": row.version, "enabled": row.enabled, "verification": "operator_attested_contract"}


@router.get("/processors")
def processors(actor: Actor = Depends(require_permissions("integration:read")), db: Session = Depends(get_db)):
    result, seen = [], set()
    for row in db.scalars(select(ProcessorApproval).where(ProcessorApproval.tenant_id == actor.tenant_id).order_by(ProcessorApproval.version.desc())):
        if row.provider_key in seen:
            continue
        seen.add(row.provider_key)
        result.append({k: getattr(row, k) for k in ("provider_key", "version", "enabled", "purposes", "regions", "origin_region", "retention_days", "fallback_eligible", "contract_reference", "contract_sha256", "expires_at")})
    return result


class ArtifactInput(StrictModel):
    phone: str = Field(max_length=30)
    purpose: Purpose
    kind: Literal["transcript", "qa_sample", "research_export", "audio", "subject_export"]
    payload: str = Field(max_length=2_000_000)
    idempotency_key: str = Field(pattern=IDENTIFIER)


def artifact_dict(row):
    return {k: getattr(row, k) for k in ("id", "purpose", "policy_version", "kind", "status", "content_sha256", "expires_at", "hold_reference", "hold_until", "metadata_safe", "created_at")}


@router.post("/artifacts")
def retain_artifact(data: ArtifactInput, actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    subject = hash_phone(data.phone)
    lock_tenant(db, actor.tenant_id)
    policy = purpose_policy(db, actor.tenant_id, data.purpose)
    if not policy or not policy.retention_days or not purpose_allowed(db, actor.tenant_id, subject, data.purpose):
        fail(403, "ARTIFACT_PERMISSION_REQUIRED", "A current independent permission and nonzero retention policy are required.")
    expected = {"audio": "recording", "qa_sample": "qa", "research_export": "training", "subject_export": "processing", "transcript": "processing"}
    if data.purpose != expected[data.kind]:
        fail(422, "ARTIFACT_PURPOSE_MISMATCH", "The artifact kind requires its specific independent purpose.")
    metadata = {"encoding": "utf8", "bytes": len(data.payload.encode())}
    if data.kind == "audio":
        try:
            blob = base64.b64decode(data.payload, validate=True)
            with wave.open(io.BytesIO(blob), "rb") as source:
                frames, rate = source.getnframes(), source.getframerate()
                if source.getnchannels() != 1 or source.getsampwidth() != 2 or rate not in {8000, 16000, 24000, 48000} or source.getcomptype() != "NONE" or not 0 < frames <= rate * 60 or len(source.readframes(frames)) != frames * 2:
                    raise ValueError
                metadata = {"encoding": "wav_pcm_s16le_base64", "sample_rate": rate, "frames": frames, "channels": 1, "bytes": len(blob)}
        except (ValueError, EOFError, wave.Error):
            fail(422, "INVALID_RETAINED_AUDIO", "Audio must be complete mono 16-bit PCM WAV, no more than 60 seconds.")
    content_hash = hashlib.sha256(data.payload.encode()).hexdigest()
    old = db.scalar(select(GovernedArtifact).where(GovernedArtifact.tenant_id == actor.tenant_id, GovernedArtifact.idempotency_key == data.idempotency_key))
    if old:
        if (old.content_sha256, old.subject_hash, old.purpose, old.kind) != (content_hash, subject, data.purpose, data.kind):
            fail(409, "ARTIFACT_CONFLICT", "This artifact key has different contents.")
        return artifact_dict(old)
    row = GovernedArtifact(tenant_id=actor.tenant_id, subject_hash=subject, purpose=data.purpose, policy_version=policy.version,
        kind=data.kind, idempotency_key=data.idempotency_key, content_sha256=content_hash, payload_encrypted=encrypt(data.payload),
        metadata_safe=metadata, expires_at=now_utc() + timedelta(days=policy.retention_days), backup_expiry_days=policy.backup_expiry_days, created_by=actor.id)
    db.add(row)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "privacy.artifact_retained", "governed_artifact", row.id, purpose=row.purpose, content_sha256=content_hash)
    db.commit()
    return artifact_dict(row)


@router.get("/artifacts")
def artifacts(actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    return [artifact_dict(row) for row in db.scalars(select(GovernedArtifact).where(GovernedArtifact.tenant_id == actor.tenant_id).order_by(GovernedArtifact.created_at.desc()).limit(200))]


@router.get("/artifacts/{artifact_id}/content")
def artifact_content(artifact_id: str, actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    row = db.get(GovernedArtifact, artifact_id)
    if not row or row.tenant_id != actor.tenant_id:
        fail(404, "ARTIFACT_NOT_FOUND", "Artifact is not available.")
    if row.status != "ACTIVE" or row.expires_at <= now_utc() or not purpose_allowed(db, actor.tenant_id, row.subject_hash, row.purpose):
        fail(410, "ARTIFACT_NOT_AUTHORIZED", "The artifact is expired or its purpose permission is no longer current.")
    audit(db, actor.tenant_id, actor.id, "privacy.artifact_accessed", "governed_artifact", row.id)
    db.commit()
    return {**artifact_dict(row), "payload": decrypt(row.payload_encrypted)}


class HoldInput(StrictModel):
    evidence_reference: str = Field(pattern=IDENTIFIER)
    hold_until: datetime


@router.post("/artifacts/{artifact_id}/hold")
def hold_artifact(artifact_id: str, data: HoldInput, actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    if not data.hold_until.tzinfo or not now_utc() < data.hold_until <= now_utc() + timedelta(days=365):
        fail(422, "INVALID_HOLD_EXPIRY", "A documented hold must have an expiry within one year.")
    lock_tenant(db, actor.tenant_id)
    row = db.get(GovernedArtifact, artifact_id)
    if not row or row.tenant_id != actor.tenant_id or row.status != "ACTIVE":
        fail(404, "ARTIFACT_NOT_FOUND", "Active artifact is not available.")
    row.hold_reference, row.hold_until = data.evidence_reference, data.hold_until
    audit(db, actor.tenant_id, actor.id, "privacy.artifact_hold", "governed_artifact", row.id, evidence_reference=data.evidence_reference, hold_until=data.hold_until.isoformat())
    db.commit()
    return artifact_dict(row)


def expire_artifacts(db, limit=100, *, tenant_id=None):
    if not 1 <= limit <= 1000:
        raise ValueError("artifact_expiry_batch_out_of_range")
    moment = now_utc()
    expired = [GovernedArtifact.status == "ACTIVE", GovernedArtifact.expires_at <= moment]
    if tenant_id is not None:
        expired.append(GovernedArtifact.tenant_id == tenant_id)
    # A long-lived hold must not occupy every batch slot and starve unrelated
    # expired content indefinitely. Count held rows, then select deletable work.
    held = db.scalar(select(func.count()).select_from(GovernedArtifact).where(*expired,
        GovernedArtifact.hold_until > moment)) or 0
    count = 0
    for row in db.scalars(select(GovernedArtifact).where(*expired,
        or_(GovernedArtifact.hold_until.is_(None), GovernedArtifact.hold_until <= moment))
        .order_by(GovernedArtifact.tenant_id, GovernedArtifact.expires_at, GovernedArtifact.id).limit(limit)):
        # Retirement of a clinic does not suspend its deletion obligations.
        db.execute(update(Tenant).where(Tenant.id == row.tenant_id).values(settings_version=Tenant.settings_version))
        db.refresh(row)
        if row.status != "ACTIVE" or row.expires_at > moment:
            continue
        if row.hold_until and row.hold_until > now_utc():
            held += 1
            continue
        row.payload_encrypted, row.status = None, "ERASED"
        db.add(ErasureEvidence(tenant_id=row.tenant_id, object_type="governed_artifact", object_id=row.id,
            subject_hash=row.subject_hash, purpose=row.purpose, reason="expiry_or_withdrawal", previous_content_sha256=row.content_sha256,
            backup_delete_by=now_utc() + timedelta(days=row.backup_expiry_days)))
        audit(db, row.tenant_id, "privacy-worker", "privacy.artifact_erased", "governed_artifact", row.id, purpose=row.purpose)
        count += 1
    db.flush()
    return {"erased": count, "held": held}


def erase_subject_extensions(db, tenant_id, subject):
    """Erase optional content, while uncertain live calendar writes stay reviewed."""
    from .models_core import BookingSeries, ExternalCalendarOperation, PackageEntitlement
    from .models_ops_control import VoiceOutreach
    erased = held = pending_calendar_review = structured_calendar_records = 0
    for row in db.scalars(select(GovernedArtifact).where(GovernedArtifact.tenant_id == tenant_id,
        GovernedArtifact.subject_hash == subject, GovernedArtifact.status == "ACTIVE")):
        row.expires_at = now_utc()
        if row.hold_until and row.hold_until > now_utc():
            held += 1
            continue
        row.payload_encrypted, row.status = None, "ERASED"
        db.add(ErasureEvidence(tenant_id=tenant_id, object_type="governed_artifact", object_id=row.id, subject_hash=subject,
            purpose=row.purpose, reason="subject_erasure", previous_content_sha256=row.content_sha256,
            backup_delete_by=now_utc() + timedelta(days=row.backup_expiry_days)))
        erased += 1
    for job in db.scalars(select(VoiceOutreach).where(VoiceOutreach.tenant_id == tenant_id, VoiceOutreach.subject_hash == subject)):
        job.recipient_encrypted, job.voicemail_allowed = encrypt("deleted"), False
        if job.status in {"QUEUED", "FAILED"}:
            job.status = "SUPPRESSED"
    for entitlement in db.scalars(select(PackageEntitlement).where(PackageEntitlement.tenant_id == tenant_id, PackageEntitlement.phone_hash == subject)):
        entitlement.reason_encrypted = encrypt("privacy_erasure")
    for series in db.scalars(select(BookingSeries).where(BookingSeries.tenant_id == tenant_id, BookingSeries.phone_hash == subject)):
        if series.status in {"RUNNING", "UNKNOWN", "PENDING"}:
            pending_calendar_review += 1
        else:
            series.request_encrypted = encrypt("{}")
    for operation in db.scalars(select(ExternalCalendarOperation).where(ExternalCalendarOperation.tenant_id == tenant_id, ExternalCalendarOperation.phone_hash == subject)):
        if operation.status in {"PENDING", "SENDING", "DISPATCHING", "UNKNOWN", "VERIFYING", "FAILED_REVIEW"}:
            pending_calendar_review += 1
        elif operation.status == "SUCCEEDED":
            # Match internal appointment erasure: remove direct identifiers,
            # but do not destroy the structured calendar truth needed to show,
            # cancel, or reconcile an already committed remote appointment.
            request = json.loads(decrypt(operation.request_encrypted))
            result = json.loads(decrypt(operation.result_encrypted)) if operation.result_encrypted else {}
            request_fields = {"slot_id", "revision", "provider_id", "service_id", "start_at", "patient_token",
                "approval_required", "hold_id", "remote_id", "slot_revision", "date", "cursor"}
            result_fields = {"id", "account_id", "revision", "status", "slot_id", "provider_id", "service_id",
                "patient_token", "start_at", "end_at", "reference", "payment_expires_at", "expires_at", "requires_readback", "slots"}
            operation.request_encrypted = encrypt(json.dumps({key: value for key, value in request.items() if key in request_fields}))
            if operation.result_encrypted:
                operation.result_encrypted = encrypt(json.dumps({key: value for key, value in result.items() if key in result_fields}))
            structured_calendar_records += 1
        else:
            operation.request_encrypted = encrypt("{}")
            if operation.result_encrypted:
                operation.result_encrypted = encrypt("{}")
    if pending_calendar_review:
        from .models import StaffTask
        db.add(StaffTask(tenant_id=tenant_id, reason="PRIVACY_EXTERNAL_RECONCILE", priority="urgent",
            summary="Subject erasure requires reconciliation of an unfinished calendar operation; preserve only necessary evidence until its authoritative outcome is known."))
    db.flush()
    return {"artifacts_erased": erased, "artifacts_held": held, "external_calendar_review_required": pending_calendar_review,
        "active_external_business_records_retained": bool(pending_calendar_review or structured_calendar_records),
        "structured_external_records_retained": structured_calendar_records}


def migrate_legacy_billing_notes(db):
    """Idempotently encrypt old free-text notes without changing invoice amounts."""
    from .models_ops import BillingAdjustment, Invoice
    counts = {"adjustment_notes_encrypted": 0, "invoice_note_snapshots_encrypted": 0}
    invoices = list(db.scalars(select(Invoice)))
    for invoice in invoices:
        if not isinstance(invoice.snapshot, dict) or not isinstance(invoice.snapshot.get("adjustments", []), list):
            raise ValueError("legacy_invoice_snapshot_requires_manual_review")
        for item in invoice.snapshot.get("adjustments", []):
            if not isinstance(item, dict) or item.get("reason") is not None and not isinstance(item["reason"], str):
                raise ValueError("legacy_invoice_adjustment_requires_manual_review")
    for row in db.scalars(select(BillingAdjustment).where(BillingAdjustment.reason != "encrypted_audit_evidence")):
        audit(db, row.tenant_id, "privacy-migration-v2", "billing.adjustment", "billing_adjustment", row.id,
            amount_toman=row.amount_toman, reason_encrypted=encrypt(row.reason), migrated_from_legacy=True)
        row.reason = "encrypted_audit_evidence"
        counts["adjustment_notes_encrypted"] += 1
    for invoice in invoices:
        adjustments = invoice.snapshot.get("adjustments", [])
        if not any(isinstance(item, dict) and item.get("reason") not in {None, "authorized_billing_adjustment"} for item in adjustments):
            continue
        audit(db, invoice.tenant_id, "privacy-migration-v2", "billing.legacy_notes_encrypted", "invoice", invoice.id,
            adjustments_encrypted=encrypt(json.dumps(adjustments, ensure_ascii=False)), financial_amount_unchanged=True)
        snapshot = dict(invoice.snapshot)
        snapshot["adjustments"] = [{**item, "reason": "authorized_billing_adjustment"} if isinstance(item, dict) else item for item in adjustments]
        invoice.snapshot = snapshot
        counts["invoice_note_snapshots_encrypted"] += 1
    db.flush()
    return counts


@router.get("/erasures")
def erasures(actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    return [{k: getattr(row, k) for k in ("id", "object_type", "object_id", "purpose", "reason", "backup_delete_by", "backup_status", "backup_evidence_reference", "created_at")} for row in db.scalars(select(ErasureEvidence).where(ErasureEvidence.tenant_id == actor.tenant_id).order_by(ErasureEvidence.created_at.desc()).limit(200))]


class BackupEvidenceInput(StrictModel):
    evidence_reference: str = Field(pattern=IDENTIFIER)
    deletion_verified: bool


@router.post("/erasures/{erasure_id}/backup-evidence")
def backup_evidence(erasure_id: str, data: BackupEvidenceInput, actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    if not data.deletion_verified:
        fail(422, "EVIDENCE_REQUIRED", "Record evidence only after the relevant retained backups are expired or erased.")
    row = db.get(ErasureEvidence, erasure_id)
    if not row or row.tenant_id != actor.tenant_id:
        fail(404, "ERASURE_NOT_FOUND", "Erasure record is unavailable.")
    row.backup_status, row.backup_evidence_reference = "OPERATOR_VERIFIED", data.evidence_reference
    audit(db, actor.tenant_id, actor.id, "privacy.backup_erasure_attested", "erasure_evidence", row.id, evidence_reference=data.evidence_reference)
    db.commit()
    return {"id": row.id, "backup_status": row.backup_status}


class RedactionInput(StrictModel):
    names: list[str] = Field(default_factory=list, max_length=200)
    health_terms: list[str] = Field(default_factory=list, max_length=200)
    addresses: list[str] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def lengths(self):
        if any(not 2 <= len(term.strip()) <= 300 for values in self.model_dump().values() for term in values):
            raise ValueError("Governed terms must contain 2 to 300 characters")
        return self


@router.put("/redaction")
def publish_redaction(data: RedactionInput, actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    row = db.get(RedactionPolicy, actor.tenant_id)
    if row:
        row.version += 1
        row.terms_encrypted, row.reviewed_by, row.updated_at = encrypt(json.dumps(data.model_dump())), actor.id, now_utc()
    else:
        row = RedactionPolicy(tenant_id=actor.tenant_id, terms_encrypted=encrypt(json.dumps(data.model_dump())), reviewed_by=actor.id)
        db.add(row)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "privacy.redaction_published", "redaction_policy", actor.tenant_id, version=row.version, counts={k: len(v) for k, v in data.model_dump().items()})
    db.commit()
    return {"version": row.version, "counts": {k: len(v) for k, v in data.model_dump().items()}, "free_text_log_policy": "withhold_unclassified_fields"}


def redact_text(value: str, governed: dict | None = None) -> str:
    """Deterministic governed redaction, not a claim of universal PII detection."""
    text = value.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    for category, terms in (governed or {}).items():
        for term in sorted(terms, key=len, reverse=True):
            normalized = term.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
            text = re.sub(re.escape(normalized), f"[{category.upper()}]", text, flags=re.IGNORECASE)
    patterns = [(r"(?<!\w)IR\s*(?:\d\s*){24}(?!\d)", "[BANK_ACCOUNT]"),
        (r"(?<!\d)(?:\d[ -]?){16}(?!\d)", "[PAYMENT_CARD]"),
        (r"(?<!\d)(?:\+?98|0098|0)?9(?:[ ()-]?\d){9}(?!\d)", "[PHONE]"),
        (r"(?<!\d)\d{10}(?!\d)", "[NATIONAL_ID]"),
        (r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[EMAIL]")]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


class RedactionPreviewInput(StrictModel):
    text: str = Field(max_length=10000)


@router.post("/redaction/preview")
def redaction_preview(data: RedactionPreviewInput, actor: Actor = Depends(require_permissions("privacy:manage")), db: Session = Depends(get_db)):
    row = db.get(RedactionPolicy, actor.tenant_id)
    terms = json.loads(decrypt(row.terms_encrypted)) if row else {}
    return {"redacted": redact_text(data.text, terms), "version": row.version if row else None,
        "scope": "patterns_and_reviewed_terms_only", "unclassified_free_text_safe_to_log": False}


class ContactInput(StrictModel):
    phone: str = Field(max_length=30)
    shared_phone: bool = True
    name_allowed: bool = False
    voicemail_allowed: bool = False
    clinic_name_allowed: bool = False
    evidence_reference: str = Field(pattern=IDENTIFIER)


@router.put("/contact-preferences")
def contact_preference(data: ContactInput, actor: Actor = Depends(require_permissions("appointment:write")), db: Session = Depends(get_db)):
    subject = hash_phone(data.phone)
    lock_tenant(db, actor.tenant_id)
    row = db.scalar(select(ContactPreference).where(ContactPreference.tenant_id == actor.tenant_id, ContactPreference.subject_hash == subject))
    if not row:
        row = ContactPreference(tenant_id=actor.tenant_id, subject_hash=subject, recorded_by=actor.id, evidence_reference=data.evidence_reference)
        db.add(row)
    for key, value in data.model_dump(exclude={"phone"}).items():
        setattr(row, key, value)
    row.recorded_by, row.updated_at = actor.id, now_utc()
    db.flush()
    audit(db, actor.tenant_id, actor.id, "privacy.contact_preference", "subject", subject,
        shared_phone=data.shared_phone, voicemail_allowed=data.voicemail_allowed, clinic_name_allowed=data.clinic_name_allowed)
    db.commit()
    return {"id": row.id, "phone_masked": mask_phone(normalize_phone(data.phone)), **data.model_dump(exclude={"phone", "evidence_reference"})}


def neutral_message(db, tenant_id, subject_hash, body: str, clinic_name: str) -> str:
    row = db.scalar(select(ContactPreference).where(ContactPreference.tenant_id == tenant_id, ContactPreference.subject_hash == subject_hash))
    # No specialty/procedure or patient name is ever introduced here. Clinic
    # names can themselves reveal specialty, so absent permission stays neutral.
    if not row or row.shared_phone or not row.clinic_name_allowed:
        body = body.replace(clinic_name, "پذیرش")
    return body
