"""Boundary regressions discovered during the v2 handover review."""
from datetime import timedelta
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select

from receptionist.billing import (BudgetInput, ReservationReconcileInput, StatementInput,
    StatementLineInput, expire_unused_reservations, import_statement, mark_cost_started,
    publish_budget, reconcile_reservation, record_vendor_cost, reserve_cost, settle_cost, spending)
from receptionist.config import settings
from receptionist.db import get_db, now_utc
from receptionist.messaging_controls import poll_sms_receipts
from receptionist.models import Appointment, AuditEvent, MessageOutbox, Tenant
from receptionist.models_finance import CostReservation, UsageCharge
from receptionist.models_ops import BillingAdjustment, Invoice
from receptionist.models_ops_control import SMSReceiptPoll
from receptionist.models_privacy import GovernedArtifact
from receptionist.operations import adjustment_reason, router as operations_router
from receptionist.payment_policy import router as payment_policy_router
from receptionist.privacy_controls import expire_artifacts, migrate_legacy_billing_notes
from receptionist.security import Actor, current_actor, decrypt, encrypt
from test_core import create, database as database
from test_finance_privacy_v2 import owner, setup_costs


def test_started_cost_cannot_be_dispatched_twice_and_policy_is_rechecked(database):
    with database() as db:
        setup_costs(db)
        first = reserve_cost(db, "clinic-bahar", "started-once", "speech_primary", "stt_audio_seconds", 7)
        mark_cost_started(db, first["id"])
        db.commit()
        with pytest.raises(HTTPException) as duplicate:
            mark_cost_started(db, first["id"])
        assert duplicate.value.detail["code"] == "COST_ALREADY_STARTED"
        db.rollback()
        second = reserve_cost(db, "clinic-bahar", "lowered-cap", "speech_primary", "stt_audio_seconds", 5)
        db.commit()
        publish_budget(BudgetInput(monthly_cap_toman=10, call_cap_toman=10, operation_cap_toman=10), owner(db), db)
        with pytest.raises(HTTPException) as reduced:
            mark_cost_started(db, second["id"])
        assert reduced.value.detail["code"] == "MONETARY_BUDGET_EXCEEDED"
        db.rollback()
        publish_budget(BudgetInput(enabled=False, monthly_cap_toman=100, call_cap_toman=100, operation_cap_toman=100), owner(db), db)
        with pytest.raises(HTTPException) as disabled:
            mark_cost_started(db, second["id"])
        assert disabled.value.detail["code"] == "MONETARY_POLICY_CHANGED"


def test_only_never_dispatched_cost_expires_and_review_requires_scoped_evidence(database):
    with database() as db:
        setup_costs(db)
        unused = reserve_cost(db, "clinic-bahar", "unused", "speech_primary", "stt_audio_seconds", 3)
        unknown = reserve_cost(db, "clinic-bahar", "unknown", "speech_primary", "stt_audio_seconds", 5)
        mark_cost_started(db, unknown["id"])
        settle_cost(db, unknown["id"], 0, "unknown-provider-timeout", "unknown")
        for key in (unused["id"], unknown["id"]):
            db.get(CostReservation, key).expires_at = now_utc() - timedelta(days=1)
        db.commit()
        assert expire_unused_reservations(db, "clinic-bahar") == 1
        db.commit()
        assert db.get(CostReservation, unused["id"]).status == "EXPIRED"
        assert db.get(CostReservation, unknown["id"]).status == "UNKNOWN"
        payload = ReservationReconcileInput(outcome="no_charge", quantity="0", source_reference="verified-provider-zero",
            evidence_sha256="e" * 64, provider_result_verified=True)
        with pytest.raises(HTTPException) as wrong_tenant:
            reconcile_reservation(unknown["id"], payload, owner(db, "clinic-niloufar"), db)
        assert wrong_tenant.value.status_code == 404
        db.rollback()
        with pytest.raises(HTTPException) as unverified:
            reconcile_reservation(unknown["id"], payload.model_copy(update={"provider_result_verified": False}), owner(db), db)
        assert unverified.value.detail["code"] == "VERIFIED_PROVIDER_RESULT_REQUIRED"
        result = reconcile_reservation(unknown["id"], payload, owner(db), db)
        assert result["status"] == "RELEASED" and result["cost_toman_exact"] == "0"
        assert spending(db, "clinic-bahar")["reserved_micro_toman"] == 0


