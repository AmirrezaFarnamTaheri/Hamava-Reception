# Operations, finance, privacy and research extension contract

This is the v0.2 additive contract. `scripts/migrate.py` applies schema `0002`; application startup, backup verification and model registration use the same schema registry. Existing endpoints remain, with explicit permissions replacing broad role aliases. This document describes software behavior. Operator-entered contract, consent and reconciliation references are attestations, not independent proof that a vendor or person approved anything.

## 1. Financial units and dispatch boundary

The canonical ledger stores integer **micro-Toman** (1,000,000 units per Toman). Quantities, provider prices, FX and billing quanta use exact decimal strings. One Rial is exactly 0.1 Toman. Rate publication requires a source reference/hash, effective interval and approver; there are no built-in real supplier prices.

Browsers must display `charged_toman`, `reserved_toman`, `exposure_toman`, ledger `cost_toman_exact`, and statement `billed_toman_exact` / `discrepancy_toman_exact`. These are decimal strings. Compatibility integer micro-Toman fields may exceed JavaScript's exact integer range.

The provider sequence is:

1. Check the tenant's capability and processor/purpose/region policy.
2. Reserve the maximum priced quantity under a tenant database lock.
3. Mark the operation started and commit before external I/O.
4. Record the observed quantity against the pinned rate, or keep the maximum liability as `UNKNOWN`.
5. Use trusted provider evidence or an audited operator reconciliation to close uncertainty.

Replaying a started operation does not authorize a second dispatch. Retries need their own bounded attempt identity. The policy is rechecked at first dispatch; a newly reduced or disabled limit can stop an unused reservation. Only unstarted reservations expire automatically. Unknown started liabilities continue to count across accounting-month boundaries.

Disabling a clinic blocks new reservations and dispatch, but does not discard a response for work already authorized. Settlement locks the existing reservation's clinic and record even when that clinic is now inactive; an authenticated cost returned with the same response may adjust its existing charge. These continuation paths do not authorize more provider work. Health updates skip inactive clinics, and queued messages remain suppressed. The regression deactivates a clinic inside a mocked SMS request and verifies that its accepted receipt and exact returned charge persist without a second send.

Production provider dispatch without an enabled monetary policy and current rate fails closed. Development may record `UNPRICED`; this never means that the supplier is free. Rate rounding includes the declared minimum quantity and billing quantum. Actual overruns are recorded without clamping the ledger and generate review work. Budgeting cannot retrospectively undo supplier charges already incurred.

### Finance endpoints

All paths below begin `/api/v1/operations`.

