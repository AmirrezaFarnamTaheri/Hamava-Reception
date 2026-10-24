# Core completion contracts — version 0.2

This document describes implemented application behavior. All seeded facts, local
calendar protocol responses and demonstration receipts are synthetic. A registry
approval is an accountable operator statement; it does not certify a vendor,
clinical fact, staff language skill or carrier route.

## Access and revocation

Staff login, `/me`, and clinic switch return `permissions`. The server derives
permissions from the current active membership on every request. Manager,
coordinator, billing and technical roles have distinct permissions in
`security.ROLE_PERMISSIONS`; clients must use the returned array. The technical
role does not grant patient scheduling access, and billing does not grant privacy
administration. `GET /api/v1/permissions` exposes the current permission set and
role matrix.

`POST /api/v1/auth/logout` accepts `{ "all_devices": false }`. The current JWT
session identifier is revoked, including tokens created by switching clinics.
Other device sessions stay active. Explicit `all_devices: true` increments the
user token version. Old tokens without a session identifier require login again.

`AccessControlMiddleware` records authenticated access with the route template,
actor, role, method and response status. It omits query strings and raw resource
paths. Optional `X-Action-Reason` is bounded and encrypted. Ordinary authorized
access uses the explicit `authorized_route_access` reason class; domain override,
correction and policy endpoints additionally keep their own required reasons.
This is application access auditing, not a claim to audit host administrators or
an external identity provider.

## Catalog and policy

- `GET/PUT /api/v1/core-policy`: version, six Persian time windows, provenance
  enforcement. Production cannot disable provenance. Times are quarter-hour
  boundaries and never manufacture an exact appointment instant.
- `GET /api/v1/catalog/facts`: bounded, scoped fact versions with source,
  approver, effective/expiry dates, value and hash.
- `POST /api/v1/catalog/facts/approve`: approve named current fields with source,
  effective/expiry interval and reason. Caller-supplied replacement values are
  not accepted by this endpoint.
- `GET/PUT /api/v1/services/{id}/policy`: service-specific preparation, insurance
  notes, visit policy (`any`, `first_visit`, `follow_up`, `package`), prerequisite
  service, follow-up days, package units and maximum series length.

All catalog changes remain subject to the production paused-edit/UAT policy.
Expired or modified approved facts block new calendar decisions. Fact records
are immutable versions. Operator declarations are labelled as such; real clinic
owners must verify accuracy and choose suitable expiry dates.

Package entitlements (`GET/POST /api/v1/package-entitlements`) are authorized
credits, not evidence that a payment settled. Booking consumes units atomically;
cancellation/expiry releases once. Moving a visit rechecks entitlement validity
at the new time and rejects a changed unit policy for staff review.

`POST /api/v1/booking-series` accepts an explicit list of at most twelve booking
requests for one phone. Each instance has its own durable outcome and deterministic
child idempotency key. `GET /booking-series/{id}` and `POST /{id}/resume` recover
partial work. There is no unbounded recurrence expansion or all-or-nothing claim.
External-authority packages/series require provider-specific eligibility review.

## Calendar authority and partner protocol

`GET/PUT /api/v1/calendar/authority` selects one approved internal or external
source. Changing sources requires paused automation and blocks while live
appointments, holds, pending operations or retained remote confirmations need a
migration review. Existing v1 internal calendars receive an explicit migration
provenance record; migration never invents clinic fact approval.

External connectors implement the **Hamava calendar v1 protocol** in
`calendar_contract.py`. This is an executable protocol for an authorized partner,
not an assertion of access to any named EHR or booking website. The account is
bound through both a deployment credential mapping and the approved authority
capabilities; changing the account requires renewed approval.

Every response contains the expected `account_id`. Requests carry
`X-Calendar-Account` and `X-Hamava-Protocol: hamava-calendar-v1`. Authentication is a
per-account Bearer token. Conditional writes carry `If-Match` and an opaque
`Idempotency-Key`. Redirects are rejected. Bounded timestamps are timezone aware.

