# Controlled research and local-serving workflow

This extension supplies executable preparation, evaluation and measurement tools. It does not supply a patient corpus, approved model weights, a completed training experiment, representative Persian telephone accuracy, or an economic result from a live clinic. The bundled tones and fictional transcripts are plumbing fixtures only.

Run these commands from the repository root after activating the environment described in `README.md`. The examples use `python` from that environment. Keep real captures, consent documents and keys in the operator's approved private storage; source-control examples contain no real caller data.

## 1. Preserve capture provenance before segmenting

`scripts/capture_segment.py` accepts a JSON record describing two separately captured mono PCM tracks. Caller/agent identity comes from the transport channel assignment; the tool does not identify people from their voices or infer diarization from a mixed recording.

The record has the following fields:

| Field | Meaning and validation |
|---|---|
| `sample_id`, `speaker_id`, `tenant_id` | Opaque identifiers checked against current sample, speaker and clinic withdrawal tombstones. |
| `recorded_at` | Timezone-aware actual collection time, not a future time or one beyond the recorded permission expiry. |
| `synthetic` | Explicit fixture marker. It never makes fictional permissions suitable for real data. |
| `transport_role_evidence_reference` | The operator's evidence for caller/agent track assignment. |
| `agent_voice_license_reference` | Evidence for the rights associated with the separate agent voice. |
| `rights` | Independently affirmative `recording`, `training`, `clinic_authorized`; `license_id`, `consent_version`, `consent_evidence_sha256`, `allowed_regions`, and timezone-aware `expires_at`. |
| `tracks.caller`, `tracks.agent` | Each contains exactly `path`, `sha256`, `offset_ms`, and `codec: "pcm_s16le"`. Paths stay inside the supplied input root. Offsets are nonnegative milliseconds up to 30 seconds. |

The tool checks permission/withdrawal eligibility before reading or copying source audio. It verifies both file hashes and PCM structure, rejects identical source tracks, and preserves the original sample rate and frame coordinates. Supported input rates are 8, 16, 24 and 48 kHz; tracks are bounded to 30 minutes. A second withdrawal check occurs immediately before derived files are copied.

```bash
python scripts/capture_segment.py /approved/capture-record.json \
  --input-root /approved/capture-audio \
  --output /approved/candidates-new \
  --tombstones /approved/withdrawals.json \
  --region IR
```

The destination must be new or empty. Outputs are `candidates.jsonl`, individual WAV clips, and `capture-report.json`. The manifest includes original track hashes, sample rate, codec, absolute offsets, source frame boundaries and derived hashes. A 20 ms energy heuristic generates 3–15 second candidates; exact PCM frames within each selected interval are copied without enhancement or resampling.

The candidate flags include observed track overlap, clipping, low level, and a stationary-noise ratio proxy. These are review cues. They do not certify intelligibility, identify all speech, distinguish every noise source, or restore information lost by a narrowband connection. Candidate transcripts are empty, privacy review is false, and the report explicitly says training eligibility is false.

## 2. Human review, withdrawal, freeze and split integrity

Use the existing `docs/research-workflow.md` for the complete manifest schema and redaction procedure. A qualified reviewer must establish the actual transcript, segment suitability, privacy redactions, rights and license evidence before a candidate can pass a dataset freeze. Source and derived audio hashes make a reviewed object distinguishable from a later edit.

```bash
python scripts/dataset_curate.py freeze /approved/reviewed-input.jsonl \
  /approved/frozen-new \
  --tombstones /approved/withdrawals.json \
  --region IR

python scripts/dataset_curate.py revalidate /approved/frozen-new/manifest.json \
  --tombstones /approved/withdrawals.json \
  --region IR
```

Freeze checks exact audio hashes, consent and license metadata, recording/training eligibility, privacy review, and duplicate content. It creates connected groups so shared speakers and clinics cannot appear across train, validation and test partitions. This intentionally prevents apparent gains obtained by leaking speakers or clinics into evaluation data. A small connected collection may not produce all three partitions; add independently eligible data rather than override the separation.

