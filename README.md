# هم‌آوا · Hamava Reception

A Persian reception application with a transactional appointment calendar, a responsive RTL staff workspace, Windows and Android companions, browser conversation, optional local speech, private PBX/WebRTC workers, and accountable follow-up operations.

**Streaming/transfer development integration (separate from release):** this source
includes optional native Deepgram streaming STT, local Piper streamed PCM TTS,
LiveKit/AudioSocket worker wiring, and an Asterisk AMI handoff observer.
Streaming is disabled by default. The Asterisk fallback now uses a screened
pre-bridge staff acceptance (`Dial U()`, explicit staff DTMF, and AMI bridge
evidence); production still requires a qualified PBX, verified staff audio,
and a tested callback route before it can be called an accepted warm transfer. Refer to
`FINAL_ENGINEERING_REPORT.md`, `docs/streaming-pbx-integration.md`,
`CURRENT_CHECKPOINT.md` and `docs/remaining-external-acceptance.md` before activation. Neither 0.2.1
binaries nor publisher-signed installers are claimed by this development archive.

**Source candidate: 0.2.2 (not a signed or carrier-accepted release).** The source includes the application, native projects, automated release workflows, schema upgrade and retained verification evidence. The included tenants, patients, prices, audio tests and research fixtures are fictional. Real carrier service, external calendar write access, live payment/SMS accounts, clinical and privacy sign-off, representative telephone quality, and customer economics remain explicit launch gates. Read `FINAL_ENGINEERING_REPORT.md` and `docs/requirements-follow-on.csv` for the current evidence and remaining boundaries. `IMPLEMENTATION_REPORT.md` retains historical 0.2.0 evidence only.

The conversation engine is a bounded administrative state machine. It asks for verified fields, reads back the proposed action and commits through the calendar service. It does not diagnose, prescribe, pretend a callback is a connected transfer, or present a payment/SMS transport acknowledgement as final settlement/delivery. There is no generative language model or silent third-party browser speech API in the default application.

## Start the complete local demo

Requirements: **Python 3.12**, **Node.js 24** and npm. The optional speech service additionally needs FFmpeg and explicitly provisioned models. PostgreSQL 16 is the production database; SQLite is the single-machine development profile.

From the extracted project directory:

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade -r requirements-bootstrap.txt
python -m pip install -c requirements.lock.txt '.[test,media]'
cd frontend
npm ci
npm run build
cd ..
cp .env.example .env
set -a
. ./.env
set +a
python -m uvicorn receptionist.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Open **http://127.0.0.1:8000**. The API serves the built frontend and initializes the explicitly synthetic development fixtures. Start the durable operations worker in a second terminal with the same virtual environment and environment variables:

```bash
python -m receptionist.worker
```

Leave `RUN_WORKER=false` in the API process when using the separate worker. Running both is unnecessary. The outbox uses durable claims, and uncertain external outcomes require reconciliation.

| Demo account | Password | Access |
|---|---|---|
| `owner@example.test` | `DemoReception2026!` | Owner of both fictional clinics |
| `receptionist@demo.local` | `DemoReception2026!` | Receptionist at Bahar |
| `other@example.test` | `DemoReception2026!` | Receptionist at Niloufar |

The caller page is **http://127.0.0.1:8000/talk/bahar**. Text conversation works without any provider account. In demo mode, the interface identifies the synthetic OTP **246810**, simulated delivery and simulated settlement. Those shortcuts are disabled outside demo mode; production refuses to start with demo mode enabled.

Try a booking, a deliberate date/name correction, cancellation after contact verification, a handoff, a waitlist offer and acceptance, and a deposit booking in the second clinic. The demonstration doctor/service names are marked as examples. The demo is not a substitute for the production setup procedure below.

## What is implemented

The **calendar** enforces provider and shared-resource minute occupancy, unequal durations and buffers, working hours and practitioner shifts, lead times, holidays, closure intervals, booking horizon, signed short-lived offers, expiring holds, explicit confirmation, idempotent writes, approval/deposit states and atomic rescheduling. Appointment, occupancy, audit and logical notification records commit together. The voice-turn receipt shares the booking transaction, so a retry cannot lose the conversation result after a successful reservation.

