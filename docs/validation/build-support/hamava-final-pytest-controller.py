#!/usr/bin/env python3
"""Temporary, duration-balanced, three-process full pytest controller.

`plan` performs collection only. `run` never stops an existing process. All
workers collect the full suite before selecting whole files, preserving imports.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree as ET

PLUGIN = Path(__file__).with_name("hamava_final_shard_plugin.py")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_suffix(path.suffix + ".partial")
    partial.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    partial.replace(path)


def sources(root):
    files = set(root.glob("backend/**/*.py")) | set(root.glob("scripts/*.py")) | set(root.glob("services/local_speech/*.py"))
    files.add(root / "pyproject.toml")
    return {str(path.relative_to(root)): digest(path) for path in sorted(files) if "__pycache__" not in path.parts}


def environment(output, mode, shard=None, plan=None):
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PLUGIN.parent) + os.pathsep + env.get("PYTHONPATH", "")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # A full-suite gate must not inherit selection or fail-fast flags.
    env["PYTEST_ADDOPTS"] = ""
    env.pop("PYTEST_CURRENT_TEST", None)
    env["HAMAVA_SHARD_MODE"] = mode
    env["HAMAVA_SHARD_OBSERVATION"] = str(output / "observation.json")
    (output / "os-tmp").mkdir(parents=True, exist_ok=True)
    env["TMPDIR"] = str(output / "os-tmp")
    if shard is not None:
        env["HAMAVA_SHARD_INDEX"] = str(shard)
        env["HAMAVA_SHARD_PLAN"] = str(plan)
    return env


def command(python, output, collect_only=False):
    cmd = [python, "-m", "pytest", "backend/tests", "-q", "-p", "hamava_final_shard_plugin",
           "--basetemp", str(output / "pytest-tmp"), "-o", "cache_dir=" + str(output / "pytest-cache")]
    if collect_only:
        cmd.append("--collect-only")
    else:
        cmd.append("--junitxml=" + str(output / "junit.xml"))
    return cmd


def redact_artifacts(output, env):
    url = env.get("TEST_DATABASE_URL", "")
    secrets = [url, html.escape(url, quote=True)] if url else []
    if url:
        password = urlsplit(url).password
        if password:
            secrets.extend([password, unquote(password), html.escape(unquote(password), quote=True)])
    for path in (output / "pytest.log", output / "junit.xml"):
        if path.exists():
            text = path.read_text(errors="replace")
            original = text
            for secret in sorted(set(secrets), key=len, reverse=True):
                if len(secret) >= 4:
                    text = text.replace(secret, "[REDACTED_TEST_DATABASE_CREDENTIAL]")
            if text != original:
                path.write_text(text)


def plan_run(args):
    root, output = Path(args.project).resolve(), Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    collection_dir = output / "collection"
    collection_dir.mkdir()
    initial_sources = sources(root)
    env = environment(collection_dir, "collect")
    cmd = command(args.python, collection_dir, True)
    with (collection_dir / "pytest.log").open("w") as log:
        completed = subprocess.run(cmd, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=120)
    redact_artifacts(collection_dir, env)
    if completed.returncode:
        raise RuntimeError("Collection failed; inspect the retained collection/pytest.log")
    observed = json.loads((collection_dir / "observation.json").read_text())
    rows = observed["collection"]
    expected_files = sorted(str(path.relative_to(root)) for path in (root / "backend/tests").glob("test_*.py"))
    actual_files = sorted({row["file"] for row in rows})
    if expected_files != actual_files:
        raise RuntimeError("Collected files do not exactly cover every backend test_*.py file")
    if observed["started"] or observed["finished"]:
        raise RuntimeError("Plan phase unexpectedly executed a test")
    prior = Path(args.prior_junit).resolve()
    timing = {path: 0.0 for path in expected_files}
    matched_cases = Counter()
    prior_tree = ET.parse(prior)
    for case in prior_tree.iter("testcase"):
        classname = case.attrib.get("classname", "")
        matches = [path for path in expected_files if classname == path[:-3].replace("/", ".") or classname.startswith(path[:-3].replace("/", ".") + ".")]
        if len(matches) == 1:
            timing[matches[0]] += float(case.attrib.get("time", 0))
            matched_cases[matches[0]] += 1
    counts = Counter(row["file"] for row in rows)
    known_seconds = sum(timing.values())
    known_count = sum(matched_cases.values())
    fallback = known_seconds / max(1, known_count)
    for path in expected_files:
        # Account explicitly for new cases absent from the duration baseline.
        missing = max(0, counts[path] - matched_cases[path])
        timing[path] += missing * fallback
        if timing[path] <= 0:
            timing[path] = counts[path] * max(0.1, fallback)
    shards = [{"index": n, "files": [], "estimated_seconds": 0.0} for n in range(3)]
    for path in sorted(expected_files, key=lambda p: (-timing[p], p)):
        target = min(shards, key=lambda s: (s["estimated_seconds"], s["index"]))
        target["files"].append(path)
        target["estimated_seconds"] += timing[path]
    for shard in shards:
        shard["files"].sort()
        shard["nodes"] = [row["nodeid"] for row in rows if row["file"] in shard["files"]]
        shard["estimated_seconds"] = round(shard["estimated_seconds"], 3)
    assigned_files = [path for shard in shards for path in shard["files"]]
    assigned_nodes = [node for shard in shards for node in shard["nodes"]]
    assert Counter(assigned_files) == Counter(expected_files)
    assert Counter(assigned_nodes) == Counter(row["nodeid"] for row in rows)
    assert all(value == 1 for value in Counter(assigned_nodes).values())
    if initial_sources != sources(root):
        raise RuntimeError("Backend/test/script source changed during planning")
    plan = {
        "format": "hamava-temporary-pytest-shards-v1", "created_at": datetime.now(timezone.utc).isoformat(),
        "project": str(root), "python": args.python, "shard_count": 3,
        "total_files": len(expected_files), "total_nodes": len(rows),
        "collection": rows, "shards": shards, "source_sha256": initial_sources,
        "controller_sha256": digest(__file__), "plugin_sha256": digest(PLUGIN),
        "duration_baseline": {"path": str(prior), "sha256": digest(prior), "matched_cases": known_count,
                              "summed_case_seconds": round(known_seconds, 3)},
        "file_estimates": {path: round(timing[path], 3) for path in expected_files},
        "test_database_url_supplied_during_plan": bool(os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql")),
        "environment_contract": "Run inherits current environment including TEST_DATABASE_URL/TOOL_TIMEOUT_MS; no database URL is stored. Only pytest selection flags, bytecode writes, temp/cache paths and observer variables are isolated. TEST_DATABASE_URL must be explicitly supplied for execution.",
        "coverage_assertions": {"all_files_exactly_once": True, "all_nodes_exactly_once": True, "tests_executed_during_plan": 0},
        "performance_boundary": "Estimates sum prior per-case times; they are not a guarantee of threefold speedup under CPU/native-build contention.",
    }
    write_json(output / "plan.json", plan)
    print(json.dumps({"plan": str(output / "plan.json"), "files": len(expected_files), "nodes": len(rows),
                      "shards": [{"index": s["index"], "files": len(s["files"]), "nodes": len(s["nodes"]), "estimated_seconds": s["estimated_seconds"]} for s in shards],
                      "test_database_url_provided": plan["test_database_url_supplied_during_plan"], "tests_executed": 0}, indent=2), flush=True)


def outcome(phases):
    if any(p["outcome"] == "failed" and p["phase"] != "call" for p in phases):
        return "error"
    if any(p["outcome"] == "failed" for p in phases):
        return "failed"
    if any(p["outcome"] == "skipped" for p in phases):
        return "skipped"
    return "passed" if any(p["phase"] == "call" and p["outcome"] == "passed" for p in phases) else "incomplete"


def execute_run(args):
    plan_path, output = Path(args.plan).resolve(), Path(args.output).resolve()
    plan = json.loads(plan_path.read_text())
    root = Path(plan["project"])
    if sources(root) != plan["source_sha256"] or digest(__file__) != plan["controller_sha256"] or digest(PLUGIN) != plan["plugin_sha256"]:
        raise RuntimeError("Sources/controller differ from frozen plan; make a fresh plan")
    if not os.environ.get("TEST_DATABASE_URL", "").startswith("postgresql"):
        raise RuntimeError("Explicit isolated TEST_DATABASE_URL is required; refusing to silently skip PostgreSQL cases")
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / "plan.json", plan)
    predecessor = None
    if args.supersedes_session:
        if not args.serial_log or not Path(args.serial_log).is_file():
            raise RuntimeError("A preserved serial log is required before replacing the prior run")
        old_log = Path(args.serial_log)
        retained = output / "serial-interrupted.log"
        retained.write_bytes(old_log.read_bytes())
        predecessor = {"tool_session": args.supersedes_session, "status": "interrupted_incomplete",
                       "result": "No completed full-suite result is inferred from this serial attempt",
                       "stopped_by": "parent before this controller was invoked; controller never signals it",
                       "preserved_log": str(retained), "log_sha256": digest(retained)}
        write_json(output / "serial-interrupted.json", predecessor)
    started = time.monotonic()
    processes = []
    interrupted = False
    try:
        for shard in plan["shards"]:
            shard_dir = output / f"shard-{shard['index'] + 1}"
            shard_dir.mkdir()
            env = environment(shard_dir, "run", shard["index"], output / "plan.json")
            log = (shard_dir / "pytest.log").open("w")
            proc = subprocess.Popen(command(plan["python"], shard_dir), cwd=root, env=env,
                                    stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            processes.append((shard, shard_dir, proc, log, env))
        print(json.dumps({"status": "running", "output": str(output), "processes": len(processes), "planned_nodes": plan["total_nodes"]}), flush=True)
        last_status = 0
        while any(proc.poll() is None for _, _, proc, _, _ in processes):
            if time.monotonic() - last_status >= 30:
                progress = []
                for shard, directory, proc, _, _ in processes:
                    path = directory / "observation.json"
                    observed = json.loads(path.read_text()) if path.exists() else {}
                    progress.append({"shard": shard["index"] + 1, "finished": len(observed.get("finished", [])),
                                     "planned": len(shard["nodes"]), "exit_code": proc.poll()})
                print(json.dumps({"elapsed_seconds": round(time.monotonic() - started, 1), "progress": progress}), flush=True)
                last_status = time.monotonic()
            time.sleep(0.5)
    except (KeyboardInterrupt, SystemExit):
        interrupted = True
        for _, _, proc, _, _ in processes:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGINT)
        for _, _, proc, _, _ in processes:
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=10)
    finally:
        for _, directory, _, log, env in processes:
            log.close()
            redact_artifacts(directory, env)
    selected, started_nodes, finished, all_outcomes, records = [], [], [], {}, []
    full_collection_matches = True
    for shard, directory, proc, _, _ in processes:
        observation_path = directory / "observation.json"
        observed = json.loads(observation_path.read_text()) if observation_path.exists() else {}
        full_collection_matches &= observed.get("collection") == plan["collection"]
        selected += observed.get("selected", [])
        started_nodes += observed.get("started", [])
        finished += observed.get("finished", [])
        node_outcomes = {node: outcome(phases) for node, phases in observed.get("reports", {}).items()}
        all_outcomes.update(node_outcomes)
        junit = directory / "junit.xml"
        records.append({"shard": shard["index"] + 1, "exit_code": proc.returncode,
                        "planned_nodes": len(shard["nodes"]), "selected_nodes": len(observed.get("selected", [])),
                        "finished_nodes": len(observed.get("finished", [])), "outcomes": dict(Counter(node_outcomes.values())),
                        "junit": str(junit) if junit.exists() else None,
                        "junit_sha256": digest(junit) if junit.exists() else None,
                        "log": str(directory / "pytest.log"), "log_sha256": digest(directory / "pytest.log"),
                        "observation": str(observation_path)})
    expected = Counter(row["nodeid"] for row in plan["collection"])
    coverage = {"full_collection_matches_in_every_process": full_collection_matches,
                "selected_exactly_once": Counter(selected) == expected,
                "started_exactly_once": Counter(started_nodes) == expected,
                "finished_exactly_once": Counter(finished) == expected,
                "source_unchanged": sources(root) == plan["source_sha256"]}
    totals = Counter(all_outcomes.values())
    complete = all(coverage.values()) and len(processes) == 3 and not interrupted
    passed = complete and totals.get("passed", 0) == plan["total_nodes"] and all(proc.returncode == 0 for _, _, proc, _, _ in processes)
    aggregate = {"format": "hamava-full-pytest-shard-result-v1", "status": "passed" if passed else "failed_or_incomplete",
                 "completed_at": datetime.now(timezone.utc).isoformat(), "wall_seconds": round(time.monotonic() - started, 3),
                 "planned_files": plan["total_files"], "planned_nodes": plan["total_nodes"], "outcomes": dict(totals),
                 "coverage": coverage, "shards": records, "superseded_serial_run": predecessor,
                 "source_sha256": plan["source_sha256"], "test_database_url_supplied": True,
                 "execution_environment": {"TOOL_TIMEOUT_MS": os.environ.get("TOOL_TIMEOUT_MS"), "ENVIRONMENT": os.environ.get("ENVIRONMENT"), "DEMO_MODE": os.environ.get("DEMO_MODE")},
                 "scope": "All current backend test nodes executed once across three isolated processes, each collecting all files first. This is a complete sharded run, not a completed serial run or provider/device acceptance."}
    write_json(output / "aggregate.json", aggregate)
    print(json.dumps({"status": aggregate["status"], "outcomes": dict(totals), "coverage": coverage,
                      "wall_seconds": aggregate["wall_seconds"], "aggregate": str(output / "aggregate.json")}, indent=2), flush=True)
    return 0 if passed else 1


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    planning = sub.add_parser("plan")
    planning.add_argument("--project", required=True)
    planning.add_argument("--python", default=sys.executable)
    planning.add_argument("--prior-junit", required=True)
    planning.add_argument("--output", required=True)
    running = sub.add_parser("run")
    running.add_argument("--plan", required=True)
    running.add_argument("--output", required=True)
    running.add_argument("--supersedes-session")
    running.add_argument("--serial-log")
    args = parser.parse_args()
    if args.mode == "plan":
        plan_run(args)
        return 0
    return execute_run(args)


if __name__ == "__main__":
    raise SystemExit(main())
