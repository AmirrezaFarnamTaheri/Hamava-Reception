# Synthetic research fixtures

[فارسی](README.fa.md) · [Research guide](../../docs/research.md)

The files in this directory are repeatable test inputs. The text, prices, participants and permission records describe fictional cases. The six WAV files contain non-speech tones. Their associated text is **not** a transcription of the audio.

## Find the input for your test

| File | What it exercises |
| --- | --- |
| `manifest-input.jsonl` | Audio records, metadata, rights checks and dataset curation |
| `withdrawals.json` | The exclusion of withdrawn records |
| `speech-predictions.jsonl` | Evaluation result parsing and error reports |
| `training-recipe.template.json` | Training recipe validation without a real training run |
| `capacity-input.json` | Queue and staffing scenario calculations |
| `economics-input.json` | Exact cost calculations from fictional rates |
| `pilot-cohorts.jsonl` | Baseline and pilot reporting logic |
| `audio/synthetic-tone-*.wav` | Audio file decoding and segmentation plumbing |

These fixtures tell you whether a parser or calculation behaves as expected on known values. They cannot establish Persian speech accuracy, actual supplier prices, patient permission or business impact. In particular, the presence of fictional consent fields is no substitute for permission to process a real recording.

## Generate your own clean copy

From the repository root, use a new or empty directory:

~~~sh
python scripts/make_synthetic_fixtures.py /tmp/new-synthetic-fixtures
~~~

The generator refuses to overwrite existing files. Inspect the new manifests and expected labels before running a downstream tool. The training adapter requires an explicit synthetic smoke-test mode for these examples.

## Work with approved real recordings

For actual research, keep source recordings, participant permissions, withdrawal records and model weights in approved private storage. Use a new dataset manifest tied to those permissions. Freeze speaker- and clinic-separated splits before model selection, preserve the held-out test set and record the decoding and model versions.

The [research guide](../../docs/research.md) explains the full evaluation procedure and how to interpret critical-field errors. Keep synthetic fixtures separate from any claimed real-world benchmark.
