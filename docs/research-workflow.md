# Research, evidence and economic evaluation workflow

The project includes working command-line tools for evaluating supplied predictions, validating and redacting eligible PCM segments, freezing/revalidating datasets, exact unit-cost scenarios, descriptive pilot analysis, and optional Whisper fine-tuning. The default tools need only Python's standard library. Training has an isolated optional dependency set and requires actual reviewed weights, eligible speech and compute.

The checked-in fixtures are **non-speech tones and fictional text/count/price records**. They verify software behavior. They establish no Persian acoustic accuracy, provider latency, clinic outcomes, live prices, legal permission, customer ROI or trained model quality.

## 1. Implemented tools and verified boundary

| Tool | Actual behavior | Evidence boundary |
|---|---|---|
| `scripts/evaluate_speech.py` | Raw/normalized WER and CER, exact digit sequences, critical entity accuracy, completion/handoff/false-confirmation counts, latency quantiles, slice reports, speaker-cluster bootstrap, observed split leakage checks. | Text predictions and supplied measurements; no live ASR/TTS calls or hidden training-set verification. |
| `scripts/dataset_curate.py` | Rights/provenance/review/hash/expiry checks; PCM span muting; safe file resolution; duplicate rejection; joint speaker/tenant grouping; atomic freeze; tombstone/content revalidation. | Validates supplied evidence metadata and bytes. Does not establish legal sufficiency, human review quality, or voice anonymity. |
| `scripts/economics.py` | Decimal quantities/rates, time/token unit conversion, USD/IRR/Toman accounting, cost/revenue/tax separation, FX and usage scenarios, booked/kept/incremental distinction. | Supplied rates and assumptions; no live market quote and no automatic causal ROI. |
| `scripts/pilot_analysis.py` | Completed-cohort checks, matched strata, baseline-weighted kept-per-eligible differences, Wilson/MOVER intervals, coverage of safety/answer/handoff measurements. | Descriptive observational comparison; no automatic claim of causal recovered appointments. |
| `scripts/train_asr.py` | Immutable model-revision/license gate, frozen dataset validation, per-sample/step revocation checks, optional Whisper training, validation checkpoint selection, final held-out test, model/report output. | Rights/recipe validation tested locally; actual weight loading, accelerator training and model improvement remain unexecuted without their external inputs. |
| `scripts/make_synthetic_fixtures.py` | Reproducible tone WAVs and fictional fixtures for pipeline checks. | No generated human voice or actual patient consent assertion. |

The focused regression command is:

```bash
python -m pytest backend/tests/test_research_tools.py -q
```

At the implementation checkpoint, **42 tests passed**. They cover output privacy, zero denominators, digit normalization, split leakage, byte-preserving PCM redaction, rights exclusion, reviewed-content tampering, traversal, withdrawal after freeze, atomic publication, metadata rejection, Decimal units/tax/FX, absent ROI evidence, incomplete cohorts, missing safety measurements, and the training gates. The project-wide verification report may include a later aggregate count.

## 2. Run the supplied synthetic examples

Run commands from the project root:

```bash
python scripts/evaluate_speech.py fixtures/research/speech-predictions.jsonl --output /tmp/speech-example.json
python scripts/economics.py fixtures/research/economics-input.json --output /tmp/economics-example.json
python scripts/pilot_analysis.py fixtures/research/pilot-cohorts.jsonl --output /tmp/pilot-example.json
python scripts/dataset_curate.py freeze fixtures/research/manifest-input.jsonl /tmp/voice-dataset-example --tombstones fixtures/research/withdrawals.json --region local-test
python scripts/dataset_curate.py revalidate /tmp/voice-dataset-example/manifest.json --tombstones fixtures/research/withdrawals.json --region local-test
```

Choose a new/empty output directory for each freeze. The tool refuses to overwrite an existing dataset. Successful synthetic curation yields six eligible fixture segments and, with the default seed, four training, one validation and one test segment. The files are tones; their fictional text labels are not transcripts. A successful freeze demonstrates plumbing and integrity checks, not a suitable ASR corpus.

