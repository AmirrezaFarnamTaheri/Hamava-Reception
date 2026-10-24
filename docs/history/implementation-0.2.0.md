> **Historical evidence — Hamava 0.2.0 only.** This file documents the earlier source snapshot and cannot be used as passing evidence for the current 0.2.2 source candidate. For current changes, tests, gaps, and release limits, read `FINAL_ENGINEERING_REPORT.md`.

# Hamava Reception 0.2.0 — implementation and delivery report

**Delivery date:** 23 October 2026  
**Product:** هم‌آوا / Hamava Reception  
**Scope:** revised blueprint, implemented reception platform, responsive staff experience, Windows desktop application, Android companion, build/release automation and retained verification evidence.

## 1. Delivery and its limits

Version 0.2.0 extends the existing application into a coherent reception workspace with purpose-specific privacy controls, provider and calendar governance, monetary spending controls, operational recovery and native staff companions. The original seven blueprint phases and all 263 requirement IDs remain traceable. Their acceptance statements have not been shortened to make the completion count look better.

The deliverable contains the application source, dependency locks, native projects, GitHub workflows, revised blueprint, API contracts, deployment and recovery instructions, synthetic fixtures, research tools and the requirement register. Windows and Android package results and exact hashes appear in the verification section below. Companions connect to the same clinic API; installing a companion does not create a production backend or make a telephone provider available.

This is a locally verified pilot release. No real clinic was activated, patient data imported, supplier message sent, payment collected, telephone number provisioned, repository published or signed production application submitted. Real operator identities, clinic approvals, provider accounts, publisher certificates, device acceptance and field results remain the deploying organization's inputs. Some advanced capabilities remain partial; these are named in section 10 and in the register rather than represented as completed features.

The source archive excludes credentials, databases, signing keys, dependency directories, downloaded speech models, recordings and internal browser screenshots. Included clinics, contacts, prices, messages and research measurements are synthetic fixtures.

## 2. Blueprint refinements

The revision preserves the supplied major sections and appendices. It adds decisions, acceptance evidence, operational worksheets and explicit boundaries that make the blueprint executable:

- **One declared calendar authority per clinic.** Internal booking and the external-calendar protocol have explicit authority revisions. A conversational promise or HTTP timeout is never sufficient booking evidence.
- **Provider approval before use.** Capabilities, model or endpoint revision, processing region, data terms and verification references are represented separately from credentials. A configured but unobserved dependency is reported as unknown.
- **Money reserved before supplier work.** Approved rates and currencies govern supported operations. Unknown provider outcomes retain their possible financial liability until reconciliation.
- **Consent tied to what was shown.** Real public intake requires the fingerprint of the current displayed processing notice. A changed notice requires refresh and fresh consent; disabling processing also stops existing text turns.
- **Honest outcome states.** Requested handoff differs from human connection; accepted SMS differs from delivery; pending calendar write differs from confirmation; attempted calls differ from answered and resolved calls.
- **Separate product, deployment and field evidence.** Unit and browser checks, actual local transports, physical devices, live suppliers, clinical/privacy approval and commercial outcomes have distinct gates.
- **Native delivery as part of the product.** The desktop workspace and phone companion share the authoritative API and permission model, while their platform hosts handle server connection and protected session storage.

References in the supplied blueprint to an earlier eleven-document consolidation remain source history. Only the supplied consolidated document was available here. Historical supplier prices, legal assertions and market benchmarks remain dated research pointers; the revision does not convert them into current contractual or legal conclusions.

## 3. Product and user experience

### Reception workspace

The Persian RTL interface uses a bundled Persian font, consistent spacing and contrast, explicit asynchronous states and permission-aware navigation. Desktop navigation groups daily reception work separately from management. A command menu supports keyboard navigation and Ctrl/Cmd+K access to common destinations.

Daily work centers on today's appointments, pending staff tasks, call history and clear follow-up actions. Appointment views use chronological mobile cards at narrow widths. Tasks support ownership and lifecycle changes. Calls distinguish conversation status and staff handoff state. Management screens expose clinic facts, catalog/routing, purpose and processor policy, cost controls, reconciliation, readiness and on-call configuration without requiring source edits.