Withdrawal tombstones exclude matching samples, speakers or clinics. Revalidation is required after a withdrawal and before use. The training adapter checks current tombstones and each source hash while loading samples; a previously frozen dataset is not permanent permission. Retained backups still need the documented retention and withdrawal handling outside the frozen manifest.

WAV span redaction operates on reviewed intervals and preserves out-of-scope bytes. It does not identify sensitive content automatically. Keep the redaction evidence with the manifest. None of these metadata checks independently authenticates a signed consent document or determines whether a particular use is lawful.

## 2A. Compare independent teacher outputs and require human adjudication

`scripts/teacher_labels.py` provides an offline QA and relabeling step for an eligible frozen dataset. It accepts already obtained hypotheses from two to five teacher systems, compares them, and validates a separately completed human review artifact. It makes no provider requests, loads no models, copies no audio, and does not alter or promote a dataset. A raw capture candidate with incomplete privacy/rights review cannot bypass the existing freeze gates through this tool.

The frozen manifest is revalidated against current withdrawals, processing region, rights expiry, privacy review, source hashes and speaker/clinic split integrity before any teacher file is read. Each invocation is bounded to 500 samples, five teachers, 16 MB per JSON input, and 2,000 characters/256 normalized words per hypothesis. Use separate properly frozen review batches for larger collections; preserve the original split assignment and provenance when preparing them.

Each teacher file has exactly this structure. The placeholders and false attestation below deliberately fail validation; replace them with actual reviewed evidence rather than copying fictional approvals:

```json
{
  "schema_version": "1.0",
  "manifest_sha256": "REPLACE_WITH_FROZEN_MANIFEST_CHECKSUM",
  "generated_at": "ACTUAL_TIME_WITH_TIMEZONE",
  "teacher": {
    "id": "teacher_a",
    "system": "provider/model_family_a",
    "revision": "immutable_revision",
    "independence_group": "independent_system_family_a",
    "processing_region": "IR",
    "approval": {
      "reviewer_id": "authorized_reviewer_reference",
      "independence_attested": false,
      "license_evidence_sha256": "REPLACE_WITH_EVIDENCE_HASH",
      "processing_evidence_sha256": "REPLACE_WITH_EVIDENCE_HASH",
      "issued_at": "ACTUAL_TIME_WITH_TIMEZONE",
      "expires_at": "ACTUAL_TIME_WITH_TIMEZONE"
    }
  },
  "outputs": [
    {
      "sample_id": "existing_opaque_sample_id",
      "audio_sha256": "EXACT_REVIEWED_AUDIO_HASH_FROM_MANIFEST",
      "text": "A locally held teacher hypothesis"
    }
  ]
}
```

Teacher IDs, system/revision pairs and declared independence groups must differ across files. Approval timestamps must cover both the actual generation time and the present review; the declared processing region must match the reviewed manifest. A distinct filename, account or provider label does not prove that two systems are statistically independent. The approval references and independence declaration remain accountable human attestations; code checks their presence, scope and integrity rather than authenticating their legal or scientific sufficiency.

Unknown/duplicate sample IDs, changed audio hashes, extra schema fields, duplicate JSON keys and out-of-range text are rejected. Omitted hypotheses remain explicitly missing. They are neither an agreement nor an error-free recognition result.

```bash
python scripts/teacher_labels.py compare /approved/frozen/manifest.json \
  --teacher /approved/teacher-a.json \
  --teacher /approved/teacher-b.json \
  --tombstones /approved/withdrawals.json \
  --region IR \
  --output /approved/teacher-review-new
```

The output directory must not exist. It is created with private permissions and contains:

