"""Opt-in streaming-turn composition over the existing authoritative API.

This module is a worker-side integration seam, not a replacement calendar or
independent caller session authority. It never sends partial STT or a model's
unvalidated arguments to booking code. A real worker must fence playback and
provider usage independently and must be enabled only after clinic UAT.
"""
from __future__ import annotations

import os
import re
from collections.abc import AsyncIterable, Callable
from urllib.parse import urlparse

import httpx

from ..providers import ProviderError, enabled


class NativeTurnCoordinator:
    """Route final streaming STT through the durable /turn endpoint, then stream TTS.

    Client handles authorization, tenant, idempotency, policy and booking truth.
    Caller audio never goes to the generative tool stream through this class.
    """

    def __init__(self, client: httpx.AsyncClient, *, base_url: str, session_id: str,
                 token: str, stt, tts, generation_changed: Callable[[], bool] | None = None):
        parsed = urlparse(base_url)
        safe_local = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
        if ((parsed.scheme != "https" and not safe_local) or not parsed.hostname
                or parsed.query or parsed.fragment or parsed.username or parsed.password or parsed.path not in {"", "/"}):
            raise ProviderError("INVALID_TURN_SERVICE_URL")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,60}", session_id) or not token or len(token) > 4096:
            raise ProviderError("INVALID_CALL_SESSION")
        self.client, self.base, self.session_id = client, base_url.rstrip("/"), session_id
        self.token, self.stt, self.tts = token, stt, tts
        self.generation_changed = generation_changed or (lambda: False)

    async def run(self, frames: AsyncIterable[bytes], *, request_id: str, keyterms: list[str] | None = None):
        if not enabled("SPEECH_STREAMING_APPROVED") or not enabled("NATIVE_STREAMING_CALLS_APPROVED"):
            raise ProviderError("NATIVE_TURN_NOT_APPROVED")
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,100}", request_id):
            raise ProviderError("INVALID_TURN_REQUEST_ID")
        text = None
        async for item in self.stt.events(frames, keyterms=keyterms):
            if self.generation_changed():
                raise ProviderError("TURN_INTERRUPTED")
            if item.get("event") == "partial":
                value = item.get("text")
                if isinstance(value, str) and len(value) <= 2000:
                    yield {"event": "partial", "text": value}
            elif item.get("event") == "final" and item.get("final") is True:
                value = item.get("text")
                if not isinstance(value, str) or not 1 <= len(value.strip()) <= 2000:
                    raise ProviderError("INVALID_FINAL_TRANSCRIPT")
                text = value.strip()
                break
            else:
                raise ProviderError("UNEXPECTED_STT_EVENT")
        if not text:
            raise ProviderError("STT_STREAM_INCOMPLETE")
        if self.generation_changed():
            raise ProviderError("TURN_INTERRUPTED")
        # No automatic retry after a possibly committed /turn request. The
        # request_id must be preserved for explicit authoritative reconciliation.
        try:
            response = await self.client.post(self.base + "/api/v1/public/sessions/" + self.session_id + "/turn",
                headers={"Authorization": "Bearer " + self.token},
                json={"text": text, "request_id": request_id}, timeout=30)
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
            raise ProviderError("TURN_OUTCOME_UNKNOWN", unknown_outcome=True) from exc
        if response.status_code != 200:
            # 409 can indicate a lease loss, stale authority or already joined
            # human. The transport must reconcile rather than assume no write.
            raise ProviderError("TURN_RECONCILIATION_REQUIRED", unknown_outcome=True)
        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderError("TURN_RESPONSE_UNTRUSTED", unknown_outcome=True) from exc
        if not isinstance(data, dict) or not isinstance(data.get("turn_id"), str) or not data.get("turn_id"):
            raise ProviderError("TURN_RESPONSE_UNTRUSTED", unknown_outcome=True)
        state = data.get("state")
        if state == "HUMAN_CONNECTED":
            yield {"event": "human_connected"}
            return
        if state in {"HANDOFF_PENDING", "SERVICE_UNAVAILABLE"}:
            yield {"event": "handoff_pending", "state": state}
            return
        if self.generation_changed():
            # The server may already have committed. Never undo or replay the
            # operation, and do not play stale confirmations.
            yield {"event": "interrupted_after_turn", "reconcile_request_id": request_id}
            return
        yield {"event": "confirmed_turn", "turn_id": data["turn_id"], "state": state}
        reply = data.get("reply")
        if not isinstance(reply, str) or not 1 <= len(reply) <= 2000:
            raise ProviderError("TURN_RESPONSE_UNTRUSTED", unknown_outcome=True)
        ended = False
        async for sound in self.tts.events(reply):
            if self.generation_changed():
                yield {"event": "interrupted_after_turn", "reconcile_request_id": request_id}
                return
            if ended:
                raise ProviderError("UNEXPECTED_TTS_EVENT")
            if sound.get("event") == "audio":
                pcm = sound.get("pcm16")
                if (not isinstance(pcm, bytes) or not 0 < len(pcm) <= 640
                        or len(pcm) % 2 or sound.get("sample_rate") != 16000):
                    raise ProviderError("INVALID_STREAM_AUDIO")
                yield {"event": "audio", "pcm16": pcm, "sample_rate": 16000}
            elif sound.get("event") == "end":
                ended = True
                yield {"event": "end"}
            else:
                raise ProviderError("UNEXPECTED_TTS_EVENT")
        if not ended:
            raise ProviderError("TTS_STREAM_INCOMPLETE")