Clinic setup is a guided flow. Real login is blank by default; synthetic account shortcuts appear only when the API explicitly advertises demo mode. Network failure during session validation offers retry and preserves the session. Actual logout revokes the current server token when reachable, clears the local credential and prevents silent restoration. Offline logout prevents automatic restoration but cannot establish remote revocation while the server is unreachable.

### Phone companion

The Android companion has a focused bottom navigation: **Today, Tasks, Calls and More**. Secondary administration lives in More, subject to the same server permissions. Narrow layouts are exercised at 320 and 390 pixels; loading, empty, error and permission states are part of the browser matrix.

The native connection screen verifies a server through a credential-free compatibility request before accepting it. Android requires HTTPS, including loopback. The companion does not ask the user to weaken certificate validation or enable cleartext traffic. The web/native frontends do not grant permissions by hiding a button; the server checks the current actor, tenant and capability on every protected action.

### Accessibility evidence

Automated checks inspect contrast, labels, interactive semantics, viewport overflow and browser errors. They found and drove corrections to shared navigation labels and command-menu structure. Such checks are useful evidence but do not establish complete accessibility on physical devices or with every assistive technology. Exact final screen counts and outcomes are retained with the browser results.

## 4. Implemented phases

| Blueprint phase | Implemented application and operating deliverables | Remaining integration and acceptance |
|---|---|---|
| **0 — Groundwork** | Revised blueprint and full register; clinic setup; configuration validation; permission and capability control; discovery, pilot, vendor, pricing, privacy, clinical and incident worksheets. | Accountable real people, clinic authority, supplier contracts, qualified approval, observed demand and an agreed pilot. |
| **1 — Browser and booking** | Persian responsive workspace; text and microphone caller page; durable administrative state machine; approved expiring facts; Tehran/Jalali interpretation; transactional availability, holds, booking and moves; service exceptions; packages and partially successful series. | Representative callers, real clinic UAT, physical-device accessibility and measured speech quality. |
| **2 — Telephone operations** | AudioSocket and LiveKit workers; PBX templates; scoped versioned DID routing; approved human destinations; leases, admission and duration bounds; monetary media reservations; readiness, migration and recovery. | Selected-provider native speech streaming and complete carrier transfer-event adapters; owned carrier/DID, physical PBX acceptance, public TLS/ICE/TURN, acoustic performance, staffed pickup and deployed media shutdown/recovery drills. |
| **3 — Revenue and attendance** | Durable notices, signed SMS continuation and receipt handling, quiet hours, reminders, consented waitlists, deposit terms, merchant-bound payment verification, refund/dispute evidence, attendance and default-disabled approved outbound voice gateway. | Actual SMS delivery, merchant onboarding and settlement, carrier capabilities, receipt reconciliation and clinic-confirmed attendance. |
| **4 — Building hub** | Tenant roles, staff ownership/timers, pooled allowances, exact usage and rate accounting, budget reservations, vendor invoice reconciliation, append-only corrections, attribution, owner/building views and on-call tasks. | Independent clinic permissions, real staffing and cost inventory, operational on-call coverage and demonstrated customer economics. |
| **5 — Channels and partners** | Partner-scoped keys/exports, external-calendar protocol and reconciliation, authorized voice-note path, pronunciation/branding, approved multilingual fallback scripts, aggregate digest and opt-in controls. | Independently operated calendar acceptance, actual platform accounts, qualified multilingual pickup and partner terms. |
| **6 — Optional research** | Purpose/rights and artifact controls, review provenance, text/audio redaction, segmentation metadata, duplicate/split protection, frozen datasets and withdrawals, independent-teacher comparison and human-adjudication validation, evaluation and uncertainty tools, experiment specification, optional training and local-serving harnesses. | Product-gated realtime API/conformance implementation; eligible licensed corpus and model rights, qualified real review, actual training/target-hardware results and held-out improvement. |

## 5. Backend correctness and controls

The backend uses Python 3.12, FastAPI, SQLAlchemy and PostgreSQL for production. SQLite remains an explicitly bounded development profile. The frontend uses React, TypeScript and Vite. Media, local speech and durable operations workers run separately from the transactional API.

