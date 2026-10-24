"""Actual process-signal delivery, with synthetic in-flight work and handle cleanup."""
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX SIGTERM process drill")
@pytest.mark.parametrize("mode", ["cooperative", "deadline"])
def test_standalone_worker_sigterm_drains_or_cancels_and_closes_handles(tmp_path, mode):
    code = """
import asyncio, os
from pathlib import Path
import receptionist.worker as worker
root = Path(os.environ['SHUTDOWN_TEST_DIRECTORY'])
async def in_flight(stop):
    (root / 'started').write_text('synthetic')
    try:
        await stop.wait()
        await asyncio.sleep(0.1 if os.environ['SHUTDOWN_TEST_MODE'] == 'cooperative' else 60)
        (root / 'completed').write_text('synthetic')
    finally:
        (root / 'closed').write_text('synthetic')
worker.worker_loop = in_flight
asyncio.run(worker.run_worker())
"""
    environment = dict(os.environ, SHUTDOWN_TEST_DIRECTORY=str(tmp_path), SHUTDOWN_TEST_MODE=mode,
        SHUTDOWN_GRACE_SECONDS="1", ENVIRONMENT="development", DEMO_MODE="false", RUN_WORKER="false")
    process = subprocess.Popen([sys.executable, "-c", code], env=environment,
        cwd=Path(__file__).resolve().parents[2], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        deadline = time.monotonic() + 20
        while not (tmp_path / "started").exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert (tmp_path / "started").exists(), process.communicate(timeout=1)
        process.send_signal(signal.SIGTERM)
        output, error = process.communicate(timeout=8)
        assert process.returncode == 0, (output, error)
        assert (tmp_path / "closed").exists()
        assert (tmp_path / "completed").exists() == (mode == "cooperative")
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
