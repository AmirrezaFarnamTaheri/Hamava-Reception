#!/usr/bin/env python3
"""Run each browser suite against a fresh, synthetic-only isolated server database."""
import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from zoneinfo import ZoneInfo


def prepare_synthetic_quiet_hours(database: Path) -> int:
    """Keep the isolated journey fixtures outside quiet hours at any CI start time.

    The real policy remains enabled. Its dedicated backend tests cover deferral;
    these browser journeys need an offer that can be presented immediately.
    """
    with sqlite3.connect(database) as connection:
        tenants = connection.execute("SELECT id, timezone FROM tenants").fetchall()
        for tenant_id, timezone in tenants:
            local = datetime.now(UTC).astimezone(ZoneInfo(timezone))
            quiet_start = local + timedelta(hours=6)
            quiet_end = quiet_start + timedelta(hours=1)
            connection.execute(
                "UPDATE tenants SET quiet_hours = ? WHERE id = ?",
                (json.dumps({"start": quiet_start.strftime("%H:%M"),
                             "end": quiet_end.strftime("%H:%M")}), tenant_id),
            )
    return len(tenants)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("suites", nargs="*", default=["test:ui", "test:workflows", "test:conversation", "test:extensions", "test:release", "test:outreach", "test:waitlist-deposit", "test:privacy-notice", "test:rtc-lifecycle", "test:companion", "test:platform"])
    parser.add_argument("--port", type=int, default=8137)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[1]
    output = project / "artifacts" / "ui"
    output.mkdir(parents=True, exist_ok=True)
    reports = []
    for suite in args.suites:
        if not suite.startswith("test:") or not suite.replace(":", "").replace("-", "").isalnum():
            raise ValueError("Invalid npm suite")
        with tempfile.TemporaryDirectory(prefix="hamava-ci-") as temporary:
            env = dict(os.environ)
            env.update({"ENVIRONMENT": "development", "DEMO_MODE": "true", "RUN_WORKER": "false",
                        "DATABASE_URL": "sqlite:///" + str(Path(temporary) / "demo.db"),
                        "PYTHONPATH": str(project / "backend"), "FRONTEND_DIST": str(project / "frontend/dist"),
                        "CORS_ORIGINS": f"http://127.0.0.1:{args.port},app://hamava,https://localhost",
                        "HAMAAVA_BASE_URL": f"http://127.0.0.1:{args.port}",
                        "HAMAAVA_ARTIFACTS_DIR": str(output / suite.replace(":", "-")),
                        "SMS_PROVIDER_APPROVED": "false", "PAYMENT_PROVIDER_APPROVED": "false",
                        "SPEECH_PROCESSOR_APPROVED": "false", "SPEECH_FALLBACK_APPROVED": "false",
                        "LIVEKIT_APPROVED": "false", "CALENDAR_PARTNER_APPROVED": "false",
                        "DIGEST_PROCESSOR_APPROVED": "false", "OUTBOUND_VOICE_APPROVED": "false",
                        "MEDIA_DID_TENANTS_JSON": "{}", "SMS_INBOUND_TENANTS_JSON": "{}",
                        # Functional journeys on a shared CI host do not measure latency SLOs.
                        "TOOL_TIMEOUT_MS": "30000"})
            log_path = output / (suite.replace(":", "-") + "-api.log")
            with log_path.open("w") as log:
                server = subprocess.Popen([sys.executable, "-m", "uvicorn", "receptionist.main:app", "--host", "127.0.0.1", "--port", str(args.port), "--no-access-log"], cwd=project, env=env, stdout=log, stderr=subprocess.STDOUT)
                try:
                    ready = False
                    startup_deadline = time.monotonic() + 120
                    while time.monotonic() < startup_deadline:
                        if server.poll() is not None:
                            raise RuntimeError(f"Synthetic API failed to start; inspect {log_path}")
                        try:
                            with urllib.request.urlopen(env["HAMAAVA_BASE_URL"] + "/health", timeout=1) as response:
                                ready = response.status == 200
                        except OSError:
                            pass
                        if ready:
                            break
                        time.sleep(0.5)
                    if not ready:
                        raise TimeoutError("Synthetic API was not ready in 120 seconds")
                    synthetic_tenants = prepare_synthetic_quiet_hours(Path(temporary) / "demo.db")
                    result = subprocess.run(["npm", "run", suite], cwd=project / "frontend", env=env, timeout=900)
                    reports.append({"suite": suite, "exit_code": result.returncode,
                                    "fresh_synthetic_database": True, "tool_timeout_ms": 30000,
                                    "synthetic_tenants_with_quiet_window_six_hours_ahead": synthetic_tenants})
                    if result.returncode:
                        break
                finally:
                    server.send_signal(signal.SIGTERM)
                    try:
                        server.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        server.kill()
                        server.wait(timeout=5)
                        raise RuntimeError("API failed graceful shutdown during browser verification")
    (output / "suite-results.json").write_text(json.dumps({"kind": "synthetic_functional_verification",
        "latency_slo_claim": False, "suites": reports,
        "passed": len(reports) == len(args.suites) and all(r["exit_code"] == 0 for r in reports)}, indent=2) + "\n")
    return 0 if len(reports) == len(args.suites) and all(r["exit_code"] == 0 for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