### Booking and external authority

Minute-level occupancy claims cover practitioners and shared resources, including duration and buffers. Database uniqueness is the final concurrency authority. Offers are signed, holds expire, and current availability is checked at commit. Appointment, occupancy, audit, logical notice and mutation receipt changes commit together. A lost response can be replayed without duplicating a booking. Failed rescheduling preserves the original appointment.

Service rules and approved facts carry source, effective and expiry evidence. Package entitlements and series return per-occurrence outcomes and can retry an unsuccessful part without repeating a committed occurrence. An external authority uses durable operation identities, a capability contract, read-back and revision reconciliation. An ambiguous write remains pending until reconciliation establishes its outcome. The staff interface displays that pending state rather than announcing an unproven success.

The typed conversation tool boundary validates server-derived tenant and caller authority, tool shape, proof, bounded execution and current policy. The current conversation engine is a bounded administrative state machine. A generative model is not required for its existing flows; optional generative/streaming extensions are not advertised as implemented.

### Financial truth

Exact decimal quantities, versioned rates, conversion evidence and billing quanta produce integer micro-Toman ledger values. Provider operation and receipt identities deduplicate charges. Corrections append evidence instead of overwriting financial history. Budgets reserve expected maximum liability before supported provider work and retain unknown outcomes for reconciliation.

Automated media admission reserves the configured maximum automated duration before issuing access. Finalization, expiry and human takeover preserve unknown supplier liability until an actual receipt resolves it. This covers the automated segment governed by the application. It is not a claim that the application caps an independently billed carrier, PBX or human segment outside its authority.

Deposit intent pins the clinic's approved merchant mapping, amount, currencies, expiry and published terms. Verification does not trust a browser callback assertion. Late settlement cannot recreate conflicting capacity. Refund/dispute records and legacy financial amounts remain intact through privacy and schema migrations.

### Operational outcomes

The outbox distinguishes queued, provider-accepted, delivered, failed, simulated and unknown. Dispatch rechecks current eligibility and consent. Ambiguous non-idempotent sends are not blindly repeated. Calendar recovery and dependency probing have operation/time bounds; standalone workers respond cooperatively to termination and preserve uncertain durable work for review or reconciliation.

Readiness returns bounded aggregate information to public callers. Detailed controls remain privileged. Tracing retains safe correlation and scoped operation identities while rejecting free-text patient details. On-call events create owned, deduplicated application work; they do not establish that an external human was contacted or answered.

The final tool instrumentation records per-tool execution duration and a closed outcome category with call/turn correlation. Handled failures and deadlines retain timing evidence through the rollback used for safe handoff; replay does not duplicate the record. A queued external operation is labeled as dispatch, and a rolled-back attempt is not represented as a committed booking. No tool arguments, results or exception text enter these spans. Successful per-tool distributions are available through the existing latency report. These measurements do not invent a model stage or establish first-audible latency at a physical receiver.

## 6. Security, privacy and migration

Staff tokens carry a per-session identifier. Logout revocation and current membership/permission checks apply even before a token expires. Caller capabilities remain conversation-scoped. Sensitive booking changes require contact proof; OTP budgets cannot be bypassed merely by opening a new session. Partner authority has explicit scope, expiry and revocation.

Processing, recording, QA, reminders, waitlists, follow-up, marketing, training/research use, cross-border processing and memory have independently governed purpose states. Research export uses the training purpose; it is not an additional independent consent category. Real public session creation binds the exact displayed processing notice fingerprint under the clinic publication lock. If the notice changes, the API returns `409 PROCESSING_NOTICE_CHANGED` before creating a call. The frontend refreshes the notice, clears consent and requires a new affirmative action. Demo-only omission compatibility is explicitly recorded as unbound and is not accepted for real intake.

Retention applies the strictest relevant current purpose cap, tenant cap and original call pin. Traversal includes inactive clinics and limits records per clinic; it does not claim a global execution-time cap. Protected artifacts, redaction review and erasure evidence retain required operational/financial facts while removing eligible direct identifiers. Ambiguous external-calendar operations preserve the minimum evidence needed to resolve their outcome.