| Method and path | Permission | Contract |
|---|---|---|
| `GET /costs` | `billing:read` | Current policy, rates, UTC-month charges/reservations, unknown count and soft-limit state. |
| `PUT /costs/policy` | `billing:write` | `enabled`, integer `monthly_cap_toman`, `call_cap_toman`, `operation_cap_toman`, `soft_percent`, `provider_caps_toman`. Requires operation ≤ call ≤ monthly. Publishes a new immutable version. |
| `POST /costs/rates` | `billing:write` | `provider`, `meter`, `unit`, `currency` (`TOMAN`, `IRR`, `USD`), decimal strings `price_per_unit`, `fx_toman_per_currency`, `quantum`, `minimum_quantity`, `evidence_reference`, `evidence_sha256`, timezone-aware `effective_at`, `expires_at`. |
| `GET /costs/ledger?limit=100` | `billing:read` | Up to 500 append-only usage/adjustment records with source reference, unit, rate version and exact displayed cost. |
| `GET /costs/reservations` | `billing:read` | Up to 200 `STARTED`/`UNKNOWN` attempts awaiting outcome evidence. |
| `POST /costs/reservations/{id}/reconcile` | `billing:write` | `outcome` (`confirmed` or `no_charge`), decimal-string `quantity`, `source_reference`, `evidence_sha256`, `provider_result_verified:true`. No-charge requires zero quantity. Reports `operator_attested_provider_result`. |
| `POST /costs/statements` | `billing:write` | `provider`, statement `reference`, UTC `period` (`YYYY-MM`), `evidence_sha256`, 1–500 lines. Each line has reference, optional matching charge_id, meter, quantity, unit, currency, billed_amount and FX. |
| `GET /costs/statements` | `billing:read` | Latest 40 imported documents and their match/discrepancy state. Documents remain operator-submitted evidence. |
| `POST /costs/statement-lines/{id}/review` | `billing:write` | `action`: `DISPUTE`, `ACCEPT_VENDOR`, `RESOLVE_NO_CHANGE`; opaque `evidence_reference`; encrypted free-text `explanation`. Accepting a discrepancy appends a linked adjustment. |
| `POST /costs/transport-events` | `integration:write` | `source`, unique event_key, attempt_key, optional call_id, stage, occurred_at, evidence_reference. Authenticated adapter/operator ingress, not a claim of carrier coverage. |
| `GET /costs/outcomes?period=YYYY-MM` | `reports:read` | Distinct reported transport stages and separately created-booking/kept counts. Missing transport inventory returns null, not a manufactured answer rate. |
| `POST /costs/attribution` | `billing:write` | appointment_id, opaque episode_reference, channel, classification, related appointment where applicable, evidence_reference. |
| `GET /costs/attribution` | `reports:read` | Distinct observed kept new-demand episodes; waitlist fills cannot be classified as new demand. Causal incremental count remains null. |
| `POST /staff-time/start` | `task:write` | category `RECEPTION/HANDOFF/SUPERVISION/REWORK`, optional task_id, hourly_rate_toman, idempotency_key. One active timer per user across clinics. |
| `POST /staff-time/{id}/stop` | `task:write` | Stops the caller's own timer; records elapsed time at the pinned declared rate. Sessions over 16 hours require review rather than automatic valuation. |
| `POST /staff-time/{id}/review` | `billing:write` | Closes only an unfinished timer older than 16 hours. Requires reviewed_seconds (0–57600), evidence_reference, evidence_sha256 and observation_verified. Preserves observed elapsed duration in audit evidence and values only the reviewed work interval. |
| `POST /staff-time/observations` | `billing:write` | period, released_minutes, avoidable_minutes, reassigned_minutes, hourly_rate_toman, evidence_reference, evidence_sha256. Avoidable + reassigned cannot exceed released. |
| `GET /staff-time` | `reports:read` | Observed work time, separately attested released/avoidable/reassigned time, and supervision/rework deducted from avoidable value. Includes review_required_sessions for abandoned timers. Coverage is explicitly incomplete without a real study. |

Provider keys used by built-in paths are `speech_primary`, `speech_fallback`, `calendar_primary`, `sms_kavenegar`, `telephony_primary`, and `digest_gateway`. Meters include `stt_audio_seconds`, `tts_characters`, `calendar_requests`, `sms_segments`, `sms_otp_lookup`, `sms_status_request`, `outbound_call_seconds`, `telephony_seconds`, and `digest_delivery`. The call-duration policy is also enforced by core/media admission. Only rates and integrations actually configured and approved by the operator may be enabled.

Automated SIP/WebRTC admission reserves the remaining bounded session duration under `telephony_primary` / `telephony_seconds` before granting media access. The configured processor region is checked separately from its price. Disconnect, expiry and human takeover record measured logical elapsed time, including silence, but leave the charge liability `UNKNOWN` until provider or reviewed operator evidence settles it. A logical timer does not prove a carrier's final bill. This admission boundary covers automated media; upstream ringing, PBX routing, rejected or human-only calls, and provider-account toll limits require actual carrier controls and independently reconciled events.

### Existing finance access

`GET /operations/payments/appointments?status=PENDING_PAYMENT` accepts `billing:read` and returns only `{id,reference,deposit_toman,status}`. Finance users do not gain patient names, services or phones through this lookup. Payment list rows include `appointment_reference`. Creating a link accepts `billing:write` or `appointment:write`; it still validates the existing tenant booking and accepted published terms. Refund actions and invoice/adjustment writes require `billing:write`; reads require `billing:read`. Payment-policy read accepts `policy:read` or `billing:read`; publication requires `billing:write`.

