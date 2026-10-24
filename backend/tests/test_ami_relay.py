"""Raw AMI events never assert human connection without correlated bridge facts."""
import importlib.util
from pathlib import Path
from uuid import uuid4


def module():
    path = Path(__file__).resolve().parents[2] / 'deploy' / 'asterisk' / 'hamava_ami_relay.py'
    spec = importlib.util.spec_from_file_location('hamava_ami_relay', path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def test_ami_registration_and_dial_status_correlate_one_call():
    relay = module()
    parser = relay.AMIProjector(approved_targets={'PJSIP/reception'})
    uuid = str(uuid4())
    assert parser.project({'Event':'UserEvent','UserEvent':'HamavaRegistered','CallUUID':uuid,'Linkedid':'1740.10'}) == []
    ringing = parser.project({'Event':'DialBegin','Linkedid':'1740.10','DestChannel':'PJSIP/reception-000001','DestUniqueid':'1740.22'})
    assert ringing[0]['stage'] == 'RINGING' and ringing[0]['call_uuid'] == uuid
    answer = parser.project({'Event':'DialEnd','Linkedid':'1740.10','DialStatus':'ANSWER','DestChannel':'PJSIP/reception-000001','DestUniqueid':'1740.22'})
    assert answer[0]['stage'] == 'ACCEPTED'
    assert parser.project({'Event':'BlindTransfer','Linkedid':'1740.10','Result':'Success'}) == []
    staff = parser.project({'Event':'BridgeEnter','Linkedid':'1740.10','BridgeUniqueid':'b-1','BridgeTechnology':'simple_bridge','Channel':'PJSIP/reception-000001','Uniqueid':'1740.22'})
    caller = parser.project({'Event':'BridgeEnter','Linkedid':'1740.10','BridgeUniqueid':'b-1','BridgeTechnology':'simple_bridge','Channel':'PJSIP/provider-000001','Uniqueid':'1740.10'})
    assert staff[0]['stage']=='BRIDGE_STAFF' and caller[0]['stage']=='BRIDGE_CALLER'
    assert staff[0]['bridge_id'] == caller[0]['bridge_id'] == 'b-1'


def test_ami_projector_ignores_other_calls_premium_routes_and_holding_bridges():
    relay = module()
    parser = relay.AMIProjector(approved_targets={'PJSIP/reception'})
    uuid = str(uuid4())
    parser.project({'Event':'UserEvent','UserEvent':'HamavaRegistered','CallUUID':uuid,'Linkedid':'1740.10'})
    assert parser.project({'Event':'DialBegin','Linkedid':'wrong','DestChannel':'PJSIP/reception-1','DestUniqueid':'x'}) == []
    assert parser.project({'Event':'DialBegin','Linkedid':'1740.10','DestChannel':'PJSIP/premium-1','DestUniqueid':'x'}) == []
    assert parser.project({'Event':'BridgeEnter','Linkedid':'1740.10','BridgeTechnology':'holding_bridge',
        'BridgeUniqueid':'b','Uniqueid':'1740.10','Channel':'PJSIP/carrier-1'}) == []


def test_ami_parser_bounds_input_and_excludes_conflicting_fields():
    relay = module()
    assert relay.parse_ami_frame(b'Event: DialEnd\r\nLinkedid: 1740.10\r\nDialStatus: ANSWER\r\n')['DialStatus'] == 'ANSWER'
    assert relay.parse_ami_frame(b'Event: DialEnd\r\nEvent: BlindTransfer\r\n') == {}
    assert relay.parse_ami_frame(b'Event: DialEnd\r\nEvil: header\r\ninjection\r\n') == {}
    assert relay.parse_ami_frame(b'A' * 20000) == {}


def test_ami_projector_does_not_confuse_suffix_names_with_channel_instances():
    relay = module()
    parser = relay.AMIProjector(approved_targets={'PJSIP/reception'})
    uuid = str(uuid4())
    parser.project({'Event':'UserEvent','UserEvent':'HamavaRegistered','CallUUID':uuid,'Linkedid':'1740.10'})
    assert parser.project({'Event':'DialBegin','Linkedid':'1740.10','DestChannel':'PJSIP/reception-malicious','DestUniqueid':'1740.22'}) == []


def test_ami_caller_bridge_uses_registered_uniqueid_not_assumed_linkedid():
    relay = module()
    parser = relay.AMIProjector(approved_targets={'PJSIP/reception'})
    uuid = str(uuid4())
    parser.project({'Event':'UserEvent','UserEvent':'HamavaRegistered','CallUUID':uuid,
                    'Linkedid':'1740.10','CallerUniqueid':'1740.11'})
    caller = parser.project({'Event':'BridgeEnter','Linkedid':'1740.10','BridgeUniqueid':'bridge-5',
                            'BridgeTechnology':'simple_bridge','Channel':'PJSIP/trunk-000001','Uniqueid':'1740.11'})
    assert caller and caller[0]['stage'] == 'BRIDGE_CALLER' and caller[0]['uniqueid'] == '1740.11'
    other = parser.project({'Event':'BridgeEnter','Linkedid':'1740.10','BridgeUniqueid':'bridge-6',
                          'BridgeTechnology':'simple_bridge','Channel':'PJSIP/trunk-000001','Uniqueid':'1740.99'})
    assert not other


def test_ami_dial_timeout_is_reported_as_failed_handoff():
    relay=module()
    parser=relay.AMIProjector(approved_targets={'PJSIP/reception'})
    uuid=str(uuid4())
    parser.project({'Event':'UserEvent','UserEvent':'HamavaRegistered','CallUUID':uuid,'Linkedid':'1740.10'})
    parser.project({'Event':'DialBegin','Linkedid':'1740.10','DestChannel':'PJSIP/reception-000001','DestUniqueid':'1740.22'})
    event=parser.project({'Event':'DialEnd','DialStatus':'TIMEDOUT','Linkedid':'1740.10',
                          'DestChannel':'PJSIP/reception-000001','DestUniqueid':'1740.22'})
    assert event and event[0]['stage']=='FAILED'


def test_ami_frame_accepts_valid_utf8_caller_name_without_logging_patient_data():
    relay = module()
    frame = 'Event: BridgeEnter\r\nCallerIDName: آزمایش\r\nLinkedid: 123.4\r\n\r\n'.encode('utf-8')
    fields = relay.parse_ami_frame(frame[:-4])
    assert fields['Event'] == 'BridgeEnter' and fields['CallerIDName'] == 'آزمایش'
