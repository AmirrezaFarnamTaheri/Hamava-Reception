"""Synthetic capture, metering, experiment gates and encrypted config recovery."""
from array import array
import asyncio
from collections import defaultdict
import copy
from datetime import timedelta
import importlib.util
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import wave

from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from capture_segment import segment_record  # noqa: E402
from config_backup import create_backup, restore_backup  # noqa: E402
from evaluate_speech import evaluate  # noqa: E402
from research_common import sha256  # noqa: E402
from train_asr import ExperimentBudget, training_code_hash, validate_recipe  # noqa: E402
from benchmark_local_speech import benchmark  # noqa: E402
from test_research_tools import NOW, freeze, make_fixtures, valid_training_recipe  # noqa: E402
from teacher_labels import compare_teachers, validate_adjudication  # noqa: E402


def track_bytes(active_start, active_end, frequency=300, *, clipped=False):
    rate, seconds = 8000, 22
    samples = array("h", [0]) * (rate * seconds)
    for index in range(active_start * rate, active_end * rate):
        samples[index] = (32767 if index % 2 else -32767) if clipped else int(4000 * math.sin(2 * math.pi * frequency * index / rate))
    if sys.byteorder != "little":
        samples.byteswap()
    output = io.BytesIO()
    with wave.open(output, "wb") as destination:
        destination.setnchannels(1)
        destination.setsampwidth(2)
        destination.setframerate(rate)
        destination.writeframes(samples.tobytes())
    return output.getvalue()


def capture_fixture(tmp_path):
    caller, agent = track_bytes(1, 21, clipped=True), track_bytes(6, 15, frequency=600)
    (tmp_path / "caller.wav").write_bytes(caller)
    (tmp_path / "agent.wav").write_bytes(agent)
    withdrawals = tmp_path / "withdrawals.json"
    withdrawals.write_text(json.dumps({"sample_ids": [], "speaker_ids": [], "tenant_ids": []}))
    return {"sample_id": "synthetic_capture", "speaker_id": "fictional_caller", "tenant_id": "fictional_clinic",
        "recorded_at": "2026-01-01T00:00:00+00:00", "synthetic": True,
        "transport_role_evidence_reference": "fixture_track_assignment", "agent_voice_license_reference": "synthetic_nonvoice_tone",
        "rights": {"recording": True, "training": True, "clinic_authorized": True, "license_id": "synthetic_fixture_only",
            "consent_version": "synthetic_no_person_v1", "consent_evidence_sha256": "a" * 64, "allowed_regions": ["local-test"], "expires_at": "2099-01-01T00:00:00+00:00"},
        "tracks": {"caller": {"path": "caller.wav", "sha256": sha256(caller), "offset_ms": 0, "codec": "pcm_s16le"},
            "agent": {"path": "agent.wav", "sha256": sha256(agent), "offset_ms": 500, "codec": "pcm_s16le"}}}, withdrawals


def test_dual_track_capture_preserves_source_timing_pcm_and_flags_overlap(tmp_path):
    record, withdrawals = capture_fixture(tmp_path)
    output = tmp_path / "candidates"
    report = segment_record(record, tmp_path, output, tombstone_path=withdrawals, region="local-test")
    assert report["candidates"] >= 3 and report["overlap_candidates"] >= 1
    assert report["training_eligible"] is False and report["narrowband_restoration"] is False
    samples = [json.loads(line) for line in (output / "candidates.jsonl").read_text().splitlines()]
    assert {sample["role"] for sample in samples} == {"caller", "agent"}
    for sample in samples:
        assert 3 <= sample["quality"]["duration_seconds"] <= 15
        assert sample["privacy_review"]["approved"] is False and sample["transcript"] == ""
        with wave.open(str(tmp_path / (sample["role"] + ".wav")), "rb") as source:
            source.setpos(sample["capture"]["frame_start"])
            original = source.readframes(sample["capture"]["frame_end"] - sample["capture"]["frame_start"])
        with wave.open(str(output / sample["audio_path"]), "rb") as derived:
            assert derived.getframerate() == 8000 and derived.readframes(derived.getnframes()) == original
    assert any("clipping" in sample["quality"]["flags"] for sample in samples)


