#!/usr/bin/env python3
"""Synthetic contention checks in a unique, disposable PostgreSQL schema.

Never point load testing at a live service database. The script requires an
explicit acknowledgement, creates only its own random schema, and drops only
that schema afterward. It does not print credentials or change existing rows.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import math
import os
from pathlib import Path
import statistics
import sys
import threading
import time
from uuid import uuid4
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.orm import sessionmaker

from receptionist import models_ops, models_voice  # noqa: F401
from receptionist.core import ReceptionService
from receptionist.db import Base, now_utc
from receptionist.models import Appointment, IdempotencyRecord, MessageOutbox, Occupancy, Service
from receptionist.seed import seed_demo


def run(url: str, contenders: int) -> dict:
    if not url.startswith("postgresql"):
        raise ValueError("This check requires PostgreSQL")
    schema = "hamava_test_" + uuid4().hex
    admin = create_engine(url, pool_pre_ping=True)
    with admin.begin() as connection:
        version = connection.execute(text("SELECT version()" )).scalar()
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, pool_size=contenders, max_overflow=0, pool_timeout=30, pool_pre_ping=True)

    @event.listens_for(engine, "connect")
    def search_path(connection, _record):
        with connection.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}"')
        connection.commit()

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    report = {"synthetic_only": True, "database": version, "contenders": contenders,
              "started_at": now_utc().isoformat(), "cases": []}

    def day(offset):
        return (now_utc().astimezone(ZoneInfo("Asia/Tehran")) + timedelta(days=offset)).date().isoformat()

    def offered(offset, provider="provider-bahar-1", index=0):
        with factory() as db:
            return ReceptionService(db, "clinic-bahar").slots(provider, "service-consultation", day(offset))[index]["slot_id"]

    def race(name, count, operation, expected_winners=1):
        barrier = threading.Barrier(count, timeout=40)

        def one(index):
            with factory() as db:
                db.execute(text("SELECT 1"))  # Acquire every connection before the simultaneous start.
                barrier.wait()
                start = time.perf_counter()
                try:
                    result = operation(db, index)
                    return {"outcome": "success", "id": result["id"], "ms": (time.perf_counter()-start)*1000}
                except HTTPException as exc:
                    db.rollback()
                    return {"outcome": "rejected", "code": exc.status_code,
                            "reason": exc.detail.get("code"), "ms": (time.perf_counter()-start)*1000}

        start = time.perf_counter()
        with ThreadPoolExecutor(max_workers=count) as pool:
            results = list(pool.map(one, range(count)))
        winners = [r for r in results if r["outcome"] == "success"]
        latencies = sorted(r["ms"] for r in results)
        case = {"name": name, "attempts": count, "success_responses": len(winners),
                "distinct_committed_ids": len({r["id"] for r in winners}),
                "rejected": count-len(winners), "expected_success_responses": expected_winners,
                "elapsed_seconds": round(time.perf_counter()-start, 3),
                "median_ms": round(statistics.median(latencies), 2),
                "p95_ms": round(latencies[max(0, math.ceil(.95*len(latencies))-1)], 2),
                "rejection_codes": sorted({r["reason"] for r in results if r["outcome"] == "rejected"}),
                "passed": len(winners) == expected_winners and len({r["id"] for r in winners}) == 1
                          and all(r.get("code", 409) == 409 for r in results)}
        report["cases"].append(case)
        return winners

    def book(db, slot, key):
        return ReceptionService(db, "clinic-bahar", "synthetic-load-test").create_appointment(
            slot, "آزمون هم‌زمانی ساختگی", "09123456789", key, True)

    try:
        Base.metadata.create_all(engine)
        with factory() as db:
            seed_demo(db)
        slot = offered(3)
        race("one_slot_many_distinct_requests", contenders, lambda db, n: book(db, slot, f"load-distinct-{n:04}"))
        slot = offered(4)
        race("same_idempotency_key_replay", contenders, lambda db, n: book(db, slot, "load-replay-one-key"), contenders)
        with factory() as db:
            service = db.get(Service, "service-consultation")
            service.resource_ids = ["load-test-shared-chair"]
            db.commit()
        first, overlap = offered(5), offered(5, "provider-bahar-2", 1)
        race("different_doctors_overlapping_shared_resource", contenders,
             lambda db, n: book(db, first if n % 2 == 0 else overlap, f"load-shared-{n:04}"))
        slot = offered(6)
        race("exclusive_hold_claim", contenders,
             lambda db, n: ReceptionService(db, "clinic-bahar").hold(slot, f"load-call-{n:04}"))
        initial, target1, target2 = offered(7), offered(8), offered(9)
        with factory() as db:
            booking = book(db, initial, "load-reschedule-initial")
        race("same_booking_two_simultaneous_reschedules", 2,
             lambda db, n: ReceptionService(db, "clinic-bahar").reschedule_appointment(
                 booking["id"], [target1,target2][n], f"load-move-{n:04}", booking["version"], verified=True))
        with factory() as db:
            duplicates = db.execute(select(Occupancy.tenant_id, Occupancy.resource_id, Occupancy.minute)
                .group_by(Occupancy.tenant_id, Occupancy.resource_id, Occupancy.minute).having(func.count() > 1)).all()
            replay_count = db.scalar(select(func.count()).select_from(IdempotencyRecord)
                .where(IdempotencyRecord.key == "load-replay-one-key"))
            replay_record = db.scalar(select(IdempotencyRecord).where(IdempotencyRecord.key == "load-replay-one-key"))
            replay_notices = db.scalar(select(func.count()).select_from(MessageOutbox)
                .where(MessageOutbox.appointment_id == replay_record.entity_id))
            report["integrity"] = {"duplicate_resource_minutes": len(duplicates), "replay_records": replay_count,
                "replay_notifications": replay_notices, "passed": not duplicates and replay_count == 1 and replay_notices == 1}
            try:
                ReceptionService(db, "clinic-niloufar").get_appointment(booking["id"])
            except HTTPException as exc:
                report["tenant_isolation"] = {"status": exc.status_code, "passed": exc.status_code == 404}
            else:
                report["tenant_isolation"] = {"passed": False}
            report["total_appointments_including_seed"] = db.scalar(select(func.count()).select_from(Appointment))
        report["passed"] = all(x["passed"] for x in report["cases"]) and report["integrity"]["passed"] and report["tenant_isolation"]["passed"]
        report["notes"] = "One isolated local PostgreSQL host; a contention regression, not a production capacity or voice latency benchmark."
        return report
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-isolated-test-database", action="store_true", required=True)
    parser.add_argument("--contenders", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 2 <= args.contenders <= 200:
        parser.error("contenders must be 2–200")
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        parser.error("TEST_DATABASE_URL must point to an isolated PostgreSQL test database")
    result = run(url, args.contenders)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