- `comparison.json`: source/artifact hashes, pseudonymous sample references, teacher coverage, missing-output counts, exact/normalized agreement, digit-group agreement and pairwise word edit distances. The symmetric distance divides by the longer hypothesis; it is not WER against a reference. Every sample remains marked as requiring human adjudication, including samples on which every teacher agrees.
- `adjudication-template.json`: the pinned comparison checksum, manifest checksum, audio and teacher-evidence bindings, and an explicit pending decision for every sample. It contains no copied hypothesis or audio.

Reports and stdout do not include raw transcripts, sample IDs or reviewer identity. `manifest_sample_index` is a zero-based index into the pinned manifest and lets an authorized reviewer locate the original private sample; `sample_ref` is the SHA-256 of the canonical JSON array `[manifest_sha256, sample_id]`. Teacher references identify their bound artifact metadata and file hashes. Keep the original hypotheses and recordings in approved private storage for the actual review.

Copy the generated template into a separate private human-review file. Fill the `reviewer` object with an opaque reviewer ID, true `human_review` and `independent_review` attestations, and the qualification/authority evidence hashes. For **every** sample, retain its exact sample/audio/teacher bindings and record a timezone-aware `reviewed_at` at or after the comparison was created. Choose one decision:

| Decision | Required contents |
|---|---|
| `accept` | Nonempty reviewed transcript, its exact UTF-8 SHA-256, true `listened_to_audio` and `privacy_reviewed`, privacy evidence hash, and reason `listened_confirmed` or `listened_corrected`. |
| `exclude` | No transcript or transcript hash; reason `unintelligible`, `overlap`, `sensitive_content`, `wrong_audio` or `insufficient_evidence`; explicit boolean review attestations. |

The default pending template cannot pass. Missing or duplicate decisions, stale teacher output, changed comparison metadata, mismatched transcript hashes, unreviewed acceptance, future review times and withdrawal all fail closed.

```bash
python scripts/teacher_labels.py validate-adjudication /approved/frozen/manifest.json \
  --teacher /approved/teacher-a.json \
  --teacher /approved/teacher-b.json \
  --comparison /approved/teacher-review-new/comparison.json \
  --adjudication /approved/teacher-review-new/human-review.json \
  --tombstones /approved/withdrawals.json \
  --region IR \
  --output /approved/teacher-review-new/adjudication-validation.json
```

Supply teacher files in the same order used for comparison. All original input bytes and current eligibility are checked again before a review package is published or adjudication succeeds. Validation output contains only decision counts, hashes, opaque references and limitations; an existing output is never overwritten.

A successful result means that the supplied human decisions are complete and bound to those exact inputs. It does not prove that a human listened, that their identity/qualifications/permissions are valid, or that any transcription is acoustically correct. Both comparison and adjudication therefore report `training_ready: false`; agreement never establishes ground truth automatically. Apply revised labels only through a new privacy-reviewed freeze, with updated transcript/privacy hashes and current withdrawal checks. Preserve the adjudication artifact and its checksum as evidence for that controlled change.

The automated acceptance cases use generated non-speech tones, fictional teacher hypotheses and fictional review metadata. They exercise comparison, explicit missing denominators, content binding, required human decisions, current authorization/withdrawal gates, privacy of output, private-file modes and refusal to overwrite. They are not real multi-teacher recognition results or real human review evidence.

## 3. Evaluate recognition and workflow outcomes separately

```bash
python scripts/evaluate_speech.py fixtures/research/speech-predictions.jsonl \
  --output /tmp/synthetic-evaluation.json \
  --bootstrap 500 --seed 42
```

That command is a reproducible fixture exercise, not a speech benchmark. For real evaluations, supply independently reviewed reference/hypothesis pairs and actual authoritative workflow evidence. Evaluation output aggregates results and does not print original utterances.

Recognition metrics include raw and normalized WER/CER, exact digit-group accuracy, critical entity accuracy, empty-reference hallucinations, speaker-cluster bootstrap confidence intervals, and declared slices. The partition audit detects speaker, clinic and exact-audio overlap only within the supplied inventory; it cannot certify that an opaque provider's earlier training corpus was disjoint.

