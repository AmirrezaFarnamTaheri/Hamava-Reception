# Hamava Reception

**A Persian reception desk for appointments, calls and follow-up.** [فارسی](README.fa.md)

Hamava puts the work of a reception team in one place: an appointment calendar, patient conversations, staff tasks, messaging, deposits and a clear route back to a person when automation cannot finish the job. The web workspace, Windows application and Android companion connect to the same server and share the same clinic records.

The current source version is **0.2.2**. You can run the complete text-based demo locally. Speech, telephony, calendar providers, SMS and payments are separate integrations that a clinic enables only after configuring and testing them. The repository supplies code and packaging workflows; it is not a preconfigured live reception service.

## Try Hamava in five minutes

You need Python **3.12**, Node.js **24** and npm. These commands are for a POSIX shell, from the repository root:

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

Open **http://127.0.0.1:8000**. The demo owner is `owner@example.test` with password `DemoReception2026!`. You can also start a visitor conversation at **http://127.0.0.1:8000/talk/bahar**. The example clinics, people, appointment records and message/payment responses are fictional. They let you explore the complete workflow without connecting real services.

Open another terminal, activate the same environment and load `.env` before starting the background worker:

~~~sh
python -m receptionist.worker
~~~

The API process should keep `RUN_WORKER=false` while the separate worker is running. On Windows, use the equivalent virtual-environment activation and environment-variable commands. PostgreSQL **16** is used for production; the demo uses local SQLite. FFmpeg is needed for certain speech-decoding tests.

### A useful first walkthrough

1. Sign in and switch between the fictional clinics **Bahar** and **Niloufar**. Notice that the selected clinic controls which appointments, settings and tasks you can see.
2. Open the appointment calendar. Choose a practitioner and service, check available slots, create a hold, then confirm a booking. A hold expires; it is not a completed appointment.
3. Move or cancel the booking. Hamava checks its current version and records the change instead of overwriting whatever happened in the meantime.
4. Open the staff task queue and inspect an unresolved handoff or notification. A request marked *pending* should stay pending until there is evidence of the next step.
5. Open the visitor page, give the displayed processing consent, and ask to book an appointment in Persian. Try an ambiguous date or a correction and see how the conversation asks for clarification.

## Decide what to explore next

The demo is most useful when you follow one request through its entire life. Start by booking a fictional patient, then try a change that makes the original screen stale. The conflict is deliberate: two people should not be able to overwrite each other's work without seeing what changed.

If you are approaching Hamava with a particular job in mind, use this route:

| Your job | First stop | What to check |
| --- | --- | --- |
| Receptionist or clinic owner | [Product guide](docs/product.md) | Booking states, staff handoff and a typical day |
| Developer | [Development handbook](docs/development.md) | Code map, repeatable tests and safe schema changes |
| Client or integration developer | [API guide](docs/api.md) | Scope, request fields, idempotency and error handling |
| System operator | [Deployment guide](docs/deployment.md) | Configuration, health, worker startup and restore drills |
| Release engineer | [Native release guide](docs/clients-and-releases.md) | Windows/Android packaging, signing and device checks |
| Researcher | [Research guide](docs/research.md) | Dataset rights, speech evaluation, capacity and pilot measures |

The demo uses fictional records and provider responses. You can use it to check how the interface and server handle a workflow; it does not establish what an actual phone carrier, payment provider or clinic will do. The [operations guide](docs/operations.md) describes the additional checks needed for those integrations.

## What lives where

| Part | Job | Code |
| --- | --- | --- |
| Reception server | Scheduling, identity, permissions, tenant policies and authoritative business state | `backend/receptionist/` |
| Background worker | Reminders, delivery, reconciliation and operational follow-up | `backend/receptionist/worker.py` |
| Shared interface | Persian RTL desk, administration and public conversation | `frontend/` |
| Desktop app | Electron host, clinic connection and protected session storage | `apps/desktop/` |
| Android app | Capacitor host, HTTPS connection and device-backed session storage | `apps/mobile/` |
| Speech and media | Optional local speech, AudioSocket, LiveKit and Asterisk handoff | `services/local_speech/`, `backend/receptionist/media/`, `deploy/asterisk/` |
| Infrastructure | Docker, Caddy, database, observability and CI | `compose.yaml`, `deploy/`, `.github/workflows/` |

The backend owns appointment writes, contact permissions and the notification outbox. Clients never become independent calendars. An accepted request from a remote provider is not automatically the same thing as an appointment saved, an SMS delivered, money settled or a staff call connected. These distinctions are reflected in the interface and in the underlying state records.

## Run the checks

After installing the dependencies above:

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

`.github/workflows/verify.yml` additionally checks an isolated PostgreSQL database, browser journeys and the deployable container. The native release workflow has separate Windows and Android jobs. For the exact results of a commit, read its Actions run rather than an old report.

## Where to go next

The [documentation index](docs/README.md) gives each guide a clear purpose. For a first deployment, read [Deployment](docs/deployment.md), then [Operations](docs/operations.md). To understand how a booking or an integration works, start with [Architecture](docs/architecture.md) and [API](docs/api.md). Developers should use [Development](docs/development.md); native packaging is covered in [Clients and releases](docs/clients-and-releases.md).

**Before serving a real clinic**, prepare its production configuration, tested backups and staffed fallback. Use [Clinic acceptance](docs/clinic-acceptance.md) for the required synthetic checks and [Provider integrations](docs/provider-integrations.md) for real provider tests. [Operations](docs/operations.md) covers the team's decision to begin service.
