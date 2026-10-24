#!/usr/bin/env python3
"""Stream PostgreSQL custom archives through GnuPG; no plaintext dump on disk.

Backup uses a reviewed public-key fingerprint. Restore requires an explicitly
acknowledged empty target, then verifies the schema and calendar invariants.
The application encryption key is recovered separately from the backup key.
"""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url


def pg_environment(url: str) -> dict:
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("Backup and restore require PostgreSQL")
    result = dict(os.environ)
    for key, value in {"PGHOST": parsed.query.get("host", parsed.host),
                       "PGPORT": parsed.query.get("port", parsed.port or 5432),
                       "PGUSER": parsed.username, "PGPASSWORD": parsed.password,
                       "PGDATABASE": parsed.database,
                       "PGSSLMODE": parsed.query.get("sslmode", "prefer")}.items():
        if value is not None:
            result[key] = str(value)
    return result


def checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1_048_576):
            digest.update(block)
    return digest.hexdigest()


def publish_once(temporary: Path, output: Path) -> None:
    """Atomically publish on this filesystem without replacing another backup."""
    os.link(temporary, output)
    temporary.unlink()


def inspect_database(url: str, *, empty=False, verify_key=False) -> dict:
    engine = create_engine(url)
    try:
        with engine.connect() as db:
            tables = db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")).scalars().all()
            if empty:
                if tables:
                    raise ValueError("Restore target is not empty; no changes were made")
                return {"empty": True}
            version = db.execute(text("SELECT version FROM schema_version")).scalar()
            from receptionist.migrations import BASELINE_TABLES, SCHEMA_VERSION
            if version not in {"0001", SCHEMA_VERSION}:
                raise ValueError("Unsupported restored schema version")
            from receptionist import model_registry  # noqa: F401
            from receptionist.db import validate_schema
            validate_schema(db, table_names=BASELINE_TABLES if version == "0001" else None)
            counts = {table: db.execute(text('SELECT count(*) FROM "' + table.replace('"','""') + '"')).scalar() for table in tables}
            duplicate_claims = db.execute(text("SELECT count(*) FROM (SELECT 1 FROM occupancy GROUP BY tenant_id,resource_id,minute HAVING count(*) > 1) d")).scalar()
            orphans = db.execute(text("SELECT count(*) FROM occupancy o WHERE (o.owner_type='appointment' AND NOT EXISTS (SELECT 1 FROM appointments a WHERE a.id=o.owner_id AND a.tenant_id=o.tenant_id)) OR (o.owner_type='hold' AND NOT EXISTS (SELECT 1 FROM slot_holds h WHERE h.id=o.owner_id AND h.tenant_id=o.tenant_id))")).scalar()
            if duplicate_claims or orphans:
                raise ValueError("Restored calendar invariant verification failed")
            key_checked = False
            if verify_key:
                from cryptography.fernet import Fernet, MultiFernet
                key = os.environ.get("ENCRYPTION_KEY", "")
                if not key:
                    raise ValueError("Recovered ENCRYPTION_KEY is required for the decryption check")
                encrypted = db.execute(text("SELECT patient_name_encrypted FROM appointments LIMIT 1")).scalar()
                if encrypted:
                    previous = [item.strip() for item in os.environ.get("ENCRYPTION_PREVIOUS_KEYS", "").split(",") if item.strip()]
                    MultiFernet([Fernet(item.encode()) for item in [key, *previous]]).decrypt(encrypted.encode())
                    key_checked = True
            return {"schema_version": version, "table_counts": counts, "duplicate_claims": duplicate_claims,
                    "orphan_claims": orphans, "application_key_checked": key_checked}
    finally:
        engine.dispose()


