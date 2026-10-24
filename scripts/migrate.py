#!/usr/bin/env python3
"""Apply the explicit 0001 baseline and additive 0002 migration; never drop data."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from receptionist.db import engine  # noqa: E402
from receptionist.migrations import migrate  # noqa: E402


if __name__ == "__main__":
    version = migrate(engine)
    print(f"Schema version {version} is ready. No tables were dropped.")