def test_capture_rights_and_withdrawal_precede_source_read_or_copy(tmp_path):
    record, withdrawals = capture_fixture(tmp_path)
    record["rights"]["training"] = False
    record["tracks"]["caller"]["path"] = "not-present.wav"
    with pytest.raises(ValueError, match="rights_required"):
        segment_record(record, tmp_path, tmp_path / "denied", tombstone_path=withdrawals, region="local-test")
    assert not (tmp_path / "denied").exists()
    record["rights"]["training"] = True
    withdrawals.write_text(json.dumps({"sample_ids": [], "speaker_ids": ["fictional_caller"], "tenant_ids": []}))
    with pytest.raises(ValueError, match="withdrawal"):
        segment_record(record, tmp_path, tmp_path / "withdrawn", tombstone_path=withdrawals, region="local-test")


def test_capture_rejects_corrupted_track_and_identical_role_claim(tmp_path):
    record, withdrawals = capture_fixture(tmp_path)
    record["tracks"]["agent"]["sha256"] = "f" * 64
    with pytest.raises(ValueError, match="hash_mismatch"):
        segment_record(record, tmp_path, tmp_path / "corrupt", tombstone_path=withdrawals, region="local-test")
    record["tracks"]["agent"] = record["tracks"]["caller"].copy()
    with pytest.raises(ValueError, match="identical_tracks"):
        segment_record(record, tmp_path, tmp_path / "same", tombstone_path=withdrawals, region="local-test")


def test_retry_and_stage_outcomes_preserve_missing_unknown_denominators():
    rows = [{"id": "a", "reference": "سلام", "hypothesis": "سلام", "eligible": True, "retry_count": 2,
        "confirmed_claim": True, "authoritative_confirmed": False, "stage_latency_ms": {"stt": 120, "tts": 140}},
        {"id": "b", "reference": "خوب", "hypothesis": "خوب", "eligible": True, "task_completed": True,
         "handoff_requested": True, "stage_latency_ms": {"stt": 180}}]
    result = evaluate(rows, repetitions=100)["overall"]
    assert result["retries"] == {"observed_samples": 1, "unknown_samples": 1, "total": 2, "mean": 2.0, "retry_rate": 1.0}
    assert result["counts"]["false_confirmations"] == 1
    assert result["counts"]["unverified_task_outcomes"] == 1 and result["counts"]["unverified_handoff_outcomes"] == 1
    assert result["stage_latency_ms"]["tts"]["missing"] == 1
    with pytest.raises(ValueError, match="invalid_retry"):
        evaluate([{**rows[0], "retry_count": -1}], repetitions=100)


def test_experiment_code_pin_rollback_and_actual_elapsed_budget_are_gates(tmp_path):
    recipe = valid_training_recipe()
    assert recipe["training_code_sha256"] == training_code_hash()
    recipe["training_code_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="training_code_hash"):
        validate_recipe(recipe, tmp_path / "not-read", tombstone_path=tmp_path / "not-read", region="local-test")
    recipe = valid_training_recipe()
    recipe["rollback"] = {}
    with pytest.raises(ValueError, match="rollback"):
        validate_recipe(recipe, tmp_path / "not-read", tombstone_path=tmp_path / "not-read", region="local-test")
    elapsed = {"value": 0}
    budget = ExperimentBudget(valid_training_recipe(), clock=lambda: elapsed["value"])
    elapsed["value"] = 20
    assert budget.check()["elapsed_seconds"] == 20
    elapsed["value"] = 61
    with pytest.raises(ValueError, match="budget_exceeded"):
        budget.check()


def inventory_file(tmp_path):
    path = tmp_path / "inventory.json"
    path.write_text(json.dumps([{"key_id": "app-key-v1", "purpose": "application_ciphertext", "algorithm": "fernet",
        "fingerprint_sha256": "b" * 64, "recovery_reference": "offline-custody-reference", "owner_role": "technical_operator", "last_recovery_drill": "not-yet-performed"}]))
    return path


def test_encrypted_config_backup_restore_hashes_modes_no_overwrite_or_secret_report(tmp_path):
    key = tmp_path / "backup.key"
    key.write_bytes(Fernet.generate_key())
    key.chmod(0o600)
    config = tmp_path / "app.env"
    secret = b"JWT_SECRET=synthetic-test-secret-never-print\n"
    config.write_bytes(secret)
    output = tmp_path / "configuration.enc"
    result = create_backup({"environment/app.env": config}, inventory_file(tmp_path), key, output)
    assert secret not in output.read_bytes() and "synthetic-test-secret" not in json.dumps(result)
    restored = restore_backup(output, key, tmp_path / "restored", confirmed=True)
    assert restored["hashes_verified"] and (tmp_path / "restored/environment/app.env").read_bytes() == secret
    assert (tmp_path / "restored/environment/app.env").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match="target_must_be_empty"):
        restore_backup(output, key, tmp_path / "restored", confirmed=True)
    with pytest.raises(FileExistsError):
        create_backup({"app.env": config}, inventory_file(tmp_path), key, output)


