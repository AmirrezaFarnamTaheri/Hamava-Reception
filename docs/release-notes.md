# Hamava Reception 0.2.2: release notes

[فارسی](release-notes.fa.md) | [Documentation](README.md)

Version **0.2.2** brings the reception server, Persian workspace, patient conversation, operational controls and Windows/Android packaging together. This guide explains what the release includes, how to use it, and the checks to perform before upgrading a clinic.

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

## A walkthrough from request to result

A receptionist signs in, selects a clinic, chooses a service and practitioner, and checks available slots. A short-lived hold reserves the selected time while details are confirmed. The server checks occupancy again before committing the appointment. If another staff member made a change in the meantime, the appointment-version check prevents a silent overwrite. Notification delivery is tracked separately from the booking itself.

A patient can instead use the public Persian conversation. The assistant clarifies ambiguous Jalali dates and names, reads proposed actions back, and requests human help when the case cannot safely be completed. Both interfaces use the same scheduler and clinic policy. The result is one authoritative booking rather than competing staff and conversational calendars.

External systems introduce an important extra step. A calendar write, provider-accepted SMS and payment initiation may each need later verification. Operations screens keep uncertain results visible so staff can reconcile them rather than accidentally retrying a completed action.

## Build and distribution in practice

The repository runs server/PostgreSQL, browser, desktop bridge and container checks through GitHub Actions. The native release workflow builds Windows NSIS/portable and Android APK/AAB artifacts, collects checksums and can create a signed draft GitHub Release when the necessary credentials and tag are available.

For a source-only package, run `python scripts/make_source_release.py --output ../hamava-source.zip`. For native packages use [Clients and releases](clients-and-releases.md), and record the actual artifact digest, publisher signature, tested OS and installation result. A source archive and a signed installer serve different purposes.

## A release checklist with an explicit owner

Before anyone distributes a build, identify the exact source commit and workflow run. The artifact name alone is not enough: an installer with the right version string may still be unsigned, built from the wrong commit or missing a required file.

| Checkpoint | Where to inspect it | What to record |
| --- | --- | --- |
| Source and version | Commit, tag, `node scripts/check-versions.mjs` | Commit SHA, release version and tag |
| Verification | `.github/workflows/verify.yml` | Run ID and result for every required job |
| Archive integrity | Manifest and SHA-256 of the generated file | File name, digest and storage location |
| Windows identity | Signing check and an installed Windows test | Publisher identity, OS version and upgrade result |
| Android identity | Keystore signing check and device tests | Package/version identity, device and install result |
| Existing data | A restored backup and migration result | Schema version, record checks and recovery owner |
| Clinic acceptance | Named operations and provider checks | Accepted features, remaining limits and staff fallback |

For a source-only archive, run the following from the repository root. The script deliberately refuses to write its output **inside** the source tree.

~~~sh
python scripts/make_source_release.py --output ../hamava-source.zip
~~~

This produces a source archive with its own content manifest. It is different from an installed or publisher-signed native application. Keep the exact build and test evidence with the release record, not as historical screenshots copied into the handbook.

## Upgrading a running clinic

Treat the upgrade as a short operational change, not just a code replacement. Record the previous revision, stop writers, take a recoverable encrypted backup with the matching keys, deploy the intended image, run the schema migration and verify existing appointments, membership and finance records. Restart the API and worker only after the migration has succeeded.

If the new version fails its functional checks, use the documented restoration route and the matching old configuration. Do not try to invent a reverse SQL migration for schema `0002`. The [deployment guide](deployment.md) explains the restore drill and startup checks; [operations](operations.md) covers the staff acceptance decision.

## Still required for real-world launch

Independently verify legal/clinical and privacy approvals; carrier/PBX routing and audible two-way staff transfer; actual calendar authority; SMS delivery receipts; payment settlement and reversals; secure secrets and backup restoration; native signing and physical device upgrade/logout behavior; approved speech rights and real noisy Persian-telephone metrics; supervised clinic acceptance and staffed fallback.

The source history and GitHub Actions logs are the evidence trail for each commit. Synthetic fixtures and historical reports must never be represented as current external acceptance.
