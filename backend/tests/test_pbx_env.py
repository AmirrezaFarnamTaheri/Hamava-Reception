"""PBX observation token must be independent from the media registration key."""
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def test_production_secret_generator_uses_distinct_pbx_observer_token(tmp_path):
    destination=tmp_path/'prod.env'
    result=subprocess.run([sys.executable,str(ROOT/'scripts/generate_env.py'),'--host','demo.example.test',
                           '--output',str(destination)],capture_output=True,text=True)
    assert result.returncode == 0
    config=dict(line.split('=',1) for line in destination.read_text().splitlines() if '=' in line and not line.startswith('#'))
    assert len(config['PBX_EVENT_TOKEN']) >= 32
    assert config['PBX_EVENT_TOKEN'] != config['MEDIA_API_TOKEN']
    assert config['NATIVE_STREAMING_CALLS_APPROVED'] == 'false'
    assert config['PBX_REQUIRE_STAFF_SCREENING'] == 'true'
    assert destination.stat().st_mode & 0o777 == 0o600
