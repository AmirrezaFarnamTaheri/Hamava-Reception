"""Optional local Persian speech service; audio stays in memory.

Models must be explicitly provisioned under a reviewed license. This process
never downloads model weights during a patient call. It is a CPU baseline, not
a claim of telephone accuracy or sub-second production latency.
"""
from __future__ import annotations

import asyncio
import hmac
import io
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import wave
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

app = FastAPI(title="Hamava Local Speech", docs_url=None, redoc_url=None)
_model = _voice = None
_lock = threading.Lock()
_capacity = max(1, min(8, int(os.getenv("SPEECH_MAX_CONCURRENCY", "2"))))
_queue_limit = max(0, min(64, int(os.getenv("SPEECH_MAX_QUEUE", "8"))))
_admission = asyncio.Semaphore(_capacity)
_metrics_lock = threading.Lock()
_counts = defaultdict(int)
_timings = defaultdict(lambda: deque(maxlen=2048))
_started = time.monotonic()


@asynccontextmanager
async def admission():
    # Bound expensive work before retaining multi-megabyte uploads.
    started = time.monotonic()
    with _metrics_lock:
        if _counts["active"] + _counts["waiting"] >= _capacity + _queue_limit:
            _counts["rejected"] += 1
            raise HTTPException(503, "Speech capacity queue is full")
        _counts["waiting"] += 1
    try:
        await asyncio.wait_for(_admission.acquire(), timeout=.05)
    except TimeoutError:
        with _metrics_lock:
            _counts["rejected"] += 1
        raise HTTPException(503, "Speech capacity is busy")
    finally:
        with _metrics_lock:
            _counts["waiting"] -= 1
            _timings["queue_ms"].append((time.monotonic() - started) * 1000)
    with _metrics_lock:
        _counts["active"] += 1
        _counts["admitted"] += 1
    try:
        yield
    finally:
        with _metrics_lock:
            _counts["active"] -= 1
        _admission.release()


def record_runtime(kind, duration_ms, *, failed=False):
    with _metrics_lock:
        _counts[kind + ("_failed" if failed else "_completed")] += 1
        _timings[kind + "_ms"].append(duration_ms)


async def measured_work(kind, function, *args):
    started = time.monotonic()
    try:
        result = await run_in_threadpool(function, *args)
    except Exception:
        record_runtime(kind, (time.monotonic() - started) * 1000, failed=True)
        raise
    record_runtime(kind, (time.monotonic() - started) * 1000)
    return result


def authorize(authorization: str = Header(default="")):
    token = os.getenv("SPEECH_GATEWAY_TOKEN", "")
    if len(token) < 32 or not hmac.compare_digest(authorization, "Bearer " + token):
        raise HTTPException(401, "Speech service authorization required")


def configured_models() -> tuple[Path, Path]:
    asr = Path(os.getenv("WHISPER_MODEL_PATH", "/models/whisper"))
    voice = Path(os.getenv("PIPER_MODEL_PATH", "/models/fa_IR-amir-medium.onnx"))
    if not (asr / "model.bin").is_file() or not voice.is_file() or not voice.with_suffix(".onnx.json").is_file():
        raise HTTPException(503, "Speech models have not been provisioned")
    if os.getenv("SPEECH_MODEL_RIGHTS_REVIEWED", "false").lower() != "true":
        raise HTTPException(503, "Speech model rights review has not been recorded")
    return asr, voice


def configured_voice() -> Path:
    voice = Path(os.getenv("PIPER_MODEL_PATH", "/models/fa_IR-amir-medium.onnx"))
    if not voice.is_file() or not voice.with_suffix(".onnx.json").is_file():
        raise HTTPException(503, "Speech voice model has not been provisioned")
    if os.getenv("SPEECH_MODEL_RIGHTS_REVIEWED", "false").lower() != "true":
        raise HTTPException(503, "Speech model rights review has not been recorded")
    return voice


