"""The publicly pinned processing limit governs actual administrative transcripts."""
from datetime import timedelta
import hashlib
import json

from sqlalchemy import func, select

from receptionist.db import now_utc
from receptionist.models import AuditEvent, Tenant
from receptionist.models_ops import BillingAdjustment
from receptionist.models_privacy import ErasureEvidence, GovernedArtifact
from receptionist.models_voice import CallSession, VoiceTurn
from receptionist.operations import run_jobs
from receptionist.ops_controls import run_control_jobs
from receptionist.privacy_controls import effective_processing_retention, purge_administrative_transcripts
from receptionist.security import decrypt, encrypt
from test_core import database as database
from test_finance_privacy_v2 import purpose


def ended_call(db, key, days_ago, pinned_days, tenant_id="clinic-bahar"):
    ended = now_utc() - timedelta(days=days_ago)
    row = CallSession(tenant_id=tenant_id, token_hash=hashlib.sha256(key.encode()).hexdigest(),
        channel="browser_text", state="DONE", policy_version=1,
        policy_snapshot={} if pinned_days is None else {"retention_days": pinned_days},
        context_encrypted=encrypt(json.dumps({"patient_name": "Synthetic private transcript"})),
        phone_hash="a" * 64, started_at=ended - timedelta(minutes=5), ended_at=ended, expires_at=ended + timedelta(minutes=5))
    db.add(row)
    db.flush()
    db.add(VoiceTurn(tenant_id=row.tenant_id, call_id=row.id, request_id=key, request_hash="b" * 64,
        result_encrypted=encrypt('{"reply":"Synthetic private reply"}')))
    db.commit()
    return row


def test_effective_limit_is_strictest_processing_tenant_and_original_pin(database):
    with database() as db:
        tenant = db.get(Tenant, "clinic-bahar")
        tenant.retention_days = 30
        db.commit()
        assert effective_processing_retention(db, tenant) == 30
        purpose(db, "processing", days=5)
        assert effective_processing_retention(db, tenant) == 5
        assert effective_processing_retention(db, tenant, pinned_days=2) == 2
        tenant.retention_days = 1
        db.commit()
        assert effective_processing_retention(db, tenant) == 1
        purpose(db, "qa", days=0)
        assert effective_processing_retention(db, tenant) == 1
        assert effective_processing_retention(db, tenant, pinned_days="malformed") == 0


def test_real_worker_purges_shorter_original_and_published_limits_with_backup_evidence(database):
    with database() as db:
        tenant = db.get(Tenant, "clinic-bahar")
        tenant.retention_days = 30
        db.commit()
        purpose(db, "processing", days=5)
        published_due = ended_call(db, "published-shorter", 6, 30)
        original_due = ended_call(db, "original-shorter", 3, 2)
        retained = ended_call(db, "still-authorized", 3, 30)
        financial = BillingAdjustment(tenant_id=tenant.id, period="2026-10", amount_toman=7,
            reason="encrypted_audit_evidence", idempotency_key="retained-financial-record")
        db.add(financial)
        db.commit()
        result = run_jobs(db)
        assert result["retention_purged"] == 2
        for row in (published_due, original_due):
            db.refresh(row)
            assert decrypt(row.context_encrypted) == "{}" and row.phone_hash is None
            assert not db.scalar(select(VoiceTurn.id).where(VoiceTurn.call_id == row.id))
            evidence = db.scalar(select(ErasureEvidence).where(ErasureEvidence.object_type == "call_transcript", ErasureEvidence.object_id == row.id))
            assert evidence.purpose == "processing" and evidence.backup_status == "PENDING_EXPIRY"
            assert evidence.backup_delete_by > now_utc()
        db.refresh(retained)
        assert "Synthetic private" in decrypt(retained.context_encrypted)
        assert db.get(BillingAdjustment, financial.id).amount_toman == 7
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "privacy.transcript_erased", AuditEvent.entity_id == original_due.id))
        assert event.details["retention_days"] == 2
        assert run_jobs(db)["retention_purged"] == 0


def test_due_query_does_not_starve_short_pin_and_disabled_clinic_still_purges(database):
    with database() as db:
        tenant = db.get(Tenant, "clinic-bahar")
        tenant.retention_days = 30
        db.commit()
        older_not_due = ended_call(db, "older-long-retention", 8, 30)
        newer_due = ended_call(db, "newer-zero-retention", 1, 0)
        assert purge_administrative_transcripts(db, tenant, limit=1) == 1
        db.commit()
        assert decrypt(newer_due.context_encrypted) == "{}"
        assert "Synthetic private" in decrypt(older_not_due.context_encrypted)
        tenant.active = False
        tenant.retention_days = 0
        db.commit()
        report = run_control_jobs(db)
        db.commit()
        assert report["privacy"]["transcripts_erased"] == 1
        db.refresh(older_not_due)
        assert decrypt(older_not_due.context_encrypted) == "{}"
        assert db.scalar(select(func.count()).select_from(ErasureEvidence).where(ErasureEvidence.object_type == "call_transcript")) == 2


def test_per_tenant_cap_does_not_starve_later_clinics(database):
    with database() as db:
        for tenant_id in ("clinic-bahar", "clinic-niloufar"):
            tenant = db.get(Tenant, tenant_id)
            tenant.active, tenant.retention_days = False, 0
            for index in range(2):
                ended_call(db, f"fair-{tenant_id}-{index}", index + 1, 0, tenant_id)
                db.add(GovernedArtifact(tenant_id=tenant_id, subject_hash="b" * 64, purpose="qa", policy_version=1,
                    kind="qa_sample", idempotency_key=f"fair-artifact-{index}", content_sha256="a" * 64,
                    payload_encrypted=encrypt("synthetic retained data"), expires_at=now_utc() - timedelta(days=1),
                    backup_expiry_days=7, created_by="demo-owner"))
        db.commit()
        first = run_control_jobs(db, limit=1)
        db.commit()
        assert first["privacy"] == {"erased": 2, "held": 0, "transcripts_erased": 2}
        for tenant_id in ("clinic-bahar", "clinic-niloufar"):
            assert db.scalar(select(func.count()).select_from(ErasureEvidence).where(
                ErasureEvidence.tenant_id == tenant_id, ErasureEvidence.object_type == "call_transcript")) == 1
            assert db.scalar(select(func.count()).select_from(GovernedArtifact).where(
                GovernedArtifact.tenant_id == tenant_id, GovernedArtifact.status == "ACTIVE")) == 1
        second = run_control_jobs(db, limit=1)
        db.commit()
        assert second["privacy"] == first["privacy"]
        assert run_control_jobs(db, limit=1)["privacy"] == {"erased": 0, "held": 0, "transcripts_erased": 0}
