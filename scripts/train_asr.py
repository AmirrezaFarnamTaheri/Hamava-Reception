#!/usr/bin/env python3
"""Optional rights-gated Whisper fine-tuning adapter (Transformers 4.57.3).

No model downloads, training or publication occur in --validate-only mode.
Actual training needs reviewed weights, licensed eligible audio and local compute.
The supplied tone fixtures exercise plumbing and are not speech-training evidence.
"""
from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import platform
import re
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

try:
    from .dataset_curate import read_tombstones, revalidate_manifest, resolve_under, validate_rights, wav_info
    from .evaluate_speech import aggregate, sample_stats
    from .research_common import canonical_json, sha256, write_json
except ImportError:
    from dataset_curate import read_tombstones, revalidate_manifest, resolve_under, validate_rights, wav_info
    from evaluate_speech import aggregate, sample_stats
    from research_common import canonical_json, sha256, write_json


def training_code_hash():
    return sha256(Path(__file__).read_bytes())


class ExperimentBudget:
    """Stop at the declared wall-time/compute allowance, including evaluation."""
    def __init__(self, recipe, *, clock=time.monotonic):
        self.clock, self.started = clock, clock()
        self.seconds = recipe["max_wall_seconds"]
        self.rate = Decimal(recipe["compute_toman_per_hour"])
        self.limit = Decimal(recipe["max_compute_toman"])

    def check(self):
        elapsed = max(0, self.clock() - self.started)
        cost = Decimal(str(elapsed)) * self.rate / 3600
        if elapsed > self.seconds or cost > self.limit:
            raise ValueError("experiment_budget_exceeded_do_not_deploy")
        return {"elapsed_seconds": elapsed, "estimated_compute_toman": format(cost, "f"), "cost_basis": "measured_wall_time_at_declared_reviewed_rate"}


def validate_recipe(recipe: dict[str, Any], manifest_path: Path, *, tombstone_path: Path,
                    region: str, allow_synthetic: bool = False) -> tuple[dict[str, Any], dict[str, Any]]:
    if recipe.get("model_license_reviewed") is not True or not recipe.get("model_license_evidence"):
        raise ValueError("reviewed_model_license_evidence_required")
    if not isinstance(recipe.get("model_id"), str) or not recipe["model_id"]:
        raise ValueError("model_id_required")
    if not re.fullmatch(r"[0-9a-f]{40}", str(recipe.get("model_revision", ""))):
        raise ValueError("immutable_40_character_model_revision_required")
    if recipe.get("transformers_version") != "4.57.3":
        raise ValueError("adapter_requires_transformers_4_57_3")
    if recipe.get("training_code_sha256") != training_code_hash():
        raise ValueError("training_code_hash_must_match_reviewed_adapter")
    if isinstance(recipe.get("max_wall_seconds"), bool) or not isinstance(recipe.get("max_wall_seconds"), int) or not 1 <= recipe["max_wall_seconds"] <= 604800:
        raise ValueError("bounded_experiment_wall_budget_required")
    try:
        amounts = [Decimal(str(recipe.get(key))) for key in ("compute_toman_per_hour", "max_compute_toman")]
    except InvalidOperation as exc:
        raise ValueError("explicit_experiment_compute_budget_required") from exc
    if any(not amount.is_finite() or amount <= 0 for amount in amounts) or not recipe.get("compute_rate_evidence_reference"):
        raise ValueError("positive_reviewed_compute_rate_and_budget_required")
    rollback = recipe.get("rollback", {})
    if not isinstance(rollback, dict) or not rollback.get("model_id") or not re.fullmatch(r"[a-f0-9]{40}", str(rollback.get("model_revision", ""))) or not re.fullmatch(r"[a-f0-9]{64}", str(rollback.get("artifact_sha256", ""))) or not rollback.get("owner") or not rollback.get("evidence_reference"):
        raise ValueError("pinned_rollback_artifact_owner_and_evidence_required")
    for key, maximum in (("max_steps", 100000), ("batch_size", 32), ("gradient_accumulation", 128)):
        value = recipe.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
            raise ValueError(f"invalid_{key}")
    try:
        lr = float(recipe.get("learning_rate"))
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_learning_rate") from exc
    if not math.isfinite(lr) or not 0 < lr <= .01:
        raise ValueError("invalid_learning_rate")
    report = revalidate_manifest(manifest_path, tombstone_path=tombstone_path, region=region)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if any(sample.get("synthetic") is True for sample in manifest["samples"]) and not allow_synthetic:
        raise ValueError("synthetic_tones_are_not_real_training_data_use_explicit_smoke_test_mode")
    if any(report["split_counts"][name] < 1 for name in ("train", "validation", "test")):
        raise ValueError("all_three_disjoint_splits_required")
    report.update({"recipe_sha256": sha256(canonical_json(recipe)), "weights_downloaded": False,
                   "training_code_sha256": training_code_hash(), "max_wall_seconds": recipe["max_wall_seconds"],
                   "max_compute_toman": str(recipe["max_compute_toman"]), "rollback_verified_for_presence_only": True,
                   "trained": False, "license_evidence_verified_only_for_presence": True,
                   "synthetic_smoke_test": any(s.get("synthetic") is True for s in manifest["samples"])})
    return report, manifest


