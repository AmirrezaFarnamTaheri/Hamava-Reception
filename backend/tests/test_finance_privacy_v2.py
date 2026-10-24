"""Exact-money, independent consent and durable artifact lifecycle regressions."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from receptionist.billing import (BudgetInput, RateInput, StatementInput, StatementLineInput, ReconcileInput,
    TransportInput, AttributionInput, TimeObservationInput, WorkStartInput, attribute, attribution_report,
    calculate_cost, import_statement, mark_cost_started, outcomes, publish_budget, publish_rate,
    record_time_observation, record_transport, reserve_cost, review_line, router as billing_router,
    settle_cost, spending, start_work, stop_work, time_report)
from receptionist.config import settings
from receptionist.db import get_db, now_utc
from receptionist.models import Appointment, User
from receptionist.models_finance import CostReservation, UsageCharge, StaffWorkSession
from receptionist.models_privacy import ErasureEvidence, GovernedArtifact
from receptionist.privacy_controls import (ArtifactInput, HoldInput, PermissionInput, ProcessorInput, PurposeInput,
    approve_processor, artifact_content, expire_artifacts, hold_artifact, publish_purpose,
    record_permission, redact_text, require_processor, retain_artifact)
from receptionist.security import Actor, actor_for, current_actor, hash_phone
from test_core import create, database as database, slot_for


def owner(db, tenant="clinic-bahar"):
    return actor_for(db, db.get(User, "demo-owner"), tenant)


def setup_costs(db, cap=100, price="1", currency="TOMAN", fx="1", quantum="1", minimum="0"):
    actor = owner(db)
    publish_budget(BudgetInput(monthly_cap_toman=cap, call_cap_toman=cap, operation_cap_toman=cap), actor, db)
    return publish_rate(RateInput(provider="speech_primary", meter="stt_audio_seconds", unit="second",
        currency=currency, price_per_unit=price, fx_toman_per_currency=fx, quantum=quantum, minimum_quantity=minimum,
        evidence_reference="fixture:contract:1", evidence_sha256="a" * 64,
        effective_at=now_utc() - timedelta(days=1), expires_at=now_utc() + timedelta(days=20)), actor, db)


def grant(db, purpose, granted=True, *, version=1, phone="09123456789"):
    return record_permission(PermissionInput(phone=phone, purpose=purpose, granted=granted, policy_version=version,
        evidence_reference="fixture:subject:1", evidence_sha256="b" * 64, method="signed_form", subject_request_confirmed=True), owner(db), db)


def purpose(db, name, enabled=True, days=5):
    return publish_purpose(PurposeInput(purpose=name, enabled=enabled, notice="Independent synthetic fixture purpose notice.",
        retention_days=days, backup_expiry_days=10, consent_valid_days=30, evidence_reference="fixture:policy:1"), owner(db), db)


def test_decimal_quantum_fx_and_minimum_are_exact(database):
    with database() as db:
        rate = setup_costs(db, cap=100000, price="0.000003", currency="USD", fx="70000", quantum="0.1", minimum="1")
        assert calculate_cost(rate, "0.01") == 210000
        assert calculate_cost(rate, "1.11") == 252000
        assert calculate_cost(rate, "0") == 0
        for value in ("NaN", "Infinity", "-1"):
            with pytest.raises(HTTPException):
                calculate_cost(rate, value)


def test_budget_reserves_concurrently_and_never_blindly_releases_unknown(database):
    with database() as db:
        setup_costs(db, cap=10)
    def attempt(key):
        with database() as db:
            try:
                result = reserve_cost(db, "clinic-bahar", key, "speech_primary", "stt_audio_seconds", "7")
                mark_cost_started(db, result["id"])
                db.commit()
                return result["id"]
            except HTTPException as exc:
                db.rollback()
                return exc.detail["code"]
    with ThreadPoolExecutor(2) as executor:
        results = list(executor.map(attempt, ["race-one", "race-two"]))
    assert results.count("MONETARY_BUDGET_EXCEEDED") == 1
    reservation = next(value for value in results if value != "MONETARY_BUDGET_EXCEEDED")
    with database() as db:
        settle_cost(db, reservation, "0", "timeout-one", "unknown")
        db.get(CostReservation, reservation).created_at = now_utc() - timedelta(days=90)
        db.get(CostReservation, reservation).expires_at = now_utc() - timedelta(days=89)
        db.commit()
        assert spending(db, "clinic-bahar")["reserved_micro_toman"] == 7_000_000
        with pytest.raises(HTTPException):
            reserve_cost(db, "clinic-bahar", "race-three", "speech_primary", "stt_audio_seconds", "4")


def test_cost_idempotency_receipts_and_pinned_rates(database):
    with database() as db:
        setup_costs(db)
        first = reserve_cost(db, "clinic-bahar", "one", "speech_primary", "stt_audio_seconds", "10")
        assert reserve_cost(db, "clinic-bahar", "one", "speech_primary", "stt_audio_seconds", "10")["id"] == first["id"]
        with pytest.raises(HTTPException):
            reserve_cost(db, "clinic-bahar", "one", "speech_primary", "stt_audio_seconds", "11")
        db.commit()
        setup_costs(db, price="2")
        mark_cost_started(db, first["id"])
        charged = settle_cost(db, first["id"], "2", "provider-receipt-one")
        assert charged["cost_micro_toman"] == 2_000_000
        assert settle_cost(db, first["id"], "2.0", "provider-receipt-one")["charge_id"] == charged["charge_id"]
        with pytest.raises(HTTPException):
            settle_cost(db, first["id"], "3", "provider-receipt-one")
        db.commit()
        assert db.scalar(select(func.count()).select_from(UsageCharge)) == 1


def test_production_requires_monetary_policy_and_unpriced_is_unknown(database, monkeypatch):
    with database() as db:
        row = reserve_cost(db, "clinic-bahar", "unpriced", "speech_primary", "tts_characters", 5)
        assert row["status"] == "UNPRICED"
        mark_cost_started(db, row["id"])
        assert settle_cost(db, row["id"], 4, "unpriced-result")["cost_micro_toman"] is None
        db.commit()
        monkeypatch.setattr(settings, "environment", "production")
        with pytest.raises(HTTPException) as error:
            reserve_cost(db, "clinic-bahar", "production", "speech_primary", "stt_audio_seconds", 5)
        assert error.value.detail["code"] == "MONETARY_POLICY_REQUIRED"


def test_vendor_reconciliation_adjusts_without_mutating_usage(database):
    with database() as db:
        setup_costs(db)
        ticket = reserve_cost(db, "clinic-bahar", "statement-one", "speech_primary", "stt_audio_seconds", 10)
        mark_cost_started(db, ticket["id"])
        charge = settle_cost(db, ticket["id"], 5, "bill-source-one")
        db.commit()
        payload = StatementInput(provider="speech_primary", reference="vendor-2026-01", period=now_utc().strftime("%Y-%m"),
            evidence_sha256="c" * 64, lines=[StatementLineInput(reference="line-one", charge_id=charge["charge_id"],
                meter="stt_audio_seconds", quantity="5", unit="second", currency="TOMAN", billed_amount="7", fx_toman_per_currency="1")])
        statement = import_statement(payload, owner(db), db)
        assert statement["lines"][0]["status"] == "DISCREPANCY"
        assert statement["lines"][0]["discrepancy_micro_toman"] == 2_000_000
        assert import_statement(payload, owner(db), db)["id"] == statement["id"]
        review_line(statement["lines"][0]["id"], ReconcileInput(action="DISPUTE", evidence_reference="dispute-one", explanation="Synthetic billing dispute for review."), owner(db), db)
        review_line(statement["lines"][0]["id"], ReconcileInput(action="ACCEPT_VENDOR", evidence_reference="resolution-one", explanation="Reviewed vendor charge and accepted documented difference."), owner(db), db)
        assert db.get(UsageCharge, charge["charge_id"]).cost_micro_toman == 5_000_000
        assert spending(db, "clinic-bahar")["charged_micro_toman"] == 7_000_000
        with pytest.raises(HTTPException):
            review_line(statement["lines"][0]["id"], ReconcileInput(action="ACCEPT_VENDOR", evidence_reference="twice", explanation="Attempt to apply the same adjustment twice."), owner(db), db)


def test_transport_denominators_do_not_invent_unobserved_attempts(database):
    with database() as db:
        assert outcomes(None, owner(db), db)["transport"] is None
        for event, stage in [("a", "ATTEMPTED"), ("b", "BUSY"), ("c", "ATTEMPTED"), ("d", "ANSWERED")]:
            record_transport(db, "clinic-bahar", TransportInput(source="synthetic-carrier", event_key=event,
                attempt_key="failed" if event in {"a", "b"} else "answered", stage=stage,
                occurred_at=now_utc(), evidence_reference="fixture:cdr:1"))
        db.commit()
        result = outcomes(None, owner(db), db)
        assert result["transport"]["ATTEMPTED"] == 2
        assert result["transport"]["ANSWERED"] == 1 and result["transport"]["BUSY"] == 1


def test_attribution_counts_distinct_episodes_and_waitlist_is_not_new_demand(database):
    with database() as db:
        first, second = create(db), create(db, slot_for(db, index=1), key="second-observed-demand")
        for appointment in (first, second):
            db.get(Appointment, appointment["id"]).status = "ATTENDED"
            db.commit()
            attribute(AttributionInput(appointment_id=appointment["id"], episode_reference="same-request-not-phone",
                channel="ai", classification="NEW_DEMAND", evidence_reference="reviewed-cohort-one"), owner(db), db)
        result = attribution_report(None, owner(db), db)
        assert result["observed_new_demand_kept_episodes"] == 1 and result["causal_incremental_kept"] is None
        with pytest.raises(HTTPException):
            attribute(AttributionInput(appointment_id=first["id"], episode_reference="bad-new-demand",
                channel="waitlist", classification="NEW_DEMAND", evidence_reference="unacceptable-double-count"), owner(db), db)


def test_time_saved_deducts_observed_supervision_and_avoids_reassignment_cash_claim(database):
    with database() as db:
        actor = owner(db)
        work = start_work(WorkStartInput(category="SUPERVISION", hourly_rate_toman=600, idempotency_key="work-one"), actor, db)
        with pytest.raises(HTTPException):
            start_work(WorkStartInput(category="REWORK", hourly_rate_toman=600, idempotency_key="overlap"), actor, db)
        row = db.get(StaffWorkSession, work["id"])
        row.started_at = now_utc() - timedelta(minutes=30)
        db.commit()
        stop_work(row.id, actor, db)
        record_time_observation(TimeObservationInput(period=now_utc().strftime("%Y-%m"), released_minutes=120,
            avoidable_minutes=60, reassigned_minutes=60, hourly_rate_toman=600,
            evidence_reference="time-study-one", evidence_sha256="d" * 64), actor, db)
        result = time_report(None, actor, db)
        assert result["avoidable_value_micro_toman"] == 600_000_000
        assert Decimal(result["net_avoidable_value_micro_toman"]) <= 300_000_000
        assert result["reassigned_minutes"] == 60 and result["coverage_complete"] is False


def test_processor_requires_current_region_and_independent_cross_border(database, monkeypatch):
    with database() as db:
        monkeypatch.setattr(settings, "environment", "production")
        with pytest.raises(HTTPException):
            require_processor(db, "clinic-bahar", "speech_primary", "processing", "IR")
        approve_processor(ProcessorInput(provider_key="speech_primary", enabled=True, purposes=["processing"], regions=["IR", "EU"],
            retention_days=0, fallback_eligible=False, contract_reference="synthetic-reviewed-contract", contract_sha256="e" * 64,
            expires_at=now_utc() + timedelta(days=30)), owner(db), db)
        assert require_processor(db, "clinic-bahar", "speech_primary", "processing", "IR")["version"] == 1
        with pytest.raises(HTTPException):
            require_processor(db, "clinic-bahar", "speech_primary", "processing", "IR", is_fallback=True)
        with pytest.raises(HTTPException):
            require_processor(db, "clinic-bahar", "speech_primary", "processing", "EU", hash_phone("09123456789"))
        purpose(db, "cross_border")
        grant(db, "cross_border")
        assert require_processor(db, "clinic-bahar", "speech_primary", "processing", "EU", hash_phone("09123456789"))["region"] == "EU"
        grant(db, "cross_border", False)
        with pytest.raises(HTTPException):
            require_processor(db, "clinic-bahar", "speech_primary", "processing", "EU", hash_phone("09123456789"))


def test_independent_artifact_permissions_expiry_and_backup_truth(database):
    with database() as db:
        actor = owner(db)
        for p in ("processing", "training", "qa"):
            purpose(db, p)
        grant(db, "processing")
        with pytest.raises(HTTPException):
            retain_artifact(ArtifactInput(phone="09123456789", purpose="training", kind="research_export", payload="synthetic text", idempotency_key="training-one"), actor, db)
        grant(db, "qa")
        result = retain_artifact(ArtifactInput(phone="09123456789", purpose="qa", kind="qa_sample", payload="sensitive synthetic QA", idempotency_key="qa-one"), actor, db)
        artifact = db.get(GovernedArtifact, result["id"])
        assert "sensitive" not in artifact.payload_encrypted
        grant(db, "qa", False)
        with pytest.raises(HTTPException):
            artifact_content(artifact.id, actor, db)
        assert expire_artifacts(db)["erased"] == 1
        db.commit()
        db.refresh(artifact)
        assert artifact.payload_encrypted is None and artifact.status == "ERASED"
        evidence = db.scalar(select(ErasureEvidence).where(ErasureEvidence.object_id == artifact.id))
        assert evidence.backup_status == "PENDING_EXPIRY" and evidence.backup_delete_by > now_utc()


def test_hold_prevents_erasure_but_not_unauthorized_access_and_stale_notice(database):
    with database() as db:
        actor = owner(db)
        purpose(db, "qa")
        grant(db, "qa")
        result = retain_artifact(ArtifactInput(phone="09123456789", purpose="qa", kind="qa_sample", payload="held", idempotency_key="held-one"), actor, db)
        hold_artifact(result["id"], HoldInput(evidence_reference="documented-hold-one", hold_until=now_utc() + timedelta(days=1)), actor, db)
        grant(db, "qa", False)
        assert expire_artifacts(db)["held"] == 1
        with pytest.raises(HTTPException):
            artifact_content(result["id"], actor, db)
        purpose(db, "qa")
        with pytest.raises(HTTPException):
            grant(db, "qa", version=1)


def test_redaction_covers_governed_terms_identifiers_without_logging_original():
    text = "علی رضایی سرطان خیابان نمونه ۰۹۱۲۳۴۵۶۷۸۹ ۱۲۳۴۵۶۷۸۹۰ 6037991234567890 IR123456789012345678901234"
    result = redact_text(text, {"names": ["علی رضایی"], "health_terms": ["سرطان"], "addresses": ["خیابان نمونه"]})
    assert all(value not in result for value in ("علی رضایی", "سرطان", "خیابان نمونه", "09123456789", "1234567890", "6037991234567890"))
    assert "[BANK_ACCOUNT]" in result and "[PHONE]" in result


def test_finance_permissions_do_not_grant_billing_role_privacy_or_technical_cost_access(database):
    app = FastAPI()
    app.include_router(billing_router)
    from receptionist.privacy_controls import router as privacy_router
    app.include_router(privacy_router)
    def session():
        with database() as db:
            yield db
    app.dependency_overrides[get_db] = session
    role = {"value": "billing"}
    app.dependency_overrides[current_actor] = lambda: Actor("demo-owner", "clinic-bahar", role["value"], "fixture", "fixture@example.invalid", "fixture")
    with TestClient(app) as client:
        assert client.get("/api/v1/operations/costs").status_code == 200
        assert client.get("/api/v1/operations/privacy-controls/purposes").status_code == 403
        role["value"] = "technical"
        assert client.get("/api/v1/operations/costs").status_code == 403
        assert client.get("/api/v1/operations/privacy-controls/processors").status_code == 200
        assert "09123456789" not in json.dumps(client.get("/api/v1/operations/privacy-controls/processors").json())
