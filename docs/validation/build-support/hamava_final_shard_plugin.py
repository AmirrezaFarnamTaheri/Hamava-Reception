"""Temporary exact-coverage observer/selector; no product or test modifications."""
import json
import os
from pathlib import Path
import time

import pytest

_STATE = {"started": [], "finished": [], "reports": {}, "collection": [], "selected": []}
_START = time.monotonic()


def _write():
    target = Path(os.environ["HAMAVA_SHARD_OBSERVATION"])
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".partial")
    partial.write_text(json.dumps({**_STATE, "elapsed_seconds": time.monotonic() - _START}, indent=2) + "\n")
    partial.replace(target)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    root = Path(config.rootpath).resolve()
    rows = [{"nodeid": item.nodeid, "file": str(Path(item.path).resolve().relative_to(root))} for item in items]
    ids = [row["nodeid"] for row in rows]
    if len(ids) != len(set(ids)):
        raise pytest.UsageError("Duplicate collected node IDs")
    _STATE["collection"] = rows
    _STATE["root"] = str(root)
    _STATE["mode"] = os.environ["HAMAVA_SHARD_MODE"]
    if os.environ["HAMAVA_SHARD_MODE"] == "run":
        plan = json.loads(Path(os.environ["HAMAVA_SHARD_PLAN"]).read_text())
        if rows != plan["collection"]:
            raise pytest.UsageError("Full collection differs from the frozen shard plan")
        index = int(os.environ["HAMAVA_SHARD_INDEX"])
        expected = plan["shards"][index]["nodes"]
        selected_set = set(expected)
        selected = [item for item in items if item.nodeid in selected_set]
        deselected = [item for item in items if item.nodeid not in selected_set]
        if [item.nodeid for item in selected] != expected:
            raise pytest.UsageError("Selected nodes differ from exact shard assignment")
        items[:] = selected
        config.hook.pytest_deselected(items=deselected)
        _STATE["shard"] = index
    _STATE["selected"] = [item.nodeid for item in items]
    _write()


def pytest_runtest_logstart(nodeid, location):
    _STATE["started"].append(nodeid)


def pytest_runtest_logreport(report):
    _STATE["reports"].setdefault(report.nodeid, []).append({
        "phase": report.when, "outcome": report.outcome,
        "duration_seconds": report.duration,
        "wasxfail": getattr(report, "wasxfail", None),
    })


def pytest_runtest_logfinish(nodeid, location):
    _STATE["finished"].append(nodeid)
    _write()


def pytest_sessionfinish(session, exitstatus):
    _STATE["exit_status"] = int(exitstatus)
    _write()
