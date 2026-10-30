# Deployment and recovery guide

[فارسی](deployment.fa.md) · [Documentation](README.md)

This guide is for the person responsible for getting Hamava onto an owned server and keeping it recoverable. The default architecture is one HTTPS entrance, a FastAPI service, PostgreSQL and a separate background worker. Telephony and speech are additional, explicitly configured services—not prerequisites for the text receptionist.

## 1. Prepare the host and ownership

Arrange a hostname under your control, DNS and HTTPS termination, a Docker host with sufficient storage, PostgreSQL **16**, secure off-host backup storage and named technical/on-call owners. Decide who can approve clinic facts, update routing, handle payment disputes and restore keys. Do not start patient traffic before there is a staffed fallback for automation failures.

The repository's `compose.yaml` supplies the following services:

| Service | Role | Default |
| --- | --- | --- |
| `db` | PostgreSQL data store | On |
| `migrate` | Validate/create/upgrade the schema before API startup | Runs before API |
| `api` | FastAPI HTTP application | On |
| `jobs` | Durable outbox and operations worker | On |
| `edge` | Caddy public HTTPS gateway | `https` profile |
| `speech` | Local speech gateway with operator-provided models | `speech` profile |
| `audiosocket` | Private PBX AudioSocket server | `pbx` profile |
| `livekit-worker` | Application-side LiveKit worker | `webrtc` profile |

The `webrtc` profile does **not** install a LiveKit server; the `pbx` profile does **not** provision a telephone carrier. The AudioSocket listener is plaintext on a private interface and must never be exposed directly to the public internet.

## 2. Generate configuration, then review it

Start with the supplied production template instead of editing the demo `.env`:

~~~sh
python scripts/generate_env.py --host reception.your-domain.example
~~~

The generator creates `.env.production` with restrictive file permissions and refuses to overwrite an existing file. It produces separate JWT, encryption, lookup, database, media, monitoring and PBX credentials. Store their recovery copies in the approved secure vault; a database backup without its application encryption key may be unusable.

Review at least these settings before startup:

| Setting | Decision |
| --- | --- |
| `ENVIRONMENT=production`, `DEMO_MODE=false` | Real mode, no demo accounts or synthetic operations |
| `PUBLIC_HOST`, `PUBLIC_BASE_URL`, `CORS_ORIGINS` | Exact owned HTTPS host and permitted origins |
| `DATABASE_URL`, `POSTGRES_PASSWORD` | Dedicated PostgreSQL credentials and correct database |
| `ENCRYPTION_KEY`, `LOOKUP_HASH_KEY`, `ENCRYPTION_PREVIOUS_KEYS` | Backup/rotation plan and independently recoverable keys |
| `RUN_WORKER=false` | API does not duplicate the separate `jobs` service |
| `SPEECH_PROCESSOR_APPROVED`, `SMS_PROVIDER_APPROVED`, `PAYMENT_PROVIDER_APPROVED`, `LIVEKIT_APPROVED` | Off unless the individual integration has been reviewed and tested |
| `MEDIA_DID_TENANTS_JSON`, `HUMAN_TRANSFER_TARGETS`, `AUDIOSOCKET_ALLOWED_CIDRS` | Explicit clinic/DID routing, allowed staff destinations and private networks |
| `TOOL_TIMEOUT_MS`, `MAX_MEDIA_CONNECTIONS` | Deliberate deadlines and admission limits for the host |

The config validator rejects missing, conflicting or unsafe active provider settings. An environment variable saying “approved” is an operator decision, not a replacement for checking its actual vendor account and contract.

## 3. Start the standard stack

From the repository root, after confirming the domain, keys and backups:

~~~sh
docker compose --env-file .env.production build
docker compose --env-file .env.production --profile https up -d
docker compose --env-file .env.production exec api python scripts/admin.py --email owner@your-domain.example --clinic-name 'نام مرکز' --slug your-clinic
~~~

The owner-creation command is interactive; choose a unique password instead of using the demo account. `migrate` must complete successfully before `api` starts. The new clinic starts in a restricted state until services, hours, approved facts, policies and staff coverage are configured.

Check both endpoints: `/health` verifies database access, and `/ready` reports configured dependencies. A healthy HTTP server can still lack a qualified payment account, voice route or clinic approval. Use authenticated operational screens to inspect the specific dependency and its latest observation.

## 4. Enable one integration at a time

**Calendar.** Choose whether the internal calendar or a supported external authority owns writes. Configure capability, remote identity, readback and revision handling. Test double booking, delayed responses and unknown outcomes before switching an active clinic.

**SMS and payments.** Use the clinic's approved provider credentials and its own merchant binding. Test inbound/outbound ownership, receipt verification, quiet hours, refunds, expired deposits and uncertain callbacks. A sandbox success does not justify marking live money as settled.

**Speech.** Install optional dependencies and provision approved Faster-Whisper/Piper weights separately. Configure the gateway URL and token, exact allowed hosts, model versions, processing location and explicit approval flags. Start the `speech` profile only after testing output formats, timeouts and fallbacks.

**Telephony.** Configure the actual carrier/PBX and reviewed Asterisk dialplan, private AudioSocket routing and an allowed human destination. For an accepted transfer, test staff screening, DTMF, decline/timeout and an audible two-way bridge on the real line. LiveKit browser RTC requires its separately operated server and network configuration, not merely the worker container.

Keep the text path and a staffed callback route available when optional services degrade.

## 5. Backups, migrations and keys

Before deployment changes or schema upgrades:

1. Announce a maintenance window and stop API, background and media writers.
2. Back up PostgreSQL in encrypted form and separately back up configuration/key-custody material. `scripts/backup.py` uses an approved GnuPG recipient; `scripts/config_backup.py` requires a separate protected backup key and an inventory of key custody.
3. **Restore those backups to an isolated empty target** and verify schema, counts, encrypted field access and the right application keys.
4. Run `python scripts/migrate.py` on the intended database, then check `schema_version` and representative appointments, money records, clinic memberships and policy revisions.
5. Resume workers and API; check health, business flows, queues and staff connection before reopening patient traffic.

The current supported schema path is `0001 → 0002`; unknown/partial schemas are not automatically repaired. There is no general reversible migration. If an upgrade fails, restore the tested database **and** its corresponding keys/configuration rather than manually guessing a downgrade. `scripts/rotate_encryption.py` has an offline preview and explicit apply gate; preserve previous keys until every protected record and eligible backup is accounted for.

Schedule and periodically verify backup jobs using `scripts/backup_daily.py` and the templates in `deploy/`. A backup existing on disk is not proof that a clinic can be restored.

## 6. Monitor what matters

Track queue backlog, pending calendar operations, provider health observations, booking conflicts, message delivery failures, payment liabilities, media admission/transfer failures, disk/DB health and backup age. Prometheus/alert examples live under `deploy/`; keep diagnostic endpoints restricted. A patient complaint is often the first sign that an “accepted” provider request never completed—preserve request IDs and investigate the authoritative result.

For the shift checklist, escalation and external launch review see [Operations](operations.md). For the service boundaries and failure states see [Architecture](architecture.md).
