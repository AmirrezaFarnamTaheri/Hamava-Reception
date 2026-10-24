# Maintainer guide: CI, migrations, and retained evidence

Hamava separates executable application source from test evidence and old release
checkpoints. The current source candidate is version 0.2.2; past passing
evidence is **not** proof that an updated checkout passes the same gates.

## Supported code and test entry points

- `backend/receptionist/` contains server, policy, database, media, and providers.
- `frontend/src/` is the shared web application. `frontend/scripts/` contains
  synthetic browser journeys, all using `browser-launch.mjs`.
- `apps/desktop/` and `apps/mobile/` are native shells for the shared interface.
- `scripts/` contains deployment, research, packaging, and maintenance commands.
- `docs/history/` preserves superseded engineering reports and checkpoints.
- `docs/validation/` contains *historical observations* and build evidence,
  not automatically executed application code. See its README for provenance.

The normal CI gate uses Python 3.12, Node 24, PostgreSQL 16, and the
FFmpeg command-line decoder for speech-integrity tests. The optional local
speech Docker image also installs FFmpeg explicitly. Reproduce
with the pinned dependencies before changing a test assertion to match a bug:

```sh
python -m pip install --upgrade -r requirements-bootstrap.txt
python -m pip install -c requirements.lock.txt '.[test,media]'
ruff check backend scripts services
pytest -q
python scripts/protocol_conformance.py --output artifacts/backend/protocol-conformance.json
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run build
npm --prefix frontend run test:browser-launch
python scripts/ci_ui.py test:ui test:workflows test:conversation test:extensions test:release test:outreach test:waitlist-deposit test:privacy-notice test:rtc-lifecycle test:companion test:platform test:latency-labels
```

The browser orchestration starts a separate **synthetic-only** database for
each journey. PostgreSQL invariants must be exercised against an isolated
test database, never a live clinic database. CI checks are separate from
real telephone-carrier, clinic, signing, and device acceptance.

## Forward-only schema history (do not squash)

The application deliberately supports an explicit `0001` baseline and additive
`0002` upgrade in `backend/receptionist/migrations.py`. Both sets of table
definitions are required to migrate existing installations. Removing the
baseline merely because fresh installs reach `0002` would silently strand
backups or deployments at `0001`.

1. Quiesce API, background workers, media workers, and other DB writers.
2. Take a recoverable encrypted backup and verify its restore procedure.
3. Point `DATABASE_URL` at the **intended** database; run
   `python scripts/migrate.py` during a maintenance window.
4. Verify `schema_version`, startup, and data integrity before resuming
   writers. Roll back by restoring the backup, **not** by guessing a
   reverse schema migration.

Never auto-stamp an unversioned or partially upgraded database. Never
recreate or drop populated application tables to make tests pass. A new
schema change must introduce a new version, preserve upgrade paths from
both supported predecessors, and add tests covering idempotency,
data-preserving upgrade, unknown versions, partial failure, and rollback.

`0002` includes a one-time privacy-preserving migration of legacy billing
notes. `scripts/migrate_privacy_notes.py` is a separately operated dry-run
inspection/recovery command; `--apply` is an explicit data mutation.
It is **not** an alternative to the schema migration. Existing versioned
upgrade tests are in `backend/tests/test_migrations_v2.py`.

## Working-tree hygiene and evidence

Do not check in local environments, DB dumps, browser captures, signing
material, generated Android/Windows packages, or temporary test output.
A source package is built with `scripts/make_source_release.py`; its
SHA-256 inventory is generated *inside the archive*. A repository-root
`PACKAGE-MANIFEST.json` is not authoritative and should not be tracked.

Retain old validation evidence only with accurate provenance. In particular,
`docs/validation/v2-pytest-before-consent-fixture-fix/` records a **failed**
pre-correction run, while the historic `v2-pytest-current-shards/` index
documents the 0.2.0 follow-up. Neither can certify 0.2.2 or subsequent
commits. Avoid rewriting old evidence to look newer or greener. For
the current checkout, use the linked GitHub Actions run and fresh artifacts.

Android tests must use the actual `ir.hamava.reception` application identity.
The generated `com.getcapacitor.myapp` example test classes were removed:
the instrumented example asserted an obsolete application ID, and the unit
example did not test application behavior. The real
`ServerPolicyTest.java` remains.
