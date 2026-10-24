#!/usr/bin/env python3
"""Exercise real media control handlers in an isolated PostgreSQL schema.

This is a synthetic control-plane benchmark, not an HTTP, acoustic, GPU,
carrier, TURN, public-network or paid-channel capacity test. No media provider
is called. Every database write uses one random private schema, which is
dropped on exit. The explicit acknowledgement is required even for imports.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import statistics
import sys
import threading
import time
from unittest.mock import patch
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from receptionist import models_ext, models_ops, models_outreach, models_partner  # noqa: F401
from receptionist.config import settings
from receptionist.db import Base, now_utc
from receptionist.media_api import WorkerPoll, media_rooms
from receptionist.models import AuditEvent, Tenant, UsageEvent
from receptionist.models_voice import CallSession, MediaRegistration
from receptionist.security import encrypt
from receptionist.voice import configured_versions, end_session, new_session


LEVELS = (4, 8, 10, 20, 50, 80)


def latency(values):
    ordered = sorted(values)
    return {"samples": len(ordered), "median_ms": round(statistics.median(ordered), 3),
            "p95_ms": round(ordered[math.ceil(.95 * len(ordered)) - 1], 3),
            "p99_ms": round(ordered[math.ceil(.99 * len(ordered)) - 1], 3),
            "maximum_ms": round(ordered[-1], 3)} if ordered else {"samples": 0}


def safe_error(exc):
    result = {"error_type": type(exc).__name__}
    original = getattr(exc, "orig", None)
    code = getattr(original, "sqlstate", None)
    if isinstance(code, str) and code.isalnum() and len(code) <= 10:
        result["database_error_code"] = code
    return result


def run(url: str, levels=LEVELS, *, acknowledge_isolated_test_database=False):
    if not acknowledge_isolated_test_database:
        raise ValueError("Explicit isolated-test acknowledgement is required")
    if make_url(url).get_backend_name() != "postgresql":
        raise ValueError("This harness requires PostgreSQL")
    if settings.environment.lower() in {"production", "prod"}:
        raise ValueError("Run this synthetic harness in a separate development process")
    levels = tuple(levels)
    if not levels or len(set(levels)) != len(levels) or any(isinstance(n, bool) or not 2 <= n <= 80 for n in levels):
        raise ValueError("Levels must be distinct integers from 2 to 80")
    # A one-minute budget must have one full minute left in the UTC month.
    now = now_utc()
    month_end = (now.replace(day=1) + timedelta(days=32)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if (month_end - now).total_seconds() < 120:
        raise ValueError("Run outside the final two minutes of the UTC month")
    schema = "hamava_media_test_" + uuid4().hex
    admin = create_engine(url, pool_pre_ping=True)
    engine = None
    created = False
    report = {"schema_version": "1.0", "synthetic_only": True,
              "boundary": "Direct typed new_session/media_rooms/end_session handlers over independent PostgreSQL connections; no HTTP/media provider calls.",
              "started_at": now.isoformat(), "levels": list(levels), "worker_capacity": 8, "cases": [],
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "runtime_versions": configured_versions(),
              "limitations": ["No audio was transmitted; this is not a carrier/channel capacity result.",
                              "No STT/TTS/GPU throughput, first-audible latency, packet loss, jitter, TLS/TURN or mobile device behavior is measured.",
                              "Percentiles describe these finite local handler samples, not a production latency SLO.",
                              "The existing SQLite and PostgreSQL application schemas are never used or mutated."]}
    try:
        with admin.begin() as connection:
            report["database_version"] = connection.execute(text("SELECT version()")).scalar()
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        engine = create_engine(url, pool_size=max(levels) + 2, max_overflow=0, pool_timeout=35, pool_pre_ping=True)

        @event.listens_for(engine, "connect")
        def private_schema(connection, _record):
            with connection.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{schema}"')
                cursor.execute("SET statement_timeout TO '30s'")
                cursor.execute("SET lock_timeout TO '15s'")
            connection.commit()

        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine, expire_on_commit=False)

        def concurrent(count, operation, *, simultaneous=True):
            barrier = threading.Barrier(count, timeout=40) if simultaneous else None

            def execute(index):
                with factory() as db:
                    backend_id, current_schema = db.execute(text("SELECT pg_backend_pid(), current_schema()")).one()
                    if current_schema != schema:
                        raise RuntimeError("Isolation verification failed before operation")
                    if barrier:
                        barrier.wait()
                    start = time.perf_counter()
                    try:
                        value = operation(db, index)
                        return {"outcome": "success", "value": value, "backend": backend_id,
                                "ms": (time.perf_counter() - start) * 1000}
                    except HTTPException as exc:
                        db.rollback()
                        return {"outcome": "rejected", "status": exc.status_code,
                                "code": exc.detail.get("code") if isinstance(exc.detail, dict) else "HTTP_ERROR",
                                "backend": backend_id, "ms": (time.perf_counter() - start) * 1000}
                    except Exception as exc:
                        db.rollback()
                        return {"outcome": "error", **safe_error(exc), "backend": backend_id,
                                "ms": (time.perf_counter() - start) * 1000}

            with ThreadPoolExecutor(max_workers=min(count, max(levels) + 2)) as pool:
                return list(pool.map(execute, range(count)))

        def add_call(db, tenant_id, index, with_room):
            channel = "sip" if index % 2 else "browser_text"
            row, token = new_session(db, db.get(Tenant, tenant_id), channel)
            if with_room:
                row.channel, row.media_room, row.media_participant = "webrtc", "synthetic-" + row.id, "caller-" + row.id
                db.add(MediaRegistration(call_uuid=row.id, call_id=row.id, tenant_id=tenant_id,
                                        token_encrypted=encrypt(token), expires_at=row.expires_at))
                db.commit()
            return {"id": row.id, "original_channel": channel}

        def worker_poll(db, worker_id, active=()):
            result = media_rooms(WorkerPoll(worker_id=worker_id, active_sessions=list(active), capacity=100), db)
            return {"rooms": [item["session_id"] for item in result["rooms"]],
                    "renewed": result["renewed_sessions"], "revoked": result["revoked_sessions"],
                    "capacity": result["capacity"]}

        # These keys sign only synthetic tokens. No socket/provider API is used.
        media_environment = {"LIVEKIT_APPROVED": "true", "LIVEKIT_URL": "wss://synthetic-media.example.test",
                             "LIVEKIT_API_KEY": "synthetic-load-key", "LIVEKIT_API_SECRET": secrets.token_urlsafe(40),
                             "MAX_LIVEKIT_ROOMS_PER_WORKER": "8"}
        with patch.dict(os.environ, media_environment):
            for level in levels:
                case_started = time.perf_counter()
                tenant_id, budget_id = f"media-load-{level}", f"media-budget-{level}"
                with factory() as db:
                    db.add_all([Tenant(id=tenant_id, name=f"Synthetic media load {level}", slug=tenant_id,
                                       mode="ai_primary", monthly_minute_budget=level * 30 + 100),
                                Tenant(id=budget_id, name=f"Synthetic minute cap {level}", slug=budget_id,
                                       mode="ai_primary", monthly_minute_budget=1)])
                    db.commit()
                with patch.dict(os.environ, {"MAX_CONCURRENT_CALLS_PER_TENANT": str(level)}):
                    admitted = concurrent(level + 2, lambda db, index: add_call(db, tenant_id, index, True))
                successful = [r for r in admitted if r["outcome"] == "success"]
                rejected = [r for r in admitted if r["outcome"] == "rejected"]
                call_ids = [r["value"]["id"] for r in successful]
                admission = {"attempts": level + 2, "admitted": len(call_ids), "distinct_calls": len(set(call_ids)),
                             "rejected": len(rejected), "rejection_codes": dict(Counter(r["code"] for r in rejected)),
                             "independent_connections": len({r["backend"] for r in admitted}),
                             "latency": latency([r["ms"] for r in admitted]),
                             "scope": "new_session plus durable synthetic room registration",
                             "passed": len(call_ids) == level and len(set(call_ids)) == level and len(rejected) == 2
                                       and all(r["code"] == "CAPACITY" for r in rejected)}
                with factory() as db:
                    active = list(db.scalars(select(CallSession).where(CallSession.tenant_id == tenant_id,
                                                                     CallSession.ended_at.is_(None))))
                    seconds = [(r.expires_at - r.started_at).total_seconds() for r in active]
                    reservations = {"active_sessions": len(active), "reserved_seconds": round(sum(seconds), 3),
                                    "budget_seconds": (level * 30 + 100) * 60,
                                    "maximum_call_seconds": max(seconds, default=0),
                                    "passed": len(active) == level and all(0 < duration <= 1800 for duration in seconds)
                                              and sum(seconds) <= (level * 30 + 100) * 60}
                workers = [f"synthetic-worker-{level}-{n}" for n in range(max(1, math.ceil(level / 8)))]
                owned = {worker: [] for worker in workers}
                claimed_ids, poll_samples, poll_errors = [], [], []
                first = concurrent(4, lambda db, _: worker_poll(db, workers[0]))
                for result in first:
                    poll_samples.append(result["ms"])
                    if result["outcome"] != "success":
                        poll_errors.append({key: value for key, value in result.items() if key not in {"backend", "ms", "value"}})
                        continue
                    owned[workers[0]].extend(result["value"]["rooms"])
                    claimed_ids.extend(result["value"]["rooms"])
                first_claims = len(owned[workers[0]])
                rounds = 0
                for rounds in range(1, len(workers) + 3):
                    batch = concurrent(len(workers), lambda db, index: worker_poll(db, workers[index], owned[workers[index]]))
                    for index, result in enumerate(batch):
                        poll_samples.append(result["ms"])
                        if result["outcome"] != "success":
                            poll_errors.append({key: value for key, value in result.items() if key not in {"backend", "ms", "value"}})
                            continue
                        value = result["value"]
                        if value["revoked"] or value["capacity"] != 8 or set(value["renewed"]) != set(owned[workers[index]]):
                            poll_errors.append({"error_type": "UnexpectedRenewalOrCapacity"})
                        owned[workers[index]].extend(value["rooms"])
                        claimed_ids.extend(value["rooms"])
                    if len(set(claimed_ids)) == level:
                        break
                with factory() as db:
                    assigned = dict(db.execute(select(CallSession.media_worker_id, func.count()).where(
                        CallSession.tenant_id == tenant_id, CallSession.media_worker_lease > now_utc(),
                        CallSession.ended_at.is_(None)).group_by(CallSession.media_worker_id)).all())
                assignment = {"workers": len(workers), "server_max_rooms_per_worker": 8,
                              "same_worker_simultaneous_polls": 4, "first_worker_claimed": first_claims,
                              "claim_rounds": rounds, "distinct_assigned_calls": len(set(claimed_ids)),
                              "duplicate_dispatches": len(claimed_ids) - len(set(claimed_ids)),
                              "maximum_assigned_per_worker": max(assigned.values(), default=0),
                              "owned_counts": sorted(assigned.values()), "poll_latency": latency(poll_samples),
                              "errors": poll_errors,
                              "passed": first_claims == min(level, 8) and len(set(claimed_ids)) == level
                                        and len(claimed_ids) == level and sum(assigned.values()) == level
                                        and max(assigned.values(), default=0) <= 8 and not poll_errors}
                with patch.dict(os.environ, {"MAX_CONCURRENT_CALLS_PER_TENANT": str(level + 2)}):
                    limited = concurrent(level, lambda db, index: add_call(db, budget_id, index, False))
                budget_success = [r for r in limited if r["outcome"] == "success"]
                budget_rejected = [r for r in limited if r["outcome"] == "rejected"]
                with factory() as db:
                    budget_calls = list(db.scalars(select(CallSession).where(CallSession.tenant_id == budget_id)))
                    reserved = sum((r.expires_at - r.started_at).total_seconds() for r in budget_calls)
                budget = {"attempts": level, "budget_seconds": 60, "admitted": len(budget_success),
                          "reserved_seconds": round(reserved, 3), "rejected": len(budget_rejected),
                          "rejection_codes": dict(Counter(r["code"] for r in budget_rejected)),
                          "latency": latency([r["ms"] for r in limited]),
                          "passed": len(budget_success) == 1 and len(budget_rejected) == level - 1
                                    and all(r["code"] == "BUDGET_LIMIT" for r in budget_rejected) and 59 <= reserved <= 60}
                all_calls = call_ids + [r["value"]["id"] for r in budget_success]
                cleanup = concurrent(len(all_calls) * 2,
                    lambda db, index: end_session(db, db.get(CallSession, all_calls[index // 2])), simultaneous=False)
                with factory() as db:
                    remaining = db.scalar(select(func.count()).select_from(CallSession).where(
                        CallSession.id.in_(all_calls), CallSession.ended_at.is_(None)))
                    usage = dict(db.execute(select(UsageEvent.call_id, func.count()).where(
                        UsageEvent.call_id.in_(all_calls), UsageEvent.kind == "call_seconds").group_by(UsageEvent.call_id)).all())
                    audits = db.scalar(select(func.count()).select_from(AuditEvent).where(
                        AuditEvent.entity_id.in_(all_calls), AuditEvent.action == "call.ended"))
                finalization = {"requests": len(cleanup), "sessions": len(all_calls), "active_remaining": remaining,
                                "call_duration_events": sum(usage.values()), "max_duration_events_per_call": max(usage.values(), default=0),
                                "ended_audits": audits, "latency": latency([r["ms"] for r in cleanup]),
                                "passed": not remaining and len(usage) == len(all_calls) and all(count == 1 for count in usage.values())
                                          and audits == len(all_calls) and all(r["outcome"] == "success" for r in cleanup)}
                case = {"target_sessions": level, "admission": admission, "reservations": reservations,
                        "worker_assignment": assignment, "one_minute_budget": budget, "idempotent_cleanup": finalization,
                        "elapsed_seconds": round(time.perf_counter() - case_started, 3)}
                case["passed"] = all(case[key]["passed"] for key in
                    ("admission", "reservations", "worker_assignment", "one_minute_budget", "idempotent_cleanup"))
                report["cases"].append(case)
                print(json.dumps({"target_sessions": level, "passed": case["passed"],
                                  "admitted": len(call_ids), "worker_bound": assignment["maximum_assigned_per_worker"]}), flush=True)
        report["passed"] = all(case["passed"] for case in report["cases"])
    finally:
        if engine:
            engine.dispose()
        if created:
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                report["temporary_schema_removed"] = connection.execute(
                    text("SELECT count(*) FROM pg_namespace WHERE nspname=:schema"), {"schema": schema}).scalar() == 0
        admin.dispose()
    report["finished_at"] = now_utc().isoformat()
    report["passed"] = report["passed"] and report.get("temporary_schema_removed", False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--acknowledge-isolated-test-database", action="store_true", required=True)
    parser.add_argument("--levels", default=",".join(map(str, LEVELS)))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url:
        parser.error("TEST_DATABASE_URL must point to an isolated PostgreSQL test database")
    try:
        result = run(url, tuple(int(value) for value in args.levels.split(",")),
                     acknowledge_isolated_test_database=args.acknowledge_isolated_test_database)
    except Exception as exc:
        result = {"synthetic_only": True, "passed": False, **safe_error(exc),
                  "notes": "The harness failed; investigate privately. Credentials and SQL parameters are intentionally omitted."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"passed": result["passed"], "report": str(args.output), "cases": len(result.get("cases", []))}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
