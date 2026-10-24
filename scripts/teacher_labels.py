#!/usr/bin/env python3
"""Compare offline teacher hypotheses and validate explicit human adjudication.

Inputs stay local. Agreement is not ground truth; no provider is called, no audio
is copied, and no transcript is printed or published by this tool. Existing
frozen samples must pass current rights, withdrawal and content validation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from itertools import combinations
import json
import os
from pathlib import Path
import re

try:
    from .dataset_curate import revalidate_manifest, utc
    from .research_common import canonical_json, digit_groups, edit_distance, normalize_text, sha256
except ImportError:
    from dataset_curate import revalidate_manifest, utc
    from research_common import canonical_json, digit_groups, edit_distance, normalize_text, sha256

MAX_SAMPLES = 500
MAX_FILE_BYTES = 16_000_000
TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_.:/-]{0,127}$")
HASH = re.compile(r"^[0-9a-f]{64}$")


def require(condition, code):
    if not condition:
        raise ValueError("teacher_" + code)


def keys(value, expected, code):
    require(isinstance(value, dict) and set(value) == set(expected), code)


def token(value):
    return isinstance(value, str) and TOKEN.fullmatch(value) is not None


def hash_value(value):
    return isinstance(value, str) and HASH.fullmatch(value) is not None


def read_object(path):
    require(path.is_file() and path.stat().st_size <= MAX_FILE_BYTES, "input_size_or_file")
    content = path.read_bytes()
    require(len(content) <= MAX_FILE_BYTES, "input_size_or_file")
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate_json_key")
            value[key] = item
        return value

    try:
        result = json.loads(content, object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("teacher_invalid_json") from exc
    require(isinstance(result, dict), "object_required")
    return result, sha256(content)


def bounded_text(value):
    require(isinstance(value, str) and len(value) <= 2000, "invalid_transcript")
    require(len(normalize_text(value).split()) <= 256, "transcript_token_limit")
    require(not any(ord(c) < 32 and c not in "\t\r\n" for c in value), "transcript_control_character")
    return value


def current_clock(now):
    now = now or datetime.now(timezone.utc)
    require(now.tzinfo is not None and now.utcoffset() is not None, "aware_clock_required")
    return now


def load_inputs(manifest_path, teacher_paths, *, tombstone_path, region, now):
    require(2 <= len(teacher_paths) <= 5, "two_to_five_independent_teachers_required")
    manifest, manifest_file_hash = read_object(manifest_path)
    require(isinstance(manifest.get("samples"), list) and 1 <= len(manifest["samples"]) <= MAX_SAMPLES,
            "sample_limit")
    # This gate precedes reading any hypothesis file. It also verifies the
    # frozen audio/transcript hashes, privacy review and disjoint partitions.
    validation = revalidate_manifest(manifest_path, tombstone_path=tombstone_path, region=region, now=now)
    samples = {row["sample_id"]: row for row in manifest["samples"]}
    inputs = {str(manifest_path): manifest_file_hash, str(tombstone_path): sha256(tombstone_path.read_bytes())}
    teachers, ids, groups, systems = [], set(), set(), set()
    for path in teacher_paths:
        value, file_hash = read_object(path)
        keys(value, ("schema_version", "manifest_sha256", "generated_at", "teacher", "outputs"), "artifact_schema")
        require(value["schema_version"] == "1.0" and value["manifest_sha256"] == validation["manifest_sha256"],
                "artifact_manifest_mismatch")
        generated = utc(value["generated_at"])
        require(generated <= now, "future_teacher_output")
        teacher = value["teacher"]
        keys(teacher, ("id", "system", "revision", "independence_group", "processing_region", "approval"), "identity_schema")
        require(all(token(teacher[k]) for k in ("id", "system", "revision", "independence_group")), "identity_invalid")
        identity = (teacher["system"], teacher["revision"])
        require(teacher["id"] not in ids and teacher["independence_group"] not in groups and identity not in systems,
                "independence_not_distinct")
        ids.add(teacher["id"])
        groups.add(teacher["independence_group"])
        systems.add(identity)
        require(teacher["processing_region"] == region, "processing_region_not_permitted")
        approval = teacher["approval"]
        keys(approval, ("reviewer_id", "independence_attested", "license_evidence_sha256", "processing_evidence_sha256",
                        "issued_at", "expires_at"), "approval_schema")
        require(token(approval["reviewer_id"]) and approval["independence_attested"] is True
                and hash_value(approval["license_evidence_sha256"]) and hash_value(approval["processing_evidence_sha256"]),
                "approval_evidence_required")
        require(utc(approval["issued_at"]) <= generated < utc(approval["expires_at"]) and now < utc(approval["expires_at"]),
                "approval_expired_or_invalid")
        rows = value["outputs"]
        require(isinstance(rows, list) and len(rows) <= len(samples), "output_count")
        outputs = {}
        for row in rows:
            keys(row, ("sample_id", "audio_sha256", "text"), "output_schema")
            sample_id = row["sample_id"]
            require(isinstance(sample_id, str) and sample_id in samples and sample_id not in outputs, "unknown_or_duplicate_sample")
            sample = samples[sample_id]
            require(row["audio_sha256"] == sample["audio_sha256"], "output_audio_hash_mismatch")
            require(utc(sample["recorded_at"]) <= generated < utc(sample["rights"]["expires_at"]), "output_collection_time")
            outputs[sample_id] = bounded_text(row["text"])
        ref = sha256(canonical_json(teacher))
        teachers.append({"ref": ref, "artifact_sha256": file_hash, "generated_at": generated.isoformat(), "outputs": outputs})
        require(str(path) not in inputs, "duplicate_input_file")
        inputs[str(path)] = file_hash
    return manifest, validation, teachers, inputs


def unchanged(inputs, manifest_path, *, tombstone_path, region, now):
    require(all(sha256(Path(path).read_bytes()) == expected for path, expected in inputs.items()), "input_changed_during_review")
    revalidate_manifest(manifest_path, tombstone_path=tombstone_path, region=region, now=now)


def comparison_record(manifest, validation, teachers, inputs, *, created_at):
    records = []
    for index, sample in enumerate(manifest["samples"]):
        sample_id = sample["sample_id"]
        sample_ref = sha256(canonical_json([validation["manifest_sha256"], sample_id]))
        hypotheses, pairs = [], []
        for teacher in teachers:
            text = teacher["outputs"].get(sample_id)
            hypotheses.append({"teacher_ref": teacher["ref"], "status": "missing" if text is None else "provided",
                               "text_sha256": None if text is None else sha256(text.encode("utf-8"))})
        for left, right in combinations(teachers, 2):
            a, b = left["outputs"].get(sample_id), right["outputs"].get(sample_id)
            if a is None or b is None:
                continue
            aa, bb = normalize_text(a).split(), normalize_text(b).split()
            distance = edit_distance(aa, bb)
            pairs.append({"teacher_refs": [left["ref"], right["ref"]], "exact_agreement": a == b,
                          "normalized_agreement": aa == bb, "digit_group_agreement": digit_groups(a) == digit_groups(b),
                          "word_edit_distance": distance, "symmetric_word_disagreement": distance / max(len(aa), len(bb), 1)})
        flags = []
        if any(h["status"] == "missing" for h in hypotheses):
            flags.append("teacher_missing")
        if any(not p["normalized_agreement"] for p in pairs):
            flags.append("teacher_disagreement")
        if any(not p["digit_group_agreement"] for p in pairs):
            flags.append("digit_disagreement")
        if any(not normalize_text(t["outputs"].get(sample_id, "")) for t in teachers if sample_id in t["outputs"]):
            flags.append("empty_teacher_output")
        records.append({"sample_ref": sample_ref, "manifest_sample_index": index, "audio_sha256": sample["audio_sha256"],
                        "hypotheses": hypotheses, "teacher_evidence_sha256": sha256(canonical_json(hypotheses)),
                        "pairs": pairs, "flags": flags, "human_adjudication_required": True})
    report = {"schema_version": "1.0", "created_at": created_at.isoformat(), "manifest_sha256": validation["manifest_sha256"],
              "synthetic_only": validation["synthetic_only"], "input_file_sha256": sorted(inputs.values()),
              "teachers": [{k: t[k] for k in ("ref", "artifact_sha256", "generated_at")} for t in teachers],
              "samples": records, "sample_count": len(records),
              "disagreement_samples": sum("teacher_disagreement" in r["flags"] for r in records),
              "review_flagged_samples": sum(bool(r["flags"]) for r in records),
              "compared_samples": sum(bool(r["pairs"]) for r in records),
              "missing_hypotheses": sum(h["status"] == "missing" for r in records for h in r["hypotheses"]),
              "complete_teacher_coverage": all("teacher_missing" not in r["flags"] for r in records),
              "agreement_is_ground_truth": False, "training_ready": False,
              "limitations": ["System/group distinctions and rights evidence are operator attestations, not independently verified teacher independence or legal approval.",
                              "Pairwise disagreement is symmetric hypothesis comparison, not WER against a reference and not proof of accuracy.",
                              "All samples require a separate human decision, including identical or missing teacher outputs.",
                              "No audio/transcript is copied, no model/provider is invoked, and no corpus is changed or promoted."]}
    report["comparison_sha256"] = sha256(canonical_json(report))
    return report


def write_private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(canonical_json(value) + b"\n")


def compare_teachers(manifest_path, teacher_paths, output_dir, *, tombstone_path, region, now=None):
    now = current_clock(now)
    manifest, validation, teachers, inputs = load_inputs(manifest_path, teacher_paths, tombstone_path=tombstone_path, region=region, now=now)
    report = comparison_record(manifest, validation, teachers, inputs, created_at=now)
    template = {"schema_version": "1.0", "comparison_sha256": report["comparison_sha256"], "manifest_sha256": validation["manifest_sha256"],
                "reviewer": {"reviewer_id": "REQUIRED", "human_review": False, "independent_review": False,
                             "qualification_evidence_sha256": None, "authority_evidence_sha256": None},
                "adjudications": [{"sample_ref": r["sample_ref"], "audio_sha256": r["audio_sha256"],
                                  "teacher_evidence_sha256": r["teacher_evidence_sha256"], "decision": "pending",
                                  "reason": None, "reviewed_at": None, "listened_to_audio": False, "privacy_reviewed": False,
                                  "privacy_evidence_sha256": None, "transcript": None, "transcript_sha256": None} for r in report["samples"]]}
    unchanged(inputs, manifest_path, tombstone_path=tombstone_path, region=region, now=now)
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    try:
        write_private_json(output_dir / "comparison.json", report)
        write_private_json(output_dir / "adjudication-template.json", template)
    except Exception:
        for name in ("comparison.json", "adjudication-template.json"):
            (output_dir / name).unlink(missing_ok=True)
        output_dir.rmdir()
        raise
    return report


def validate_adjudication(manifest_path, teacher_paths, comparison_path, adjudication_path, *, tombstone_path, region, now=None):
    now = current_clock(now)
    manifest, validation, teachers, inputs = load_inputs(manifest_path, teacher_paths, tombstone_path=tombstone_path, region=region, now=now)
    comparison, comparison_file_hash = read_object(comparison_path)
    created = utc(comparison.get("created_at"))
    require(created <= now and all(utc(t["generated_at"]) <= created for t in teachers), "comparison_time")
    expected = comparison_record(manifest, validation, teachers, inputs, created_at=created)
    require(comparison == expected, "comparison_or_inputs_changed")
    artifact, artifact_file_hash = read_object(adjudication_path)
    keys(artifact, ("schema_version", "comparison_sha256", "manifest_sha256", "reviewer", "adjudications"), "adjudication_schema")
    require(artifact["schema_version"] == "1.0" and artifact["comparison_sha256"] == comparison["comparison_sha256"]
            and artifact["manifest_sha256"] == validation["manifest_sha256"], "adjudication_binding")
    reviewer = artifact["reviewer"]
    keys(reviewer, ("reviewer_id", "human_review", "independent_review", "qualification_evidence_sha256", "authority_evidence_sha256"), "reviewer_schema")
    require(token(reviewer["reviewer_id"]) and reviewer["reviewer_id"] != "REQUIRED" and reviewer["human_review"] is True
            and reviewer["independent_review"] is True and hash_value(reviewer["qualification_evidence_sha256"])
            and hash_value(reviewer["authority_evidence_sha256"]), "human_reviewer_evidence_required")
    rows = artifact["adjudications"]
    require(isinstance(rows, list) and len(rows) == len(comparison["samples"]), "all_samples_require_adjudication")
    originals = {r["sample_ref"]: r for r in comparison["samples"]}
    results, seen = [], set()
    for row in rows:
        keys(row, ("sample_ref", "audio_sha256", "teacher_evidence_sha256", "decision", "reason", "reviewed_at", "listened_to_audio",
                   "privacy_reviewed", "privacy_evidence_sha256", "transcript", "transcript_sha256"), "adjudication_row_schema")
        ref = row["sample_ref"]
        require(isinstance(ref, str) and ref in originals and ref not in seen, "unknown_or_duplicate_adjudication")
        seen.add(ref)
        original = originals[ref]
        require(row["audio_sha256"] == original["audio_sha256"] and row["teacher_evidence_sha256"] == original["teacher_evidence_sha256"], "adjudication_content_binding")
        require(row["decision"] in {"accept", "exclude"}, "human_decision_required")
        require(created <= utc(row["reviewed_at"]) <= now, "review_time")
        if row["decision"] == "accept":
            text = bounded_text(row["transcript"])
            require(bool(normalize_text(text)), "accepted_transcript_required")
            require(row["listened_to_audio"] is True and row["privacy_reviewed"] is True and hash_value(row["privacy_evidence_sha256"]), "audio_and_privacy_review_required")
            require(row["reason"] in {"listened_confirmed", "listened_corrected"}, "acceptance_reason")
            require(row["transcript_sha256"] == sha256(text.encode("utf-8")), "adjudicated_transcript_hash")
        else:
            require(row["reason"] in {"unintelligible", "overlap", "sensitive_content", "wrong_audio", "insufficient_evidence"}, "exclusion_reason")
            require(row["transcript"] is None and row["transcript_sha256"] is None, "excluded_transcript_must_be_absent")
            require(type(row["listened_to_audio"]) is bool and type(row["privacy_reviewed"]) is bool
                    and (row["privacy_evidence_sha256"] is None or hash_value(row["privacy_evidence_sha256"])), "exclusion_review_metadata")
        results.append({"sample_ref": ref, "decision": row["decision"], "reason": row["reason"], "transcript_sha256": row["transcript_sha256"]})
    inputs[str(comparison_path)] = comparison_file_hash
    inputs[str(adjudication_path)] = artifact_file_hash
    unchanged(inputs, manifest_path, tombstone_path=tombstone_path, region=region, now=now)
    return {"schema_version": "1.0", "valid": True, "validated_at": now.isoformat(), "comparison_sha256": comparison["comparison_sha256"],
            "adjudication_file_sha256": artifact_file_hash, "manifest_sha256": validation["manifest_sha256"], "synthetic_only": validation["synthetic_only"],
            "reviewer_ref": sha256(canonical_json(reviewer)), "accepted": sum(r["decision"] == "accept" for r in results),
            "excluded": sum(r["decision"] == "exclude" for r in results), "all_samples_adjudicated": True, "results": results,
            "ground_truth_automatically_established": False, "training_ready": False,
            "remaining_gates": ["Human identity, qualifications, independence, permissions and actual listening/privacy review are attestations requiring authorized verification.",
                                "Apply any revised labels only through a new privacy-reviewed dataset freeze; revalidate current withdrawals before use.",
                                "This validates artifact integrity and complete recorded decisions, not acoustic truth, real-corpus quality or model superiority."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("compare", "validate-adjudication"):
        command = commands.add_parser(name)
        command.add_argument("manifest", type=Path)
        command.add_argument("--teacher", type=Path, action="append", required=True)
        command.add_argument("--tombstones", type=Path, required=True)
        command.add_argument("--region", required=True)
        command.add_argument("--output", type=Path, required=True)
        if name == "validate-adjudication":
            command.add_argument("--comparison", type=Path, required=True)
            command.add_argument("--adjudication", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "compare":
            result = compare_teachers(args.manifest, args.teacher, args.output, tombstone_path=args.tombstones, region=args.region)
            summary = {k: result[k] for k in ("comparison_sha256", "sample_count", "disagreement_samples", "synthetic_only", "agreement_is_ground_truth", "training_ready")}
        else:
            result = validate_adjudication(args.manifest, args.teacher, args.comparison, args.adjudication,
                                           tombstone_path=args.tombstones, region=args.region)
            write_private_json(args.output, result)
            summary = {k: result[k] for k in ("valid", "accepted", "excluded", "synthetic_only", "ground_truth_automatically_established", "training_ready")}
        print(json.dumps(summary, sort_keys=True))
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        code = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r"[a-z][a-z0-9_]{0,100}", str(exc)) else "invalid_input_or_io_error"
        parser.exit(2, "Teacher review refused: " + code + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
