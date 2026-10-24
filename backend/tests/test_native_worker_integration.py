"""Actual LiveKit worker event-loop wiring with a synthetic RTC transport."""
import asyncio
import json
import struct
import sys
from types import ModuleType, SimpleNamespace

import pytest

from receptionist.media.native_runtime import NativeMediaTurn


@pytest.mark.asyncio
async def test_livekit_worker_feeds_audio_before_vad_finishes_and_fences_output(monkeypatch):
    rtc = ModuleType('livekit.rtc')
    livekit = ModuleType('livekit')
    livekit.rtc = rtc
    monkeypatch.setitem(sys.modules, 'livekit', livekit)
    monkeypatch.setitem(sys.modules, 'livekit.rtc', rtc)
    # Isolate this synthetic import from the real installed LiveKit worker:
    # the temporary module must not escape into subsequent pytest cases.
    monkeypatch.delitem(sys.modules, 'receptionist.media.livekit_worker', raising=False)
    import receptionist.media.livekit_worker as worker

    speech = struct.pack('<h', 4500) * 320
    silent = bytes(640)
    frames = [speech] * 6 + [silent] * 50
    class AudioStream:
        def __init__(self, *args, **kw):
            self.closed = False
        async def __aiter__(self):
            for pcm in frames:
                await asyncio.sleep(0)
                yield SimpleNamespace(frame=SimpleNamespace(data=pcm))
        async def aclose(self):
            self.closed = True
    rtc.AudioStream = AudioStream
    received, events, played = [], [], []
    class FakeCoordinator:
        async def run(self, incoming, *, request_id):
            i = 0
            async for frame in incoming:
                i += 1
                received.append(frame)
                if i == 1:
                    yield {'event':'partial','text':'نمونه'}
            yield {'event':'confirmed_turn','turn_id':'v1','state':'INTENT'}
            yield {'event':'audio','pcm16':bytes(640),'sample_rate':16000}
            yield {'event':'end'}
    def new_turn(client, **kw):
        return NativeMediaTurn(FakeCoordinator(), emit_event=kw['emit_event'],
            send_audio=kw['send_audio'],sample_rate=kw['source_rate'],
            generation=kw['generation'],generation_current=kw['generation_current'],
            request_id=kw['request_id'])
    monkeypatch.setattr(worker, 'native_enabled', lambda: True)
    monkeypatch.setattr(worker, 'new_native_turn', new_turn)
    agent = object.__new__(worker.RoomAgent)
    agent.caller_ready, agent.finished = asyncio.Event(), asyncio.Event()
    agent.human_present, agent.lease_lost = False, False
    agent.generation = 0
    agent.playback, agent.processing, agent.pending_audio, agent.native_turn = None, None, None, None
    agent.client, agent.api_url = None, 'https://api.test'
    agent.record = {'session_id':'call-1','token':'synthetic'}
    class Transport:
        def interrupt(self): pass
        async def send_audio(self, pcm, rate): played.append((pcm,rate))
    agent.transport = Transport()
    async def publish(data, **kw): events.append(json.loads(data))
    agent.room = SimpleNamespace(local_participant=SimpleNamespace(publish_data=publish))
    await agent.listen(object())
    assert agent.caller_ready.is_set()
    assert agent.processing is not None
    await agent.processing
    assert any(e['event']=='partial' for e in events)
    assert any(e['event']=='confirmed_turn' for e in events)
    assert len(received) >= 2 and all(len(p) == 640 for p in received)
    assert played == [(bytes(640),16000)]


@pytest.mark.asyncio
async def test_audiosocket_bridge_uses_native_stream_and_preserves_human_fallback(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from uuid import uuid4, UUID
    import httpx
    from receptionist.media import audiosocket
    from receptionist.media.audio import wav_bytes
    monkeypatch.setattr(audiosocket, 'native_enabled', lambda: True)
    input_frames, paths, writes = [], [], []
    class Coord:
        async def run(self, incoming, *, request_id):
            async for frame in incoming:
                input_frames.append(frame)
            yield {'event':'confirmed_turn','turn_id':'t1','state':'INTENT'}
            yield {'event':'audio','pcm16':bytes(640),'sample_rate':16000}
            yield {'event':'end'}
    def native_turn(client, **kw):
        return NativeMediaTurn(Coord(), emit_event=kw['emit_event'], send_audio=kw['send_audio'],
             sample_rate=kw['source_rate'],generation=kw['generation'],
             generation_current=kw['generation_current'],request_id=kw['request_id'])
    monkeypatch.setattr(audiosocket, 'new_native_turn', native_turn)
    identifier = str(uuid4())
    def api(req):
        paths.append((req.method, req.url.path))
        if req.url.path.endswith('/claim'):
            return httpx.Response(200,json={'session_id':'call-1','token':'synthetic',
                'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=2)).isoformat()})
        if req.url.path.endswith('/speech'):
            return httpx.Response(200,content=wav_bytes(bytes(320),8000))
        return httpx.Response(200,json={'state':'HANDOFF_PENDING'})
    client = httpx.AsyncClient(transport=httpx.MockTransport(api))
    monkeypatch.setattr(audiosocket.httpx, 'AsyncClient', lambda **kw: client)
    reader = asyncio.StreamReader()
    reader.feed_data(audiosocket.encode_frame(1,UUID(identifier).bytes))
    high = struct.pack('<h', 5000)*160
    for sample in [high]*6+[bytes(320)]*50:
        reader.feed_data(audiosocket.encode_frame(0x10,sample))
    reader.feed_data(audiosocket.encode_frame(0))
    reader.feed_eof()
    class Writer:
        closing = False
        def write(self, data): writes.append(data)
        async def drain(self): await asyncio.sleep(0)
        def close(self): self.closing = True
        def is_closing(self): return self.closing
        async def wait_closed(self): pass
    writer=Writer()
    bridge=audiosocket.AudioSocketBridge('https://api.test','synthetic-media-token')
    await bridge._call(reader,writer)
    assert writer.closing
    assert ('POST','/api/v1/internal/media/claim') in paths
    assert ('POST','/api/v1/public/sessions/call-1/end') in paths
    assert not any(p.endswith('/audio') for _,p in paths)
    assert len(input_frames)>5
    assert any(part[0]==0x10 and len(part)==323 for part in writes)  # PCM16/8k wire frame


@pytest.mark.asyncio
async def test_interrupted_native_turn_does_not_trigger_service_failure_transfer(monkeypatch):
    from receptionist.media.native_runtime import NativeMediaTurn
    from receptionist.providers import ProviderError
    # A barge-in before submission is routine cancellation, not a telephony
    # outage. Verify the shared error discriminator used by both workers.
    from receptionist.media.native_runtime import routine_interruption
    assert routine_interruption(ProviderError('TURN_INTERRUPTED')) is True
    assert routine_interruption(ProviderError('TURN_OUTCOME_UNKNOWN',unknown_outcome=True)) is False
