"""Screened PSTN transfer must not become human-connected before staff DTMF consent."""
from datetime import timedelta
from uuid import uuid4
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from receptionist.db import Base, make_engine, now_utc
from receptionist.models import Tenant
from receptionist.models_voice import CallSession
from receptionist.media.transfer_events import PBXObservation, record_pbx_registration, accept_pbx_observation


def _relay():
    path = Path(__file__).resolve().parents[2] / "deploy/asterisk/hamava_ami_relay.py"
    spec = importlib.util.spec_from_file_location("hamava_ami_relay_screen", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _observation(call, stage, key, *, uniqueid="pbx.22", channel="PJSIP/reception-0000022", bridge=None):
    return PBXObservation(call_uuid=call, linkedid="pbx.10", event_key=key, stage=stage,
        occurred_at=now_utc(), uniqueid=uniqueid, channel=channel, bridge_id=bridge)


@pytest.fixture
def screened_session(monkeypatch, tmp_path):
    monkeypatch.setenv("PBX_REQUIRE_STAFF_SCREENING", "true")
    monkeypatch.setenv("HUMAN_TRANSFER_TARGETS", "PJSIP/reception")
    engine = make_engine(f"sqlite:///{tmp_path / 'screened.db'}")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id="screen-clinic", slug="screen-clinic", name="Synthetic clinic"))
        row = CallSession(id="screen-call", tenant_id="screen-clinic", token_hash="screen-token",
            policy_version=1, policy_snapshot={"inbound_route": {"transfer_target": "PJSIP/reception"}},
            context_encrypted="sealed", expires_at=now_utc()+timedelta(minutes=10),
            handoff_status="QUEUED", state="HANDOFF_PENDING")
        db.add(row)
        uuid = str(uuid4())
        record_pbx_registration(db, row, uuid, linkedid="pbx.10", caller_uniqueid="pbx.10")
        db.commit()
        yield db, row, uuid
    engine.dispose()


def test_screened_staff_approval_required_before_verified_bridge(screened_session):
    db, row, call = screened_session
    accept_pbx_observation(db, _observation(call, "RINGING", "ring"))
    accept_pbx_observation(db, _observation(call, "ACCEPTED", "answered"))
    accept_pbx_observation(db, _observation(call, "BRIDGE_CALLER", "caller", uniqueid="pbx.10", channel="PJSIP/trunk-00001", bridge="b1"))
    result = accept_pbx_observation(db, _observation(call, "BRIDGE_STAFF", "staff", bridge="b1"))
    assert not result["connected"], "answered leg and bridge observation alone bypass staff consent"
    approve = accept_pbx_observation(db, _observation(call, "SCREENED", "accepted"))
    assert approve["status"] == "CONNECTED" and approve["connected"]


def test_screening_decline_and_wrong_staff_cannot_connect(screened_session):
    db, row, call = screened_session
    accept_pbx_observation(db, _observation(call, "RINGING", "ring"))
    accept_pbx_observation(db, _observation(call, "ACCEPTED", "answered"))
    assert accept_pbx_observation(db, _observation(call, "SCREEN_DECLINED", "declined"))["status"] == "FAILED"
    assert not accept_pbx_observation(db, _observation(call, "BRIDGE_CALLER", "caller", uniqueid="pbx.10", channel="PJSIP/trunk-00001", bridge="b1"))["connected"]
    assert row.handoff_status == "FAILED"


def test_screening_requires_same_answered_staff_leg(screened_session):
    db, row, call = screened_session
    accept_pbx_observation(db, _observation(call, "RINGING", "ring"))
    with pytest.raises(ValueError, match="PBX_SCREENING_ORDER_MISMATCH"):
        accept_pbx_observation(db, _observation(call, "SCREENED", "wrong", uniqueid="pbx.77"))


def test_ami_relay_projects_only_registered_and_allowlisted_screening():
    relay = _relay().AMIProjector(approved_targets={"PJSIP/reception"})
    call = str(uuid4())
    relay.project({"Event":"UserEvent", "UserEvent":"HamavaRegistered", "CallUUID":call,
        "Linkedid":"pbx.10", "CallerUniqueid":"pbx.10"})
    accepted = {"Event":"UserEvent", "UserEvent":"HamavaStaffAccepted", "CallUUID":call,
        "Linkedid":"pbx.10", "StaffUniqueid":"pbx.22", "StaffChannel":"PJSIP/reception-0000022"}
    assert relay.project(accepted)[0]["stage"] == "SCREENED"
    assert relay.project({**accepted, "CallUUID":str(uuid4())}) == []
    assert relay.project({**accepted, "StaffChannel":"PJSIP/other-0000022"}) == []
    assert relay.project({**accepted, "UserEvent":"HamavaStaffDeclined"})[0]["stage"] == "SCREEN_DECLINED"


def test_dialplan_requires_explicit_staff_press_before_bridge():
    plan = (Path(__file__).resolve().parents[2] / "deploy/asterisk/extensions_hamava.conf").read_text()
    assert "U(hamava-screened" in plan
    assert "GOSUB_RESULT=CONTINUE" in plan
    assert "HamavaStaffAccepted" in plan
    assert "READSTATUS" in plan
    assert "HAMAVA_STAFF_SCREENED" in plan
    assert "Read(" in plan
