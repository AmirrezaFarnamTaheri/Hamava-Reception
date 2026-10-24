#!/usr/bin/env python3
"""Authenticated encrypted configuration and key-custody inventory recovery.

No network transfer, secret printing, shell interpolation, overwriting, or
plaintext staging occurs. The separate Fernet backup key must already exist in
a protected file and be recoverable independently of the application database.
"""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat

from cryptography.fernet import Fernet, InvalidToken

MAX_BYTES = 20_000_000
INVENTORY_FIELDS = {"key_id", "purpose", "algorithm", "fingerprint_sha256", "recovery_reference", "owner_role", "last_recovery_drill"}


def key_from_file(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError("backup_key_must_be_regular_private_file")
    value = path.read_bytes().strip()
    try:
        Fernet(value)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_config_backup_key") from exc
    return value


def safe_name(value: str) -> str:
    path = PurePosixPath(value)
    if not value or value == "key-custody-inventory.json" or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts) or "\\" in value or len(value) > 200:
        raise ValueError("unsafe_backup_entry_name")
    if value != str(path) or len(path.parts) > 5:
        raise ValueError("unsafe_backup_entry_name")
    return str(path)


def read_inventory(path: Path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000:
        raise ValueError("invalid_key_inventory")
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ValueError("invalid_key_inventory") from exc
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValueError("invalid_key_inventory")
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != INVENTORY_FIELDS or any(not isinstance(v, str) or not v or len(v) > 200 for v in entry.values()):
            raise ValueError("inventory_requires_metadata_only_no_key_material")
        fingerprint = entry["fingerprint_sha256"]
        if len(fingerprint) != 64 or any(c not in "0123456789abcdef" for c in fingerprint):
            raise ValueError("invalid_key_inventory_fingerprint")
    if len({item["key_id"] for item in entries}) != len(entries):
        raise ValueError("duplicate_key_inventory_id")
    return entries


def exclusive_write(path: Path, data: bytes):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def create_backup(files: dict[str, Path], inventory_path: Path, key_path: Path, output: Path):
    if not 1 <= len(files) <= 100:
        raise ValueError("one_to_one_hundred_config_files_required")
    inventory = read_inventory(inventory_path)
    key = key_from_file(key_path)
    entries, total = [], 0
    for name, source in sorted(files.items()):
        safe_name(name)
        if source.is_symlink() or not source.is_file() or source.resolve() == key_path.resolve():
            raise ValueError("config_source_must_be_regular_file_not_backup_key")
        size = source.stat().st_size
        total += size
        if total > MAX_BYTES:
            raise ValueError("configuration_backup_exceeds_limit")
        blob = source.read_bytes()
        if len(blob) != size:
            raise ValueError("configuration_changed_during_backup")
        entries.append({"name": name, "sha256": hashlib.sha256(blob).hexdigest(), "bytes": len(blob), "data": base64.b64encode(blob).decode()})
    payload = {"schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(), "files": entries,
        "key_custody_inventory": inventory, "separate_backup_key_included": False}
    ciphertext = Fernet(key).encrypt(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    exclusive_write(output, ciphertext)
    return {"encrypted": True, "files": len(entries), "source_bytes": total, "sha256": hashlib.sha256(ciphertext).hexdigest(),
        "key_inventory_entries": len(inventory), "separate_backup_key_included": False, "external_copy": "not_performed"}


def inspect_backup(source: Path, key_path: Path):
    if source.is_symlink() or not source.is_file() or source.stat().st_size > MAX_BYTES * 2:
        raise ValueError("invalid_configuration_backup")
    try:
        payload = json.loads(Fernet(key_from_file(key_path)).decrypt(source.read_bytes()))
    except (InvalidToken, ValueError) as exc:
        raise ValueError("configuration_backup_authentication_failed") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or payload.get("separate_backup_key_included") is not False:
        raise ValueError("unsupported_configuration_backup")
    if not isinstance(payload.get("files"), list) or not 1 <= len(payload["files"]) <= 100:
        raise ValueError("invalid_backup_manifest")
    seen, total = set(), 0
    for entry in payload["files"]:
        if not isinstance(entry, dict) or set(entry) != {"name", "sha256", "bytes", "data"}:
            raise ValueError("invalid_backup_manifest")
        name = safe_name(entry["name"])
        if name in seen:
            raise ValueError("duplicate_backup_entry")
        seen.add(name)
        try:
            blob = base64.b64decode(entry["data"], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError("invalid_backup_content") from exc
        total += len(blob)
        if total > MAX_BYTES or len(blob) != entry["bytes"] or hashlib.sha256(blob).hexdigest() != entry["sha256"]:
            raise ValueError("configuration_backup_hash_mismatch")
    if any(a != b and b.startswith(a + "/") for a in seen for b in seen):
        raise ValueError("backup_file_directory_conflict")
    return payload


def restore_backup(source: Path, key_path: Path, target: Path, *, confirmed=False):
    if not confirmed:
        raise ValueError("explicit_empty_restore_target_confirmation_required")
    payload = inspect_backup(source, key_path)
    if target.is_symlink() or target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError("configuration_restore_target_must_be_empty")
    target.mkdir(mode=0o700, parents=False, exist_ok=True)
    os.chmod(target, 0o700)
    for entry in payload["files"]:
        destination = target / entry["name"]
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        exclusive_write(destination, base64.b64decode(entry["data"], validate=True))
        if stat.S_IMODE(destination.stat().st_mode) != 0o600:
            raise ValueError("restored_file_permissions_invalid")
    exclusive_write(target / "key-custody-inventory.json", json.dumps(payload["key_custody_inventory"], sort_keys=True, indent=2).encode())
    return {"restored_files": len(payload["files"]), "hashes_verified": True, "permissions": "directories0700_files0600",
        "application_started": False, "recovery_drill": "file_recovery_only_application_key_validation_separate"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    backup = sub.add_parser("create")
    backup.add_argument("--file", action="append", required=True, metavar="NAME=PATH")
    backup.add_argument("--inventory", type=Path, required=True)
    backup.add_argument("--key-file", type=Path, required=True)
    backup.add_argument("--output", type=Path, required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("source", type=Path)
    restore.add_argument("--key-file", type=Path, required=True)
    restore.add_argument("--target", type=Path, required=True)
    restore.add_argument("--confirm-empty-target", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "create":
            pairs = [value.split("=", 1) for value in args.file]
            if any(len(pair) != 2 for pair in pairs) or len({pair[0] for pair in pairs}) != len(pairs):
                raise ValueError("unique_named_source_files_required")
            result = create_backup({name: Path(path) for name, path in pairs}, args.inventory, args.key_file, args.output)
        else:
            result = restore_backup(args.source, args.key_file, args.target, confirmed=args.confirm_empty_target)
        print(json.dumps(result, sort_keys=True))
    except (ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, ValueError) else "configuration_backup_io_failure"
        parser.exit(2, message + "\n")


if __name__ == "__main__":
    main()