Contacts and protected notes are encrypted. The version-0002 upgrade also encrypts eligible legacy billing free text and preserves financial IDs and amounts. A separate stable lookup key supports contact identity without coupling it to ciphertext rotation. Log and error handling avoid raw SQL, credentials and patient transcript disclosure.

The schema has **88 application tables plus `schema_version`**. The migration upgrades a valid version-0001 schema transactionally, initializes fresh deployments and refuses unknown, unversioned or damaged state. It does not silently repair drift with `create_all`. Synthetic upgrade, rollback and privacy-preservation tests are retained.

Production configuration rejects demo mode, weak/default secrets, SQLite, missing independent lookup keys, insecure or wildcard origins, invalid limits and incomplete enabled-provider declarations. Provider credentials and approved regions remain supplied evidence, not invented defaults. Activating a production clinic requires the appropriate current UAT attestation.

The research tooling now compares two to five explicitly identified teacher-output artifacts against a currently revalidated frozen dataset. It reports word/digit disagreements and missing hypotheses separately, then requires a content-bound human accept/exclude decision for every sample. Teacher agreement never substitutes for human adjudication. Current withdrawal, rights, region and privacy checks apply before processing; stale inputs, incomplete decisions and changed hashes fail validation. Outputs retain hashes and counts without copying hypotheses, transcripts or audio. This is an offline implementation tested with synthetic fixtures, not an actual corpus review, provider benchmark or trained-model result. The exact commands and schemas are in `docs/research-workflow-v2.md`.

## 7. Native applications and release workflow

### Windows desktop

The Electron host uses sandboxed rendering, context isolation, disabled renderer Node access, a fixed narrow bridge, an application-origin policy and checked asset paths. Server profiles are normalized and credential-free. Native session persistence uses the operating system's protected storage; an insecure Linux fallback is not silently used as durable credential storage.

The supported Windows release targets are a per-user assisted NSIS installer and a portable executable. The installer supports selecting its directory without requiring machine-wide elevation. The desktop host loads the built local interface and connects to the configured clinic API.

The Linux environment can exercise the actual Electron host and produce Windows packages, but it cannot establish Windows installation, upgrade or uninstall behavior. Local unsigned NSIS packaging uses the pinned extractor already shipped inside the installed electron-builder version because the available host could not execute the required PE32 tool. Its bounded adapter and provenance are recorded separately; the product code and native Windows CI use the standard builder path. No Windows execution or signature is inferred from extraction.

### Android companion

The Capacitor Android project targets SDK 36, supports API 24 and above, and uses Java 21 with a checksum-pinned Gradle wrapper. Session encryption uses Android Keystore-backed AES-GCM and binds stored state to the selected server. The native host disables cleartext traffic, WebView debugging, backup and device transfer; secure-window policy limits incidental screen capture. These source and unit checks do not replace testing the actual Keystore and microphone on a device.

The debug application ID is `ir.hamava.reception.debug`; release uses `ir.hamava.reception`. The debug APK has a development signature. Without the organization's publisher keystore, the release APK and AAB are explicitly unsigned. A release bundle is a store/build input, not an installable APK.

### GitHub Actions

`verify.yml` checks Python lint/tests, PostgreSQL contention and startup, the frontend build and isolated synthetic browser matrix, desktop contracts and container startup. `release-apps.yml` invokes that gate before Windows and Android packaging. Both package jobs consume the same verified web artifact. Actions are pinned by commit SHA; versions are checked across the project.

The Windows job runs on a Windows runner, launches Electron and creates installer/portable outputs. The Android job runs unit/lint checks and builds debug/release APKs plus the release bundle. Optional explicit signing inputs fail closed if a required secret is missing and verify the resulting signatures when configured. Checksums include compiled packages and supplied dependency/signature metadata. Intermediate uninstallers are excluded.

Ordinary tag or manual builds produce artifacts. An optional draft-release job requires a tag in the default branch's history and both requested signatures; only that job receives repository write permission. It does not automatically publish a public release. No matching authorized project repository was available in this session, so remote GitHub Actions execution, repository publication and production signing are not claimed.

## 8. Verification evidence