The **Persian conversation** uses a frozen Tehran call clock, Jalali conversion, Persian/Arabic digits and character normalization, spoken phone digits, clarification of uncertain weekdays and AM/PM, current approved FAQs, correction handling, separate family bookings, separate reminder permission, human priority and an administrative urgency route. Replaying a booking result reads the current appointment state. The speech endpoint only synthesizes trusted stored replies and rejects stale booking audio.

The **staff workspace** groups daily reception work and clinic management, with a keyboard command menu and permission-aware routes. Its phone layout prioritizes Today, Tasks, Calls and More with chronological appointment cards. It includes clinic switching, booking/move/cancel, attendance, staff approval, atomic task ownership and lifecycle, notifications, waitlists, deposits, refund review, disputes, invoices, building allocations, partner credentials, team management, branding, pronunciation, policy history, disruptions, patient corrections and outreach. The controls center exposes provider capabilities, calendar authority, approved facts, routing, monetary rates and budgets, reconciliation, processing purposes, retention and on-call policy. Controls use the same authoritative API as caller channels.

The **native companions** connect to a clinic server after a credential-free compatibility check. Windows uses a sandboxed Electron host and an OS-encrypted, server-bound session vault. Android uses Capacitor and an Android Keystore AES-GCM vault, HTTPS-only networking and disabled app backup. A failed connection offers retry without discarding a valid session; explicit logout revokes the session and cannot resurrect an old credential after a failed vault deletion. The native hosts contain the interface, while clinic data and background work stay on the server.

The **integration control plane** implements expiring approved catalog facts, service-specific rules, package entitlements and partial-result booking series, versioned DID routing and exact human-destination allowlists. External-calendar adapters use a published capability/authority contract, durable write identities, read-back and revision reconciliation. Signed SMS intake can continue a scoped conversation. A capability that is configured but has no health observation remains unknown.

The **media layer** includes a real AudioSocket TCP bridge and a real LiveKit RTC worker. Both enforce bounded input, pacing, cancellation, call deadlines and human fallback. WebRTC rooms use scoped tokens and signed participant webhooks; worker leases contain fencing generations. The system records a human connection only after an authorized staff participant actually joins. PBX return routes remain under the reviewed Asterisk dialplan.

The **operations layer** includes transactional outbox delivery, verified SMS receipt polling, bounded attempts, quiet hours, opt-outs, reminders, patient responses, consented waitlists, refunds and disputes. Versioned supplier rates and exact monetary reservations govern supported provider operations; uncertain charges retain their liability until reconciliation. Automated media admission reserves its configured maximum duration before issuing access. A separately approved outbound-voice gateway has consent, destination and duration controls. Privacy controls separate purposes and processors, govern protected artifacts, record erasure evidence and enforce the stricter applicable processing-retention limit. Aggregate digests, safe logs, health/readiness, latency, on-call tasks and Prometheus output support operations.

The **research and business tools** include eligibility/rights manifests, text/audio review evidence, redaction spans, disjoint speaker/tenant splits, frozen datasets and withdrawals, independent-teacher comparison with required human-adjudication validation, WER/CER and exact-field evaluation, stage and per-tool latency distributions, slice/bootstrap reporting, an optional actual Whisper training adapter, staff-capacity simulation, cost sensitivity and matched pilot analysis. The included results are synthetic verification fixtures. No fine-tuning run, held-out quality advantage or customer ROI has been fabricated.

## Project map

