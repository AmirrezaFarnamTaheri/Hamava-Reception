# Hamava Reception · هم‌آوا

[فارسی](README.fa.md) | English

Hamava is a Persian-first reception platform for appointment-based organizations. It combines a transaction-safe scheduling service, right-to-left staff workspace, patient conversation, optional media workers, and Windows/Android companions. The authoritative clinic state resides on the server; clients do not maintain independent appointment databases.

**Current source version: 0.2.2.** This repository is a development/source candidate, **not** evidence of a signed public release or an approved live clinic, carrier, clinical workflow, payment processor, or speech model. Demo patients, clinics, prices, recordings and research inputs are synthetic. External services are disabled until explicitly configured and accepted.

## Quick start: isolated demo

Requirements: **Python 3.12**, **Node.js 24**, npm; FFmpeg for media decoding tests. PostgreSQL 16 is used for production; the single-machine demo uses SQLite. Run from the repository root:

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

On Windows use the equivalent Python virtual-environment activation and environment-loading commands; the shell example above targets POSIX systems. Open **http://127.0.0.1:8000** for the staff workspace or **http://127.0.0.1:8000/talk/bahar** for the fictional caller flow. Demo owner login: `owner@example.test` / `DemoReception2026!` (**never** use these credentials or demo mode for a real clinic). Text interaction needs no speech provider.

Start background jobs in a separate shell with the same environment:

~~~sh
python -m receptionist.worker
~~~

Keep `RUN_WORKER=false` in the API process when using this separate worker. Do not launch duplicate workers without understanding their scheduling and recovery behavior.

## Key capabilities

- Transactional holds, appointment creation/rescheduling/cancellation, occupancy conflicts, service buffers, idempotency, audit events and follow-up tasks.
- Persian and Jalali date handling, consent-first patient conversation, verified facts, explicit readback and safe handoff to staff.
- Tenant-scoped staff management, approved service/catalog policies, calendar authority, communication status, waitlists, deposits, refund/dispute records, privacy and provider controls.
- Optional AudioSocket/Asterisk, LiveKit, local speech and external processors behind independent approval, routing, cost and reconciliation controls.
- A shared React interface with Electron/Windows and Capacitor/Android hosts. The native shells connect to a deployed API; they are not standalone servers.

## Verification

~~~sh
python -m ruff check backend scripts services
python -m pytest -q
python scripts/protocol_conformance.py --output artifacts/backend/protocol-conformance.json
npm --prefix frontend run build
npm --prefix frontend run test:browser-launch
npm --prefix apps/desktop test
node scripts/check-versions.mjs
node scripts/check-docs.mjs
node --test scripts/check-docs.test.mjs
~~~

The GitHub verification workflow additionally runs isolated PostgreSQL invariants, browser journeys and container startup. Passing synthetic tests does **not** validate actual PSTN audio, bank settlement, physical devices, publisher signing or clinic authorization. Read the current CI results for the exact revision; archived reports are not current test proof.

## Documentation

Start at the [documentation index](docs/README.md), then use the [product](docs/product.md), [architecture](docs/architecture.md), [API](docs/api.md), [development](docs/development.md), [deployment](docs/deployment.md), [operations](docs/operations.md), [native clients and releases](docs/clients-and-releases.md), and [research](docs/research.md) guides. Every maintained guide has a corresponding `.fa.md` Persian version. The API's live OpenAPI specification is available from a running server at `/openapi.json` (and `/docs` when enabled).

**Production stays closed until named operators approve provider contracts, tenant settings, telephone handoff, privacy/clinical obligations, backup recovery and real end-to-end acceptance.** No generated artifact or self-attested checklist grants that approval.
