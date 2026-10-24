"""Asterisk AudioSocket sidecar with framed PCM, pacing, cancellation and DTMF.

The socket has no native authentication: bind privately and require pre-registered
one-use call UUIDs from an authenticated PBX gateway. Never expose port 9092.
Official protocol: https://docs.asterisk.org/Configuration/Channel-Drivers/AudioSocket/
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import struct
from datetime import datetime, timezone
from uuid import UUID, uuid4

import httpx

from .audio import TurnBuffer, decode_wav
from .contracts import AudioSocketTransport
from .native_runtime import PCMTransportOutput, native_enabled, new_native_turn, routine_interruption
from ..providers import ProviderError

log = logging.getLogger("receptionist.media")
SAMPLE_RATES = {0x10: 8000, 0x11: 12000, 0x12: 16000, 0x13: 24000, 0x14: 32000,
                0x15: 44100, 0x16: 48000, 0x17: 96000, 0x18: 192000}


def encode_frame(kind: int, payload: bytes = b"") -> bytes:
    if not 0 <= kind <= 255 or len(payload) > 65535:
        raise ValueError("Frame exceeds protocol limits")
    return struct.pack("!BH", kind, len(payload)) + payload


async def read_frame(reader: asyncio.StreamReader, timeout: float = 30.0) -> tuple[int, bytes]:
    header = await asyncio.wait_for(reader.readexactly(3), timeout)
    kind, length = struct.unpack("!BH", header)
    payload = await asyncio.wait_for(reader.readexactly(length), timeout) if length else b""
    if kind == 1 and length != 16:
        raise ValueError("Invalid UUID frame")
    if kind in SAMPLE_RATES and (not length or length % 2):
        raise ValueError("PCM payload is empty or not 16-bit aligned")
    if kind == 3 and (length != 1 or payload not in [bytes([i]) for i in b"0123456789*#ABCD"]):
        raise ValueError("Invalid DTMF frame")
    if kind not in {0, 1, 3, 255, *SAMPLE_RATES}:
        raise ValueError("Unsupported frame type")
    return kind, payload


class AudioSocketBridge:
    def __init__(self, api_url: str, media_token: str):
        if not media_token:
            raise ValueError("MEDIA_API_TOKEN must be configured")
        self.api_url, self.media_token = api_url.rstrip("/"), media_token
        self.networks = [ipaddress.ip_network(x.strip()) for x in os.getenv("AUDIOSOCKET_ALLOWED_CIDRS", "127.0.0.0/8,::1/128").split(",")]
        self.active_tasks = set()
        self.active_writers = set()
        self.semaphore = asyncio.Semaphore(max(1, min(100, int(os.getenv("MAX_MEDIA_CONNECTIONS", "8")))))

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        peer = writer.get_extra_info("peername")
        address = ipaddress.ip_address(peer[0]) if peer else None
        if not address or not any(address in n for n in self.networks) or self.semaphore.locked():
            writer.close()
            await writer.wait_closed()
            return
        task = asyncio.current_task()
        self.active_tasks.add(task)
        self.active_writers.add(writer)
        try:
            async with self.semaphore:
                await self._call(reader, writer)
        finally:
            self.active_tasks.discard(task)
            self.active_writers.discard(writer)

    async def _call(self, reader, writer):
        playback = processing = native = None
        session_id = None
        headers = {}
        client = httpx.AsyncClient(timeout=35, follow_redirects=False)
        try:
            kind, payload = await read_frame(reader, 5)
            if kind != 1:
                raise ValueError("UUID must be the first packet")
            call_uuid = str(UUID(bytes=payload))
            claim = await client.post(self.api_url + "/api/v1/internal/media/claim", json={"call_uuid": call_uuid},
                headers={"Authorization": "Bearer " + self.media_token})
            claim.raise_for_status()
            data = claim.json()
            session_id = data["session_id"]
            expires = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
            if expires.tzinfo is None:
                raise ValueError("Call expiration must be timezone-aware")
            call_deadline = asyncio.get_running_loop().time() + max(0, min(1800, (expires - datetime.now(timezone.utc)).total_seconds()))
            headers = {"Authorization": "Bearer " + data["token"]}
            base = self.api_url + "/api/v1/public/sessions/" + session_id
            async def request_transfer(reason):
                response = await client.post(base + "/handoff", headers=headers, json={"reason": reason})
                return response.status_code == 200
            transport = AudioSocketTransport(writer, request_transfer)
            await transport.start(session_id)
            buffer = TurnBuffer()
            dtmf = ""
            speech_generation = 0
            pending_turn = None
            media_started = asyncio.get_running_loop().time()
            received_seconds = 0.0
            received_frames = 0

            async def native_emit(item):
                if item.get("event") == "handoff_pending":
                    await transport.hangup()

            async def fallthrough():
                try:
                    await transport.transfer("service_failure")
                except httpx.HTTPError:
                    pass
                finally:
                    writer.close()  # The configured PBX dialplan owns the staffed fallback.

            async def play(turn_id: str, generation: int):
                try:
                    audio = await client.get(base + "/speech", params={"turn_id": turn_id}, headers=headers)
                    if generation != speech_generation:
                        return
                    if audio.status_code != 200:
                        await fallthrough()
                        return
                    pcm = decode_wav(audio.content, 8000)
                except (httpx.HTTPError, ValueError):
                    await fallthrough()
                    return
                loop = asyncio.get_running_loop()
                deadline = loop.time()
                for offset in range(0, len(pcm), 320):
                    if generation != speech_generation:
                        return
                    await transport.send_audio(pcm[offset:offset+320].ljust(320, b"\0"), 8000)
                    deadline += .02
                    await asyncio.sleep(max(0, deadline - loop.time()))

            async def submit(audio: bytes | None, digits: str | None, generation: int):
                nonlocal playback, pending_turn
                while not writer.is_closing():
                    try:
                        if digits is not None:
                            response = await client.post(base + "/turn", json={"text": digits, "request_id": str(uuid4())}, headers=headers)
                        else:
                            response = await client.post(base + "/audio", content=audio,
                                headers={**headers, "Content-Type": "audio/wav", "X-Request-ID": str(uuid4())})
                        if response.status_code == 200:
                            result = response.json()
                            if result.get("turn_id") and generation == speech_generation:
                                playback = asyncio.create_task(play(result["turn_id"], generation))
                            if result.get("state") in {"HANDOFF_PENDING", "HUMAN_CONNECTED"}:
                                if playback:
                                    await asyncio.gather(playback, return_exceptions=True)
                                await transport.hangup()  # PBX fallthrough executes its approved staffed route.
                                return
                        else:
                            # Never retry an uncertain mutation with a new request identifier.
                            await client.post(base + "/handoff", headers=headers, json={"reason": "service_failure"})
                            writer.write(encode_frame(0))
                            await writer.drain()
                            writer.close()
                            return
                    except (httpx.HTTPError, ConnectionError, ValueError):
                        writer.close()
                        return
                    pending, pending_turn = pending_turn, None
                    if pending is None:
                        return
                    audio, digits, generation = pending

            def enqueue(audio: bytes | None = None, digits: str | None = None):
                nonlocal processing, pending_turn
                item = (audio, digits, speech_generation)
                if processing and not processing.done():
                    pending_turn = item  # bounded, and its playback generation is retained
                else:
                    processing = asyncio.create_task(submit(*item))

            async def run_native(turn):
                nonlocal processing, pending_turn
                try:
                    await turn.wait()
                except ProviderError as error:
                    if not routine_interruption(error):
                        await fallthrough()
                except (httpx.HTTPError, ValueError, ConnectionError, TimeoutError):
                    await fallthrough()
                finally:
                    pending, pending_turn = pending_turn, None
                    if pending and not writer.is_closing():
                        await submit(*pending)

            playback = asyncio.create_task(play("greeting", speech_generation))
            while not writer.is_closing():
                remaining = call_deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    break
                async with asyncio.timeout(min(30, remaining)):
                    kind, payload = await read_frame(reader, 30)
                received_frames += 1
                elapsed = asyncio.get_running_loop().time() - media_started
                if received_frames > elapsed * 100 + 200:
                    raise ValueError("Media frame rate exceeds the bounded transport allowance")
                if kind in {0, 255}:
                    break
                if kind == 1:
                    raise ValueError("UUID cannot change during a call")
                if kind == 3:
                    digit = payload.decode("ascii")
                    if not dtmf and digit not in {"#", "*"}:
                        speech_generation += 1
                        transport.interrupt()
                        if playback:
                            playback.cancel()
                    if digit == "#" and dtmf == "0":
                        speech_generation += 1
                        transport.interrupt()
                        if playback:
                            playback.cancel()
                        await transport.transfer("human_requested")
                        break
                    if digit == "#":
                        if dtmf:
                            enqueue(digits=dtmf)
                        dtmf = ""
                    elif digit == "*":
                        dtmf = ""
                    elif len(dtmf) < 20:
                        dtmf += digit
                    continue
                if kind in SAMPLE_RATES:
                    received_seconds += len(payload) / (SAMPLE_RATES[kind] * 2)
                    if received_seconds > elapsed + 5:
                        raise ValueError("Media arrived faster than the permitted jitter buffer")
                    if buffer.sample_rate != SAMPLE_RATES[kind]:
                        if buffer.speaking:
                            raise ValueError("Sample rate changed during a turn")
                        buffer = TurnBuffer(sample_rate=SAMPLE_RATES[kind])
                    was_speaking = buffer.speaking
                    turn_audio, began = buffer.push(payload)
                    if began:
                        speech_generation += 1
                        transport.interrupt()
                        if playback:
                            playback.cancel()
                        if (native_enabled() and SAMPLE_RATES[kind] <= 48000 and not turn_audio
                            and (processing is None or processing.done())):
                            sink = PCMTransportOutput(transport.send_audio)
                            async def send_pcm(pcm, rate):
                                await sink.feed(pcm)
                            async def emit_with_flush(item):
                                if item.get("event") == "end":
                                    await sink.finish()
                                await native_emit(item)
                            try:
                                native = new_native_turn(client, api_url=self.api_url,
                                    session_id=session_id, token=data["token"],
                                    emit_event=emit_with_flush, send_audio=send_pcm,
                                    source_rate=SAMPLE_RATES[kind], generation=speech_generation,
                                    generation_current=lambda: speech_generation,
                                    request_id=str(uuid4()))
                                native.start(bytes(buffer._frames))
                                processing = asyncio.create_task(run_native(native))
                            except (ProviderError, ValueError):
                                await fallthrough()
                                break
                    elif was_speaking and native:
                        try:
                            native.feed(payload)
                        except ProviderError:
                            await fallthrough()
                            break
                    if turn_audio:
                        if native:
                            native.finish()
                            native = None
                        else:
                            enqueue(audio=turn_audio)
        except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionError, ValueError, httpx.HTTPError):
            log.info("media_session_closed", extra={"call_id": session_id})
        finally:
            writer.close()
            if native:
                await native.close()
            if playback:
                playback.cancel()
                await asyncio.gather(playback, return_exceptions=True)
            # Let a committed tool settle before ending the logical call.
            if processing:
                try:
                    await asyncio.wait_for(asyncio.shield(processing), timeout=35)
                except (Exception, asyncio.CancelledError):
                    processing.cancel()
                    await asyncio.gather(processing, return_exceptions=True)
            if session_id:
                try:
                    await client.post(self.api_url + "/api/v1/public/sessions/" + session_id + "/end", headers=headers)
                except httpx.HTTPError:
                    pass  # expiry sweeper accounts for orphaned sessions
            await client.aclose()
            writer.close()
            await writer.wait_closed()


async def main(stop=None):
    from ..core_runtime import shutdown_event, drain_tasks
    stop = stop or shutdown_event()
    bridge = AudioSocketBridge(os.getenv("RECEPTION_API_URL", "http://127.0.0.1:8000"), os.getenv("MEDIA_API_TOKEN", ""))
    server = await asyncio.start_server(bridge.handle, os.getenv("AUDIOSOCKET_BIND", "127.0.0.1"), int(os.getenv("AUDIOSOCKET_PORT", "9092")), limit=131072)
    async with server:
        try:
            await stop.wait()
        finally:
            server.close()
            await server.wait_closed()
            for writer in list(bridge.active_writers):
                writer.close()
            await drain_tasks(bridge.active_tasks)


if __name__ == "__main__":
    asyncio.run(main())
