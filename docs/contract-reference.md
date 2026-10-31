# Contract reference: where to verify a documented instruction

[فارسی](contract-reference.fa.md) · [Documentation](README.md) · [Development](development.md)

This reference identifies the sources behind Hamava's documented HTTP routes, command-line tools, environment variables and recovery instructions. Use the source at the exact commit being deployed or reviewed. A command can exist in one release and change in another.

The executable examples in the handbook are intended for synthetic or explicitly authorized environments. A passing static check confirms the spelling of a route or option, not that the operation is safe or successful in a real clinic.

## HTTP requests and response contracts

| Area | Route or contract source | Check before changing documentation |
| --- | --- | --- |
| Authentication, clinic scope, booking, tasks, settings | `backend/receptionist/api.py` | Method, route, `staff_actor` or permission dependency and accepted request model |
| Booking fields, cancellation versions and policy updates | `backend/receptionist/schemas.py` | Required fields, defaults, bounds and accepted enum values |
| Public conversations | `backend/receptionist/voice.py` | Public session authorization, processing notice and session-specific credentials |
| External calendar | `backend/receptionist/calendar_bridge.py`, `calendar_contract.py` | Current authority, operation identity, readback and reconciliation state |
| Provider capability declarations | `backend/receptionist/provider_control.py` | Provider key, `CapabilityInput` fields, attestation and probe limitations |
| Clinic configuration acceptance | `backend/receptionist/operations_uat.py` | Required checks, configuration fingerprint, attestation validity and mode guard |
| Consent and subject permissions | `backend/receptionist/privacy_controls.py` | Policy version, purpose, consent evidence, withdrawal and erasure state |
| Payments, notifications and subject export/deletion | `backend/receptionist/operations.py`, `payment_policy.py` | Authorized role, business outcome, durable state and provider confirmation |
| Staff and media | `backend/receptionist/media_api.py`, `operations_extensions.py` | Requested transfer versus observed connection, task owner and worker state |
| Operational health and timing | `backend/receptionist/main.py`, `telemetry.py` | `/health` versus `/ready`, scoped diagnostics, observation windows and thresholds |

All applicable routers are mounted in `backend/receptionist/main.py`. On a running instance, `/openapi.json` gives the version-specific method and request schemas. The source and tests are still needed to understand permission checks, effects of retries and provider-specific behavior.

## Command-line entry points

| Program | Accepted interface relevant to the handbook | Constraint |
| --- | --- | --- |
| `scripts/generate_env.py` | `--host`; optional `--output` | Creates a new private production environment file; refuses overwrite |
| `scripts/admin.py` | `--email`, `--clinic-name`, `--slug` | Prompts for the new owner's password; do not use the demo password |
| `scripts/backup.py` | `backup --output --recipient`; `restore --source --acknowledge-empty-target [--verify-application-key]` | Uses private `BACKUP_DATABASE_URL`; backup recipient is a reviewed full hexadecimal GnuPG fingerprint |
| `scripts/config_backup.py` | `create --file --inventory --key-file --output`; `restore source --key-file --target [--confirm-empty-target]` | Uses a separate Fernet backup key and restores only to an authorized empty target |
| `scripts/rotate_encryption.py` | Dry-run by default; `--apply --acknowledge-offline-tested-backup` to write | Stop writers and verify a recoverable backup; keep `LOOKUP_HASH_KEY` unchanged |
| `scripts/ci_ui.py` | Suite names and `--port` | Starts disposable synthetic databases and servers; not a production smoke test |
| `scripts/postgres_stress.py` | `--acknowledge-isolated-test-database --contenders --output` | Requires a dedicated database through `TEST_DATABASE_URL` |
| `scripts/production_smoke.py` | `--acknowledge-isolated-test-database --output` | Tests software invariants on the isolated database |
| `scripts/audit_dead_code.py` | `--check --output`; optional `--root` | Reports source reachability, not every dynamic framework entry point |
| `scripts/make_source_release.py` | `--output`; optional `--source`, `--manifest-out` | Source ZIP is not a signed native installer |
| `scripts/launch_readiness.py` | `--evidence-dir --output`; optional `--manifest` | Produces an evidence inventory and deliberately returns exit code **2**. It cannot certify a live clinic |

Each source file defines its full argument grammar. Positional arguments and subcommands matter as much as the flag names. For the backup and recovery sequence, see [Deployment](deployment.md); for external acceptance, see [Clinic acceptance](clinic-acceptance.md) and [Provider integrations](provider-integrations.md).

## Configuration: which file defines the value?

| Configuration group | Source to inspect | Important distinction |
| --- | --- | --- |
| Local demo | `.env.example` | Uses `DEMO_MODE=true` and a local SQLite database; never reuse it as production configuration |
| Production template | `.env.production.example`, `scripts/generate_env.py` | Identifies required credentials and provider switches; the generator creates new secrets but does not approve integrations |
| Runtime validation | `backend/receptionist/config.py` | Validates active providers, allowed hosts, origins, required tokens and production-mode restrictions |
| Database and encryption | `DATABASE_URL`, `ENCRYPTION_KEY`, `ENCRYPTION_PREVIOUS_KEYS`, `LOOKUP_HASH_KEY` | Recover application keys independently of a database dump; ciphertext rotation must not rotate the lookup hash key |
| Provider network policy | `APPROVED_PROVIDER_HOSTS`, `ALLOW_LOCAL_HTTP_PROVIDERS`, `PROVIDER_HEALTH_STALE_SECONDS` | An allowed host does not imply processor approval or a successful business write |
| Backup process | `BACKUP_DATABASE_URL` used by `scripts/backup.py` | Operator-supplied private database URL, separate from the normal app process |
| Isolated verification | `TEST_DATABASE_URL` used by PostgreSQL regression scripts | Never point destructive tests at a clinic database |

Do not copy credentials, complete `.env.production` files, patient identifiers or decrypted backups into an issue or PR. In an incident, retain the permitted request ID, timestamp, code revision, error code and evidence location.

## Automated contract checks

The repository has three complementary commands:

| Command | What it verifies |
| --- | --- |
| `node scripts/check-docs.mjs` | English–Persian file pairs, local links, balanced fences and identical executable blocks |
| `node scripts/check-doc-contracts.mjs` | Fenced HTTP method and path against direct FastAPI decorators; documented `python scripts/…` flags against their specific argparse subcommand declarations; explicit `npm --prefix` scripts against their package manifests |
| `node scripts/check-versions.mjs` | Release number consistency across the Python, web, native, Compose and release-notes surfaces |

The contract checker runs on both languages and reports the document and code-fence line of a mismatch. Its unit tests live in `scripts/check-doc-contracts.test.mjs`; the bilingual checker tests live in `scripts/check-docs.test.mjs`. CI runs both.

The checks **do not** parse request bodies into Pydantic models, run authorization decisions, test hidden dynamic routes or establish the effects of remote calls. They also do not determine whether a Persian paragraph preserves every qualification in its English counterpart. Compare the current OpenAPI schema and source tests when editing a request, and review each translation with someone who understands the operational consequences.

## Evidence needed beyond code

An operator can run a successful health probe while SMS delivery, payment settlement, PBX bridging or external-calendar reconciliation still fails. Keep these outcomes separate. The route and CLI inventories above establish which interface the software exposes, while the real acceptance records establish what happened on the provider and clinic side.

For incidents, start at [Troubleshooting](troubleshooting.md). For retention, export and erasure, use [Privacy operations](privacy-operations.md). When a command or field changes, update the specific task guide and its Farsi pair in the same PR.
