"""Real upgrade boundaries: preserve old records, refuse drift and roll back failures."""
import pytest
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from receptionist.db import Base, make_engine
from receptionist.migrations import BASELINE_TABLES, V2_TABLES, SCHEMA_VERSION, migrate
from receptionist.models import Tenant
from receptionist.models_ops import BillingAdjustment, Invoice


def baseline(engine):
    with engine.begin() as db:
        Base.metadata.create_all(db, tables=[t for t in Base.metadata.sorted_tables if t.name in BASELINE_TABLES])
        db.execute(text("CREATE TABLE schema_version (version VARCHAR(20) PRIMARY KEY)"))
        db.execute(text("INSERT INTO schema_version VALUES ('0001')"))
    with Session(engine) as db:
        db.add(Tenant(id="upgrade-clinic", name="Existing clinic", slug="upgrade-clinic"))
        db.commit()


def test_fresh_migration_and_repeat_are_explicit_and_idempotent(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    try:
        assert migrate(engine) == SCHEMA_VERSION
        assert migrate(engine) == SCHEMA_VERSION
        with engine.connect() as db:
            assert set(inspect(db).get_table_names()) == BASELINE_TABLES | V2_TABLES | {"schema_version"}
            assert db.execute(text("SELECT version FROM schema_version")).scalars().all() == [SCHEMA_VERSION]
    finally:
        engine.dispose()


def test_v1_records_survive_and_technical_authority_does_not_invent_clinical_approval(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'old.db'}")
    try:
        baseline(engine)
        assert migrate(engine) == SCHEMA_VERSION
        with engine.connect() as db:
            assert db.execute(text("SELECT name FROM tenants WHERE id='upgrade-clinic'")).scalar_one() == "Existing clinic"
            assert db.execute(text("SELECT kind FROM calendar_authorities WHERE tenant_id='upgrade-clinic'")).scalar_one() == "internal"
            assert db.execute(text("SELECT approved_by FROM calendar_authorities")).scalar_one() == "migration:v1-local-authority"
            assert db.execute(text("SELECT count(*) FROM catalog_facts")).scalar_one() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("damage", ["missing_column", "partial_v2", "unknown_version", "unversioned"])
def test_upgrade_refuses_ambiguous_or_damaged_existing_schema(tmp_path, damage):
    engine = make_engine(f"sqlite:///{tmp_path / (damage + '.db')}")
    try:
        baseline(engine)
        with engine.begin() as db:
            if damage == "missing_column":
                db.execute(text("ALTER TABLE users DROP COLUMN name"))
            elif damage == "partial_v2":
                Base.metadata.tables["cost_rates"].create(db)
            elif damage == "unknown_version":
                db.execute(text("UPDATE schema_version SET version='9999'"))
            else:
                db.execute(text("DELETE FROM schema_version"))
        with pytest.raises(RuntimeError):
            migrate(engine)
        with engine.connect() as db:
            assert db.execute(text("SELECT name FROM tenants")).scalar_one() == "Existing clinic"
            assert "catalog_facts" not in inspect(db).get_table_names()
    finally:
        engine.dispose()


def test_failed_v2_validation_rolls_back_all_new_tables_and_version(tmp_path, monkeypatch):
    import receptionist.migrations as module
    engine = make_engine(f"sqlite:///{tmp_path / 'rollback.db'}")
    original = module.validate_schema
    try:
        baseline(engine)
        def fail_final(connection, **options):
            if options.get("table_names") is None:
                raise RuntimeError("synthetic final validation failure")
            original(connection, **options)
        monkeypatch.setattr(module, "validate_schema", fail_final)
        with pytest.raises(RuntimeError, match="synthetic"):
            migrate(engine)
        with engine.connect() as db:
            assert db.execute(text("SELECT version FROM schema_version")).scalar_one() == "0001"
            assert not (set(inspect(db).get_table_names()) & V2_TABLES)
    finally:
        engine.dispose()


def test_v1_upgrade_encrypts_legacy_notes_without_changing_financial_evidence(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'financial-upgrade.db'}")
    try:
        baseline(engine)
        with Session(engine) as db:
            db.add(BillingAdjustment(id="legacy-adjustment", tenant_id="upgrade-clinic", period="2026-10",
                amount_toman=-100, reason="Synthetic confidential billing note", idempotency_key="legacy-adjustment"))
            db.add(Invoice(id="legacy-invoice", tenant_id="upgrade-clinic", period="2026-10", amount_toman=900,
                snapshot={"subtotal": 1000, "adjustments": [{"id": "legacy-adjustment", "amount_toman": -100,
                    "reason": "Synthetic confidential billing note"}]}))
            db.commit()
        migrate(engine)
        migrate(engine)
        with Session(engine) as db:
            adjustment = db.get(BillingAdjustment, "legacy-adjustment")
            invoice = db.get(Invoice, "legacy-invoice")
            assert adjustment.amount_toman == -100 and invoice.amount_toman == 900
            assert adjustment.reason == "encrypted_audit_evidence"
            assert invoice.snapshot["adjustments"][0]["id"] == "legacy-adjustment"
            assert invoice.snapshot["adjustments"][0]["reason"] == "authorized_billing_adjustment"
            from receptionist.models import AuditEvent
            from receptionist.security import decrypt
            from sqlalchemy import select
            evidence = db.scalars(select(AuditEvent).where(AuditEvent.actor_id == "privacy-migration-v2")).all()
            assert len(evidence) == 2
            assert any(decrypt(row.details["reason_encrypted"]) == "Synthetic confidential billing note"
                       for row in evidence if "reason_encrypted" in row.details)
    finally:
        engine.dispose()


def test_invalid_legacy_invoice_rolls_back_schema_and_preserves_original_data(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'invalid-invoice.db'}")
    try:
        baseline(engine)
        with Session(engine) as db:
            db.add(Invoice(id="invalid-invoice", tenant_id="upgrade-clinic", period="2026-10",
                amount_toman=900, snapshot={"adjustments": "unknown legacy structure"}))
            db.commit()
        with pytest.raises(ValueError, match="requires_manual_review"):
            migrate(engine)
        with engine.connect() as db:
            assert db.execute(text("SELECT version FROM schema_version")).scalar_one() == "0001"
            assert not (set(inspect(db).get_table_names()) & V2_TABLES)
            assert db.execute(text("SELECT amount_toman FROM invoices")).scalar_one() == 900
    finally:
        engine.dispose()
