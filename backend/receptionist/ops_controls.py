"""Durable event chains and actually dispatched in-app on-call escalations."""
from __future__ import annotations

from datetime import timedelta
import re
from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .billing import IDENTIFIER, MICRO, current_policy, digest, expire_unused_reservations, lock_tenant, spending
from .db import get_db, now_utc
from .models import Appointment, AuditEvent, Membership, MessageOutbox, StaffTask, Tenant, User
from .models_finance import CostReservation, UsageCharge
from .models_ops_control import AlertDelivery, OnCallPolicy, OperationalAlert, TraceEvent
from .operations import audit
from .privacy_controls import expire_artifacts, purge_administrative_transcripts, redact_text
from .schemas import StrictModel
from .security import Actor, fail, has_permission, require_permissions

router = APIRouter(prefix="/api/v1/operations")
VERSION_KEYS = {"app", "fsm", "locale", "calendar", "adapter", "configured_asr", "configured_tts", "model", "policy", "client"}
ATTRIBUTE_KEYS = {"duration_ms", "quantity", "unit", "outcome", "error_code", "cost_micro_toman", "reservation_id", "retry", "status", "http_status", "bytes", "queue_depth"}
QUEUE_THRESHOLDS = {"outbox_due_seconds": 180, "staff_wait_seconds": 900, "failed_deliveries_24h": 5}


def safe_attributes(values):
    if set(values) - ATTRIBUTE_KEYS:
        fail(422, "UNCLASSIFIED_TRACE_FIELD", "Trace attributes are a closed non-content allowlist.")
    for key, value in values.items():
        if key == "reservation_id":
            if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", value):
                fail(422, "INVALID_TRACE_RESERVATION", "Reservation correlation requires a canonical opaque identifier.")
            # A generated UUID can coincidentally contain a phone-like digit
            # run. Existence and scope are checked below instead of redacting it.
            continue
        if isinstance(value, bool) or isinstance(value, int):
            continue
        if not isinstance(value, str) or len(value) > 160 or not re.fullmatch(IDENTIFIER, value) or redact_text(value) != value:
            fail(422, "SENSITIVE_TRACE_VALUE", "Trace values must be opaque codes or bounded numbers, never free text.")


def append_trace(db, tenant_id: str, event_key: str, event: str, *, call_id=None, turn_id=None,
                 appointment_id=None, job_id=None, provider=None, parent_id=None, versions=None, attributes=None,
                 occurred_at=None):
    if not re.fullmatch(IDENTIFIER, event_key) or not re.fullmatch(r"[a-z][a-z0-9_.]{1,79}", event):
        fail(422, "INVALID_TRACE_EVENT", "Trace events require stable opaque identifiers.")
    versions, attributes = versions or {}, attributes or {}
    safe_attributes(attributes)
    if attributes.get("reservation_id"):
        reservation = db.get(CostReservation, attributes["reservation_id"])
        if (not reservation or reservation.tenant_id != tenant_id
                or provider and reservation.provider != provider
                or call_id and reservation.call_id != call_id):
            fail(404, "TRACE_RESERVATION_NOT_FOUND", "Reservation does not belong to this clinic and event scope.")
    if set(versions) - VERSION_KEYS or any(not isinstance(v, str) or not re.fullmatch(IDENTIFIER, v) for v in versions.values()):
        fail(422, "INVALID_TRACE_VERSION", "Supply only supported version identifiers.")
    if call_id:
        from .models_voice import CallSession, VoiceTurn
        call = db.get(CallSession, call_id)
        if not call or call.tenant_id != tenant_id:
            fail(404, "TRACE_CALL_NOT_FOUND", "Call does not belong to this clinic.")
        if turn_id:
            turn = db.get(VoiceTurn, turn_id)
            if not turn or turn.tenant_id != tenant_id or turn.call_id != call_id:
                fail(404, "TRACE_TURN_NOT_FOUND", "Turn does not belong to this call.")
    elif turn_id:
        fail(422, "TRACE_CALL_REQUIRED", "A turn must be correlated with its call.")
    if appointment_id:
        booking = db.get(Appointment, appointment_id)
        if not booking or booking.tenant_id != tenant_id:
            fail(404, "TRACE_BOOKING_NOT_FOUND", "Booking does not belong to this clinic.")
    if parent_id:
        parent = db.get(TraceEvent, parent_id)
        if not parent or parent.tenant_id != tenant_id or call_id and parent.call_id and parent.call_id != call_id:
            fail(404, "TRACE_PARENT_NOT_FOUND", "Parent event is unavailable for this chain.")
    if job_id:
        job = db.get(MessageOutbox, job_id)
        if not job or job.tenant_id != tenant_id:
            fail(404, "TRACE_JOB_NOT_FOUND", "Notification job does not belong to this clinic.")
    when = occurred_at or now_utc()
    if not when.tzinfo or when > now_utc() + timedelta(minutes=5):
        fail(422, "INVALID_TRACE_TIME", "Trace timestamp must be timezone-aware and not in the future.")
    body = {"event": event, "call_id": call_id, "turn_id": turn_id, "appointment_id": appointment_id,
        "job_id": job_id, "provider": provider, "parent_id": parent_id, "versions": versions, "attributes": attributes}
    fingerprint = digest(body)
    existing = db.scalar(select(TraceEvent).where(TraceEvent.tenant_id == tenant_id, TraceEvent.event_key == event_key))
    if existing:
        if existing.request_hash != fingerprint:
            fail(409, "TRACE_REPLAY_CONFLICT", "A trace event cannot change after recording.")
        return existing
    row = TraceEvent(tenant_id=tenant_id, event_key=event_key, request_hash=fingerprint, occurred_at=when, **body)
    db.add(row)
    db.flush()
    return row