| Operation | Protocol endpoint | Required behavior |
|---|---|---|
| Capabilities | `GET /capabilities` | Protocol/account/revision and truthful operation booleans; atomic conditional create/update, idempotency, readback and reconciliation required. |
| Slots | `GET /slots` | Provider, service, date query; at most 500 scoped slot records with expiry/revision. |
| Readback | `GET /appointments/{id}` | Exact ID/account, current status/revision, patient token and canonical service/provider/time. |
| Hold | `POST /holds` | Conditional slot revision; bounded hold ID, matching slot and aware expiry. |
| Release | `POST /holds/{id}/release` | Matching ID and `RELEASED` or `EXPIRED`. |
| Create | `POST /appointments` | Conditional slot revision and idempotency; subsequent GET must match submitted identity and slot. |
| Cancel | `POST /appointments/{id}/cancel` | Conditional appointment revision; readback must identify the same appointment and show canceled. |
| Update | `PUT /appointments/{id}` | Appointment and destination-slot revisions; readback must match destination and patient. |
| Reconcile | `GET /operations/by-idempotency-key` | Explicit `PENDING`, `NOT_COMMITTED` or `COMMITTED`, with current readback. |
| Changes | `GET /changes` | Bounded events, cursor and explicit completeness; event/account binding. |

The live staff API and deterministic conversation use this selected source.
Internal occupancy is never used to claim success for an external tenant. A
lost write response creates a durable `UNKNOWN` operation; recovery looks up that
operation, never automatically resubmits the write. A genuinely uncommitted
request is handed to staff for a new explicit decision.

Successful `/holds` returns `{id, hold_id, status:'HELD', expires_at, authority}`.
The optional hold `idempotency_key` should remain stable for that attempt. A
pending hold does not authorize proceeding to create.

Successful create/cancel/reschedule/readback returns an Appointment object.
Remote appointments use `id: 'external:<id>'`, string `version`, derived Tehran
`local_date`/`local_time`, and `authority: 'external'`. Unobserved attendance,
creation time and reminder opt-in are `null`; notification status is `UNKNOWN`.

Unknown or incomplete mutations instead return:

```json
{
  "operation_id": "opaque-id",
  "operation": "create",
  "operation_status": "UNKNOWN",
  "status": "PENDING_CONFIRMATION",
  "result": null,
  "error_code": "CALENDAR_UNKNOWN_OUTCOME",
  "verified_at": null,
  "requires_reconciliation": true
}
```

Cancel/update use `CANCEL_PENDING`/`RESCHEDULE_PENDING`. Other possible operation
states are `PENDING`, `SENDING`, `SUCCEEDED`, `FAILED_REVIEW`, and the public stale
view `READBACK_REQUIRED`. No pending object should trigger a confirmed toast.

`GET /calendar/operations/{id}` reads the persisted outcome.
`POST /calendar/operations/{id}/reconcile` performs authoritative lookup and adds
`booking` when verified. `GET /appointments` is the inventory of remote identities
known to this application, with `READBACK_REQUIRED`, `last_known_status` and
`verified_at`. It is not a complete EHR export. `GET /appointments/{external:id}`
performs fresh readback. Payments and visit-history/package eligibility are not
silently delegated without a supported provider workflow; those external cases
require staff review.

Signed `POST /calendar/webhooks/{tenant_id}` requires the same tenant in the
signed body. Event IDs are idempotent and conflicting replays are rejected.
Revision gaps set `SYNC_REQUIRED`; changed records become `READBACK_REQUIRED`.
The recovery worker polls the provider cursor, records lag, and clears a gap only
when the provider declares the bounded result complete.

## Provider authorization, limits and readiness

`PUT /api/v1/operations/integration-capabilities/{provider_key}` publishes
operations, endpoint/model versions, region, terms reference, evidence,
verification state and expiry. `GET /api/v1/operations/integration-capabilities`
reads the tenant-scoped collection. POST
`/{provider_key}/probe` performs a bounded health/capability read where a documented
read-only endpoint exists. The keys are `speech_primary`, `speech_fallback`,
`calendar_primary`, `sms_kavenegar`, `telephony_primary`, `payment_primary`, and
`digest_gateway`.

Capability, processing purpose/region approval and exact money reservation are
checked under the tenant fence before provider dispatch. That transaction commits
before external I/O. Fallback speech has an independent authorization and budget.
Disabling a clinic blocks new reservations and dispatches. A response to an
already-authorized attempt still settles its original, locked reservation and
preserves authenticated vendor-cost evidence; health recording skips the inactive
clinic instead of rolling back the accepted result. This exception grants no new
provider work.
The PCM submitted duration determines STT quantity when known. Compressed-input
duration is explicitly bounded provider-reported evidence. Invalid TTS WAV still
preserves accepted-text cost, but marks the dependency degraded.

`/ready` uses at most seven aggregate queries. Configured but unobserved SMS,
media and payment integrations are **unknown**, never healthy because an
environment flag is present. Real handler evidence refreshes the relevant clinic
and provider: accepted SMS sends and matching status replies, verified payment
request/settlement responses, matching media-room creation, authenticated PBX
claims, owned worker-lease renewals and verified authorized human joins. Current
capability approval and a fresh observation are both required for readiness.

