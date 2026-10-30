# API guide: working with the reception service

[فارسی](api.fa.md) · [Documentation](README.md)

Hamava's HTTP API is served by FastAPI. Most operations are under `/api/v1`; health endpoints are at the root. This guide describes the calling conventions and a typical workflow. For the full field-level contract of the **running build**, use `/openapi.json` or the interactive `/docs` page.

## Connecting a client

A new companion checks the address before asking for a password:

~~~http
GET /api/v1/client-info
~~~

The response identifies `product: "hamava"`, `api_version: 1`, `app_version` and whether the server is in demo mode. The compatibility check is intentionally credential-free. A production Android client requires HTTPS; server selection must not accept a URL containing user information, query parameters or arbitrary paths.

Staff sign in with:

~~~http
POST /api/v1/auth/login
Content-Type: application/json

{"email":"owner@example.test","password":"DemoReception2026!"}
~~~

This account is available only in the fictional demo. The response includes a bearer token and a user object scoped to an active clinic membership. Protected requests send `Authorization: Bearer <access_token>`. `GET /api/v1/me` returns the current user context, `GET /api/v1/permissions` returns authorized capabilities and `GET /api/v1/clinics` lists memberships.

To work in another clinic, send `POST /api/v1/auth/switch` with `{"tenant_id":"<authorized-tenant-id>"}` and use the returned scoped token. To end a session, use `POST /api/v1/auth/logout` with `{"all_devices":false}`; `true` explicitly revokes all device sessions. The server checks active membership and permissions again on each request. Hiding a menu item is not a security boundary.

## Common route map

| Area | Endpoints | Main use |
| --- | --- | --- |
| Authentication | `/auth/login`, `/auth/switch`, `/auth/logout`, `/me`, `/permissions` | Sign in, scope and revoke access |
| Catalog | `/clinics`, `/practitioners`, `/services`, `/settings` | Published clinic configuration |
| Scheduling | `/slots`, `/holds`, `/appointments` | Availability, temporary reservation and final booking |
| Changes | `/appointments/{appointment_id}/cancel`, `/reschedule`, `/approve` | Version-checked transitions |
| Work | `/tasks`, `/notifications`, `/audit`, `/dashboard` | Staff work and operational history |
| Public reception | `/public/clinics/{slug}`, `/public/sessions`, `/public/sessions/{session_id}/turn` | Consent-first visitor conversation |
| Calendar authority | `/calendar/authority`, `/calendar/operations`, `/calendar/operations/{operation_id}/reconcile` | Remote-calendar configuration and reconciliation |
| Costs and controls | `/operations/costs`, `/operations/integration-capabilities`, `/operations/privacy-controls/purposes` | Budget, provider permission and processing policy |
| Calls | `/operations/calls`, `/operations/calls/{call_id}/takeover` | Staff calls and takeover requests |

All routes in this table, except the public reception routes, generally require an authenticated staff member with the appropriate permission. The full application has additional payment, refund, waitlist, consent, outreach, partner and media endpoints; discover their exact schemas from OpenAPI rather than guessing their request bodies.

## Booking through the API

### 1. Find a slot

~~~http
GET /api/v1/slots?provider_id=<provider-id>&service_id=<service-id>&date=2026-11-03
Authorization: Bearer <access_token>
~~~

`date` is an ISO Gregorian date for the transport contract; the interface can display the corresponding Jalali date. Select a slot from the response rather than manufacturing the signed `slot_id`.

### 2. Hold the chosen slot

~~~http
POST /api/v1/holds
Authorization: Bearer <access_token>
Content-Type: application/json

{"slot_id":"<signed-slot-id>","session_id":"staff-demo"}
~~~

The hold has a finite lifetime. It is not the appointment and must not be presented as confirmation.

### 3. Confirm the booking

~~~http
POST /api/v1/appointments
Authorization: Bearer <access_token>
Content-Type: application/json

{
  "slot_id": "<signed-slot-id>",
  "hold_id": "<hold-id-if-issued>",
  "patient_name": "بیمار نمونه",
  "phone": "09120000000",
  "idempotency_key": "example-booking-20261103-0001",
  "confirmed": true,
  "reminder_opt_in": false
}
~~~

The request uses the exact fields in `BookingInput` (`backend/receptionist/schemas.py`). Where the service requires a deposit, read the currently published payment terms and submit their version and separate acceptance fields. Do not set `payment_terms_accepted` without a deliberate user choice.

### 4. Change the booking safely

A reschedule supplies the current appointment `version`, a newly selected `slot_id` and a fresh idempotency key. A cancellation likewise supplies its version, reason and idempotency key. If the appointment has changed, refresh it and resolve the conflict; do not force a stale update.

## Internal and external calendars

For the internal scheduler, an appointment mutation either commits or returns an error. An external calendar can return a **pending operation**, even when transport succeeded. Read `/api/v1/calendar/operations/{operation_id}` and reconcile with provider readback using the authorized workflow. The state record, not the status code alone, determines whether staff should promise a booking.

The same principle applies to SMS (accepted versus delivered), payment (intent versus settled) and telephony (requested versus staff bridged).

## Public sessions and media

`GET /api/v1/public/clinics/{slug}` supplies the public clinic configuration and current processing notice. `POST /api/v1/public/sessions` is consent-aware and creates a scoped session. Subsequent turns use the session bearer token rather than a staff token. Audio and LiveKit endpoints require separate configured capabilities. A failed microphone/RTC connection should leave the text route available, and public response-link secrets must not be copied into telemetry or stored as ordinary navigation history.

## Errors, retries and tracing

Application errors commonly have this shape:

~~~json
{"detail":{"code":"SOME_CODE","message":"پیام قابل فهم برای کاربر"}}
~~~

Validation errors use FastAPI's standard structure, so clients should handle both. HTTP `409`-style business conflicts and ambiguous external outcomes should be represented separately from ordinary connectivity failures. `X-Request-ID` can correlate safe diagnostic events; do not log patient transcripts, bearer tokens or response-link fragments.

For broader design decisions see [Architecture](architecture.md). Staff-facing exception handling is in [Operations](operations.md).
