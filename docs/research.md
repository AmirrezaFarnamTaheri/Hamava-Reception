# Research, evaluation and capacity

[فارسی](research.fa.md) | [Documentation](README.md)

## What the repository provides

The project includes non-production scripts for speech dataset preparation, rights and withdrawal manifests, segment capture, redaction/review, teacher-output adjudication, WER/CER, exact-field and slice evaluation, training adapters, local speech benchmarking, capacity simulation, provider economics and pilot analysis. Code lives under `scripts/`; clearly labeled example inputs are in `fixtures/research/` and `docs/evidence/`.

**The included fixtures are synthetic.** Audio may be non-speech tones and fictional transcripts; they cannot support claims of Persian ASR quality, real-world telephone latency, training improvement, legal permission, supplier prices or customer ROI. No real patient recording or model weight belongs in the source repository.

## Controlled workflow

1. Establish a separately approved purpose, participant consent and processing rights before collecting real audio; store captures and authorization references in controlled external storage.
2. Preserve source channel, speaker/tenant identity evidence, timestamps, recording format, rights, withdrawal state and immutable dataset references. Never infer diarization from a mixed track without evidence.
3. Curate and redact samples, verify permissions at every reuse, freeze splits disjoint by speaker/tenant, and keep dataset hashes and independent human adjudication.
4. Evaluate WER/CER and critical exact fields (dates, telephone digits, names, appointment outcomes) separately, reporting sample sizes and uncertainty per acoustic/noise/provider slice.
5. Benchmark actual deployed hardware with full queueing, first/last token or audio timing, call admission, cancellation, failures and fallback. Test under representative Persian PSTN conditions.
6. Measure staff workload, appointment recovery, cost exposure and net value using real, authorized pilots with explicit baselines; never extrapolate from demonstration fixtures.

## Commands and safety

`python scripts/make_synthetic_fixtures.py /tmp/new-synthetic-fixtures` generates a fresh example dataset. Relevant tools include `scripts/dataset_curate.py`, `scripts/evaluate_speech.py`, `scripts/teacher_labels.py`, `scripts/train_asr.py`, `scripts/benchmark_local_speech.py`, `scripts/capacity.py`, `scripts/economics.py` and `scripts/pilot_analysis.py`. Consult each CLI's `--help` and prerequisites; do not invoke training/collection against real data until rights, isolation, retention and deletion procedures are approved.

Research success does not override product authority: clinical advice remains prohibited and appointment state is set only by verified business transactions.