def decode_audio(data: bytes) -> bytes:
    try:
        result = subprocess.run(["ffmpeg", "-nostdin", "-v", "error",
            "-protocol_whitelist", "pipe", "-format_whitelist", "wav,matroska,webm,ogg,mov,mp4,m4a,3gp,3g2,mj2",
            "-i", "pipe:0", "-map", "0:a:0", "-vn", "-sn", "-dn", "-t", "60.01",
            "-f", "s16le", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", "pipe:1"],
            input=data, capture_output=True, timeout=15, check=True)
    except (subprocess.SubprocessError, FileNotFoundError):
        raise HTTPException(422, "Audio could not be decoded")
    if len(result.stdout) > 1_920_000 or len(result.stdout) < 320:
        raise HTTPException(422, "Audio duration is outside the permitted range")
    return result.stdout


def transcribe_local(data: bytes, keyterms: list[str]) -> dict:
    global _model
    asr, _ = configured_models()
    pcm = decode_audio(data)
    # ffmpeg already validated and decoded the stream. Passing a float waveform
    # avoids a second container decoder and PyAV version-specific APIs.
    import numpy as np
    waveform = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    with _lock:
        if _model is None:
            cold_started = time.monotonic()
            import onnxruntime
            onnxruntime.disable_telemetry_events()
            from faster_whisper import WhisperModel
            _model = WhisperModel(str(asr), device=os.getenv("WHISPER_DEVICE", "cpu"),
                compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"), local_files_only=True,
                cpu_threads=int(os.getenv("WHISPER_CPU_THREADS", "4")))
            record_runtime("asr_cold_load", (time.monotonic() - cold_started) * 1000)
        segments, _info = _model.transcribe(waveform, language="fa", beam_size=3, vad_filter=True,
            condition_on_previous_text=False, temperature=0, hotwords=", ".join(keyterms[:30])[:800],
            no_speech_threshold=.6, hallucination_silence_threshold=1.5)
        text = " ".join(segment.text.strip() for segment in segments)
    return {"text": text[:2000], "audio_seconds": len(pcm) / 32000,
            "model": "faster-whisper-local", "confidence": None}


class Synthesis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)
    language: str = "fa"
    slow: bool = False
    format: str = "wav"
    sample_rate: int = 16000


def synthesize_local(request: Synthesis) -> bytes:
    global _voice
    _, voice_path = configured_models()
    if request.language != "fa" or request.format != "wav" or request.sample_rate != 16000:
        raise HTTPException(422, "Only Persian 16 kHz WAV output is configured")
    from piper import PiperVoice, SynthesisConfig
    import onnxruntime
    onnxruntime.disable_telemetry_events()
    buffer = io.BytesIO()
    with _lock:
        if _voice is None:
            cold_started = time.monotonic()
            _voice = PiperVoice.load(str(voice_path))
            record_runtime("tts_cold_load", (time.monotonic() - cold_started) * 1000)
        with wave.open(buffer, "wb") as output:
            _voice.synthesize_wav(request.text, output, syn_config=SynthesisConfig(length_scale=1.35 if request.slow else 1.0))
    pcm = decode_audio(buffer.getvalue())
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(pcm)
    return target.getvalue()


@app.get("/health", dependencies=[Depends(authorize)])
def health():
    configured_models()
    return {"status": "configured", "language": "fa", "recording": False, "mode": "local_cpu_baseline"}


@app.get("/metrics", dependencies=[Depends(authorize)])
def metrics():
    with _metrics_lock:
        counts = dict(_counts)
        timings = {key: sorted(values) for key, values in _timings.items()}
    summaries = {}
    for key, values in timings.items():
        summaries[key] = {"samples": len(values), "p50": values[min(len(values) - 1, int((len(values) - 1) * .5))] if values else None,
            "p95": values[min(len(values) - 1, int((len(values) - 1) * .95))] if values else None}
    elapsed = max(0, time.monotonic() - _started)
    cost, rate_evidence = None, os.getenv("LOCAL_COMPUTE_RATE_EVIDENCE_REFERENCE")
    try:
        rate = Decimal(os.getenv("LOCAL_COMPUTE_TOMAN_PER_HOUR", "NaN"))
        if rate.is_finite() and rate >= 0 and rate_evidence:
            cost = format(Decimal(str(elapsed)) * rate / 3600, "f")
    except InvalidOperation:
        pass
    return {"schema_version": "1.0", "uptime_seconds": elapsed, "counts": counts, "timings": summaries,
        "admission_capacity": _capacity, "queue_limit": _queue_limit, "metric_window_max_samples": 2048,
        "model_execution_serialized": True, "asr_loaded": _model is not None, "tts_loaded": _voice is not None,
        "allocated_capacity_cost_toman_exact": cost, "cost_basis": "measured_process_uptime_including_idle_at_operator_declared_rate" if cost is not None else "unpriced",
        "cost_is_vendor_reconciled": False, "audio_or_text_stored_in_metrics": False}


