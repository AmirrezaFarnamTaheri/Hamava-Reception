# Deployment, recovery and operating boundaries

**Release:** Hamava 0.2.0 · **Evidence date:** 2026-10-23

This runbook turns the implementation into a reviewable deployment. It does not record a completed production launch. The target hostname, legal/clinical operator, supplier contracts, approved model/voice rights, staffed route and production infrastructure must belong to the deploying organization. The supplied source contains no live supplier credentials or patient recordings.

## 1. Release and configuration ownership

Assign a technical owner, clinic decision-maker, clinical script reviewer, privacy reviewer, billing owner and incident/on-call contact. Record their actual names and coverage in the launch-playbook worksheets. The software has role and tenant controls; it cannot manufacture those organizational authorizations.

The baseline runtime is Python 3.12, PostgreSQL 16 and Node 24 for the frontend build. `requirements.lock.txt` constrains the tested dependency graph. Optional media/speech/training dependencies remain explicit installation groups. `frontend/package-lock.json` controls the frontend graph. Preserve the source archive checksum, dependency lock files, container image digest when built, model provenance and reviewed configuration with each release.

Use `scripts/generate_env.py --host <owned-hostname>` to create `.env.production` once. It generates independent JWT, ciphertext-encryption, lookup-HMAC, database, metrics, media and speech secrets. It does not enable external processors. File permissions are private and existing files are not overwritten. A secret value, including a payment merchant ID or provider token, must never enter the frontend build, git history, public support log or browser URL.

`JWT_SECRET` signs staff/media authority and hashes some short-lived capabilities. Rotating it invalidates outstanding capabilities and staff tokens; pause intake, complete or reconcile in-flight work, rotate every application process consistently, revoke/reissue partner keys, and require new caller sessions. User `token_version`, current membership and per-session `jti` revocation provide scoped staff revocation without rotating the whole deployment. Version 0.2.0 requires a fresh login for old tokens without a session identifier. Native sign-out revokes one session by default; the explicit all-devices operation increments the user's token version.

`LOOKUP_HASH_KEY` is independent from the Fernet key and must remain stable during ciphertext rotation. It links normalized telephone identities to consent, suppression, privacy and booking records. Replacing it without an explicit identity reindex is not supported. Keep it recoverable alongside the approved application key inventory, separately from the encrypted data archive.

## 2. Start and verify the production baseline

Review `.env.production`, the explicit HTTPS origins, server timezone, actual public URL and database credentials. `ENVIRONMENT=production` and `DEMO_MODE=false` are mandatory. Production rejects the development encryption key, missing/weak secrets, an absent separate lookup key, SQLite and wildcard or insecure web origins. For the companions, add the exact native origins `app://hamava` and `https://localhost`; those explicit application origins are accepted. The public API must remain HTTPS for Android. See `native-apps-and-releases.md` for the separate server-connection and release-signing procedures.

```bash
docker compose --env-file .env.production build
docker compose --env-file .env.production --profile https up -d
docker compose --env-file .env.production ps
```

The database service must be healthy before the migration job runs. The API starts only after migration completion; the operations worker starts after API health. The optional speech service and media workers are separate processes. The application containers run as an unprivileged user with a read-only filesystem, temporary scratch storage, dropped Linux capabilities and no-new-privileges. The PostgreSQL data and Caddy state are named volumes.

The API port binds to loopback. Caddy is the public HTTPS boundary, with a reviewed request-body ceiling and a private upstream. The internal media admission routes and Prometheus route are blocked at the public edge. The configured proxy trust is restricted to loopback and the explicit Caddy private address; if the subnet changes, update both the network and trusted address. Do not trust arbitrary forwarded client IPs, because admission/abuse controls use the effective client address.

Create the first owner with `scripts/admin.py` through the private application container. The password is read using `getpass`, not a command-line argument. A new clinic is paused with no configured hours. Complete its catalog, ownership, terms, approved facts, working hours and human routes, then the clinic-specific UAT process, before enabling intake. Production UAT is a named operator attestation with artifact references; it is not a machine-generated assertion that an untested carrier or clinical script is approved.

The clinic launch screen records five checks, a reviewer and evidence references for the exact policy/catalog fingerprint and intended mode. An attestation expires after 30 days and is invalid if its reviewer loses the required active membership. In production, pause intake before changing the live catalog, complete the review, and attest the revised fingerprint before reactivation. A stale attestation blocks new automated intake and subsequent AI actions. Emergency pause is always available; it does not require an approval that could delay stopping the system.