Reports under `docs/evidence/` preserve example CLI output. The synthetic prediction set intentionally contains recognition errors, a silence hallucination and a false-confirmation case. Its 12 input rows produce normalized WER 1/6, exact digit accuracy 1/2, and one explicitly false confirmation. Those values are predetermined fixture behavior, **not product performance measurements**. Example latency values are also fictional.

The economic fixture leaves customer ROI `null` because its booked/kept counts and baseline difference do not establish an attributable incremental effect. Its costs are illustrative arithmetic inputs. The pilot fixture reports a descriptive +6.67 percentage-point kept-per-inquiry difference with an approximate interval spanning zero; it explicitly leaves causal attribution unestablished.

## 3. Prediction evaluation schema and metric definitions

Each JSONL row requires a unique nonempty `id`, `reference`, and `hypothesis`. Optional fields are `speaker_id`, `tenant_id`, `split`, `audio_sha256`, `slices`, `latency_ms`, `expected_entities`, `predicted_entities`, `eligible`, `task_completed`, `confirmed_claim`, `authoritative_confirmed`, `handoff_requested`, `handoff_connected`, and `synthetic`.

```json
{
  "id": "heldout_sample_001",
  "reference": "کد نمونه ۰۱۲۳",
  "hypothesis": "کد نمونه 0123",
  "speaker_id": "pseudonymous_speaker_a",
  "tenant_id": "pseudonymous_tenant_a",
  "split": "test",
  "slices": {"channel": "narrowband", "noise": "reviewed_low"},
  "expected_entities": {"reference_code": "0123"},
  "predicted_entities": {"reference_code": "0123"},
  "eligible": true,
  "task_completed": true,
  "confirmed_claim": false
}
```

The evaluator performs NFC normalization, Persian/Arabic digit conversion, common yeh/kaf normalization, diacritic and punctuation treatment, and whitespace normalization. It reports both raw and normalized word/character error rates. CER excludes whitespace. These choices are versioned behavior; keep the same normalization when comparing providers. No semantic rewriting or inference that a spoken word must represent a digit is performed. “چهار” and `4` therefore need a separately defined entity-equivalence rule if an experiment intends to equate them.

WER/CER are **micro-averages**: total edit distance divided by total reference words/characters. Insertions can make WER exceed one. Empty references do not create a fake zero denominator; silence hallucinations are counted separately and contribute inserted errors when the corpus has a valid denominator.

Exact-number accuracy compares the ordered digit groups after digit-script normalization. Leading zeroes remain significant. Any number in a hypothesis with no reference number is an eligible incorrect numeric sample. Missing/predicted critical entities use explicit provided maps. Neither metric proves contact ownership or correct source-of-truth booking.

Workflow booleans are recorded observations. A confirmation claim with `authoritative_confirmed=false` is a false confirmation; a missing authoritative field is separately counted as unverified. No success is inferred from an omitted field. Handoff task creation and connected human handling must be supplied as distinct outcomes.

Latency quantiles use linear interpolation over the supplied nonnegative finite measurements. The tool cannot know whether a number was measured from the end of caller speech, first STT token or another event; the experiment must retain the blueprint's measurement definition. The synthetic examples cannot verify latency targets.

### Uncertainty and grouping

Number/entity/completion/handoff rate intervals use Wilson limits, with the independent Bernoulli assumption made explicit. Entity observations from one caller may be correlated. WER uncertainty uses a seeded percentile bootstrap over speaker clusters when every row has speaker metadata, otherwise over sample clusters. With fewer than two clusters, the interval is unavailable. Repeated households, tenants and days can introduce correlation beyond the supplied speaker grouping; do not describe these intervals as fully adjusted for that design.

If split labels are supplied, every row needs speaker and tenant pseudonyms and a valid `train`, `validation`, or `test` label. Sharing a speaker, tenant or available audio hash across observed partitions is refused by default. The report lists the partitions actually present. An all-test file can show no observed leakage, but it cannot prove that an external model's unseen training set is disjoint. Keep the corpus manifest and model-training provenance separately.

