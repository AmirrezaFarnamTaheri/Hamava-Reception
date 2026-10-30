# Synthetic research fixtures

[فارسی](README.fa.md) · [Research guide](../../docs/research.md)

These are deterministic non-speech tones and fictional text/count/price inputs. They contain no real caller, clinic, consent, acoustic benchmark, market quote or clinical outcome. Consent and review fields are clearly fictional plumbing fixtures. The text is not a transcription of the tones. Do not use these fixtures as evidence of Persian ASR accuracy or model improvement. The training adapter refuses synthetic data unless explicitly placed in smoke-test mode.

Generate a fresh copy with `python scripts/make_synthetic_fixtures.py /tmp/new-synthetic-fixtures`. The destination must be new or empty; the command refuses to overwrite an existing fixture directory.

## When to use these examples

They are suitable for testing rights metadata, withdrawal handling, file parsing, redaction, dataset splitting, evaluation output and cost or capacity calculations without using real people. The audio files are tones rather than speech; they must not be compared with the fictional transcripts as if they were human recordings.

Generate a fresh copy from the repository root:

~~~sh
python scripts/make_synthetic_fixtures.py /tmp/new-synthetic-fixtures
~~~

The generator requires a new or empty destination. Inspect the generated manifest and rights flags before using a research tool; follow the [research workflow](../../docs/research.md) for actual authorized recordings. Synthetic inputs can exercise a smoke test, but they cannot measure Persian recognition quality or real clinic value.
