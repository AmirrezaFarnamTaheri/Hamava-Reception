#!/usr/bin/env python3
"""Loopback-only synthetic AudioSocket call; no carrier or outbound call.

Runs the real bridge, local speech gateway, durable conversation and DTMF
fallback. A carrier codec/NAT/DTMF acceptance matrix remains a separate gate.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from receptionist.media.audio import decode_wav
from receptionist.media.audiosocket import encode_frame, read_frame


async def run(api_url: str, host: str, port: int, audio_path: Path) -> dict:
    if urlparse(api_url).hostname not in {"localhost", "127.0.0.1", "::1"} or host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("This synthetic test accepts loopback endpoints only")
    headers = {"Authorization": "Bearer "+os.environ["MEDIA_API_TOKEN"]}
    report = {"synthetic_only": True, "transport": "real TCP AudioSocket over loopback",
        "checks": {}, "limits": "No carrier call, physical PBX, NAT/codec matrix, telephone quality or production-capacity claim."}
    async with httpx.AsyncClient(base_url=api_url, timeout=15) as client:
        health = (await client.get("/health")).json()
        if health.get("mode") != "demo":
            raise ValueError("A synthetic demo application is required")
        call_uuid = uuid4()
        registered = await client.post("/api/v1/internal/media/register", headers=headers, json={
            "call_uuid": str(call_uuid), "did": "TEST-DID-001", "processing_notice_played": True, "routing_reason": "incoming"})
        registered.raise_for_status()
        record = registered.json()
        if not record["registered"]:
            raise ValueError("The synthetic tenant did not authorize automated reception")
        sid = record["session_id"]
        reader, writer = await asyncio.open_connection(host, port)
        frames, nonzero = 0, 0
        arrivals = []
        got_greeting, got_reply, closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        input_started = False
        reply_after = 0.0
        async def receive():
            nonlocal frames, nonzero
            try:
                while True:
                    kind, payload = await read_frame(reader, 40)
                    if kind == 0:
                        break
                    if kind == 0x10:
                        if len(payload) != 320:
                            raise AssertionError("Bridge output must use 20 ms 8-kHz PCM packets")
                        frames += 1
                        arrivals.append(time.perf_counter())
                        if any(payload):
                            nonzero += 1
                            got_greeting.set()
                            if input_started and time.perf_counter() > reply_after:
                                got_reply.set()
            except asyncio.IncompleteReadError:
                pass
            finally:
                closed.set()
        receiver = asyncio.create_task(receive())
        try:
            # A fragmented UUID header exercises real TCP framing.
            frame = encode_frame(1, call_uuid.bytes)
            writer.write(frame[:2])
            await writer.drain()
            writer.write(frame[2:])
            await writer.drain()
            await asyncio.wait_for(got_greeting.wait(), 20)
            report["checks"]["registered_uuid_and_greeting_pcm"] = True
            input_started = True
            pcm = decode_wav(audio_path.read_bytes(), 8000)+b"\0"*16000
            reply_after = time.perf_counter()+len(pcm)/16000
            for offset in range(0, len(pcm), 320):
                writer.write(encode_frame(0x10, pcm[offset:offset+320].ljust(320,b"\0")))
                await writer.drain()
                await asyncio.sleep(.02)
            await asyncio.wait_for(got_reply.wait(), 20)
            report["checks"]["post_utterance_reply_pcm"] = True
            # Explicit human request; the PBX owns the subsequent staffed Dial.
            writer.write(encode_frame(3,b"0")+encode_frame(3,b"#"))
            await writer.drain()
            await asyncio.wait_for(closed.wait(), 8)
            report["checks"]["dtmf_zero_hash_returns_control_to_pbx"] = True
            owner_login = await client.post("/api/v1/auth/login", json={
                "email": "owner@example.test", "password": "DemoReception2026!"})
            owner_login.raise_for_status()
            owner = {"Authorization": "Bearer "+owner_login.json()["access_token"]}
            scoped = await client.post("/api/v1/auth/switch", headers=owner, json={"tenant_id": "clinic-bahar"})
            scoped.raise_for_status()
            owner = {"Authorization": "Bearer "+scoped.json()["access_token"]}
            tasks = (await client.get("/api/v1/tasks", headers=owner)).json()
            # API shape is a bare list; only the test call ID is inspected.
            tasks = tasks.get("items", []) if isinstance(tasks, dict) else tasks
            report["checks"]["durable_human_followup"] = any(t.get("call_id") == sid for t in tasks)
            duplicate = await client.post("/api/v1/internal/media/claim", headers=headers, json={"call_uuid": str(call_uuid)})
            report["checks"]["one_use_uuid_cannot_rejoin"] = duplicate.status_code in {404,409}
            from sqlalchemy import func, select
            from receptionist.db import SessionLocal
            from receptionist.models_voice import CallSession, VoiceTurn
            with SessionLocal() as db:
                turn_count = db.scalar(select(func.count()).select_from(VoiceTurn).where(VoiceTurn.call_id == sid))
                call = db.get(CallSession, sid)
                report["checks"]["audio_turn_durably_recorded"] = turn_count == 1
                report["checks"]["call_finalized_after_pbx_return"] = call is not None and call.ended_at is not None
            report["received_audio"] = {"packets": frames, "nonzero_packets": nonzero, "samples_per_packet": 160, "sample_rate": 8000}
            within = [b-a for a,b in zip(arrivals,arrivals[1:]) if b-a < .1]
            report["mean_packet_spacing_seconds_excluding_turn_gaps"] = round(sum(within)/len(within),4) if within else None
            report["passed"] = all(report["checks"].values())
            return report
        finally:
            writer.close()
            await writer.wait_closed()
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9092)
    parser.add_argument("--audio", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--acknowledge-synthetic-demo", action="store_true", required=True)
    args = parser.parse_args()
    result = asyncio.run(run(args.api_url,args.host,args.port,args.audio))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
