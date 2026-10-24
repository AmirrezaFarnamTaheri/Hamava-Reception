"""No generated checklist can self-certify a real device, clinic or legal gate."""
import importlib.util
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def readmodule():
    spec=importlib.util.spec_from_file_location('hamava_launch_readiness', ROOT/'scripts/launch_readiness.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_external_gates_are_blocked_without_evidence(tmp_path):
    result = readmodule().check_readiness(tmp_path, {})
    assert result['production_ready'] is False
    assert 'carrier_pstn' in result['gates'] and 'clinic_uat' in result['gates']
    assert 'staff_screening_and_bridge' in result['gates']
    assert all(x['state']=='MISSING' for x in result['gates'].values())


def test_evidence_never_equates_to_external_approval(tmp_path):
    proof=tmp_path/'synthetic-certificate-note.txt'
    proof.write_text('This is not real acceptance.')
    result=readmodule().check_readiness(tmp_path, {'windows_publisher_signing':{
       'file':'synthetic-certificate-note.txt', 'sha256':sha256(proof.read_bytes()).hexdigest(),
       'review_owner':'test-only', 'independently_reviewed':True}})
    assert result['production_ready'] is False
    assert result['gates']['windows_publisher_signing']['state']=='EVIDENCE_SUBMITTED_REVIEW_REQUIRED'


def test_evidence_path_escape_and_mismatched_hash_fail_closed(tmp_path):
    outside = tmp_path.parent / 'external.txt'
    outside.write_text('unapproved')
    result=readmodule().check_readiness(tmp_path, {'android_device':{'file':'../external.txt','sha256':sha256(outside.read_bytes()).hexdigest()}})
    assert result['gates']['android_device']['state']=='INVALID_EVIDENCE'
    inside = tmp_path / 'inside.txt'
    inside.write_text('receipt')
    result=readmodule().check_readiness(tmp_path, {'android_device':{'file':'inside.txt','sha256':'0'*64}})
    assert result['gates']['android_device']['state']=='INVALID_EVIDENCE'
