#!/usr/bin/env python3
"""Deterministic, secret-excluding Hamava SOURCE release archive.

This is not an executable build, Authenticode signature, provider approval or
attestation of the contents of a connected service. Run on a clean checkout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

PRIVATE_DIRECTORIES = {
    ".git", ".venv", ".gradle", ".idea", ".pytest_cache", ".ruff_cache",
    "__pycache__", "node_modules", "artifacts", "dist", "build", "data", "captures",
}
PRIVATE_SUFFIXES = {".exe", ".apk", ".aab", ".pem", ".key", ".p12", ".pfx", ".jks",
                    ".keystore", ".gpg", ".onnx", ".bin", ".sqlite", ".sqlite3", ".db",
                    ".wav", ".mp3", ".flac", ".mp4", ".tsbuildinfo", ".zip"}
PRIVATE_NAMES = {"local.properties", "PACKAGE-MANIFEST.json"}


def _allowed(relative: Path) -> bool:
    if any(part in PRIVATE_DIRECTORIES for part in relative.parts[:-1]):
        return False
    name = relative.name
    if name in PRIVATE_NAMES or name.endswith((".db-shm", ".db-wal")):
        return False
    if name.startswith(".env") and name not in {".env.example", ".env.production.example"}:
        return False
    if name.startswith(".") and name not in {".env.example", ".env.production.example", ".gitignore", ".dockerignore"} and len(relative.parts) == 1:
        return False
    if relative.suffix.lower() in PRIVATE_SUFFIXES:
        # An explicitly synthetic, license-reviewed test waveform is allowed.
        return relative.parts[:3] == ("fixtures", "research", "audio") and relative.suffix.lower() == ".wav"
    return True


def _info(name: str) -> ZipInfo:
    info = ZipInfo(name, (1980, 1, 1, 0, 0, 0))
    info.compress_type = ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    info.create_system = 3
    return info


def package_source(root: Path, destination: Path) -> dict:
    root = root.resolve(strict=True)
    destination = destination.resolve()
    if destination.is_relative_to(root):
        raise ValueError("OUTPUT_INSIDE_SOURCE")
    if not root.is_dir():
        raise ValueError("SOURCE_MUST_BE_DIRECTORY")
    files = []
    for entry in root.rglob("*"):
        if entry.is_symlink() or not entry.is_file():
            continue
        relative = entry.relative_to(root)
        if _allowed(relative):
            if entry.stat().st_size > 32_000_000:
                raise ValueError("OVERSIZED_SOURCE_FILE")
            files.append(relative)
    files.sort(key=lambda path: path.as_posix())
    manifest = {"format": 1, "product": "Hamava Reception", "artifact_kind": "source_only",
                "not_a_signed_or_certified_release": True, "file_count": len(files),
                "files": {path.as_posix(): {"sha256": hashlib.sha256((root/path).read_bytes()).hexdigest(),
                                               "bytes": (root/path).stat().st_size} for path in files}}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for path in files:
            archive.writestr(_info("voice-receptionist/" + path.as_posix()), (root/path).read_bytes(), compresslevel=9)
        data = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
        archive.writestr(_info("voice-receptionist/PACKAGE-MANIFEST.json"), data, compresslevel=9)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest-out", type=Path)
    args = parser.parse_args()
    result = package_source(args.source, args.output)
    if args.manifest_out:
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(json.dumps(result, sort_keys=True, indent=2)+"\n")
    print(f"Source files: {result['file_count']}; SHA256: {hashlib.sha256(args.output.read_bytes()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