The current schema is `0002`. Migration `0001` preserves the original 50-table baseline; `0002` adds 38 application tables for session revocation, integration/routing/calendar authority, cost accounting, privacy and operational controls. Including the version ledger, the current database has 89 tables. A fresh database receives both migrations. An intact, versioned `0001` database upgrades transactionally. Existing records and financial amounts are preserved, and old free-text billing reasons move into encrypted audit evidence with categorical markers in historical snapshots.

Before upgrading an existing deployment, pause intake, stop API/media/job writers, take a recoverable encrypted backup, and run `python scripts/migrate.py` with the intended private database configuration. The migration validates the old schema before adding tables and the new schema before committing. PostgreSQL serializes migrations with an advisory transaction lock; SQLite uses an immediate transaction for local upgrade tests. A malformed legacy invoice, partial migration, schema drift, unknown version or unversioned application database fails the upgrade. Repair the evidenced source issue or recover an isolated verified backup; do not stamp a version or call `create_all` to hide the mismatch.

Restart with version 0.2.0 only after migration succeeds, then verify `/health`, `/ready`, owner login, clinic pause state and the active authority/rate/processor policies. The legacy internal-calendar authority is carried forward as a technical default; this does not manufacture approved clinical facts or a production UAT attestation. Preserve the pre-upgrade backup until the organization accepts the upgrade and any unresolved external liabilities have been reconciled. No destructive downgrade is supplied.

The Dockerfiles and compose YAML have been inspected and parsed, and equivalent host processes have been exercised. The development environment did not include a Docker daemon; the supplied CI has a Docker build step that must run on the deployment build host. Do not label an unexecuted container build as passed.

## 3. Clinic modes and operating policy

| Mode | Implemented behavior |
|---|---|
| `human_primary` | Staff route/follow-up is preferred; the assistant does not autonomously take ordinary bookings. |
| `after_hours` | Automated intake is eligible only outside the published open intervals and on configured closure days. |
| `overflow` | Requires authenticated PBX busy/no-answer evidence. A browser cannot self-assert overflow authority. |
| `supervised` | New reservations await staff approval; sensitive moves/cancellations go to staff. |
| `ai_primary` | Administrative automation operates within the approved calendar and identity rules. |
| `paused` | Immediate stop for new and continued automated actions; existing clinical appointments are preserved. |

Calls pin a published policy snapshot. Live safety controls—paused/inactive tenant, expired call, actual human takeover, revoked partner authority or lost media lease—override the snapshot. Do not silently reinterpret an appointment when a closure or practitioner absence occurs. Preview the affected appointments, publish the disruption, choose each patient's explicit outcome, reconcile payment obligations and notify through the durable outbox.

Hours must use ordered, nonoverlapping local intervals. Practitioner `null` hours inherit the clinic; an empty object supplies no shifts. Overnight coverage is represented explicitly across date boundaries, not an inverted start/end pair. Narrowing shifts across existing appointments requires a reviewed disruption/move process. Prices and deposit amounts are integer Toman in the application; the gateway boundary performs the exact IRR conversion.

## 4. Media and network integration

### Asterisk AudioSocket: selected PSTN path

Use the templates in `deploy/asterisk/`. Configure the owned DID/trunk, exact carrier IP ACLs, credentials, reviewed codec/DTMF settings and an authorized staff extension. Do not enable anonymous SIP or an unrestricted outbound dial context. The example first attempts staff, records busy/no-answer, plays an approved processing notice, registers the one-use UUID through the authenticated private API, and connects AudioSocket only when registration explicitly authorizes automation. A failed/closed assistant path falls through to the configured staff route.

The AudioSocket bridge accepts the documented three-byte framing and UUID/DTMF/PCM/hangup messages. It produces signed 16-bit little-endian mono PCM at 8 kHz in 20 ms packets. G.711 bytes are not treated as PCM samples. The application requires the call to be answered in the PBX dialplan; the protocol itself does not answer it. Restrict port 9092 to the PBX/tunnel and exact `AUDIOSOCKET_ALLOWED_CIDRS`. AudioSocket does not provide a native encrypted/authenticated public transport.

