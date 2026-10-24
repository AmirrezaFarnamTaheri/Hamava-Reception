"""Forward-only versioned schema changes. No table rebuilds or silent drift repair."""
from datetime import timedelta

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from . import model_registry  # noqa: F401
from .db import Base, now_utc, validate_schema

SCHEMA_VERSION = "0002"
BASELINE_TABLES = frozenset("""
appointment_impacts appointment_responses appointments audit_events billing_adjustments
building_contracts call_sessions capacity_releases channel_permissions clinic_profiles consent_grants
correction_records delivery_receipts digest_deliveries digest_destinations disruptions followup_enrollments
idempotency_records invoices media_heartbeats media_registrations memberships message_outbox occupancy
operation_receipts outreach_policies outreach_suppressions partner_credentials partner_voice_threads
payment_adjustments payment_disputes payment_intents policy_revisions practitioners privacy_tombstones
rate_windows refund_ledger refund_reviews services slot_holds staff_tasks task_controls tenant_payment_policies
tenants usage_events users verification_challenges voice_turns waitlist_entries waitlist_offers
""".split())
V2_TABLES = frozenset("""
staff_token_revocations core_policies catalog_facts service_rules package_entitlements package_uses
booking_series routing_revisions routing_bindings integration_capabilities provider_observations calendar_authorities
external_calendar_operations calendar_sync_states calendar_change_receipts sms_conversations
cost_rates monetary_policies cost_reservations usage_charges vendor_statements vendor_statement_lines
transport_events demand_attributions staff_work_sessions staff_time_observations
purpose_policies processor_approvals governed_artifacts erasure_evidence redaction_policies contact_preferences
trace_events operational_alerts oncall_policies alert_deliveries sms_receipt_polls voice_outreach_jobs
""".split())


def upgrade_connection(connection) -> str:
    """Caller owns a transaction. PostgreSQL advisory lock serializes deployment upgrades."""
    if set(Base.metadata.tables) != BASELINE_TABLES | V2_TABLES:
        raise RuntimeError("Mapped schema changed without an explicit versioned migration")
    if connection.dialect.name == "postgresql":
        connection.execute(text("SELECT pg_advisory_xact_lock(47382915)"))
    connection.execute(text("CREATE TABLE IF NOT EXISTS schema_version (version VARCHAR(20) PRIMARY KEY)"))
    versions = connection.execute(text("SELECT version FROM schema_version ORDER BY version")).scalars().all()
    existing = set(inspect(connection).get_table_names())
    if not versions:
        if existing & (BASELINE_TABLES | V2_TABLES):
            raise RuntimeError("Existing unversioned application tables found; refusing to stamp or modify a legacy database")
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name in BASELINE_TABLES])
        connection.execute(text("INSERT INTO schema_version(version) VALUES ('0001')"))
        versions = ["0001"]
    if versions == ["0001"]:
        validate_schema(connection, table_names=BASELINE_TABLES)
        if existing & V2_TABLES:
            raise RuntimeError("Unversioned v2 tables already exist; refusing to overwrite or silently repair a partial migration")
        Base.metadata.create_all(connection, tables=[table for table in Base.metadata.sorted_tables if table.name in V2_TABLES], checkfirst=False)
        # v1 scheduling used this local database as its technical authority. Preserve
        # that provenance without asserting approval of any clinical/price facts.
        authority = Base.metadata.tables["calendar_authorities"]
        approved_at = now_utc()
        tenant_ids = connection.execute(text("SELECT id FROM tenants ORDER BY id")).scalars().all()
        for tenant_id in tenant_ids:
            connection.execute(authority.insert().values(
                tenant_id=tenant_id, kind="internal", provider_key="internal_calendar", version=1,
                capabilities={key: True for key in ("read", "hold", "create", "cancel", "update", "atomic_conflict", "readback")},
                approved_by="migration:v1-local-authority", approved_at=approved_at,
                expires_at=approved_at + timedelta(days=365), connector_revision="internal-v1",
            ))
        # Preserve financial amounts and invoice evidence while removing legacy
        # plaintext free text. The helper flushes into this migration transaction.
        from .privacy_controls import migrate_legacy_billing_notes
        with Session(bind=connection, join_transaction_mode="rollback_only") as session:
            migrate_legacy_billing_notes(session)
        connection.execute(text("UPDATE schema_version SET version=:version WHERE version='0001'"), {"version": SCHEMA_VERSION})
    elif versions != [SCHEMA_VERSION]:
        raise RuntimeError("Unrecognized schema version; refusing automatic downgrade")
    validate_schema(connection)
    return SCHEMA_VERSION


def migrate(engine) -> str:
    with engine.connect() as connection:
        try:
            if connection.dialect.name == "sqlite":
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            version = upgrade_connection(connection)
            connection.commit()
            return version
        except BaseException:
            connection.rollback()
            raise