New adjustment reasons are encrypted audit evidence; invoice snapshots contain categorical adjustment labels. Migration `0002` applies the idempotent legacy-note conversion in its transaction. `scripts/migrate_privacy_notes.py` can separately preview the conversion, with `--apply` for an authorized repair after backup. It preserves financial amounts and record identifiers, and malformed snapshots fail before mutation for manual review. Retained older database backups still need their documented expiry/recovery procedure.

## 2. Independent privacy purposes

The prefix is `/api/v1/operations/privacy-controls`.

| Path | Permission | Contract |
|---|---|---|
| `GET /purposes` | `privacy:manage` | Ten independent purpose states, each disabled until published. |
| `PUT /purposes` | `privacy:manage` | purpose, enabled, notice, retention_days (0–365), backup_expiry_days, consent_valid_days, evidence_reference. Publishes a version. |
| `POST /permissions` | `privacy:manage` | phone, purpose, granted, integer policy_version, evidence_reference, evidence_sha256, method, subject_request_confirmed. Evidence is a staff attestation of an actual independent choice. |
| `GET /processors` | `integration:read` | Latest approval per provider, region, purpose, retention, fallback, contract hash and expiry. |
| `PUT /processors` | `privacy:manage` + `integration:write` | provider_key, enabled, purposes, regions, origin_region, retention_days, fallback_eligible, contract_reference, contract_sha256, expires_at. |
| `POST /artifacts` | `privacy:manage` | phone, specific purpose, kind, payload, idempotency_key. Requires current independent grant and nonzero retention. |
| `GET /artifacts` | `privacy:manage` | Metadata only, latest 200. |
| `GET /artifacts/{id}/content` | `privacy:manage` | Audited content access only while active, unexpired and permission-current. |
| `POST /artifacts/{id}/hold` | `privacy:manage` | evidence_reference and hold_until within one year. A hold prevents deletion but does not restore withdrawn access permission. |
| `GET /erasures` | `privacy:manage` | Local erasure evidence and pending backup-delete deadlines. |
| `POST /erasures/{id}/backup-evidence` | `privacy:manage` | evidence_reference and deletion_verified. Records an operator attestation; elapsed time alone never marks backup erasure verified. |
| `PUT /redaction` | `privacy:manage` | Reviewed names, health_terms, addresses. Stored encrypted. |
| `POST /redaction/preview` | `privacy:manage` | text → redacted preview; no input text is persisted. Clearly marks limited pattern/governed-term coverage. |
| `PUT /contact-preferences` | `appointment:write` | phone, shared_phone, name_allowed, voicemail_allowed, clinic_name_allowed, evidence_reference. Shared/unspecified phones receive neutral reception wording. |

Purposes are `processing`, `recording`, `qa`, `marketing`, `training`, `cross_border`, `memory`, `reminder`, `waitlist`, `followup`. Processing consent does not grant the others. The caller's current processing notice version and expiry are pinned by core session creation. A newer notice requires its own current evidence. Recording, QA and training remain independently disabled by default.

Public clinic responses include `processing_notice_fingerprint`, alongside the displayed notice, policy version and effective transcript retention. Non-demo `POST /api/v1/public/sessions` requires `processing_consent:true` and that exact displayed fingerprint. Admission rechecks it under the clinic transaction fence; missing or stale fingerprints reject before a session is created. Existing text/media AI turns also reject a disabled processing purpose. Demo omission is explicitly recorded as unbound compatibility; a supplied stale fingerprint still rejects. This browser notice binding does not independently prove that a telephony caller heard the required disclosure.

A processor approval does not prove a legal contract. It supplies enforceable region/purpose/expiry/fallback gates around an operator's reviewed evidence. Cross-border use requires the independently recorded subject permission. Unapproved fallback fails closed. The built-in development escape is explicitly labelled `unapproved_development`; production has none.