Official references: [AudioSocket protocol](https://docs.asterisk.org/Configuration/Channel-Drivers/AudioSocket/), [AudioSocket dialplan application](https://docs.asterisk.org/Latest_API/API_Documentation/Dialplan_Applications/AudioSocket/), [Dial status and options](https://docs.asterisk.org/Latest_API/API_Documentation/Dialplan_Applications/Dial/).

### LiveKit browser path and optional SIP recipe

The WebRTC worker is implemented with the actual LiveKit RTC SDK. The application creates isolated rooms, issues scoped caller/agent/staff tokens and verifies signed participant events. Tokens and room credentials must not be logged. Staff access also requires an active tenant membership and ownership of the matching handoff task. `ROOM_READY` is not `HUMAN_CONNECTED`.

Deploy a reviewed LiveKit server or approved hosted service and configure `LIVEKIT_URL`, key, secret and explicit approval. Configure public TLS, ICE/TURN and the necessary firewall addresses for the deployment. The templates are in `deploy/livekit/`; they contain placeholders, not live keys. The optional SIP-server recipe requires separate tenant-aware dispatch and carrier acceptance before it can replace the selected Asterisk integration.

Official references: [self-hosted ports/firewall](https://docs.livekit.io/transport/self-hosting/ports-firewall/), [LiveKit SIP deployment](https://docs.livekit.io/telephony/start/sip-server/). The published port matrix includes signaling, media TCP/UDP and TURN; choose the documented deployment configuration rather than opening all example ports indiscriminately.

The local SDK smoke test proves actual loopback signaling, PCM reception, speech processing, a trusted conversation event and verified human room takeover. It does not prove public NAT traversal, mobile background behavior, a real carrier line, warm PSTN transfer or high-load acoustic quality. Complete the launch-playbook codec/DTMF/device/busy/no-answer/drop matrix against the authorized target network.

### Speech deployment

The optional local gateway holds incoming audio in bounded memory, accepts only the supported audio containers, decodes through a restricted FFmpeg invocation, rejects excessive duration/size and limits expensive work. Models are provisioned explicitly. ASR and TTS are CPU baselines unless the operator changes the reviewed runtime. The service never downloads model weights during a call.

Keep code, weights, dataset, voice and derivative rights distinct. Relevant primary references include [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper), [Piper](https://github.com/OHF-Voice/piper1-gpl) and the selected voice's own model card. A repository label does not automatically settle every commercial/derivative/data right. `SPEECH_MODEL_RIGHTS_REVIEWED` records the operator's assertion; it is not legal approval supplied by the application.

Change `SPEECH_VOICE_VERSION` when changing the reviewed voice. Document the actual model revision and processing region. Fallback transmission requires its own approval and host allowlist. Do not enable a fallback just because its URL responds.

## 5. External services and result semantics

Kavenegar SMS uses the approved sender/template and private key. Provider acceptance records `SENT`; delivery polling/verified receipts establish `DELIVERED`. A timeout after a non-idempotent send becomes `UNKNOWN`. Reconciliation comes before resend. Quiet hours and purpose/channel withdrawal apply at scheduling and again immediately before dispatch. Transactional booking messages do not imply marketing, follow-up or training consent.

Zarinpal uses hosted payment links and server-side verification. A browser callback alone cannot confirm payment. Unpaid reservations expire; late settlement triggers review/refund work and never recreates a conflicting slot. Full/partial/refused/reconciled refund records preserve the original financial history. Staff-recorded provider evidence is labelled as such. The application does not invent a refund API or send card data through a voice call. Primary reference: [Zarinpal payment gateway documentation](https://www.zarinpal.com/docs/paymentGateway/).

Before enabling real deposits, publish that clinic's deposit, cancellation and refund terms, currency and hold duration. The patient must explicitly accept the published version; an appointment and payment intent retain an immutable copy. The voice flow reads the applicable terms before asking for agreement, and requests agreement again if the amount or terms change. Terms that cannot fit the safe spoken interaction route to staff instead of being silently truncated. Fictional demonstration terms are labelled as synthetic.

The operator, not a browser user, configures `PAYMENT_TENANT_MERCHANTS_JSON` as a mapping from tenant ID to a stable merchant alias, and `PAYMENT_MERCHANTS_JSON` as a mapping from that alias to `merchant_id`, `sandbox` and `approved`. Set `PAYMENT_PROVIDER_APPROVED=true` only after the actual provider review. Each intent pins the alias, identity hash, sandbox mode, application/gateway currencies, amount and terms version. The application does not fall back to the legacy global `ZARINPAL_MERCHANT_ID`. Keep old approved aliases unchanged while intents remain unresolved: mapping a tenant to a new alias preserves verification through its old alias, whereas rebinding an existing alias to a different identity or environment deliberately blocks its earlier intents for reconciliation. A configuration-readiness indicator does not establish live settlement or the legal adequacy of the terms.

An external calendar must satisfy the implemented capability contract, including conditional/idempotent writes and read-back. Publish the exact provider/account authority and approved capability revision while intake is paused. The application records a durable operation before remote mutation, preserves an ambiguous outcome for read-back, and invalidates stale inventory when revisions are discontinuous. Pending or unknown operations must be presented as pending; a transport response alone is not an appointment confirmation. A vendor name in the blueprint is not authorization. The internal transactional calendar remains authoritative until the selected integration has passed its clinic-specific tests.

Publish supplier price evidence and a monetary policy before enabling supported real provider operations. Rate versions specify currency, billing unit/quanta and conversion evidence. Reservations hold the maximum allowed exposure before dispatch; measured use, provider settlement and vendor-statement reconciliation are distinct events. The automated media gate reserves `telephony_primary` / `telephony_seconds` for its maximum allowed call duration before admitting SIP or WebRTC media. Disconnect, expiry and human takeover retain uncertain carrier liability until reconciliation. This cap covers the application's automated media segment; it does not cap carrier/PBX time before admission or the subsequent staff call. The owned trunk must have its own carrier fraud, destination and spending controls.

Purpose policies and processor approvals are tenant-specific, versioned and time-bounded. Review the processing region, permitted operation, actual supplier contract and approval expiry. Configured integrations with no current observation remain unknown; they are not reported as healthy merely because credentials exist. The signed SMS gateway validates replay/tenant scope, and outbound voice remains disabled until its separate approved gateway, contact permission and destination policy are configured. On-call escalation creates auditable staff work; it does not silently send messages to external chat/email accounts.

Owner digests use a separately approved gateway contract for configured Telegram/Bale/Eitaa/email-style destinations. They contain aggregate operational counts, not patient records. Manual enqueue or explicit automatic-daily opt-in creates one closed-day delivery per destination. Gateway acceptance is `SENT`, not evidence the owner read it. An unknown send is not automatically retried. The source does not claim that native social-platform API access has been provisioned.

## 6. Backup, retention and a real restore drill

Install PostgreSQL client tools compatible with the server and GnuPG. Provision a reviewed public-key fingerprint for backup encryption; keep its private decryption key under the recovery policy. Keep the application Fernet key ring and stable lookup key recoverable independently. Configure `BACKUP_DATABASE_URL` privately; credentials are passed through the child process environment, not printed or put in the command line.

```bash
python scripts/backup.py backup --output /approved/private/backup.dump.gpg \
  --recipient REVIEWED_FULL_GPG_FINGERPRINT
```

The pipeline streams a PostgreSQL custom archive directly into GPG encryption. It does not write a plaintext database dump. The output and manifest have private permissions. Publication uses an atomic no-overwrite operation, so a concurrent same-name job cannot replace an earlier archive. The manifest includes timestamp, encrypted-file SHA-256, schema and preflight counts.

Use the reviewed examples `deploy/hamava-backup.service` and `.timer` to schedule `scripts/backup_daily.py`. Configure an approved `BACKUP_RETENTION_DAYS`; deletion stays off unless `BACKUP_DELETE_EXPIRED=true`. `BACKUP_LEGAL_HOLD=true` prevents expiry deletion. Pruning only removes matching old archive/manifest pairs whose format, timestamp and checksum validate; unknown/unpaired/corrupt/symlinked files are preserved for investigation. Offsite storage, access monitoring and key recovery must be deployed and tested by the actual operator; no remote backup destination has been silently created.

Restore into a **new, empty, isolated target**:

```bash
python scripts/backup.py restore --source /approved/private/backup.dump.gpg \
  --acknowledge-empty-target --verify-application-key
```

The target `BACKUP_DATABASE_URL` must identify the recovery database. The command rejects an existing populated target, checks the encrypted checksum, streams decryption into `pg_restore --single-transaction`, checks schema/constraints, occupancy duplicates/orphans and optional application decryption, and compares source/target counts. Count equality is expected in a quiescent drill; a live snapshot can legitimately differ from a preflight count. A failed decryption/restore target must remain isolated even if partial pipeline effects appear present. Do not route traffic to it merely because PostgreSQL starts.

The current `docs/validation/v2-restore-drill.json` records an actual encrypted PostgreSQL backup and restore of all 89 tables with synthetic records, matching counts, zero duplicate/orphan claims and decryption of appointment data plus four new protected field types. The older `restore-drill.json` is baseline history. Neither proves offsite durability, a real key-custodian exercise, scheduled execution or an agreed production RTO/RPO. Record measured detection, retrieval, provisioning, restore, verification and traffic-switch times in the operator worksheet.

Administrative call transcripts use the stricter applicable limit from the current processing-purpose policy, tenant retention cap and original call snapshot. Tightening a limit applies to existing transcripts; increasing it does not silently extend an earlier promise. Expiry removes protected conversation material and records backup-expiry evidence while retaining separate financial/audit obligations. Legal holds and optional research/marketing permissions are distinct. Operational erasure traverses clinics, including inactive ones, with per-clinic record caps; the traversal has no fixed total-runtime ceiling, so monitor its duration as the tenant count grows. `scripts/config_backup.py` separately encrypts configuration and metadata-only key inventory under a recovery key supplied by the operator; the key inventory is not a secret-key backup.

## 7. Ciphertext-key rotation

Stop application, media and job writers and keep a tested recoverable backup. Load a new `ENCRYPTION_KEY`, place the previous key(s) in `ENCRYPTION_PREVIOUS_KEYS`, and retain the **unchanged** `LOOKUP_HASH_KEY`. Existing records decrypt through the explicit key ring; new writes use the current key.

```bash
python scripts/rotate_encryption.py
python scripts/rotate_encryption.py --apply --acknowledge-offline-tested-backup
python scripts/rotate_encryption.py
```

The first command reports counts only. Applying rotates mapped encrypted fields and the protected values nested in JSON, including audit notes, idempotent response receipts and queued OTP payloads. It uses table transactions, validates the schema first and never changes lookup hashes. An interruption leaves a mixed-key dataset readable by the same ring; rerunning skips already-current ciphertext. The final dry run must show zero fields requiring rotation. Restore and decrypt a new backup before restarting. Retain previous keys until all backups needing them expire under the approved policy. The isolated regression tests verify unchanged identity hashes, nested-payload decryption with the old key removed, and successful idempotent re-execution.

## 8. Monitoring, incident response and rollback

`/health` reports application/database reachability. `/ready` evaluates bounded dependency aggregates and exposes only public readiness state, without clinic identifiers or credentials. Authenticated `/api/v1/operations/health` shows tenant-scoped queue ages, notification states, active calls, media worker freshness, usage-budget exposure and recorded safety incidents. `/api/v1/operations/latency` reports successful observed STT, TTS/cache, conversation/calendar and verified handoff distributions with counts. A server completion timestamp is not first audible output at the caller; use receiver instrumentation for that boundary.

The API's optional embedded worker and the standalone operations worker use cooperative stop signals and `SHUTDOWN_GRACE_SECONDS` before bounded cancellation. Configure the process/container stop timeout longer than that grace plus cleanup time. Started operations with uncertain remote effects retain their durable reconciliation state across shutdown. The retained process tests exercise actual SIGTERM with completed work and a timed-out task; they do not imply every external provider supports cancellation.

`/metrics` requires a distinct `METRICS_TOKEN` and is intended for the private monitoring network. The supplied Prometheus examples cover queue age, missing workers, delivery uncertainty and recorded safety incidents. Logs allow static event names, correlation IDs, exception class and driver error code. SQL, bound parameters, phone numbers, patient names, arbitrary exception text and full transcripts are excluded. Access logging is disabled in the supplied commands because callback/query strings can carry sensitive identifiers.

An empty incident ledger does not prove zero unobserved false confirmations. Reconcile sampled conversations against authoritative appointments and actual attendance. Treat an invented booking, wrong-tenant disclosure, false financial settlement or unconsented recording as a stop-ship event: pause intake, preserve minimal correlated evidence, assign the named incident owner, provide the staffed alternative and follow the launch-playbook incident procedure.

For rollback, pause clinics and stop intake/media/jobs first. Preserve uncertain outbox/payment/calendar states for reconciliation. Deploy the previous **compatible** image/configuration only when its schema contract matches. If a migration changed compatibility, recover a separately verified pre-change backup into an isolated database and reconcile any intervening business activity before switching traffic. Never run a destructive downgrade or overwrite the current database as an improvised rollback.

## 9. Final launch evidence

Complete the item-level register and retain actual evidence for: authorized DID and staffed routing; public TLS/NAT/TURN; real phone/browser device tests; provider acceptance/delivery/settlement; correct per-clinic merchant/calendar authority; clinical/privacy/contract approval; eligible model/voice rights; representative Persian phone accuracy and latency; cost exposure and staff coverage; backup restore and incident ownership; and a real customer baseline/pilot/attendance comparison.

The synthetic engineering tests and commercial worksheets are useful preparation. They do not constitute customer renewal, permission to train on patient calls or evidence that a domestic speech platform is economically justified. Those phase gates remain explicit in the revised blueprint.
