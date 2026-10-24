#!/usr/bin/env python3
"""Offline, resumable ciphertext-key rotation with a stable lookup HMAC key.

Load the NEW ENCRYPTION_KEY, the previous keys in ENCRYPTION_PREVIOUS_KEYS, and
the unchanged LOOKUP_HASH_KEY privately. First run without --apply. Stop all
application/media/job processes before applying. Keep the old keys available
until every table verifies, a new backup restores, and old backups expire.
"""
from __future__ import annotations
import argparse
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlalchemy import JSON, select, update

from receptionist import model_registry  # noqa: F401 -- include every encrypted v2 field
from receptionist.config import settings
from receptionist.db import Base, engine, validate_schema


def rotate(engine, current_key: str, previous_keys: list[str], *, apply=False) -> dict:
    current = Fernet(current_key.encode())
    ring = MultiFernet([current, *[Fernet(key.encode()) for key in previous_keys]])
    result = {"applied": apply, "rows_needing_rotation": 0, "fields_needing_rotation": 0,
              "nested_fields_needing_rotation": 0, "tables": {}, "lookup_hashes_changed": False}

    def ciphertext(value):
        if value is None:
            return value, 0
        if not isinstance(value, str):
            raise ValueError("An encrypted field has an unsupported value type")
        try:
            current.decrypt(value.encode())
            return value, 0
        except InvalidToken:
            # Invalid/unknown-key ciphertext fails this table's transaction.
            return current.encrypt(ring.decrypt(value.encode())).decode(), 1

    def nested(value, *, outbox_payload=False):
        if isinstance(value, dict):
            replaced, changed = {}, 0
            for key, item in value.items():
                protected = key.endswith("_encrypted") or key == "encrypted" or (outbox_payload and key == "secret")
                replacement, count = ciphertext(item) if protected else nested(item, outbox_payload=outbox_payload)
                replaced[key] = replacement
                changed += count
            return replaced, changed
        if isinstance(value, list):
            replaced, changed = [], 0
            for item in value:
                replacement, count = nested(item, outbox_payload=outbox_payload)
                replaced.append(replacement)
                changed += count
            return replaced, changed
        return value, 0
    with engine.connect() as connection:
        validate_schema(connection)
    # A table is one transaction. Interruption leaves mixed keys decryptable by
    # the explicit ring; rerunning skips already-current ciphertext.
    for table in Base.metadata.sorted_tables:
        encrypted = [column for column in table.columns if column.name.endswith("_encrypted")]
        structured = [column for column in table.columns if isinstance(column.type, JSON)]
        if not encrypted and not structured:
            continue
        if len(table.primary_key.columns) != 1:
            raise ValueError("Rotation requires an explicitly supported single-column primary key")
        primary = next(iter(table.primary_key.columns))
        count = 0
        with engine.begin() as connection:
            rows = connection.execute(select(primary, *encrypted, *structured)).mappings()
            for row in rows:
                changes = {}
                changed_fields = nested_fields = 0
                for column in encrypted:
                    replacement, amount = ciphertext(row[column.name])
                    if amount:
                        changes[column.name] = replacement
                        changed_fields += amount
                for column in structured:
                    replacement, amount = nested(row[column.name], outbox_payload=table.name == "message_outbox" and column.name == "payload")
                    if amount:
                        changes[column.name] = replacement
                        changed_fields += amount
                        nested_fields += amount
                if changes:
                    count += 1
                    result["rows_needing_rotation"] += 1
                    result["fields_needing_rotation"] += changed_fields
                    result["nested_fields_needing_rotation"] += nested_fields
                    if apply:
                        connection.execute(update(table).where(primary == row[primary.name]).values(**changes))
        result["tables"][table.name] = count
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--acknowledge-offline-tested-backup", action="store_true")
    args = parser.parse_args()
    if not settings.lookup_hash_key or len(settings.lookup_hash_key) < 32:
        parser.error("An explicit, unchanged LOOKUP_HASH_KEY is required; never replace it during ciphertext rotation")
    if not settings.previous_encryption_keys:
        parser.error("ENCRYPTION_PREVIOUS_KEYS must contain the existing key(s)")
    if args.apply and not args.acknowledge_offline_tested_backup:
        parser.error("Applying requires stopped writers and an independently tested recoverable backup")
    result = rotate(engine, settings.encryption_key, settings.previous_encryption_keys, apply=args.apply)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