Artifacts are encrypted at rest. Supported retained kinds map exactly: transcript/subject_export→processing, qa_sample→qa, research_export→training, audio→recording. Audio retention accepts only explicitly authorized complete mono 16-bit PCM WAV, at most 60 seconds, supplied as base64. The live speech default still does not store raw audio automatically.

Withdrawal blocks new use and expires matching optional artifacts. Processing withdrawal ends matching active calls and releases their temporary holds. Automatic expiry continues for disabled clinics, and documented holds do not consume the deletion batch slots of unrelated records. Subject erasure also suppresses queued voice jobs and removes optional extension content. Unfinished external calendar writes, including SENDING and FAILED_REVIEW, retain necessary encrypted reconciliation evidence and create a privacy-review task; the application does not silently lose or cancel an unknown booking outcome.

Administrative call transcripts use the shortest of the tenant retention limit, the published processing-purpose limit when one exists, and the limit pinned when the call began. The public processing notice and session snapshot use that same helper. A later longer policy cannot extend an older call's pin; a later shorter policy applies at cleanup. Missing purpose policy preserves the tenant cap, and malformed explicit limits fail conservatively to zero. Expiry applies to ended calls and removes encrypted conversation context, voice turns, verification challenges and media registrations. It retires the access token and subject lookup while retaining structured business, financial and audit evidence. Local erasure creates a content hash and a separate `PENDING_EXPIRY` backup deadline; cleanup never treats that deadline as proof of backup deletion.

For a committed external calendar write, subject erasure removes direct patient contact fields and optional payment links while retaining the minimal structured appointment identity/status/time needed for truthful inventory and later cancellation. In-flight or uncertain writes retain encrypted reconciliation evidence for authorized review. Financial/audit obligations and those unresolved writes are distinct from optional recording, QA, marketing and training permissions.

Redaction matches defined identifier patterns plus governed terms. It is not universal name/health/address recognition. Trace/log code uses a closed metadata allowlist and withholds unclassified free text, rather than treating pattern matching as proof of anonymity.

## 3. Observability and actual on-call delivery

`GET /operations/traces/{call_id}` requires `audit:read`. It reconstructs persisted call/provider/turn/booking/notification events from database state, including across process restarts. Fields are opaque references, fixed event/status codes, bounded measurements and version identifiers; no transcripts or audio. Coverage is explicitly limited to instrumented events.

Cost reservation correlation requires a canonical UUID that resolves to the same clinic and, when supplied, the same call and provider. That known database identifier is validated structurally instead of passing through a free-text phone-number heuristic; coincidental digit runs in generated UUIDs therefore do not block valid provider operations. Other trace values retain the closed metadata and sensitive-text checks.

SMS send/status and payment request/verification record tenant-scoped provider health only after known adapter I/O. Successful receipt of a delivery status means the status API responded; the message keeps its actual `SENT`, `DELIVERED` or `FAILED` state. Generic supplier rejections, malformed responses and uncertain transport failures degrade readiness. Local configuration, consent, budget, authentication and circuit-breaker rejection do not create supplier evidence; neither do demo sends, simulated payment settlement or sandbox merchant results. A browser payment callback alone never establishes provider health or payment settlement. Health contains fixed codes and bounded elapsed time, not patient content or supplier response bodies, and does not establish carrier or clinical acceptance.

`GET /operations/oncall/members` returns `{user_id,name,role}` for eligible active clinic staff with `health:read`. `GET /operations/oncall` returns its policy or null. `PUT /operations/oncall` requires `integration:write`, accepts enabled, ordered user_ids, escalation_minutes, spike_window_minutes, spike_cap_toman and provider_failure_threshold.

`GET /operations/alerts` requires `health:read`. Alert generation uses actual exact-ledger monetary exposure, actual observed spend in a recent window, recorded provider failures, positive safety audit evidence, and uncertain notifications. It also escalates due outbox work older than 180 seconds, active staff work older than 900 seconds (excluding alert tasks themselves), and at least five failed deliveries in 24 hours. The response exposes those queue_thresholds; cost/provider thresholds are published in the on-call policy. Future deferred messages do not count as overdue. Positive safety events include the same false-confirmation and tenant-exposure audit names used by telemetry. Empty logs are not proof of zero incidents. Delivery creates a durable assigned in-app staff task. An unacknowledged alert escalates through configured active members at the specified interval. It does not claim an email/SMS/page was sent.

