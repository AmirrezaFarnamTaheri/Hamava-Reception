# Developer handbook

[فارسی](development.fa.md) · [Documentation](README.md)

This guide is for the person changing the source, reviewing a pull request or investigating a failed test. The central rule is simple: **the API and database decide business outcomes; interfaces and external adapters report what they can actually observe**.

## Set up a repeatable local workspace

Hamava uses Python **3.12** and the locked Python dependency constraints, Node.js **24** and separate npm lockfiles for web, desktop and Android. For the standard demo on a POSIX shell:

~~~sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade -r requirements-bootstrap.txt
python -m pip install -c requirements.lock.txt '.[test,media]'
npm --prefix frontend ci
npm --prefix frontend run build
cp .env.example .env
set -a; . ./.env; set +a
python -m uvicorn receptionist.main:app --host 127.0.0.1 --port 8000 --no-access-log
~~~

In a second shell use `python -m receptionist.worker` with the same environment. Keep `RUN_WORKER=false` in the API process if you start the separate worker. For browser development you can use `npm --prefix frontend run dev`; Vite proxies `/api` to the local API. On Windows use the corresponding environment commands.

Local runs use synthetic clinics and SQLite by default. The production stack uses PostgreSQL **16**; concurrency checks therefore need a separate PostgreSQL test database. Do **not** run destructive experiments, migrations or UI mutation suites against customer data.

## Find the right code first

| Change | Start here | Regressions to consider |
| --- | --- | --- |
| Booking, holds, availability | `backend/receptionist/core.py`, `schemas.py` | Overlapping resources, expiry, idempotency, stale versions |
| Caller dialogue, Persian dates | `voice.py`, `locale.py` | Turn replay, corrected details, ambiguous dates, human fallback |
| Policy and calendar authority | `core_policy.py`, `calendar_bridge.py` | Publication permissions, remote unknown outcomes and readback |
| Staff tasks, message dispatch | `operations*.py`, `messaging_controls.py` | Durable outbox, quiet hours, duplicate delivery, ownership |
| Deposits and costs | `payment_policy.py`, `billing.py` | Terms acceptance, exact amount, reservations, reconciliation |
| Access and retention | `security.py`, `privacy_controls.py` | Current tenant membership, withdrawal, deletion and redaction |
| Media/call takeover | `media_api.py`, `media/`, `deploy/asterisk/` | Cancellation, worker fencing, human bridge evidence |
| Interface behavior | `frontend/src/`, `frontend/scripts/` | Real API result, RTL layout, keyboard flow, connection recovery |
| Native host security | `apps/desktop/`, `apps/mobile/` | Vault, HTTPS, sign-out, device identity |
| Packaging | `.github/workflows/`, `scripts/collect-release.mjs` | Release tags, signatures, checksums and artifact filenames |

The project does not use the UI as a second implementation of scheduling, payments or roles. Where an interaction feels awkward, fix the presentation without bypassing the server's state transitions.

## Test before changing behavior

For a bug, first add a regression demonstrating the failure. Keep the new test as close as possible to the affected contract, then change the implementation and run the focused test before the broader suite. When changing a booking operation, prove the correct result under a conflicting request and a retry—not just the happy path. When changing media, cover disconnect and late events. For an external provider, test accepted, rejected, timed out and unknown outcomes separately.

The normal checks are:

~~~sh
python -m ruff check backend scripts services
python -m pytest -q
python scripts/protocol_conformance.py --output artifacts/backend/protocol-conformance.json
npm --prefix frontend run build
npm --prefix frontend run test:browser-launch
npm --prefix apps/desktop test
node scripts/check-versions.mjs
node --test scripts/check-docs.test.mjs
node scripts/check-docs.mjs
~~~

For a browser regression, **build the frontend first** and then run the isolated suite orchestration:

~~~sh
python scripts/ci_ui.py test:ui test:workflows test:conversation test:privacy-notice --port 8137
~~~

`ci_ui.py` starts a disposable synthetic server for each named suite. Other available suites cover extensions, release UI, outreach, waitlist/deposits, RTC lifecycle, companions, platform connection and latency labels. CI runs the larger matrix defined in `.github/workflows/verify.yml`.

For PostgreSQL locking, run the dedicated tests only after setting `TEST_DATABASE_URL` to an isolated test database:

~~~sh
python scripts/postgres_stress.py --acknowledge-isolated-test-database --contenders 40 --output artifacts/backend/postgres.json
python scripts/production_smoke.py --acknowledge-isolated-test-database --output artifacts/backend/production.json
~~~

These validate software invariants; they are not telephone-call or deployment-load benchmarks.

## Schema changes: preserve the upgrade path

`backend/receptionist/migrations.py` defines the existing **0001 → 0002** path. Version `0001` represents installations that must still be upgraded; deleting it because a fresh database can create `0002` would strand those installations.

For a new schema version, write a forward-only migration and tests for clean creation, upgrade from each supported version, partial failure, unknown versions, data preservation and restart/idempotency. On a real database: stop writers, take a tested backup, run `python scripts/migrate.py`, verify records, then resume. Do not silently stamp a damaged schema or change production tables to make one test pass. The operator-only `scripts/migrate_privacy_notes.py` is not a replacement for migration.

## Files that should not be in a commit

Generated test output belongs under `artifacts/` or in CI artifacts linked to a run. Keep database dumps, recordings, credentials, model weights, private keys, signed packages, screenshots and JUnit XML out of Git. Source-only archives are built by `scripts/make_source_release.py`; their manifest is generated inside the ZIP. Rebuilding a historical report in the source tree does not make it current evidence.

A good PR describes **what behavior changed, why, how it was tested and what remains external**. Avoid lists of undocumented assertions such as “fully production ready.” Include exact commands, affected components and the relevant CI run.

## Keeping the handbook current

Every maintained Markdown guide has an English file and a `.fa.md` translation. Edit both in the same PR. Translate the explanation, but leave endpoint names, file paths, config keys and executable snippets intact. Check the pair and local links with `node scripts/check-docs.mjs`. Release notes are tied to the package version via `node scripts/check-versions.mjs`.

Use [Architecture](architecture.md) for responsibility boundaries, [API](api.md) for request contracts, [Deployment](deployment.md) for release setup and [Operations](operations.md) for real-world procedures.

## Removing dead code safely

Run the source inventory from the repository root:

~~~sh
python scripts/audit_dead_code.py --check --output artifacts/dead-code/report.json
~~~

The check follows Python imports from FastAPI, workers, scripts and tests; JavaScript/TypeScript imports and lazy routes from the web and native entry points; and Android Java references from the manifest and Capacitor registration. It also reports unreferenced top-level Python functions and frontend exports. Ruff catches unused Python imports and locals; TypeScript's `noUnusedLocals` and `noUnusedParameters` catch ordinary frontend dead declarations. CI runs the source graph as an independent fast job and separately verifies server, browser, desktop and container behavior.

A name that looks unused can still be loaded through a framework. Before deletion, inspect FastAPI decorators, SQLAlchemy model registration, migrations, Electron preload paths, Java/Android manifest entries, browser test fixtures and the package/Actions commands that start operator tools. A script manually run for recovery remains a supported entry point even if no other Python file imports it.

The repository-wide audit found one abandoned screenshot-preview utility and two unreferenced functions; those were removed. Essential registrations, all existing database migration versions, native bridges and RTC test fixtures remain. The machine-readable audit output is generated under `artifacts/`, not committed. For each later cleanup, remove only candidates with verified references and run the relevant regression suite.
