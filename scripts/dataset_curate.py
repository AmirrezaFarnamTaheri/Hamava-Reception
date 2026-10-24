#!/usr/bin/env python3
"""Validate rights metadata, redact PCM spans, freeze and revalidate a dataset.

This validates recorded evidence, not legal sufficiency or true anonymization.
No audio or transcript is sent to an external service. Reports contain counts,
reason codes and hashed sample references, never raw rejected content.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from pathlib import Path
from typing import Any

try:
    from .research_common import canonical_json, read_jsonl, safe_reference, sha256, write_json
except ImportError:
    from research_common import canonical_json, read_jsonl, safe_reference, sha256, write_json

HASH_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,95}$")


def utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timezone_aware_timestamp_required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid_timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone_aware_timestamp_required")
    return parsed.astimezone(timezone.utc)


def read_tombstones(path: Path) -> dict[str, set[str]]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise ValueError("tombstone_registry_unreadable") from exc
    expected = {"sample_ids", "speaker_ids", "tenant_ids"}
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError("invalid_tombstone_registry")
    for identifiers in value.values():
        if not isinstance(identifiers, list) or any(not isinstance(i, str) for i in identifiers):
            raise ValueError("invalid_tombstone_registry")
    return {key: set(value[key]) for key in expected}


def validate_rights(sample: dict[str, Any], *, now: datetime, region: str,
                    tombstones: dict[str, set[str]]) -> None:
    for key in ("sample_id", "speaker_id", "tenant_id"):
        value = sample.get(key)
        if not isinstance(value, str) or not ID_RE.fullmatch(value):
            raise ValueError("pseudonymous_identifiers_required")
        if value in tombstones[key + "s"]:
            raise ValueError("withdrawn")
    rights = sample.get("rights")
    if not isinstance(rights, dict):
        raise ValueError("rights_missing")
    for flag in ("recording", "training", "clinic_authorized"):
        if rights.get(flag) is not True:
            raise ValueError(f"right_{flag}_missing")
    for key in ("license_id", "consent_version"):
        if not isinstance(rights.get(key), str) or not rights[key].strip():
            raise ValueError(f"{key}_missing")
    if not HASH_RE.fullmatch(str(rights.get("consent_evidence_sha256", ""))):
        raise ValueError("consent_evidence_hash_missing")
    allowed = rights.get("allowed_regions")
    if not isinstance(allowed, list) or region not in allowed:
        raise ValueError("processing_region_not_permitted")
    if utc(rights.get("expires_at")) <= now:
        raise ValueError("rights_expired")
    recorded = utc(sample.get("recorded_at"))
    if recorded > now or recorded >= utc(rights["expires_at"]):
        raise ValueError("invalid_collection_time")
    review = sample.get("privacy_review")
    if not isinstance(review, dict) or not review.get("reviewer") or review.get("approved") is not True:
        raise ValueError("privacy_review_required")
    reviewed_at = utc(review.get("approved_at"))
    if not recorded <= reviewed_at <= now:
        raise ValueError("invalid_review_time")
    for key in ("audio_sha256", "transcript_sha256"):
        if not HASH_RE.fullmatch(str(review.get(key, ""))):
            raise ValueError("reviewed_content_hash_required")


def resolve_under(root: Path, value: str) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError("audio_path_required")
    root = root.resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("audio_path_outside_input_root_or_missing")
    return path


def wav_info(blob: bytes) -> dict[str, Any]:
    """Parse uncompressed RIFF PCM while preserving all bytes outside data spans."""
    if len(blob) < 44 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise ValueError("pcm_riff_wave_required")
    if struct.unpack_from("<I", blob, 4)[0] + 8 != len(blob):
        raise ValueError("invalid_riff_size")
    offset, fmt, data, chunks, metadata_safe = 12, None, None, [], True
    while offset + 8 <= len(blob):
        kind = blob[offset:offset + 4]
        length = struct.unpack_from("<I", blob, offset + 4)[0]
        start, end = offset + 8, offset + 8 + length
        if end > len(blob):
            raise ValueError("truncated_wave_chunk")
        chunks.append(kind)
        if kind == b"fmt ":
            if fmt is not None or length not in (16, 18):
                raise ValueError("invalid_wave_format_chunk")
            fmt = struct.unpack_from("<HHIIHH", blob, start)
            if length == 18 and blob[start + 16:end] != b"\0\0":
                metadata_safe = False
        elif kind == b"data":
            if data is not None:
                raise ValueError("multiple_audio_data_chunks_not_supported")
            data = (start, length)
        elif kind != b"JUNK" or any(blob[start:end]):
            # Nonzero padding may itself contain identifying metadata.
            metadata_safe = False
        offset = end + (length % 2)
    if offset != len(blob) or fmt is None or data is None:
        raise ValueError("incomplete_wave_structure")
    encoding, channels, rate, byte_rate, block_align, bits = fmt
    if encoding != 1 or channels not in (1, 2) or bits not in (8, 16, 24, 32):
        raise ValueError("unsupported_pcm_format")
    if rate not in (8000, 12000, 16000, 24000, 32000, 44100, 48000, 96000, 192000):
        raise ValueError("unsupported_sample_rate")
    if block_align != channels * bits // 8 or byte_rate != rate * block_align or data[1] % block_align:
        raise ValueError("invalid_pcm_alignment")
    frames = data[1] // block_align
    return {"sample_rate": rate, "channels": channels, "bits": bits,
            "block_align": block_align, "frames": frames, "data_offset": data[0], "data_bytes": data[1],
            "duration_ms": Decimal(frames) * 1000 / rate, "chunks": chunks,
            "metadata_safe": metadata_safe}


def redact_wav_bytes(blob: bytes, spans: list[list[Any]]) -> tuple[bytes, dict[str, Any]]:
    info = wav_info(blob)
    if not isinstance(spans, list):
        raise ValueError("redaction_spans_must_be_list")
    result = bytearray(blob)
    covered: list[tuple[int, int]] = []
    for span in spans:
        if not isinstance(span, list) or len(span) != 2:
            raise ValueError("redaction_span_requires_start_end_ms")
        try:
            start, end = (Decimal(str(x)) for x in span)
        except Exception as exc:
            raise ValueError("invalid_redaction_span") from exc
        if not start.is_finite() or not end.is_finite() or not 0 <= start < end <= info["duration_ms"]:
            raise ValueError("redaction_span_out_of_bounds")
        first = int((start * info["sample_rate"] / 1000).to_integral_value(rounding=ROUND_FLOOR))
        last = int((end * info["sample_rate"] / 1000).to_integral_value(rounding=ROUND_CEILING))
        begin = info["data_offset"] + first * info["block_align"]
        finish = info["data_offset"] + last * info["block_align"]
        result[begin:finish] = (b"\x80" if info["bits"] == 8 else b"\0") * (finish - begin)
        covered.append((first, last))
    # Audio byte boundaries, not file rewriting, preserve metadata and all other audio.
    info["redaction_frame_ranges"] = covered
    return bytes(result), info


def assign_splits(samples: list[dict[str, Any]], *, seed: int = 42) -> dict[str, str]:
    """Connected components enforce BOTH speaker and tenant disjointness."""
    parent = list(range(len(samples)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    seen: dict[tuple[str, str], int] = {}
    for i, sample in enumerate(samples):
        for field in ("speaker_id", "tenant_id"):
            key = (field, sample[field])
            if key in seen:
                parent[find(i)] = find(seen[key])
            else:
                seen[key] = i
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for i, sample in enumerate(samples):
        groups[find(i)].append(sample)
    if len(groups) < 3:
        raise ValueError("at_least_three_disjoint_speaker_tenant_components_required")
    components = sorted(groups.values(), key=lambda group: (-len(group), sha256(canonical_json([seed, sorted(s["sample_id"] for s in group)]))))
    counts = {"train": 0, "validation": 0, "test": 0}
    targets = {"train": .8 * len(samples), "validation": .1 * len(samples), "test": .1 * len(samples)}
    assigned: dict[str, str] = {}
    for index, group in enumerate(components):
        split = ("train", "validation", "test")[index] if index < 3 else min(counts, key=lambda name: counts[name] / targets[name])
        counts[split] += len(group)
        for sample in group:
            assigned[sample["sample_id"]] = split
    return assigned


def _prepare_sample(sample: dict[str, Any], *, root: Path, now: datetime, region: str,
                    tombstones: dict[str, set[str]]) -> tuple[dict[str, Any], bytes]:
    validate_rights(sample, now=now, region=region, tombstones=tombstones)
    transcript = sample.get("transcript")
    if not isinstance(transcript, str) or not transcript.strip() or len(transcript) > 8000:
        raise ValueError("reviewed_transcript_required")
    transcript_hash = sha256(transcript.encode("utf-8"))
    if sample["privacy_review"]["transcript_sha256"] != transcript_hash:
        raise ValueError("transcript_changed_after_review")
    path = resolve_under(root, sample.get("audio_path"))
    if path.stat().st_size > 12_000_000:
        raise ValueError("audio_too_large_for_segment")
    source = path.read_bytes()
    if sample.get("source_sha256") != sha256(source):
        raise ValueError("source_hash_mismatch")
    redacted, info = redact_wav_bytes(source, sample.get("redaction_spans_ms", []))
    if not info["metadata_safe"]:
        raise ValueError("unreviewed_wave_metadata_chunks")
    if not 3000 <= info["duration_ms"] <= 15000:
        raise ValueError("segment_duration_must_be_3_to_15_seconds")
    audio_hash = sha256(redacted)
    if sample["privacy_review"]["audio_sha256"] != audio_hash:
        raise ValueError("audio_changed_after_review")
    clean = {key: sample[key] for key in ("sample_id", "speaker_id", "tenant_id", "rights", "recorded_at", "privacy_review")}
    clean.update({"source_sha256": sha256(source), "audio_sha256": audio_hash,
                  "audio_path": f"audio/{safe_reference(sample['sample_id'])}.wav",
                  "transcript": transcript, "transcript_sha256": transcript_hash,
                  "sample_rate": info["sample_rate"], "channels": info["channels"],
                  "duration_ms": str(info["duration_ms"]), "synthetic": sample.get("synthetic") is True,
                  "redaction_frame_ranges": [list(p) for p in info["redaction_frame_ranges"]]})
    return clean, redacted


def freeze_dataset(input_path: Path, output_dir: Path, *, tombstone_path: Path, region: str,
                   now: datetime | None = None, seed: int = 42) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone_aware_clock_required")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("output_directory_must_be_new_or_empty")
    rows = read_jsonl(input_path)
    tombstones = read_tombstones(tombstone_path)
    tombstone_hash = sha256(canonical_json({k: sorted(v) for k, v in tombstones.items()}))
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    rejected, accepted = [], []
    seen_ids, seen_source, seen_output = set(), set(), set()
    with tempfile.TemporaryDirectory(prefix="curation-", dir=output_dir.parent) as staging:
        stage = Path(staging)
        (stage / "audio").mkdir()
        for row in rows:
            try:
                sample, blob = _prepare_sample(row, root=input_path.parent, now=now, region=region, tombstones=tombstones)
                if sample["sample_id"] in seen_ids or sample["source_sha256"] in seen_source or sample["audio_sha256"] in seen_output:
                    raise ValueError("duplicate_sample_or_audio")
                seen_ids.add(sample["sample_id"])
                seen_source.add(sample["source_sha256"])
                seen_output.add(sample["audio_sha256"])
                (stage / sample["audio_path"]).write_bytes(blob)
                accepted.append(sample)
            except (ValueError, OSError) as exc:
                reason = str(exc) if isinstance(exc, ValueError) else "audio_input_error"
                rejected.append({"sample_ref": safe_reference(str(row.get("sample_id", "missing"))), "reason": reason})
        split_map = assign_splits(accepted, seed=seed)
        for sample in accepted:
            sample["split"] = split_map[sample["sample_id"]]
        current_tombstones = read_tombstones(tombstone_path)
        if current_tombstones != tombstones:
            raise ValueError("withdrawal_registry_changed_during_freeze")
        manifest = {"schema_version": "1.0", "created_at": now.isoformat(), "processing_region": region,
                    "evidence_class": "metadata_checked_not_legal_approval", "seed": seed,
                    "requested_split_ratios": {"train": .8, "validation": .1, "test": .1},
                    "split_counts": {name: sum(s["split"] == name for s in accepted) for name in ("train", "validation", "test")},
                    "tombstones_sha256_at_freeze": tombstone_hash,
                    "input_manifest_sha256": sha256(input_path.read_bytes()),
                    "synthetic_only": all(s["synthetic"] for s in accepted), "samples": accepted}
        manifest["manifest_sha256"] = sha256(canonical_json(manifest))
        write_json(manifest, stage / "manifest.json")
        report = {"accepted": len(accepted), "rejected": len(rejected), "rejections": rejected,
                  "split_counts": manifest["split_counts"], "synthetic_only": manifest["synthetic_only"],
                  "manifest_sha256": manifest["manifest_sha256"],
                  "limitations": ["Group-disjoint splits may differ substantially from target ratios on small corpora.",
                                  "Metadata checks do not prove legal consent, voice anonymity or transcription correctness.",
                                  "Manifest checksum detects accidental changes; it is not a cryptographic signer identity."]}
        write_json(report, stage / "report.json")
        # A failed curation never leaves a partly published dataset.
        os.replace(stage, output_dir)
    return report


def revalidate_manifest(manifest_path: Path, *, tombstone_path: Path, region: str,
                        now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("timezone_aware_clock_required")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    recorded_hash = manifest.get("manifest_sha256")
    unsigned = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if recorded_hash != sha256(canonical_json(unsigned)):
        raise ValueError("manifest_checksum_mismatch")
    if manifest.get("schema_version") != "1.0" or manifest.get("processing_region") != region:
        raise ValueError("manifest_version_or_region_mismatch")
    samples = manifest.get("samples")
    if not isinstance(samples, list) or not samples:
        raise ValueError("empty_frozen_manifest")
    tombstones = read_tombstones(tombstone_path)
    groups: dict[tuple[str, str], set[str]] = defaultdict(set)
    hashes, sample_ids = set(), set()
    for sample in samples:
        validate_rights(sample, now=now, region=region, tombstones=tombstones)
        if sample.get("split") not in {"train", "validation", "test"}:
            raise ValueError("invalid_split")
        for field in ("speaker_id", "tenant_id"):
            groups[(field, sample[field])].add(sample["split"])
        blob = resolve_under(manifest_path.parent, sample.get("audio_path")).read_bytes()
        if sha256(blob) != sample.get("audio_sha256") or sha256(blob) != sample["privacy_review"]["audio_sha256"]:
            raise ValueError("frozen_audio_changed")
        info = wav_info(blob)
        if info["sample_rate"] != sample.get("sample_rate") or info["channels"] != sample.get("channels"):
            raise ValueError("frozen_audio_metadata_mismatch")
        transcript_hash = sha256(sample["transcript"].encode("utf-8"))
        if transcript_hash != sample.get("transcript_sha256") or transcript_hash != sample["privacy_review"]["transcript_sha256"]:
            raise ValueError("frozen_transcript_changed")
        if sample["audio_sha256"] in hashes or sample["sample_id"] in sample_ids:
            raise ValueError("duplicate_frozen_sample")
        hashes.add(sample["audio_sha256"])
        sample_ids.add(sample["sample_id"])
    if any(len(splits) > 1 for splits in groups.values()):
        raise ValueError("cross_split_speaker_or_tenant_leakage")
    if read_tombstones(tombstone_path) != tombstones:
        raise ValueError("withdrawal_registry_changed_during_validation")
    return {"valid": True, "samples": len(samples), "manifest_sha256": recorded_hash,
            "synthetic_only": manifest.get("synthetic_only") is True,
            "split_counts": {name: sum(s["split"] == name for s in samples) for name in ("train", "validation", "test")},
            "evidence_class": "metadata_and_content_integrity_checked_not_legal_approval"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("input", type=Path)
    freeze.add_argument("output", type=Path)
    freeze.add_argument("--tombstones", type=Path, required=True)
    freeze.add_argument("--region", required=True)
    freeze.add_argument("--seed", type=int, default=42)
    validate = commands.add_parser("revalidate")
    validate.add_argument("manifest", type=Path)
    validate.add_argument("--tombstones", type=Path, required=True)
    validate.add_argument("--region", required=True)
    redact = commands.add_parser("redact")
    redact.add_argument("input", type=Path)
    redact.add_argument("output", type=Path)
    redact.add_argument("--spans", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "freeze":
            result = freeze_dataset(args.input, args.output, tombstone_path=args.tombstones, region=args.region, seed=args.seed)
        elif args.command == "revalidate":
            result = revalidate_manifest(args.manifest, tombstone_path=args.tombstones, region=args.region)
        else:
            if args.output.exists():
                raise ValueError("redaction_output_must_not_exist")
            blob, info = redact_wav_bytes(args.input.read_bytes(), json.loads(args.spans.read_text()))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(blob)
            result = {"sha256": sha256(blob), "frames": info["frames"], "redacted_ranges": len(info["redaction_frame_ranges"]),
                      "review_required": True, "voice_anonymity_not_established": True}
        write_json(result)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Curation refused: {str(exc) if isinstance(exc, ValueError) else 'invalid_input_or_io_error'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
