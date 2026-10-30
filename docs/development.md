# Developer and maintainer handbook

[فارسی](development.fa.md) | [Documentation](README.md)

## Workspaces and toolchain

Python **3.12** and the pinned `requirements.lock.txt` build the backend. Node **24** and the individual npm lock files build the web and native shells. The project layout is `backend/receptionist/` (service), `backend/tests/` (behavioral tests), `frontend/` (shared interface and browser journeys), `apps/desktop/` and `apps/mobile/` (native hosts), `services/local_speech/` (optional speech), `scripts/` (maintenance/research), and `deploy/` (infrastructure templates).

Do not use a live clinic database or provider account for development. Use `.env.example`, synthetic fixtures, an isolated SQLite database or a dedicated PostgreSQL test database. Keep secrets, patient data, binary builds and generated output out of git.

## Checks

From the root after dependency installation:

~~~sh
python -m ruff check backend scripts services
python -m pytest -q
python scripts/protocol_conformance.py --output artifacts/backend/protocol-conformance.json
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run build
npm --prefix frontend run test:browser-launch
python scripts/ci_ui.py test:ui test:workflows test:conversation test:extensions test:release test:outreach test:waitlist-deposit test:privacy-notice test:rtc-lifecycle test:companion test:platform test:latency-labels
npm --prefix apps/desktop test
node scripts/check-versions.mjs
node scripts/check-docs.mjs
node --test scripts/check-docs.test.mjs
~~~

Browser journeys require an already-built shared interface and isolated synthetic server; `scripts/ci_ui.py` supplies that isolation. PostgreSQL stress and deployment smoke tools require a specifically designated **test** database. Follow `.github/workflows/verify.yml` as the authoritative CI gate. Never claim a test passed without its actual execution.

## Changes and tests

Add a failing regression for a behavior change, implement the smallest fix, and run the focused and then full relevant suites. Keep business outcomes, permissions, transaction identity, durability and rollback assertions explicit. Native client changes also require security bridge tests; media changes require protocol and cancellation/concurrency checks.

## Migrations and cleanups

The live upgrade chain in `backend/receptionist/migrations.py` is **0001 → 0002**. It is part of supported deployed behavior, not obsolete scaffolding. Stop writers, back up and verify recovery, migrate, then check version and preserved records. Never stamp unknown schemas or drop tables to make a broken upgrade pass. The separate `scripts/migrate_privacy_notes.py` helper is operator-controlled and is not a substitute for schema migration.

Do not commit JUnit XML, screenshots, past run reports or temporary build helper experiments. Use `artifacts/` locally and GitHub Actions artifacts for run-specific proof. `scripts/make_source_release.py` creates a deterministic source-only archive with a generated hash manifest.

## Documentation policy

Each maintained `README.md` or `docs/*.md` needs a corresponding `.fa.md`. Translate narrative content accurately, keep code and paths unchanged, update links on both sides, and run the documentation checks. Binary/font license notices are kept in their original legally required form. For acceptance see [operations](operations.md), for deployment see [deployment](deployment.md).
