"""Common transport control surface used by AudioSocket and WebRTC workers."""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MediaCapabilities:
    pcm_rates: tuple[int, ...]
    interrupt: bool
    transfer_mode: str
    human_join_observable: bool


@dataclass(frozen=True)
class TransferResult:
    requested: bool
    connected: bool
    mode: str


class MediaTransport(Protocol):
    capabilities: MediaCapabilities
    async def start(self, session_id: str) -> None: ...
    async def send_audio(self, pcm16: bytes, sample_rate: int) -> None: ...
    def interrupt(self) -> int: ...
    async def transfer(self, reason: str) -> TransferResult: ...
    async def hangup(self) -> None: ...


class AudioSocketTransport:
    capabilities = MediaCapabilities((8000,), True, "approved_pbx_fallthrough", False)

    def __init__(self, writer, request_handoff):
        self.writer, self.request_handoff = writer, request_handoff
        self.session_id, self.generation = None, 0
        self.closed = False

    async def start(self, session_id):
        if self.session_id is not None or not session_id:
            raise ValueError("Transport may start once after authentication")
        self.session_id = session_id

    async def send_audio(self, pcm16, sample_rate):
        if not self.session_id or self.closed or sample_rate != 8000 or not pcm16 or len(pcm16) % 2 or len(pcm16) > 320:
            raise ValueError("Invalid bounded AudioSocket PCM frame")
        from .audiosocket import encode_frame
        self.writer.write(encode_frame(0x10, pcm16))
        await self.writer.drain()

    def interrupt(self):
        self.generation += 1
        return self.generation

    async def transfer(self, reason):
        self.interrupt()
        requested = await self.request_handoff(reason)
        await self.hangup()
        return TransferResult(bool(requested), False, self.capabilities.transfer_mode)

    async def hangup(self):
        if self.closed:
            return
        self.closed = True
        from .audiosocket import encode_frame
        if not self.writer.is_closing():
            self.writer.write(encode_frame(0))
            await self.writer.drain()
            self.writer.close()


class LiveKitTransport:
    capabilities = MediaCapabilities((16000,), True, "signed_staff_room_join", True)

    def __init__(self, source, room, request_handoff):
        self.source, self.room, self.request_handoff = source, room, request_handoff
        self.session_id, self.generation = None, 0
        self.closed = False

    async def start(self, session_id):
        if self.session_id is not None or not session_id:
            raise ValueError("Transport may start once after authenticated room join")
        self.session_id = session_id

    async def send_audio(self, pcm16, sample_rate):
        if not self.session_id or self.closed or sample_rate != 16000 or not pcm16 or len(pcm16) % 2 or len(pcm16) > 640:
            raise ValueError("Invalid bounded LiveKit PCM frame")
        from livekit import rtc
        await self.source.capture_frame(rtc.AudioFrame(pcm16, 16000, 1, len(pcm16)//2))

    def interrupt(self):
        self.generation += 1
        self.source.clear_queue()
        return self.generation

    async def transfer(self, reason):
        self.interrupt()
        requested = await self.request_handoff(reason)
        # Only the authenticated human-join webhook may later assert connected.
        return TransferResult(bool(requested), False, self.capabilities.transfer_mode)

    async def hangup(self):
        if self.closed:
            return
        self.closed = True
        self.interrupt()
        await self.room.disconnect()
