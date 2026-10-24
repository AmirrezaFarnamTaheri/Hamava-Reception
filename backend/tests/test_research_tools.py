"""Research gates and measurement semantics; no external models or services."""
# ruff: noqa: E402 -- standalone CLI modules are imported after their explicit path bootstrap.
from __future__ import annotations

import copy
import io
import json
import struct
import sys
import wave
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))

from dataset_curate import (assign_splits, freeze_dataset, redact_wav_bytes,
                            revalidate_manifest, wav_info)
from economics import evaluate_economics, scenario_report, to_toman
from evaluate_speech import evaluate
from make_synthetic_fixtures import make_fixtures, tone_bytes
from pilot_analysis import analyze_pilot
from research_common import normalize_text, read_jsonl, sha256, wilson
from train_asr import validate_recipe

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def research_input(tmp_path):
    root = tmp_path / "inputs"
    make_fixtures(root)
    return root


def rewrite_input(root: Path, rows: list[dict]) -> None:
    (root / "manifest-input.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n")


def freeze(root: Path, output: Path):
    return freeze_dataset(root / "manifest-input.jsonl", output, tombstone_path=root / "withdrawals.json", region="local-test", now=NOW)


def rows_for_metrics():
    return [{"id": "one", "reference": "الف ب ج د", "hypothesis": "الف ب ج ه", "speaker_id": "speaker_a"},
            {"id": "two", "reference": "الف ب ج د", "hypothesis": "الف ب ج د", "speaker_id": "speaker_b"}]


def test_persian_normalization_preserves_identifier_zeros():
    assert normalize_text("يک كد ۰۱۲٣؛ پنج‌شنبه") == "یک کد 0123 پنج شنبه"


def test_wer_is_micro_averaged_and_bootstrap_reproducible():
    result = evaluate(rows_for_metrics(), repetitions=100)
    assert result["overall"]["normalized_wer"] == .125
    assert result["normalized_wer_bootstrap_95"] == evaluate(rows_for_metrics(), repetitions=100)["normalized_wer_bootstrap_95"]


def test_wer_can_exceed_one_on_insertions():
    result = evaluate([{"id": "one", "reference": "الف", "hypothesis": "ب ج د ه"}], repetitions=100)
    assert result["overall"]["normalized_wer"] == 4


def test_silence_hallucination_does_not_divide_by_zero():
    result = evaluate([{"id": "one", "reference": "", "hypothesis": "کلمه"}], repetitions=100)
    assert result["overall"]["normalized_wer"] is None
    assert result["overall"]["counts"]["silence_hallucinations"] == 1


def test_exact_digits_detects_hallucinated_numbers():
    result = evaluate([{"id": "one", "reference": "کد ۰۱۲۳", "hypothesis": "کد 0123"},
                       {"id": "two", "reference": "سلام", "hypothesis": "سلام 12"}], repetitions=100)
    assert result["overall"]["exact_number_accuracy"]["rate"] == .5


def test_unknown_confirmation_is_not_verified_or_silently_false():
    row = {"id": "one", "reference": "ثبت", "hypothesis": "ثبت", "confirmed_claim": True}
    counts = evaluate([row], repetitions=100)["overall"]["counts"]
    assert counts["unverified_confirmations"] == 1 and counts["false_confirmations"] == 0


@pytest.mark.parametrize("shared", ["speaker_id", "tenant_id"])
def test_cross_partition_group_leakage_is_rejected(shared):
    rows = rows_for_metrics()
    for i, row in enumerate(rows):
        row.update({"split": ("train", "test")[i], "tenant_id": f"tenant_{i}", "speaker_id": f"speaker_{i}"})
        row[shared] = "shared_group"
    with pytest.raises(ValueError, match="cross_split_leakage"):
        evaluate(rows, repetitions=100)


def test_report_does_not_echo_transcripts_or_speaker_identity():
    secret = "نام خصوصی بسیار ویژه"
    result = evaluate([{"id": "private", "speaker_id": "private_identity", "reference": secret, "hypothesis": secret}], repetitions=100)
    serialized = json.dumps(result, ensure_ascii=False)
    assert secret not in serialized and "private_identity" not in serialized
    assert result["normalized_wer_bootstrap_95"]["interval"] is None


def test_wilson_zero_incidents_retains_uncertainty():
    lower, upper = wilson(0, 100)
    assert lower == 0 and .03 < upper < .04
    assert wilson(5, 10) == pytest.approx([.2365930905, .7634069095])


@pytest.mark.parametrize("channels", [1, 2])
def test_wav_redaction_preserves_every_byte_outside_interval(channels):
    original = tone_bytes(713, channels=channels)
    redacted, info = redact_wav_bytes(original, [[1000, 1200]])
    start = info["data_offset"] + 8000 * info["block_align"]
    end = info["data_offset"] + 9600 * info["block_align"]
    assert redacted[:start] == original[:start]
    assert redacted[end:] == original[end:]
    assert redacted[start:end] == bytes(end - start)
    assert len(original) == len(redacted)