<!-- GENERATED:VERIFICATION:START -->
The final backend gate executed **444 tests across all 33 files: 444 passed, zero failed, zero skipped**. Three isolated processes each collected the entire suite before selecting disjoint whole files. The retained execution and recovery evidence proves every node was selected, started and finished exactly once and all 113 frozen source hashes remained unchanged. The longest recorded worker interval was 762.892 seconds; the lost supervisor's wall-clock result remains unknown. This is one complete planned execution, not a composite of partial reruns.

The execution service lost the supervising process during the run. The same three original pytest workers continued and completed all planned tests. Recovery independently verified their complete collections, exact node identities, all 1,332 passing setup/call/teardown records, JUnit results, durable pytest session-finish exit statuses and unchanged source/controller/plugin hashes. No new or focused test results were substituted. The aggregate is explicitly labeled `passed_recovered_supervisor`; missing operating-system exit observations remain `null`, and an uninterrupted supervisor completion is not claimed.

| Verification | Observed result | Scope and evidence |
|---|---|---|
| Complete backend regression | **444/444 passed** | Current frozen source; `docs/validation/v2-pytest-current-shards/aggregate.json` plus per-shard JUnit, observations, sanitized logs and explicit supervisor-recovery provenance. |
| Server wheel installation smoke | **15/15 passed** | All 53 packaged runtime modules match current source; no test modules; fresh version-0002 schema, final UI, login, displayed-notice intake, logout revocation and zero-sent operations tick. |
| Browser workflow and contract checks | **102 passing named checks** | 92 frontend checks plus 10 platform checks; 12 of the 102 are explicit RTC event-contract fixture checks. |
| Browser accessibility/layout audits | **99 audit executions; zero reported violations or document overflow** | 93 matrix/latency audits plus six focused setup audits. Counts are executions, not 99 distinct screens or comprehensive accessibility qualification. |
| PostgreSQL startup and concurrency | **10 startup checks; 402 contention operations across five cases** | Up to 100 contenders, no duplicate occupancy and wrong-tenant 404. Synthetic transaction correctness, not capacity or latency acceptance. |
| Migration, process shutdown and retention | **11 migration/worker checks; four PostgreSQL retention checks** | Includes actual POSIX worker termination; these focused cases overlap the complete regression and are not added to 444. |
| Tool spans and research adjudication | **9 focused span checks; 25 teacher/adjudication checks** | Rollback/replay metadata, strict rights/withdrawal bindings and mandatory separate human decisions; included in the full source gate. No real teacher/provider/corpus run. |
| Desktop security and actual host launch | **Five security groups and five Linux Electron launch checks passed** | Actual renderer/bridge/protocol; unchanged host sources. Root/headless launch disables the process sandbox for that test only and reports protected OS storage unavailable. |
| Windows build | **Installer and portable EXE generated and inspected** | Unsigned x64 payload; both final compressed EXEs contain the verified application archive and all 61 final web files. No Windows install/upgrade/uninstall execution. |
| Android build | **Debug APK, release APK and AAB generated and inspected** | All 63 public assets match in all three packages; actual manifests and signature classification checked. Four policy unit tests and one generated example test retained with unchanged native inputs. |
| Release tooling | **26/26 collector fixtures passed; version guard, Ruff and actionlint passed** | Exact release-set rules, hash associations and current workflow syntax; remote Actions and Docker runtime remain unexecuted. |
| Encrypted recovery drill | **89 tables restored, matching counts, zero duplicate/orphan occupancy** | Local encrypted PostgreSQL restore with synthetic records, appointment decryption and four new protected-field roundtrips. No production RPO/RTO or offsite-custody claim. |

The final UI entry is `/assets/index-DnPskxcg.js`. Eleven frontend checks and five audits ran directly against that final bundle. The other 81 frontend checks, 88 audits, six focused setup audits and 10 platform checks retain their original bundle provenance. Exact source-equivalence records establish that the last application amendment added only five Persian tool-stage names; the prior amendment changed only three color values. These are not described as new executions. The final release journey was rerun against all nine real API stage keys, and the latency-specific journey observed a real successful slots span, distinct labels, actual counts and empty percentiles for unobserved tools. The same immutable final web snapshot is embedded in every native package.

