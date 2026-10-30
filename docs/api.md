# API guide

[فارسی](api.fa.md) | [Documentation](README.md)

## Source of truth and access

The server is implemented in FastAPI under `backend/receptionist/`. Its live, revision-specific contract is `GET /openapi.json`; the interactive Swagger view is `/docs` when available. Most application routes use `/api/v1`. Do not infer a stable operation from a stale generated report.

Staff authenticate with `POST /api/v1/auth/login` and submit `Authorization: Bearer <access_token>`. `GET /api/v1/me` and `GET /api/v1/permissions` expose the currently authenticated membership and permissions. `POST /api/v1/auth/switch` issues a newly scoped credential after verifying membership; `POST /api/v1/auth/logout` revokes the selected session or, when explicitly requested, all sessions. Every protected request is checked server-side.

## Important endpoint groups

| Group | Representative endpoints | Meaning |
| --- | --- | --- |
| Discovery | `GET /api/v1/client-info`, `GET /health`, `GET /ready` | Public client compatibility, database liveness, dependency readiness |
| Clinics and catalog | `GET /api/v1/clinics`, `GET /api/v1/practitioners`, `GET /api/v1/services` | Tenant-scoped organization, people and service metadata |
| Calendar | `GET /api/v1/slots`, `POST /api/v1/holds`, `GET /api/v1/appointments`, `POST /api/v1/appointments` | Availability, expiring holds and committed appointments |
| Mutations | `POST /api/v1/appointments/{appointment_id}/reschedule`, `/cancel`, `/approve` | Guarded state transitions, not blind updates |
| Staff operations | `GET /api/v1/tasks`, `GET /api/v1/notifications`, `GET /api/v1/audit` | Scoped work, messaging outcomes and history |
| Settings and health | `GET /api/v1/settings`, `GET /api/v1/usage`, `GET /api/v1/dashboard` | Authorized policy and operational views |

Additional routers implement consent, conversation, media, external calendars, provider control, payments, privacy, outreach and partners. Use OpenAPI for their exact paths, shapes and status codes. The client compatibility request sends no staff secret.

## Result semantics

A successful HTTP response is not necessarily a final business outcome. A **hold** is not a booking; a remote calendar write may remain pending until authoritative read-back; an SMS acknowledgement is not confirmed delivery; a payment intent/webhook is not independent settlement proof; a handoff request is not a connected staff call. The UI must display pending/unknown/failed statuses without inventing success.

Use idempotency keys as documented by the endpoint; preserve request identifiers for diagnostics. API errors commonly use `{"detail":{"code":"...","message":"..."}}`, whereas FastAPI validation errors retain their standard detail format. Callers should handle both. Never put session credentials, patient identifiers or secret response-link fragments in logs.
