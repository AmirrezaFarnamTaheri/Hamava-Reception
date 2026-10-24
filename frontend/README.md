# Hamava reception interface

Persian RTL staff console and public receptionist built with React, TypeScript and Vite. The interface reads and changes the real FastAPI application through `/api/v1`. It does not substitute sample data when a request fails.

## Run and build

Use the Node.js and Python versions and backend startup instructions in the project README. With the API listening on `127.0.0.1:8000`:

```bash
npm ci
npm run dev
```

Vite proxies `/api/v1` to the local API. For the complete same-origin application:

```bash
npm run typecheck
npm run build
```

The API serves `dist/` when built. The seeded owner account shown on the login page belongs only to the fictional demo. Production accounts are created through the deployment bootstrap and owner-controlled team administration.

The desktop shell uses grouped navigation and Control/Command + K for authorized destinations and actions. The mobile companion uses Today / Tasks / Calls / More, with today's schedule before secondary metrics and chronological appointment cards. `/connection` guides the first service connection; `/setup` links the real center configuration steps. Desktop and Android packages use the same compiled interface and the explicit server connection in `src/platform.ts`; Android requires HTTPS. Packaging, signing and release commands are documented in the parent project's native-client documentation.

## Product areas

The staff console includes current work, appointments and attendance, signed slot selection, audited corrections, approval and deposit states, tasks and verified takeover, message status and retry, waitlists, schedule disruptions, outreach consent, follow-up enrollment, payment/refund/dispute records, billing, aggregate building contracts, usage, stage latency and daily digests. Settings support clinic creation, providers and shifts, services/resources, approved answers, operating modes, identity and pronunciation, permissions, privacy, policy history, payment publication and clinic launch review.

Partner accounts get a separate aggregate view. Clinic changes replace the scoped staff credential and remount clinic state. Staff authorization is still enforced by the API for every operation.

Public routes:

| Route                 | Purpose                                                                                                           |
| --------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `/talk/:slug`         | Processing consent, typed conversation, optional microphone and optional live RTC, human request and explicit end |
| `/respond/:id#secret` | Private appointment response link; the fragment is removed from the address bar after it is held in memory        |

Deposit terms display the published version and payment deadline. Actual deposit bookings require a separate explicit acceptance of the current terms. Merchant configuration is displayed independently from live settlement verification. Clinic readiness requires a named review, five specific checks and evidence references; the form does not manufacture production attestations.

## Voice and privacy behavior

The server advertises `audio_input`, `audio_output` and `livekit` capabilities. Microphone and live-call controls become available only when the corresponding approved service and worker are configured. Text conversation remains available when speech is unavailable. The application does not use the browser's third-party speech recognition service.

Microphone capture starts after a deliberate action. Short recordings use `MediaRecorder`, transient in-memory blobs, an idempotent request identifier and the authenticated audio endpoint. Recording stops at the duration limit or on end, page hiding and unmount; media tracks are stopped. A failed recording can be retried with its same identifier while the page remains open. Nothing silently persists the raw audio for later training.

Trusted reply audio is fetched using the session bearer token and a server turn ID. Pending playback requests are canceled on end, object URLs are revoked, and late responses cannot restart playback. LiveKit loads only on explicit use, uses scoped room admission and processes trusted server data. Disconnect stops publication and restores typed input.

Caller and staff controls distinguish initial connection, connected, media/signaling recovery and terminal disconnect. Initial connected status waits for microphone setup; recovery preserves mute state, disables microphone changes and keeps an exit available. Caller text input becomes available after leaving the live room. Retired room events and delayed microphone operations cannot change a replacement room's status. These lifecycle bindings have targeted event-contract coverage; actual-network reconnect and physical mobile continuity remain unqualified.

Staff credentials live in `sessionStorage` for the browser tab and use the platform's secure credential bridge in packaged clients when available. The runtime reports storage failure and protects logout from restoring an old session. Public session tokens and response-link secrets stay in memory. Partner API keys are shown once and never stored in browser storage. There is no service worker or offline patient-record cache. The manifest supplies application identity; it is not an offline booking guarantee. An offline notice and recoverable request errors replace any claim of a successful offline reservation.

Before processing consent, the public page renders the server's current privacy notice and configured transcript retention period. It explains that raw audio is not retained or used for training, while necessary encrypted conversation text and results support reception and request recovery. Scheduled cleanup after the retention period is distinct from necessary appointment records. The same notice remains accessible during conversation, with contact through reception for deletion requests or service without the assistant.

Starting a conversation sends the exact displayed notice fingerprint. A changed notice receives a server rejection, refreshes the visible disclosure and clears consent; a new explicit choice is required before another start request. An unavailable or missing current fingerprint prevents startup.

Fonts are bundled locally from the licensed Vazirmatn package; the license is in `public/font-license.txt`. No remote font or image request is needed.

## Browser verification

The scripts use Playwright and a packaged headless Chromium. `CHROMIUM_EXECUTABLE` can select another installed Chromium executable. The test target is `HAMAAVA_BASE_URL` (default `http://127.0.0.1:8000`) and outputs go to `HAMAAVA_ARTIFACTS_DIR` (default `/tmp/hamaava-ui-validation`).

