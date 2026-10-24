"""Bounded streaming PCM producer and generation-fenced receptionist playback.

The network/media loop never waits on recognition or synthesis. A slow vendor
causes an explicit backpressure failure, not dropped phonemes or a phantom
booking. Business writes remain exclusively behind the authenticated /turn API.
"""
from __future__ import annotations

import asyncio
import audioop
from collections.abc import Awaitable, Callable

from ..providers import ProviderError


class PCMIngress:
    """Bounded 16-kHz mono PCM16 frames, resampled with continuous filter state."""

    def __init__(self, *, max_queue_frames: int = 100, max_seconds: int = 20):
        if not 1 <= max_queue_frames <= 200 or not 1 <= max_seconds <= 60:
            raise ValueError("INVALID_STREAM_LIMIT")
        self.queue: asyncio.Queue[bytes | None] = asyncio.Queue(max_queue_frames + 1)
        self.max_queue_frames = max_queue_frames
        self.max_bytes = max_seconds * 32000
        self.audio_bytes = 0
        self._pending = bytearray()
        self._rate = None
        self._resample_state = None
        self.closed = False
        self.error: ProviderError | None = None

    def _abort(self, code: str):
        self.error = ProviderError(code)
        self.finish()
        raise self.error

    def feed(self, pcm: bytes, sample_rate: int):
        if self.closed:
            raise ProviderError("STREAM_ALREADY_ENDED")
        if not isinstance(pcm, bytes) or not pcm or len(pcm) % 2 or len(pcm) > 38400 or sample_rate not in {8000, 12000, 16000, 24000, 32000, 44100, 48000}:
            self._abort("INVALID_STREAM_AUDIO")
        if self._rate not in {None, sample_rate}:
            self._abort("STREAM_SAMPLE_RATE_CHANGED")
        self._rate = sample_rate
        if sample_rate != 16000:
            pcm, self._resample_state = audioop.ratecv(pcm, 2, 1, sample_rate, 16000, self._resample_state)
        if self.audio_bytes + len(pcm) > self.max_bytes:
            self._abort("STREAM_AUDIO_DURATION_LIMIT")
        self.audio_bytes += len(pcm)
        self._pending.extend(pcm)
        while len(self._pending) >= 640:
            if self.queue.qsize() >= self.max_queue_frames:
                self._abort("STREAM_BACKPRESSURE")
            self.queue.put_nowait(bytes(self._pending[:640]))
            del self._pending[:640]

    def finish(self):
        if self.closed:
            return
        self.closed = True
        if self._pending and self.error is None:
            if self.queue.qsize() >= self.max_queue_frames:
                self.error = ProviderError("STREAM_BACKPRESSURE")
            else:
                # Final PCM packet must be a full 20ms transport frame.
                self.queue.put_nowait(bytes(self._pending).ljust(640, b"\0"))
        self._pending.clear()
        self.queue.put_nowait(None)  # A reserved slot prevents blocked consumers.

    async def frames(self):
        while True:
            frame = await self.queue.get()
            if frame is None:
                if self.error is not None:
                    raise self.error
                return
            yield frame


