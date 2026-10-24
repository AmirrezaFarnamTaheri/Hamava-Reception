#!/usr/bin/env python3
"""Rights-gated two-track PCM capture manifest and candidate segmentation.

Track roles come from the transport, not biometric diarization. Energy VAD
creates review candidates; it does not identify speech, restore bandwidth or
approve transcripts. Candidate manifests cannot pass dataset freeze until an
independent human supplies reviewed transcript and content-hash evidence.
"""
from __future__ import annotations

import argparse
from array import array
from datetime import datetime, timezone
import io
import json
import math
from pathlib import Path
import sys
import wave

try:
    from .dataset_curate import HASH_RE, ID_RE, read_tombstones, resolve_under, utc
    from .research_common import sha256, write_json
except ImportError:
    from dataset_curate import HASH_RE, ID_RE, read_tombstones, resolve_under, utc
    from research_common import sha256, write_json


def capture_rights(record, region, tombstones, now):
    for key in ("sample_id", "speaker_id", "tenant_id"):
        if not ID_RE.fullmatch(str(record.get(key, ""))) or record[key] in tombstones[key + "s"]:
            raise ValueError("capture_identity_or_withdrawal_invalid")
    rights = record.get("rights", {})
    if any(rights.get(key) is not True for key in ("recording", "training", "clinic_authorized")):
        raise ValueError("capture_independent_recording_training_clinic_rights_required")
    if not rights.get("license_id") or not rights.get("consent_version") or not HASH_RE.fullmatch(str(rights.get("consent_evidence_sha256", ""))):
        raise ValueError("capture_license_and_consent_evidence_required")
    if region not in rights.get("allowed_regions", []) or utc(rights.get("expires_at")) <= now:
        raise ValueError("capture_region_or_expiry_not_permitted")
    recorded = utc(record.get("recorded_at"))
    if recorded > now or recorded >= utc(rights["expires_at"]):
        raise ValueError("capture_collection_time_invalid")
    if not record.get("transport_role_evidence_reference") or not record.get("agent_voice_license_reference"):
        raise ValueError("transport_role_and_agent_voice_rights_evidence_required")


def pcm_track(root, spec):
    if not isinstance(spec, dict) or set(spec) != {"path", "sha256", "offset_ms", "codec"}:
        raise ValueError("explicit_track_path_hash_offset_codec_required")
    path = resolve_under(root, spec["path"])
    if path.stat().st_size > 180_000_000:
        raise ValueError("capture_track_too_large")
    blob = path.read_bytes()
    if sha256(blob) != spec["sha256"]:
        raise ValueError("capture_source_hash_mismatch")
    if spec["codec"] != "pcm_s16le" or isinstance(spec["offset_ms"], bool) or not isinstance(spec["offset_ms"], int) or not 0 <= spec["offset_ms"] <= 30000:
        raise ValueError("capture_track_metadata_invalid")
    try:
        with wave.open(io.BytesIO(blob), "rb") as source:
            rate, frames = source.getframerate(), source.getnframes()
            if source.getnchannels() != 1 or source.getsampwidth() != 2 or source.getcomptype() != "NONE" or rate not in {8000, 16000, 24000, 48000} or not 0 < frames <= 1800 * rate:
                raise ValueError("capture_requires_bounded_separate_mono_pcm_tracks")
            data = source.readframes(frames)
            if len(data) != frames * 2:
                raise ValueError("capture_pcm_truncated")
    except (wave.Error, EOFError) as exc:
        raise ValueError("capture_wav_invalid") from exc
    samples = array("h")
    samples.frombytes(data)
    if sys.byteorder != "little":
        samples.byteswap()
    return {"samples": samples, "pcm": data, "sample_rate": rate, "frames": frames,
        "source_sha256": spec["sha256"], "offset_ms": spec["offset_ms"], "codec": "pcm_s16le"}


def energy_activity(track):
    size = track["sample_rate"] // 50
    samples = track["samples"]
    energies = [math.sqrt(sum(value * value for value in samples[i:i + size]) / len(samples[i:i + size])) for i in range(0, len(samples), size)]
    ordered = sorted(energies)
    noise_floor = ordered[max(0, int(len(ordered) * .2) - 1)]
    # A stationary all-tone track has no reliable noise-only interval; use a
    # bounded threshold and flag the proxy, never infer true SNR.
    threshold = max(150.0, min(1200.0, noise_floor * 3))
    return {"active": [value >= threshold for value in energies], "energies": energies, "noise_floor_rms": noise_floor, "threshold_rms": threshold}


