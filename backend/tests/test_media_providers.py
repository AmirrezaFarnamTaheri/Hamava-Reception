import asyncio
import hashlib
import hmac
import io
import json
import math
import struct
import time
import wave
from uuid import uuid4

import httpx
import pytest

from receptionist.media.audio import TurnBuffer, decode_wav, wav_bytes
from receptionist.media.audiosocket import encode_frame, read_frame
from receptionist.providers import (
    AuthorizedCalendarAdapter, CircuitBreaker, KavenegarSMS, ProviderError,
    SpeechGateway, ZarinpalGateway, approved_url, provider_request, verify_webhook,
)


async def test_fragmented_audiosocket_frames_and_dtmf():
    reader = asyncio.StreamReader()
    stream = encode_frame(1, uuid4().bytes) + encode_frame(0x10, b"\0" * 320) + encode_frame(3, b"#") + encode_frame(0)
    for i in range(0, len(stream), 7):
        reader.feed_data(stream[i:i+7])
    reader.feed_eof()
    assert (await read_frame(reader))[0] == 1
    kind, data = await read_frame(reader)
    assert kind == 0x10 and len(data) == 320
    assert await read_frame(reader) == (3, b"#")
    assert await read_frame(reader) == (0, b"")


@pytest.mark.parametrize("packet", [encode_frame(1, b"bad"), encode_frame(0x10, b"odd"), encode_frame(3, b"x"), encode_frame(3, b"00"), encode_frame(0x99)])
async def test_bad_media_frames_fail_closed(packet):
    reader = asyncio.StreamReader()
    reader.feed_data(packet)
    reader.feed_eof()
    with pytest.raises(ValueError):
        await read_frame(reader)


async def test_truncated_media_frame_closes():
    reader = asyncio.StreamReader()
    reader.feed_data(b"\x10\x01\x40\0")
    reader.feed_eof()
    with pytest.raises(asyncio.IncompleteReadError):
        await read_frame(reader)


def test_pcm_wav_resampling_preserves_duration():
    pcm = struct.pack("<" + "h" * 16000, *[int(2000 * math.sin(2 * math.pi * 440 * n / 16000)) for n in range(16000)])
    encoded = wav_bytes(pcm, 16000)
    resampled = decode_wav(encoded, 8000)
    assert abs(len(resampled) - 16000) <= 2
    with wave.open(io.BytesIO(encoded), "rb") as source:
        assert source.getnchannels() == 1 and source.getsampwidth() == 2
    assert encode_frame(0x10, b"\0" * 320)[:3] == b"\x10\x01\x40"


def test_endpointing_supports_barge_in_and_does_not_transcribe_silence():
    buffer = TurnBuffer(sample_rate=8000)
    silence = b"\0" * 320
    speech = struct.pack("<" + "h" * 160, *([2000] * 160))
    for _ in range(100):
        assert buffer.push(silence) == (None, False)
    starts = 0
    for _ in range(25):
        result, started = buffer.push(speech)
        assert result is None
        starts += started
    assert starts == 1
    result = None
    for _ in range(50):
        result, _ = buffer.push(silence)
    assert result and result[:4] == b"RIFF"
    assert not buffer.speaking


def test_processor_approval_and_allowlist(monkeypatch):
    monkeypatch.delenv("SPEECH_PROCESSOR_APPROVED", raising=False)
    assert not SpeechGateway().configured
    with pytest.raises(ProviderError):
        approved_url("https://example.com", "SPEECH_PROCESSOR_APPROVED")
    monkeypatch.setenv("SPEECH_PROCESSOR_APPROVED", "true")
    monkeypatch.setenv("APPROVED_PROVIDER_HOSTS", "speech.example.test")
    assert approved_url("https://speech.example.test/", "SPEECH_PROCESSOR_APPROVED") == "https://speech.example.test"
    for url in ("https://unapproved.example", "https://user:pass@speech.example.test", "http://speech.example.test"):
        with pytest.raises(ProviderError):
            approved_url(url, "SPEECH_PROCESSOR_APPROVED")