def train(recipe: dict[str, Any], manifest_path: Path, output_dir: Path, *, tombstone_path: Path,
          region: str, allow_synthetic: bool = False, allow_download: bool = False) -> dict[str, Any]:
    report, manifest = validate_recipe(recipe, manifest_path, tombstone_path=tombstone_path,
                                       region=region, allow_synthetic=allow_synthetic)
    budget = ExperimentBudget(recipe)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError("training_output_must_be_new_or_empty")
    try:
        installed = importlib.metadata.version("transformers")
    except importlib.metadata.PackageNotFoundError as exc:
        raise ValueError("optional_training_dependencies_not_installed") from exc
    if installed != "4.57.3":
        raise ValueError("installed_transformers_version_does_not_match_recipe")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    import numpy as np
    import torch
    from scipy.signal import resample_poly
    from transformers import (Seq2SeqTrainer, Seq2SeqTrainingArguments, TrainerCallback,
                              WhisperForConditionalGeneration, WhisperProcessor)

    output_dir.mkdir(parents=True, exist_ok=True)
    model_kwargs = {"revision": recipe["model_revision"], "local_files_only": not allow_download,
                    "trust_remote_code": False}
    processor = WhisperProcessor.from_pretrained(recipe["model_id"], language="persian", task="transcribe", **model_kwargs)
    model = WhisperForConditionalGeneration.from_pretrained(recipe["model_id"], **model_kwargs)
    budget.check()
    model.generation_config.language = "persian"
    model.generation_config.task = "transcribe"
    model.generation_config.forced_decoder_ids = None
    model.config.use_cache = False

    class AudioDataset(torch.utils.data.Dataset):
        def __init__(self, split: str):
            self.samples = [sample for sample in manifest["samples"] if sample["split"] == split]

        def __len__(self) -> int:
            return len(self.samples)

        def __getitem__(self, index: int) -> dict[str, Any]:
            sample = self.samples[index]
            # Re-check withdrawal/expiry before each queued sample is read.
            validate_rights(sample, now=datetime.now(timezone.utc), region=region,
                            tombstones=read_tombstones(tombstone_path))
            blob = resolve_under(manifest_path.parent, sample["audio_path"]).read_bytes()
            if sha256(blob) != sample["audio_sha256"]:
                raise ValueError("training_audio_changed_after_freeze")
            info = wav_info(blob)
            if info["channels"] != 1 or info["bits"] != 16:
                raise ValueError("training_adapter_requires_mono_16_bit_pcm")
            audio = np.frombuffer(blob[info["data_offset"]:info["data_offset"] + info["data_bytes"]], dtype="<i2").astype(np.float32) / 32768.0
            if info["sample_rate"] != 16000:
                divisor = math.gcd(info["sample_rate"], 16000)
                audio = resample_poly(audio, 16000 // divisor, info["sample_rate"] // divisor).astype(np.float32)
            features = processor.feature_extractor(audio, sampling_rate=16000).input_features[0]
            labels = processor.tokenizer(sample["transcript"]).input_ids
            if not labels or len(labels) > model.config.max_target_positions:
                raise ValueError("training_transcript_exceeds_model_target_length")
            return {"input_features": features, "labels": labels}

    def collate(rows: list[dict[str, Any]]) -> dict[str, Any]:
        batch = processor.feature_extractor.pad([{"input_features": row["input_features"]} for row in rows], return_tensors="pt")
        padded = processor.tokenizer.pad([{"input_ids": row["labels"]} for row in rows], return_tensors="pt")
        labels = padded["input_ids"].masked_fill(padded.attention_mask.ne(1), -100)
        if (labels[:, 0] == model.config.decoder_start_token_id).all().cpu().item():
            labels = labels[:, 1:]
        batch["labels"] = labels
        return batch

    def metrics(prediction: Any) -> dict[str, float]:
        predicted_ids = prediction.predictions[0] if isinstance(prediction.predictions, tuple) else prediction.predictions
        label_ids = np.where(prediction.label_ids == -100, processor.tokenizer.pad_token_id, prediction.label_ids)
        hypotheses = processor.tokenizer.batch_decode(predicted_ids, skip_special_tokens=True)
        references = processor.tokenizer.batch_decode(label_ids, skip_special_tokens=True)
        result = aggregate([sample_stats({"reference": ref, "hypothesis": hyp}) for ref, hyp in zip(references, hypotheses)])
        return {key: value for key, value in {"wer": result["normalized_wer"], "cer": result["normalized_cer"],
                                             "exact_number_accuracy": result["exact_number_accuracy"]["rate"]}.items() if value is not None}

    class RightsCallback(TrainerCallback):
        def on_step_begin(self, args: Any, state: Any, control: Any, **kwargs: Any) -> None:
            budget.check()
            revoked = read_tombstones(tombstone_path)
            now = datetime.now(timezone.utc)
            for sample in manifest["samples"]:
                validate_rights(sample, now=now, region=region, tombstones=revoked)

        def on_prediction_step(self, args: Any, state: Any, control: Any, **kwargs: Any) -> None:
            budget.check()

    interval = max(1, min(100, recipe["max_steps"] // 5))
    args = Seq2SeqTrainingArguments(
        output_dir=str(output_dir), max_steps=recipe["max_steps"],
        per_device_train_batch_size=recipe["batch_size"], per_device_eval_batch_size=recipe["batch_size"],
        gradient_accumulation_steps=recipe["gradient_accumulation"], learning_rate=float(recipe["learning_rate"]),
        eval_strategy="steps", eval_steps=interval, save_strategy="steps", save_steps=interval,
        logging_steps=interval, save_total_limit=2, predict_with_generate=True,
        generation_max_length=225, load_best_model_at_end=True, metric_for_best_model="wer", greater_is_better=False,
        remove_unused_columns=False, report_to=[], push_to_hub=False, seed=int(recipe.get("seed", 42)),
        dataloader_num_workers=0, use_cpu=recipe.get("use_cpu", False), fp16=False, bf16=False,
        gradient_checkpointing=True, optim="adamw_torch",
    )
    trainer = Seq2SeqTrainer(model=model, args=args, train_dataset=AudioDataset("train"),
                            eval_dataset=AudioDataset("validation"), data_collator=collate,
                            processing_class=processor.feature_extractor, compute_metrics=metrics,
                            callbacks=[RightsCallback()])
    try:
        baseline = trainer.evaluate(metric_key_prefix="baseline_validation")
        trainer.train()
        validation = trainer.evaluate(metric_key_prefix="trained_validation")
        # Test set is used once for final reporting, never checkpoint selection.
        heldout = trainer.evaluate(eval_dataset=AudioDataset("test"), metric_key_prefix="heldout_test")
        measured_budget = budget.check()
        revalidate_manifest(manifest_path, tombstone_path=tombstone_path, region=region)
        trainer.save_model(str(output_dir / "model"))
        processor.save_pretrained(str(output_dir / "model"))
    except Exception:
        write_json({"status": "aborted_do_not_deploy", "trained_artifacts_require_review": True}, output_dir / "status.json")
        raise
    report.update({"trained": True, "published": False, "model_download_allowed": allow_download,
                   "compute_budget": measured_budget, "rollback": recipe["rollback"],
                   "baseline_validation": baseline, "trained_validation": validation, "heldout_test": heldout,
                   "python_version": platform.python_version(),
                   "dependency_versions": {name: importlib.metadata.version(name) for name in ("transformers", "torch", "accelerate", "numpy", "scipy")},
                   "promotion": "requires_independent_native_review_cost_and_nonregression_evidence"})
    write_json(recipe, output_dir / "recipe.json")
    write_json(report, output_dir / "training-report.json")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--recipe", type=Path, required=True)
    parser.add_argument("--tombstones", type=Path, required=True)
    parser.add_argument("--region", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--allow-synthetic-smoke-test", action="store_true")
    parser.add_argument("--allow-model-download", action="store_true")
    args = parser.parse_args()
    try:
        recipe = json.loads(args.recipe.read_text(encoding="utf-8"))
        if args.validate_only:
            report, _ = validate_recipe(recipe, args.manifest, tombstone_path=args.tombstones,
                                         region=args.region, allow_synthetic=args.allow_synthetic_smoke_test)
        else:
            if args.output is None:
                raise ValueError("training_output_required")
            report = train(recipe, args.manifest, args.output, tombstone_path=args.tombstones,
                           region=args.region, allow_synthetic=args.allow_synthetic_smoke_test,
                           allow_download=args.allow_model_download)
        write_json(report)
    except Exception as exc:
        # Third-party exceptions may contain paths or transcripts: never print them.
        reason = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r"[a-z0-9_]+", str(exc)) else "training_or_input_failure_see_local_operator"
        parser.exit(2, f"Training refused or stopped: {reason}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