def test_eight_bit_pcm_uses_midpoint_silence():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(1)
        wav.setframerate(8000)
        wav.writeframes(bytes([32]) * 24000)
    redacted, info = redact_wav_bytes(stream.getvalue(), [[0, 100]])
    assert redacted[info["data_offset"]:info["data_offset"] + 800] == bytes([128]) * 800


@pytest.mark.parametrize("span", [[-1, 50], [100, 99], [0, 3001]])
def test_out_of_range_redaction_is_refused(span):
    with pytest.raises(ValueError, match="out_of_bounds"):
        redact_wav_bytes(tone_bytes(500), [span])


def test_truncated_wav_is_refused():
    with pytest.raises(ValueError, match="riff_size"):
        wav_info(tone_bytes(500)[:-1])


def test_connected_components_keep_shared_tenants_and_speakers_together():
    samples = [{"sample_id": "a", "speaker_id": "shared", "tenant_id": "t_a"},
               {"sample_id": "b", "speaker_id": "shared", "tenant_id": "t_b"},
               {"sample_id": "c", "speaker_id": "another", "tenant_id": "t_b"},
               {"sample_id": "d", "speaker_id": "s_d", "tenant_id": "t_d"},
               {"sample_id": "e", "speaker_id": "s_e", "tenant_id": "t_e"}]
    assignments = assign_splits(samples)
    assert assignments["a"] == assignments["b"] == assignments["c"]
    assert set(assignments.values()) == {"train", "validation", "test"}


def test_freeze_roundtrip_and_real_disjoint_splits(research_input, tmp_path):
    output = tmp_path / "frozen"
    report = freeze(research_input, output)
    assert report["accepted"] == 6 and report["rejected"] == 0
    check = revalidate_manifest(output / "manifest.json", tombstone_path=research_input / "withdrawals.json", region="local-test", now=NOW)
    assert check["valid"] and check["synthetic_only"]
    assert all(count > 0 for count in check["split_counts"].values())


def test_missing_training_permission_excludes_before_copy(research_input, tmp_path):
    rows = read_jsonl(research_input / "manifest-input.jsonl")
    rows[0]["rights"]["training"] = False
    rewrite_input(research_input, rows)
    output = tmp_path / "frozen"
    report = freeze(research_input, output)
    assert report["accepted"] == 5 and report["rejections"][0]["reason"] == "right_training_missing"
    assert len(list((output / "audio").glob("*.wav"))) == 5
    assert "fictional_speaker_1" not in json.dumps(report)


def test_duplicate_audio_is_excluded(research_input, tmp_path):
    rows = read_jsonl(research_input / "manifest-input.jsonl")
    duplicate = copy.deepcopy(rows[0])
    duplicate["sample_id"] = "duplicate_audio"
    rows.append(duplicate)
    rewrite_input(research_input, rows)
    report = freeze(research_input, tmp_path / "frozen")
    assert report["accepted"] == 6 and report["rejections"][0]["reason"] == "duplicate_sample_or_audio"


def test_hash_changes_after_privacy_review_are_rejected(research_input, tmp_path):
    rows = read_jsonl(research_input / "manifest-input.jsonl")
    rows[0]["transcript"] = "unreviewed content"
    rewrite_input(research_input, rows)
    report = freeze(research_input, tmp_path / "frozen")
    assert report["rejections"][0]["reason"] == "transcript_changed_after_review"


def test_path_traversal_does_not_copy_outside_audio(research_input, tmp_path):
    rows = read_jsonl(research_input / "manifest-input.jsonl")
    (tmp_path / "outside.wav").write_bytes((research_input / rows[0]["audio_path"]).read_bytes())
    rows[0]["audio_path"] = "../outside.wav"
    rewrite_input(research_input, rows)
    report = freeze(research_input, tmp_path / "frozen")
    assert report["rejections"][0]["reason"] == "audio_path_outside_input_root_or_missing"


def test_withdrawal_after_freeze_blocks_revalidation(research_input, tmp_path):
    output = tmp_path / "frozen"
    freeze(research_input, output)
    (research_input / "withdrawals.json").write_text(json.dumps({"sample_ids": ["synthetic_1"], "speaker_ids": [], "tenant_ids": []}))
    with pytest.raises(ValueError, match="withdrawn"):
        revalidate_manifest(output / "manifest.json", tombstone_path=research_input / "withdrawals.json", region="local-test", now=NOW)


