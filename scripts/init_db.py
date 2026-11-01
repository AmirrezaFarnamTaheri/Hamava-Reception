#!/usr/bin/env python3
"""Create or verify the current schema in a dedicated empty database."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from receptionist.db import engine  # noqa: E402
from receptionist.schema import initialize_schema  # noqa: E402


if __name__ == "__main__":
    initialize_schema(engine)
    print("Current database schema is ready.")
