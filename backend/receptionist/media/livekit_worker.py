"""LiveKit WebRTC worker using the same bounded, transactional conversation API.

No browser credentials or provider secrets enter room metadata. Worker leases
are acquired from the private API, and an actual staff participant pauses AI.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from livekit import rtc

from .audio import TurnBuffer, decode_wav
from .contracts import LiveKitTransport
from .native_runtime import native_enabled, new_native_turn, routine_interruption
from ..providers import ProviderError

log = logging.getLogger("receptionist.webrtc")


class RoomAgent:
    def __init__(self, api_url: str, record: dict):
        self.api_url, self.record = api_url.rstrip("/"), record
        self.room = rtc.Room()
        self.source = rtc.AudioSource(16000, 1, queue_size_ms=200)
        self.client = httpx.AsyncClient(timeout=35, follow_redirects=False)
        self.base = self.api_url + "/api/v1/public/sessions/" + record["session_id"]
        self.headers = {"Authorization": "Bearer " + record["token"]}
        self.finished = asyncio.Event()
        self.caller_ready = asyncio.Event()
        self.human_present = False
        self.generation = 0
        self.playback = None
        self.processing = None
        self.streams: set[asyncio.Task] = set()
        self.pending_audio: tuple[bytes, int] | None = None
        self.lease_lost = False
        self.lease_deadline = asyncio.get_running_loop().time() + 30
        expires = datetime.fromisoformat(record["expires_at"].replace("Z", "+00:00"))
        if expires.tzinfo is None:
            raise ValueError("Call expiration must be timezone-aware")
        self.call_deadline = asyncio.get_running_loop().time() + max(0, min(1800, (expires - datetime.now(timezone.utc)).total_seconds()))
        self.input_task = None
        self.native_turn = None
        self.transport = LiveKitTransport(self.source, self.room, self.request_transfer)

    async def request_transfer(self, reason):
        response = await self.client.post(self.base + "/handoff", headers=self.headers, json={"reason": reason})
        return response.status_code == 200 and response.json().get("state") == "HANDOFF_PENDING"

    def renew_lease(self, seconds: int = 30):
        self.lease_deadline = asyncio.get_running_loop().time() + min(30, max(1, seconds))

    def lose_lease(self):
        self.lease_lost = True
        self.pending_audio = None
        if self.native_turn:
            self.native_turn.finish()
        self.interrupt()
        self.finished.set()

    async def watch_lease(self):
        while not self.finished.is_set():
            if asyncio.get_running_loop().time() >= self.call_deadline:
                self.interrupt()
                self.finished.set()
                return
            if asyncio.get_running_loop().time() >= self.lease_deadline:
                self.lose_lease()
                return
            await asyncio.sleep(1)

    def interrupt(self):
        self.generation += 1
        if self.playback and self.playback is not asyncio.current_task():
            self.playback.cancel()
        self.transport.interrupt()

    async def play(self, turn_id: str, generation: int):
        if self.human_present or self.lease_lost or self.finished.is_set():
            return
        try:
            response = await self.client.get(self.base + "/speech", params={"turn_id": turn_id}, headers=self.headers)
            if generation != self.generation:
                return
            if response.status_code != 200:
                if response.status_code == 409 and response.json().get("detail", {}).get("code") == "MEDIA_LEASE_LOST":
                    self.lose_lease()
                elif response.status_code == 409 and response.json().get("detail", {}).get("code") == "HUMAN_CONNECTED":
                    self.human_present = True
                    self.interrupt()
                elif response.status_code == 410:
                    self.finished.set()
                else:
                    await self.failure_handoff()
                return
            pcm = decode_wav(response.content, 16000)
        except (httpx.HTTPError, ValueError):
            await self.failure_handoff()
            return
        for offset in range(0, len(pcm), 640):
            if self.human_present or self.lease_lost or self.finished.is_set() or generation != self.generation:
                return
            chunk = pcm[offset:offset+640].ljust(640, b"\0")
            await self.transport.send_audio(chunk, 16000)

    async def process(self, audio: bytes, generation: int | None = None):
        generation = self.generation if generation is None else generation
        while audio and not self.human_present and not self.finished.is_set():
            try:
                result = await self.client.post(self.base + "/audio", content=audio,
                    headers={**self.headers, "Content-Type": "audio/wav", "X-Request-ID": str(uuid4())})
            except httpx.HTTPError:
                await self.failure_handoff()
                return
            if result.status_code == 200:
                data = result.json()
                if data.get("state") == "HUMAN_CONNECTED":
                    self.human_present = True
                    self.pending_audio = None
                    self.interrupt()
                    return
                await self.room.local_participant.publish_data(json.dumps(data, ensure_ascii=False).encode(), reliable=True, topic="reception.turn")
                if data.get("turn_id") and generation == self.generation and not self.human_present:
                    self.playback = asyncio.create_task(self.play(data["turn_id"], generation))
            elif result.status_code in {410, 429}:
                self.finished.set()
            elif result.status_code == 409:
                code = result.json().get("detail", {}).get("code")
                if code == "MEDIA_LEASE_LOST":
                    self.lose_lease()
                elif code == "HUMAN_CONNECTED":
                    self.human_present = True
                    self.pending_audio = None
                    self.interrupt()
                else:
                    await self.failure_handoff()
                    return
            elif result.status_code >= 500:
                await self.failure_handoff()
                return
            pending, self.pending_audio = self.pending_audio, None
            if pending:
                audio, generation = pending
            else:
                audio = None

    async def failure_handoff(self):
        if self.human_present or self.lease_lost:
            return
        self.pending_audio = None
        self.interrupt()
        queued = False
        try:
            result = await self.transport.transfer("service_failure")
            queued = result.requested
        except httpx.HTTPError:
            pass
        reply = "پاسخ‌گویی صوتی قطع شد؛ درخواست پیگیری پذیرش ثبت شده است." if queued else "پاسخ‌گویی صوتی قطع شد؛ لطفاً با شماره مستقیم مرکز تماس بگیرید."
        await self.room.local_participant.publish_data(json.dumps({"reply": reply,
            "state": "HANDOFF_PENDING" if queued else "SERVICE_UNAVAILABLE"}, ensure_ascii=False).encode(), reliable=True, topic="reception.turn")
        if not queued:
            self.finished.set()

    async def listen(self, track):
        self.caller_ready.set()
        buffer = TurnBuffer(sample_rate=16000)
        stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1, capacity=50, frame_size_ms=20)
        native = None

        async def run_native(turn):
            try:
                await turn.wait()
            except ProviderError as error:
                if not routine_interruption(error):
                    await self.failure_handoff()
            except (httpx.HTTPError, ValueError, ConnectionError, TimeoutError):
                await self.failure_handoff()
            finally:
                # The first /turn may already have committed before its reply
                # was lost. Never resubmit it; process only the distinct next
                # utterance and only while the session still belongs to AI.
                pending, self.pending_audio = self.pending_audio, None
                if pending and not self.human_present and not self.lease_lost and not self.finished.is_set():
                    audio, generation = pending
                    self.processing = asyncio.create_task(self.process(audio, generation))

        async def emit(item):
            if not self.human_present and not self.lease_lost and not self.finished.is_set():
                await self.room.local_participant.publish_data(
                    json.dumps(item, ensure_ascii=False).encode(), reliable=True, topic="reception.turn")

        try:
            async for event in stream:
                if self.human_present or self.finished.is_set():
                    break
                frame = bytes(event.frame.data)
                speaking_before = buffer.speaking
                audio, began = buffer.push(frame)
                if began:
                    self.interrupt()
                    if (native_enabled() and not audio and not self.lease_lost
                        and (self.processing is None or self.processing.done())):
                        try:
                            generation = self.generation
                            native = new_native_turn(self.client, api_url=self.api_url,
                                session_id=self.record["session_id"], token=self.record["token"],
                                emit_event=emit, send_audio=self.transport.send_audio,
                                source_rate=16000, generation=generation,
                                generation_current=lambda: self.generation,
                                request_id=str(uuid4()))
                            native.start(bytes(buffer._frames))  # includes speech pre-roll
                            self.native_turn = native
                            self.processing = asyncio.create_task(run_native(native))
                        except (ProviderError, ValueError):
                            await self.failure_handoff()
                            return
                elif speaking_before and native:
                    try:
                        native.feed(frame)
                    except ProviderError:
                        await self.failure_handoff()
                        return
                if audio:
                    if native:
                        native.finish()
                        native = None
                        self.native_turn = None
                    elif self.processing and not self.processing.done():
                        self.pending_audio = (audio, self.generation)
                    else:
                        self.processing = asyncio.create_task(self.process(audio, self.generation))
        finally:
            if native:
                # Disconnect is not an utterance endpoint and cannot authorize
                # a transcript or another appointment write.
                await native.close()
                self.native_turn = None
            await stream.aclose()

    async def run(self):
        @self.room.on("track_subscribed")
        def subscribed(track, publication, participant):
            if (participant.identity == "caller-" + self.record["session_id"] and track.kind == rtc.TrackKind.KIND_AUDIO
                    and not self.human_present and not self.finished.is_set()
                    and (self.input_task is None or self.input_task.done())):
                task = asyncio.create_task(self.listen(track))
                self.input_task = task
                self.streams.add(task)
                task.add_done_callback(self.streams.discard)

        @self.room.on("participant_connected")
        def connected(participant):
            if participant.identity.startswith("staff-"):
                self.human_present = True
                self.pending_audio = None
                self.interrupt()

        @self.room.on("participant_disconnected")
        def disconnected(participant):
            if participant.identity == "caller-" + self.record["session_id"]:
                self.finished.set()
            elif participant.identity.startswith("staff-"):
                # Do not resume autonomous writes after takeover without a fresh caller flow.
                self.finished.set()

        @self.room.on("disconnected")
        def room_disconnected(*args):
            self.finished.set()

        lease_watch = asyncio.create_task(self.watch_lease())
        try:
            await self.room.connect(self.record["livekit"]["url"], self.record["livekit"]["token"])
            await self.transport.start(self.record["session_id"])
            track = rtc.LocalAudioTrack.create_audio_track("receptionist", self.source)
            await self.room.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
            for participant in self.room.remote_participants.values():
                if participant.identity.startswith("staff-"):
                    connected(participant)
                for publication in participant.track_publications.values():
                    if publication.track:
                        subscribed(publication.track, publication, participant)
            readiness = asyncio.create_task(self.caller_ready.wait())
            closure = asyncio.create_task(self.finished.wait())
            _, waiting = await asyncio.wait({readiness, closure}, timeout=45, return_when=asyncio.FIRST_COMPLETED)
            for waiter in waiting:
                waiter.cancel()
            await asyncio.gather(readiness, closure, return_exceptions=True)
            if self.finished.is_set() or not self.caller_ready.is_set():
                return
            self.playback = asyncio.create_task(self.play("greeting", self.generation))
            await asyncio.wait_for(self.finished.wait(), 1800)
        except (TimeoutError, httpx.HTTPError, ConnectionError):
            log.info("webrtc_call_closed", extra={"call_id": self.record["session_id"]})
        finally:
            self.finished.set()
            lease_watch.cancel()
            await asyncio.gather(lease_watch, return_exceptions=True)
            self.interrupt()
            for task in self.streams:
                task.cancel()
            await asyncio.gather(*self.streams, return_exceptions=True)
            if self.processing:
                try:
                    await asyncio.wait_for(asyncio.shield(self.processing), 35)
                except (Exception, asyncio.CancelledError):
                    self.processing.cancel()
                    await asyncio.gather(self.processing, return_exceptions=True)
            if self.playback:
                await asyncio.gather(self.playback, return_exceptions=True)
            if not self.lease_lost:
                try:
                    await self.client.post(self.base + "/end", headers=self.headers)
                except httpx.HTTPError:
                    pass
            await self.transport.hangup()
            await self.source.aclose()
            await self.client.aclose()


async def main(stop=None):
    from ..core_runtime import shutdown_event, drain_tasks
    stop = stop or shutdown_event()
    api_url = os.getenv("RECEPTION_API_URL", "http://127.0.0.1:8000")
    token = os.environ["MEDIA_API_TOKEN"]
    worker_id = "worker-" + str(uuid4())
    tasks: dict[str, asyncio.Task] = {}
    agents: dict[str, RoomAgent] = {}
    capacity = max(1, min(100, int(os.getenv("MAX_LIVEKIT_ROOMS_PER_WORKER", "8"))))
    async with httpx.AsyncClient(timeout=12) as client:
        try:
            while not stop.is_set():
                for sid in list(tasks):
                    if tasks[sid].done():
                        await asyncio.gather(tasks.pop(sid), return_exceptions=True)
                        agents.pop(sid, None)
                try:
                    response = await client.post(api_url.rstrip("/") + "/api/v1/internal/media/rooms",
                        headers={"Authorization": "Bearer " + token},
                        json={"worker_id": worker_id, "active_sessions": list(tasks), "capacity": capacity})
                    response.raise_for_status()
                    data = response.json()
                    for sid in data.get("revoked_sessions", []):
                        if sid in agents:
                            agents[sid].lose_lease()
                    for sid in data.get("renewed_sessions", []):
                        if sid in agents:
                            agents[sid].renew_lease(data.get("lease_seconds", 30))
                    for record in data["rooms"]:
                        if record["session_id"] not in tasks and len(tasks) < capacity:
                            agent = RoomAgent(api_url, record)
                            agent.renew_lease(data.get("lease_seconds", 30))
                            agents[record["session_id"]] = agent
                            tasks[record["session_id"]] = asyncio.create_task(agent.run())
                except (httpx.HTTPError, KeyError):
                    log.warning("media_poll_failed")
                try:
                    await asyncio.wait_for(stop.wait(), timeout=5)
                except TimeoutError:
                    pass
        finally:
            for agent in agents.values():
                agent.pending_audio = None
                agent.interrupt()
                agent.finished.set()
            await drain_tasks(tasks.values())


if __name__ == "__main__":
    asyncio.run(main())
