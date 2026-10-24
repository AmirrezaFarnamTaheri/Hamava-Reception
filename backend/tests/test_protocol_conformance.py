"""Offline protocol replay must exercise code, reject unsafe events, and emit evidence."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def harness():
    spec = importlib.util.spec_from_file_location("hamava_protocol_conformance", ROOT / "scripts" / "protocol_conformance.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_protocol_suite_exercises_success_and_safe_failure_contracts():
    result = await harness().run_fixture_suite(ROOT / "fixtures" / "protocol")
    assert result["cases"] >= 8
    assert result["passed"] == result["cases"]
    assert result["failed"] == 0
    names = {case["id"] for case in result["results"]}
    assert {"deepgram_partial_and_final", "deepgram_incomplete", "deepgram_failed_provider",
            "model_complete_tool", "model_injected_tenant", "model_unfinished_tool",
            "tts_incremental", "tts_truncated", "ami_cold_transfer"}.issubset(names)
    assert all(len(case["fixture_sha256"]) == 64 for case in result["results"])
    # Full user speech, generated content, credentials, and synthetic IDs are absent.
    output = json.dumps(result, ensure_ascii=False)
    assert "09123456789" not in output
    assert "fake-key" not in output
    assert "سخت" not in output


@pytest.mark.asyncio
async def test_protocol_suite_rejects_broken_expected_result(tmp_path):
    directory = tmp_path / "protocol"
    directory.mkdir()
    (directory / "bad.json").write_text(json.dumps({
        "id":"deepgram_partial_and_final", "family":"deepgram", "events":[
            {"type":"Results", "is_final":False, "channel":{"alternatives":[{"transcript":"partial"}]}}
        ], "expect":{"event":"final", "text":"not produced"}
    }))
    result = await harness().run_fixture_suite(directory)
    assert result["cases"] == 1 and result["failed"] == 1
    assert result["results"][0]["status"] == "FAIL"


def test_protocol_cli_is_fail_closed_when_no_fixtures(tmp_path):
    # A report cannot certify an empty corpus.
    import subprocess
    destination = tmp_path / "report.json"
    result = subprocess.run(["python", str(ROOT / "scripts" / "protocol_conformance.py"),
        "--fixtures", str(tmp_path), "--output", str(destination)], capture_output=True, text=True)
    assert result.returncode != 0
    assert destination.exists() and json.loads(destination.read_text())["cases"] == 0