class NativeMediaTurn:
    """Plays only the currently authorized generation of a native speech turn.

    The coordinating API owns slot mutation and idempotency. The caller handles
    ProviderError by requesting the preapproved staffed fallback, never by
    retrying /turn with a new idempotency identifier.
    """

    def __init__(self, coordinator, *, emit_event: Callable[[dict], Awaitable[None]],
                 send_audio: Callable[[bytes, int], Awaitable[None]], sample_rate: int,
                 generation: int, generation_current: Callable[[], int], request_id: str):
        if sample_rate not in {8000, 12000, 16000, 24000, 32000, 44100, 48000}:
            raise ValueError("INVALID_STREAM_RATE")
        self.coordinator = coordinator
        self.emit_event, self.send_audio = emit_event, send_audio
        self.source_rate = sample_rate
        self.generation, self.generation_current = generation, generation_current
        self.request_id = request_id
        self.ingress = PCMIngress()
        self.task: asyncio.Task | None = None

    def start(self, preroll: bytes):
        if self.task is not None:
            raise RuntimeError("NATIVE_TURN_ALREADY_STARTED")
        self.ingress.feed(preroll, self.source_rate)
        self.task = asyncio.create_task(self._drive())

    def feed(self, frame: bytes):
        if self.task is None:
            raise RuntimeError("NATIVE_TURN_NOT_STARTED")
        self.ingress.feed(frame, self.source_rate)

    def finish(self):
        self.ingress.finish()

    def stale(self) -> bool:
        return self.generation_current() != self.generation

    async def _drive(self):
        deadline = asyncio.get_running_loop().time()
        async for item in self.coordinator.run(self.ingress.frames(), request_id=self.request_id):
            event = item.get("event")
            if event == "partial":
                if not self.stale():
                    await self.emit_event(item)
            elif event == "audio":
                if self.stale():
                    continue
                await self.send_audio(item["pcm16"], 16000)
                deadline += len(item["pcm16"]) / 32000
                await asyncio.sleep(max(0, deadline - asyncio.get_running_loop().time()))
            elif event in {"confirmed_turn", "end", "human_connected", "handoff_pending", "interrupted_after_turn"}:
                if not self.stale() or event == "interrupted_after_turn":
                    await self.emit_event(item)
            else:
                raise ProviderError("UNEXPECTED_NATIVE_EVENT")

    async def wait(self):
        if self.task is None:
            raise RuntimeError("NATIVE_TURN_NOT_STARTED")
        return await self.task

    async def close(self):
        self.finish()
        if self.task and not self.task.done():
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class PCMTransportOutput:
    """Incremental 16-kHz to 8-kHz mono output without resetting filter state."""
    def __init__(self, send_audio: Callable[[bytes, int], Awaitable[None]]):
        self.send_audio = send_audio
        self.pending = bytearray()
        self.state = None
        self.closed = False

    async def feed(self, pcm: bytes):
        if self.closed or not isinstance(pcm, bytes) or not pcm or len(pcm) > 640 or len(pcm) % 2:
            raise ProviderError("INVALID_TTS_TRANSPORT_FRAME")
        reduced, self.state = audioop.ratecv(pcm, 2, 1, 16000, 8000, self.state)
        self.pending.extend(reduced)
        while len(self.pending) >= 320:
            packet = bytes(self.pending[:320])
            del self.pending[:320]
            await self.send_audio(packet, 8000)

    async def finish(self):
        if self.closed:
            return
        self.closed = True
        if self.pending:
            await self.send_audio(bytes(self.pending).ljust(320, b"\0"), 8000)
            self.pending.clear()


def native_enabled() -> bool:
    """Approval is explicit and both provider credentials must be provisioned."""
    import os
    from ..providers import enabled
    return (enabled("NATIVE_STREAMING_CALLS_APPROVED") and enabled("SPEECH_STREAMING_APPROVED")
            and bool(os.getenv("DEEPGRAM_STREAM_TOKEN")) and bool(os.getenv("SPEECH_GATEWAY_TOKEN")))


def new_native_turn(client, *, api_url: str, session_id: str, token: str,
                    emit_event, send_audio, source_rate: int, generation: int,
                    generation_current, request_id: str):
    """Build one approved speech turn; never infer permissions from a token alone."""
    import os
    from .streaming import DeepgramRealtimeSTT, GatewayPCMStream
    from .turn_stream import NativeTurnCoordinator
    if not native_enabled():
        raise ProviderError("NATIVE_STREAMING_NOT_APPROVED")
    stt = DeepgramRealtimeSTT(os.environ["DEEPGRAM_STREAM_TOKEN"])
    tts = GatewayPCMStream(os.getenv("SPEECH_GATEWAY_URL", ""), os.environ["SPEECH_GATEWAY_TOKEN"])
    coordinator = NativeTurnCoordinator(client, base_url=api_url, session_id=session_id,
        token=token, stt=stt, tts=tts, generation_changed=lambda: generation_current() != generation)
    return NativeMediaTurn(coordinator, emit_event=emit_event, send_audio=send_audio,
        sample_rate=source_rate, generation=generation, generation_current=generation_current,
        request_id=request_id)


def routine_interruption(error: Exception) -> bool:
    """Barge-in before a business request is not a provider outage."""
    return isinstance(error, ProviderError) and error.code == "TURN_INTERRUPTED" and not error.unknown_outcome
