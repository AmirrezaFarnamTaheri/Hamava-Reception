# Hamava Reception 0.2.2 - delivery guide

**24 October 2026.** This handoff is a reproducible **source candidate**, not a production-qualified, medically approved or signed installer release.

## Contents

- `Hamava-Reception-0.2.2-source.zip`: complete Python backend, React RTL frontend, desktop and Android native projects, PBX/LiveKit bridge, scripts, tests, deployment configuration, and documentation. A SHA-256 source file inventory (`PACKAGE-MANIFEST.json`) is embedded.
- `Hamava-0.2.2-from-integrated.patch`: verified patch applied against the last persisted integrated streaming-transfer checkpoint. From the project root, `git apply --check PATCHFILE && git apply PATCHFILE`. Byte-by-byte reconstruction was verified for 527 files in the source archive.
- `FINAL_ENGINEERING_REPORT.md`: implemented changes, verification, unresolved acceptance and how to reproduce.
- `requirements-263.csv`: original 263 requirements with their original acceptance state and updated engineering evidence where applicable.
- `focused-tests.xml` / `focused-tests.log`: 73 focused pytest successes from this candidate.
- `protocol-conformance.json`: 15/15 synthetic transport and model-event fixtures.
- `broader-tests-unverified.*`: unmodified wider-suite attempt, not accepted as a passing gate because this environment lacks jdatetime and required runtime dependencies.
- `external-readiness.json`: explicit missing real-world production acceptance. It correctly records `production_ready=false`.
- `SHA256SUMS.txt`: individual delivery-file checksums. The outer handoff ZIP has its own checksum in a separate `.sha256` file.

## How to use

Extract the source archive and enter `voice-receptionist/`. Use Python 3.12 and Node 24 with the checked-in dependency constraints and native build guides. The release workflows are `.github/workflows/verify.yml` and `.github/workflows/release-apps.yml`.

```
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade -r requirements-bootstrap.txt
python -m pip install -c requirements.lock.txt '.[test,media]'
pytest -q
python scripts/protocol_conformance.py --output /tmp/hamava-protocol-conformance.json
npm --prefix frontend ci
npm --prefix frontend run build
node scripts/check-versions.mjs
```

Review `docs/remaining-external-acceptance.md` before any carrier, medical or patient traffic. The source includes opt-in native streaming and screened PBX handoff contracts; no real authorized live carrier, vendor or signed publisher release was available for acceptance. Real hardware, licensing, staffing and permission gates are NOT complete.

**Not included:** rebuilt 0.2.2 EXE/MSI/APK/AAB, signing credentials, live carrier credentials or patient recordings. Earlier 0.2.0 native artifacts are different source bytes and must not be repackaged as 0.2.2.