| Path | Responsibility |
|---|---|
| `backend/receptionist/core.py` | Authoritative scheduling and occupancy invariants |
| `backend/receptionist/voice.py`, `locale.py` | Durable administrative conversation and Persian parsing |
| `backend/receptionist/operations*.py` | Outbox, reminders, waitlists, payment records, policy/task/disruption workflows |
| `backend/receptionist/partners.py` | Published identity, scoped partner keys, aggregate digests and building allocations |
| `backend/receptionist/providers.py` | Approved-provider boundaries and external result semantics |
| `backend/receptionist/core_*.py`, `models_core.py` | Approved facts, routing, capabilities, external calendars, series and runtime controls |
| `backend/receptionist/billing.py`, `privacy_controls.py`, `ops_controls.py` | Exact costs, reconciliation, purpose/processor governance, retention and alerts |
| `backend/receptionist/media/`, `media_api.py` | AudioSocket, WebRTC admission, leases and verified human participation |
| `backend/receptionist/security.py`, `telemetry.py` | Authentication, encryption, scope, safe logs and operational metrics |
| `services/local_speech/` | Optional bounded local Faster-Whisper/Piper gateway |
| `frontend/` | React, TypeScript, Vite and locally bundled Persian font |
| `apps/desktop/`, `apps/mobile/` | Electron desktop host and Capacitor Android companion |
| `.github/workflows/` | Verification, Windows installer/portable and Android APK/AAB jobs |
| `scripts/` | Migration, owner bootstrap, backup/recovery, load checks and research tools |
| `deploy/`, `compose.yaml`, `Dockerfile` | Deployment templates and private infrastructure configuration |
| `backend/tests/` | Behavior, concurrency, security, provider and research regressions |
| `docs/validation/` | Actual local validation evidence; read each file's limits |
| `docs/evidence/`, `fixtures/research/` | Explicitly synthetic research/economics examples |

## Enable optional speech deliberately

Install the optional dependencies under the supplied constraints:

```bash
python -m pip install -c requirements.lock.txt '.[speech]'
```

Provision a compatible Faster-Whisper model directory and a Persian Piper `.onnx` voice with its `.onnx.json` sidecar **outside the source package**. Review the code, weights, training-data and voice rights independently. The application does not download weights during calls and does not include the test models in its source archive.

Set a randomly generated `SPEECH_GATEWAY_TOKEN` of at least 32 characters in both processes. Set `WHISPER_MODEL_PATH`, `PIPER_MODEL_PATH`, the reviewed `SPEECH_MODEL_RIGHTS_REVIEWED=true`, `SPEECH_PROCESSOR_APPROVED=true`, a truthful processing location, `SPEECH_GATEWAY_URL`, and its exact host in `APPROVED_PROVIDER_HOSTS`. For a **private local** HTTP service, explicitly set `ALLOW_LOCAL_HTTP_PROVIDERS=true`.

Set `SPEECH_ASR_VERSION` and `SPEECH_VOICE_VERSION` to the actual reviewed deployment identifiers. Leave `not_recorded` when unknown; a filename or generic placeholder is not evidence of a verified model revision.

```bash
python -m uvicorn services.local_speech.app:app --host 127.0.0.1 --port 8090 --no-access-log
```

Restart the API after changing configuration. The caller interface then offers microphone input and trusted-reply playback. Model access alone does not establish production quality. The real local CPU smoke test produced an imperfect Persian transcript and multi-second processing, so the blueprint's sub-second median target is an unmet gate.

The cache is limited to the exact static greeting, keyed by tenant, policy, text, voice version and speed. Dynamic patient readbacks are not cached. Processor approval is checked even on a cache hit. Unsupported, empty, malformed, stereo, wrongly sampled or truncated TTS WAVs are rejected.

## Production deployment

Read **`docs/deployment-runbook.md`** before enabling traffic. The deployment requires an owned hostname, explicit HTTPS origins, PostgreSQL, durable and independently backed-up encryption/lookup keys, a private metrics token, approved providers, reviewed tenant configuration and staffed fallback. A fresh owner starts with reception paused and no working hours.

```bash
python scripts/generate_env.py --host reception.your-domain.example
docker compose --env-file .env.production build
docker compose --env-file .env.production --profile https up -d
docker compose --env-file .env.production exec api python scripts/admin.py \
  --email owner@your-domain.example --clinic-name 'نام مرکز' --slug your-clinic
```

