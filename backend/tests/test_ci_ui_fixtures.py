"""Exercise time-independent isolated browser fixtures without a live browser."""
from datetime import datetime, timedelta
from pathlib import Path
import json
import sqlite3

import pytest

from scripts.ci_ui import prepare_outreach_attendance


def test_outreach_fixture_moves_attendance_and_occupancy_together(tmp_path: Path):
    database = tmp_path / "demo.db"
    scheduled = datetime(2026, 11, 3, 5, 30)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE appointments (id TEXT, status TEXT, start_at TEXT, "
            "end_at TEXT, occupied_until TEXT, attendance TEXT)"
        )
        connection.execute(
            "CREATE TABLE occupancy (owner_type TEXT, owner_id TEXT, minute INTEGER)"
        )
        connection.execute(
            "CREATE TABLE message_outbox (id TEXT, appointment_id TEXT, payload TEXT)"
        )
        connection.execute(
            "INSERT INTO appointments VALUES (?, ?, ?, ?, ?, ?)",
            ("demo-appt-1", "CONFIRMED", scheduled.isoformat(),
             (scheduled + timedelta(minutes=30)).isoformat(),
             (scheduled + timedelta(minutes=45)).isoformat(), None),
        )
        connection.execute(
            "INSERT INTO occupancy VALUES (?, ?, ?)",
            ("appointment", "demo-appt-1", 123456),
        )
        connection.execute(
            "INSERT INTO message_outbox VALUES (?, ?, ?)",
            ("notice-1", "demo-appt-1", json.dumps({"start_at": scheduled.isoformat()})),
        )
    prepare_outreach_attendance(database)
    with sqlite3.connect(database) as connection:
        start, end, occupied_until, attendance = connection.execute(
            "SELECT start_at, end_at, occupied_until, attendance FROM appointments"
        ).fetchone()
        assert attendance == "ATTENDED"
        assert datetime.fromisoformat(start) == scheduled - timedelta(days=1)
        assert datetime.fromisoformat(end) == scheduled - timedelta(days=1) + timedelta(minutes=30)
        assert datetime.fromisoformat(occupied_until) == scheduled - timedelta(days=1) + timedelta(minutes=45)
        assert connection.execute("SELECT minute FROM occupancy").fetchone()[0] == 123456 - 1440
        payload = json.loads(connection.execute("SELECT payload FROM message_outbox").fetchone()[0])
        assert datetime.fromisoformat(payload["start_at"]) == scheduled - timedelta(days=1)


def test_outreach_fixture_requires_confirmed_seed(tmp_path: Path):
    database = tmp_path / "demo.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE appointments (id TEXT, status TEXT, start_at TEXT, "
            "end_at TEXT, occupied_until TEXT, attendance TEXT)"
        )
    with pytest.raises(RuntimeError, match="confirmed demo appointment"):
        prepare_outreach_attendance(database)
