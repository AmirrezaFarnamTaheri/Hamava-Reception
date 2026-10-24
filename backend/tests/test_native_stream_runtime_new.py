"""Native streaming runtime: no partial turn commits and bounded live PCM."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from receptionist.providers import ProviderError
from receptionist.media.native_runtime import PCMIngress, NativeMediaTurn
from receptionist.media.streaming import GatewayPCMStream


@pytest.mark.asyncio
async def test_pcm_ingress_resamples_8khz_and_signals_completion():
    ingress = PCMIngress(max_queue_frames=8)
    ingress.feed(b'\0\0' * 160, 8000)
    ingress.feed(b'\0\0' * 160, 8000)
    ingress.finish()
    out = [x async for x in ingress.frames()]
    assert len(out) == 2 and all(len(x) == 640 for x in out)
    assert ingress.audio_bytes == 1278  # resampler preserves its actual sample count; framing pads two bytes


@pytest.mark.asyncio
async def test_pcm_ingress_rejects_overflow_without_silent_audio_loss():
    ingress = PCMIngress(max_queue_frames=1)
    ingress.feed(b'\0' * 640, 16000)
    with pytest.raises(ProviderError, match='STREAM_BACKPRESSURE'):
        ingress.feed(b'\0' * 640, 16000)
    with pytest.raises(ProviderError, match='STREAM_BACKPRESSURE'):
        assert [x async for x in ingress.frames()]


@pytest.mark.asyncio
async def test_native_media_turn_yields_partial_and_sends_fenced_audio(monkeypatch):
    monkeypatch.setenv('NATIVE_STREAMING_CALLS_APPROVED', 'true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED', 'true')
    partials, played, calls = [], [], []
    class STT:
        async def events(self, frames, **kwargs):
            first = True
            async for item in frames:
                if first:
                    yield {'event': 'partial', 'text': 'نامشخص'}
                    first = False
            yield {'event': 'final', 'final': True, 'text': 'سلام'}
    class TTS:
        async def events(self, value):
            yield {'event': 'audio', 'pcm16': b'\0'*640, 'sample_rate': 16000}
            yield {'event': 'end'}
    def handler(req):
        calls.append(json.loads(req.content))
        return httpx.Response(200, json={'turn_id': 't1', 'state': 'INTENT', 'reply': 'متن پاسخ'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        async def emit(item):
            if item.get('event') == 'partial':
                partials.append(item['text'])
        async def send(pcm, rate):
            played.append((pcm, rate))
        coordinator = __import__('receptionist.media.turn_stream', fromlist=['NativeTurnCoordinator']).NativeTurnCoordinator(
            client, base_url='https://localhost', session_id='call-1', token='fake', stt=STT(), tts=TTS())
        turn = NativeMediaTurn(coordinator, emit_event=emit, send_audio=send, sample_rate=16000, generation=1,
                               generation_current=lambda: 1, request_id='req-12345678')
        turn.start(b'\0'*640)
        await asyncio.sleep(0)
        turn.feed(b'\0'*640)
        turn.finish()
        await turn.wait()
    assert partials == ['نامشخص']
    assert len(calls) == 1 and calls[0]['text'] == 'سلام'
    assert len(played) == 1 and played[0][1] == 16000


@pytest.mark.asyncio
async def test_native_media_turn_does_not_play_after_interrupt(monkeypatch):
    monkeypatch.setenv('NATIVE_STREAMING_CALLS_APPROVED', 'true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED', 'true')
    async def fake_run(frames, *, request_id, keyterms=None):
        async for _ in frames:
            pass
        yield {'event':'confirmed_turn', 'turn_id':'already-committed','state':'INTENT'}
        yield {'event':'audio','pcm16':b'\0'*640,'sample_rate':16000}
        yield {'event':'end'}
    current = 1
    played = []
    async def emit(e): pass
    async def send(pcm, rate): played.append(pcm)
    turn = NativeMediaTurn(SimpleNamespace(run=fake_run), emit_event=emit, send_audio=send,
                           sample_rate=16000,generation=1,generation_current=lambda:current,request_id='req-abcdef12')
    turn.start(b'\0'*640)
    current = 2
    turn.finish()
    await turn.wait()
    assert played == []


@pytest.mark.asyncio
async def test_framed_tts_stream_rejects_missing_end_marker(monkeypatch):
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED','true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED','true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS','speech.example.test')
    import struct
    payload = struct.pack('!BH', 0x10, 640) + b'\0' * 640
    response = httpx.Response(200, content=payload, headers={
        'Content-Type':'application/x-hamava-pcm-frames',
        'X-Audio-Format':'pcm_s16le','X-Audio-Sample-Rate':'16000','X-Audio-Channels':'1'})
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:response)) as client:
        gateway = GatewayPCMStream('https://speech.example.test','synthetic-token', client)
        with pytest.raises(ProviderError, match='TTS_STREAM_TRUNCATED'):
            async for _ in gateway.events('سلام'):
                pass


@pytest.mark.asyncio
async def test_framed_tts_stream_emits_before_explicit_terminal_frame(monkeypatch):
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED','true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED','true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS','speech.example.test')
    import struct
    data = struct.pack('!BH', 0x10, 640) + b'\0'*640 + struct.pack('!BH',0,8) + (640).to_bytes(8,'big')
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=data,headers={
        'Content-Type':'application/x-hamava-pcm-frames','X-Audio-Format':'pcm_s16le',
        'X-Audio-Sample-Rate':'16000','X-Audio-Channels':'1'}))) as client:
        output=[x async for x in GatewayPCMStream('https://speech.example.test','synthetic',client).events('سلام')]
    assert [o['event'] for o in output] == ['audio','end']
    assert output[-1]['audio_seconds'] == pytest.approx(.02)

@pytest.mark.asyncio
async def test_transport_downsampler_flushes_a_single_final_frame():
    from receptionist.media.native_runtime import PCMTransportOutput
    sent = []
    async def send(frame, rate):
        assert rate == 8000 and len(frame) == 320
        sent.append(frame)
    sink = PCMTransportOutput(send)
    await sink.feed(b'\0' * 640)
    await sink.feed(b'\0' * 640)
    await sink.finish()
    assert len(sent) == 2


def test_native_turn_factory_requires_explicit_activation(monkeypatch):
    from receptionist.media.native_runtime import native_enabled
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED','true')
    monkeypatch.setenv('NATIVE_STREAMING_CALLS_APPROVED','false')
    assert not native_enabled()
    monkeypatch.setenv('NATIVE_STREAMING_CALLS_APPROVED','true')
    monkeypatch.setenv('DEEPGRAM_STREAM_TOKEN','token')
    monkeypatch.setenv('SPEECH_GATEWAY_TOKEN','token')
    assert native_enabled()
    monkeypatch.delenv('DEEPGRAM_STREAM_TOKEN')
    assert not native_enabled()


@pytest.mark.asyncio
async def test_framed_tts_rejects_network_payload_after_end_marker(monkeypatch):
    monkeypatch.setenv('SPEECH_PROCESSOR_APPROVED','true')
    monkeypatch.setenv('SPEECH_STREAMING_APPROVED','true')
    monkeypatch.setenv('APPROVED_PROVIDER_HOSTS','speech.example.test')
    from httpx import AsyncByteStream
    import struct
    class Stream(AsyncByteStream):
        async def __aiter__(self):
            yield struct.pack('!BH',16,640)+bytes(640)
            yield struct.pack('!BH',0,8)+(640).to_bytes(8,'big')
            yield b'extra garbage'  # response must not silently ignore suffix
        async def aclose(self): pass
    headers={'content-type':'application/x-hamava-pcm-frames','x-audio-format':'pcm_s16le',
             'x-audio-sample-rate':'16000','x-audio-channels':'1'}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,stream=Stream(),headers=headers))) as client:
        with pytest.raises(ProviderError,match='TTS_STREAM_TRUNCATED'):
            async for _ in GatewayPCMStream('https://speech.example.test','token',client).events('سلام'):
                pass