def test_vendor_statement_does_not_double_charge_inline_receipt_and_ledger_is_immutable(database):
    with database() as db:
        setup_costs(db)
        ticket = reserve_cost(db, "clinic-bahar", "inline-receipt", "speech_primary", "stt_audio_seconds", 10)
        mark_cost_started(db, ticket["id"])
        charge = settle_cost(db, ticket["id"], 5, "original-estimate")
        record_vendor_cost(db, charge["charge_id"], "7", "TOMAN", "native-response-one")
        db.commit()
        statement = import_statement(StatementInput(provider="speech_primary", reference="same-vendor-statement",
            period=now_utc().strftime("%Y-%m"), evidence_sha256="a" * 64,
            lines=[StatementLineInput(reference="same-line", charge_id=charge["charge_id"], meter="stt_audio_seconds",
                quantity="5", unit="second", currency="TOMAN", billed_amount="7", fx_toman_per_currency="1")]), owner(db), db)
        assert statement["lines"][0]["status"] == "MATCHED"
        assert statement["lines"][0]["discrepancy_micro_toman"] == 0
        assert spending(db, "clinic-bahar")["charged_micro_toman"] == 7_000_000
        db.get(UsageCharge, charge["charge_id"]).cost_micro_toman = 0
        with pytest.raises(ValueError, match="append-only"):
            db.flush()
        db.rollback()
        assert db.get(UsageCharge, charge["charge_id"]).cost_micro_toman == 5_000_000


def legacy_notes(db, snapshot=None):
    adjustment = BillingAdjustment(tenant_id="clinic-bahar", period="2026-10", amount_toman=-27,
        reason="Synthetic private billing explanation", idempotency_key="legacy-adjustment")
    db.add(adjustment)
    db.flush()
    invoice = Invoice(tenant_id="clinic-bahar", period="2026-10", amount_toman=973,
        snapshot=snapshot if snapshot is not None else {"subtotal": 1000,
            "adjustments": [{"id": adjustment.id, "amount_toman": -27, "reason": adjustment.reason}]})
    db.add(invoice)
    db.commit()
    return adjustment, invoice


def test_legacy_billing_note_migration_preserves_money_and_is_idempotent(database):
    with database() as db:
        adjustment, invoice = legacy_notes(db)
        result = migrate_legacy_billing_notes(db)
        assert result == {"adjustment_notes_encrypted": 1, "invoice_note_snapshots_encrypted": 1}
        db.commit()
        assert adjustment.amount_toman == -27 and invoice.amount_toman == 973
        assert invoice.snapshot["subtotal"] == 1000
        assert invoice.snapshot["adjustments"][0]["amount_toman"] == -27
        assert invoice.snapshot["adjustments"][0]["id"] == adjustment.id
        assert "Synthetic private" not in json.dumps(invoice.snapshot)
        assert adjustment_reason(db, adjustment) == "Synthetic private billing explanation"
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "billing.legacy_notes_encrypted", AuditEvent.entity_id == invoice.id))
        assert json.loads(decrypt(event.details["adjustments_encrypted"]))[0]["reason"] == "Synthetic private billing explanation"
        assert "Synthetic private" not in json.dumps(event.details)
        assert migrate_legacy_billing_notes(db) == {"adjustment_notes_encrypted": 0, "invoice_note_snapshots_encrypted": 0}


def test_malformed_legacy_invoice_fails_before_any_note_mutation(database):
    with database() as db:
        adjustment, _ = legacy_notes(db, {"adjustments": [{"reason": ["malformed"]}]})
        with pytest.raises(ValueError, match="legacy_invoice_adjustment_requires_manual_review"):
            migrate_legacy_billing_notes(db)
        assert adjustment.reason == "Synthetic private billing explanation"
        assert not db.scalar(select(AuditEvent.id).where(AuditEvent.actor_id == "privacy-migration-v2"))


def test_holds_do_not_starve_expiry_and_disabled_clinic_still_erases(database):
    with database() as db:
        rows = []
        for index in range(3):
            row = GovernedArtifact(tenant_id="clinic-bahar", subject_hash="b" * 64, purpose="qa", policy_version=1,
                kind="qa_sample", idempotency_key=f"retention-{index}", content_sha256="a" * 64,
                payload_encrypted=encrypt("synthetic retained data"), expires_at=now_utc() - timedelta(days=3-index),
                backup_expiry_days=7, created_by="demo-owner",
                hold_until=now_utc() + timedelta(days=1) if index < 2 else None)
            db.add(row)
            rows.append(row)
        db.get(Tenant, "clinic-bahar").active = False
        db.commit()
        result = expire_artifacts(db, limit=1)
        db.commit()
        assert result == {"erased": 1, "held": 2}
        assert rows[2].payload_encrypted is None and rows[2].status == "ERASED"
        assert all(row.payload_encrypted and row.status == "ACTIVE" for row in rows[:2])


