"""AM I handoff must use correlated call and bridge evidence, not Dial answer alone."""
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from receptionist.db import Base, make_engine, now_utc
from receptionist.models import Tenant
from receptionist.models_finance import TransportEvent
from receptionist.models_voice import CallSession
from receptionist.media.transfer_events import PBXObservation, record_pbx_registration, accept_pbx_observation


@pytest.fixture
def pbx_db(tmp_path, monkeypatch):
    monkeypatch.setenv('HUMAN_TRANSFER_TARGETS', 'PJSIP/reception')
    engine = make_engine(f'sqlite:///{tmp_path / "pbx.db"}')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        tenant = Tenant(id='test-clinic', slug='test-clinic', name='Synthetic clinic')
        db.add(tenant)
        call = CallSession(id='call-1', tenant_id=tenant.id, token_hash='token', policy_version=1,
            policy_snapshot={'inbound_route': {'transfer_target': 'PJSIP/reception'}},
            context_encrypted='sealed-test', expires_at=now_utc() + timedelta(minutes=30),
            handoff_status='QUEUED', state='HANDOFF_PENDING')
        db.add(call)
        record_pbx_registration(db, call, str(uuid4()), linkedid='1740.10', caller_uniqueid='1740.10')
        db.commit()
        reference = db.scalar(select(TransportEvent).where(TransportEvent.source=='pbx_registration'))
        yield db, call, reference.event_key.removeprefix('reg:')
    engine.dispose()


def observation(call_uuid, stage, key, *, uniqueid='1740.22', channel='PJSIP/reception-0000022', bridge_id=None):
    return PBXObservation(call_uuid=call_uuid, linkedid='1740.10', event_key=key, stage=stage,
        occurred_at=now_utc(), uniqueid=uniqueid, channel=channel, bridge_id=bridge_id)


def test_pbx_ringing_answer_is_not_connection_without_verified_bridge(pbx_db):
    db, call, call_uuid = pbx_db
    assert accept_pbx_observation(db, observation(call_uuid,'RINGING','r1'))['status'] == 'RINGING'
    assert accept_pbx_observation(db, observation(call_uuid,'ACCEPTED','a1'))['status'] == 'ACCEPTED'
    assert call.handoff_status == 'ACCEPTED'
    staff = observation(call_uuid, 'BRIDGE_STAFF','s1',bridge_id='bridge-1')
    assert accept_pbx_observation(db, staff)['status'] == 'ACCEPTED'
    caller = observation(call_uuid, 'BRIDGE_CALLER','c1', uniqueid='1740.10',channel='PJSIP/carrier-0001',bridge_id='bridge-1')
    result = accept_pbx_observation(db, caller)
    assert result['status'] == 'CONNECTED' and result['connected']
    assert call.state == 'HUMAN_CONNECTED'


def test_pbx_fail_no_answer_and_late_replay_do_not_reopen(pbx_db):
    db, call, uuid = pbx_db
    accept_pbx_observation(db, observation(uuid,'RINGING','r1'))
    assert accept_pbx_observation(db, observation(uuid,'FAILED','f1'))['status'] == 'FAILED'
    assert accept_pbx_observation(db, observation(uuid,'RINGING','r2'))['status'] == 'FAILED'
    assert call.handoff_status == 'FAILED'
    assert not accept_pbx_observation(db, observation(uuid,'ACCEPTED','a1'))['connected']


def test_pbx_wrong_tenant_linkedid_and_fake_staff_bridge_fail_closed(pbx_db):
    db, call, uuid = pbx_db
    wrong = observation(uuid,'RINGING','bad')
    wrong.linkedid = '1740.99'
    with pytest.raises(ValueError,match='PBX_REGISTRATION_MISMATCH'):
        accept_pbx_observation(db, wrong)
    wrong = observation(uuid,'RINGING','bad')
    wrong.channel = 'PJSIP/other-0001'
    with pytest.raises(ValueError,match='PBX_STAFF_ROUTE_MISMATCH'):
        accept_pbx_observation(db, wrong)
    assert call.handoff_status == 'QUEUED'