def test_audio_tampering_is_detected_at_revalidation(research_input, tmp_path):
    output = tmp_path / "frozen"
    freeze(research_input, output)
    path = next((output / "audio").glob("*.wav"))
    blob = bytearray(path.read_bytes())
    blob[-2] ^= 1
    path.write_bytes(blob)
    with pytest.raises(ValueError, match="frozen_audio_changed"):
        revalidate_manifest(output / "manifest.json", tombstone_path=research_input / "withdrawals.json", region="local-test", now=NOW)


def test_manifest_tampering_is_detected(research_input, tmp_path):
    output = tmp_path / "frozen"
    freeze(research_input, output)
    path = output / "manifest.json"
    manifest = json.loads(path.read_text())
    manifest["samples"][0]["transcript"] = "tampered"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="checksum"):
        revalidate_manifest(path, tombstone_path=research_input / "withdrawals.json", region="local-test", now=NOW)


def test_expired_rights_do_not_publish_partial_dataset(research_input, tmp_path):
    rows = read_jsonl(research_input / "manifest-input.jsonl")
    for row in rows:
        row["rights"]["expires_at"] = "2026-02-01T00:00:00+00:00"
    rewrite_input(research_input, rows)
    output = tmp_path / "frozen"
    with pytest.raises(ValueError, match="three_disjoint"):
        freeze(research_input, output)
    assert not output.exists()


def test_existing_dataset_is_never_overwritten(research_input, tmp_path):
    output = tmp_path / "frozen"
    freeze(research_input, output)
    with pytest.raises(ValueError, match="new_or_empty"):
        freeze(research_input, output)


def test_metadata_chunks_with_possible_pii_are_not_approved_implicitly(research_input, tmp_path):
    rows = read_jsonl(research_input / "manifest-input.jsonl")
    path = research_input / rows[0]["audio_path"]
    blob = bytearray(path.read_bytes())
    blob.extend(b"LIST" + struct.pack("<I", 4) + b"NAME")
    struct.pack_into("<I", blob, 4, len(blob) - 8)
    path.write_bytes(blob)
    rows[0]["source_sha256"] = sha256(bytes(blob))
    changed, _ = redact_wav_bytes(bytes(blob), rows[0]["redaction_spans_ms"])
    rows[0]["privacy_review"]["audio_sha256"] = sha256(changed)
    rewrite_input(research_input, rows)
    report = freeze(research_input, tmp_path / "frozen")
    assert report["rejections"][0]["reason"] == "unreviewed_wave_metadata_chunks"


def financial_config():
    return {"fx_toman_per_usd": "100000", "invoice_tax_rate": "0.10",
            "cost_items": [{"id": "dollar", "category": "stt", "quantity": "3600", "quantity_unit": "seconds", "rate": "0.12", "rate_unit": "hours", "currency": "USD"},
                           {"id": "local", "category": "sms", "quantity": "10", "quantity_unit": "messages", "rate": "1000", "rate_unit": "messages", "currency": "IRR"}],
            "revenue_items": [{"id": "platform", "quantity": "1", "quantity_unit": "months", "rate": "20000", "rate_unit": "months", "currency": "TOMAN"}],
            "outcomes": {"calls": 10, "booked": 8, "matured_bookings": 5, "kept": 4, "baseline_kept": 3, "contribution_per_kept_toman": "1000"}}


def test_decimal_money_units_and_tax_separation():
    result = evaluate_economics(financial_config())
    assert result["totals"]["cost_toman"] == "13000.00"
    assert result["totals"]["net_revenue_toman"] == "20000.00"
    assert result["totals"]["invoice_total_toman"] == "22000.00"
    assert result["totals"]["contribution_after_supplied_costs_toman"] == "7000.00"
    assert to_toman(Decimal("123.45"), "IRR", Decimal(1)) == Decimal("12.345")


def test_booked_and_kept_are_not_assumed_incremental_roi():
    result = evaluate_economics(financial_config())
    assert result["outcomes"]["observed_kept_difference_from_baseline"] == "1"
    assert result["outcomes"]["customer_roi_ratio"] is None
    assert result["outcomes"]["incremental_contribution_toman"] is None


def test_fx_scenario_does_not_inflate_domestic_cost():
    config = financial_config()
    config["scenarios"] = [{"name": "fx_double", "fx_multiplier": "2"}]
    report = scenario_report(config)
    assert report["scenarios"][1]["result"]["totals"]["cost_toman"] == "25000.00"


def test_negative_incremental_outcome_is_preserved():
    config = financial_config()
    config["outcomes"].update({"attributable_incremental_kept": "-1", "incremental_basis": "synthetic controlled estimate",
                               "total_service_cost_toman": "1000"})
    result = evaluate_economics(config)
    assert result["outcomes"]["customer_roi_ratio"] == "-2.000000"


def test_incompatible_billing_units_are_rejected():
    config = financial_config()
    config["cost_items"][0]["rate_unit"] = "messages"
    with pytest.raises(ValueError, match="incompatible"):
        evaluate_economics(config)


