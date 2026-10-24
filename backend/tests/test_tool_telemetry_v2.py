# ruff: noqa: F811 -- imported pytest fixture names are injected as arguments
"""Durable, content-free tool spans over real turn transactions.

Provider-free local fixtures verify trace semantics, not acoustic latency.
"""
import json
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import func, select

from receptionist import model_registry, tool_gateway, voice  # noqa: F401
from receptionist.core import ReceptionService
from receptionist.models import Appointment, Tenant
from receptionist.models_core import CalendarAuthority, ExternalCalendarOperation
from receptionist.models_ops_control import TraceEvent
from receptionist.models_voice import CallSession, VoiceTurn
from receptionist.ops_controls import append_trace, reconstruct
from receptionist.security import Actor, hash_phone
from receptionist.telemetry import latency_report
from test_core import database, future_day, slot_for  # noqa: F401


OWNER = Actor("demo-owner", "clinic-bahar", "owner", "Owner", "owner@example.test", "bahar")
OTHER = Actor("demo-other", "clinic-niloufar", "owner", "Other", "other@example.test", "niloufar")
CANARY = "private caller 09123456789 confidential details"


def prepared(db):
    row, _ = voice.new_session(db, db.get(Tenant, OWNER.tenant_id))
    row.state, row.intent = "DATE", "book"
    data = voice.context(row)
    data.update(provider_id="provider-bahar-1", service_id="service-consultation")
    voice.save_context(row, data)
    db.commit()
    return row


def spans(db, call_id):
    return list(db.scalars(select(TraceEvent).where(TraceEvent.call_id == call_id,
        TraceEvent.event.like("tool.%")).order_by(TraceEvent.created_at)))


def book_answer(db, row, monkeypatch):
    args = {"slot_id": slot_for(db), "patient_name": CANARY, "phone": "09123456789",
            "confirmed": True, "idempotency_key": "tool-span-booking"}
    data = voice.context(row)
    data.update(phone=args["phone"], verified_phone=hash_phone(args["phone"]))
    voice.save_context(row, data)
    db.commit()

    def answer(self, text):
        result = self.tools.call("book", args)
        return self.set_reply("synthetic completed tool", "COMPLETE", booking=result)

    monkeypatch.setattr(voice.Conversation, "answer", answer)


def test_tool_span_is_durable_scoped_exactly_once_on_turn_replay(database, monkeypatch):
    # A deterministic monotonic clock checks the measured boundary without
    # turning a unit fixture's wall time into a latency-performance claim.
    clock = iter((10.0, 10.125, 10.25))
    monkeypatch.setattr(tool_gateway, "time", SimpleNamespace(monotonic=lambda: next(clock)))
    with database() as db:
        row = prepared(db)
        sid = row.id
        body = voice.TurnInput(text=future_day(), request_id=str(uuid4()))
        result = voice.execute_turn(db, row, body)
        assert result["state"] == "OFFER"
        replay = voice.execute_turn(db, row, body)
        assert replay["turn_id"] == result["turn_id"]
    with database() as restarted:
        records = spans(restarted, sid)
        assert len(records) == 1
        span = records[0]
        assert span.event == "tool.slots"
        assert span.turn_id == result["turn_id"] and span.tenant_id == OWNER.tenant_id
        assert span.attributes == {"outcome": "completed", "duration_ms": 250, "status": "committed"}
        parent = restarted.get(TraceEvent, span.parent_id)
        assert parent.event == "conversation.turn_completed" and parent.turn_id == span.turn_id
        assert reconstruct(sid, OWNER, restarted)["coverage"] == "instrumented_events_only"
        with pytest.raises(HTTPException) as denied:
            reconstruct(sid, OTHER, restarted)
        assert denied.value.status_code == 404
        other, _ = voice.new_session(restarted, restarted.get(Tenant, OTHER.tenant_id))
        append_trace(restarted, OTHER.tenant_id, "tool-other-latency", "tool.slots", call_id=other.id,
            attributes={"duration_ms": 99999, "outcome": "completed", "status": "committed"})
        restarted.commit()
        report = latency_report(24, OWNER, restarted)
        assert report["stages"]["tool_slots"] == {"count": 1, "p50_ms": 250.0, "p95_ms": 250.0, "p99_ms": 250.0}
        assert report["stages"]["tool_book"]["count"] == 0
        assert report["cost_meter"] is False and "caller receiver" in report["end_to_first_audible"]


