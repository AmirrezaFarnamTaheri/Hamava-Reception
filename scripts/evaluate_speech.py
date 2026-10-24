#!/usr/bin/env python3
"""Evaluate supplied Persian ASR/workflow predictions; never invent audio evidence.

JSONL rows need id, reference, hypothesis. Optional metadata includes speaker_id,
tenant_id, split, audio_sha256, slices, latency_ms, expected_entities,
predicted_entities, eligible, task_completed, confirmed_claim,
authoritative_confirmed, handoff_requested and handoff_connected.
"""
from __future__ import annotations

import argparse
import math
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    from .research_common import digit_groups, edit_distance, normalize_text, quantile, read_jsonl, wilson, write_json
except ImportError:
    from research_common import digit_groups, edit_distance, normalize_text, quantile, read_jsonl, wilson, write_json


def split_leakage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count leaked pseudonymous groups without including group identities."""
    result: dict[str, Any] = {"has_split_metadata": any("split" in r for r in rows),
                              "speaker_groups": 0, "tenant_groups": 0, "audio_hashes": 0}
    if not result["has_split_metadata"]:
        result["verified"] = False
        return result
    for key, output in [("speaker_id", "speaker_groups"), ("tenant_id", "tenant_groups"),
                        ("audio_sha256", "audio_hashes")]:
        partitions: dict[str, set[str]] = defaultdict(set)
        for row in rows:
            if row.get("split") not in {"train", "validation", "test"}:
                raise ValueError("invalid_or_missing_split")
            value = row.get(key)
            if key != "audio_sha256" and (not isinstance(value, str) or not value):
                raise ValueError("split_requires_speaker_and_tenant_metadata")
            if value:
                partitions[value].add(row["split"])
        result[output] = sum(len(splits) > 1 for splits in partitions.values())
    result["verified"] = not any(result[k] for k in ("speaker_groups", "tenant_groups", "audio_hashes"))
    result["partitions_present"] = sorted({row["split"] for row in rows})
    result["complete_partition_inventory"] = set(result["partitions_present"]) == {"train", "validation", "test"}
    result["scope"] = "Only supplied rows are audited; unseen model training data is not verified."
    return result


def sample_stats(row: dict[str, Any]) -> dict[str, Any]:
    reference, hypothesis = row.get("reference"), row.get("hypothesis")
    if not isinstance(reference, str) or not isinstance(hypothesis, str):
        raise ValueError("reference_and_hypothesis_must_be_strings")
    if max(len(reference), len(hypothesis)) > 8000:
        raise ValueError("utterance_exceeds_8000_character_limit")
    normalized_ref, normalized_hyp = normalize_text(reference), normalize_text(hypothesis)
    stats: dict[str, Any] = {"samples": 1}
    for prefix, ref, hyp in [("raw", reference, hypothesis), ("normalized", normalized_ref, normalized_hyp)]:
        words_ref, words_hyp = ref.split(), hyp.split()
        chars_ref, chars_hyp = "".join(ref.split()), "".join(hyp.split())
        stats[f"{prefix}_word_errors"] = edit_distance(words_ref, words_hyp)
        stats[f"{prefix}_words"] = len(words_ref)
        stats[f"{prefix}_character_errors"] = edit_distance(chars_ref, chars_hyp)
        stats[f"{prefix}_characters"] = len(chars_ref)
    ref_numbers, hyp_numbers = digit_groups(reference), digit_groups(hypothesis)
    stats["number_samples"] = int(bool(ref_numbers or hyp_numbers))
    stats["number_exact"] = int(bool(ref_numbers or hyp_numbers) and ref_numbers == hyp_numbers)
    stats["empty_reference_samples"] = int(not normalized_ref)
    stats["silence_hallucinations"] = int(not normalized_ref and bool(normalized_hyp))
    stats["eligible"] = int(row.get("eligible") is True)
    stats["completed"] = int(row.get("eligible") is True and row.get("task_completed") is True)
    stats["confirmation_claims"] = int(row.get("confirmed_claim") is True)
    stats["false_confirmations"] = int(row.get("confirmed_claim") is True and row.get("authoritative_confirmed") is False)
    stats["unverified_confirmations"] = int(row.get("confirmed_claim") is True and not isinstance(row.get("authoritative_confirmed"), bool))
    stats["handoffs_requested"] = int(row.get("handoff_requested") is True)
    stats["handoffs_connected"] = int(row.get("handoff_requested") is True and row.get("handoff_connected") is True)
    stats["unverified_task_outcomes"] = int(row.get("eligible") is True and not isinstance(row.get("task_completed"), bool))
    stats["unverified_handoff_outcomes"] = int(row.get("handoff_requested") is True and not isinstance(row.get("handoff_connected"), bool))
    retry = row.get("retry_count")
    if retry is not None and (isinstance(retry, bool) or not isinstance(retry, int) or not 0 <= retry <= 100):
        raise ValueError("invalid_retry_count")
    stats["retry_observed_samples"] = int(retry is not None)
    stats["retry_total"] = retry if retry is not None else 0
    stats["retried_samples"] = int(retry is not None and retry > 0)
    expected, predicted = row.get("expected_entities", {}), row.get("predicted_entities", {})
    if not isinstance(expected, dict) or not isinstance(predicted, dict):
        raise ValueError("entity_maps_required")
    stats["entity_total"] = len(expected)
    stats["entity_exact"] = sum(normalize_text(str(value)) == normalize_text(str(predicted.get(key, "")))
                                 for key, value in expected.items())
    latency = row.get("latency_ms")
    if latency is not None and (isinstance(latency, bool) or not isinstance(latency, (float, int))
                                or not math.isfinite(latency) or latency < 0):
        raise ValueError("invalid_latency_ms")
    stats["latency_ms"] = latency
    stages = row.get("stage_latency_ms", {})
    allowed_stages = {"carrier_connect", "first_audio", "endpointing", "stt", "policy", "calendar", "tts", "transfer", "turn_to_first_audio"}
    if not isinstance(stages, dict) or set(stages) - allowed_stages or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in stages.values()):
        raise ValueError("invalid_stage_latency_ms")
    stats["stage_latency_ms"] = stages
    return stats


def aggregate(stats: list[dict[str, Any]]) -> dict[str, Any]:
    keys = [key for key in stats[0] if key not in {"latency_ms", "stage_latency_ms"}]
    totals = {key: sum(s[key] for s in stats) for key in keys}
    metrics: dict[str, Any] = {"counts": totals}
    for prefix in ("raw", "normalized"):
        metrics[f"{prefix}_wer"] = totals[f"{prefix}_word_errors"] / totals[f"{prefix}_words"] if totals[f"{prefix}_words"] else None
        metrics[f"{prefix}_cer"] = totals[f"{prefix}_character_errors"] / totals[f"{prefix}_characters"] if totals[f"{prefix}_characters"] else None
    for name, numerator, denominator in [
        ("exact_number_accuracy", "number_exact", "number_samples"),
        ("critical_entity_accuracy", "entity_exact", "entity_total"),
        ("task_completion", "completed", "eligible"),
        ("handoff_connection", "handoffs_connected", "handoffs_requested")
    ]:
        metrics[name] = {"rate": totals[numerator] / totals[denominator] if totals[denominator] else None,
                         "numerator": totals[numerator], "denominator": totals[denominator],
                         "wilson_95": wilson(totals[numerator], totals[denominator])}
    values = [s["latency_ms"] for s in stats if s["latency_ms"] is not None]
    metrics["latency_ms"] = {"n": len(values), "p50": quantile(values, .5), "p95": quantile(values, .95), "p99": quantile(values, .99)}
    stages = sorted({stage for sample in stats for stage in sample["stage_latency_ms"]})
    metrics["stage_latency_ms"] = {}
    for stage in stages:
        observed = [sample["stage_latency_ms"][stage] for sample in stats if stage in sample["stage_latency_ms"]]
        metrics["stage_latency_ms"][stage] = {"n": len(observed), "missing": len(stats) - len(observed),
            "p50": quantile(observed, .5), "p95": quantile(observed, .95), "p99": quantile(observed, .99)}
    observed = totals["retry_observed_samples"]
    metrics["retries"] = {"observed_samples": observed, "unknown_samples": len(stats) - observed,
        "total": totals["retry_total"] if observed else None, "mean": totals["retry_total"] / observed if observed else None,
        "retry_rate": totals["retried_samples"] / observed if observed else None}
    return metrics


def bootstrap_wer(rows: list[dict[str, Any]], stats: list[dict[str, Any]], repetitions: int, seed: int) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    use_speakers = all(isinstance(r.get("speaker_id"), str) and r["speaker_id"] for r in rows)
    for index, (row, stat) in enumerate(zip(rows, stats)):
        groups[row["speaker_id"] if use_speakers else str(index)].append(stat)
    clusters = list(groups.values())
    if len(clusters) < 2:
        return {"interval": None, "reason": "fewer_than_two_independent_clusters", "clusters": len(clusters)}
    rng = random.Random(seed)
    values = []
    for _ in range(repetitions):
        chosen = [rng.choice(clusters) for _ in clusters]
        denominator = sum(s["normalized_words"] for group in chosen for s in group)
        if denominator:
            values.append(sum(s["normalized_word_errors"] for group in chosen for s in group) / denominator)
    return {"interval": [quantile(values, .025), quantile(values, .975)] if values else None,
            "method": "percentile_cluster_bootstrap", "cluster_unit": "speaker" if use_speakers else "sample",
            "clusters": len(clusters), "repetitions": repetitions, "seed": seed,
            "assumption": "Clusters are independent and representative; repeated tenants/households may still correlate."}


def evaluate(rows: list[dict[str, Any]], *, repetitions: int = 500, seed: int = 42, strict_splits: bool = True) -> dict[str, Any]:
    if not rows:
        raise ValueError("empty_dataset")
    if not 100 <= repetitions <= 10000:
        raise ValueError("bootstrap_repetitions_must_be_100_to_10000")
    ids = [r.get("id") for r in rows]
    if any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("unique_nonempty_sample_ids_required")
    leakage = split_leakage(rows)
    if strict_splits and leakage["has_split_metadata"] and not leakage["verified"]:
        raise ValueError("cross_split_leakage_detected")
    stats = [sample_stats(row) for row in rows]
    slices: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row, stat in zip(rows, stats):
        labels = row.get("slices", {})
        if not isinstance(labels, dict) or len(labels) > 12:
            raise ValueError("invalid_slice_labels")
        for name, label in labels.items():
            if not isinstance(name, str) or not isinstance(label, str) or len(name) > 48 or len(label) > 64:
                raise ValueError("invalid_slice_label")
            slices[f"{name}:{label}"].append(stat)
    return {"schema_version": "1.0", "sample_count": len(rows),
            "data_kind": "synthetic" if all(r.get("synthetic") is True for r in rows) else "supplied_predictions",
            "release_evidence": "metrics_only; acoustic_quality_not_verified_by_text_predictions",
            "normalization": "NFC, Persian/Arabic digits, Arabic yeh/kaf, diacritics, punctuation and whitespace; no number-word inference; CER excludes whitespace",
            "overall": aggregate(stats), "normalized_wer_bootstrap_95": bootstrap_wer(rows, stats, repetitions, seed),
            "slices": {name: aggregate(group) for name, group in sorted(slices.items())}, "split_audit": leakage,
            "cautions": ["Wilson intervals assume independent Bernoulli observations; entity/number observations may be clustered.",
                         "Missing authoritative confirmation is unverified, not a successful confirmation.",
                         "No raw transcript or patient identifier is included in this report. Slice labels must be approved nonidentifying categories."]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--bootstrap", type=int, default=500)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    try:
        write_json(evaluate(read_jsonl(args.input), repetitions=args.bootstrap, seed=args.seed), args.output)
    except (ValueError, OSError) as exc:
        parser.exit(2, f"Evaluation refused: {str(exc) if isinstance(exc, ValueError) else 'input_output_error'}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