@pytest.mark.asyncio
async def test_pending_native_sms_receipt_remains_pending_without_false_delivery(database, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    with database() as db:
        message = db.scalar(select(MessageOutbox).limit(1))
        message.status, message.provider_id = "SENT", "native-pending-fixture"
        db.add(SMSReceiptPoll(tenant_id=message.tenant_id, message_id=message.id))
        db.commit()
        message_id = message.id
    class PendingGateway:
        async def delivery(self, provider_id):
            assert provider_id == "native-pending-fixture"
            return "SENT"
    result = await poll_sms_receipts(database, PendingGateway())
    assert result == {"checked": 1, "delivered": 0, "failed": 0, "errors": 0}
    with database() as db:
        assert db.get(MessageOutbox, message_id).status == "SENT"
        poll = db.get(SMSReceiptPoll, message_id)
        assert poll.last_status == "SENT" and poll.stopped_at is None and poll.attempts == 1


def test_billing_can_read_terms_and_minimal_deposit_choices_without_clinical_fields(database):
    with database() as db:
        appointment = db.get(Appointment, create(db)["id"])
        appointment.deposit_toman, appointment.status = 50000, "PENDING_PAYMENT"
        db.commit()
        appointment_id = appointment.id
    app = FastAPI()
    app.include_router(operations_router)
    app.include_router(payment_policy_router)
    def session():
        with database() as db:
            yield db
    app.dependency_overrides[get_db] = session
    role = {"value": "billing", "tenant": "clinic-bahar"}
    app.dependency_overrides[current_actor] = lambda: Actor("demo-owner", role["tenant"], role["value"], "fixture", "fixture@example.invalid", "fixture")
    with TestClient(app) as client:
        assert client.get("/api/v1/operations/payment-policy").status_code == 200
        response = client.get("/api/v1/operations/payments/appointments?status=PENDING_PAYMENT")
        assert response.status_code == 200
        item = next(row for row in response.json() if row["id"] == appointment_id)
        assert set(item) == {"id", "reference", "deposit_toman", "status"}
        assert "09123456789" not in json.dumps(response.json())
        role["tenant"] = "clinic-niloufar"
        assert all(row["id"] != appointment_id for row in client.get("/api/v1/operations/payments/appointments").json())
        role["value"] = "technical"
        assert client.get("/api/v1/operations/payments/appointments").status_code == 403


def test_durable_alerts_use_actual_safety_names_and_due_backlogs(database):
    from receptionist.models import StaffTask
    from receptionist.models_ops_control import OperationalAlert
    from receptionist.operations import audit
    from receptionist.ops_controls import evaluate_alerts
    with database() as db:
        audit(db, "clinic-bahar", "synthetic-review", "safety.false_confirmation", "fixture", "one")
        audit(db, "clinic-bahar", "synthetic-review", "safety.tenant_exposure", "fixture", "two")
        due = db.scalar(select(MessageOutbox).where(MessageOutbox.tenant_id == "clinic-bahar").limit(1))
        due.status, due.available_at = "QUEUED", now_utc() - timedelta(minutes=4)
        for index in range(5):
            db.add(MessageOutbox(tenant_id="clinic-bahar", recipient_encrypted=encrypt("synthetic"), purpose="confirmation",
                template="fixture", dedupe_key=f"failed-backlog-{index}", status="FAILED", updated_at=now_utc()))
        db.add(StaffTask(tenant_id="clinic-bahar", reason="HUMAN_HANDOFF", summary="Synthetic delayed work", status="CALLBACK", created_at=now_utc() - timedelta(minutes=16)))
        db.commit()
        evaluate_alerts(db, "clinic-bahar")
        db.commit()
        result = list(db.scalars(select(OperationalAlert).where(OperationalAlert.tenant_id == "clinic-bahar")))
        assert sum(row.kind == "SAFETY_REVIEW" for row in result) == 2
        assert {"OUTBOX_DELAY", "STAFF_QUEUE_DELAY", "DELIVERY_FAILURE_BACKLOG"}.issubset({row.kind for row in result})
        before = len(result)
        evaluate_alerts(db, "clinic-bahar")
        db.commit()
        assert len(list(db.scalars(select(OperationalAlert).where(OperationalAlert.tenant_id == "clinic-bahar")))) == before


def test_abandoned_staff_timer_can_be_reviewed_without_valuing_unworked_elapsed_time(database):
    from receptionist.billing import WorkReviewInput, WorkStartInput, review_work, start_work, stop_work
    from receptionist.models_finance import StaffWorkSession
    with database() as db:
        actor = owner(db)
        result = start_work(WorkStartInput(category="REWORK", hourly_rate_toman=600, idempotency_key="abandoned-timer"), actor, db)
        db.get(StaffWorkSession, result["id"]).started_at = now_utc() - timedelta(hours=18)
        db.commit()
        with pytest.raises(HTTPException) as needs_review:
            stop_work(result["id"], actor, db)
        assert needs_review.value.detail["code"] == "WORK_SESSION_REVIEW_REQUIRED"
        db.rollback()
        payload = WorkReviewInput(reviewed_seconds=3600, evidence_reference="verified-timesheet", evidence_sha256="b" * 64, observation_verified=True)
        reviewed = review_work(result["id"], payload, actor, db)
        assert reviewed["seconds"] == 3600 and reviewed["cost_toman_exact"] == "600"
        assert start_work(WorkStartInput(category="RECEPTION", hourly_rate_toman=600, idempotency_key="after-review"), actor, db)["id"] != result["id"]
        with pytest.raises(HTTPException):
            review_work(result["id"], payload, actor, db)


def test_subject_erasure_preserves_only_unfinished_external_calendar_evidence(database):
    from receptionist.models_core import ExternalCalendarOperation
    from receptionist.privacy_controls import erase_subject_extensions
    with database() as db:
        rows = []
        for state in ("SENDING", "UNKNOWN", "FAILED_REVIEW", "CONFIRMED"):
            row = ExternalCalendarOperation(tenant_id="clinic-bahar", authority_version=1, operation="CREATE",
                idempotency_key="erasure-" + state, request_hash="d" * 64, request_encrypted=encrypt('{"private":"synthetic"}'),
                result_encrypted=encrypt('{"remote":"synthetic"}'), status=state, phone_hash="a" * 64, actor_id="demo-owner")
            db.add(row)
            rows.append(row)
        db.commit()
        result = erase_subject_extensions(db, "clinic-bahar", "a" * 64)
        db.commit()
        assert result["external_calendar_review_required"] == 3
        assert all("synthetic" in decrypt(row.request_encrypted) for row in rows[:3])
        assert decrypt(rows[-1].request_encrypted) == "{}" and decrypt(rows[-1].result_encrypted) == "{}"


def test_subject_erasure_preserves_committed_external_inventory_without_direct_contact(database):
    from receptionist.calendar_bridge import list_bookings, operation_view
    from receptionist.models_core import ExternalCalendarOperation
    from receptionist.privacy_controls import erase_subject_extensions
    with database() as db:
        remote = {"id": "remote_one", "account_id": "synthetic_account", "revision": "1", "status": "CONFIRMED",
            "slot_id": "synthetic_slot", "provider_id": "provider-bahar-1", "service_id": "service-consultation",
            "patient_token": "a" * 64, "start_at": (now_utc() + timedelta(days=3)).isoformat(),
            "end_at": (now_utc() + timedelta(days=3, minutes=30)).isoformat(), "reference": "SYNTHETIC-ONE",
            "payment_url": "https://example.invalid/private-token"}
        row = ExternalCalendarOperation(tenant_id="clinic-bahar", authority_version=1, operation="create",
            idempotency_key="erasure-committed", request_hash="d" * 64,
            request_encrypted=encrypt(json.dumps({"patient_name": "Synthetic private name", "phone": "09123456789", "patient_token": "a" * 64})),
            result_encrypted=encrypt(json.dumps(remote)), status="SUCCEEDED", remote_id=remote["id"],
            phone_hash="a" * 64, actor_id="demo-owner")
        db.add(row)
        db.commit()
        result = erase_subject_extensions(db, "clinic-bahar", "a" * 64)
        db.commit()
        assert result["structured_external_records_retained"] == 1
        assert "09123456789" not in decrypt(row.request_encrypted)
        assert "Synthetic private name" not in decrypt(row.request_encrypted)
        assert "payment_url" not in decrypt(row.result_encrypted)
        assert list_bookings(db, "clinic-bahar")[0]["patient_name"] == ""
        assert operation_view(db, row)["booking"]["status"] == "CONFIRMED"
