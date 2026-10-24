"""Opt-in native speech/model streaming boundaries.

Only complete, validated, explicitly authorized business tools may be offered to
application logic. Partial recognition and generated JSON fragments are never
commit authority. Client and supplier transport require separate approval.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterable
from urllib.parse import urlencode

import httpx
from websockets.exceptions import WebSocketException

from ..providers import ProviderError, approved_url, enabled
from ..tool_contract import validate_model_tool_event


STREAM_AUDIO_LIMIT = 1_920_000  # 60 seconds * 16000 Hz * signed 16-bit mono
STREAM_TTS_LIMIT = 3_840_000  # 120 seconds * 16000 Hz * signed 16-bit mono


def require_stream_approval():
    if not enabled("SPEECH_STREAMING_APPROVED"):
        raise ProviderError("STREAMING_NOT_APPROVED")


class DeepgramRealtimeSTT:
    """Nova streaming input, with final utterances distinct from interim text.

    Frames are already PCM16 mono at 16 kHz. The caller owns VAD and turn
    cancellation. A finalized segment is not necessarily an ended utterance.
    """

    def __init__(self, api_key: str, *, connect=None, timeout: float = 30):
        self.api_key, self.connect, self.timeout = api_key, connect, timeout

    async def events(self, frames: AsyncIterable[bytes], *, keyterms=None):
        require_stream_approval()
        approved_url("https://api.deepgram.com", "SPEECH_PROCESSOR_APPROVED")
        if not self.api_key or len(self.api_key) > 512:
            raise ProviderError("STT_TOKEN_REQUIRED")
        terms = list(keyterms or [])
        if len(terms) > 30 or any(not isinstance(term, str) or not 1 <= len(term) <= 100 for term in terms):
            raise ProviderError("INVALID_STT_KEYTERMS")
        try:
            approved_terms = json.loads(os.getenv("STT_APPROVED_KEYTERMS_JSON", "[]"))
        except ValueError as exc:
            raise ProviderError("STT_KEYTERM_CONFIG_INVALID") from exc
        if not isinstance(approved_terms, list) or any(not isinstance(term, str) for term in approved_terms):
            raise ProviderError("STT_KEYTERM_CONFIG_INVALID")
        persian_digits = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
        if any(term not in approved_terms or re.search(r"[0-9]{7,}", term.translate(persian_digits)) for term in terms):
            raise ProviderError("STT_KEYTERM_NOT_APPROVED")
        params = {
            "model": "nova-3", "language": "fa", "encoding": "linear16", "sample_rate": "16000",
            "channels": "1", "interim_results": "true", "endpointing": "350", "punctuate": "true",
        }
        if terms:
            # Nova-3 supported keyterm syntax; no caller-controlled URL or host.
            params["keyterm"] = terms
        import websockets
        connector = self.connect or websockets.connect
        from urllib.parse import quote
        parameters = urlencode(params, doseq=True, quote_via=quote)
        url = "wss://api.deepgram.com/v1/listen?" + parameters
        ws = await connector(url, additional_headers={"Authorization": "Token " + self.api_key},
                             open_timeout=min(self.timeout, 10), close_timeout=3, max_size=65536)
        sent = 0
        fragments: list[str] = []
        finalized = False
        task = None

        async def produce():
            nonlocal sent
            async for frame in frames:
                if not isinstance(frame, bytes) or len(frame) == 0 or len(frame) % 2 or len(frame) > 32000:
                    raise ProviderError("INVALID_STREAM_AUDIO")
                sent += len(frame)
                if sent > STREAM_AUDIO_LIMIT:
                    raise ProviderError("AUDIO_DURATION_LIMIT")
                await ws.send(frame)
            await ws.send(json.dumps({"type": "Finalize"}))

        try:
            task = asyncio.create_task(produce())
            async with asyncio.timeout(self.timeout):
                async for raw in ws:
                    if task.done():
                        await task  # Propagate oversized PCM, failed send, etc.
                    if not isinstance(raw, str) or len(raw) > 65536:
                        raise ProviderError("STT_INVALID_EVENT")
                    try:
                        message = json.loads(raw)
                    except (TypeError, ValueError) as exc:
                        raise ProviderError("STT_INVALID_EVENT") from exc
                    if not isinstance(message, dict):
                        raise ProviderError("STT_INVALID_EVENT")
                    kind = message.get("type")
                    if kind == "Error":
                        raise ProviderError("STT_PROVIDER_REJECTED")
                    if kind == "UtteranceEnd" and fragments:
                        finalized = True
                        yield {"event": "final", "text": " ".join(fragments), "final": True,
                               "audio_seconds": sent / 32000, "provider": "deepgram_nova3"}
                        return
                    if kind != "Results":
                        continue
                    channel = message.get("channel")
                    if not isinstance(channel, dict) or not isinstance(channel.get("alternatives"), list):
                        raise ProviderError("STT_INVALID_EVENT")
                    alternatives = channel["alternatives"]
                    text = alternatives[0].get("transcript", "") if alternatives and isinstance(alternatives[0], dict) else ""
                    if not isinstance(text, str) or len(text) > 2000:
                        raise ProviderError("STT_INVALID_EVENT")
                    text = text.strip()
                    if message.get("is_final") is True:
                        if text:
                            fragments.append(text)
                        if sum(len(part) for part in fragments) > 2000:
                            raise ProviderError("STT_TEXT_LIMIT")
                        if message.get("speech_final") is True and fragments:
                            finalized = True
                            yield {"event": "final", "text": " ".join(fragments), "final": True,
                                   "audio_seconds": sent / 32000, "provider": "deepgram_nova3"}
                            return
                    elif text:
                        yield {"event": "partial", "text": " ".join([*fragments, text]),
                               "final": False, "provider": "deepgram_nova3"}
                if task:
                    await task
            if not finalized:
                raise ProviderError("STT_STREAM_INCOMPLETE")
        except TimeoutError as exc:
            raise ProviderError("STT_STREAM_TIMEOUT", retryable=False) from exc
        except ProviderError:
            raise
        except (OSError, ConnectionError, WebSocketException) as exc:
            raise ProviderError("STT_STREAM_UNAVAILABLE") from exc
        finally:
            if task and not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            await ws.close()


class GatewayPCMStream:
    """Native chunked PCM contract for an explicitly approved speech gateway.

    Unlike synthesize_chunks(), it never fetches a complete WAV before yielding
    first audio. The local Piper speech service implements framed signed
    linear16/16-kHz/mono packets and an explicit terminal byte-count marker;
    arbitrary HTTP body completion is never accepted as valid audio.
    """

    def __init__(self, base: str, token: str, client: httpx.AsyncClient | None = None):
        self.base, self.token, self.client = base, token, client

    async def events(self, text: str, *, slow: bool = False):
        require_stream_approval()
        base = approved_url(self.base, "SPEECH_PROCESSOR_APPROVED", allow_local=True)
        if not self.token or not isinstance(text, str) or not 1 <= len(text) <= 2000:
            raise ProviderError("INVALID_TTS_STREAM_INPUT")
        owned = self.client is None
        client = self.client or httpx.AsyncClient(timeout=httpx.Timeout(35, connect=4), follow_redirects=False)
        buffer = bytearray()
        total, sequence = 0, 0
        try:
            async with client.stream("POST", base + "/synthesize/stream",
                json={"text": text, "language": "fa", "slow": slow, "sample_rate": 16000,
                      "format": "pcm_s16le"}, headers={"Authorization": "Bearer " + self.token}) as response:
                if response.status_code != 200:
                    raise ProviderError("TTS_STREAM_REJECTED")
                if (response.headers.get("content-type", "").split(";")[0] not in {"application/octet-stream", "application/x-hamava-pcm-frames"}
                    or response.headers.get("x-audio-format") != "pcm_s16le"
                    or response.headers.get("x-audio-sample-rate") != "16000"
                    or response.headers.get("x-audio-channels") != "1"):
                    raise ProviderError("TTS_STREAM_FORMAT_MISMATCH")
                try:
                    declared_total = int(response.headers.get("x-audio-total-bytes", "0"))
                except ValueError as exc:
                    raise ProviderError("TTS_STREAM_FORMAT_MISMATCH") from exc
                if declared_total < 0 or declared_total > STREAM_TTS_LIMIT or declared_total % 2:
                    raise ProviderError("TTS_STREAM_FORMAT_MISMATCH")
                framed = response.headers.get("content-type", "").split(";")[0] == "application/x-hamava-pcm-frames"
                if framed:
                    # Every stream must carry an explicit terminal frame; an
                    # HTTP 200 followed by a dropped connection is NOT success.
                    import struct
                    ended = False
                    async for chunk in response.aiter_bytes():
                        if len(chunk) > 65536:
                            raise ProviderError("TTS_STREAM_TOO_LONG")
                        if ended:
                            if chunk:
                                raise ProviderError("TTS_STREAM_TRUNCATED")
                            continue
                        buffer.extend(chunk)
                        while len(buffer) >= 3:
                            kind, size = struct.unpack("!BH", buffer[:3])
                            if kind not in (0, 0x10) or (kind == 0x10 and size != 640) or (kind == 0 and size != 8):
                                raise ProviderError("TTS_STREAM_FORMAT_MISMATCH")
                            if len(buffer) < 3 + size:
                                break
                            packet = bytes(buffer[3:3 + size])
                            del buffer[:3 + size]
                            if kind == 0:
                                if int.from_bytes(packet, "big") != total or not total or buffer:
                                    raise ProviderError("TTS_STREAM_TRUNCATED")
                                ended = True
                                break
                            total += len(packet)
                            if total > STREAM_TTS_LIMIT:
                                raise ProviderError("TTS_STREAM_TOO_LONG")
                            yield {"event": "audio", "sequence": sequence, "pcm16": packet, "sample_rate": 16000,
                                   "channels": 1, "buffered": False}
                            sequence += 1
                    if not ended or buffer:
                        raise ProviderError("TTS_STREAM_TRUNCATED")
                else:
                    # Legacy raw contract is accepted only when the exact final
                    # byte count is declared, preventing undetected truncation.
                    if declared_total <= 0:
                        raise ProviderError("TTS_STREAM_FORMAT_MISMATCH")
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > STREAM_TTS_LIMIT:
                            raise ProviderError("TTS_STREAM_TOO_LONG")
                        buffer.extend(chunk)
                        while len(buffer) >= 640:
                            pcm = bytes(buffer[:640])
                            del buffer[:640]
                            yield {"event": "audio", "sequence": sequence, "pcm16": pcm, "sample_rate": 16000,
                                   "channels": 1, "buffered": False}
                            sequence += 1
                    if buffer or total != declared_total or not total:
                        raise ProviderError("TTS_STREAM_TRUNCATED")
            yield {"event": "end", "sequence": sequence, "buffered": False, "audio_seconds": total / 32000}
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
            raise ProviderError("TTS_STREAM_UNAVAILABLE") from exc
        finally:
            if owned:
                await client.aclose()


class ResponsesToolStream:
    """Validate OpenAI Responses semantic events without executing model output.

    The stream may finish partially on cancellation. A `done` arguments event
    alone is NEVER dispatch authority; only a completed response makes a
    schema-validated proposal visible to a separate, caller-authorized gateway.
    """

    async def parse(self, events: AsyncIterable[dict], *, request_id: str):
        if not re.fullmatch(r"[a-zA-Z0-9_-]{8,100}", request_id):
            raise ProviderError("INVALID_MODEL_REQUEST_ID")
        calls = {}
        processed = 0
        async for value in events:
            processed += 1
            if processed > 512 or not isinstance(value, dict):
                raise ProviderError("MODEL_STREAM_TOO_LONG")
            kind = value.get("type")
            if kind == "response.output_item.added":
                item = value.get("item", {})
                if item.get("type") == "function_call":
                    if len(calls) >= 8 or not isinstance(item.get("id"), str):
                        raise ProviderError("MODEL_TOOL_REJECTED")
                    calls[item["id"]] = {"name": item.get("name"), "arguments": None, "delta": ""}
            elif kind == "response.function_call_arguments.delta":
                call = calls.get(value.get("item_id"))
                if call is None or not isinstance(value.get("delta"), str):
                    raise ProviderError("MODEL_TOOL_REJECTED")
                call["delta"] += value["delta"]
                if len(call["delta"]) > 8192:
                    raise ProviderError("MODEL_TOOL_REJECTED")
            elif kind == "response.function_call_arguments.done":
                call = calls.get(value.get("item_id"))
                complete = value.get("arguments")
                if call is None or not isinstance(complete, str) or len(complete) > 8192 or (call["delta"] and not complete.startswith(call["delta"])):
                    raise ProviderError("MODEL_TOOL_REJECTED")
                call["arguments"] = complete
            elif kind in {"response.failed", "response.incomplete", "error"}:
                raise ProviderError("MODEL_STREAM_INCOMPLETE")
            elif kind == "response.completed":
                if value.get("response", {}).get("status") != "completed":
                    raise ProviderError("MODEL_STREAM_INCOMPLETE")
                proposals = []
                for identifier, call in calls.items():
                    if call["arguments"] is None:
                        raise ProviderError("MODEL_TOOL_INCOMPLETE")
                    try:
                        arguments = json.loads(call["arguments"])
                        validated = validate_model_tool_event({"event": "tool_call", "request_id": request_id,
                            "tool": call["name"], "arguments": arguments})
                    except Exception as exc:
                        # Never expose model text or fields in the error, nor execute them.
                        raise ProviderError("MODEL_TOOL_REJECTED") from exc
                    proposals.append({"event": "tool_proposal", "request_id": request_id,
                                      "tool": validated.tool, "arguments": validated.arguments,
                                      "item_id": identifier, "executable": False})
                for proposal in proposals:
                    yield proposal
                yield {"event": "completed", "proposals": len(proposals)}
                return
            elif kind == "response.output_text.delta":
                # Partial prose is not a verified clinic fact and not a caller reply.
                continue
        raise ProviderError("MODEL_STREAM_INCOMPLETE")

    async def request(self, *, prompt: str, model: str, tools: list[dict], client: httpx.AsyncClient | None = None,
                      request_id: str):
        if not enabled("MODEL_STREAMING_APPROVED"):
            raise ProviderError("MODEL_STREAMING_NOT_APPROVED")
        base = approved_url(os.getenv("MODEL_RESPONSES_BASE", ""), "MODEL_PROCESSOR_APPROVED")
        token = os.getenv("MODEL_STREAM_TOKEN", "")
        if not token or not 1 <= len(prompt) <= 4000 or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", model):
            raise ProviderError("MODEL_STREAM_CONFIG_INVALID")
        from ..tool_contract import TOOL_NAMES
        if len(tools) > 5 or any(not isinstance(tool, dict) or tool.get("type") != "function"
                                 or tool.get("name") not in TOOL_NAMES or tool.get("strict") is not True for tool in tools):
            raise ProviderError("MODEL_TOOL_REJECTED")
        owned = client is None
        session = client or httpx.AsyncClient(timeout=httpx.Timeout(30, connect=4), follow_redirects=False)
        async def semantic_events():
            size = 0
            async with session.stream("POST", base + "/responses", headers={"Authorization": "Bearer " + token},
                                      json={"model": model, "input": prompt, "tools": tools,
                                            "stream": True, "max_output_tokens": 500}) as response:
                if response.status_code != 200:
                    raise ProviderError("MODEL_STREAM_REJECTED")
                async for line in response.aiter_lines():
                    size += len(line)
                    if size > 131072:
                        raise ProviderError("MODEL_STREAM_TOO_LONG")
                    if line.startswith("data: "):
                        data = line[6:]
                        if data == "[DONE]":
                            continue
                        try:
                            yield json.loads(data)
                        except (ValueError, TypeError) as exc:
                            raise ProviderError("MODEL_STREAM_INVALID_EVENT") from exc
        try:
            async for item in self.parse(semantic_events(), request_id=request_id):
                yield item
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ProtocolError) as exc:
            raise ProviderError("MODEL_STREAM_UNAVAILABLE") from exc
        finally:
            if owned:
                await session.aclose()
