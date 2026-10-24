"""Low-cardinality, patient-free operational telemetry and explicit alerts."""
from collections import defaultdict
from datetime import timedelta
import hmac
import json
import logging
import math
import os
import re
import threading

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .core import call_minutes
from .db import get_db, now_utc
from .models import AuditEvent, MessageOutbox, StaffTask, Tenant, UsageEvent
from .models_voice import CallSession, MediaHeartbeat, VoiceTurn
from .models_ops_control import TraceEvent
from .security import Actor, bearer, fail, require_permissions

router = APIRouter(tags=["operations telemetry"])
_lock = threading.Lock()
_counts = defaultdict(int)
_latency = defaultdict(lambda: {"count": 0, "sum": 0.0, "buckets": defaultdict(int)})
BUCKETS = (.05, .1, .25, .5, 1., 2., 5., 10.)


class SafeJSONFormatter(logging.Formatter):
    """Only static event names and an explicit safe field list enter app logs."""
    def format(self, record):
        event = record.msg if isinstance(record.msg, str) and re.fullmatch(r"[a-z_]{3,80}", record.msg) else "redacted_log_event"
        value = {"timestamp": now_utc().isoformat(), "level": record.levelname, "event": event}
        for key in ("request_id", "call_id", "error_type", "database_error_code"):
            candidate = getattr(record, key, None)
            if isinstance(candidate, str) and re.fullmatch(r"[a-zA-Z0-9_-]{1,120}", candidate):
                value[key] = candidate
        return json.dumps(value, separators=(",", ":"))


def safe_error_fields(exc: Exception) -> dict:
    """Expose a driver-defined code, never SQL, parameters or exception text."""
    result = {"error_type": type(exc).__name__}
    original = getattr(exc, "orig", None)
    code = getattr(original, "sqlite_errorname", None) or getattr(original, "sqlstate", None)
    if isinstance(code, str) and re.fullmatch(r"[A-Z0-9_]{3,60}", code):
        result["database_error_code"] = code
    return result


def configure_logging():
    logger = logging.getLogger("receptionist")
    if not any(getattr(handler, "hamava_safe", False) for handler in logger.handlers):
        handler = logging.StreamHandler()
        handler.hamava_safe = True
        handler.setFormatter(SafeJSONFormatter())
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False


def record_http(route: str, method: str, status: int, elapsed: float):
    # Only router templates are passed here, never a raw URL or query string.
    route = route[:150] if route and re.fullmatch(r"[/a-zA-Z0-9_{}:.-]+", route) else "unmatched"
    method = method if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"} else "OTHER"
    with _lock:
        _counts[(route, method, f"{status//100}xx")] += 1
        item = _latency[(route, method)]
        item["count"] += 1
        item["sum"] += elapsed
        for boundary in BUCKETS:
            if elapsed <= boundary:
                item["buckets"][boundary] += 1