def trace_dict(row):
    return {k: getattr(row, k) for k in ("id", "parent_id", "call_id", "turn_id", "appointment_id", "job_id", "provider", "event", "versions", "attributes", "occurred_at")}


@router.get("/traces/{call_id}")
def reconstruct(call_id: str, actor: Actor = Depends(require_permissions("audit:read")), db: Session = Depends(get_db)):
    from .models_voice import CallSession
    call = db.get(CallSession, call_id)
    if not call or call.tenant_id != actor.tenant_id:
        fail(404, "CALL_NOT_FOUND", "Call is not available in this clinic.")
    direct = list(db.scalars(select(TraceEvent).where(TraceEvent.tenant_id == actor.tenant_id, TraceEvent.call_id == call_id)))
    booking_ids = {row.appointment_id for row in direct if row.appointment_id}
    related = list(db.scalars(select(TraceEvent).where(TraceEvent.tenant_id == actor.tenant_id, TraceEvent.appointment_id.in_(booking_ids)))) if booking_ids else []
    combined = {row.id: row for row in direct + related}
    return {"call_id": call_id, "events": [trace_dict(row) for row in sorted(combined.values(), key=lambda r: (r.occurred_at, r.created_at, r.id))],
        "content_policy": "closed_metadata_allowlist_no_audio_or_transcript", "coverage": "instrumented_events_only"}


class OnCallInput(StrictModel):
    enabled: bool
    user_ids: list[str] = Field(min_length=1, max_length=5)
    escalation_minutes: int = Field(default=10, ge=1, le=120)
    spike_window_minutes: int = Field(default=10, ge=1, le=60)
    spike_cap_toman: int = Field(default=100000, ge=1, le=1_000_000_000)
    provider_failure_threshold: int = Field(default=5, ge=1, le=1000)