Each input row may independently supply:

| Evidence | Fields | Result |
|---|---|---|
| Task completion | `eligible`, `task_completed` | Completion numerator/denominator and count of eligible rows with missing authoritative outcome. |
| Booking truth | `confirmed_claim`, `authoritative_confirmed` | False-confirmation count and separately unverified claims. Missing truth is never silently accepted as confirmation. |
| Human transfer | `handoff_requested`, `handoff_connected` | Requested/connected counts and unknown connection outcomes. A request alone is not a successful transfer. |
| Retries | `retry_count` integer 0–100 | Observed retry total/rate/mean and explicit unknown sample count. Absence is not zero. |
| Overall timing | `latency_ms` | Observed sample count and p50/p95/p99. |
| Stage timing | `stage_latency_ms` | Separate stage quantiles and missing counts. |

Allowed stage names are `carrier_connect`, `first_audio`, `endpointing`, `stt`, `policy`, `calendar`, `tts`, `transfer`, and `turn_to_first_audio`. Durations must be finite and nonnegative. Only include a stage when it was measured at the corresponding boundary. Server HTTP time, receipt of a generated WAV, and a caller hearing the first sound are different measurements.

The economics and matched-pilot scripts remain available as documented in `docs/research-workflow.md`. Their formulas keep booked, kept, displaced and estimated incremental activity distinct. Matched observational strata and confidence intervals describe the supplied observations; they do not establish causation or create missing baseline/control data.

## 4. Pin an experiment before downloading or training

Start from `fixtures/research/training-recipe.template.json`. Its placeholders and false license-review flag are deliberately ineligible. The recipe requires:

1. An immutable 40-character model revision and reviewed model license evidence.
2. The exact SHA-256 of the reviewed `scripts/train_asr.py`, the adapter's pinned Transformers version, explicit seed, learning rate, batch size, accumulation and step count.
3. A revalidated dataset with nonempty speaker-and-clinic-disjoint train/validation/test splits.
4. A maximum wall time of at most one week, positive documented compute rate per hour, explicit maximum compute allowance and source reference.
5. A rollback model/revision/artifact hash, responsible owner and evidence reference.

Compute the adapter hash after review, then place it in the recipe:

```bash
sha256sum scripts/train_asr.py

python scripts/train_asr.py /approved/frozen-new/manifest.json \
  --recipe /approved/reviewed-training-recipe.json \
  --tombstones /approved/withdrawals.json \
  --region IR --validate-only
```

Validation-only mode does not load or download weights, train, publish, or mutate the dataset. It verifies the presence and format of license/rollback evidence; a successful validation is not an independent legal or recovery review. Synthetic-tone manifests are rejected unless the explicit `--allow-synthetic-smoke-test` flag is used. That flag labels the report and does not make tones a meaningful training set.

Actual training is optional. It requires the separately documented optional training environment and approved local weights. Downloads remain disabled unless the operator explicitly uses `--allow-model-download`.

```bash
python scripts/train_asr.py /approved/frozen-new/manifest.json \
  --recipe /approved/reviewed-training-recipe.json \
  --tombstones /approved/withdrawals.json \
  --region IR --output /approved/experiment-new
```

The adapter evaluates the unmodified model on validation data, trains with validation-based checkpoint selection, then measures the held-out test split once for final reporting. It records the exact recipe, adapter/data identity, dependency versions, baseline, validation and held-out metrics. Remote model code and automatic hub publication are disabled.

The experiment measures elapsed monotonic wall time, including model load and evaluation, and allocates cost at the declared reviewed rate. It checks the time and cost budget at model-load, training-step and evaluation boundaries. These are cooperative checks: a native kernel or a long model-load call cannot be preempted by a Python callback. Deploy actual experiments under a separately enforced scheduler/container timeout and hardware allocation ceiling. A budget or rights failure produces an aborted, nondeployable status; checkpoints require independent review before any promotion. No training or model promotion was performed for this delivery.

