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

## A complete request sequence with curl

Use a local demo, a staff account and fictional patient details for this exercise. The commands assume a POSIX shell. Sign in using the `/auth/login` request above, then paste the returned `access_token` into the local variable without saving it in a shared script.

~~~sh
BASE='http://127.0.0.1:8000'
TOKEN='<access_token returned by auth/login>'
curl -sS -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/services"
curl -sS -H "Authorization: Bearer $TOKEN" "$BASE/api/v1/practitioners"
~~~

Choose a service and practitioner that belong to the same selected clinic. Fetch available signed slots using their returned IDs:

~~~sh
curl -sS -G "$BASE/api/v1/slots" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode 'provider_id=<provider-id>' \
  --data-urlencode 'service_id=<service-id>' \
  --data-urlencode 'date=2026-11-03'
~~~

Take a `slot_id` from the response. The hold endpoint accepts `slot_id`, an optional `session_id` and an optional idempotency key. If it returns a hold ID, include that ID in the booking request. The example below shows the shape of the write; the placeholders must come from the current server response.

~~~sh
curl -sS -X POST "$BASE/api/v1/appointments" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"slot_id":"<returned-slot-id>","patient_name":"بیمار آزمایشی","phone":"09120000000","idempotency_key":"demo-create-20261103-01","confirmed":true,"reminder_opt_in":false}'
~~~

The booking may be `PENDING_PAYMENT` or `PENDING_STAFF_APPROVAL` rather than immediately `CONFIRMED`. Payment terms require their current version and deliberate acceptance when the service demands a deposit. Record the returned appointment ID and version before changing it.

Here is the shape of a cancellation request. Version `1` is illustrative, so read the appointment first and use its actual version.

~~~http
POST /api/v1/appointments/<appointment-id>/cancel
Authorization: Bearer <access_token>
Content-Type: application/json

{"version":1,"reason":"درخواست بیمار","idempotency_key":"demo-cancel-20261103-01"}
~~~

## Handle errors according to their meaning

| Observation | What it means | What the client should do |
| --- | --- | --- |
| `401` | The protected call has no valid session | Ask the user to sign in again; do not silently replay the write under a new identity |
| `403` | Membership or permission does not allow the action | Explain the restriction; leave the server as the authority |
| `409` and `IDEMPOTENCY_MISMATCH` | A key was reused for different content | Investigate the earlier operation and correct the request identity |
| Stale appointment version | Another action already changed the record | Read the new appointment, then let the user review the change |
| `422` | Invalid fields or a failed business condition | Show the specific message and let the user correct the input |
| `/ready` returns `503` | A configured dependency is unavailable | Inspect that dependency before relying on the affected workflow |
| Remote write times out | The remote service may already have committed it | Find the recorded operation and reconcile using its original identity |

A read-only request can usually be retried after a network failure. A booking, calendar, payment or refund write can require readback before retry. Do not generate a new idempotency key every time an HTTP request fails.

## Integration-test the full journey

Test a staff login, clinic switching, slot search, hold, booking, readback and cancellation. Replay an identical booking request with the same idempotency key and verify the recorded result is returned. Reuse that key with different details and verify the mismatch is rejected. Finally, attempt a cancellation with an outdated version and check that the client refreshes the record instead of displaying a false success.

Use `backend/tests/test_core_integrations.py` and the browser suites as examples of server-side and client-side regression coverage. For field-level requirements, inspect the OpenAPI document generated by the exact version under test.

## Errors, retries and tracing

Application errors commonly have this shape:

~~~json
{"detail":{"code":"SOME_CODE","message":"پیام قابل فهم برای کاربر"}}
~~~

Validation errors use FastAPI's standard structure, so clients should handle both. HTTP `409`-style business conflicts and ambiguous external outcomes should be represented separately from ordinary connectivity failures. `X-Request-ID` can correlate safe diagnostic events; do not log patient transcripts, bearer tokens or response-link fragments.

For broader design decisions see [Architecture](architecture.md). Staff-facing exception handling is in [Operations](operations.md).
