"""Streaming speech may call the existing deterministic turn endpoint only on final text."""
import httpx
import pytest

from receptionist.providers import ProviderError
from receptionist.media.turn_stream import NativeTurnCoordinator


class SyntheticSTT:
    def __init__(self, events):
        self.sequence = events
    async def events(self, frames, **kw):
        async for _ in frames:
            pass
        for event in self.sequence:
            yield event


class SyntheticTTS:
    async def events(self, text, **kw):
        assert text == 'Verified clinic response.'
        yield {"event":"audio","pcm16":b'\0'*640,"sample_rate":16000}
        yield {"event":"end","audio_seconds":.02}


async def audio_frames():
    for i in range(3):
        yield b'\0'*640


@pytest.fixture
def config(monkeypatch):
    monkeypatch.setenv('NATIVE_STREAMING_CALLS_APPROVED','true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED','true')


@pytest.mark.asyncio
async def test_native_stream_only_posts_complete_transcript_once(config):
    calls=[]
    def handler(request):
        calls.append(request)
        assert request.url.path == '/api/v1/public/sessions/call-1/turn'
        assert request.headers['authorization'] == 'Bearer synthetic-session-token'
        assert request.headers['content-type'] == 'application/json'
        assert b'salam' in request.content
        return httpx.Response(200,json={'turn_id':'turn-1','state':'INTENT','reply':'Verified clinic response.'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        unit = NativeTurnCoordinator(client,base_url='https://localhost',session_id='call-1',token='synthetic-session-token',
            stt=SyntheticSTT([{'event':'partial','text':'uncertain'}, {'event':'final','text':'salam','final':True}]),
            tts=SyntheticTTS())
        results=[event async for event in unit.run(audio_frames(),request_id='req-00112233')]
    assert [event['event'] for event in results] == ['partial','confirmed_turn','audio','end']
    assert results[0]['text'] == 'uncertain' and results[1]['turn_id'] == 'turn-1'
    assert len(calls)==1


@pytest.mark.asyncio
async def test_native_stream_incomplete_never_submits_a_booking(config):
    called=[]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: (called.append(req),httpx.Response(200))[1])) as client:
        unit=NativeTurnCoordinator(client,base_url='https://localhost',session_id='call-1',token='secret',
            stt=SyntheticSTT([{'event':'partial','text':'yes'}]),tts=SyntheticTTS())
        with pytest.raises(ProviderError,match='STT_STREAM_INCOMPLETE'):
            async for _ in unit.run(audio_frames(),request_id='req-00112233'):
                pass
    assert not called


@pytest.mark.asyncio
async def test_native_stream_never_talks_after_human_connected(config):
    stt=SyntheticSTT([{'event':'final','text':'hello','final':True}])
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200,
        json={'turn_id':'turn-1','state':'HUMAN_CONNECTED','reply':'Verified clinic response.'}))) as client:
        unit=NativeTurnCoordinator(client,base_url='https://localhost',session_id='call-1',token='secret',stt=stt,tts=SyntheticTTS())
        results=[x async for x in unit.run(audio_frames(),request_id='req-00112233')]
    assert [x['event'] for x in results] == ['human_connected']


@pytest.mark.asyncio
async def test_native_stream_cannot_start_unapproved(monkeypatch):
    monkeypatch.delenv('NATIVE_STREAMING_CALLS_APPROVED',raising=False)
    called=[]
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: (called.append(req),httpx.Response(200))[1])) as client:
        unit=NativeTurnCoordinator(client,base_url='https://localhost',session_id='call-1',token='secret',
            stt=SyntheticSTT([]),tts=SyntheticTTS())
        with pytest.raises(ProviderError,match='NATIVE_TURN_NOT_APPROVED'):
            async for _ in unit.run(audio_frames(),request_id='req-00112233'):
                pass
    assert not called

@pytest.mark.asyncio
async def test_native_stream_rejects_audio_after_declared_end(config):
    class ImproperTTS:
        async def events(self, text, **kwargs):
            yield {'event': 'end'}
            yield {'event': 'audio', 'pcm16': bytes(640), 'sample_rate': 16000}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200,
        json={'turn_id': 'turn-1', 'state': 'INTENT', 'reply': 'Verified clinic response.'}))) as client:
        unit = NativeTurnCoordinator(client, base_url='https://localhost', session_id='call-1', token='secret',
            stt=SyntheticSTT([{'event': 'final', 'text': 'hello', 'final': True}]), tts=ImproperTTS())
        with pytest.raises(ProviderError, match='UNEXPECTED_TTS_EVENT'):
            async for _ in unit.run(audio_frames(), request_id='req-00112233'):
                pass
