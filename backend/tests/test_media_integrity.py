"""Bounded decoder/admission and transport interruption regressions."""

import asyncio
import importlib.util
import io
from pathlib import Path
import struct
import sys
from types import SimpleNamespace
import wave

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from receptionist.media.audio import TurnBuffer, decode_wav, wav_bytes
from receptionist.media.audiosocket import read_frame
from receptionist.media.livekit_worker import RoomAgent


def test_wav_decoder_rejects_expansion_and_truncation():
    raw = io.BytesIO()
    with wave.open(raw, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(1)
        output.writeframes(b"\0\0" * 50)
    with pytest.raises(ValueError):
        decode_wav(raw.getvalue(), 16000)
    with pytest.raises(ValueError):
        decode_wav(wav_bytes(b"\0\0" * 1600, 16000)[:-16])
    with pytest.raises(ValueError):
        decode_wav(b"not a wave")


def test_high_rate_turns_are_downsampled_before_bounded_upload():
    buffer = TurnBuffer(sample_rate=192000)
    frame = struct.pack("<h", 1200) * 3840
    result = None
    for _ in range(1100):
        result, _ = buffer.push(frame)
        if result:
            break
    assert result and len(result) < 5_000_000
    with wave.open(io.BytesIO(result), "rb") as stream:
        assert stream.getframerate() == 16000
        assert 19.9 <= stream.getnframes() / stream.getframerate() <= 20.1


@pytest.mark.asyncio
async def test_empty_audiosocket_pcm_is_rejected_instead_of_spin():
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x10\0\0")
    with pytest.raises(ValueError, match="empty"):
        await read_frame(reader)


def speech_service():
    path = Path(__file__).resolve().parents[2] / "services" / "local_speech" / "app.py"
    name = "synthetic_local_speech_test"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_local_decoder_accepts_pcm_but_rejects_playlist_and_overlong_audio(tmp_path):
    service = speech_service()
    valid = wav_bytes(b"\0\0" * 16000, 16000)
    assert len(service.decode_audio(valid)) == 32000
    source = tmp_path / "private.wav"
    source.write_bytes(valid)
    playlist = f"#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1.0,\n{source.as_uri()}\n#EXT-X-ENDLIST\n".encode()
    with pytest.raises(HTTPException) as error:
        service.decode_audio(playlist)
    assert error.value.status_code == 422
    with pytest.raises(HTTPException) as error:
        service.decode_audio(wav_bytes(b"\0\0" * (16000 * 61), 16000))
    assert error.value.status_code == 422


@pytest.mark.asyncio
async def test_speech_overload_rejects_before_reading_upload():
    service = speech_service()
    service._admission = asyncio.Semaphore(1)
    await service._admission.acquire()
    received = False

    async def receive():
        nonlocal received
        received = True
        return {"type": "http.request", "body": b"audio" * 1000000, "more_body": False}

    request = Request({"type": "http", "method": "POST", "path": "/transcribe", "headers": []}, receive)
    try:
        with pytest.raises(HTTPException) as error:
            await service.transcribe(request, "[]")
        assert error.value.status_code == 503
        assert not received
    finally:
        service._admission.release()


def fake_agent(client):
    # Avoid allocating the optional native RTC engine in protocol-unit tests.
    agent = object.__new__(RoomAgent)
    agent.client = client
    agent.base = "https://reception.example.test/api/v1/public/sessions/synthetic"
    agent.headers = {"Authorization": "Bearer synthetic"}
    agent.human_present = False
    agent.lease_lost = False
    agent.finished = asyncio.Event()
    agent.call_deadline = asyncio.get_running_loop().time() + 1800
    agent.generation = 3
    agent.playback = None
    agent.pending_audio = None
    agent.native_turn = None
    agent.source = SimpleNamespace(clear_queue=lambda: None)
    from receptionist.media.contracts import LiveKitTransport
    agent.transport = LiveKitTransport(agent.source, None, None)
    return agent


@pytest.mark.asyncio
async def test_barge_in_keeps_committed_result_but_never_plays_stale_generations():
    posted = []
    published = []

    async def transport(request):
        posted.append(request.content)
        return httpx.Response(200, json={"turn_id": str(len(posted)), "state": "REMINDER_CONSENT",
            "booking": {"id": "already-committed", "status": "CONFIRMED"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        agent = fake_agent(client)
        agent.pending_audio = (b"second utterance", 2)

        async def publish(data, **kwargs):
            published.append(data)

        async def forbidden_play(*args):
            pytest.fail("An interrupted generation was spoken")

        agent.room = SimpleNamespace(local_participant=SimpleNamespace(publish_data=publish))
        agent.play = forbidden_play
        await agent.process(b"first utterance", generation=1)
        assert posted == [b"first utterance", b"second utterance"]
        assert len(published) == 2 and b"already-committed" in published[0]
        assert agent.playback is None


@pytest.mark.asyncio
async def test_media_watchdog_stops_a_worker_when_poll_renewal_is_lost():
    agent = fake_agent(None)
    agent.lease_deadline = asyncio.get_running_loop().time() - 1
    await agent.watch_lease()
    assert agent.lease_lost and agent.finished.is_set()
    assert agent.pending_audio is None and agent.generation == 4


@pytest.mark.asyncio
async def test_call_budget_deadline_stops_media_even_with_a_live_worker_lease():
    agent = fake_agent(None)
    agent.lease_deadline = asyncio.get_running_loop().time() + 30
    agent.call_deadline = asyncio.get_running_loop().time() - 1
    await agent.watch_lease()
    assert agent.finished.is_set() and not agent.lease_lost
    assert agent.generation == 4
