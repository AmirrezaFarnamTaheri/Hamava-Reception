# Application API contract

All application endpoints use `/api/v1`. Staff requests send `Authorization: Bearer <access_token>`. The token identifies a server-checked tenant membership. A caller cannot choose arbitrary `tenant_id` values. Error responses are `{detail: {code, message}}` (validation errors use FastAPI's standard details).

**Version 0.2.0 extensions:** `core-extension-contract.md` specifies current permissions, provider capabilities, approved facts, routing, external-calendar authority, packages/series and typed tools. `v2-operations-api.md` specifies exact cost controls, privacy/artifact policy and operations controls. Those contracts extend the baseline endpoints below. In particular, external-authority scheduling returns an explicit pending operation until verified read-back; it must not be interpreted as an `Appointment` or trigger a confirmation merely because an HTTP request succeeded.

## Login and navigation

- `POST /auth/login {email,password}` → `{access_token,token_type:"bearer",user:{id,email,name,role,tenant_id,tenant_name}}`.
- `GET /me` → the same user object.
- `GET /clinics` → `[{id,name,slug,role,timezone,settings_version}]` for accessible memberships.
- `POST /auth/switch {tenant_id}` → a fresh login-shaped response after membership validation.
- `POST /auth/logout {all_devices:false}` revokes the current session identifier; `all_devices:true` applies the documented account-wide revocation behavior. Membership and permission checks remain current on subsequent protected requests.
- `GET /client-info` is a credential-free companion compatibility handshake. Server setup must not send an existing staff token to an unverified proposed origin.
- Development credentials: `owner@example.test` / `DemoReception2026!`; the owner can access both demo clinics. `other@example.test` / same password accesses only the second clinic. Demo accounts are never seeded outside explicit demo mode.

## Public notice and session admission

`GET /public/clinics/{slug}` returns `notice`, optional `processing_notice`, `processing_policy_version`, effective `transcript_retention_days` and `processing_notice_fingerprint`. Display both notice texts before requesting consent. `POST /public/sessions` includes `processing_consent:true` and the exact displayed `processing_notice_fingerprint`, alongside the clinic/session fields defined by the request schema.

The server checks that fingerprint under the clinic lock before admitting the call. A changed notice, policy or retention cap returns `409 PROCESSING_NOTICE_CHANGED`: refresh the notice, clear consent and require a fresh affirmative action. Never automatically retry with a newly fetched fingerprint. Missing fingerprints are refused for real public intake; explicitly synthetic demo clients may omit one, and their evidence records that no displayed notice was bound. A supplied stale fingerprint is refused even in demo mode. Current processing-purpose disablement also stops existing automated turns with `PROCESSING_DISABLED`.

## Reception

- `GET /dashboard` → `{clinic:{id,name,timezone,mode,settings_version},date,metrics:{appointments_today,confirmed_today,pending_tasks,active_calls,notifications_failed,minutes_used},appointments:Appointment[],tasks:Task[],notifications:Notification[],recent_activity:AuditEvent[]}`. Active-call values are supplemented by the voice API.
- `GET /practitioners` → `[{id,name,specialty,working_hours,active}]`.
- `GET /services` → `[{id,name,provider_ids,resource_ids,active,duration_minutes,buffer_minutes,price_toman,deposit_toman,requires_approval,description}]`. Both catalog reads accept `include_inactive=true` for owner/admin, enabling reversible deactivation.
- `GET /slots?provider_id=<id>&service_id=<id>&date=YYYY-MM-DD` → `[{slot_id,provider_id,service_id,start_at,end_at,local_date,local_time,display,timezone,available,settings_version}]`.
- `POST /holds {slot_id,session_id}` → `{id,slot_id,expires_at,status}`. Staff may omit session_id. Holds last five minutes by default.
- `GET /appointments?date=YYYY-MM-DD&status=CONFIRMED` → `Appointment[]`. Both filters optional; maximum 250 latest results.
- `POST /appointments {slot_id,patient_name,phone,idempotency_key,confirmed:true,hold_id?,session_id?,reminder_opt_in?:false,payment_terms_version?,payment_terms_accepted?:false}` → `Appointment`. An actual deposit requires the current published financial-policy version and explicit acceptance; a generic booking confirmation does not imply acceptance of undisclosed terms.
- `POST /appointments/{id}/cancel {reason?,idempotency_key,version}` → `Appointment`.
- `POST /appointments/{id}/reschedule {slot_id,idempotency_key,version}` → `Appointment`.
- `POST /appointments/{id}/approve {version}` → `Appointment` (authorized staff; only awaiting approval and paid if a deposit applies).
- `PATCH /appointments/{id}/outcome {outcome:"ATTENDED"|"NO_SHOW",version}` → `Appointment`.

`Appointment = {id,reference,provider_id,provider_name,service_id,service_name,patient_name,phone_masked,start_at,end_at,local_date,local_time,jalali_display,status,attendance,price_toman,deposit_toman,payment_status,payment_terms,payment_expires_at,notification_status,version,created_at,reminder_opt_in,disruptions}`. `payment_terms` is the safe published snapshot or null; it contains no merchant credentials. `disruptions` identifies unresolved clinic/provider disruption reviews. Phone digits are never included in list responses. States include CONFIRMED, PENDING_PAYMENT, PENDING_STAFF_APPROVAL, CANCELED, EXPIRED. Start/end are UTC ISO instants; the server supplies local and Jalali displays.

`slot_id` is a server-signed compact token bound to tenant/provider/service/start/duration/policy version. Availability is still checked at commit; a token does not reserve a slot.

## Staff work and notifications

- `GET /tasks?status=OPEN` → `[{id,reason,summary,priority,status,call_id,appointment_id,created_at,resolved_at,resolution}]`.
- `POST /tasks/{id}/resolve {resolution}` → Task.
- `GET /notifications` → `[{id,appointment_id,purpose,recipient_masked,status,attempts,provider_id,created_at,updated_at,last_error_code}]`. Status distinguishes QUEUED, SENDING, SENT, DELIVERED, FAILED, UNKNOWN.
- `GET /audit` → `[{id,action,entity_type,entity_id,actor_id,details,created_at}]` with bounded metadata, no raw patient name/phone.
- `GET /usage` → `{period,minutes,calls,bookings,events:[{id,kind,quantity,unit,cost_toman,created_at}]}`.

## Approved tenant configuration

- `GET /settings` → `{id,name,slug,timezone,mode,settings_version,address,phone,website,working_hours,holidays,faq,retention_days,lead_time_minutes,booking_horizon_days,cancellation_notice_hours,quiet_hours,monthly_minute_budget}`.
- `PUT /settings {version, ...changed_fields}` → settings. Requires owner/admin. `mode` is `after_hours`, `overflow`, `human_primary`, `supervised`, `ai_primary`, or `paused`; provider/date edits immediately increment policy version. `working_hours` keys `0`–`6` use **Monday=0**, each value an array of `["09:00","13:00"]` intervals. Holidays are local Gregorian dates. FAQ is `[{question,answer,category}]` plus the approval metadata below. Inputs are validated; contradictory/stale versions return a conflict.

## Internal service interface

`ReceptionService(db, tenant_id, actor_id="system")` uses one SQLAlchemy Session. Standalone mutations commit their own atomic transactions and leave the session usable after a conflict. `slots(provider_id,service_id,date)`, `hold(slot_id,session_id)`, `create_appointment(slot_id,patient_name,phone,idempotency_key,confirmed,hold_id=None,session_id=None,reminder_opt_in=False,force_approval=False,payment_terms_version=None,payment_terms_accepted=False)`, `cancel_appointment(appointment_id,idempotency_key,version,reason="",verified=False)`, and `reschedule_appointment(appointment_id,slot_id,idempotency_key,version,verified=False)` return dictionaries. `force_approval` is an internal supervised-policy argument and is not accepted from public booking payloads. Caller agents must pass `verified=True` only after a successful scoped identity challenge; staff routes enforce staff authorization first. Existence and tenant isolation are enforced inside the service.

The conversation engine composes these methods through `_TurnTransaction`: internal commits become flushes while a fenced call-row lock is held. The calendar mutation, encrypted conversation context, outbox, consent and idempotent turn receipt commit together. A failure before the turn receipt rolls them all back. Replays refresh current appointment status, including cancellation after an earlier response.

The service writes MessageOutbox atomically. It never transmits external SMS itself. Integration modules consume the outbox and implement voice, consent, waitlist, payments, and external media routes.

## Onboarding and policy publishing

- `POST /clinics {name,slug,address?,phone?}` creates a clinic with no open hours and grants its authenticated creator owner membership. Production clinics begin paused; the development profile uses human-primary. Only an existing owner may use this endpoint; bootstrap the first owner with the local administrator script.
- `POST /practitioners {name,specialty?,active?,working_hours?}`, `PUT /practitioners/{id}`: owner/admin only. Shifts use the clinic weekday/local-time format, with ordered nonoverlapping `HH:MM` intervals (at most eight/day). `null` inherits clinic hours; `{}` has no shifts. Omitting a field on update preserves it. Deactivation or narrowed shifts that conflict with active bookings return `FUTURE_BOOKINGS_REQUIRE_REVIEW`; existing bookings remain intact.
- `POST /services {name,description?,provider_ids,resource_ids?,duration_minutes,buffer_minutes?,price_toman?,deposit_toman?,requires_approval?,active?}`; `PUT /services/{id}` has the same body. All practitioner IDs belong to the actor's tenant. Resources are named single-capacity resources within a tenant. Changed resource allocation with future bookings requires review.
- Publishing catalog entries increments the policy version, invalidating previously offered signed slots. Appointment duration, price, deposit, and approval obligation are stored when booking is created.
- FAQ items also accept `source`, `keywords`, `effective_at`, and `expires_at`. Owner/admin publishing sets `approved_by` to the authenticated editor; callers cannot forge the approving identity. If dates are omitted, content is effective immediately and expires after 30 days. Expired or unapproved facts are not spoken by the agent.

## Operational endpoints

- `GET /operations/integrations`, `/operations/privacy`, `/operations/building` provide configuration status, consent summaries, and membership-scoped aggregate counts. `configured_unverified` means required configuration and approval flags exist; it is not a live carrier/vendor test. Configured speech/LiveKit/AudioSocket retain this state in demo mode because media can operate locally. Only actual demo-disabled SMS/payment transmissions use `demo_disabled`. AudioSocket checks `MEDIA_API_TOKEN`; LiveKit also requires `LIVEKIT_APPROVED`.
- `POST /operations/notifications/{id}/retry` only requeues known FAILED sends below the attempt cap; UNKNOWN, SENDING, SENT, DELIVERED and SIMULATED are never requeued blindly.
- `POST /operations/privacy/export {phone}` and `/operations/privacy/delete {phone,confirm:true}` require owner/admin. Active future appointments are retained for controlled review; conversations, challenges and outreach eligibility are erased/revoked. Past appointment identities are anonymized without silently canceling a future visit.
- `POST /operations/waitlist {provider_id,service_id,patient_name,phone,date_from,date_to,time_from?,time_to?,travel_minutes?,consent:true}` and `GET /operations/waitlist` manage eligible candidates. `POST /operations/waitlist/offer {slot_id}` reserves the slot and chooses the oldest eligible entry. Quiet hours, travel lead time, a daily contact cap, and three lifetime offers apply.
- `GET /operations/waitlist/offers` returns resumable offer records without acceptance tokens. `POST /operations/waitlist/offers/{id}/accept {confirmed:true}` permits authorized staff to record the patient's explicit acceptance. `POST /public/waitlist/{id}/accept {token,confirmed:true}` requires the opaque offer capability. Every result comes from the same authoritative booking service.
- `POST /operations/payments {appointment_id}`, `GET /operations/payments`, and demo-only `POST /operations/payments/{id}/simulate` manage deposit intents. Actual callbacks always perform server-to-server gateway verification. Late payments create refund review and never resurrect expired slots.
- `POST /operations/payments/{id}/refunds {amount_toman,reason,idempotency_key}` reserves a bounded partial/full refund allocation and creates an execution task. `GET /operations/refunds` lists them. `POST /operations/refunds/{id}/record {provider_reference,confirmed:true}` records verified external execution by authorized staff; it does not send a transfer itself.
- `POST /operations/billing/adjustments {period,amount_toman,reason,idempotency_key}`, `POST /operations/billing/invoices {period,base_fee_toman,included_minutes,per_minute_toman,pricing_approved:true}`, and `GET /operations/billing/invoices` produce immutable closed-period draft invoice snapshots. They do not charge customers. Tax remains subject to the actual contract and operator configuration.
- `POST /webhooks/notifications` accepts the documented partner HMAC scheme (`X-Timestamp`, `X-Signature`) and `{event_id,message_id,provider_id,status}`. Vendor-specific callbacks must be translated/verified by their adapter; Kavenegar polling is also implemented by the provider client. This generic webhook is not represented as Kavenegar's native signature format.

`run_jobs(db)` performs bounded local expiry, reminders and retention. `await run_once(session_factory=SessionLocal)` adds outbox dispatch. Default demo processing returns `SIMULATED`, never SENT/DELIVERED, and does not call external providers. A crashed dispatch lease becomes UNKNOWN and creates reconciliation work rather than risking duplicate texts.

## Caller automation and correction policy

| Mode | Enforced behavior |
|---|---|
| `ai_primary` | Approved FAQ and verified scheduling flows run automatically. |
| `human_primary` | The session immediately creates a scoped staff task; responses truthfully report queued status until actual human participation is verified. |
| `after_hours` | AI runs only outside the clinic's published local working intervals or on a listed holiday. During clinic hours, the session takes the human-primary path. |
| `overflow` | AI requires `busy` or `no_answer` routing evidence supplied by the authenticated PBX gateway after a real staffed dial attempt. A public browser cannot assert this evidence and takes the human-primary path. |
| `supervised` | New appointments preserve an approval obligation, including after deposit settlement. Verified cancellation/reschedule requests create staff review tasks and preserve the original appointment. |
| `paused` | New automated sessions are refused and existing sessions stop automatic turns and speech. Staff calendar work remains available. |

Policy and published pronunciation/profile version are pinned at session creation; a live pause is an immediate override. Demo clinics explicitly use `ai_primary`. AI never resumes automatically from `HUMAN_CONNECTED`, and repeating a handoff request cannot downgrade a connected human to queued.

Before final confirmation, callers can request `اصلاح اطلاعات` or an explicit correction to name, contact, service, doctor, or date. Contact correction invalidates prior verification challenges/proof and suppresses unsent old OTPs. Doctor/service/date changes release incompatible holds and discard old signed offers; only providers and services in the same tenant are offered. Corrected details receive a fresh explicit confirmation. Committed-patient changes go to the staff workflow instead of creating an unintended second booking.

All admission channels call `new_session(db,tenant,channel="browser_text",routing_reason=None,commit=True)`. A tenant write lock serializes capacity and budget checks. Completed canonical call-duration usage plus active maximum-duration reservations share the monthly minute budget; STT processing seconds are excluded. Calls reserve at most 30 minutes and never extend beyond the UTC budget month boundary. End/expiry metering releases unused reservation capacity. `commit=False` lets an authenticated integration atomically add its own registration/thread record.

## Media admission and worker authority

- `POST /internal/media/register {call_uuid,did,processing_notice_played:true,routing_reason?:"incoming"|"busy"|"no_answer"|"after_hours"}` requires the private media token and an allowlisted DID mapping. Returns `{call_uuid,session_id,registered,route:"ai"|"human"}`. The PBX may enter AudioSocket only when `registered` is true; otherwise it follows its staffed fallback. Duplicate UUIDs cannot create a second call registration.
- `POST /internal/media/claim {call_uuid}` consumes an unexpired one-use PBX registration.
- `POST /internal/media/rooms {worker_id,active_sessions?:[],capacity?:8}` returns `{rooms,renewed_sessions,revoked_sessions,lease_seconds:30,capacity}`. The server counts all still-leased rooms and caps total ownership; each lease generation issues a distinct worker-only session credential. Every session request validates the worker ID, generation and live lease. A former worker cannot mutate or end the successor's call.
- The worker renews every five seconds and stops on revocation or a missed 30-second renewal deadline. It keeps at most one caller audio track and one queued subsequent utterance, retaining each utterance's playback generation. Interruption silences stale playback while allowing an already-submitted transaction to settle and report its authoritative result.
- Staff takeover tokens require a live tenant membership. `CONNECTED` is recorded only from a verified LiveKit participation webhook for a currently authorized, assigned staff member; repeated events have no additional effect. PBX fallthrough is a configured carrier/PBX route and is not represented as a verified LiveKit connection.

Audio uploads are request-hash bound: replaying a completed turn with an identical request ID and payload reuses its result without repeating STT; different payloads reject with `TURN_REPLAY_MISMATCH`. Local decoding permits only pipe input and approved audio containers, rejects over-60-second or unsupported audio, and refuses overload before reading an upload. The transport WAV decoder also rejects truncated PCM. No model weights are downloaded during a call and no raw audio is persisted.

Only the exact static greeting may use the bounded tenant/policy-scoped TTS cache. Cache hits record `tts_cache_hit` and do not add provider `tts_characters`; dynamic booking/status readbacks never use a cache scope. The API reads booking state again after synthesis and returns `STALE_SPEECH` instead of stale confirmation audio if the booking changed during provider latency.

## Production clinic UAT

Owner/admin routes record a named attestation for a specific clinic configuration and intended automation mode. They validate completeness, identity, expiry and configuration binding. They do not run the referenced checks automatically or certify live carrier, clinical, legal or vendor approval.

`GET /operations/uat?target_mode=after_hours` returns:

```json
{
  "current_mode": "paused",
  "target_mode": "after_hours",
  "configuration_fingerprint": "<64 lowercase hex characters>",
  "approved": false,
  "production_enforced": true,
  "required_checks": ["booking", "cancellation", "conflict", "provider_failure", "handoff"],
  "verification_kind": "clinic_synthetic_checks_attested",
  "attestation": null,
  "scope": "Named operator attestation; separate external approvals remain necessary."
}
```

`target_mode` accepts `after_hours`, `overflow`, `human_primary`, `supervised`, and `ai_primary`. `POST /operations/uat/approve` accepts:

```json
{
  "target_mode": "after_hours",
  "configuration_fingerprint": "<the exact reviewed fingerprint>",
  "checks": {"booking": true, "cancellation": true, "conflict": true, "provider_failure": true, "handoff": true},
  "evidence_refs": {
    "booking": "<specific redacted evidence reference>",
    "cancellation": "<specific redacted evidence reference>",
    "conflict": "<specific redacted evidence reference>",
    "provider_failure": "<specific redacted evidence reference>",
    "handoff": "<specific redacted evidence reference>"
  },
  "confirmed": true
}
```

All five checks must be true and all five evidence references nonempty (3–300 characters). The response has the same shape, with `attestation:{id,created_at,valid_until,reviewer_user_id,reviewer_name,checks,evidence_refs}`. It expires after 30 days; losing active owner/admin membership invalidates the reviewer authority. Changes to bound policy/catalog/payment publication invalidate the fingerprint. The target mode is part of the fingerprint. Evidence references must not contain patient data.

In production, pause first, edit policy/catalog/payment terms, perform and record the checks, then activate that exact mode through `PUT /settings`. Pausing is always allowed. Active production catalog/financial-policy edits return `PAUSE_BEFORE_CATALOG_CHANGE`; activation or AI admission/continuation without matching evidence returns `CLINIC_UAT_REQUIRED`. This is a software enforcement gate, with the truth of the operator's test attestation remaining an operational responsibility.

## Financial policy and tenant merchant binding

`GET /operations/payment-policy` is available to staff and returns:

```text
{version,enabled,currency:"TOMAN",hold_minutes,deposit_terms,cancellation_terms,
 refund_terms,merchant_alias,merchant_ready,merchant_configuration_status,
 demonstration,published_at,published_by}
```

`PUT /operations/payment-policy` requires owner/admin and `{version,enabled,hold_minutes,deposit_terms,cancellation_terms,refund_terms,confirmed:true}`. The hold limit is 5–1440 minutes. Each enabled terms field must contain at least 10 nonblank characters and at most 2000 characters. Publication increments the version, records its author and exact terms, and invalidates production UAT. A readiness value of `CONFIGURED_NOT_LIVE_VERIFIED` refers to checked configuration only. It does not establish a working bank account, valid legal terms or a completed live payment.

`GET /public/clinics/{slug}/payment-policy` returns only `{version,enabled,synthetic,currency,hold_minutes,deposit_terms,cancellation_terms,refund_terms,published_at}`. Merchant identities and aliases are omitted. A demo with no published policy exposes a clearly synthetic version-zero policy; an actual deployment has no implicit deposit policy. An explicitly disabled policy prevents deposit bookings.

The operator configures the merchant registry outside the staff/browser API:

```text
PAYMENT_PROVIDER_APPROVED=true
PAYMENT_TENANT_MERCHANTS_JSON={"<tenant-id>":"<stable-merchant-alias>"}
PAYMENT_MERCHANTS_JSON={"<stable-merchant-alias>":{"merchant_id":"<private-value>","sandbox":true,"approved":true}}
```

Every real tenant must have an explicit approved mapping. The application never substitutes a global merchant for an unconfigured tenant. Publication pins the merchant alias, a hash of provider/merchant identity, and sandbox mode. The appointment records the accepted policy and amount; its payment intent copies this immutable snapshot before creating the hosted link. Integer Toman values convert to gateway IRR by exactly ten. The payment hold cannot extend beyond the appointment start.

Keep old aliases and identities unchanged while their intents await verification. A tenant may map to a new alias for future publication; its old intents still verify through the original alias. Removing an old alias or changing its identity/sandbox mode fails closed before gateway verification. Changing the identity under the current published alias also requires republishing the financial policy. No API response implies that payment has settled until the gateway server verification succeeds and the authoritative payment/calendar transaction commits. A late settlement becomes refund review and cannot resurrect capacity.

Session start, turn and reconnect responses include `versions` and `policy_version`. Version metadata contains application/FSM/locale/calendar/adapter identifiers and configured ASR/TTS identifiers; absent historical labels remain `not_recorded`. Turns carry `bookings` for the current booking cycle. `payment_terms` is present only during `CONFIRM`, including repeats and reconnect; it is null in other states. The conversational readback presents deposit amount, hold time and published terms before accepting a final yes. A changed amount or policy requires a fresh confirmation and the stale yes creates no appointment. Reconnect returns current booking(s) and offers only when the state remains `OFFER`.

## Policy history, case ownership and corrections

- `GET /operations/policies` returns `{current_version,revisions,scope}` with immutable reception-policy snapshots. `POST /operations/policies/{version}/restore {expected_version,reason,confirmed:true}` appends a new version through normal settings validation; it never deletes intervening history or rolls back calendar transactions/catalog prices.
- `GET /operations/tasks?status=...` returns extended tasks with `assignee_id`, `assignee_name`, `assigned_to`, `version`, `callback_at`, and authorized `last_note`. The active statuses are `OPEN`, `IN_PROGRESS`, `PENDING`, and `CALLBACK`; terminal cases are `RESOLVED`. Dashboard/building open counts include every active status, not only the first page of cases.
- `GET /operations/assignees` returns active eligible members as `{user_id,name,role}` without credential administration fields. The separate owner-only `/operations/team` endpoint manages membership/credentials.
- `POST /operations/tasks/{id}/actions {action,version,idempotency_key,reason?,assignee_id?,callback_at?}` accepts `claim`, `reassign`, `pending`, `callback`, `resolve`, `reopen`, `reject`, `redirect`. The server checks ownership, active membership, action-specific authority and version. Callback time must be timezone-aware, future, and within 90 days. Competing claims have one owner; retries of the same operation reuse its receipt. The legacy `/tasks/{id}/resolve` route enforces the same ownership policy. Free-text reasons are encrypted; plain task resolution stores a categorical summary.
- `GET /operations/appointments/{id}` returns one scoped Appointment, independent of the latest-250 list limit.
- `PATCH /operations/appointments/{id}/details {version,idempotency_key,reason,confirmed:true,patient_name?,phone?,slot_id?,accept_price_change?:false}` performs authorized correction atomically. A different service/provider/time uses a current signed `slot_id`. Resource conflicts preserve the original appointment and details. A changed price requires explicit acceptance; deposit changes require a separate reviewed rebooking/payment workflow. Pending-payment slot corrections are rejected. Changing a phone stops old queued notices and resets reminder opt-in; prior/current identities remain linked for authorized privacy requests. Audit before/after values and staff reasons are encrypted.

## Clinic disruptions and daily review

`POST /operations/disruptions/preview` and `POST /operations/disruptions` share:

```text
{kind:"LATE_ARRIVAL"|"PROVIDER_DELAY"|"EMERGENCY_CLOSURE",
 provider_id?,appointment_id?,start_at?,end_at?,delay_minutes?:0,
 reason,expected_policy_version,idempotency_key,confirmed?:false}
```

Preview makes no calendar mutation. Commit requires explicit confirmation. Late arrival identifies an existing confirmed appointment and nonzero delay; it records review without extending occupancy. Provider delay/closure identifies a timezone-aware interval and optional scoped provider; absence of a provider means clinic-wide closure. Those actions require owner/admin. New availability is blocked, incompatible unused holds released, and existing appointments receive explicit unresolved impacts and staff work. Existing appointments are not silently moved or canceled. Minimal notices do not invent replacement times.

`GET /operations/disruptions` lists scoped impacts. `POST /operations/disruptions/{id}/resolve {version,reason,confirmed:true}` releases the blocking interval but leaves each patient's outcome unresolved. `POST /operations/disruptions/impacts/{id}/decision {version,decision:"KEEP_ORIGINAL"|"CANCEL",reason,confirmed:true,idempotency_key}` records an explicit patient outcome. Keeping the original time requires the block to be resolved (except the late-arrival review path). Relocation uses the correction endpoint. Cancellation uses the authoritative calendar and opens necessary financial review; it does not issue a money transfer. Patient RSVP is refused while an unresolved schedule disruption requires staff coordination.

`GET /operations/digest?day=YYYY-MM-DD` requires owner/admin and returns `{day,timezone,generated_at,metrics,usage,definitions}`. Counts distinguish currently verified bookings created that local day, scheduled attendance/no-show/unknown, cancellations, fulfilled waitlist visits, all unresolved current cases, delivery states and actual recorded call duration/cost. Open cases are current backlog, not a reconstruction of a past day's queue. STT processing time is excluded from billable call minutes. This endpoint itself sends nothing; approved scheduled digest destination/dispatch is a separate partner operation.

## Outreach policy, consent withdrawal and patient response

`POST /operations/consents/revoke {phone,purposes:["reminder","waitlist","followup"]}` is a distinct authenticated staff action for an actual patient request. It creates purpose-specific suppression tombstones, revokes matching grants, suppresses eligible unsent messages and releases applicable waitlist offers. It preserves the appointment. Counts disclose already in-flight messages that cannot truthfully be recalled. Export/delete remains a separate owner/admin workflow. Tombstone suppression overrides purpose grants and channel-specific permissions; an explicit SMS channel denial also blocks enrollment, scheduling and dispatch.

`GET /operations/outreach-policy` returns `{version,reminder_offsets_minutes,waitlist_auto_offer,waitlist_offer_limit_per_run,followup_enabled,followup_offsets_days,clinician_approved_version,clinician_user_id,clinician_approved_at,followup_effective,followup_template,outbound_voice_enabled:false}`. Staff can inspect it. Owner/admin `PUT /operations/outreach-policy` accepts the current version and the editable policy fields. Up to six reminder offsets are allowed, 5–10080 minutes before the visit; followup day offsets are 1–365. Workers generate the latest due reminder once and do not burst-send all previously missed offsets. Changed offsets/revisions are checked again at dispatch.

Published followup cadence requires a separately authorized clinician: `POST /operations/outreach-policy/approve {version,confirmed:true}`. Owner status alone does not satisfy this route. Publishing another version invalidates approval. `POST /operations/followups {appointment_id,policy_version,confirmed_consent:true}` requires an attended visit, current published clinician approval, eligible channel/purpose consent and staff authority; `GET /operations/followups` lists enrollment metadata. The effective clinician membership, policy, consent and suppression are checked again at dispatch. The approved template is generic administrative followup; it contains no individualized aftercare or clinical advice.

`POST /operations/appointments/{id}/response-link {version}` returns `{response_id,public_path,expires_at,status}` to staff. `public_path` has form `/respond/<id>#<opaque-token>`; the fragment avoids placing the capability in server access-log query strings. The server retains a token hash and encrypted delivery copy. It expires at the appointment start and is bound to the appointment version.

Public `POST /public/appointments/responses/{id}/view {token}` returns `{response_id,clinic,reference,display,booking_status,response_status,expires_at,action}`. The three display fields are strings; no patient contact/name is exposed. `POST /public/appointments/responses/{id} {token,action:"CONFIRM"|"DECLINE"}` returns the same view. Confirmation records `CONFIRMED_ATTENDANCE_INTENT`, never actual attendance. An eligible decline cancels the authoritative appointment and records `DECLINED_CANCELED`; a decline inside the cancellation cutoff preserves the booking and records `DECLINE_REVIEW_REQUIRED` with staff work. Same-action replay is idempotent, a conflicting action returns a conflict, and stale/expired/erased capabilities fail closed.

Waitlist auto-offer is off by default. When explicitly enabled, bounded worker claims consume real durable capacity-release events from cancellation, movement or expiry. They recheck the current calendar and consent, acquire an actual expiring hold, and then enqueue the offer. An intervening booking defeats the offer. Quiet hours, travel time, one contact per 24 hours, three lifetime offers and per-run policy caps apply. `POST /operations/waitlist/offers/{id}/reject {confirmed:true,reason:"declined"|"unreachable"|"timing"|"no_longer_needed"}` audits the rejection, revokes the unused capability and releases capacity. Expiry is audited and stale offer messages are suppressed. Selective outbound voice remains disabled pending a real approved carrier contract; these APIs do not dial anyone.

Deposit-bearing waitlist offers follow the same explicit financial acceptance as ordinary booking. Offer creation and saved-offer list responses include `{deposit_toman,price_toman,payment_terms}`. `GET /operations/waitlist/offers/{id}/terms` requires scoped staff authority and returns `{id,status,expires_at,display,deposit_toman,price_toman,payment_terms}`. Capability-protected public `POST /public/waitlist/{id}/view {token}` returns the same minimal view without patient name/contact or merchant identity. Views refuse expired or withdrawn offers. Both existing acceptance endpoints accept `payment_terms_version` and `payment_terms_accepted` in addition to their confirmation/capability fields. Actual deposits require the current version and explicit acceptance; a stale version returns `PAYMENT_TERMS_CONFIRMATION_REQUIRED` before booking. The UI must refresh the terms, clear acceptance and ask again. A successfully accepted deposit offer creates `PENDING_PAYMENT`, with the exact accepted terms/merchant snapshot; acceptance itself neither creates a hosted charge nor verifies settlement. A configured clinic can use the staff flow after contacting the patient; a standalone public waitlist page/SMS link is not advertised by this delivery.

## Refund review and disputes

Refund amounts reserve against the settled principal minus known principal adjustments. Concurrent requests cannot over-reserve it. Same-key replay must match payment, amount and reason. Staff request text is encrypted in the scoped audit; the authorized refund list decrypts it without changing the API shape. Legacy ledgers with plaintext reasons remain readable and require a controlled migration/retention decision rather than a false claim that old rows were rewritten.

`POST /operations/refunds/{id}/review {action:"REFUSE"|"RECONCILE_PENDING"|"RECONCILE_FAILED",reason,provider_reference?,confirmed:true,idempotency_key}` requires owner/admin. Refusal of an unexecuted request releases its reservation once. An uncertain transfer remains reserved in `RECONCILING`; it cannot be dismissed as refused. Evidence of failure releases that reservation once. `POST /operations/refunds/{id}/record {provider_reference,confirmed:true}` can complete a requested/reconciling refund only with recorded external execution evidence. Reused provider references and conflicting completed evidence are rejected. These endpoints record authorized review/evidence; no gateway refund API or transfer is fabricated.

`GET /operations/disputes`, `POST /operations/payments/{id}/disputes {amount_toman,provider_case_reference,reason,confirmed:true,idempotency_key}`, and `PATCH /operations/disputes/{id} {version,status:"UNDER_REVIEW"|"WON"|"LOST"|"CLOSED",reason,confirmed:true,idempotency_key}` track provider cases. A recorded loss appends exactly one negative principal adjustment. It does not rewrite the original settlement, and subsequent refund availability accounts for it. State/version/idempotency and tenant scope are validated; live provider dispute handling remains an external staff obligation.
