"""Bounded core background recovery and cooperative process shutdown."""
import asyncio
import logging
import os
import signal
from datetime import timedelta

from sqlalchemy import delete, or_, select

from .db import now_utc
from .models_core import CalendarAuthority, ExternalCalendarOperation, StaffTokenRevocation
from .models_voice import CallSession

log = logging.getLogger("receptionist")


def shutdown_event():
    event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for number in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(number, event.set)
        except (NotImplementedError, RuntimeError):
            pass  # Windows service wrappers trigger the supplied event instead.
    return event


async def drain_tasks(tasks, *, grace=None):
    tasks = set(tasks)
    if not tasks:
        return {"completed": 0, "cancelled": 0}
    grace = float(grace if grace is not None else os.getenv("SHUTDOWN_GRACE_SECONDS", "20"))
    done, pending = await asyncio.wait(tasks, timeout=max(0, grace))
    for task in pending:
        task.cancel()
    unfinished = set()
    if pending:
        _, unfinished = await asyncio.wait(pending, timeout=min(5, max(.05, grace / 4)))
    for task in tasks - unfinished:
        if not task.cancelled():
            task.exception()  # Retrieve terminal exceptions without an unbounded await.
    for task in unfinished:
        task.cancel()
    result = {"completed": len(done), "cancelled": len(pending)}
    if unfinished:
        log.warning("shutdown_cleanup_incomplete")
        result["cleanup_incomplete"] = len(unfinished)
    return result


async def run_core_jobs(db, *, limit=3, budget_seconds=20):
    """At most three remote logical operations and twenty seconds per tick.

    A cancelled external write retains its committed SENDING lease and started
    money reservation. Recovery can only reconcile it. No immediate blind retry.
    Fair oldest-first queues include every active tenant, without a first-N bias.
    """
    from .calendar_bridge import execute_operation, poll_changes
    from .providers import ProviderError, enabled
    from .provider_control import PROVIDERS, probe
    from .voice import TurnInput, context, execute_turn
    from .models import Tenant
    from .models_core import CalendarSyncState, ProviderObservation
    from fastapi import HTTPException
    from starlette.concurrency import run_in_threadpool
    from sqlalchemy import and_, literal, union_all

    maximum = max(1, min(limit, 3))
    done = examined = 0
    deadline = False
    try:
        async with asyncio.timeout(max(1, min(budget_seconds, 20))):
            now = now_utc()
            # One mutation recovery, one revision poll, one dependency probe per
            # tick prevents any category from starving the others indefinitely.
            operation = db.scalar(select(ExternalCalendarOperation).where(
                ExternalCalendarOperation.status.in_(["PENDING", "SENDING", "UNKNOWN"]),
                or_(ExternalCalendarOperation.lease_until.is_(None), ExternalCalendarOperation.lease_until <= now),
                or_(ExternalCalendarOperation.status == "PENDING", ExternalCalendarOperation.updated_at <= now - timedelta(seconds=30)))
                .order_by(ExternalCalendarOperation.updated_at, ExternalCalendarOperation.id).limit(1))
            if operation:
                examined += 1
                try:
                    result = await execute_operation(db, operation)
                    if result["operation_status"] == "SUCCEEDED":
                        done += 1
                        if operation.call_id:
                            call = db.get(CallSession, operation.call_id)
                            if (call and call.tenant_id == operation.tenant_id and not call.ended_at and call.expires_at > now_utc()
                                    and call.state == "WAIT_CALENDAR" and context(call).get("pending_tool", {}).get("id") == operation.id):
                                await run_in_threadpool(execute_turn, db, call, TurnInput(text="ادامه بررسی تقویم", request_id="calendar-result:" + operation.id))
                except (HTTPException, ProviderError):
                    db.rollback()
                    log.warning("calendar_recovery_deferred")
            if examined < maximum:
                profile = db.scalar(select(CalendarAuthority).outerjoin(CalendarSyncState, CalendarSyncState.tenant_id == CalendarAuthority.tenant_id)
                    .where(CalendarAuthority.kind == "external", CalendarAuthority.expires_at > now,
                        or_(CalendarSyncState.last_poll_at.is_(None), CalendarSyncState.last_poll_at < now - timedelta(seconds=60)))
                    .order_by(CalendarSyncState.last_poll_at.asc().nullsfirst(), CalendarAuthority.tenant_id).limit(1))
                if profile:
                    examined += 1
                    try:
                        await poll_changes(db, profile.tenant_id)
                    except (ProviderError, HTTPException):
                        db.rollback()
                        from .core_policy import lock
                        lock(db, profile.tenant_id)
                        state = db.get(CalendarSyncState, profile.tenant_id)
                        if not state:
                            state = CalendarSyncState(tenant_id=profile.tenant_id, revision=0)
                            db.add(state)
                        state.status, state.error_code, state.last_poll_at = "SYNC_REQUIRED", "POLL_UNAVAILABLE", now_utc()
                        db.commit()
            if examined < maximum:
                queries = []
                stale = now - timedelta(seconds=int(os.getenv("PROVIDER_HEALTH_STALE_SECONDS", "120")))
                for provider in ("speech_primary", "speech_fallback", "calendar_primary", "digest_gateway"):
                    if enabled(PROVIDERS[provider][0]) and os.getenv(PROVIDERS[provider][2]):
                        queries.append(select(Tenant.id.label("tenant_id"), literal(provider).label("provider"), ProviderObservation.checked_at.label("checked_at"))
                            .outerjoin(ProviderObservation, and_(ProviderObservation.tenant_id == Tenant.id, ProviderObservation.provider_key == provider))
                            .where(Tenant.active.is_(True), or_(ProviderObservation.checked_at.is_(None), ProviderObservation.checked_at <= stale)))
                if queries:
                    candidates = union_all(*queries).subquery()
                    candidate = db.execute(select(candidates).order_by(candidates.c.checked_at.asc().nullsfirst(), candidates.c.tenant_id).limit(1)).first()
                    if candidate:
                        examined += 1
                        try:
                            await probe(db, candidate.tenant_id, candidate.provider)
                        except (ProviderError, HTTPException):
                            db.rollback()
                            from .provider_control import observation
                            observation(db, candidate.tenant_id, candidate.provider, "degraded", "PROBE_UNAVAILABLE")
                            db.commit()
            db.execute(delete(StaffTokenRevocation).where(StaffTokenRevocation.expires_at < now - timedelta(days=1)))
            db.commit()
    except TimeoutError:
        db.rollback()
        deadline = True
        log.warning("core_tick_deadline")
    return {"examined": examined, "completed": done, "deadline_reached": deadline, "max_remote_operations": maximum}
