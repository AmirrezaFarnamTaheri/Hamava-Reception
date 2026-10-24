#!/usr/bin/env python3
"""Generate explicitly synthetic, non-speech research plumbing fixtures."""
from __future__ import annotations

import argparse
import io
import json
import math
import struct
import wave
from pathlib import Path

try:
    from .dataset_curate import redact_wav_bytes
    from .research_common import sha256, write_json
except ImportError:
    from dataset_curate import redact_wav_bytes
    from research_common import sha256, write_json


def tone_bytes(frequency: int, *, rate: int = 8000, channels: int = 1, seconds: int = 3) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(channels)
        audio.setsampwidth(2)
        audio.setframerate(rate)
        frames = b"".join(struct.pack("<h", int(1000 * math.sin(2 * math.pi * frequency * i / rate))) * channels
                          for i in range(rate * seconds))
        audio.writeframes(frames)
    return buffer.getvalue()


def make_fixtures(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "audio").mkdir(exist_ok=True)
    manifest = []
    for index in range(6):
        blob = tone_bytes(300 + index * 73)
        filename = f"audio/synthetic-tone-{index + 1}.wav"
        (root / filename).write_bytes(blob)
        spans = [[1000, 1200]]
        redacted, _ = redact_wav_bytes(blob, spans)
        transcript = "این برچسب مصنوعی برای آزمون نرم‌افزار است و صدای گفتار ندارد"
        manifest.append({"sample_id": f"synthetic_{index + 1}", "speaker_id": f"fictional_speaker_{index + 1}",
                         "tenant_id": f"fictional_tenant_{index + 1}", "synthetic": True,
                         "audio_path": filename, "source_sha256": sha256(blob), "redaction_spans_ms": spans,
                         "transcript": transcript, "recorded_at": "2026-01-01T00:00:00+00:00",
                         "rights": {"recording": True, "training": True, "clinic_authorized": True,
                                    "license_id": "synthetic-fixture-only-not-clinic-consent",
                                    "consent_version": "synthetic-no-human-speaker-v1",
                                    "consent_evidence_sha256": sha256(b"synthetic tones; no human speaker or actual consent assertion"),
                                    "allowed_regions": ["local-test"], "expires_at": "2099-01-01T00:00:00+00:00"},
                         "privacy_review": {"approved": True, "reviewer": "synthetic-fixture-generator-not-real-human-review",
                                            "approved_at": "2026-01-02T00:00:00+00:00", "audio_sha256": sha256(redacted),
                                            "transcript_sha256": sha256(transcript.encode("utf-8"))}})
    (root / "manifest-input.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in manifest) + "\n", encoding="utf-8")
    write_json({"sample_ids": [], "speaker_ids": [], "tenant_ids": []}, root / "withdrawals.json")
    speech = [
        ("سلام وقت بخیر", "سلام وقت بخیر"), ("فردا ساعت چهار و نیم", "فردا ساعت پنج و نیم"),
        ("کد نمونه ۰۱۲۳", "کد نمونه 0123"), ("کد نمونه ۱۲۳", "کد نمونه ۱۲۴"),
        ("سه‌شنبه هفته دیگه", "سه شنبه هفته دیگه"), ("برای پذیرش تماس گرفتم", "برای پذیرش تماس گرفتم"),
        ("", "سلام"), ("", ""), ("يک نمونهٔ آزمایشی", "یک نمونه آزمایشی"),
        ("دوباره تکرار کنید", "دوباره تکرار کنید"), ("ساعت پنج و ربع", "ساعت پنج و ربع"),
        ("نوبت هنوز تأیید نشده", "نوبت تایید شد")
    ]
    rows = []
    for index, (reference, hypothesis) in enumerate(speech):
        rows.append({"id": f"evaluation_{index + 1}", "reference": reference, "hypothesis": hypothesis,
                     "speaker_id": f"fictional_eval_speaker_{index % 4}", "tenant_id": f"fictional_eval_tenant_{index % 2}",
                     "split": "test", "synthetic": True, "slices": {"channel": "synthetic_text", "case": "number" if index in (2, 3) else "dialogue"},
                     "latency_ms": 300 + index * 25, "eligible": True, "task_completed": index not in (1, 3, 6, 11),
                     "confirmed_claim": index == 11, "authoritative_confirmed": False if index == 11 else None})
    (root / "speech-predictions.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    costs = [
        {"id": "stt", "category": "stt", "quantity": "165000", "quantity_unit": "seconds", "rate": "0.12", "rate_unit": "hours", "currency": "USD"},
        {"id": "model_input", "category": "llm", "quantity": "3000000", "quantity_unit": "tokens", "rate": "0.20", "rate_unit": "million_tokens", "currency": "USD"},
        {"id": "tts", "category": "tts", "quantity": "1200", "quantity_unit": "minutes", "rate": "0.02", "rate_unit": "minutes", "currency": "USD"},
        {"id": "carrier", "category": "carrier", "quantity": "2750", "quantity_unit": "minutes", "rate": "1000", "rate_unit": "minutes", "currency": "IRR"},
        {"id": "sms", "category": "sms", "quantity": "800", "quantity_unit": "messages", "rate": "200", "rate_unit": "messages", "currency": "TOMAN"},
        {"id": "human", "category": "human", "quantity": "300", "quantity_unit": "minutes", "rate": "100000", "rate_unit": "hours", "currency": "TOMAN"},
        {"id": "compute", "category": "compute", "quantity": "1", "quantity_unit": "months", "rate": "1000000", "rate_unit": "months", "currency": "TOMAN"},
    ]
    config = {"period": "synthetic-month-no-current-price-claim", "fx_toman_per_usd": "100000", "invoice_tax_rate": "0.10",
              "cost_items": costs, "revenue_items": [{"id": "platform", "category": "platform", "quantity": "1", "quantity_unit": "months", "rate": "7000000", "rate_unit": "months", "currency": "TOMAN"}],
              "outcomes": {"calls": 1000, "booked": 120, "matured_bookings": 100, "kept": 70, "baseline_kept": 58,
                           "contribution_per_kept_toman": "600000", "observed_avoidable_staff_value_toman": "0", "extra_supervision_rework_toman": "300000"},
              "scenarios": [{"name": "FX +30% (hypothetical)", "fx_multiplier": "1.3"},
                            {"name": "Human escalation doubles (hypothetical)", "cost_quantity_multipliers": {"human": "2"}}]}
    write_json(config, root / "economics-input.json")
    pilot = []
    for period in ("baseline", "pilot"):
        for stratum in ("weekday_after_hours", "weekend_overflow"):
            for cohort in range(3):
                pilot.append({"cohort_id": f"{period}_{stratum}_{cohort}", "stratum": stratum, "period": period,
                              "attempts": 50, "answered": 35 if period == "baseline" else 46, "eligible_requests": 30,
                              "confirmed_bookings": 12 if period == "baseline" else 15,
                              "matured_bookings": 12 if period == "baseline" else 15,
                              "kept": 8 if period == "baseline" else 10, "cohort_complete": True, "severe_incidents": 0,
                              "handoff_requested": 5, "handoff_connected": 4, "synthetic": True})
    (root / "pilot-cohorts.jsonl").write_text("\n".join(json.dumps(row) for row in pilot) + "\n", encoding="utf-8")
    write_json({"model_id": "REPLACE_WITH_APPROVED_WHISPER_MODEL", "model_revision": "REPLACE_WITH_40_CHARACTER_COMMIT_HASH",
                "model_license_reviewed": False, "model_license_evidence": "", "transformers_version": "4.57.3",
                "max_steps": 100, "batch_size": 1, "gradient_accumulation": 4, "learning_rate": "0.00001", "seed": 42}, root / "training-recipe.template.json")
    (root / "README.md").write_text("# Synthetic research fixtures\n\nThese are deterministic non-speech tones and fictional text/count/price inputs. They contain no real caller, clinic, consent, acoustic benchmark, market quote or clinical outcome. Consent and review fields are clearly fictional plumbing fixtures. The text is not a transcription of the tones. Do not use these fixtures as evidence of Persian ASR accuracy or model improvement. The training adapter refuses synthetic data unless explicitly placed in smoke-test mode.\n\nGenerate a fresh copy with `python scripts/make_synthetic_fixtures.py /tmp/new-synthetic-fixtures`. The destination must be new or empty; the command refuses to overwrite an existing fixture directory.\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.exists() and any(args.output.iterdir()):
        parser.exit(2, "Refusing to overwrite a nonempty fixture directory. Use a new directory.\n")
    make_fixtures(args.output)
    print("Synthetic fixtures created; no speech quality or real consent evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
