#!/usr/bin/env python3
"""Actual loopback WebRTC speech + verified human takeover smoke test.

This is restricted to a synthetic demo server. It proves local transport and
state integration, not PSTN performance, mobile coverage or clinical accuracy.
"""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from livekit import rtc
from receptionist.media.audio import decode_wav


async def run(api_url, audio_path):
    if urlparse(api_url).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("This smoke test accepts a loopback demo only")
    caller, staff = rtc.Room(), rtc.Room()
    received = {"frames": 0, "nonzero_frames": 0, "samples": 0}
    messages = []
    got_audio, got_turn, got_reply_pcm = asyncio.Event(), asyncio.Event(), asyncio.Event()
    timing = {}
    readers = set()
    source = rtc.AudioSource(16000, 1, queue_size_ms=200)
    report = {"synthetic_only": True, "transport": "actual LiveKit RTC SDK over loopback",
              "checks": {}, "limits": "One synthetic call; no public carrier, TLS/TURN, browser/device matrix or quality/SLO claim."}

    @caller.on("track_subscribed")
    def on_track(track, publication, participant):
        if track.kind != rtc.TrackKind.KIND_AUDIO or not participant.identity.startswith("agent-"):
            return
        async def read():
            stream = rtc.AudioStream(track, sample_rate=16000, num_channels=1, capacity=50)
            try:
                async for event in stream:
                    received["frames"] += 1
                    received["samples"] += event.frame.samples_per_channel
                    if any(event.frame.data):
                        received["nonzero_frames"] += 1
                        got_audio.set()
                        if got_turn.is_set() and "last_input_speech_frame" in timing and not got_reply_pcm.is_set():
                            timing["first_reply_pcm_received"] = time.perf_counter()
                            got_reply_pcm.set()
            finally:
                await stream.aclose()
        task = asyncio.create_task(read())
        readers.add(task)
        task.add_done_callback(readers.discard)

    @caller.on("data_received")
    def on_data(packet):
        if packet.topic == "reception.turn" and packet.participant and packet.participant.identity.startswith("agent-"):
            body = json.loads(packet.data)
            messages.append({key: body.get(key) for key in ("reply", "state", "transcript", "text") if key in body})
            timing["conversation_received"] = time.perf_counter()
            got_turn.set()

    async with httpx.AsyncClient(base_url=api_url, timeout=45) as client:
        health = (await client.get("/health")).json()
        if health.get("mode") != "demo":
            raise ValueError("Refusing to send synthetic calls to a non-demo application")
        started = await client.post("/api/v1/public/sessions", json={"clinic_slug": "bahar", "processing_consent": True})
        started.raise_for_status()
        session = started.json()
        sid = session["session_id"]
        headers = {"Authorization": "Bearer "+session["token"]}
        base = "/api/v1/public/sessions/"+sid
        try:
            joined = await client.post(base+"/livekit", headers=headers)
            joined.raise_for_status()
            media = joined.json()
            await caller.connect(media["url"], media["token"])
            track = rtc.LocalAudioTrack.create_audio_track("synthetic-caller", source)
            await caller.local_participant.publish_track(track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
            for _ in range(30):
                await source.capture_frame(rtc.AudioFrame(b"\0"*640, 16000, 1, 320))
            await asyncio.wait_for(got_audio.wait(), 35)
            report["checks"]["audible_agent_pcm_received"] = True
            pcm = decode_wav(audio_path.read_bytes(), 16000)+b"\0"*64000
            start = time.perf_counter()
            for offset in range(0, len(pcm), 640):
                chunk = pcm[offset:offset+640].ljust(640,b"\0")
                await source.capture_frame(rtc.AudioFrame(chunk,16000,1,320))
                if any(chunk):
                    timing["last_input_speech_frame"] = time.perf_counter()
            await asyncio.wait_for(got_turn.wait(), 35)
            await asyncio.wait_for(got_reply_pcm.wait(), 35)
            report["checks"]["audio_to_asr_to_conversation_to_data"] = True
            report["checks"]["nonzero_reply_audio_after_conversation"] = True
            report["utterance_send_to_turn_seconds"] = round(timing["conversation_received"]-start, 3)
            report["last_input_speech_frame_to_first_reply_pcm_received_ms"] = round(
                (timing["first_reply_pcm_received"]-timing["last_input_speech_frame"])*1000, 3)
            report["latency_boundary"] = "Last nonzero synthetic input frame submitted to SDK -> first nonzero reply PCM received after trusted turn event; includes endpointing and buffering, excludes physical speaker output. One observation, not an SLO distribution."
            report["turns"] = messages
            report["checks"]["no_unverified_booking_claim"] = all(x.get("state") not in {"COMPLETE", "CONFIRMED"} for x in messages)
            login = await client.post("/api/v1/auth/login", json={"email": "owner@example.test", "password": "DemoReception2026!"})
            login.raise_for_status()
            owner = {"Authorization": "Bearer "+login.json()["access_token"]}
            scoped = await client.post("/api/v1/auth/switch", headers=owner, json={"tenant_id": "clinic-bahar"})
            scoped.raise_for_status()
            owner = {"Authorization": "Bearer "+scoped.json()["access_token"]}
            takeover = await client.post("/api/v1/operations/calls/"+sid+"/takeover", headers=owner)
            takeover.raise_for_status()
            result = takeover.json()
            report["checks"]["takeover_requires_room_join"] = result["status"] == "ROOM_READY"
            before = (await client.get(base, headers=headers)).json()
            report["checks"]["not_connected_before_human_join"] = before.get("state") != "HUMAN_CONNECTED"
            await staff.connect(result["livekit"]["url"], result["livekit"]["token"])
            state = {}
            for _ in range(30):
                state = (await client.get(base, headers=headers)).json()
                if state.get("state") == "HUMAN_CONNECTED":
                    break
                await asyncio.sleep(.2)
            report["checks"]["signed_real_participant_handoff"] = state.get("state") == "HUMAN_CONNECTED"
            after = await client.post(base+"/turn", headers=headers, json={"text": "نوبت", "request_id": str(uuid4())})
            report["checks"]["ai_blocked_after_human_join"] = after.status_code == 409 and after.json().get("detail",{}).get("code") == "HUMAN_CONNECTED"
            report["received_audio"] = received.copy()
            report["passed"] = all(report["checks"].values())
            return report
        finally:
            active_readers = tuple(readers)
            for task in active_readers:
                task.cancel()
            await asyncio.gather(*active_readers, return_exceptions=True)
            await source.aclose()
            await caller.disconnect()
            await staff.disconnect()
            await client.post(base+"/end", headers=headers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--acknowledge-synthetic-demo", action="store_true", required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.api_url, args.audio))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
