# Hamava Reception 0.2.2 — source-candidate release notes

[فارسی](release-notes.fa.md) | [Documentation](README.md)

**Release class:** development source candidate. These notes describe source capabilities and distribution mechanisms; **they do not certify** a signed Windows release, store-approved Android app, production carrier, approved clinic, deployed provider integration or representative speech quality.

## What is included

### Reception and scheduling

- Persian-first, RTL reception workspace and responsive appointment, task, call and management views.
- Transactional scheduling with checked practitioner/resource occupancy, temporary holds, idempotent booking changes, audit records, staff approval and appointment-response workflows.
- Patient text conversation with Jalali dates, verification, explicit confirmation, task escalation and safe administrative boundaries.
- Scoped tenant permissions and current-membership checks, with separately governed service catalog facts, routing and calendar authority.

### Communications and operations

- Durable notifications, consent/quiet-hour controls, waitlist offers, outreach, follow-up tasks, service disruption and daily-review surfaces.
- Payment intentions, deposit-policy acceptance, refund/dispute tracking and exact financial reservation/reconciliation records; these are not live bank settlement claims.
- Approved-provider configuration, observed readiness, privacy-purpose controls, retention and artifact governance, and private operational metrics.
- Optional AudioSocket and LiveKit workers plus screened Asterisk human handoff, with an additional optional streaming STT/TTS integration. Disabled or unaccepted external paths remain closed.

### Native clients and delivery

- Shared React/TypeScript web interface, sandboxed Electron desktop host and Capacitor Android companion.
- Automated verification and packaging workflows, SHA-256 artifact inventory and opt-in publisher signing/draft GitHub release behavior.
- Forward-only database schema **0001 → 0002** with preserved operational records and protected legacy billing-note conversion.
- Bilingual final project documentation with automated translation-pair and link checks.

## Compatibility and upgrade

Runtime baseline: Python **3.12**, PostgreSQL **16** for production, Node.js **24** for the web/native build, and the locked dependencies in this repository. Do not deploy upgrades before taking and verifying an encrypted database and key/configuration backup. Pause writers, execute `python scripts/migrate.py`, inspect schema version and records, and verify staff workflows before restoring traffic. **Do not remove the 0001 migration path**, since earlier installs depend on it.

Use `node scripts/check-versions.mjs` for version parity. The native release workflow publishes artifacts only after the required quality checks. Signed draft release creation requires an explicit tagged, signed, authorized run and does not publish to app stores.

## Still required for real-world launch

Independently verify legal/clinical and privacy approvals; carrier/PBX routing and audible two-way staff transfer; actual calendar authority; SMS delivery receipts; payment settlement and reversals; secure secrets and backup restoration; native signing and physical device upgrade/logout behavior; approved speech rights and real noisy Persian-telephone metrics; supervised clinic acceptance and staffed fallback.

The source history and GitHub Actions logs are the evidence trail for each commit. Synthetic fixtures and historical reports must never be represented as current external acceptance.