def test_config_backup_refuses_bad_key_traversal_inventory_secret_and_tampering(tmp_path):
    key = tmp_path / "key"
    key.write_bytes(Fernet.generate_key())
    key.chmod(0o644)
    source = tmp_path / "source"
    source.write_text("synthetic")
    inventory = inventory_file(tmp_path)
    with pytest.raises(ValueError, match="private_file"):
        create_backup({"safe": source}, inventory, key, tmp_path / "out")
    key.chmod(0o600)
    with pytest.raises(ValueError, match="unsafe_backup"):
        create_backup({"../escape": source}, inventory, key, tmp_path / "out")
    result = json.loads(inventory.read_text())
    result[0]["private_key"] = "not-allowed"
    inventory.write_text(json.dumps(result))
    with pytest.raises(ValueError, match="metadata_only"):
        create_backup({"safe": source}, inventory, key, tmp_path / "out")
    inventory = inventory_file(tmp_path)
    create_backup({"safe": source}, inventory, key, tmp_path / "out")
    encrypted = bytearray((tmp_path / "out").read_bytes())
    encrypted[-8] ^= 1
    (tmp_path / "out").write_bytes(encrypted)
    with pytest.raises(ValueError, match="authentication_failed"):
        restore_backup(tmp_path / "out", key, tmp_path / "not-created", confirmed=True)
    assert not (tmp_path / "not-created").exists()