The Android full unit/lint/build run took 530 seconds for 264 tasks. The final web-only package refresh took 126 seconds for 220 tasks (16 executed, 204 up-to-date); unchanged native sources and test/lint report hashes link those runs. Android lint retains **24 application warnings, three generated Cordova warnings and six upstream baseline-suppressed errors**. Six additional unmatched baseline entries are historical entries, not additional active suppressions. The retained review scopes those findings; no unsuppressed clean-lint claim is made.

Earlier diagnostic results are preserved honestly. The completed pre-correction 444-test run had 442 passes and two failures because two deposit fixtures omitted the now-required current notice fingerprint. The shared fixture was corrected without changing runtime code or weakening payment/consent assertions; all four focused deposit/consent cases then passed, followed by the new complete 444-test pass above. The earlier 388-test run with one concurrency-fixture failure and the interrupted serial attempt remain historical, not passing final evidence.

### Exact compiled release files

| File | Bytes | SHA-256 | Signing |
|---|---:|---|---|
| `Hamava-Companion-0.2.0-android-debug.apk` | 4,970,272 | `be4be3e0f4812fa6aab0ad64fcebee943d14b67a40f73362ff76b4e66da53c75` | debug |
| `Hamava-Companion-0.2.0-android-release-unsigned.aab` | 1,995,574 | `0536f6e58ce9e18511fc9cabf0f321d089fa300beaff7e909c9f16d625b87eb0` | unsigned |
| `Hamava-Companion-0.2.0-android-release-unsigned.apk` | 1,536,976 | `74048d892d6a5fa17bd8d9dc286d2202b433e1cf789ccaf7937b53fa080efcf8` | unsigned |
| `Hamava-Reception-0.2.0-windows-x64-portable.exe` | 121,209,590 | `6bf3a836a4218266b645b4332b29d446114c200c91324cc9e60b71f85e7ead5b` | unsigned |
| `Hamava-Reception-0.2.0-windows-x64-setup.exe` | 121,434,127 | `38755a520a1d684b10c6ee67a8f61fda2c011d1d0d7117fb8e634f88fa35bec8` | unsigned |

The combined release manifest also records three CycloneDX inventories for the shared interface, desktop host and Capacitor npm graph. The APK debug signature is a development identity. Both Windows executables and the Android release APK/AAB are unsigned. The AAB is a bundle for a signing/store pipeline and is not directly installable. `SHA256SUMS.txt` establishes file identity, not publisher identity.
<!-- GENERATED:VERIFICATION:END -->

Functional browser and broad backend verification use a documented test-only 30-second tool budget on the shared build host. The production default remains 3 seconds; deadline-specific regressions set their own limits. This separates functional outcomes from performance claims. PostgreSQL contention timing under concurrent builds is likewise not a capacity or latency benchmark.

The retained earlier 0.1 media results establish the actual local AudioSocket and LiveKit paths at that revision. They are historical evidence, not a claim that every 0.2 change was re-exercised against real audio. The earlier CPU Persian speech example had recognition errors and multi-second response time; no production speech SLO or model-superiority claim follows from it.

Dependency versions and lock files are included. A prior advisory report is dated evidence for its scanned set; it is not a fresh audit of every native dependency or a guarantee against unknown vulnerabilities. Runtime web license notices are bundled, including the upstream license text missing from one installed npm package. The license provenance and build generation are retained in source.

## 9. Requirement accounting

<!-- GENERATED:REQUIREMENTS:START -->
The original **263 requirements** are reconciled as **212 verified locally**, **26 partial or not fully verified**, **22 blocked on external inputs**, and **3 deferred by their original optional product/research gates**. No row is omitted or left pending. These categories are not a production completion percentage.