Malformed responses and uncertain or failed provider I/O degrade readiness.
Generic send/payment rejection codes also degrade it because their adapter codes
cannot distinguish account/configuration errors from ordinary business declines.
A validated SMS status of `FAILED` proves the status API responded while the
message remains failed; it is not a delivery claim. Local consent/budget/config
rejections, rejected credentials, an idle global media poll, demo/sandbox results
and duplicate/stale media claims do not refresh provider health. Inactive clinics
are skipped safely when recording a completed operation.

These records establish recent control-plane evidence, not acoustic quality,
end-to-end carrier reachability, an uptime SLO or successful business outcomes.
A successful synthetic fixture is not a live health observation. `/health`
remains application/database liveness.

`run_core_jobs(db, limit=3, budget_seconds=20)` performs at most three logical
remote operations: one oldest eligible recovery, one oldest calendar cursor poll,
and one oldest/unobserved dependency scope. The real connector has a bounded
capability/readback request count; the overall tick has a twenty-second timeout.
Cancellation retains committed SENDING/STARTED evidence for recovery. Queues
include all scopes instead of repeatedly selecting a fixed first set of tenants.

Media admission reserves the bounded maximum automated duration using
`telephony_primary/telephony_seconds`. SIP grants and WebRTC room creation occur
after the reservation. Local elapsed time (including silence) is recorded
separately. Disconnect, expiry and verified human takeover retain **UNKNOWN**
liability until financial reconciliation provides carrier evidence. This protects
automated media admission; it does not promise a hard cap over the entire PBX
call, pre-routing charges, or later human participation.

## Voice, accessibility and language boundaries

`GET /api/v1/public/clinics/{slug}` returns the standard `notice`, optional
purpose-specific `processing_notice`, `processing_policy_version`, effective
`transcript_retention_days`, and `processing_notice_fingerprint` (64 lowercase
hex characters). The client displays both notices before requesting processing
consent. `POST /api/v1/public/sessions` sends that exact displayed fingerprint
alongside `processing_consent: true`. The server rechecks the fingerprint under the tenant
lock before creating the session. A changed notice, policy version or retention
cap returns `409 PROCESSING_NOTICE_CHANGED`; the client refreshes the notice,
clears consent, and requires a new explicit confirmation without automatic retry.
Real public intake also rejects a missing fingerprint. Demo-only synthetic
clients may omit it; their consent evidence explicitly records
`displayed_notice_bound: false`. A supplied stale fingerprint is rejected even in
demo mode. Trusted internal channel admission retains its separate consent path
and does not claim browser-displayed notice binding.

The original notice fingerprint, purpose version and conservative retention cap
are pinned to the call and processing-consent evidence. Recording and training
remain separate disabled defaults. Existing text and media turns recheck the
current processing-purpose policy; disabling processing rejects new AI work with
`PROCESSING_DISABLED`. Administrative transcript cleanup follows the strictest
current cap and original shorter pin, while required financial and audit records
retain their separately documented purpose and retention rules.

The live deterministic conversation calls strict, typed tool schemas. It binds
phone proof, tenant, call and idempotency on the server; model-supplied tenant or
proof fields are rejected. External tools queue work without awaiting a provider
inside the conversation transaction. Metadata includes intent, policy version,
proof state, uncertainty, pending operation and actual FSM outcome.

Persian readback renders times/prices as words and telephone/tracking identifiers
in order. `آخر وقت` selects the last actual available slot; configured fuzzy ranges
filter actual availability. English, Arabic and mixed-language routing signals
are conservative heuristics. An approved language route needs a current script,
qualified-staff attestation and existing queue; it never proves that a person has
joined. Persian remains the deployed automated language. Native partial ASR and
a generative model stream are explicitly unsupported. STT final events and
validated buffered TTS PCM chunks have common contracts; chunks are not described
as native model streaming.

`POST /api/v1/public/sessions/{id}/sms/request` requires `{phone,sms_consent:true}`
and a configured clinic receiver. The normal OTP turn verifies the phone and
records independent conversational-SMS consent. `POST /api/v1/internal/sms/inbound`
uses the signed gateway envelope `{receiver,sender,message_id,text}` with
`X-Timestamp` and `X-Signature`. HMAC binds exact bytes and time; receiver routing
selects the tenant. The sender must match one active explicitly enrolled session.
Receipts and queued encrypted replies are idempotent. Repeated critical fields
use the same tool gateway. Oversized replies hand off instead of truncating
payment or booking conditions. A carrier must authenticate inbound sender and
receipt identity before calling this gateway; this contract does not establish a
native carrier webhook deployment.

