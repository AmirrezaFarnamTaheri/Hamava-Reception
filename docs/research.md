# Research, evaluation and capacity

[فارسی](research.fa.md) · [Documentation](README.md)

Hamava's research tools answer practical questions about speech recognition, staffing and cost. They do not run a hidden learning pipeline on patient calls. The data preparation, training and evaluation scripts live under \`scripts/\`; their generated reports are stored separately from the application and tied to the input and code revision.

## Choose an evaluation for the decision

| Decision | Evidence to collect | Useful measures |
| --- | --- | --- |
| Is phone speech understood accurately? | Approved Persian telephone recordings with independently reviewed transcripts | WER, CER, error distribution by accent/noise/channel |
| Does the system capture booking details? | Calls with known, verified appointment facts | Exact dates, names, numbers, services and authorized outcomes |
| Is a conversation responsive? | End-to-end traffic on the intended hardware and network | First-response delay, turn duration, queue time, interruption behavior |
| Does the service reduce reception work? | Comparable real shifts or eligible inbound cohorts | Completed bookings, escalations, rework and staff minutes |
| What is the operating cost? | Supplier invoices, observed usage, staff cost and capacity measurements | Cost per verified outcome, unknown liability and budget utilization |

Word error rate alone cannot tell whether the right person was booked for the right day. Report critical-field errors and business outcomes alongside transcription metrics. Treat synthetic queue models as scenarios to test, not observed forecasts.

## Data, consent and provenance

The research process starts with explicit permission and a defined purpose. Record who is authorized to use a recording, where it may be processed, its retention period and how withdrawal takes effect. Store the source recording and proof of permission in approved private storage—not in Git, a public CI artifact or a shared bug report.

The main stages are:

1. **Capture and segment.** \`scripts/capture_segment.py\` reads an authorized, two-track audio manifest and proposes segments using energy-based detection. Channel assignments come from the telephony transport; the tool does not prove a speaker's identity by itself.
2. **Review and protect.** Independently check the transcription, remove or mask identifiers where appropriate, maintain content hashes and record the reviewer's decision. Withdrawal tombstones must be consulted each time the dataset is reused.
3. **Freeze the dataset.** \`scripts/dataset_curate.py\` validates rights and creates a versioned manifest with reproducible training, validation and test splits. Keep speakers and clinics separated across splits so the model cannot be tested on voices it learned during training.
4. **Compare annotations.** \`scripts/teacher_labels.py\` compares supplied teacher hypotheses; agreeing models are not a substitute for human adjudication of contested words, dates or names.
5. **Train deliberately.** \`scripts/train_asr.py\` has a \`--validate-only\` option that checks a recipe and input without training or downloading. Real training requires approved data, reviewed model weights and an explicit recipe.
6. **Measure on untouched examples.** \`scripts/evaluate_speech.py\` accepts JSONL predictions with \`id\`, \`reference\` and \`hypothesis\`; optional metadata supports speaker, tenant, acoustic slice, expected entities and the verified appointment outcome. Report the sample count and uncertainty for each meaningful slice.

Keep train/test manifests, model revisions, data hashes, review decisions and withdrawal records reproducible. Do not continue using a withdrawn recording simply because it was included in an earlier frozen dataset.

## Running the examples

The bundled examples are deterministic fictional text, numbers, prices and non-speech tones. They are useful for checking file formats, privacy gates and analysis code; they cannot be used as a Persian speech benchmark.

~~~sh
python scripts/make_synthetic_fixtures.py /tmp/new-synthetic-fixtures
python scripts/dataset_curate.py --help
python scripts/evaluate_speech.py --help
python scripts/train_asr.py --help
~~~

Use a new or empty fixture directory. Before using real data, inspect the relevant command's required rights manifest, tombstone list and region arguments. No real recording should enter a generic issue or workflow log. \`fixtures/research/README.md\` explains what is generated and how to interpret it.

## Measuring the speech service

\`scripts/benchmark_local_speech.py\` sends explicitly supplied audio to a permitted endpoint, with loopback as the default. Document the deployed device, CPU/GPU, model revision, codec, concurrent calls and whether the service was cold or warm. Measure not only model latency but the entire turn: audio transport, queue admission, recognition, decision, synthesis, playback and fallback.

A telephone release also needs real channel tests: narrowband audio, packet loss, noise, dialect variation, mixed digits and Jalali dates, interruptions, cancellation and live transfer. The outcome that matters is whether the caller and staff can complete the work—not just whether an isolated model returned a transcript quickly.

## Capacity, economics and pilots

The project includes three complementary analysis tools:

- \`scripts/capacity.py\` simulates queueing and staff workload. Its arrival-rate and handling-time assumptions are inputs, not measured facts. Calibrate them against real demand and include busy-hour peaks and uncertainty.
- \`scripts/economics.py\` uses exact decimal accounting for costs and scenarios. Separate committed cost, observed supplier usage and charges still awaiting reconciliation. Record rate effective dates and currency units.
- \`scripts/pilot_analysis.py\` compares matured baseline and pilot cohorts by comparable strata. Do not mix a booking created yesterday with a booking whose attendance can already be verified.

A pilot's evaluation plan should define the eligible inbound population, primary outcome, exclusions, time window and ownership of follow-up before data collection. Good primary measures include **verified bookings per eligible request**, **human interventions**, **duplicate/incorrect bookings**, **time to resolution**, **staff minutes** and **net cost per completed outcome**. When the design is observational, describe differences; do not claim causation from a before/after chart alone.

## Moving a research result into service

A model or policy change should have a reviewed dataset, reproducible offline evaluation, tests for critical fields and retries, actual runtime timing, a rollback path and clinic acceptance. The scheduling database—not the speech model—remains responsible for the booking. Low confidence, provider failures, clinical questions and unsupported requests must still reach a person.

Related reading: [Architecture](architecture.md) for the runtime boundary, [Product](product.md) for the customer workflow and [Operations](operations.md) for supervised pilots.