async def test_sms_send_is_sent_not_delivered(monkeypatch):
    monkeypatch.setenv("SMS_PROVIDER_APPROVED", "true")
    monkeypatch.setenv("KAVENEGAR_API_KEY", "testonly")
    monkeypatch.setenv("KAVENEGAR_SENDER", "test")
    def handler(request):
        return httpx.Response(200, json={"return": {"status": 200}, "entries": [{"messageid": 123, "status": 1, "cost": 1000}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await KavenegarSMS(client).send("09123456789", "Synthetic test")
    assert result["status"] == "SENT"
    assert result["provider_id"] == "123"


async def test_non_idempotent_timeout_is_unknown_and_not_retryable():
    def handler(request):
        raise httpx.ReadTimeout("response lost")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ProviderError) as error:
            await provider_request("POST", "https://example.test/send", operation=str(uuid4()), write=True, client=client)
    assert error.value.unknown_outcome and not error.value.retryable


async def test_calendar_unknown_write_reconciles_without_second_post(monkeypatch):
    monkeypatch.setenv("CALENDAR_PARTNER_APPROVED", "true")
    monkeypatch.setenv("APPROVED_PROVIDER_HOSTS", "calendar.example.test")
    seen = []
    expected = {"slot_id": "slot-1", "patient_token": "subject-1"}
    def handler(request):
        seen.append((request.method, request.url.path))
        if request.url.path == "/capabilities":
            return httpx.Response(200, json={"conditional_create": True, "idempotency": True, "readback": True})
        if request.method == "POST":
            raise httpx.ReadTimeout("committed response lost")
        return httpx.Response(200, json={"id": "booking-1", "status": "CONFIRMED", **expected})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await AuthorizedCalendarAdapter("https://calendar.example.test", "test", client).create_verified(expected, "request-1")
    assert result["id"] == "booking-1"
    assert sum(method == "POST" for method, _ in seen) == 1
    assert any(path == "/appointments/by-idempotency-key" for _, path in seen)


async def test_calendar_rejects_unverified_capability(monkeypatch):
    monkeypatch.setenv("CALENDAR_PARTNER_APPROVED", "true")
    monkeypatch.setenv("APPROVED_PROVIDER_HOSTS", "calendar.example.test")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"conditional_create": False}))) as client:
        with pytest.raises(ProviderError, match="CALENDAR_ATOMICITY"):
            await AuthorizedCalendarAdapter("https://calendar.example.test", "test", client).create_verified({}, "request-1")


def test_webhook_signature_timestamp_and_payload_binding():
    body, secret, ts = b'{"status":"DELIVERED"}', "secret-32-characters-for-test-only", str(int(time.time()))
    signature = hmac.new(secret.encode(), ts.encode() + b"." + body, hashlib.sha256).hexdigest()
    assert verify_webhook(body, ts, signature, secret)
    assert not verify_webhook(body + b" ", ts, signature, secret)
    assert not verify_webhook(body, ts, signature, secret, now=int(ts) + 301)


def test_circuit_breaker_recovers_after_cooldown():
    circuit = CircuitBreaker(threshold=2, cooldown=.01)
    circuit.failure()
    circuit.failure()
    with pytest.raises(ProviderError, match="CIRCUIT_OPEN"):
        circuit.allow()
    circuit.opened_at -= 1
    circuit.allow()
    circuit.success()
    assert circuit.failures == 0


async def test_zarinpal_verifies_server_amount_and_not_redirect(monkeypatch):
    monkeypatch.setenv("PAYMENT_PROVIDER_APPROVED", "true")
    monkeypatch.setenv("ZARINPAL_MERCHANT_ID", "synthetic-merchant")
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"data": {"code": 100, "ref_id": "verified-synthetic"}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        verified = await ZarinpalGateway(client).verify("synthetic-authority", 100000)
    assert verified["verified"]
    assert requests[0]["amount"] == 1000000