def health_snapshot(db, tenant_id=None):
    now = now_utc()
    message_scope = [MessageOutbox.tenant_id == tenant_id] if tenant_id else []
    task_scope = [StaffTask.tenant_id == tenant_id] if tenant_id else []
    call_scope = [CallSession.tenant_id == tenant_id] if tenant_id else []
    audit_scope = [AuditEvent.tenant_id == tenant_id] if tenant_id else []
    oldest = db.scalar(select(func.min(MessageOutbox.created_at)).where(*message_scope,
        MessageOutbox.status == "QUEUED", MessageOutbox.available_at <= now))
    oldest_task = db.scalar(select(func.min(StaffTask.created_at)).where(*task_scope, StaffTask.status.in_(["OPEN", "IN_PROGRESS", "PENDING", "CALLBACK"])))
    counts = dict(db.execute(select(MessageOutbox.status, func.count()).where(*message_scope).group_by(MessageOutbox.status)).all())
    active_calls = db.scalar(select(func.count()).select_from(CallSession).where(*call_scope,
        CallSession.ended_at.is_(None), CallSession.expires_at > now))
    incidents = dict(db.execute(select(AuditEvent.action, func.count()).where(*audit_scope,
        AuditEvent.action.in_(["safety.false_confirmation", "safety.tenant_exposure"]),
        AuditEvent.created_at >= now-timedelta(hours=24)).group_by(AuditEvent.action)).all())
    alerts = []
    queue_age = max(0, (now-oldest).total_seconds()) if oldest else 0
    task_age = max(0, (now-oldest_task).total_seconds()) if oldest_task else 0
    if queue_age > 180:
        alerts.append({"code": "OUTBOX_DELAY", "severity": "warning", "action": "Check worker and approved provider status; reconcile UNKNOWN before retrying."})
    if counts.get("UNKNOWN", 0):
        alerts.append({"code": "UNKNOWN_DELIVERY", "severity": "warning", "action": "Reconcile provider records; do not resend automatically."})
    if task_age > 900:
        alerts.append({"code": "STAFF_QUEUE_DELAY", "severity": "warning", "action": "Assign staff coverage or pause automated intake."})
    for kind, count in incidents.items():
        if count:
            alerts.append({"code": kind.upper().replace(".", "_"), "severity": "critical", "action": "Pause automation and open the incident runbook."})
    budget_percent = 0.0
    if tenant_id:
        tenant = db.get(Tenant, tenant_id)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        used = sum(call_minutes(row) for row in db.scalars(select(UsageEvent).where(
            UsageEvent.tenant_id == tenant_id, UsageEvent.created_at >= start)))
        budget_percent = used / tenant.monthly_minute_budget * 100 if tenant.monthly_minute_budget else 0
        if budget_percent >= 80:
            alerts.append({"code": "MINUTE_BUDGET", "severity": "warning", "action": "Review usage and staffed coverage before increasing the authorized budget."})
    workers = db.scalar(select(func.count()).select_from(MediaHeartbeat).where(MediaHeartbeat.updated_at > now-timedelta(seconds=20)))
    return {"as_of": now.isoformat(), "active_calls": active_calls, "due_outbox_oldest_seconds": round(queue_age),
        "open_task_oldest_seconds": round(task_age), "notifications_by_status": counts,
        "live_media_workers": workers, "minute_budget_used_percent": round(budget_percent, 2),
        "reported_safety_incidents_24h": incidents, "alerts": alerts,
        "safety_note": "An empty incident ledger does not establish zero unobserved incidents."}


@router.get("/api/v1/operations/health")
def clinic_health(actor: Actor = Depends(require_permissions("health:read")), db: Session = Depends(get_db)):
    return health_snapshot(db, actor.tenant_id)


def latency_distribution(values):
    values = sorted(float(value) for value in values if math.isfinite(float(value)) and value >= 0)
    return {"count": len(values), **{f"p{int(q*100)}_ms": values[max(0, math.ceil(q*len(values))-1)] if values else None
                                  for q in (.5, .95, .99)}}


