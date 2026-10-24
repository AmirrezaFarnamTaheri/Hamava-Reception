"""The real local speech service serves independently parseable, bounded PCM streams."""
import importlib.util
import struct
from pathlib import Path
from fastapi.testclient import TestClient
import pytest


def service():
    path = Path(__file__).resolve().parents[2] / 'services' / 'local_speech' / 'app.py'
    spec = importlib.util.spec_from_file_location('local_speech_stream_fixture', path)
    import sys
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_local_stream_exposes_complete_framed_audio_without_wav_headers(monkeypatch):
    module = service()
    monkeypatch.setenv('SPEECH_GATEWAY_TOKEN', 'x'*40)
    monkeypatch.setattr(module, 'configured_voice', lambda: 'test')
    monkeypatch.setattr(module, 'synthesize_pcm_frames', lambda req: iter((b'\0'*640, b'\1'*640)))
    with TestClient(module.app) as client:
        res = client.post('/synthesize/stream', headers={'Authorization':'Bearer '+ 'x'*40},
                          json={'text':'سلام', 'language':'fa', 'format':'pcm_s16le','sample_rate':16000})
    assert res.status_code == 200 and res.headers['content-type'].startswith('application/x-hamava-pcm-frames')
    assert res.headers['x-audio-format'] == 'pcm_s16le'
    expected = struct.pack('!BH',16,640) + b'\0'*640 + struct.pack('!BH',16,640) + b'\1'*640 + struct.pack('!BH',0,8)+(1280).to_bytes(8,'big')
    assert res.content == expected


def test_local_stream_denies_missing_token_and_unapproved_format(monkeypatch):
    module = service()
    monkeypatch.setenv('SPEECH_GATEWAY_TOKEN', 'x'*40)
    with TestClient(module.app) as client:
        assert client.post('/synthesize/stream',json={'text':'سلام'}).status_code == 401
        result = client.post('/synthesize/stream',headers={'Authorization':'Bearer '+'x'*40},
            json={'text':'سلام','language':'en','format':'pcm_s16le','sample_rate':16000})
        assert result.status_code == 422


def test_frame_builder_rejects_output_over_limit_without_emitting_success(monkeypatch):
    module = service()
    class FakeVoice:
        def synthesize(self, *args, **kw):
            from types import SimpleNamespace
            yield SimpleNamespace(audio_int16_bytes=b'\0'*640, sample_rate=16000,sample_width=2,sample_channels=1)
            yield SimpleNamespace(audio_int16_bytes=b'\0'*640, sample_rate=16000,sample_width=2,sample_channels=1)
    monkeypatch.setattr(module, 'configured_voice', lambda: 'path')
    monkeypatch.setattr(module, '_voice', FakeVoice())
    monkeypatch.setattr(module, 'STREAM_PCM_MAX_BYTES', 640)
    import sys
    from types import SimpleNamespace
    monkeypatch.setitem(sys.modules, 'piper', SimpleNamespace(PiperVoice=FakeVoice,SynthesisConfig=lambda **kw: None))
    request=module.Synthesis(text='سلام',language='fa',format='pcm_s16le',sample_rate=16000)
    with pytest.raises(ValueError, match='STREAM_AUDIO_LIMIT'):
        list(module.synthesize_pcm_frames(request))


@pytest.mark.asyncio
async def test_gateway_consumes_actual_local_asgi_stream_contract(monkeypatch):
    import httpx
    from receptionist.media.streaming import GatewayPCMStream
    module = service()
    secret = 's'*40
    monkeypatch.setenv('SPEECH_GATEWAY_TOKEN',secret)
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED','true')
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED','true')
    monkeypatch.setenv('ALLOW_LOCAL_HTTP_PROVIDERS','true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS','127.0.0.1')
    monkeypatch.setattr(module,'configured_voice',lambda:'synthetic')
    monkeypatch.setattr(module,'synthesize_pcm_frames',lambda request:iter((bytes(640),bytes(640))))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app),base_url='http://127.0.0.1:8090') as client:
        events=[event async for event in GatewayPCMStream('http://127.0.0.1:8090',secret,client).events('سلام')]
    assert [item['event'] for item in events] == ['audio','audio','end']
    assert events[-1]['audio_seconds'] == pytest.approx(.04)
