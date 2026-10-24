#!/usr/bin/env python3
"""Encrypt legacy billing notes; amounts and stable record identifiers stay intact."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from receptionist import model_registry  # noqa: E402,F401
from receptionist.db import SessionLocal, validate_schema  # noqa: E402
from receptionist.privacy_controls import migrate_legacy_billing_notes  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit the otherwise rolled-back preview")
    args = parser.parse_args()
    with SessionLocal() as db:
        validate_schema(db.get_bind())
        result = migrate_legacy_billing_notes(db)
        if args.apply:
            db.commit()
        else:
            db.rollback()
    print(json.dumps({"applied": args.apply, **result, "source_content_printed": False}))


if __name__ == "__main__":
    main()