def load_speech():
    spec = importlib.util.spec_from_file_location("local_speech_metrics_fixture", ROOT / "services/local_speech/app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_speech_auth_runtime_metrics_include_idle_cost_without_weights(monkeypatch):
    module = load_speech()
    monkeypatch.setenv("SPEECH_GATEWAY_TOKEN", "x" * 40)
    monkeypatch.setenv("LOCAL_COMPUTE_TOMAN_PER_HOUR", "3600")
    monkeypatch.setenv("LOCAL_COMPUTE_RATE_EVIDENCE_REFERENCE", "synthetic-declared-fixture")
    monkeypatch.setattr(module, "transcribe_local", lambda audio, keyterms: {"text": "synthetic", "audio_seconds": 1})
    with TestClient(module.app) as client:
        assert client.get("/metrics").status_code == 401
        response = client.post("/transcribe", content=b"synthetic-nonpatient-input", headers={"Authorization": "Bearer " + "x" * 40})
        assert response.status_code == 200
        metrics = client.get("/metrics", headers={"Authorization": "Bearer " + "x" * 40}).json()
        assert metrics["counts"]["transcribe_completed"] == 1
        assert metrics["asr_loaded"] is False and metrics["allocated_capacity_cost_toman_exact"] is not None
        assert metrics["audio_or_text_stored_in_metrics"] is False
        assert "synthetic-nonpatient-input" not in json.dumps(metrics)


@pytest.mark.asyncio
async def test_local_speech_queue_is_bounded_before_upload():
    module = load_speech()
    module._capacity, module._queue_limit, module._admission = 1, 0, asyncio.Semaphore(1)
    module._counts = defaultdict(int)
    async with module.admission():
        with pytest.raises(HTTPException) as error:
            async with module.admission():
                pass
        assert error.value.status_code == 503
    assert module._counts["active"] == 0 and module._counts["waiting"] == 0 and module._counts["rejected"] == 1


@pytest.mark.asyncio
async def test_local_benchmark_separates_cold_observation_and_rejections():
    state = {"metrics": 0, "calls": 0}
    def response(request):
        if request.url.path == "/metrics":
            state["metrics"] += 1
            return httpx.Response(200, json={"asr_loaded": state["metrics"] > 1,
                "allocated_capacity_cost_toman_exact": "1.25" if state["metrics"] == 1 else "2.75"})
        state["calls"] += 1
        return httpx.Response(503 if state["calls"] == 3 else 200, json={"text": "never-report-content"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        result = await benchmark("http://127.0.0.1:8001", "t" * 40, b"synthetic", requests=4, concurrency=2, client=client)
    assert result["cold_model_observed_before"] is True and result["status_counts"] == {"200": 3, "503": 1}
    assert result["allocated_compute_delta_toman_exact"] == "1.50"
    assert result["subsequent_success_latency_ms"]["n"] == 2 and "never-report-content" not in json.dumps(result)


def teacher_review_fixture(tmp_path, *, disagree=True):
    root = tmp_path / "inputs"
    make_fixtures(root)
    frozen = tmp_path / "frozen"
    freeze(root, frozen)
    manifest_path = frozen / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    teacher_paths = []
    for index in range(2):
        value = {"schema_version": "1.0", "manifest_sha256": manifest["manifest_sha256"],
                 "generated_at": (NOW - timedelta(minutes=2)).isoformat(),
                 "teacher": {"id": f"fictional_teacher_{index}", "system": f"fictional_system_{index}", "revision": "fixture_v1",
                             "independence_group": f"fictional_group_{index}", "processing_region": "local-test",
                             "approval": {"reviewer_id": "synthetic_authority", "independence_attested": True,
                                          "license_evidence_sha256": "b" * 64, "processing_evidence_sha256": "c" * 64,
                                          "issued_at": "2026-01-01T00:00:00+00:00", "expires_at": "2099-01-01T00:00:00+00:00"}},
                 "outputs": [{"sample_id": s["sample_id"], "audio_sha256": s["audio_sha256"],
                              "text": "PRIVATE-FICTIONAL-TEXT شناسه ۱۲۳"} for s in manifest["samples"]]}
        if index == 1 and disagree:
            value["outputs"][0]["text"] = "PRIVATE-FICTIONAL-TEXT شناسه ۴۵۶"
        path = tmp_path / f"teacher-{index}.json"
        path.write_text(json.dumps(value, ensure_ascii=False))
        teacher_paths.append(path)
    return manifest_path, teacher_paths, root / "withdrawals.json"


def create_teacher_comparison(tmp_path, *, disagree=True):
    manifest, teachers, withdrawals = teacher_review_fixture(tmp_path, disagree=disagree)
    directory = tmp_path / "review"
    report = compare_teachers(manifest, teachers, directory, tombstone_path=withdrawals, region="local-test", now=NOW)
    return manifest, teachers, withdrawals, directory, report


def completed_adjudication(directory):
    value = json.loads((directory / "adjudication-template.json").read_text())
    value["reviewer"] = {"reviewer_id": "fictional_human_reviewer", "human_review": True, "independent_review": True,
                         "qualification_evidence_sha256": "d" * 64, "authority_evidence_sha256": "e" * 64}
    for row in value["adjudications"]:
        text = "PRIVATE-HUMAN-CORRECTION شناسه ۱۲۳"
        row.update(decision="accept", reason="listened_corrected", reviewed_at=(NOW + timedelta(seconds=10)).isoformat(),
                   listened_to_audio=True, privacy_reviewed=True, privacy_evidence_sha256="f" * 64,
                   transcript=text, transcript_sha256=sha256(text.encode()))
    row = value["adjudications"][-1]
    row.update(decision="exclude", reason="unintelligible", transcript=None, transcript_sha256=None)
    return value


def check_adjudication(manifest, teachers, withdrawals, directory, artifact):
    path = directory / "human-review.json"
    path.write_text(json.dumps(artifact, ensure_ascii=False))
    return validate_adjudication(manifest, teachers, directory / "comparison.json", path,
                                 tombstone_path=withdrawals, region="local-test", now=NOW + timedelta(minutes=1))


def test_teacher_comparison_flags_digits_and_never_emits_private_hypotheses(tmp_path):
    manifest, teachers, withdrawals, directory, report = create_teacher_comparison(tmp_path)
    assert report["sample_count"] == 6 and report["disagreement_samples"] == 1
    assert report["samples"][0]["flags"] == ["teacher_disagreement", "digit_disagreement"]
    assert report["samples"][0]["pairs"][0]["word_edit_distance"] == 1
    assert report["agreement_is_ground_truth"] is False and report["training_ready"] is False
    assert all(s["human_adjudication_required"] for s in report["samples"])
    for path in directory.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
        assert "PRIVATE-FICTIONAL-TEXT" not in path.read_text()
    assert directory.stat().st_mode & 0o777 == 0o700
    with pytest.raises(FileExistsError):
        compare_teachers(manifest, teachers, directory, tombstone_path=withdrawals, region="local-test", now=NOW)


def test_identical_teacher_outputs_still_require_complete_human_adjudication(tmp_path):
    manifest, teachers, withdrawals, directory, report = create_teacher_comparison(tmp_path, disagree=False)
    assert report["disagreement_samples"] == 0 and report["agreement_is_ground_truth"] is False
    template = json.loads((directory / "adjudication-template.json").read_text())
    with pytest.raises(ValueError, match="human_reviewer_evidence_required"):
        check_adjudication(manifest, teachers, withdrawals, directory, template)
    template["reviewer"] = completed_adjudication(directory)["reviewer"]
    with pytest.raises(ValueError, match="human_decision_required"):
        check_adjudication(manifest, teachers, withdrawals, directory, template)


def test_human_adjudication_pins_content_accepts_exclusions_and_does_not_promote(tmp_path):
    manifest, teachers, withdrawals, directory, _ = create_teacher_comparison(tmp_path)
    original_manifest = manifest.read_bytes()
    report = check_adjudication(manifest, teachers, withdrawals, directory, completed_adjudication(directory))
    assert report["valid"] and report["all_samples_adjudicated"] and report["synthetic_only"]
    assert report["accepted"] == 5 and report["excluded"] == 1
    assert report["ground_truth_automatically_established"] is False and report["training_ready"] is False
    assert "PRIVATE-HUMAN-CORRECTION" not in json.dumps(report)
    assert "fictional_human_reviewer" not in json.dumps(report)
    assert manifest.read_bytes() == original_manifest


@pytest.mark.parametrize("identity", ["independence_group", "same_system_revision", "missing_attestation"])
def test_teacher_independence_and_approval_cannot_be_inferred_from_two_files(tmp_path, identity):
    manifest, teachers, withdrawals = teacher_review_fixture(tmp_path)
    first, second = (json.loads(p.read_text()) for p in teachers)
    if identity == "independence_group":
        second["teacher"][identity] = first["teacher"][identity]
    elif identity == "same_system_revision":
        second["teacher"]["system"] = first["teacher"]["system"]
    else:
        second["teacher"]["approval"]["independence_attested"] = False
    teachers[1].write_text(json.dumps(second))
    with pytest.raises(ValueError, match="independence_not_distinct|approval_evidence_required"):
        compare_teachers(manifest, teachers, tmp_path / "denied", tombstone_path=withdrawals, region="local-test", now=NOW)
    assert not (tmp_path / "denied").exists()


@pytest.mark.parametrize("mutation", ["wrong_audio", "unknown_sample", "duplicate_sample", "wrong_region", "expired_approval"])
def test_teacher_outputs_bind_exact_audio_scope_region_and_current_approval(tmp_path, mutation):
    manifest, teachers, withdrawals = teacher_review_fixture(tmp_path)
    value = json.loads(teachers[0].read_text())
    if mutation == "wrong_audio":
        value["outputs"][0]["audio_sha256"] = "0" * 64
    elif mutation == "unknown_sample":
        value["outputs"][0]["sample_id"] = "unrelated_sample"
    elif mutation == "duplicate_sample":
        value["outputs"][1] = copy.deepcopy(value["outputs"][0])
    elif mutation == "wrong_region":
        value["teacher"]["processing_region"] = "unapproved-region"
    else:
        value["teacher"]["approval"]["expires_at"] = (NOW - timedelta(minutes=1)).isoformat()
    teachers[0].write_text(json.dumps(value))
    with pytest.raises(ValueError, match="teacher_"):
        compare_teachers(manifest, teachers, tmp_path / "denied", tombstone_path=withdrawals, region="local-test", now=NOW)
    assert not (tmp_path / "denied").exists()


def test_teacher_missing_is_explicit_and_no_teacher_subset_can_hide_sample(tmp_path):
    manifest, teachers, withdrawals = teacher_review_fixture(tmp_path)
    value = json.loads(teachers[1].read_text())
    value["outputs"].pop()
    teachers[1].write_text(json.dumps(value))
    report = compare_teachers(manifest, teachers, tmp_path / "review", tombstone_path=withdrawals, region="local-test", now=NOW)
    last = report["samples"][-1]
    assert last["flags"] == ["teacher_missing"] and last["pairs"] == []
    assert last["human_adjudication_required"] and report["sample_count"] == 6
    assert report["missing_hypotheses"] == 1 and report["complete_teacher_coverage"] is False
    assert report["compared_samples"] == 5 and report["disagreement_samples"] == 1


@pytest.mark.parametrize("mutation", ["teacher_content", "comparison_content", "transcript_content", "missing_row", "duplicate_row",
                                      "not_listened", "no_privacy_review", "future_review", "stale_audio", "stale_teacher_evidence"])
def test_adjudication_rejects_tampering_unreviewed_and_incomplete_artifacts(tmp_path, mutation):
    manifest, teachers, withdrawals, directory, _ = create_teacher_comparison(tmp_path)
    artifact = completed_adjudication(directory)
    if mutation == "teacher_content":
        teacher = json.loads(teachers[0].read_text())
        teacher["outputs"][0]["text"] = "changed hypothesis"
        teachers[0].write_text(json.dumps(teacher))
    elif mutation == "comparison_content":
        path = directory / "comparison.json"
        report = json.loads(path.read_text())
        report["samples"][0]["flags"] = []
        path.write_text(json.dumps(report))
    elif mutation == "transcript_content":
        artifact["adjudications"][0]["transcript"] = "changed without hash"
    elif mutation == "missing_row":
        artifact["adjudications"].pop()
    elif mutation == "duplicate_row":
        artifact["adjudications"][1] = copy.deepcopy(artifact["adjudications"][0])
    elif mutation == "not_listened":
        artifact["adjudications"][0]["listened_to_audio"] = False
    elif mutation == "no_privacy_review":
        artifact["adjudications"][0]["privacy_reviewed"] = False
    elif mutation == "future_review":
        artifact["adjudications"][0]["reviewed_at"] = (NOW + timedelta(days=1)).isoformat()
    elif mutation == "stale_audio":
        artifact["adjudications"][0]["audio_sha256"] = "0" * 64
    else:
        artifact["adjudications"][0]["teacher_evidence_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="teacher_"):
        check_adjudication(manifest, teachers, withdrawals, directory, artifact)


def test_withdrawal_precedes_teacher_read_and_is_rechecked_before_adjudication(tmp_path):
    manifest, teachers, withdrawals, directory, _ = create_teacher_comparison(tmp_path)
    sample = json.loads(manifest.read_text())["samples"][0]
    withdrawals.write_text(json.dumps({"sample_ids": [sample["sample_id"]], "speaker_ids": [], "tenant_ids": []}))
    with pytest.raises(ValueError, match="withdrawn"):
        compare_teachers(manifest, [tmp_path / "never-read-one", tmp_path / "never-read-two"], tmp_path / "denied",
                         tombstone_path=withdrawals, region="local-test", now=NOW)
    with pytest.raises(ValueError, match="withdrawn"):
        check_adjudication(manifest, teachers, withdrawals, directory, completed_adjudication(directory))
    assert not (tmp_path / "denied").exists()


def test_teacher_comparison_rechecks_inputs_before_publishing_review_package(tmp_path, monkeypatch):
    import teacher_labels
    manifest, teachers, withdrawals = teacher_review_fixture(tmp_path)
    original = teacher_labels.comparison_record

    def revoke_after_comparison(*args, **kwargs):
        result = original(*args, **kwargs)
        sample = json.loads(manifest.read_text())["samples"][0]
        withdrawals.write_text(json.dumps({"sample_ids": [], "speaker_ids": [sample["speaker_id"]], "tenant_ids": []}))
        return result

    monkeypatch.setattr(teacher_labels, "comparison_record", revoke_after_comparison)
    with pytest.raises(ValueError, match="input_changed_during_review"):
        compare_teachers(manifest, teachers, tmp_path / "never-published", tombstone_path=withdrawals, region="local-test", now=NOW)
    assert not (tmp_path / "never-published").exists()


def test_teacher_cli_rejects_ambiguous_json_without_echoing_content(tmp_path):
    manifest, teachers, withdrawals = teacher_review_fixture(tmp_path)
    teachers[0].write_text('{"schema_version":"1.0","schema_version":"PRIVATE-PAYLOAD-DO-NOT-PRINT"}')
    result = subprocess.run([sys.executable, str(ROOT / "scripts/teacher_labels.py"), "compare", str(manifest),
                             "--teacher", str(teachers[0]), "--teacher", str(teachers[1]), "--tombstones", str(withdrawals),
                             "--region", "local-test", "--output", str(tmp_path / "denied")], capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and "teacher_duplicate_json_key" in result.stderr
    assert "PRIVATE-PAYLOAD" not in result.stdout + result.stderr and not (tmp_path / "denied").exists()
