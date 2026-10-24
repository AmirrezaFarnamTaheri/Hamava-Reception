#!/usr/bin/env python3
"""Bounded speech-worker benchmark; sends only operator-supplied approved audio.

Default endpoint scope is loopback. No transcript/audio is included in reports.
It records cold-state observations, actual responses and server cost metrics;
synthetic fixture runs are transport evidence, not Persian speech-quality proof.
"""
from __future__ import annotations

import argparse
import asyncio
from decimal import Decimal
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx

try:
    from .research_common import quantile, sha256, write_json
except ImportError:
    from research_common import quantile, sha256, write_json


async def benchmark(url, token, audio, *, requests=20, concurrency=2, client=None):
    if not 1 <= requests <= 1000 or not 1 <= concurrency <= 32 or len(audio) > 5_000_000:
        raise ValueError("benchmark_bounds_invalid")
    if len(token) < 32:
        raise ValueError("speech_gateway_token_required")
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=120, follow_redirects=False)
    headers = {"Authorization": "Bearer " + token}
    try:
        before_response = await client.get(url.rstrip("/") + "/metrics", headers=headers)
        before = before_response.json() if before_response.status_code == 200 else None
        gate = asyncio.Semaphore(concurrency)
        async def request(index):
            async with gate:
                started = time.monotonic()
                try:
                    result = await client.post(url.rstrip("/") + "/transcribe", headers={**headers, "Content-Type": "audio/wav"}, content=audio)
                    status = result.status_code
                except httpx.HTTPError:
                    status = "transport_error"
                return {"ordinal": index, "status": status, "duration_ms": (time.monotonic() - started) * 1000}
        # First request is isolated so cold and subsequent concurrent requests
        # are distinguishable without resetting any existing model process.
        first = await request(0)
        remaining = await asyncio.gather(*(request(index) for index in range(1, requests)))
        after_response = await client.get(url.rstrip("/") + "/metrics", headers=headers)
        after = after_response.json() if after_response.status_code == 200 else None
        completed = [row["duration_ms"] for row in remaining if row["status"] == 200]
        counts = {}
        for row in [first, *remaining]:
            counts[str(row["status"])] = counts.get(str(row["status"]), 0) + 1
        cost_delta = None
        if before and after and before.get("allocated_capacity_cost_toman_exact") is not None and after.get("allocated_capacity_cost_toman_exact") is not None:
            cost_delta = format(Decimal(after["allocated_capacity_cost_toman_exact"]) - Decimal(before["allocated_capacity_cost_toman_exact"]), "f")
        return {"schema_version": "1.0", "audio_sha256": sha256(audio), "requests": requests, "concurrency": concurrency,
            "first_request": first, "cold_model_observed_before": before.get("asr_loaded") is False if before else None,
            "status_counts": counts, "subsequent_success_latency_ms": {"n": len(completed), "p50": quantile(completed, .5), "p95": quantile(completed, .95), "p99": quantile(completed, .99)},
            "server_metrics_before": before, "server_metrics_after": after, "allocated_compute_delta_toman_exact": cost_delta,
            "speech_quality_measured": False, "carrier_latency_measured": False, "model_or_corpus_created": False}
    finally:
        if own_client:
            await client.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--requests", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--approved-remote-endpoint", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    parsed = urlsplit(args.url)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.scheme not in {"http", "https"} or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} and not args.approved_remote_endpoint:
        parser.error("Use a loopback endpoint or explicitly approve a remote endpoint without URL credentials")
    try:
        if args.audio.stat().st_size > 5_000_000:
            raise ValueError("audio_size_exceeds_limit")
        result = asyncio.run(benchmark(args.url, os.getenv("SPEECH_GATEWAY_TOKEN", ""), args.audio.read_bytes(), requests=args.requests, concurrency=args.concurrency))
        write_json(result, args.output)
    except (ValueError, OSError, httpx.HTTPError, json.JSONDecodeError):
        parser.exit(2, "benchmark_failed_no_response_content_logged\n")


if __name__ == "__main__":
    main()
