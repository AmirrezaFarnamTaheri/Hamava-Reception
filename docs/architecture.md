# System architecture and invariants

[فارسی](architecture.fa.md) | [Documentation](README.md)

## Deployment topology

- **FastAPI server** (`backend/receptionist/main.py`): HTTP admission, auth, routing, policy, scheduling, public conversation, API and operational health.
- **Transactional store** (`backend/receptionist/db.py`, `models*.py`): PostgreSQL 16 in production, isolated SQLite for demo/tests. Server DB is the single source of truth for clinics, appointments, outbox and financial records.
- **Worker** (`backend/receptionist/worker.py`, `operations*.py`, `core_runtime.py`): durable reminders, follow-up, control-plane jobs, retries and reconciliation. Run separately from API unless the explicit in-process flag is selected.
- **Shared interface** (`frontend/src/`): React/TypeScript/Vite RTL portal, patient conversation and role-scoped administration.
- **Native hosts** (`apps/desktop/`, `apps/mobile/`): Electron and Capacitor presentation/credential boundaries to an HTTPS clinic server.
- **Optional media** (`backend/receptionist/media/`, `services/local_speech/`, `deploy/asterisk/`): private AudioSocket, WebRTC/LiveKit, screened Asterisk handoff and speech gateway. Supplier connectivity is *not* bundled or enabled implicitly.
- **External adapters:** calendars, SMS, payments, provider cost control, outbound voice and partner services are accessed through reviewed capabilities, distinct identities and explicit readiness states.

## Authoritative transaction model

An appointment mutation validates actor, tenant, clinic policy, practitioner and resource occupancy, holds, expiry, consent and idempotency before recording results. The appointment state, occupancy, audit and notification intention commit atomically. A successful remote calendar request is only an **attempt** until the external authority supplies a verified read-back. Unknown outcomes remain pending reconciliation; they are never silently treated as success or retried as fresh writes.

The administrative conversation is bounded by verified fields and allowed tools. It freezes a call clock, parses Persian digits/Jalali dates, requests clarification for ambiguity, uses approved catalog facts and reads back actions before final writes. Human-transfer state differentiates **requested**, **screened**, **accepted**, **bridged** and **failed**; only validated actual membership/bridge evidence can establish connection.

## Security and privacy boundaries

Every protected request rechecks the current tenant membership and role-derived permission; frontend route visibility is not authorization. Clinic switching issues scoped session credentials. Dedicated media, provider, PBX, webhook, and monitoring secrets are distinct from staff tokens. Protect signing and encryption keys outside source control; logs and tracing must avoid raw patient content, secrets and query strings.

Consent, processing purpose, processor approval, retention, withdrawal and governed artifact rules are distinct. A temporary recording is not permission to retain it for research. Monetary amounts use exact decimal/micro-Toman contracts rather than imprecise browser floating point. Provider charges have explicit reservation, observed usage and unknown-liability reconciliation states.

## Schema evolution

`backend/receptionist/migrations.py` defines **0001 → 0002** without dropping existing clinic records; v2 includes preserving/encrypting legacy billing notes. Production startup validates the supported schema and rejects unknown or partial states. **Never delete versioned migration history** as “old code”: existing installations depend on the upgrade path. Add future changes with tested forward-only versions and a proven backup/restore route.

## Readiness boundaries

`/health` checks database reachability; `/ready` reflects configured dependency observations. Neither by itself is evidence of carrier acceptance, staff transfer intelligibility, external read/write permission or production sign-off. Operator approval and real integration testing remain mandatory.