def candidate_intervals(active, *, minimum_ms=3000, maximum_ms=15000):
    if minimum_ms != 3000 or maximum_ms != 15000:
        raise ValueError("candidate_bounds_are_3_to_15_seconds")
    # Bridge <=300ms internal silence and keep at most200ms surrounding context.
    runs, first, last = [], None, None
    for index, voiced in enumerate(active):
        if voiced:
            if first is None:
                first = index
            last = index
        elif first is not None and index - last > 15:
            runs.append((max(0, first - 10), min(len(active), last + 11)))
            first = last = None
    if first is not None:
        runs.append((max(0, first - 10), min(len(active), last + 11)))
    result = []
    for start, end in runs:
        cursor = start
        while end - cursor >= minimum_ms // 20:
            stop = min(end, cursor + maximum_ms // 20)
            # Avoid a tiny remainder by dividing the last <=18s into two >=3s.
            if 0 < end - stop < minimum_ms // 20 and end - cursor > maximum_ms // 20:
                stop = end - minimum_ms // 20
            result.append((cursor * 20, stop * 20))
            cursor = stop
    return result


def wave_bytes(track, start_ms, end_ms):
    rate = track["sample_rate"]
    first, last = start_ms * rate // 1000, min(track["frames"], end_ms * rate // 1000)
    stream = io.BytesIO()
    with wave.open(stream, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(rate)
        target.writeframes(track["pcm"][first * 2:last * 2])
    return stream.getvalue(), first, last


def segment_record(record, input_root: Path, output: Path, *, tombstone_path: Path, region: str):
    capture_rights(record, region, read_tombstones(tombstone_path), datetime.now(timezone.utc))
    if set(record.get("tracks", {})) != {"caller", "agent"}:
        raise ValueError("both_separate_caller_and_agent_tracks_required")
    # All rights and both source hashes are checked before any output is made.
    tracks = {role: pcm_track(input_root, spec) for role, spec in record["tracks"].items()}
    if tracks["caller"]["source_sha256"] == tracks["agent"]["source_sha256"]:
        raise ValueError("identical_tracks_cannot_prove_separate_capture")
    if output.exists() and any(output.iterdir()):
        raise ValueError("candidate_output_must_be_new_or_empty")
    activity = {role: energy_activity(track) for role, track in tracks.items()}
    candidates = []
    for role, track in tracks.items():
        other_role = "agent" if role == "caller" else "caller"
        other = tracks[other_role]
        for sequence, (start_ms, end_ms) in enumerate(candidate_intervals(activity[role]["active"])):
            blob, first, last = wave_bytes(track, start_ms, end_ms)
            if (last - first) / track["sample_rate"] < 3:
                continue
            absolute_start = start_ms + track["offset_ms"]
            absolute_end = end_ms + track["offset_ms"]
            overlap = 0
            for time_ms in range(absolute_start, absolute_end, 20):
                own_index = (time_ms - track["offset_ms"]) // 20
                other_index = (time_ms - other["offset_ms"]) // 20
                if 0 <= own_index < len(activity[role]["active"]) and activity[role]["active"][own_index] and 0 <= other_index < len(activity[other_role]["active"]) and activity[other_role]["active"][other_index]:
                    overlap += 20
            samples = track["samples"][first:last]
            clipping = sum(abs(value) >= 32760 for value in samples) / len(samples)
            rms = math.sqrt(sum(value * value for value in samples) / len(samples))
            floor = activity[role]["noise_floor_rms"]
            ratio = 20 * math.log10(rms / floor) if rms > 0 and floor > 0 else None
            sample_id = f"{record['sample_id']}-{role}-{sequence + 1}"
            if not ID_RE.fullmatch(sample_id):
                raise ValueError("derived_sample_id_exceeds_limit")
            candidates.append({"sample_id": sample_id, "tenant_id": record["tenant_id"],
                "speaker_id": record["speaker_id"] if role == "caller" else record.get("agent_speaker_id", "agent_transport_voice"),
                "role": role, "audio_path": sample_id + ".wav", "audio_sha256": sha256(blob), "transcript": "",
                "recorded_at": record["recorded_at"], "rights": record["rights"], "synthetic": record.get("synthetic", False),
                "privacy_review": {"approved": False, "reason": "candidate_requires_independent_transcript_audio_and_privacy_review"},
                "capture": {"source_audio_sha256": track["source_sha256"], "source_frames": track["frames"],
                    "frame_start": first, "frame_end": last, "sample_rate": track["sample_rate"], "codec": track["codec"],
                    "absolute_start_ms": absolute_start, "absolute_end_ms": absolute_end,
                    "role_evidence_reference": record["transport_role_evidence_reference"]},
                "quality": {"duration_seconds": (last - first) / track["sample_rate"], "overlap_fraction": overlap / (end_ms - start_ms),
                    "clipping_fraction": clipping, "rms": rms, "stationary_noise_ratio_proxy_db": ratio,
                    "flags": [flag for condition, flag in ((overlap > 0, "overlap_requires_review"), (clipping > .005, "clipping"),
                        (rms < 200, "low_level"), (ratio is not None and ratio < 6, "stationary_or_noisy_requires_review")) if condition]},
                "_audio": blob})
    # Revalidate revocations immediately before copying derived data.
    capture_rights(record, region, read_tombstones(tombstone_path), datetime.now(timezone.utc))
    output.mkdir(parents=True, exist_ok=True)
    for sample in candidates:
        blob = sample.pop("_audio")
        with (output / sample["audio_path"]).open("xb") as target:
            target.write(blob)
    with (output / "candidates.jsonl").open("x", encoding="utf-8") as target:
        for sample in candidates:
            target.write(json.dumps(sample, ensure_ascii=False, sort_keys=True) + "\n")
    summary = {"schema_version": "1.0", "candidates": len(candidates), "tracks": 2,
        "source_hashes_verified": True, "human_review_complete": False, "training_eligible": False,
        "vad": "bounded_energy_heuristic_20ms", "role_source": "declared_transport_tracks",
        "speaker_biometrics_used": False, "narrowband_restoration": False,
        "overlap_candidates": sum(sample["quality"]["overlap_fraction"] > 0 for sample in candidates)}
    write_json(summary, output / "capture-report.json")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--input-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--tombstones", type=Path, required=True)
    parser.add_argument("--region", required=True)
    args = parser.parse_args()
    try:
        result = segment_record(json.loads(args.record.read_text(encoding="utf-8")), args.input_root, args.output,
            tombstone_path=args.tombstones, region=args.region)
        write_json(result)
    except (ValueError, OSError) as exc:
        reason = str(exc) if isinstance(exc, ValueError) and all(c.islower() or c == "_" or c.isdigit() for c in str(exc)) else "capture_input_or_output_failure"
        parser.exit(2, reason + "\n")


if __name__ == "__main__":
    main()