def test_pbx_replay_is_idempotent_but_conflicting_event_id_rejected(pbx_db):
    db, call, uuid = pbx_db
    value = observation(uuid,'RINGING','same')
    accept_pbx_observation(db, value)
    assert accept_pbx_observation(db, value)['replayed']
    with pytest.raises(ValueError,match='PBX_EVENT_CONFLICT'):
        accept_pbx_observation(db, observation(uuid,'ACCEPTED','same'))
    assert db.scalar(select(TransportEvent).where(TransportEvent.event_key=='same')).stage == 'RINGING'


def test_pbx_accepted_before_ringing_does_not_claim_connection(pbx_db):
    db, call, uuid = pbx_db
    with pytest.raises(ValueError,match='PBX_ORDER_MISMATCH'):
        accept_pbx_observation(db, observation(uuid,'ACCEPTED','early'))
    assert call.handoff_status == 'QUEUED'


def test_pbx_bridge_after_audio_leg_is_not_claimed_as_active_ai(pbx_db):
    db, call, uuid = pbx_db
    accept_pbx_observation(db, observation(uuid,'RINGING','r1'))
    accept_pbx_observation(db, observation(uuid,'ACCEPTED','a1'))
    call.ended_at = now_utc()
    call.state = 'ENDED'
    accept_pbx_observation(db, observation(uuid,'BRIDGE_CALLER','c1', uniqueid='1740.10',channel='PJSIP/carrier-1',bridge_id='b1'))
    result = accept_pbx_observation(db, observation(uuid,'BRIDGE_STAFF','s1',bridge_id='b1'))
    assert result['connected'] and call.handoff_status == 'CONNECTED'
    assert call.state == 'ENDED'


def test_pbx_departed_caller_cannot_be_joined_to_later_staff_on_same_bridge(pbx_db):
    db, call, uuid = pbx_db
    accept_pbx_observation(db, observation(uuid,'RINGING','r1'))
    accept_pbx_observation(db, observation(uuid,'ACCEPTED','a1'))
    accept_pbx_observation(db, observation(uuid,'BRIDGE_CALLER','c1',uniqueid='1740.10',channel='PJSIP/carrier-1',bridge_id='b1'))
    leave = observation(uuid,'BRIDGE_CALLER_LEFT','l1',uniqueid='1740.10',channel='PJSIP/carrier-1',bridge_id='b1')
    accept_pbx_observation(db, leave)
    result = accept_pbx_observation(db, observation(uuid,'BRIDGE_STAFF','s1',bridge_id='b1'))
    assert not result['connected'] and result['status'] == 'ACCEPTED'


def test_pbx_channel_prefix_is_not_staff_identity(pbx_db):
    db, call, uuid = pbx_db
    with pytest.raises(ValueError,match='PBX_STAFF_ROUTE_MISMATCH'):
        accept_pbx_observation(db, observation(uuid,'RINGING','bad',channel='PJSIP/reception-malicious'))


def test_pbx_connected_handoff_loses_verified_connection_on_staff_departure(pbx_db):
    db, call, uuid = pbx_db
    accept_pbx_observation(db, observation(uuid,'RINGING','r1'))
    accept_pbx_observation(db, observation(uuid,'ACCEPTED','a1'))
    accept_pbx_observation(db, observation(uuid,'BRIDGE_CALLER','c1',uniqueid='1740.10',channel='PJSIP/carrier-1',bridge_id='b1'))
    assert accept_pbx_observation(db, observation(uuid,'BRIDGE_STAFF','s1',bridge_id='b1'))['connected']
    left = accept_pbx_observation(db, observation(uuid,'BRIDGE_STAFF_LEFT','l1',bridge_id='b1'))
    assert left == {'status':'DISCONNECTED','connected':False,'replayed':False,'transitioned':True}
    assert call.state == 'HUMAN_CONNECTED'  # NEVER resume autonomous booking
    assert accept_pbx_observation(db, observation(uuid,'BRIDGE_STAFF','s2',bridge_id='b1'))['status'] == 'DISCONNECTED'
