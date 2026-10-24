"""Fail-closed PBX handoff observation over independently authenticated AMI events.

DialEnd/BlindTransfer success is never proof that the caller and staff are
sharing audio. Connection requires a correlated answered staff leg and both
participants observed in the SAME bridge, with a registered PBX caller id.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select

from ..db import now_utc
from ..models_finance import TransportEvent
from ..models_voice import CallSession


_PBX_ID = r"^[A-Za-z0-9_.:-]{1,100}$"


class PBXObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    call_uuid: str
    linkedid: str = Field(pattern=_PBX_ID)
    event_key: str = Field(pattern=_PBX_ID)
    stage: Literal["RINGING", "ACCEPTED", "FAILED", "SCREENED", "SCREEN_DECLINED", "BRIDGE_CALLER", "BRIDGE_STAFF", "BRIDGE_CALLER_LEFT", "BRIDGE_STAFF_LEFT"]
    occurred_at: datetime
    uniqueid: str = Field(pattern=_PBX_ID)
    channel: str = Field(min_length=1, max_length=160)
    bridge_id: str | None = Field(default=None, pattern=_PBX_ID)

    @model_validator(mode="after")
    def consistent(self):
        try:
            UUID(self.call_uuid)
        except ValueError as exc:
            raise ValueError("INVALID_CALL_UUID") from exc
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("PBX_EVENT_TIME_REQUIRED")
        if self.stage.startswith("BRIDGE_") and not self.bridge_id:
            raise ValueError("PBX_BRIDGE_REQUIRED")
        return self


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _staff_channel_matches(channel: str, target: str) -> bool:
    # AMI appends a channel instance suffix. Exact-prefix plus its documented
    # delimiter excludes names like PJSIP/reception-attacker.
    if not target.startswith(("PJSIP/", "Local/", "IAX2/")):
        return False
    if not re.fullmatch(r"[A-Za-z0-9_@.:+/-]{1,120}", target):
        return False
    # Channel runtime instance IDs are Asterisk hex channel counters, not
    # arbitrary extension names that happen to begin with the same prefix.
    suffix = channel[len(target) + 1:] if channel.startswith(target + "-") else ""
    return channel == target or re.fullmatch(r"[A-Fa-f0-9]{6,16}", suffix) is not None


def record_pbx_registration(db, row: CallSession, call_uuid: str, *, linkedid: str, caller_uniqueid: str):
    UUID(call_uuid)
    if not re.fullmatch(_PBX_ID, linkedid) or not re.fullmatch(_PBX_ID, caller_uniqueid):
        raise ValueError("INVALID_PBX_CORRELATION")
    db.add(TransportEvent(tenant_id=row.tenant_id, source="pbx_registration", event_key="reg:" + call_uuid,
        attempt_key=linkedid, call_id=row.id, stage="REGISTERED", request_hash=_sha(caller_uniqueid),
        evidence_reference="registered_agi", occurred_at=now_utc()))


def accept_pbx_observation(db, observation: PBXObservation) -> dict:
    if not isinstance(observation, PBXObservation):
        observation = PBXObservation.model_validate(observation)
    registration = db.scalar(select(TransportEvent).where(TransportEvent.source == "pbx_registration",
        TransportEvent.event_key == "reg:" + observation.call_uuid))
    if not registration or registration.attempt_key != observation.linkedid:
        raise ValueError("PBX_REGISTRATION_MISMATCH")
    row = db.get(CallSession, registration.call_id)
    if not row or row.tenant_id != registration.tenant_id or row.handoff_status not in {
        "QUEUED", "RINGING", "ACCEPTED", "CONNECTED", "FAILED", "DISCONNECTED"}:
        raise ValueError("PBX_HANDOFF_NOT_REQUESTED")
    now = now_utc()
    if (observation.occurred_at < now - timedelta(minutes=5) or observation.occurred_at > now + timedelta(seconds=30)
        or observation.occurred_at < row.started_at - timedelta(seconds=30)
        or observation.occurred_at > row.expires_at + timedelta(minutes=2)):
        raise ValueError("PBX_EVENT_STALE")
    existing = db.scalar(select(TransportEvent).where(TransportEvent.tenant_id == row.tenant_id,
        TransportEvent.source == "pbx_ami", TransportEvent.event_key == observation.event_key))
    fingerprint = _sha(observation.model_dump_json(exclude_none=True))
    if existing:
        if existing.request_hash != fingerprint or existing.call_id != row.id:
            raise ValueError("PBX_EVENT_CONFLICT")
        return {"status": row.handoff_status, "connected": row.handoff_status == "CONNECTED", "replayed": True,
                "transitioned": False}
    target = row.policy_snapshot.get("inbound_route", {}).get("transfer_target", "")
    if target not in {item.strip() for item in os.getenv("HUMAN_TRANSFER_TARGETS", "").split(",") if item.strip()}:
        raise ValueError("PBX_TARGET_NOT_APPROVED")
    if observation.stage in {"BRIDGE_CALLER", "BRIDGE_CALLER_LEFT"}:
        if _sha(observation.uniqueid) != registration.request_hash:
            raise ValueError("PBX_CALLER_MISMATCH")
    elif not _staff_channel_matches(observation.channel, target):
        raise ValueError("PBX_STAFF_ROUTE_MISMATCH")
    history = db.scalars(select(TransportEvent).where(TransportEvent.tenant_id == row.tenant_id,
        TransportEvent.source == "pbx_ami", TransportEvent.call_id == row.id)).all()
    if observation.stage in {"ACCEPTED", "FAILED", "SCREENED", "SCREEN_DECLINED"} and not any(
        item.stage == "RINGING" and item.attempt_key == observation.uniqueid for item in history):
        raise ValueError("PBX_SCREENING_ORDER_MISMATCH" if observation.stage.startswith("SCREEN") else "PBX_ORDER_MISMATCH")
    item = TransportEvent(tenant_id=row.tenant_id, source="pbx_ami", event_key=observation.event_key,
        attempt_key=observation.uniqueid, call_id=row.id, stage=observation.stage,
        request_hash=fingerprint, evidence_reference=observation.bridge_id or "no_bridge",
        occurred_at=observation.occurred_at)
    db.add(item)
    history.append(item)
    previous = row.handoff_status
    if previous == "CONNECTED" and observation.stage in {"BRIDGE_CALLER_LEFT", "BRIDGE_STAFF_LEFT"}:
        entered = observation.stage.removesuffix("_LEFT")
        if any(old.stage == entered and old.attempt_key == observation.uniqueid
                   and old.evidence_reference == observation.bridge_id for old in history[:-1]):
            # The caller/staff bridge is no longer live. Keep the business
            # session human-owned: AI must not resume, even if later AMI
            # events reuse the same bridge or arrive out of order.
            row.handoff_status = "DISCONNECTED"
    if previous not in {"FAILED", "CONNECTED", "DISCONNECTED"}:
        if observation.stage == "RINGING" and previous == "QUEUED":
            row.handoff_status = "RINGING"
        elif observation.stage == "ACCEPTED":
            row.handoff_status = "ACCEPTED"
        elif observation.stage in {"FAILED", "SCREEN_DECLINED"}:
            row.handoff_status = "FAILED"
        if row.handoff_status != "FAILED":
            answers = {event.attempt_key for event in history if event.stage == "ACCEPTED"}
            screened = {event.attempt_key for event in history if event.stage == "SCREENED"}
            require_screening = os.getenv("PBX_REQUIRE_STAFF_SCREENING", "false").lower() in {"true", "1", "yes"}
            # A later BridgeLeave invalidates a prior enter; two historical
            # BridgeEnter events alone cannot prove simultaneous membership.
            latest = {}
            for event in history:
                if event.stage.startswith("BRIDGE_"):
                    who = "caller" if event.stage.startswith("BRIDGE_CALLER") else "staff"
                    identity = (who, event.evidence_reference, event.attempt_key)
                    old = latest.get(identity)
                    if old is None or (event.occurred_at, event.event_key) > (old.occurred_at, old.event_key):
                        latest[identity] = event
            callers = {bridge for (role, bridge, _), event in latest.items()
                       if role == "caller" and event.stage == "BRIDGE_CALLER"}
            staffs = {(bridge, staff_id) for (role, bridge, staff_id), event in latest.items()
                      if role == "staff" and event.stage == "BRIDGE_STAFF"}
            if any(bridge in callers and staff_id in answers and (not require_screening or staff_id in screened)
                   for bridge, staff_id in staffs):
                row.handoff_status = "CONNECTED"
                if row.ended_at is None:
                    row.state = "HUMAN_CONNECTED"
                    row.lease_token = None
                    row.lease_until = None
    db.flush()
    return {"status": row.handoff_status, "connected": row.handoff_status == "CONNECTED",
            "replayed": False, "transitioned": row.handoff_status != previous}