def test_deadline_span_survives_safe_handoff_without_committing_booking(database, monkeypatch):
    with database() as db:
        row = prepared(db)
        book_answer(db, row, monkeypatch)
        before = db.scalar(select(func.count()).select_from(Appointment))
        monkeypatch.setenv("TOOL_TIMEOUT_MS", "0")
        result = voice.execute_turn(db, row, voice.TurnInput(text="بله", request_id=str(uuid4())))
        assert result["state"] == "HANDOFF_PENDING" and result["booking"] is None
        assert db.scalar(select(func.count()).select_from(Appointment)) == before
        span, = spans(db, row.id)
        assert span.turn_id == result["turn_id"]
        assert span.attributes["outcome"] == "deadline"
        assert span.attributes["error_code"] == "TOOL_DEADLINE"
        assert span.attributes["status"] == "rolled_back" and span.attributes["http_status"] == 503
        assert type(span.attributes["duration_ms"]) is int and span.attributes["duration_ms"] >= 0
        assert CANARY not in json.dumps(reconstruct(row.id, OWNER, db), default=str)
        assert "09123456789" not in json.dumps(reconstruct(row.id, OWNER, db), default=str)
        assert latency_report(24, OWNER, db)["stages"]["tool_book"]["count"] == 0


@pytest.mark.parametrize("failure_point", ["tool_exception", "receipt_exception"])
def test_unhandled_failure_preserves_metadata_but_no_receipt_or_booking(database, monkeypatch, failure_point):
    with database() as db:
        row = prepared(db)
        sid = row.id
        before = db.scalar(select(func.count()).select_from(Appointment))

        def crash(*args, **kwargs):
            raise RuntimeError(CANARY)

        if failure_point == "tool_exception":
            monkeypatch.setattr(ReceptionService, "slots", crash)
        else:
            book_answer(db, row, monkeypatch)
            monkeypatch.setattr(voice, "uid", crash)
        with pytest.raises(RuntimeError, match="private caller"):
            voice.execute_turn(db, row, voice.TurnInput(text=future_day(), request_id=str(uuid4())))
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Appointment)) == before
        assert db.scalar(select(VoiceTurn).where(VoiceTurn.call_id == sid)) is None
        assert db.get(CallSession, sid).lease_token is None
        span, = spans(db, sid)
        assert span.turn_id is None and span.parent_id is None
        assert span.attributes["status"] == "rolled_back"
        assert span.attributes["outcome"] == ("failed" if failure_point == "tool_exception" else "completed")
        if failure_point == "tool_exception":
            assert span.attributes["error_code"] == "TOOL_FAILURE"
        payload = json.dumps(reconstruct(sid, OWNER, db), default=str)
        assert CANARY not in payload and "09123456789" not in payload


def test_external_tool_is_queued_not_completed_and_has_one_replay_safe_span(database):
    with database() as db:
        row = prepared(db)
        authority = db.get(CalendarAuthority, OWNER.tenant_id)
        authority.kind, authority.provider_key = "external", "calendar_primary"
        authority.capabilities = {"account_id": "synthetic-clinic"}
        db.commit()
        body = voice.TurnInput(text=future_day(), request_id=str(uuid4()))
        result = voice.execute_turn(db, row, body)
        assert result["state"] == "WAIT_CALENDAR" and result["booking"] is None
        assert voice.execute_turn(db, row, body)["turn_id"] == result["turn_id"]
        operation, = list(db.scalars(select(ExternalCalendarOperation).where(ExternalCalendarOperation.call_id == row.id)))
        assert operation.status == "PENDING" and operation.attempts == 0
        span, = spans(db, row.id)
        assert span.attributes["outcome"] == "queued" and span.attributes["status"] == "committed"
        assert latency_report(24, OWNER, db)["stages"]["tool_slots"]["count"] == 0


def test_invalid_tool_name_and_validation_details_never_become_trace_labels(database, monkeypatch):
    def invalid(self, text):
        return self.tools.call(CANARY, {"patient": CANARY})

    monkeypatch.setattr(voice.Conversation, "answer", invalid)
    with database() as db:
        row = prepared(db)
        result = voice.execute_turn(db, row, voice.TurnInput(text="سلام", request_id=str(uuid4())))
        assert result["state"] == "HANDOFF_PENDING"
        span, = spans(db, row.id)
        assert span.event == "tool.invalid" and span.attributes["outcome"] == "rejected"
        assert span.attributes["error_code"] == "TOOL_REJECTED"
        assert span.attributes["http_status"] == 422
        assert CANARY not in json.dumps(reconstruct(row.id, OWNER, db), default=str)