@router.put("/oncall")
def configure_oncall(data: OnCallInput, actor: Actor = Depends(require_permissions("integration:write")), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    eligible = set(db.scalars(select(Membership.user_id).where(Membership.tenant_id == actor.tenant_id, Membership.active.is_(True), Membership.role.in_(["owner", "admin", "technical", "manager"]))))
    if len(set(data.user_ids)) != len(data.user_ids) or set(data.user_ids) - eligible:
        fail(422, "INVALID_ONCALL_TEAM", "Choose distinct active authorized clinic staff.")
    row = db.get(OnCallPolicy, actor.tenant_id)
    if row:
        row.version += 1
        for key, value in data.model_dump().items():
            setattr(row, key, value)
        row.updated_by, row.updated_at = actor.id, now_utc()
    else:
        row = OnCallPolicy(tenant_id=actor.tenant_id, updated_by=actor.id, **data.model_dump())
        db.add(row)
    db.flush()
    audit(db, actor.tenant_id, actor.id, "operations.oncall_configured", "oncall_policy", actor.tenant_id, version=row.version)
    db.commit()
    return {"version": row.version, **data.model_dump(), "delivery_channel": "in_app_assigned_task", "read_receipt": "explicit_alert_acknowledgment_required"}


@router.get("/oncall")
def oncall(actor: Actor = Depends(require_permissions("health:read")), db: Session = Depends(get_db)):
    row = db.get(OnCallPolicy, actor.tenant_id)
    return {k: getattr(row, k) for k in ("version", "enabled", "user_ids", "escalation_minutes", "spike_window_minutes", "spike_cap_toman", "provider_failure_threshold")} if row else None


@router.get("/oncall/members")
def oncall_members(actor: Actor = Depends(require_permissions("health:read")), db: Session = Depends(get_db)):
    return [{"user_id": user.id, "name": user.name, "role": membership.role} for user, membership in db.execute(
        select(User, Membership).join(Membership, Membership.user_id == User.id).where(Membership.tenant_id == actor.tenant_id,
        Membership.active.is_(True), User.active.is_(True), Membership.role.in_(["owner", "admin", "technical", "manager"])).order_by(User.name).limit(100))]


def raise_alert(db, tenant_id, kind, dedupe_key, evidence, severity="high"):
    old = db.scalar(select(OperationalAlert).where(OperationalAlert.tenant_id == tenant_id, OperationalAlert.dedupe_key == dedupe_key))
    if old:
        return old
    row = OperationalAlert(tenant_id=tenant_id, kind=kind, dedupe_key=dedupe_key, evidence=evidence, severity=severity)
    db.add(row)
    db.flush()
    return row


def evaluate_alerts(db, tenant_id):
    lock_tenant(db, tenant_id)
    expire_unused_reservations(db, tenant_id)
    policy = current_policy(db, tenant_id)
    monetary = spending(db, tenant_id)
    period = now_utc().strftime("%Y-%m")
    if policy and monetary["exposure_micro_toman"] * 100 >= policy.monthly_cap_micro_toman * policy.soft_percent:
        hard = monetary["exposure_micro_toman"] >= policy.monthly_cap_micro_toman
        raise_alert(db, tenant_id, "MONETARY_HARD_CAP" if hard else "MONETARY_SOFT_CAP", f"budget:{period}:{policy.version}:{hard}", monetary, "critical" if hard else "warning")
    oncall_policy = db.get(OnCallPolicy, tenant_id)
    if oncall_policy:
        start = now_utc() - timedelta(minutes=oncall_policy.spike_window_minutes)
        recent = db.scalar(select(func.coalesce(func.sum(UsageCharge.cost_micro_toman), 0)).where(UsageCharge.tenant_id == tenant_id, UsageCharge.created_at >= start)) or 0
        window = int(now_utc().timestamp()) // (oncall_policy.spike_window_minutes * 60)
        if recent > oncall_policy.spike_cap_toman * MICRO:
            raise_alert(db, tenant_id, "SPEND_SPIKE", f"spend-spike:{window}", {"cost_micro_toman": int(recent), "window_minutes": oncall_policy.spike_window_minutes}, "critical")
        failures = list(db.execute(select(TraceEvent.provider, func.count()).where(TraceEvent.tenant_id == tenant_id,
            TraceEvent.occurred_at >= start, TraceEvent.event == "provider.failed").group_by(TraceEvent.provider)))
        for provider, count in failures:
            if count >= oncall_policy.provider_failure_threshold:
                raise_alert(db, tenant_id, "PROVIDER_FAILURE_SPIKE", f"provider-failure:{provider}:{window}", {"provider": provider, "count": count}, "high")
    # A durable recorded safety event is positive evidence; an empty table is
    # explicitly not an audited proof of zero incidents.
    for safety in db.scalars(select(AuditEvent).where(AuditEvent.tenant_id == tenant_id,
        AuditEvent.action.in_(["safety.failure", "safety.false_confirmation", "safety.tenant_exposure", "security.cross_tenant_denied", "cost.reservation_overrun"]),
        AuditEvent.created_at >= now_utc() - timedelta(days=1)).order_by(AuditEvent.created_at.desc()).limit(100)):
        raise_alert(db, tenant_id, "SAFETY_REVIEW", "safety:" + safety.id, {"audit_event_id": safety.id}, "critical")
    moment = now_utc()
    overdue_message = db.scalar(select(MessageOutbox).where(MessageOutbox.tenant_id == tenant_id,
        MessageOutbox.status == "QUEUED", MessageOutbox.available_at <= moment - timedelta(seconds=QUEUE_THRESHOLDS["outbox_due_seconds"]))
        .order_by(MessageOutbox.available_at).limit(1))
    if overdue_message:
        raise_alert(db, tenant_id, "OUTBOX_DELAY", "outbox-delay:" + overdue_message.id,
            {"message_id": overdue_message.id, "due_age_seconds": int((moment - overdue_message.available_at).total_seconds()),
             "threshold_seconds": QUEUE_THRESHOLDS["outbox_due_seconds"]}, "warning")
    overdue_task = db.scalar(select(StaffTask).where(StaffTask.tenant_id == tenant_id,
        StaffTask.status.in_(["OPEN", "IN_PROGRESS", "PENDING", "CALLBACK"]), StaffTask.reason != "OPERATIONAL_ALERT",
        StaffTask.created_at <= moment - timedelta(seconds=QUEUE_THRESHOLDS["staff_wait_seconds"]))
        .order_by(StaffTask.created_at).limit(1))
    if overdue_task:
        raise_alert(db, tenant_id, "STAFF_QUEUE_DELAY", "staff-delay:" + overdue_task.id,
            {"task_id": overdue_task.id, "age_seconds": int((moment - overdue_task.created_at).total_seconds()),
             "threshold_seconds": QUEUE_THRESHOLDS["staff_wait_seconds"]}, "warning")
    failures = db.scalar(select(func.count()).select_from(MessageOutbox).where(MessageOutbox.tenant_id == tenant_id,
        MessageOutbox.status == "FAILED", MessageOutbox.updated_at >= moment - timedelta(days=1))) or 0
    if failures >= QUEUE_THRESHOLDS["failed_deliveries_24h"]:
        raise_alert(db, tenant_id, "DELIVERY_FAILURE_BACKLOG", "delivery-failure:" + moment.strftime("%Y-%m-%d"),
            {"count": failures, "window_hours": 24, "threshold": QUEUE_THRESHOLDS["failed_deliveries_24h"]}, "high")
    for message in db.scalars(select(MessageOutbox).where(MessageOutbox.tenant_id == tenant_id,
        MessageOutbox.status == "UNKNOWN").limit(100)):
        raise_alert(db, tenant_id, "UNKNOWN_DISPATCH", "unknown-message:" + message.id, {"message_id": message.id})
    return monetary


def dispatch_alerts(db, tenant_id):
    policy = db.get(OnCallPolicy, tenant_id)
    if not policy or not policy.enabled:
        return {"dispatched": 0, "status": "oncall_not_configured"}
    count = 0
    for alert in db.scalars(select(OperationalAlert).where(OperationalAlert.tenant_id == tenant_id, OperationalAlert.status == "OPEN").order_by(OperationalAlert.created_at).limit(100)):
        age = max(0, int((now_utc() - alert.created_at).total_seconds()))
        maximum = min(len(policy.user_ids) - 1, age // (policy.escalation_minutes * 60))
        for level in range(maximum + 1):
            if db.scalar(select(AlertDelivery.id).where(AlertDelivery.alert_id == alert.id, AlertDelivery.level == level)):
                continue
            user_id = policy.user_ids[level]
            membership = db.scalar(select(Membership).where(Membership.tenant_id == tenant_id, Membership.user_id == user_id, Membership.active.is_(True), Membership.role.in_(["owner", "admin", "technical", "manager"])))
            if not membership:
                continue
            task = StaffTask(tenant_id=tenant_id, reason="OPERATIONAL_ALERT", summary=f"Operational alert {alert.kind}; review alert reference {alert.id}.",
                priority="urgent" if alert.severity == "critical" else "normal", assigned_to=user_id)
            db.add(task)
            db.flush()
            db.add(AlertDelivery(tenant_id=tenant_id, alert_id=alert.id, level=level, user_id=user_id, task_id=task.id))
            count += 1
    db.flush()
    return {"dispatched": count, "status": "in_app_only"}


def alert_dict(db, row):
    return {**{k: getattr(row, k) for k in ("id", "kind", "severity", "status", "evidence", "acknowledged_by", "acknowledged_at", "created_at", "resolved_at")},
        "deliveries": [{"level": r.level, "user_id": r.user_id, "task_id": r.task_id, "status": r.status} for r in db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == row.id))]}


