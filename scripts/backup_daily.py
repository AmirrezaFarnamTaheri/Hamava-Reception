#!/usr/bin/env python3
"""Noninteractive scheduler entry; retention is a separately approved policy."""
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
from backup import backup, checksum


def prune(directory: Path, days: int, *, apply=False, legal_hold=False, now=None) -> dict:
    """Remove only expired, checksummed archives produced by this scheduler."""
    if not 1 <= days <= 3650:
        raise ValueError("Retention must be explicitly set between 1 and 3650 days")
    cutoff = (now or datetime.now(UTC))-timedelta(days=days)
    result = {"eligible": 0, "deleted": 0, "invalid_pairs_preserved": 0, "legal_hold": legal_hold}
    for manifest in directory.glob("hamava-*.dump.gpg.json"):
        archive = manifest.with_suffix("")
        try:
            data = json.loads(manifest.read_text())
            created = datetime.fromisoformat(data["created_at"])
            if (data.get("format") != "pg-custom-gpg-v1" or created.tzinfo is None
                    or not archive.is_file() or archive.is_symlink() or manifest.is_symlink()
                    or checksum(archive) != data["encrypted_sha256"]):
                raise ValueError("Unverified archive pair")
            if created < cutoff:
                result["eligible"] += 1
                if apply and not legal_hold:
                    archive.unlink()
                    manifest.unlink()
                    result["deleted"] += 1
        except (OSError, ValueError, KeyError, TypeError):
            result["invalid_pairs_preserved"] += 1
    return result

if __name__ == "__main__":
    name = datetime.now(UTC).strftime("hamava-%Y%m%dT%H%M%SZ.dump.gpg")
    result = backup(os.environ["BACKUP_DATABASE_URL"], Path(os.environ["BACKUP_DIRECTORY"]) / name,
                    os.environ["BACKUP_GPG_RECIPIENT"])
    retention = None
    if os.getenv("BACKUP_RETENTION_DAYS"):
        retention = prune(Path(os.environ["BACKUP_DIRECTORY"]), int(os.environ["BACKUP_RETENTION_DAYS"]),
                          apply=os.getenv("BACKUP_DELETE_EXPIRED", "false").lower() == "true",
                          legal_hold=os.getenv("BACKUP_LEGAL_HOLD", "false").lower() == "true")
    print(json.dumps({"backup": name, "bytes": result["bytes"], "sha256": result["encrypted_sha256"], "retention": retention}))