@router.get("/api/v1/operations/latency")
def latency_report(hours: int = Query(default=24, ge=1, le=168),
                   actor: Actor = Depends(require_permissions("health:read")), db: Session = Depends(get_db)):
    cutoff = now_utc()-timedelta(hours=hours)
    kinds = {"latency_stt_ms": "stt_provider", "latency_tts_ms": "tts_or_static_cache",
             "latency_handoff_ms": "staff_task_to_verified_room_join"}
    rows = list(db.scalars(select(UsageEvent).where(UsageEvent.tenant_id == actor.tenant_id,
        UsageEvent.created_at >= cutoff, UsageEvent.kind.in_(kinds)).order_by(UsageEvent.created_at.desc()).limit(10001)))
    stages = {name: latency_distribution(row.quantity for row in rows[:10000] if row.kind == kind)
              for kind, name in kinds.items()}
    turns = list(db.scalars(select(VoiceTurn.latency_ms).where(VoiceTurn.tenant_id == actor.tenant_id,
        VoiceTurn.created_at >= cutoff).order_by(VoiceTurn.created_at.desc()).limit(10001)))
    stages["conversation_and_calendar"] = latency_distribution(turns[:10000])
    from .tool_gateway import TOOL_NAMES
    tools = list(db.scalars(select(TraceEvent).where(TraceEvent.tenant_id == actor.tenant_id,
        TraceEvent.created_at >= cutoff, TraceEvent.event.in_(["tool." + name for name in TOOL_NAMES]))
        .order_by(TraceEvent.created_at.desc()).limit(10001)))
    for name in TOOL_NAMES:
        stages["tool_" + name] = latency_distribution(event.attributes["duration_ms"] for event in tools[:10000]
            if event.event == "tool." + name and event.attributes.get("outcome") == "completed"
            and event.attributes.get("status") == "committed")
    return {"hours": hours, "stages": stages, "truncated": len(rows) > 10000 or len(turns) > 10000 or len(tools) > 10000,
        "percentile_method": "nearest_rank", "successful_observations_only": True,
        "end_to_first_audible": "Measure at the caller receiver; server HTTP/TTS completion is not audible playback.",
        "model_stage": "No generative language model in the deterministic administrative engine.",
        "tool_stage": "Local tool dispatch only; queued, failed and rolled-back attempts remain in scoped call traces and are excluded from successful percentiles.",
        "cost_meter": False}


def metrics_auth(credentials=Depends(bearer)):
    expected = os.getenv("METRICS_TOKEN", "")
    if len(expected) < 32 or not credentials or not hmac.compare_digest(expected, credentials.credentials):
        fail(401, "METRICS_AUTH_REQUIRED", "دسترسی پایش مجاز نیست.")


@router.get("/metrics", dependencies=[Depends(metrics_auth)])
def metrics(db: Session = Depends(get_db)):
    rows = ["# TYPE hamava_http_requests_total counter", "# TYPE hamava_http_seconds histogram"]
    with _lock:
        for (route, method, status), count in sorted(_counts.items()):
            rows.append(f'hamava_http_requests_total{{route="{route}",method="{method}",class="{status}"}} {count}')
        for (route, method), data in sorted(_latency.items()):
            labels = f'route="{route}",method="{method}"'
            for boundary in BUCKETS:
                rows.append(f'hamava_http_seconds_bucket{{{labels},le="{boundary}"}} {data["buckets"][boundary]}')
            rows.extend([f'hamava_http_seconds_bucket{{{labels},le="+Inf"}} {data["count"]}',
                         f'hamava_http_seconds_count{{{labels}}} {data["count"]}',
                         f'hamava_http_seconds_sum{{{labels}}} {data["sum"]}'])
    state = health_snapshot(db)
    from .providers import speech_cache_stats
    for field, value in speech_cache_stats().items():
        rows.append(f"hamava_speech_cache_{field} {value}")
    for field in ("active_calls", "due_outbox_oldest_seconds", "open_task_oldest_seconds", "live_media_workers"):
        rows.extend([f"# TYPE hamava_{field} gauge", f"hamava_{field} {state[field]}"])
    rows.append("# TYPE hamava_outbox_records gauge")
    for status, count in state["notifications_by_status"].items():
        if re.fullmatch(r"[A-Z_]+", status):
            rows.append(f'hamava_outbox_records{{status="{status}"}} {count}')
    rows.append("# TYPE hamava_reported_safety_incidents_24h gauge")
    for kind in ("safety.false_confirmation", "safety.tenant_exposure"):
        rows.append(f'hamava_reported_safety_incidents_24h{{kind="{kind}"}} {state["reported_safety_incidents_24h"].get(kind,0)}')
    return Response("\n".join(rows)+"\n", media_type="text/plain; version=0.0.4")