| Original phase | Verified locally | Partial / unverified | External inputs | Optional gate | Total |
|---|---:|---:|---:|---:|---:|
| 0 — Groundwork and accountable launch preparation | 28 | 9 | 7 | 0 | 44 |
| 1 — Browser proof and trustworthy booking foundation | 81 | 3 | 0 | 0 | 84 |
| 2 — Single-location PSTN/media operations | 23 | 9 | 6 | 0 | 38 |
| 3 — Revenue/attendance workflows | 30 | 3 | 1 | 0 | 34 |
| 4 — Multi-tenant building hub | 29 | 0 | 0 | 0 | 29 |
| 5 — Channels and partner scale | 8 | 1 | 5 | 0 | 14 |
| 6 — Optional Persian speech research/infrastructure | 13 | 1 | 3 | 3 | 20 |
| **Total** | **212** | **26** | **22** | **3** | **263** |

The additional ten native/release criteria are kept separate: six verified locally, two partial/unverified and two external. They do not inflate the original denominator. The complete JSON/CSV register and `docs/requirements-summary.md` list each remaining acceptance, its responsible role and evidence. UI-only observations for overlapping requirements supplement the authoritative backend/operations assessment and do not replace it.
<!-- GENERATED:REQUIREMENTS:END -->

The register preserves each original ID, phase, source section and acceptance. `verified_local` applies to the recorded local behavior within its stated limits. `implemented_unverified` includes missing implementation and acceptance not yet demonstrated; it must not be read as all code complete. External and optional gates retain the exact missing inputs. Assessor snapshots are retained, while the root reconciliation in the main register controls the final status.

## 10. Exact remaining work and operator inputs

The remaining acceptance is itemized in `docs/requirements-summary.md`. Principal boundaries are:

1. **Repository and publisher identity:** an authorized GitHub repository, actual workflow execution, protected signing credentials, Windows installer/device acceptance and Android device/store acceptance. Local unsigned packages and reviewed workflow files do not establish those outcomes.
2. **Clinic and supplier operation:** real clinic authority and UAT, named qualified clinical/privacy reviewers, staffed fallback, carrier/DID, approved processors and regions, actual SMS/payment/calendar credentials, receipt/invoice reconciliation and public TLS/ICE/TURN.
3. **Media integration and language validation:** native partial STT, streaming TTS and generative tool-stream adapters are not implemented; current speech processing uses the supported buffered contract. The full requested/ringing/accepted/failed carrier-event adapter and warm-transfer integration also require implementation against the selected PBX/carrier contract. Current handoff truth covers queued work, verified LiveKit human connection and an explicitly unobserved Asterisk cold-transfer fallthrough. Representative multilingual classification, acoustics, real staff pickup and deployed SDK/carrier shutdown/reconnect behavior remain unverified.
4. **External concurrency:** internal PostgreSQL correctness is exercised locally; atomic contention and recovery against an independently operated calendar source require that source and its contractual guarantees.
5. **Research and commercial outcomes:** the optional realtime API/conformance suite remains unimplemented behind its original product gate. Rights-cleared representative data, actual reviewers and target hardware, a real training/evaluation run, blind held-out improvement, real customer demand, baseline/pilot observations and causal economic results cannot be supplied by synthetic fixtures.

These are acceptance boundaries, not hidden successes. The application keeps unavailable capabilities disabled or explicit and preserves uncertain operational states for review.

## 11. Handover and operation

Start with `README.md` for the synthetic local application and exact commands. Use `docs/deployment-runbook.md` for production configuration, version-0002 migration, backup/recovery, retention and incident operation. Native setup, build commands, signing variables and release acceptance are in `docs/native-apps-and-releases.md`.

For an existing deployment, pause intake, obtain an encrypted backup, validate its recovery path, run the explicit migration, restart API/workers and inspect readiness and clinic UAT state before resuming. Preserve unresolved provider operations and old merchant mappings until reconciliation completes. The native apps should connect to the same deployed HTTPS API and exact allowed origins; Android must not be pointed at a cleartext endpoint.

The latest backup drill restores all 89 tables into an isolated fresh PostgreSQL database, checks matching counts and occupancy invariants and verifies decryption of both earlier and new protected data. It does not establish offsite key custody, production recovery time or a continuously operated backup service. Those responsibilities remain with the named deploying operator.

The evidence directory distinguishes current `v2-*` results from historical artifacts. Overlapping focused suites are not added to the full-suite total. Release checksums establish file identity; publisher identity requires the separate signature evidence. Keep the source, its matching native packages, requirement register and this report together when reviewing or handing over the pilot.
