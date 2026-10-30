# Hamava documentation

[فارسی](README.fa.md) · [Project home](../README.md)

**Start with the job you're doing.** This handbook covers Hamava Reception source version **0.2.2**. All maintained guides have an English version and an equivalent Persian version, linked at the top of each page.

## Find your guide

| You're trying to… | Start here | You'll learn |
| --- | --- | --- |
| Understand the product or demonstrate it | [Product and workflows](product.md) | Who uses Hamava, how a booking proceeds and what the staff sees |
| Understand why a request has a particular state | [Architecture](architecture.md) | Service boundaries, state transitions, external calendars and persistence |
| Build a client or integrate another service | [API](api.md) | Authentication, route groups, booking examples and error handling |
| Change or review the code | [Development](development.md) | Local setup, test strategy, migrations and code ownership |
| Install Hamava for a center | [Deployment and recovery](deployment.md) | Production configuration, Compose, integrations, backups and rollback |
| Manage a center's working day | [Operations](operations.md) | Onboarding, shift routines, exceptions, incidents and approval |
| Attest a clinic's production configuration | [Clinic acceptance](clinic-acceptance.md) | Five required synthetic checks, evidence, fingerprint and renewal |
| Enable an external provider | [Provider integrations](provider-integrations.md) | Credentials, permissions, health observations and real acceptance tests |
| Handle consent, export or erasure | [Privacy operations](privacy-operations.md) | Independent purposes, withdrawal, disclosure and backup follow-up |
| Diagnose a failed workflow | [Troubleshooting](troubleshooting.md) | Health signals, error handling, reconciliation and incident closure |
| Build Windows or Android applications | [Clients and releases](clients-and-releases.md) | Native architecture, build steps, signing and device checks |
| Evaluate voice models or the business case | [Research](research.md) | Dataset governance, speech metrics, capacity and pilot design |
| Review the current release scope | [Release notes](release-notes.md) | Source capabilities, upgrade notes and distribution boundaries |
| Trace an original requirement | [Requirements register](requirements-register.md) | How to interpret the 263-item historical inventory and archived evidence |

The web interface has its own [developer entry point](../frontend/README.md). The deliberately synthetic research inputs are explained in [fixture notes](../fixtures/research/README.md).

## How these documents fit together

A **patient asks for an appointment**. The product guide describes what the patient experiences; the API guide shows the calls; architecture explains why the scheduler checks capacity again before committing. The operations guide tells staff what to do if the result is uncertain. Deployment explains how to keep the service running and how to recover it after failure.

A **team wants to enable phone calls**. Begin with provider approval and controlled tests in [Provider integrations](provider-integrations.md). [Architecture](architecture.md) explains what counts as an observed staff connection. [Deployment](deployment.md) covers private networking, and [Clinic acceptance](clinic-acceptance.md) records the five production checks. [Research](research.md) covers speech measurement.

A **developer changes the app**. Start with the relevant code area in development, add a regression test, and use API/architecture to preserve the contract. Update both language versions of the affected guide.

## Which source is authoritative?

For implemented behavior, inspect the relevant code, tests and the running server's `/openapi.json`. For a specific revision's test outcome, inspect its GitHub Actions run and downloadable artifacts. For real-world readiness, inspect the center's actual acceptance records, provider receipts and deployment observations. The handbook explains the workflow; it is not a substitute for those observations.

The [requirements register](requirements-register.md) is an original **0.2.0 snapshot**, not a current completion dashboard. Some evidence paths in that JSON refer to files preserved in Git history after the repository cleanup. They are not live files or present-day test results.

## Start with the symptom when something goes wrong

| You see… | Read first | Then check |
| --- | --- | --- |
| A booking was requested but has no confirmed slot | [Product](product.md) | [API](api.md) and [Architecture](architecture.md) for holds, states and retries |
| The server responds, but a provider operation is stuck | [Troubleshooting](troubleshooting.md) | [Provider integrations](provider-integrations.md) for approval, readiness and reconciliation |
| A phone call says it transferred but nobody answered | [Operations](operations.md) | [Architecture](architecture.md) for bridge evidence |
| A native app fails on first connection | [Clients and releases](clients-and-releases.md) | [Frontend guide](../frontend/README.md) for the handshake |
| A test passes locally but fails in CI | [Development](development.md) | The actual workflow job and its artifacts |
| A historic acceptance link is missing | [Requirements register](requirements-register.md) | The named source commit in Git history |

## Keep the same words for the same states

The code keeps state identifiers in English. User-facing Persian should explain the state without changing its meaning. The shared vocabulary below is a useful review reference, not a replacement for the API enum values.

| Code or English term | Recommended Persian wording |
| --- | --- |
| Hold / held slot | رزرو موقت |
| Confirmed appointment | نوبت قطعی |
| `PENDING_PAYMENT` | در انتظار پرداخت |
| `PENDING_STAFF_APPROVAL` | در انتظار تأیید پذیرش |
| Unknown external outcome | نتیجهٔ نامعلوم سرویس بیرونی |
| Reconciliation | تطبیق نتیجه با مرجع |
| Callback task | وظیفهٔ تماس مجدد |
| Observed staff bridge | اتصال مشاهده‌شدهٔ بیمار به کارمند |

Translate for the reader, but keep executable commands and machine-readable state values unchanged. For screenshots or support replies, prefer the phrase a receptionist would recognize over a literal translation of a database column.

## Editing the handbook

- Change the English and `.fa.md` counterparts together. Prefer concrete instructions, examples and failure handling to repeated status claims.
- Do not translate code identifiers, CLI commands or API paths; do translate user-facing explanations naturally.
- Keep generated logs, screenshots, transient reports, credentials and customer data out of tracked documentation. Link evidence to the exact CI run instead.
- Run `node --test scripts/check-docs.test.mjs`, `node scripts/check-docs.mjs` and `node scripts/check-versions.mjs` before submitting a change.

The license notice under `docs/licenses/` remains in its original wording. It is not an editorial guide and should not be edited as a translation exercise.