@app.post("/transcribe", dependencies=[Depends(authorize)])
async def transcribe(request: Request, x_keyterms: str = Header(default="[]")):
    try:
        if len(x_keyterms) > 16000:
            raise ValueError
        keyterms = json.loads(x_keyterms)
        if not isinstance(keyterms, list) or any(not isinstance(x, str) or len(x) > 100 for x in keyterms) or len(keyterms) > 30:
            raise ValueError
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid keyterms")
    async with admission():
        data = bytearray()
        try:
            async with asyncio.timeout(15):
                async for chunk in request.stream():
                    if len(data) + len(chunk) > 5_000_000:
                        raise HTTPException(413, "Audio upload is too large")
                    data.extend(chunk)
        except TimeoutError:
            raise HTTPException(408, "Audio upload timed out")
        return await measured_work("transcribe", transcribe_local, bytes(data), keyterms)


@app.post("/synthesize", dependencies=[Depends(authorize)])
async def synthesize(request: Synthesis):
    async with admission():
        audio = await measured_work("synthesize", synthesize_local, request)
    return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})


# Streaming synthesis is separate from the original WAV endpoint. No WAV is
# synthesized to completion before the first PCM chunk reaches the caller.
STREAM_PCM_MAX_BYTES = 3_840_000  # 120 seconds at 16 kHz, mono, 16-bit


def synthesize_pcm_frames(request: Synthesis):
    """Yield Piper sentence chunks in complete 20-ms 16-kHz mono frames.

    The bounded synthesis generator keeps the licensed voice loaded and shared
    locally; it never records an audio file or accepts a model path from users.
    """
    import audioop
    global _voice
    voice_path = configured_voice()
    if request.language != "fa" or request.format != "pcm_s16le" or request.sample_rate != 16000:
        raise ValueError("INVALID_STREAM_FORMAT")
    from piper import PiperVoice, SynthesisConfig
    config = SynthesisConfig(length_scale=1.35 if request.slow else 1.0)
    with _lock:
        if _voice is None:
            started = time.monotonic()
            _voice = PiperVoice.load(str(voice_path))
            record_runtime("tts_cold_load", (time.monotonic() - started) * 1000)
        pending = bytearray()
        state, rate, count = None, None, 0
        for item in _voice.synthesize(request.text, syn_config=config):
            if (item.sample_width != 2 or item.sample_channels != 1
                or not 8000 <= item.sample_rate <= 48000
                or not isinstance(item.audio_int16_bytes, bytes) or len(item.audio_int16_bytes) % 2):
                raise ValueError("STREAM_PCM_FORMAT_MISMATCH")
            if rate is not None and item.sample_rate != rate:
                raise ValueError("STREAM_SAMPLE_RATE_CHANGED")
            rate = item.sample_rate
            packet = item.audio_int16_bytes
            if rate != 16000:
                packet, state = audioop.ratecv(packet, 2, 1, rate, 16000, state)
            count += len(packet)
            if count > STREAM_PCM_MAX_BYTES:
                raise ValueError("STREAM_AUDIO_LIMIT")
            pending.extend(packet)
            while len(pending) >= 640:
                yield bytes(pending[:640])
                del pending[:640]
        if pending:
            yield bytes(pending).ljust(640, b"\0")


@app.post("/synthesize/stream", dependencies=[Depends(authorize)])
async def synthesize_stream(request: Synthesis):
    from starlette.responses import StreamingResponse
    from starlette.concurrency import iterate_in_threadpool
    if request.language != "fa" or request.format != "pcm_s16le" or request.sample_rate != 16000:
        raise HTTPException(422, "Only Persian PCM16 16-kHz streaming is configured")
    # Validate licensing and provisioning before returning 200 + an audio body.
    configured_voice()

    async def body():
        import struct
        started, total = time.monotonic(), 0
        failed = False
        async with admission():
            try:
                async for pcm in iterate_in_threadpool(synthesize_pcm_frames(request)):
                    if not isinstance(pcm, bytes) or len(pcm) != 640:
                        raise ValueError("STREAM_PCM_FORMAT_MISMATCH")
                    total += len(pcm)
                    if total > STREAM_PCM_MAX_BYTES:
                        raise ValueError("STREAM_AUDIO_LIMIT")
                    yield struct.pack("!BH", 0x10, len(pcm)) + pcm
                if total == 0:
                    raise ValueError("STREAM_EMPTY_OUTPUT")
                # Explicit terminal frame is withheld whenever synthesis fails.
                yield struct.pack("!BH", 0, 8) + total.to_bytes(8, "big")
            except BaseException:
                failed = True
                raise
            finally:
                record_runtime("synthesize_stream", (time.monotonic() - started) * 1000, failed=failed)

    return StreamingResponse(body(), media_type="application/x-hamava-pcm-frames", headers={
        "Cache-Control": "no-store", "X-Audio-Format": "pcm_s16le",
        "X-Audio-Sample-Rate": "16000", "X-Audio-Channels": "1",
        "X-Content-Type-Options": "nosniff",
    })
