#!/usr/bin/env python3
"""Exercise production startup/migration gates in a disposable PostgreSQL schema.

Requires an explicitly isolated TEST_DATABASE_URL. Creates and drops only its
own random schema. It never starts a public listener or calls a supplier.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def run(url: str) -> dict:
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("An isolated PostgreSQL test database is required")
    schema = "hamava_gate_"+uuid4().hex
    engine = create_engine(url)
    with engine.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    project = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env.update({"ENVIRONMENT": "production", "DEMO_MODE": "false", "RUN_WORKER": "false",
                "DATABASE_URL": parsed.update_query_dict({"options": "-csearch_path="+schema}).render_as_string(hide_password=False),
                "JWT_SECRET": secrets.token_urlsafe(48), "ENCRYPTION_KEY": Fernet.generate_key().decode(),
                "LOOKUP_HASH_KEY": secrets.token_urlsafe(48), "ENCRYPTION_PREVIOUS_KEYS": "",
                "CORS_ORIGINS": "https://reception.example.test", "SMS_PROVIDER_APPROVED": "false",
                "SPEECH_PROCESSOR_APPROVED": "false", "PAYMENT_PROVIDER_APPROVED": "false",
                "LIVEKIT_APPROVED": "false", "DIGEST_PROCESSOR_APPROVED": "false"})
    checks = {}
    def execute(arguments, overrides=None):
        return subprocess.run([sys.executable, *arguments], cwd=project, env=env | (overrides or {}),
                              capture_output=True, text=True, timeout=60)
    try:
        first = execute(["scripts/migrate.py"])
        checks["fresh_versioned_schema"] = first.returncode == 0
        second = execute(["scripts/migrate.py"])
        checks["repeat_migration_is_idempotent"] = second.returncode == 0
        startup = execute(["-c", """
import json
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from receptionist.main import app
from receptionist.db import SessionLocal
from receptionist.models import Tenant, User
with TestClient(app) as client:
    health = client.get('/health')
    no_demo = client.post('/api/v1/auth/login', json={'email':'owner@example.test','password':'DemoReception2026!'})
    with SessionLocal() as db:
        count = db.scalar(select(func.count()).select_from(Tenant))
        users = db.scalar(select(func.count()).select_from(User))
    assert health.status_code == 200 and health.json()['mode'] == 'configured'
    assert count == 0 and users == 0 and no_demo.status_code == 401
    assert health.headers['Strict-Transport-Security'].startswith('max-age=')
    print(json.dumps({'ready':True,'synthetic_accounts_seeded':False,'demo_login_rejected':True,'https_headers':True}))
"""])
        checks["production_starts_without_demo_accounts"] = startup.returncode == 0
        for name, override in {
            "demo_mode_rejected": {"DEMO_MODE": "true"},
            "development_secret_rejected": {"JWT_SECRET": "development-only-change-this-secret-before-production-2026"},
            "missing_lookup_key_rejected": {"LOOKUP_HASH_KEY": ""},
            "insecure_origins_rejected": {"CORS_ORIGINS": "http://example.test"},
        }.items():
            result = execute(["-c", "from receptionist.config import settings; settings.validate()"], override)
            checks[name] = result.returncode != 0
        # Only this disposable schema is altered; all source databases remain untouched.
        with engine.begin() as db:
            db.execute(text(f'ALTER TABLE "{schema}".users DROP COLUMN name'))
        drift = execute(["-c", """
from fastapi.testclient import TestClient
from receptionist.main import app
with TestClient(app):
    pass
"""])
        checks["missing_column_blocks_startup"] = drift.returncode != 0 and "missing columns users: name" in drift.stderr
        drift_migration = execute(["scripts/migrate.py"])
        checks["baseline_migration_does_not_silently_repair_drift"] = drift_migration.returncode != 0
        # An unversioned legacy table is also never stamped as this release.
        with engine.begin() as db:
            db.execute(text(f'DELETE FROM "{schema}".schema_version'))
        legacy = execute(["scripts/migrate.py"])
        checks["unversioned_existing_data_rejected"] = legacy.returncode != 0 and "Existing unversioned" in legacy.stderr
        report = {"synthetic_only": True, "database": "isolated PostgreSQL schema", "checks": checks,
                  "passed": all(checks.values()), "public_listener_started": False,
                  "limits": "Local configuration/migration/startup checks; no container build, public deployment or supplier/customer approval."}
        if not report["passed"]:
            report["failed_checks"] = [name for name, passed in checks.items() if not passed]
        return report
    finally:
        with engine.begin() as db:
            db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-isolated-test-database", action="store_true", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        parser.error("Set TEST_DATABASE_URL privately")
    report = run(url)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps(report))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
