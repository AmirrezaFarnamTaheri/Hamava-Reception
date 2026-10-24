"""Approved external boundaries. A transport success is not a business outcome.

No provider is activated merely because an API key exists. The operator must
explicitly approve each processor. Unknown non-idempotent write outcomes are
reconciled, never retried automatically.
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import math
import os
from collections import OrderedDict
import threading
import time
import wave
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx


class ProviderError(Exception):
    def __init__(self, code: str, *, unknown_outcome: bool = False, retryable: bool = False):
        super().__init__(code)
        self.code, self.unknown_outcome, self.retryable = code, unknown_outcome, retryable


def enabled(name: str) -> bool:
    return os.getenv(name, "false").lower() in {"true", "1", "yes"}


@dataclass
class CircuitBreaker:
    threshold: int = 3
    cooldown: float = 30.0
    failures: int = 0
    opened_at: float = 0

    def allow(self) -> None:
        if self.failures >= self.threshold and time.monotonic() - self.opened_at < self.cooldown:
            raise ProviderError("PROVIDER_CIRCUIT_OPEN", retryable=True)

    def success(self) -> None:
        self.failures = 0

    def failure(self) -> None:
        self.failures += 1
        if self.failures >= self.threshold:
            self.opened_at = time.monotonic()


_breakers: dict[str, CircuitBreaker] = {}
_speech_cache: OrderedDict[tuple, tuple[float, bytes]] = OrderedDict()
_speech_cache_lock = threading.Lock()
_speech_cache_counts = {"hits": 0, "misses": 0}


def speech_cache_stats() -> dict:
    with _speech_cache_lock:
        return {**_speech_cache_counts, "entries": len(_speech_cache),
                "bytes": sum(len(value[1]) for value in _speech_cache.values())}


def approved_url(value: str, approval_env: str, *, allow_local: bool = False) -> str:
    if not enabled(approval_env):
        raise ProviderError("PROCESSOR_NOT_APPROVED")
    parsed = urlparse(value)
    allowed = {x.strip() for x in os.getenv("APPROVED_PROVIDER_HOSTS", "").split(",") if x.strip()}
    if parsed.username or parsed.password or parsed.fragment or parsed.query or not parsed.hostname:
        raise ProviderError("INVALID_PROVIDER_URL")
    if parsed.hostname not in allowed:
        raise ProviderError("PROVIDER_HOST_NOT_ALLOWLISTED")
    if parsed.scheme != "https" and not (allow_local and parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"} and enabled("ALLOW_LOCAL_HTTP_PROVIDERS")):
        raise ProviderError("HTTPS_REQUIRED")
    return value.rstrip("/")


async def provider_request(method: str, url: str, *, operation: str, write: bool = False,
                           client: httpx.AsyncClient | None = None, **kwargs) -> httpx.Response:
    breaker = _breakers.setdefault(operation, CircuitBreaker())
    breaker.allow()
    owned = client is None
    session = client or httpx.AsyncClient(timeout=httpx.Timeout(float(os.getenv("PROVIDER_OPERATION_TIMEOUT_SECONDS", "12")), connect=4.0), follow_redirects=False)
    try:
        response = await session.request(method, url, **kwargs)
        if response.status_code >= 500 or response.status_code == 429:
            breaker.failure()
            raise ProviderError("PROVIDER_UNAVAILABLE", unknown_outcome=write, retryable=not write)
        if not 200 <= response.status_code < 300:
            raise ProviderError("PROVIDER_REJECTED", unknown_outcome=write and response.status_code >= 300)
        breaker.success()
        return response
    except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
        breaker.failure()
        raise ProviderError("PROVIDER_TIMEOUT", unknown_outcome=write, retryable=not write) from exc
    finally:
        if owned:
            await session.aclose()


class SpeechGateway:
    """Our documented speech-gateway contract, implemented by local_speech.py.

    Domestic vendors can implement the same contract in an adapter service.
    Raw audio is memory-only here. A fallback must be separately approved.
    """
    def __init__(self, client: httpx.AsyncClient | None = None, *, context=None):
        self.client = client
        self.context = context
        self.last_cache_hit = False

    @property
    def configured(self) -> bool:
        try:
            approved_url(os.getenv("SPEECH_GATEWAY_URL", ""), "SPEECH_PROCESSOR_APPROVED", allow_local=True)
            return bool(os.getenv("SPEECH_GATEWAY_TOKEN"))
        except ProviderError:
            return False

    def base(self, secondary: bool = False) -> str:
        prefix = "SPEECH_FALLBACK" if secondary else "SPEECH_GATEWAY"
        gate = "SPEECH_FALLBACK_APPROVED" if secondary else "SPEECH_PROCESSOR_APPROVED"
        return approved_url(os.getenv(prefix + "_URL", ""), gate, allow_local=True)

    def _require_context(self):
        from .config import settings
        if self.context is None and settings.environment.lower() in {"prod", "production"}:
            raise ProviderError("PROVIDER_CONTEXT_REQUIRED")

    async def transcribe(self, audio: bytes, content_type: str, keyterms: list[str] | None = None) -> dict:
        self._require_context()
        if not self.configured:
            raise ProviderError("SPEECH_NOT_CONFIGURED")
        if not 32 <= len(audio) <= 5_000_000:
            raise ProviderError("INVALID_AUDIO_BOUND")
        # Metered speech is bounded at the provider contract, including compressed inputs.
        maximum = 60
        known_duration = False
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav:
                maximum = wav.getnframes() / wav.getframerate()
                known_duration = True
                if not 0 < maximum <= 60:
                    raise ProviderError("AUDIO_DURATION_LIMIT")
        except (wave.Error, EOFError):
            maximum = 60
        terms = [str(value)[:120] for value in (keyterms or [])[:30]]
        for secondary in (False, True):
            if secondary and not enabled("SPEECH_FALLBACK_APPROVED"):
                raise ProviderError("SPEECH_UNAVAILABLE")
            provider = "speech_fallback" if secondary else "speech_primary"
            prefix = "SPEECH_FALLBACK" if secondary else "SPEECH_GATEWAY"
            headers = {"Authorization": "Bearer " + os.getenv(prefix + "_TOKEN", ""), "Content-Type": content_type,
                       "X-Language": "fa", "X-Max-Audio-Seconds": "60", "X-Keyterms": json.dumps(terms, ensure_ascii=True)}
            ticket = None
            started = time.monotonic()
            try:
                base = self.base(secondary)
                if self.context:
                    ticket = self.context.start(provider, "stt_audio_seconds", maximum, "transcribe_final", fallback=secondary)
                result = await provider_request("POST", base + "/transcribe", operation="stt-fallback" if secondary else "stt-primary",
                    content=audio, headers=headers, client=self.client)
                data = result.json()
                text, seconds = data["text"], float(data["audio_seconds"])
                confidence = data.get("confidence")
                if (not isinstance(text, str) or len(text) > 2000 or not math.isfinite(seconds) or not 0 <= seconds <= maximum + 0.05 or not known_duration and seconds <= 0
                        or confidence is not None and (not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or not 0 <= confidence <= 1)):
                    raise ValueError
                if self.context:
                    self.context.finish(ticket, maximum if known_duration else min(maximum, seconds), duration_ms=int((time.monotonic()-started)*1000))
                return {"text": text, "audio_seconds": maximum if known_duration else seconds, "provider_audio_seconds": seconds,
                        "duration_source": "submitted_pcm" if known_duration else "provider_reported_bounded", "confidence": confidence,
                        "model": str(data.get("model", "not_recorded"))[:120], "provider": provider, "final": True}
            except (KeyError, TypeError, ValueError) as exc:
                if ticket:
                    self.context.finish(ticket, 0, outcome="unknown", code="INVALID_STT_RESPONSE")
                raise ProviderError("INVALID_STT_RESPONSE") from exc
            except ProviderError as exc:
                if ticket:
                    self.context.finish(ticket, 0, outcome="no_charge" if exc.code == "PROVIDER_CIRCUIT_OPEN" else "unknown", code=exc.code)
                if secondary or not exc.retryable or not enabled("SPEECH_FALLBACK_APPROVED"):
                    raise
        raise ProviderError("SPEECH_UNAVAILABLE")

    async def transcribe_events(self, audio: bytes, content_type: str, keyterms: list[str] | None = None):
        """Common final-event interface; this buffered adapter never fabricates partials."""
        result = await self.transcribe(audio, content_type, keyterms)
        yield {"event": "final", **result}

    async def synthesize_chunks(self, text: str, *, slow=False, chunk_milliseconds=20):
        if chunk_milliseconds not in {10, 20, 40}:
            raise ProviderError("INVALID_AUDIO_CHUNK")
        wav = await self.synthesize(text, slow=slow)
        with wave.open(io.BytesIO(wav), "rb") as audio:
            frames = 16000 * chunk_milliseconds // 1000
            sequence = 0
            while chunk := audio.readframes(frames):
                yield {"event": "audio", "sequence": sequence, "pcm16": chunk, "sample_rate": 16000, "channels": 1,
                       "buffered": True}
                sequence += 1
            yield {"event": "end", "sequence": sequence, "buffered": True}

    @staticmethod
    def stream_capabilities():
        return {"stt_final": True, "stt_partial": False, "keyterms": True,
                "tts_pcm_chunks": True, "tts_native_streaming": False, "structured_model_tools": False}

    async def synthesize(self, text: str, *, slow: bool = False, cache_scope: str | None = None) -> bytes:
        self._require_context()
        if not isinstance(text, str) or not 1 <= len(text) <= 2000:
            raise ProviderError("INVALID_TTS_TEXT_BOUND")
        if self.context:
            self.context.authorize("speech_primary", "synthesize_wav")
        if not self.configured:
            raise ProviderError("SPEECH_NOT_CONFIGURED")
        base = self.base()
        key = (base, os.getenv("SPEECH_VOICE_VERSION", "configured-v1"), cache_scope,
               hashlib.sha256(text.encode()).hexdigest(), slow) if cache_scope else None
        self.last_cache_hit = False
        if key:
            with _speech_cache_lock:
                now = time.monotonic()
                for expired in [k for k, value in _speech_cache.items() if value[0] <= now]:
                    _speech_cache.pop(expired)
                cached = _speech_cache.get(key)
                if cached:
                    _speech_cache.move_to_end(key)
                    _speech_cache_counts["hits"] += 1
                    self.last_cache_hit = True
                    return cached[1]
                _speech_cache_counts["misses"] += 1
        ticket = self.context.start("speech_primary", "tts_characters", len(text), "synthesize_wav") if self.context else None
        started = time.monotonic()
        try:
            result = await provider_request("POST", base + "/synthesize", operation="tts-primary",
                json={"text": text, "language": "fa", "slow": slow, "format": "wav", "sample_rate": 16000},
                headers={"Authorization": "Bearer " + os.environ["SPEECH_GATEWAY_TOKEN"]}, client=self.client)
        except ProviderError as exc:
            if ticket:
                self.context.finish(ticket, 0, outcome="no_charge" if exc.code == "PROVIDER_CIRCUIT_OPEN" else "unknown", code=exc.code)
            raise
        data = result.content
        try:
            if len(data) > 8_000_000 or len(data) < 44 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
                raise ValueError
            with wave.open(io.BytesIO(data), "rb") as audio:
                frames = audio.getnframes()
                if (audio.getnchannels() != 1 or audio.getsampwidth() != 2 or audio.getframerate() != 16000
                        or not 160 <= frames <= 960000 or audio.getcomptype() != "NONE"
                        or len(audio.readframes(frames)) != frames * 2):
                    raise ValueError
        except (ValueError, EOFError, wave.Error) as exc:
            if ticket:
                # Accepted text is still billable, but malformed output is not
                # a healthy dependency observation.
                self.context.finish(ticket, len(text), code="INVALID_TTS_AUDIO", healthy=False, duration_ms=int((time.monotonic()-started)*1000))
            raise ProviderError("INVALID_TTS_AUDIO") from exc
        if ticket:
            self.context.finish(ticket, len(text), duration_ms=int((time.monotonic()-started)*1000))
        if key:
            with _speech_cache_lock:
                _speech_cache[key] = (time.monotonic()+900, data)
                while len(_speech_cache) > 32 or sum(len(value[1]) for value in _speech_cache.values()) > 16_000_000:
                    _speech_cache.popitem(last=False)
        return data


class KavenegarSMS:
    """No assumed idempotency support: timeout after send becomes UNKNOWN."""
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client

    @property
    def configured(self) -> bool:
        return enabled("SMS_PROVIDER_APPROVED") and bool(os.getenv("KAVENEGAR_API_KEY"))

    async def send(self, recipient: str, body: str, *, otp: str | None = None) -> dict:
        if not self.configured:
            raise ProviderError("SMS_NOT_CONFIGURED")
        key = os.environ["KAVENEGAR_API_KEY"]
        if not key.isalnum():
            raise ProviderError("INVALID_SMS_CONFIGURATION")
        if otp:
            template = os.getenv("KAVENEGAR_OTP_TEMPLATE")
            if not template:
                raise ProviderError("OTP_TEMPLATE_NOT_APPROVED")
            path, data = "verify/lookup", {"receptor": recipient, "token": otp, "template": template}
        else:
            sender = os.getenv("KAVENEGAR_SENDER")
            if not sender:
                raise ProviderError("SMS_SENDER_NOT_CONFIGURED")
            path, data = "sms/send", {"receptor": recipient, "message": body, "sender": sender}
        result = await provider_request("POST", f"https://api.kavenegar.com/v1/{key}/{path}.json",
                                         operation="sms-send", write=True, data=data, client=self.client)
        try:
            payload = result.json()
            if payload["return"]["status"] != 200:
                raise ProviderError("SMS_REJECTED")
            entry = payload["entries"][0]
            cost = entry.get("cost")
            if cost is not None and (isinstance(cost, bool) or not isinstance(cost, int) or cost < 0):
                raise ValueError
            if not isinstance(entry["messageid"], (int, str)) or not str(entry["messageid"]).isdigit():
                raise ValueError
            return {"provider_id": str(entry["messageid"]), "status": "SENT", "cost_rial": cost}
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("INVALID_SMS_RESPONSE", unknown_outcome=True) from exc

    async def delivery(self, provider_id: str) -> str:
        if not self.configured:
            raise ProviderError("SMS_NOT_CONFIGURED")
        key = os.environ["KAVENEGAR_API_KEY"]
        result = await provider_request("GET", f"https://api.kavenegar.com/v1/{key}/sms/status.json",
                                         operation="sms-status", params={"messageid": provider_id}, client=self.client)
        try:
            body = result.json()
            if body["return"]["status"] != 200:
                raise ProviderError("SMS_STATUS_UNAVAILABLE", retryable=True)
            entry = body["entries"][0]
            if str(entry.get("messageid", "")) != str(provider_id):
                raise ValueError
            status = int(entry["status"])
            return "DELIVERED" if status == 10 else "FAILED" if status in {6, 11, 13, 14, 100} else "SENT"
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError("INVALID_SMS_STATUS") from exc


class ZarinpalGateway:
    """A browser callback is a hint. Server-side verification proves settlement."""
    def __init__(self, client: httpx.AsyncClient | None = None, *, merchant_id: str | None = None, sandbox: bool | None = None):
        self.client = client
        self.merchant_id = merchant_id if merchant_id is not None else os.getenv("ZARINPAL_MERCHANT_ID")
        self.sandbox = sandbox if sandbox is not None else enabled("ZARINPAL_SANDBOX")

    @property
    def configured(self) -> bool:
        return enabled("PAYMENT_PROVIDER_APPROVED") and bool(self.merchant_id)

    @property
    def base(self) -> str:
        return "https://sandbox.zarinpal.com/pg" if self.sandbox else "https://payment.zarinpal.com/pg"

    async def create(self, amount_toman: int, callback_url: str, description: str) -> dict:
        if not self.configured:
            raise ProviderError("PAYMENT_NOT_CONFIGURED")
        if amount_toman <= 0 or not callback_url.startswith("https://"):
            raise ProviderError("INVALID_PAYMENT_PARAMETERS")
        result = await provider_request("POST", self.base + "/v4/payment/request.json", operation="payment-create", write=True,
            json={"merchant_id": self.merchant_id, "amount": amount_toman * 10,
                  "currency": "IRR", "description": description[:100], "callback_url": callback_url}, client=self.client)
        try:
            data = result.json()["data"]
            if data["code"] != 100:
                raise ProviderError("PAYMENT_REJECTED")
            authority = data["authority"]
            if not isinstance(authority, str) or not authority.isalnum() or len(authority) > 64:
                raise ValueError
            host = "https://sandbox.zarinpal.com" if self.sandbox else "https://www.zarinpal.com"
            return {"authority": authority, "url": host + "/pg/StartPay/" + authority}
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("INVALID_PAYMENT_RESPONSE", unknown_outcome=True) from exc

    async def verify(self, authority: str, amount_toman: int) -> dict:
        if not self.configured:
            raise ProviderError("PAYMENT_NOT_CONFIGURED")
        result = await provider_request("POST", self.base + "/v4/payment/verify.json", operation="payment-verify",
            json={"merchant_id": self.merchant_id, "amount": amount_toman * 10, "authority": authority}, client=self.client)
        try:
            data = result.json()["data"]
            if data["code"] not in {100, 101}:
                raise ProviderError("PAYMENT_NOT_SETTLED")
            if not data.get("ref_id"):
                raise ValueError
            return {"verified": True, "reference": str(data["ref_id"])}
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("INVALID_PAYMENT_VERIFICATION") from exc


def verify_webhook(body: bytes, timestamp: str, signature: str, secret: str, *, now: float | None = None) -> bool:
    """Our partner webhook scheme. Vendor callbacks use their own verification."""
    try:
        if not secret or abs((now or time.time()) - int(timestamp)) > 300:
            return False
    except (TypeError, ValueError):
        return False
    expected = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.removeprefix("sha256="))


class AuthorizedCalendarAdapter:
    """A partner contract, not a claim of Paziresh24/Doctoreto write access.

    A partner must advertise conditional_create, idempotency, and readback.
    Otherwise writes are rejected and the workflow routes to staff.
    """
    def __init__(self, base_url: str, token: str, client: httpx.AsyncClient | None = None):
        self.base_url = approved_url(base_url, "CALENDAR_PARTNER_APPROVED", allow_local=True)
        self.token, self.client = token, client

    async def capabilities(self) -> dict:
        result = await provider_request("GET", self.base_url + "/capabilities", operation="calendar-capabilities",
            headers={"Authorization": "Bearer " + self.token}, client=self.client)
        return result.json()

    async def create_verified(self, request: dict, idempotency_key: str) -> dict:
        caps = await self.capabilities()
        if not all(caps.get(key) is True for key in ("conditional_create", "idempotency", "readback")):
            raise ProviderError("CALENDAR_ATOMICITY_NOT_SUPPORTED")
        headers = {"Authorization": "Bearer " + self.token, "Idempotency-Key": idempotency_key}
        try:
            response = await provider_request("POST", self.base_url + "/appointments", operation="calendar-create", write=True,
                headers=headers, json=request, client=self.client)
            booking = response.json()
        except ProviderError as exc:
            if not exc.unknown_outcome:
                raise
            # Lookup only; never replay a potentially committed remote write.
            response = await provider_request("GET", self.base_url + "/appointments/by-idempotency-key",
                operation="calendar-reconcile", headers=headers, params={"key": idempotency_key}, client=self.client)
            booking = response.json()
        remote_id = booking.get("id", "")
        if not remote_id or not isinstance(remote_id, str) or not all(c.isalnum() or c in "-_" for c in remote_id):
            raise ProviderError("CALENDAR_UNKNOWN_OUTCOME", unknown_outcome=True)
        response = await provider_request("GET", self.base_url + "/appointments/" + remote_id,
            operation="calendar-readback", headers=headers, client=self.client)
        verified = response.json()
        if verified.get("status") != "CONFIRMED" or any(verified.get(k) != request.get(k) for k in ("slot_id", "patient_token")):
            raise ProviderError("CALENDAR_READBACK_MISMATCH", unknown_outcome=True)
        return verified