def backup(url: str, output: Path, recipient: str, *, pg_dump="pg_dump", gpg="gpg") -> dict:
    if not re.fullmatch(r"[A-Fa-f0-9]{40,64}", recipient):
        raise ValueError("Specify the reviewed full GPG key fingerprint")
    if output.exists() or output.with_suffix(output.suffix + ".json").exists():
        raise ValueError("Refusing to overwrite an existing backup")
    state = inspect_database(url)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".backup-", suffix=".partial", dir=output.parent)
    os.close(fd)
    start = time.monotonic()
    producer = consumer = None
    try:
        with tempfile.TemporaryFile() as errors:
            producer = subprocess.Popen([pg_dump, "--format=custom", "--no-owner", "--no-acl"],
                                        env=pg_environment(url), stdout=subprocess.PIPE, stderr=errors)
            consumer = subprocess.Popen([gpg, "--batch", "--yes", "--trust-model", "always", "--recipient", recipient,
                                         "--cipher-algo", "AES256", "--output", temporary, "--encrypt"],
                                         stdin=producer.stdout, stdout=subprocess.DEVNULL, stderr=errors)
            producer.stdout.close()
            if consumer.wait(timeout=3600) != 0 or producer.wait(timeout=60) != 0:
                raise RuntimeError("Backup pipeline failed; temporary encrypted archive discarded")
        os.chmod(temporary, 0o600)
        publish_once(Path(temporary), output)
        manifest = {"format": "pg-custom-gpg-v1", "created_at": datetime.now(UTC).isoformat(),
                    "encrypted_sha256": checksum(output), "bytes": output.stat().st_size,
                    "duration_seconds": round(time.monotonic()-start, 3), "verification_before_backup": state,
                    "recipient_fingerprint": recipient.upper()}
        manifest_path = output.with_suffix(output.suffix + ".json")
        with os.fdopen(os.open(manifest_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
            json.dump(manifest, file, indent=2)
            file.write("\n")
        return manifest
    finally:
        for process in (consumer, producer):
            if process and process.poll() is None:
                process.kill()
                process.wait()
        if Path(temporary).exists():
            Path(temporary).unlink()


def restore(url: str, source: Path, *, pg_restore="pg_restore", gpg="gpg", verify_key=False) -> dict:
    expected = json.loads(source.with_suffix(source.suffix + ".json").read_text())
    if expected.get("format") != "pg-custom-gpg-v1" or checksum(source) != expected["encrypted_sha256"]:
        raise ValueError("Encrypted backup integrity check failed")
    inspect_database(url, empty=True)
    producer = consumer = None
    start = time.monotonic()
    try:
        with tempfile.TemporaryFile() as errors:
            producer = subprocess.Popen([gpg, "--batch", "--decrypt", str(source)], stdout=subprocess.PIPE, stderr=errors)
            consumer = subprocess.Popen([pg_restore, "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl",
                                         "--dbname", make_url(url).database], env=pg_environment(url),
                                         stdin=producer.stdout, stdout=subprocess.DEVNULL, stderr=errors)
            producer.stdout.close()
            if consumer.wait(timeout=3600) != 0 or producer.wait(timeout=60) != 0:
                raise RuntimeError("Restore pipeline failed; isolate the target and inspect privately before retrying")
        state = inspect_database(url, verify_key=verify_key)
        return {"restored": True, "duration_seconds": round(time.monotonic()-start, 3),
                "verification": state, "source_schema": expected["verification_before_backup"]["schema_version"],
                "count_match": state["table_counts"] == expected["verification_before_backup"]["table_counts"],
                "notes": "Count equality is expected for a quiescent drill; a live pg_dump snapshot may differ from the preflight counts."}
    finally:
        for process in (consumer, producer):
            if process and process.poll() is None:
                process.kill()
                process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("backup")
    save.add_argument("--output", type=Path, required=True)
    save.add_argument("--recipient", required=True)
    recover = commands.add_parser("restore")
    recover.add_argument("--source", type=Path, required=True)
    recover.add_argument("--acknowledge-empty-target", action="store_true", required=True)
    recover.add_argument("--verify-application-key", action="store_true")
    args = parser.parse_args()
    url = os.environ.get("BACKUP_DATABASE_URL", "")
    if not url:
        parser.error("BACKUP_DATABASE_URL must be set privately")
    result = backup(url, args.output, args.recipient) if args.command == "backup" else restore(
        url, args.source, verify_key=args.verify_application_key)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