`POST /operations/alerts/{id}/actions` accepts `action: ACKNOWLEDGE|RESOLVE` and evidence_reference. Only an authorized integration administrator or configured on-call member can act. Resolve requires acknowledgment and closes linked alert tasks. Shared worker runs are deduplicated.

## 4. Trusted receipts and selective outbound reminders

The SMS worker calculates actual GSM/UCS2 segment units, applies neutral shared-phone wording, checks processor and monetary controls, commits the dispatch boundary, and records actual provider-returned charges separately from approved-rate estimates. An unknown send is not retried automatically. Trusted Kavenegar HTTPS status polling checks the exact provider message identity, is bounded to 12 checks with backoff, and stops at a terminal receipt. A pending status does not mean delivered.

The controlled SMS conversation template is `conversation_reply_v1`, with encrypted trusted server reply and linked call/turn identifiers. Dispatch checks tenant, caller hash and processing consent; templates are capped by both text and ten actual transport segments.

`POST /operations/voice-outreach` accepts appointment_id, purpose=`reminder`, idempotency_key, max_seconds (10–120), patient_voice_request_confirmed. The appointment must be future, confirmed and opted in; current independent reminder permission and explicit voice-channel permission are both required. `GET /operations/voice-outreach` exposes job state and separate gateway-configuration truth.

The **operator-approved outbound gateway v1 contract** is an optional integration, not an invented native carrier API. Required deployment settings are `OUTBOUND_VOICE_APPROVED`, `OUTBOUND_VOICE_GATEWAY_URL`, `OUTBOUND_VOICE_GATEWAY_TOKEN`, `OUTBOUND_ALLOWED_PREFIXES`, `OUTBOUND_PROCESSOR_REGION`, plus approved HTTPS host configuration. The gateway must advertise bounded idempotent origination, authoritative readback, maximum-duration enforcement and voicemail suppression at `GET /v1/capabilities`. Origination uses `POST /v1/calls` with request identity, allowed Iranian mobile destination, a neutral fixed template, duration bound and voicemail policy. Readback is `GET /v1/calls/by-key/{id}`.

Only two explicitly requested, definitively unsuccessful attempts are allowed per appointment. Quiet hours apply before first dispatch. Unknown or interrupted origination is reconciled by readback, never blindly originated again. Missing final billable duration remains an unresolved cost reservation. Default shared-phone/voicemail policy prevents recorded-message disclosure. A real gateway/carrier contract, machine-detection behavior, toll controls and live delivery must still be independently approved and tested.

## 5. Worker and recovery integration

`run_control_jobs(db, limit=100)` is synchronous and flush-only; the caller commits it. It performs bounded artifact and administrative-transcript expiry, unused reservation expiry, positive alert evaluation and in-app escalation. `run_messaging_control_jobs(session_factory)` performs trusted receipt checks and approved voice job dispatch/reconciliation, releasing transactions before external I/O. These are registered in the root worker loop alongside the existing outbox/partner jobs.

The control worker's `limit` is a **per-clinic record cap**, from 1 to 1000. It traverses all clinics in stable ID order, including disabled clinics for expiry, so a later clinic cannot be permanently excluded by a fixed first page. Tenant traversal itself is not capped and no fixed total-runtime bound is claimed. The traversal performs database work only; messaging/provider network I/O remains outside it.

`scripts/config_backup.py` creates an authenticated encrypted configuration bundle and metadata-only key custody inventory under a separate protected Fernet key file. It never prints key/config contents, stages plaintext, replaces an existing backup or restores over a nonempty directory. Restore verifies every content hash first and writes directory/file permissions 0700/0600. The tool does not make an offsite copy, perform a real key-custodian exercise, or start the recovered application. Those remain named operator responsibilities.

See `docs/research-workflow-v2.md` for the new capture, evaluation, training and worker-measurement commands and their evidence limits.