@router.get("/alerts")
def alerts(actor: Actor = Depends(require_permissions("health:read")), db: Session = Depends(get_db)):
    return {"alerts": [alert_dict(db, row) for row in db.scalars(select(OperationalAlert).where(OperationalAlert.tenant_id == actor.tenant_id).order_by(OperationalAlert.created_at.desc()).limit(100))],
        "queue_thresholds": QUEUE_THRESHOLDS,
        "coverage": "recorded_application_and_cost_events", "carrier_security_coverage": "requires_authenticated_carrier_events_and_operational_review"}


class AlertActionInput(StrictModel):
    action: str = Field(pattern=r"^(ACKNOWLEDGE|RESOLVE)$")
    evidence_reference: str = Field(pattern=IDENTIFIER)


@router.post("/alerts/{alert_id}/actions")
def alert_action(alert_id: str, data: AlertActionInput, actor: Actor = Depends(require_permissions("health:read")), db: Session = Depends(get_db)):
    lock_tenant(db, actor.tenant_id)
    row = db.get(OperationalAlert, alert_id)
    if not row or row.tenant_id != actor.tenant_id:
        fail(404, "ALERT_NOT_FOUND", "Alert is not available in this clinic.")
    policy = db.get(OnCallPolicy, actor.tenant_id)
    if not has_permission(actor, "integration:write") and (not policy or actor.id not in policy.user_ids):
        fail(403, "ONCALL_RESPONSIBILITY_REQUIRED", "Only the configured on-call team or integration administrator may act on this alert.")
    if row.status == "RESOLVED":
        fail(409, "ALERT_RESOLVED", "This alert is already resolved.")
    if data.action == "ACKNOWLEDGE":
        row.status, row.acknowledged_by, row.acknowledged_at = "ACKNOWLEDGED", actor.id, now_utc()
    else:
        if row.status != "ACKNOWLEDGED":
            fail(409, "ALERT_ACK_REQUIRED", "Acknowledge responsibility before resolving an alert.")
        row.status, row.resolved_at, row.resolution_reference = "RESOLVED", now_utc(), data.evidence_reference
        for delivery in db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == row.id)):
            delivery.status = "RESOLVED"
            task = db.get(StaffTask, delivery.task_id)
            if task and task.tenant_id == actor.tenant_id:
                task.status, task.resolved_at, task.resolution = "RESOLVED", now_utc(), "Resolved through audited operational alert."
    audit(db, actor.tenant_id, actor.id, "operations.alert_action", "operational_alert", row.id, decision=data.action, evidence_reference=data.evidence_reference)
    db.commit()
    return alert_dict(db, row)


def run_control_jobs(db, limit=100):
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
        raise ValueError("control_job_batch_out_of_range")
    report = {"privacy": {"erased": 0, "held": 0, "transcripts_erased": 0}, "alerts_dispatched": 0}
    # All phases use the same tenant ordering; multiple replicas never acquire
    # a late tenant during expiry and then an earlier one during alert delivery.
    # The record cap is per tenant. Capping this stable traversal would keep
    # revisiting the same first tenants and permanently starve later clinics.
    for tenant in db.scalars(select(Tenant).order_by(Tenant.id)):
        result = expire_artifacts(db, limit, tenant_id=tenant.id)
        for key in ("erased", "held"):
            report["privacy"][key] += result[key]
        report["privacy"]["transcripts_erased"] += purge_administrative_transcripts(db, tenant, limit=limit)
        if tenant.active:
            evaluate_alerts(db, tenant.id)
            report["alerts_dispatched"] += dispatch_alerts(db, tenant.id)["dispatched"]
    db.flush()
    return report