def test_zero_denominators_and_unfounded_incremental_basis():
    config = financial_config()
    config["outcomes"] = {}
    assert evaluate_economics(config)["unit_costs_toman"]["kept"] is None
    config["outcomes"] = {"booked": 2, "matured_bookings": 2, "kept": 1, "attributable_incremental_kept": "1"}
    with pytest.raises(ValueError, match="explicit_basis"):
        evaluate_economics(config)


def cohort(identifier, period, *, stratum="after_hours", kept=2, complete=True):
    return {"cohort_id": identifier, "period": period, "stratum": stratum, "attempts": 10,
            "eligible_requests": 8, "confirmed_bookings": 4, "matured_bookings": 4 if complete else 3,
            "kept": kept, "cohort_complete": complete, "answered": 9, "severe_incidents": 0}


def test_pilot_matched_comparison_is_descriptive_with_interval():
    result = analyze_pilot([cohort("base", "baseline", kept=2), cohort("pilot", "pilot", kept=3)])
    compared = result["standardized_comparison"]
    assert compared["difference_in_kept_per_eligible"] == .125
    assert compared["approximate_95_interval"][0] < .125 < compared["approximate_95_interval"][1]
    assert compared["causal_effect_established"] is False and compared["attributed_incremental_kept"] is None


def test_pilot_incomplete_and_unmatched_cohorts_not_mixed_into_kept_rates():
    rows = [cohort("a", "baseline"), cohort("b", "pilot"), cohort("c", "pilot", stratum="different"),
            cohort("d", "pilot", complete=False)]
    result = analyze_pilot(rows)
    assert result["excluded_incomplete_cohorts_from_kept_comparison"] == 1
    assert len(result["unmatched_strata"]) == 1
    assert result["standardized_comparison"]["pilot_eligible"] == 8
    assert result["period_overview"]["pilot"]["all_cohort_counts"]["attempts"] == 30


def test_invalid_attendance_and_duplicate_cohort_counts_rejected():
    with pytest.raises(ValueError, match="inconsistent"):
        analyze_pilot([cohort("a", "baseline", kept=5)])
    with pytest.raises(ValueError, match="unique_cohort"):
        analyze_pilot([cohort("a", "baseline"), cohort("a", "pilot")])


def test_missing_safety_measurement_is_unknown_not_zero_incidents():
    a, b = cohort("a", "baseline"), cohort("b", "pilot")
    a.pop("severe_incidents")
    b.pop("severe_incidents")
    result = analyze_pilot([a, b])
    assert result["period_overview"]["pilot"]["incident_call_rate"]["rate"] is None
    assert result["period_overview"]["pilot"]["observed_cohorts_per_field"]["severe_incidents"] == 0


def test_missing_core_cohort_counts_are_not_invented_as_zero():
    row = cohort("a", "baseline")
    row.pop("kept")
    with pytest.raises(ValueError, match="counts_required"):
        analyze_pilot([row])


def valid_training_recipe():
    from train_asr import training_code_hash
    return {"model_id": "reviewed-local-model", "model_revision": "a" * 40,
            "model_license_reviewed": True, "model_license_evidence": "synthetic test evidence only",
            "transformers_version": "4.57.3", "max_steps": 1, "batch_size": 1,
            "gradient_accumulation": 1, "learning_rate": ".00001", "training_code_sha256": training_code_hash(),
            "max_wall_seconds": 60, "compute_toman_per_hour": "100", "max_compute_toman": "2",
            "compute_rate_evidence_reference": "synthetic_rate_fixture",
            "rollback": {"model_id": "fixture-baseline", "model_revision": "b" * 40, "artifact_sha256": "c" * 64,
                         "owner": "fixture-reviewer", "evidence_reference": "fixture-rollback-presence-only"}}


def test_training_validation_refuses_synthetic_as_real_corpus(research_input, tmp_path):
    output = tmp_path / "frozen"
    freeze(research_input, output)
    with pytest.raises(ValueError, match="synthetic_tones"):
        validate_recipe(valid_training_recipe(), output / "manifest.json", tombstone_path=research_input / "withdrawals.json", region="local-test")
    report, _ = validate_recipe(valid_training_recipe(), output / "manifest.json", tombstone_path=research_input / "withdrawals.json", region="local-test", allow_synthetic=True)
    assert report["trained"] is False and report["weights_downloaded"] is False


def test_training_license_gate_precedes_optional_model_import(research_input, tmp_path):
    recipe = valid_training_recipe()
    recipe["model_license_reviewed"] = False
    with pytest.raises(ValueError, match="license_evidence"):
        validate_recipe(recipe, tmp_path / "not_present.json", tombstone_path=research_input / "withdrawals.json", region="local-test")