Slices are user-supplied approved categories, never inferred protected traits. Do not put names, numbers, addresses or free-form health descriptions in slice labels. Reports omit raw transcripts and speaker/tenant identifiers, but approved slice labels are displayed.

## 4. Dataset admission and redaction

### Required source record

An admission row contains:

- Pseudonymous `sample_id`, `speaker_id`, `tenant_id`; IDs begin with a letter and use a constrained safe character set.
- `audio_path` relative to the input manifest directory, `source_sha256`, `recorded_at`, reviewed `transcript`, and optional `redaction_spans_ms`.
- `rights.recording`, `rights.training`, `rights.clinic_authorized` explicitly true; a license ID, consent version, consent-evidence SHA-256, allowed processing regions and timezone-aware expiry.
- `privacy_review.approved`, reviewer, approval time, **hash of the final redacted audio** and **hash of the reviewed transcript**.
- `synthetic=true` only for explicitly fictional test fixtures.

The final review hashes prevent changing the transcript, source audio or mute plan after the recorded review without invalidating eligibility. The tool checks that evidence fields exist and match content, but cannot verify a person signed a genuine consent or that a reviewer found every identifying detail. This CLI is an authorized operator tool: source records must come from the application's authoritative consent/process records or an independently approved review process. A caller-supplied JSON boolean must never grant training rights in a public API.

### PCM span operation

The redactor supports uncompressed RIFF PCM, one or two channels, supported sample rates and 8/16/24/32-bit samples. It validates the RIFF/chunk lengths, alignment and declared byte rate. It floors the starting frame and ceils the ending frame so the selected interval is fully covered. Both channels are muted in a selected interval. Eight-bit PCM uses midpoint 128; signed formats use zero.

The operation mutates only the selected data bytes. Every byte outside those intervals remains unchanged, including the header and other audio. The test suite proves this for mono/stereo examples. This matters for reliable redaction, but it also means arbitrary metadata is not magically removed. Dataset admission separately rejects unexpected metadata chunks and nonzero padding that may carry identifiers. The source-hash and output-hash trail remains available.

To create a candidate redacted artifact for human review:

```bash
python scripts/dataset_curate.py redact approved-input.wav candidate-redacted.wav --spans redaction-spans.json
```

`redaction-spans.json` is an array such as `[[1000, 1200], [2400, 2700]]`, in milliseconds. The command refuses to overwrite an existing output and labels the result as requiring review. Muting names or numbers does **not** establish speaker anonymity: voice, specialty, event context and combinations of non-obvious facts may still identify a person. Exclude clips that cannot be made eligible for the approved purpose.

### Freeze semantics

Admission checks rights/expiry/region before copying a segment. The tool verifies source and reviewed output hashes, rejects path traversal or links outside the manifest root, limits segment size, and requires a 3–15-second clip. It rejects duplicate sample IDs, duplicate source hashes and identical redacted output hashes. It does not yet implement acoustic near-duplicate identification or independently infer whether two pseudonymous IDs are the same real speaker.

Splits use connected components over both speaker and tenant links. If one speaker appears in two tenants, both tenants' connected samples stay in one partition. At least three independent components are required; otherwise the pipeline refuses to claim three disjoint partitions. It targets 80/10/10 while ensuring nonempty partitions, so small or uneven groups can produce substantially different realized shares. Inspect the actual counts and sample diversity before calling a dataset representative.

The dataset is written to staging and published atomically only after validation and a final withdrawal-registry check. Rejections contain reason codes and hashed sample references, not rejected transcripts or paths. A frozen `manifest.json` records sample hashes, review/rights provenance, split assignment, seed, processing region, creation time, and input/tombstone checksums. The checksum detects accidental alteration; it is not a signature proving who approved the manifest. Protect the artifact and authoritative consent records through actual access controls.

### Withdrawal and revalidation

The withdrawal registry is explicit:

```json
{"sample_ids": [], "speaker_ids": [], "tenant_ids": []}
```

It is required even when empty. Missing or unreadable registry fails closed. Add a withdrawn sample, speaker or tenant pseudonym through the authorized process. Revalidation checks the **current** registry, rights expiry, permitted region, manifest checksum, audio/transcript hashes, duplicate samples and observed speaker/tenant split separation. It refuses a changed registry during validation.

A freeze is not permanent permission. Revalidate when a job is queued, immediately before reading data, and after an experiment. The optional trainer additionally checks rights/withdrawal before each sample and at the beginning of each training step. A revocation discovered after earlier optimizer steps cannot erase past model influence; the run is stopped and artifacts require review. Backup expiry, downstream dataset notices, model withdrawal/retraining and legal retention require the agreed operational policy.

## 5. Decimal economic scenarios

`economics.py` accepts an explicit `fx_toman_per_usd`, cost/revenue line items and optional outcome/scenario inputs. Money is represented with `Decimal`; conversion and totals occur before two-decimal presentation rounding. USD converts through the supplied FX; IRR divides by ten; TOMAN stays unchanged. There is no inferred exchange quote.

A priced line item contains `id`, `category`, `quantity`, `quantity_unit`, `rate`, `rate_unit`, and `currency`. Time units convert between seconds/minutes/hours; token units convert between tokens/million tokens; incompatible dimensions are rejected. For example, 3,600 supplied STT seconds at USD 0.12/hour is USD 0.12, not USD 432. This is a mathematical example, not a current supplier tariff.

Revenue credits are explicit. Invoice tax is shown separately from net revenue. The contribution result means revenue minus **the cost items actually supplied**; missing support, channel fees, compute, silence, retry, human time or taxes cannot be assumed zero in a real pricing decision.

Outcome inputs distinguish booked, matured and kept counts. Kept cannot exceed matured; matured cannot exceed booked. The report displays unearned booked contribution potential, observed kept contribution, and any baseline count difference separately. It computes customer ROI only when there is an explicit attributable-incremental-kept estimate, stated basis, and positive total service cost. The estimate is an input assumption, not a causal result created by the calculator. Negative effects remain negative.

Scenarios support `fx_multiplier`, cost quantity multipliers by known category, and explicit outcome overrides. Unknown scenario options/categories are rejected. FX changes affect USD items only; local costs remain local unless a quantity assumption changes. Run low demand, long conversations, doubled handoffs and high FX scenarios before agreeing a price.

For a compact table:

```bash
python scripts/economics.py fixtures/research/economics-input.json --format markdown --output /tmp/economics-example.md
```

## 6. Pilot cohorts and descriptive intervals

`pilot_analysis.py` operates on **inbound cohorts whose resulting appointment observations are complete**. The fields are `cohort_id`, `stratum`, `period` (`baseline` or `pilot`), attempts, eligible inquiries, confirmed bookings, matured bookings, kept visits, and explicit cohort completion. Missing core counts or inconsistent inequalities are rejected. Do not mix today's completed visits with today's newly booked appointments; link outcome cohorts using the real calendar.

Incomplete cohorts are excluded from the kept comparison. Strata need both periods and positive eligible denominators; unmatched strata are reported, not silently pooled. Within each matched stratum, the tool compares kept visits per eligible inquiry and then weights stratum differences by baseline eligible inquiries. This standardizes the observed mix; it does not resolve confounding, clinic capacity changes or channel displacement.

Individual rates use Wilson intervals. Differences combine the appropriate lower/upper Wilson deviations; the weighted comparison uses their squared, weighted components in a MOVER-style approximation. This approach is grounded in the primary work on Wilson-combined differences and linear combinations of binomial proportions, but the application's interval remains an **approximation under independent inquiry/stratum assumptions**. It does not adjust for repeated patients, clustered days, serial correlation, dynamic treatment assignment or finite-sample weight uncertainty. Design an appropriate cluster-aware experiment when those are material. [Newcombe 1998](https://pubmed.ncbi.nlm.nih.gov/9595617/); [Zou, Huang and Zhang 2009](https://www.sciencedirect.com/science/article/pii/S0167947308004623).

