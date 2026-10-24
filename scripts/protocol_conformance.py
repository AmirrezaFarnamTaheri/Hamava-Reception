#!/usr/bin/env python3
"""Deterministic, synthetic protocol-fixture conformance checks.

This exercises the real stream parsers and AMI projector with in-memory
transport doubles. It DOES NOT certify a provider SDK, an Iranian carrier,
recorded patient speech, a physical handset, or an OpenAI Realtime API clone.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from receptionist.media.streaming import DeepgramRealtimeSTT, GatewayPCMStream, ResponsesToolStream  # noqa: E402
from receptionist.media.realtime_contract import RealtimeProposalStream  # noqa: E402
from receptionist.providers import ProviderError  # noqa: E402


@contextmanager
def test_provider_gates():
    overrides = {
        "SPEECH_PROCESSOR_APPROVED": "true", "SPEECH_STREAMING_APPROVED": "true",
        "APPROVED_PROVIDER_HOSTS": "api.deepgram.com,speech.example.test",
        "STT_APPROVED_KEYTERMS_JSON": "[]",
    }
    before = {name: os.environ.get(name) for name in overrides}
    try:
        os.environ.update(overrides)
        yield
    finally:
        for name, prior in before.items():
            if prior is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = prior


async def _stt(fixture):
    class Socket:
        async def __aiter__(self):
            for value in fixture["events"]:
                await asyncio.sleep(0)
                yield json.dumps(value)
        async def send(self, value):
            pass
        async def close(self):
            pass
    async def connect(*args, **kwargs):
        return Socket()
    async def frames():
        yield b"\0" * 640
    events = [event async for event in DeepgramRealtimeSTT("synthetic-only", connect=connect).events(frames())]
    return {"event": events[-1]["event"] if events else None,
            "text": events[-1].get("text") if events else None,
            "partial_count": sum(event["event"] == "partial" for event in events)}


async def _model(fixture):
    async def events():
        for item in fixture["events"]:
            yield item
    received = [result async for result in ResponsesToolStream().parse(events(), request_id="req-synthetic-001")]
    proposals = [item for item in received if item["event"] == "tool_proposal"]
    return {"event": received[-1]["event"] if received else None,
            "proposals": len(proposals),
            "tools": [item["tool"] for item in proposals],
            "all_nonexecutable": all(item["executable"] is False for item in proposals)}


async def _realtime(fixture):
    async def events():
        for item in fixture["events"]:
            yield item
    received = [result async for result in RealtimeProposalStream().parse(events(), request_id="req-synthetic-001")]
    proposals = [item for item in received if item["event"] == "tool_proposal"]
    return {"event": received[-1]["event"] if received else None,
            "proposals": len(proposals), "tools": [item["tool"] for item in proposals],
            "all_nonexecutable": all(item["executable"] is False for item in proposals)}


async def _tts(fixture):
    """Replay the real framed PCM transport with arbitrary TCP/HTTP chunking."""
    import struct
    from httpx import AsyncByteStream
    if fixture.get("expect_error"):
        payload = struct.pack("!BH", 0x10, 640) + bytes(640)
    else:
        payload = (struct.pack("!BH", 0x10, 640) + bytes(640)) * 2
        payload += struct.pack("!BH", 0, 8) + (1280).to_bytes(8, "big")

    class Bytes(AsyncByteStream):
        async def __aiter__(self):
            offset = 0
            for size in fixture["chunks"]:
                yield payload[offset:offset+size]
                offset += size
            if offset < len(payload):
                yield payload[offset:]
        async def aclose(self):
            pass
    def handler(request):
        return httpx.Response(200, stream=Bytes(), headers={
            "Content-Type": "application/x-hamava-pcm-frames", "X-Audio-Format": "pcm_s16le",
            "X-Audio-Sample-Rate": "16000", "X-Audio-Channels": "1"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        events = [event async for event in GatewayPCMStream("https://speech.example.test", "synthetic-only", client).events("synthetic")]
    return {"event": events[-1]["event"] if events else None,
            "audio_frames": sum(event["event"] == "audio" for event in events),
            "buffered": any(event.get("buffered") for event in events)}


def _ami(fixture):
    relay_path = ROOT / "deploy/asterisk/hamava_ami_relay.py"
    spec = importlib.util.spec_from_file_location("hamava_ami_relay_conformance", relay_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    observer = module.AMIProjector(approved_targets={"PJSIP/reception"})
    observations = []
    for event in fixture["events"]:
        observations.extend(observer.project(event))
    return {"stages": [item["stage"] for item in observations],
            "connected_candidate": {"BRIDGE_CALLER", "BRIDGE_STAFF", "ACCEPTED", "SCREENED"}.issubset(
                {item["stage"] for item in observations})}


async def run_fixture(fixture):
    family = fixture.get("family")
    try:
        with test_provider_gates():
            if family == "deepgram":
                actual = await _stt(fixture)
            elif family == "model":
                actual = await _model(fixture)
            elif family == "realtime":
                actual = await _realtime(fixture)
            elif family == "tts":
                actual = await _tts(fixture)
            elif family == "ami":
                actual = _ami(fixture)
            else:
                return False, "UNSUPPORTED_FIXTURE_FAMILY"
        expected = fixture.get("expect")
        return (actual == expected, "MATCH" if actual == expected else "EXPECTED_OUTCOME_MISMATCH")
    except ProviderError as exc:
        error = fixture.get("expect_error")
        return (str(exc) == error, "MATCH" if str(exc) == error else "UNEXPECTED_PROVIDER_ERROR")
    except Exception:
        # Do not log synthetic content, patient-like values, or provider errors.
        return False, "UNEXPECTED_EXCEPTION"


async def run_fixture_suite(directory: Path):
    results = []
    paths = sorted(directory.glob("*.json"))
    for path in paths:
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        try:
            fixture = json.loads(data)
            if not isinstance(fixture, dict) or not isinstance(fixture.get("id"), str) or len(data) > 65536:
                raise ValueError
            success, code = await run_fixture(fixture)
            identifier = fixture["id"] if len(fixture["id"]) <= 80 else "INVALID_FIXTURE_ID"
        except (ValueError, TypeError, UnicodeDecodeError):
            success, code, identifier = False, "INVALID_FIXTURE", "INVALID_FIXTURE_ID"
        results.append({"id": identifier, "status": "PASS" if success else "FAIL",
                        "reason": code, "fixture_sha256": digest})
    passed = sum(r["status"] == "PASS" for r in results)
    return {"protocol_suite": "synthetic-parser-and-adapter-conformance", "version": 1,
            "cases": len(results), "passed": passed, "failed": len(results) - passed,
            "scope": "offline deterministic mock transport only; no vendor, carrier, or real device certified",
            "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "fixtures/protocol")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = asyncio.run(run_fixture_suite(args.fixtures))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Protocol fixtures: {result['passed']}/{result['cases']} passing; no live provider certified")
    return 0 if result["cases"] >= 8 and not result["failed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