Build first, start the backend, and run scripts against an isolated synthetic demo. Do not rebuild `dist/` while a browser run is using its hashed chunks. Mutation suites verify the API's explicit demo mode before creating fictional records. They must not be pointed at customer data.

```bash
npm run format:check
npm run test:ui
npm run test:workflows
npm run test:conversation
npm run test:extensions
npm run test:outreach
npm run test:release
npm run test:latency-labels
npm run test:waitlist-deposit
npm run test:privacy-notice
npm run test:rtc-lifecycle
npm run test:companion
npm run test:platform
```

For isolated, reproducible runs, use the parent project's `scripts/ci_ui.py` with its Python environment. It starts a fresh synthetic database and API for each named suite, serves the already-built UI and stops the service afterward. Example from the project root:

```bash
python scripts/ci_ui.py test:companion test:privacy-notice test:ui --port 8137
```

The helper uses a 30-second tool timeout for functional journeys on shared CI hardware; it does not change the production timeout or measure latency SLOs. Reports and diagnostic screenshots are written under `artifacts/ui/test-<suite>/`. Do not rebuild while those tests run. The suites change synthetic data and deliberately exercise booking, cancellation, approval, simulated payment, consent and owner administration. Each suite creates its own required fixtures. They do not send external digests or record successful real bank transfers.

`test:companion` exercises keyboard action search, 390/320px daily work, bottom navigation, actual budget/rate/privacy/on-call/service-policy writes, role-aware navigation, and visible service-error recovery. Its external-calendar response fixture verifies cached/unknown/verified presentation without qualifying a real remote calendar. `test:privacy-notice` changes an actual synthetic retention policy after display to verify stale-consent rejection and renewed consent. `test:platform` separately exercises the server-connection/runtime contract.

`test:latency-labels` creates a successful slot-search trace through an actual synthetic conversation, checks the API's nine stage keys, and verifies distinct Persian labels and actual counts at 1440/390/320px. Stages without observations keep empty percentiles. These are local successful tool-dispatch measurements, not first-audible, model-stage, provider or latency-SLO qualification.

`test:waitlist-deposit` exercises both immediate and resumed waitlist acceptance, separate current-terms consent, pending-payment readback and a no-deposit regression. It deliberately injects one stale-terms rejection to verify that the UI fetches actual current terms and clears acceptance before retrying. Successful reservations use the real demo API; the test does not submit a payment intent or simulate settlement. The isolated Niloufar fixture must retain an enabled synthetic deposit policy. The CI helper places only its newly created synthetic tenants' quiet window six hours ahead, so execution time does not accidentally defer the offers; production policy and quiet-hour enforcement are unchanged. A standalone run against a manually started demo still needs a permitted outreach window.

`test:rtc-lifecycle` serves the already-built frontend on a temporary loopback port and injects explicitly synthetic API and LiveKit Room fixtures. It exercises the actual caller and staff components through SDK event contracts, including reconnection, signaling recovery, terminal disconnect, delayed microphone setup, old-room callbacks and connection failure ordering. It needs no backend or media services and closes its local server. Its twelve checks are event-to-UI evidence, separate from the live transport suites and from actual-network reconnect qualification.

With the optional speech service, and for RTC the actual local LiveKit server and reception worker, provide a **synthetic** input WAV:

```bash
HAMAAVA_TEST_AUDIO=/path/to/synthetic.wav npm run test:audio
HAMAAVA_TEST_AUDIO=/path/to/synthetic.wav npm run test:live
```

The main audit covers desktop and 390/320px viewports, axe WCAG checks, document overflow, errors and failed API responses. The common workflow suites inspect actual synthetic server results, response-link secrecy, replay of a lost response and explicit booking confirmation. Optional audio/live suites separately inspect microphone lifecycle, trusted audio bytes and actual local RTC connection; they require the configured services described above.

Current companion-release evidence is retained in `docs/validation/v2-browser-*.json`, with requirement scope in `v2-frontend-requirement-evidence.json`. Every report identifies the bundle it actually tested. `v2-ui-source-equivalence.json` records the preceding three-color correction; `v2-ui-latency-labels-source-equivalence.json` records the final five-label change, unchanged application files, immutable build manifest and related test-contract update. Earlier suites retain their original bundle and script hashes. The replaced release report is preserved as `v2-ui-release-before-latency-labels.json`; it is not counted twice. `v2-ui-setup-contrast.json` retains the six before/after guide audits. Interrupted attempts and their resolutions remain in `v2-ui-interrupted-runs.json`. The earlier `browser-*.json` files are historical release evidence, including optional media runs; they are not added to the current totals. Screenshots remain internal test artifacts outside the source deliverable.

Headless Chromium viewport checks do not establish iOS Safari, Android hardware, in-app browser, screen-reader usability, PSTN quality, carrier routing or live payment/SMS readiness. These remain the device/provider checks in the project's launch register. Synthetic speech results also do not establish recognition quality for representative patients.
