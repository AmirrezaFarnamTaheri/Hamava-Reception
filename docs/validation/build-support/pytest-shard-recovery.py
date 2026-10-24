#!/usr/bin/env python3
"""Verify one existing full run after loss of its exec transport supervisor.

This performs no test execution and never fills an unobserved OS exit code.
Only the three original worker directories of the single pinned plan are read.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources(root):
    paths = set(root.glob("backend/**/*.py"))
    paths |= set(root.glob("scripts/*.py"))
    paths |= set(root.glob("services/local_speech/*.py"))
    paths.add(root / "pyproject.toml")
    return {
        str(path.relative_to(root)): digest(path)
        for path in sorted(paths)
        if "__pycache__" not in path.parts
    }


def redact(path, url):
    values = [url, html.escape(url, quote=True)]
    password = urlsplit(url).password
    if password:
        values += [password, unquote(password), html.escape(unquote(password), quote=True)]
    text = original = path.read_text()
    for value in sorted(set(values), key=len, reverse=True):
        if len(value) >= 4:
            text = text.replace(value, "[REDACTED_TEST_DATABASE_CREDENTIAL]")
    if text != original:
        path.write_text(text)
    return text != original


def junit_key(node):
    parts = node.split("::")
    return (
        parts[0][:-3].replace("/", ".") + ("." + ".".join(parts[1:-1]) if len(parts) > 2 else ""),
        parts[-1],
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--supervisor-session", required=True)
    args = parser.parse_args()
    raw, root = args.raw.resolve(), args.project.resolve()
    destination = raw / "aggregate.json"
    assert not destination.exists(), "An aggregate already exists; never replace it"
    plan = json.loads((raw / "plan.json").read_text())
    assert Path(plan["project"]).resolve() == root
    assert plan["shard_count"] == 3 and len(plan["shards"]) == 3
    support = Path(__file__).parent
    assert digest(support / "hamava-final-pytest-controller.py") == plan["controller_sha256"]
    assert digest(support / "hamava_final_shard_plugin.py") == plan["plugin_sha256"]
    initial = sources(root)
    assert initial == plan["source_sha256"], "Current sources differ from the original frozen plan"
    expected = Counter(row["nodeid"] for row in plan["collection"])
    assert len(expected) == plan["total_nodes"] and all(count == 1 for count in expected.values())
    assert Counter(node for shard in plan["shards"] for node in shard["nodes"]) == expected
    url = os.environ.get("TEST_DATABASE_URL", "")
    assert url.startswith("postgresql"), "Provide the original isolated test URL for exact log redaction"
    selected, started, finished = [], [], []
    records, junit_nodes, phase_counts = [], [], Counter()
    redacted = []
    for shard in plan["shards"]:
        number = shard["index"] + 1
        directory = raw / f"shard-{number}"
        observation = directory / "observation.json"
        observed = json.loads(observation.read_text())
        assigned = shard["nodes"]
        assert observed["root"] == str(root)
        assert observed["mode"] == "run" and observed["shard"] == shard["index"]
        assert observed["collection"] == plan["collection"]
        assert observed["selected"] == assigned
        assert Counter(observed["started"]) == Counter(assigned)
        assert Counter(observed["finished"]) == Counter(assigned)
        assert set(observed["reports"]) == set(assigned)
        assert type(observed.get("exit_status")) is int and observed["exit_status"] == 0
        for node in assigned:
            phases = observed["reports"][node]
            assert Counter(row["phase"] for row in phases) == Counter({"setup": 1, "call": 1, "teardown": 1})
            assert all(row["outcome"] == "passed" and row.get("wasxfail") is None for row in phases)
            phase_counts.update(row["phase"] for row in phases)
        junit = directory / "junit.xml"
        log = directory / "pytest.log"
        for path in (junit, log):
            assert path.is_file(), f"Incomplete worker artifact: {path.name}"
            if redact(path, url):
                redacted.append(str(path.relative_to(raw)))
        tree = ET.parse(junit)
        cases = list(tree.iter("testcase"))
        assert len(cases) == len(assigned)
        observed_keys = Counter((case.get("classname"), case.get("name")) for case in cases)
        assert observed_keys == Counter(junit_key(node) for node in assigned)
        assert not any(list(case.iter(tag)) for case in cases for tag in ("failure", "error", "skipped"))
        for suite in tree.iter("testsuite"):
            assert all(int(suite.get(key, 0)) == 0 for key in ("failures", "errors", "skipped"))
        log_text = log.read_text()
        assert re.search(rf"(?m)^{len(assigned)} passed(?:,| in )", log_text)
        assert "INTERNALERROR>" not in log_text and "Traceback (most recent call last):" not in log_text
        selected += observed["selected"]
        started += observed["started"]
        finished += observed["finished"]
        junit_nodes += assigned
        records.append({
            "shard": number, "exit_code": None,
            "exit_code_basis": "OS wait status was not retained after exec-server transport loss",
            "pytest_exit_status": observed["exit_status"],
            "pytest_exit_status_basis": "Pinned observer's original pytest_sessionfinish record",
            "planned_nodes": len(assigned), "selected_nodes": len(observed["selected"]),
            "finished_nodes": len(observed["finished"]), "outcomes": {"passed": len(assigned)},
            "worker_elapsed_seconds": observed["elapsed_seconds"],
            "junit": str(junit), "junit_sha256": digest(junit),
            "log": str(log), "log_sha256": digest(log),
            "observation": str(observation), "observation_sha256": digest(observation),
        })
    coverage = {
        "full_collection_matches_in_every_process": True,
        "selected_exactly_once": Counter(selected) == expected,
        "started_exactly_once": Counter(started) == expected,
        "finished_exactly_once": Counter(finished) == expected,
        "source_unchanged": sources(root) == initial == plan["source_sha256"],
    }
    assert all(coverage.values())
    assert Counter(junit_nodes) == expected
    assert phase_counts == Counter({phase: plan["total_nodes"] for phase in ("setup", "call", "teardown")})
    predecessor = json.loads((raw / "serial-interrupted.json").read_text())
    report = {
        "format": "hamava-full-pytest-shard-recovered-result-v1",
        "status": "passed_recovered_supervisor",
        "completion_mode": "same_original_three_workers_after_exec_transport_loss",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "completed_at_basis": "Recovery validation timestamp; exact supervisor completion timestamp unavailable",
        "wall_seconds": None,
        "max_worker_elapsed_seconds": max(row["worker_elapsed_seconds"] for row in records),
        "wall_seconds_boundary": "No uninterrupted supervisor wall time is inferred; worker timings are preserved independently",
        "planned_files": plan["total_files"], "planned_nodes": plan["total_nodes"],
        "outcomes": {"passed": plan["total_nodes"]}, "coverage": coverage,
        "recovery_checks": {
            "same_original_plan_and_workers": True,
            "no_focused_or_other_run_substitution": True,
            "complete_junit_identity_matches_planned_nodes": True,
            "all_setup_call_teardown_phases_passed": True,
            "all_pytest_sessionfinish_exit_statuses_zero": True,
            "original_controller_and_plugin_hashes_match": True,
            "source_start_current_equality": True,
            "complete_worker_summaries_without_internal_errors": True,
        },
        "phase_counts": dict(phase_counts), "shards": records,
        "supervisor": {
            "tool_session": args.supervisor_session, "status": "exec_server_transport_lost",
            "os_exit_code": None,
            "observation": "Existing session became unknown after an exec-server disconnect. No supervisor process remained; the original last pytest worker continued, adopted by PID1. Durable records are used; no OS wait status is invented.",
            "earlier_progress": "Before the outage, tool progress reported shard3 exit0. This historical observation is not substituted for a complete supervisor wait record.",
        },
        "superseded_serial_run": predecessor,
        "source_sha256": plan["source_sha256"],
        "test_database_url_supplied": True,
        "execution_environment": {"TOOL_TIMEOUT_MS": "30000", "ENVIRONMENT": None, "DEMO_MODE": None},
        "execution_environment_basis": "Original authorized controller invocation, unchanged worker environment; no worker was relaunched during recovery",
        "recovery_verifier": {"path": str(Path(__file__).relative_to(root)), "sha256": digest(Path(__file__)), "test_execution": False},
        "redacted_artifacts": redacted,
        "scope": "All current backend nodes passed once in the same originally planned three-worker execution. This is a recovered result after loss of supervisor observation, not an uninterrupted supervisor completion, a composition of focused reruns, or supplier/device/acoustic acceptance.",
    }
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "outcomes": report["outcomes"], "coverage": coverage, "recovery_checks": report["recovery_checks"], "aggregate": str(destination)}, indent=2))


if __name__ == "__main__":
    main()
