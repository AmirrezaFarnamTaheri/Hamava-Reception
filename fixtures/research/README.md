# Synthetic research fixtures

These are deterministic non-speech tones and fictional text/count/price inputs. They contain no real caller, clinic, consent, acoustic benchmark, market quote or clinical outcome. Consent and review fields are clearly fictional plumbing fixtures. The text is not a transcription of the tones. Do not use these fixtures as evidence of Persian ASR accuracy or model improvement. The training adapter refuses synthetic data unless explicitly placed in smoke-test mode.

Generate a fresh copy with `python scripts/make_synthetic_fixtures.py /tmp/new-synthetic-fixtures`. The destination must be new or empty; the command refuses to overwrite an existing fixture directory.