## 5. Measure the local speech worker honestly

`services/local_speech/app.py` retains the existing local-model rights gates and exposes bounded admission before accepting work. Configure:

| Setting | Meaning |
|---|---|
| `SPEECH_MAX_CONCURRENCY` | Active request bound, clamped to 1–8; default 2. |
| `SPEECH_MAX_QUEUE` | Waiting request bound, clamped to 0–64; default 8. |
| `LOCAL_COMPUTE_TOMAN_PER_HOUR` | Optional finite, nonnegative declared allocation rate. |
| `LOCAL_COMPUTE_RATE_EVIDENCE_REFERENCE` | Required evidence reference for reporting priced allocation. |
| Existing `SPEECH_GATEWAY_TOKEN` | Protects both speech requests and `GET /metrics`. |

The worker rejects excess or timed-out queue admissions and reports measured active/waiting/admitted/completed/failed/rejected counts, observed latency samples, model-loaded state and measured cold-load timings. Model calls retain their existing serialization lock; admitting multiple requests is not a claim of parallel model execution.

Cost metrics allocate measured process uptime, including idle time, at the declared rate. Missing or invalid price evidence produces an unknown/null cost. This is a local allocation measurement, not a supplier invoice. Metrics are process-local and reset on restart; fleet accounting uses the canonical application ledger and real provider statements.

After installing approved weights and starting the local worker using the deployment documentation, run a bounded experiment against it:

```bash
python scripts/benchmark_local_speech.py /approved/non-sensitive-test.wav \
  --url http://127.0.0.1:8001 \
  --requests 20 --concurrency 2 \
  --output /tmp/local-serving-measurement.json
```

The token is read from `SPEECH_GATEWAY_TOKEN`, not a command-line credential. Loopback is the default; a remote endpoint requires an explicit approval flag. The benchmark isolates the first request, then issues bounded concurrent requests, records actual response status and latency, and compares worker metrics/cost allocation before and after. It does not persist response content or infer speech quality. A previously loaded worker is reported as warm rather than relabeled a cold start. Total requests are capped at 1,000 and concurrency at 32.

The automated tests use generated non-speech PCM and mock model/provider behavior. They verify bounds, authentication, measurement logic and failure semantics without downloading weights. Representative telephone accuracy, actual local-model throughput on deployment hardware, production cold-start behavior, vendor costs and carrier end-to-end latency remain separate experiments.

## 6. Recovery evidence and release gates

`scripts/config_backup.py` complements the database backup/restore tooling. It encrypts selected configuration files and a metadata-only key-custody inventory with a separate protected Fernet key. The inventory records key IDs, purposes, algorithms, fingerprints, recovery references, responsible roles and last-drill references, never the key material itself.

```bash
python scripts/config_backup.py create \
  --file app.env=/approved/config/app.env \
  --inventory /approved/key-custody-inventory.json \
  --key-file /approved/separate-config-backup.key \
  --output /approved/backups/config-new.enc

python scripts/config_backup.py restore /approved/backups/config-new.enc \
  --key-file /approved/separate-config-backup.key \
  --target /approved/restore-new --confirm-empty-target
```

The tool authenticates the bundle and verifies every content hash before restoring, refuses overwrite/nonempty targets/path traversal/symlink sources, and writes private file permissions. A successful run proves file recovery within that test. It does not prove offsite replication, independent key custody, recovery of an actual production deployment, or a live application restart.

Before any production research or model release, obtain the actual rights/clinical/legal review appropriate to the intended use, review representative redactions and transcripts, execute the approved experiment on documented hardware, compare against the pinned baseline and rollback artifact, and inspect latency, cost and safety regressions. Keep those actual receipts and reviews with the experiment. The software provides enforceable gates and evidence fields; it cannot supply approvals or observations that have not occurred.