Safety, answer and handoff metrics use all supplied cohorts, including ones whose appointments have not matured, but only rows where the relevant measurement exists contribute to that metric's denominator. Coverage counts identify missing observations. Missing incident data is unknown, not an invented zero-incident rate. A measured zero still has a positive upper confidence bound.

The output always leaves `causal_effect_established=false` and `attributed_incremental_kept=null`. It reports associations with denominators and assumptions. Any later causal or ROI claim needs the pilot design, data provenance, concurrent changes and analysis to justify it.

## 7. Optional model-training execution

The training adapter targets **Transformers 4.57.3** and uses its documented sequence-to-sequence training/evaluation interfaces. It keeps the optional dependency environment separate from the serving API. The selected API shape was checked against [the versioned Trainer documentation](https://huggingface.co/docs/transformers/v4.57.3/en/main_classes/trainer) and [the official speech-recognition example](https://github.com/huggingface/transformers/blob/main/examples/pytorch/speech-recognition/run_speech_recognition_seq2seq.py). This documentation review is not a completed local training run.

```bash
python -m venv .research-venv
.research-venv/bin/python -m pip install -r scripts/requirements-training.txt
.research-venv/bin/python -m pip freeze > /tmp/research-environment.lock
```

Keep the resolved lockfile with the actual experiment. The optional requirements constrain compatible major families; the complete resolved environment is recorded only when installed. The base application does not download model weights.

Copy the supplied template recipe to an experiment file and fill **real** reviewed model ID, immutable 40-character model commit revision, license evidence and approved compute budget. Leave `model_license_reviewed=false` until that evidence exists. The recipe specifies maximum optimizer steps, batch size, gradient accumulation, learning rate and seed. Then validate without model dependencies or downloads:

```bash
python scripts/train_asr.py /path/to/frozen/manifest.json --recipe /path/to/approved-recipe.json --tombstones /path/to/current-withdrawals.json --region approved-region --validate-only
```

For an actual permitted experiment, use the research environment and provide a new output directory. Model loading is local-only by default. The explicit `--allow-model-download` flag permits retrieval of the reviewed model revision; it must be consistent with the deployment's network/service terms. The script disables remote model code, hub publication and training telemetry reporting.

```bash
.research-venv/bin/python scripts/train_asr.py /path/to/frozen/manifest.json --recipe /path/to/approved-recipe.json --tombstones /path/to/current-withdrawals.json --region approved-region --output /path/to/new-experiment-output
```

The adapter reads mono 16-bit PCM, resamples to 16 kHz where needed using a polyphase operation, extracts Whisper features, pads audio/labels, and masks label padding. Resampling narrowband audio does not recreate missing speech information. Training uses the training split; checkpoint selection uses validation WER; the held-out test split is evaluated once after selection. The report records baseline/trained validation, held-out metrics, model/data/recipe identities, dependency versions, and publication=false. An interrupted/revoked run is marked not deployable.

Synthetic tones are refused as real training data by default. `--allow-synthetic-smoke-test` is only for explicitly exercising plumbing and cannot establish a speech-model achievement. No weights were downloaded, no actual training run was completed, and no trained model is claimed in this implementation checkpoint.

## 8. Remaining external evidence

Real research needs eligible narrowband call audio; rights and model/voice licenses; meaningful native annotations and privacy review; enough independent speakers/tenants for representative splits; chosen provider measurements; licensed reviewed weights; compute and a reproducible installed environment; and independent speech/cost/non-regression review. The software makes these inputs inspectable and enforces its metadata/integrity gates. It cannot substitute for them.

Real commercial evidence likewise needs clinic-attested attendance, comparable demand/capacity periods, supplier invoices, staffed escalation costs and customer renewal decisions. The calculators preserve missingness so a dashboard can say “not established” when those facts are absent.