## Deployment settings added or tightened

- `CORS_ORIGINS`: exact HTTPS origins plus the explicitly chosen `app://hamava`
  desktop origin. `https://localhost` supports Capacitor. No arbitrary custom
  origin or wildcard is accepted.
- `CALENDAR_PARTNER_APPROVED`, `CALENDAR_PARTNER_URL`,
  `CALENDAR_TENANT_CREDENTIALS_JSON` (tenant ID → unique `{account_id,token}`),
  `CALENDAR_WEBHOOK_SECRET`, `CALENDAR_PROCESSOR_REGION`. A global token is not
  a substitute for tenant-bound account credentials.
- `SMS_INBOUND_TENANTS_JSON` (receiver → clinic slug),
  `SMS_INBOUND_WEBHOOK_SECRET`; production also needs the approved outbound SMS
  configuration. All enabled secrets are non-placeholder bounded values.
- `HUMAN_TRANSFER_TARGETS`: explicit PBX transfer destinations for persisted
  routing validation. Caller text cannot add a destination.
- `SMS_PROCESSOR_REGION`, `TELEPHONY_PROCESSOR_REGION`,
  `DIGEST_PROCESSOR_REGION`, `PAYMENT_PROCESSOR_REGION`: required declarations
  when the respective provider is enabled in production. Speech/calendar region
  and configured speech model/voice version declarations are also required.
  Real provider contract/rate approval remains separately required.
- `PROVIDER_HEALTH_TIMEOUT_SECONDS` (1–15),
  `PROVIDER_HEALTH_STALE_SECONDS` (10–3600),
  `PROVIDER_OPERATION_TIMEOUT_SECONDS` (1–60), `TOOL_TIMEOUT_MS` (50–30000),
  `SHUTDOWN_GRACE_SECONDS` (1–60). Media/call/concurrency/token limits are also
  validated at startup.
- The exact bounded runtime names are `ACCESS_TOKEN_MINUTES`,
  `MAX_CONCURRENT_CALLS_PER_TENANT`, `MAX_MEDIA_CONNECTIONS`,
  `MAX_LIVEKIT_ROOMS_PER_WORKER`, `MAX_CALL_SECONDS`,
  `SPEECH_MAX_CONCURRENCY`, `WHISPER_CPU_THREADS`, and `AUDIOSOCKET_PORT`.
  Existing media credentials use **`MEDIA_API_TOKEN`**, not a new secret alias.
  SIP configuration comes from approved versioned DID bindings or
  `MEDIA_DID_TENANTS_JSON`; `AUDIOSOCKET_ALLOWED_CIDRS` is an explicit network
  allowlist. A configured SIP path remains health `unknown` without observation.
- `API_DEPRECATIONS_JSON`: explicit entries `{prefix,deprecated_at,sunset_at,successor}`.
  Prefixes may identify the API or a nested `/api/v1/partner/v1` export version.
  Active entries emit Deprecation/Sunset/successor Link headers; expired versions
  return 410. Longest matching prefix controls. Configure retirement only when
  its actual successor is available; none is invented or enabled by default.

## Tool-stage timing boundary

Every executed administrative tool now records a separate monotonic duration in
the existing scoped call trace as `tool.slots`, `tool.hold`, `tool.book`,
`tool.cancel`, or `tool.reschedule`. Invalid dispatch names use the fixed
`tool.invalid` label. A span contains only duration, a fixed result classification,
transaction status and an optional fixed error classification/HTTP status. Tool
arguments, patient fields, returned values and exception text are excluded.

Successful turn receipts and their tool spans commit together. A handled
rejection or deadline retains its span after the failed calendar work rolls back.
An unhandled turn failure records a separate call-scoped aborted attempt after
rollback; if the database cannot accept that metadata, the application emits only
the static `tool_trace_persistence_failed` event. Process death before persistence
can leave no span and is not claimed as observed coverage. Receipt replay does
not execute or count the tool again.

The latency endpoint adds `tool_slots`, `tool_hold`, `tool_book`, `tool_cancel`,
and `tool_reschedule` successful-duration distributions. Queued external
operations, failures and rolled-back attempts remain in the trace and are
excluded from those successful percentiles. A completed local dispatch does not
prove a remote booking was confirmed. These values do not measure physical
speaker playback; no generative-model stage is deployed.

## External acceptance still required

A contracted calendar adapter deployment, actual authenticated carrier receipts,
language-qualified staffing and pickup drills, measured speech/acoustic quality,
physical device/accessibility testing and provider pricing/rights/region approval
remain external inputs. The executable local tests exercise transactional and
protocol behavior, not those operational outcomes.