Replace the example domain with a real hostname you control. The generator creates `.env.production` once with private permissions and refuses to overwrite it. Store the keys in the approved recovery vault. The compose migration job initializes schema `0002` or upgrades an intact `0001` deployment before the API and jobs start; existing unversioned, partial or drifted schemas are rejected. The upgrade preserves existing records and encrypts legacy free-text billing notes without changing financial amounts. Docker templates were inspected and parsed locally; Docker execution requires the supplied CI/container build gate on a Docker host.

Optional compose profiles are `speech`, `pbx` and `webrtc`. The `webrtc` profile runs the application worker; it does **not** secretly provision a LiveKit server or a carrier trunk. The Asterisk and LiveKit/SIP configurations are reviewed starting templates, with explicit placeholders and deployment boundaries.

## Verification

```bash
python -m pytest -q
python -m ruff check backend scripts services
cd frontend
npm ci
npm run build
npm audit
cd ..
```

For the independent PostgreSQL contention test, set `TEST_DATABASE_URL` privately to an **isolated test database**, then run:

```bash
python scripts/postgres_stress.py --acknowledge-isolated-test-database \
  --contenders 100 --output docs/validation/postgres-contention.json
```

The harness creates its own randomly named schema, uses independent connections and removes only that schema. Its 100-way slot/hold/idempotency/resource tests establish database invariants; they do not establish 100 simultaneous intelligible telephone conversations.

The real media smoke scripts require a configured **loopback demo** with the local speech gateway, the corresponding media server/worker, private credentials, and the synthetic input WAV:

```bash
python scripts/livekit_smoke.py --acknowledge-synthetic-demo \
  --audio /path/to/synthetic.wav --output docs/validation/livekit-loopback.json
python scripts/audiosocket_smoke.py --acknowledge-synthetic-demo \
  --audio /path/to/synthetic.wav --output docs/validation/audiosocket-loopback.json
```

They do not place a carrier call. The AudioSocket check also verifies its local application database, so its `DATABASE_URL` must match the demo API. Do not point synthetic tools at customer data. In the development environment used for validation, the native RTC library required direct loopback signaling because its proxy handling differed from HTTPX. The shipped worker does not override deployment network policy.

See `docs/research-workflow.md` for the exact curation, evaluation, economics, pilot and optional training commands. Each fixture output identifies its synthetic provenance and limits.

## Desktop, Android and automated releases

See **`docs/native-apps-and-releases.md`** for installation, clinic connection, native security, local build commands and GitHub signing configuration. Windows builds create an assisted NSIS installer and a portable EXE. Android builds create an installable development APK, a release APK and an Android App Bundle. Release signing requires the organization's publisher certificate or Android keystore; none is embedded in the source.

The verification workflow checks server behavior, PostgreSQL invariants, the shared interface, browser journeys, native bridge contracts and container startup. The release workflow consumes the verified interface bundle for both native platforms and produces SHA-256 manifests. Optional signed draft releases are separate from ordinary test-artifact builds. An authorized repository is required to execute these workflows remotely.

## Scope and release decisions

The internal calendar and the external-authority adapter contract are implemented. An external provider must implement the documented conditional/idempotent write/read-back contract and pass clinic-specific acceptance before it becomes that clinic's authority. No Paziresh24, Doctoreto, EHR, Google, Bookly or insurer write permission is assumed. Native social-platform access requires an actual platform adapter and account. The outbound-voice gateway is implemented and disabled by default; live calls require its approved provider, consent and destination policy.

The selected PSTN integration is Asterisk AudioSocket. LiveKit browser RTC is implemented and locally exercised; the optional LiveKit SIP recipe is not a claim that tenant-aware SIP dispatch and a production carrier trunk have been deployed. Real warm transfer, mobile-device coverage, external account operations, local legal requirements and representative telephone accuracy must pass their named gates before launch.

The full revised blueprint is `docs/blueprint-revision.md`. All original major sections and appendices are retained. `docs/launch-playbook.md` contains the discovery, pilot, clinical/privacy review, staffing, commercial, incident and recovery worksheets. `docs/requirements.json` is the item-level source of truth for what is verified, what is partial and what needs external evidence.
