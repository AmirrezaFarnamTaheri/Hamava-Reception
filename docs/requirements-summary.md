# Requirement completion and remaining-work register

**Hamava 0.2.0: 263 original requirement IDs; no pending or omitted rows.** This is an evidence register, not a production-readiness certificate or a completion percentage.

The JSON register preserves every original acceptance statement and its history; the CSV is a filterable view. Current v2 evidence supersedes stale implementation limitations while preserving real external and optional gates. Native companion and release acceptance is recorded separately in `validation/v2-native-release-evidence.json`.

## Status interpretation

- **Verified locally — 212:** The named local software/document behavior is supported by explicit tests or inspection within acceptance_limits. This is not external provider, deployment, legal, clinical, commercial or representative research validation.
- **Partial / full acceptance unverified — 26:** Partially implemented and/or full stated acceptance not demonstrated. Read remaining_acceptance; this status does not mean all required code exists.
- **Blocked by external inputs — 22:** Work depends on a specifically missing external account, rights, infrastructure, person or observation.
- **Optional product/research gate — 3:** Original blueprint explicitly places feature behind an unmet product/evidence gate; retain exact rationale.

There are **0 externally verified** requirements. Named owner fields denote roles; actual accountable people must be assigned.

## Phase totals

| Phase | Verified locally | Partial / unverified | External inputs | Optional gate | Total |
|---|---:|---:|---:|---:|---:|
| 0 — Groundwork and accountable launch preparation | 28 | 9 | 7 | 0 | 44 |
| 1 — Browser proof and trustworthy booking foundation | 81 | 3 | 0 | 0 | 84 |
| 2 — Single-location PSTN/media operations | 23 | 9 | 6 | 0 | 38 |
| 3 — Revenue/attendance workflows | 30 | 3 | 1 | 0 | 34 |
| 4 — Multi-tenant building hub | 29 | 0 | 0 | 0 | 29 |
| 5 — Channels and partner scale | 8 | 1 | 5 | 0 | 14 |
| 6 — Optional Persian speech research/infrastructure | 13 | 1 | 3 | 3 | 20 |
| **Total** | **212** | **26** | **22** | **3** | **263** |

## Open implementation or full acceptance, by phase

Every non-verified item is listed below. The final section also lists external evidence still attached to locally verified behavior.

### Phase 0 — Groundwork and accountable launch preparation

#### FOUNDATION-009 — Graceful shutdown

**Status:** Partial / full acceptance unverified  
**Responsible role:** Platform engineering (role; actual accountable person not assigned)

**Acceptance:** API/worker/media processes end in-flight work safely, close handles and preserve recoverable jobs.

**Remaining acceptance:**

- Execute real RTC/AudioSocket process-signal and forced-stop drills with deployed SDK/carrier handles and subsequent recovery.
- Prior real RTC smoke emitted an unknown-FFI-handle cleanup warning; this revision does not claim to have eliminated it or proven a leak.

**Evidence:** `backend/receptionist/main.py`, `backend/receptionist/worker.py`, `backend/receptionist/media/livekit_worker.py`, `backend/receptionist/media/audiosocket.py`, `backend/receptionist/operations.py`, `backend/tests/test_ops.py::test_stalled_dispatch_becomes_unknown`, `docs/validation/media-admission-load.json`, `docs/validation/livekit-loopback.json`, `docs/validation/audiosocket-loopback.json`, `backend/receptionist/core_runtime.py`, `backend/tests/test_core_integrations.py::test_runtime_is_fair_bounded_and_explicitly_reports_timeout`, `docs/core-extension-contract.md`

#### FOUNDATION-011 — Automated CI

**Status:** Partial / full acceptance unverified  
**Responsible role:** Platform engineering (role; actual accountable person not assigned)

**Acceptance:** CI runs necessary backend, frontend, type/build, contract and integration gates without live customer credentials.

**Remaining acceptance:**

- Connect the intended authorized repository and execute its actual workflows; retain the remote run and Docker startup results.

**External inputs:** Connect the intended authorized repository and execute its actual workflows; retain the remote run and Docker startup results.

**Evidence:** `.github/workflows/verify.yml`, `frontend/package.json`, `docs/validation/pytest-final.xml`, `.github/workflows/release-apps.yml`, `scripts/ci_ui.py`, `scripts/collect-release.mjs`, `docs/validation/v2-release-collector.json`, `docs/validation/v2-docker-context-check.json`, `docs/validation/v2-final-checks.json`

#### BUSINESS-001 — Discovery worksheet

**Status:** Partial / full acceptance unverified  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Capture observed demand, missed calls, capacity, contribution, staff load, decision-maker and willingness-to-pay.

**Remaining acceptance:**

- No real interview or observed demand was collected.

**External inputs:** Authorized clinic interviews and operating data.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### BUSINESS-002 — Pilot segment scorecard

**Status:** Partial / full acceptance unverified  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Score low-complexity dental/aesthetic/salon sites and buildings on measurable fit, access and change readiness.

**Remaining acceptance:**

- No sites were actually scored from verified observations.

**External inputs:** Observed site data and authorized decision makers.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### BUSINESS-003 — Vendor due-diligence registry

**Status:** Partial / full acceptance unverified  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Carrier/host/STT/TTS/LLM/calendar/SMS/payment candidates retain terms, availability, price dates and proof gaps.

**Remaining acceptance:**

- No vendor account/contract/due-diligence conclusion is fabricated.

**External inputs:** Current primary documentation, rights and account tests.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### BUSINESS-004 — Clinical script sign-off

**Status:** Blocked by external inputs  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Approved administrative/emergency/aftercare scripts have named qualified clinical owner before medical launch.

**Remaining acceptance:**

- No qualified real clinical owner has signed.

**External inputs:** Actual clinical sign-off and clinic-specific guidance.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### BUSINESS-005 — Privacy and contract review

**Status:** Blocked by external inputs  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Actual controller/processor, recording, retention, cross-border, medical secrecy and training purposes have local counsel review.

**Remaining acceptance:**

- No legal opinion/compliance conclusion is claimed.

**External inputs:** Qualified actual legal review and executed agreements.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### BUSINESS-006 — Pilot agreement

**Status:** Blocked by external inputs  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** A 7/14/30-day or agreed overflow trial specifies traffic cap, baseline, scope, fallback, privacy, support and success metrics.

**Remaining acceptance:**

- No pilot agreement was signed or counterparty contacted.

**External inputs:** Authorized counterparties and executed terms.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### BUSINESS-007 — Staffed operating coverage

**Status:** Blocked by external inputs  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Each shift/holiday/language route has authorized people and measured pickup capacity.

**Remaining acceptance:**

- No actual roster or pickup capacity was measured.

**External inputs:** Real staff, availability, training and answered-handoff tests.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### BUSINESS-008 — Comparable baseline design

**Status:** Partial / full acceptance unverified  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Matched hours/control route accounts for campaigns, holidays, capacity, displaced demand and seasonality.

**Remaining acceptance:**

- No observed comparable baseline/control cohort was collected.

**External inputs:** Authorized baseline/pilot/attendance data and confounder coverage.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`, `scripts/economics.py`, `scripts/pilot_analysis.py`, `backend/tests/test_research_tools.py`, `docs/evidence/economics-synthetic.json`, `docs/evidence/pilot-synthetic.json`

#### BUSINESS-009 — Pilot attendance reconciliation

**Status:** Blocked by external inputs  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Confirmed appointments are reconciled to clinic-verified attendance and failure/correction records.

**Remaining acceptance:**

- No clinic-verified attendance/correction log was reconciled.

**External inputs:** Actual clinic appointment/attendance/failure records and review.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`, `scripts/economics.py`, `scripts/pilot_analysis.py`, `backend/tests/test_research_tools.py`, `docs/evidence/economics-synthetic.json`, `docs/evidence/pilot-synthetic.json`

#### BUSINESS-010 — Honest pricing offer

**Status:** Partial / full acceptance unverified  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Setup/platform/allowance/overage/SMS/outbound/human service/tax/unit/FX terms are explicit and cost-tested.

**Remaining acceptance:**

- No actual contract/current verified tariff is implied by examples.

**External inputs:** Dated actual costs, tax/unit terms and commercial approval.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`, `scripts/economics.py`, `scripts/pilot_analysis.py`, `backend/tests/test_research_tools.py`, `docs/evidence/economics-synthetic.json`, `docs/evidence/pilot-synthetic.json`

#### BUSINESS-011 — Sales material

**Status:** Partial / full acceptance unverified  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Persian offer describes verified outcomes and limitations without unsupported percentages/unlimited promises.

**Remaining acceptance:**

- Actual brand/contact/offer facts still require approval before publication.

**External inputs:** Commercial approval and evidence for advertised claims.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### BUSINESS-012 — Renewal evidence

**Status:** Blocked by external inputs  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** At least two pilot customers independently demonstrate value and willingness to pay before scaling.

**Remaining acceptance:**

- No two paid pilots, renewal decisions or willingness-to-pay evidence exists.

**External inputs:** Actual independent customer outcomes and paid renewals.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### BUSINESS-013 — Building authority

**Status:** Blocked by external inputs  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Each independent clinic authorizes phone/data participation; building management alone cannot grant access.

**Remaining acceptance:**

- No clinic phone/data participation agreements were signed.

**External inputs:** Real clinic controller/phone owners and executed rights.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### BUSINESS-014 — Founder and escalation ownership

**Status:** Partial / full acceptance unverified  
**Responsible role:** Commercial owner and clinic decision maker (role; actual accountable person not assigned)

**Acceptance:** Commercial, technical, clinical/privacy, finance/support and stop-ship decisions have named owners.

**Remaining acceptance:**

- No real accountable people were supplied by the user.

**External inputs:** Actual operators accepting ownership and escalation duties.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`


### Phase 1 — Browser proof and trustworthy booking foundation

#### BOOKING-012 — External conflict recovery

**Status:** Partial / full acceptance unverified  
**Responsible role:** Calendar engineering and clinic operations (role; actual accountable person not assigned)

**Acceptance:** A concurrent staff/website write is detected or the action remains supervised pending review.

**Remaining acceptance:**

- Demonstrate atomic conditional writes against the independently operated clinic website/EHR while staff and website writers contend. Local protocol fixtures cannot establish a third-party source actually enforces its advertised preconditions.

**Evidence:** `backend/receptionist/core.py`, `backend/receptionist/api.py`, `backend/receptionist/voice.py`, `backend/receptionist/partners.py`, `backend/tests/test_core.py::test_successful_reschedule_and_stale_version`, `docs/validation/postgres-contention.json`, `backend/receptionist/calendar_contract.py`, `backend/receptionist/calendar_bridge.py`, `backend/receptionist/tool_gateway.py`, `backend/tests/test_core_integrations.py::test_calendar_unknown_write_is_reconciled_once_and_replay_reads_current_authority`, `backend/tests/test_core_integrations.py::test_calendar_contract_scope_id_match_and_interval_fail_closed`, `docs/core-extension-contract.md`

#### CONVERSATION-007 — Urgent phrase route

**Status:** Partial / full acceptance unverified  
**Responsible role:** Conversation engineering and clinic operations (role; actual accountable person not assigned)

**Acceptance:** Approved potentially urgent phrases interrupt ordinary booking and invoke approved human/emergency guidance without diagnosis.

**Remaining acceptance:**

- Clinical/clinic approval of the final production emergency wording and actual staffed emergency route remains external.

**Evidence:** `backend/tests/test_voice.py::test_urgency_never_enters_booking_or_claims_triage`, `backend/receptionist/voice.py::Conversation.answer`

#### CONVERSATION-015 — Language fallback

**Status:** Partial / full acceptance unverified  
**Responsible role:** Conversation engineering and clinic operations (role; actual accountable person not assigned)

**Acceptance:** Unsupported English/Arabic/code-switching routes to an approved language path rather than fabricated fluency.

**Remaining acceptance:**

- Validate unannounced language/code-switch classification on a representative corpus.
- Verify language-qualified staff availability and actual pickup.

**Evidence:** `backend/receptionist/voice.py::Conversation.answer`, `backend/receptionist/voice.py::_requested_language`, `backend/tests/test_voice_followup.py::test_explicit_unsupported_language_gets_truthful_human_route`, `backend/tests/test_voice_followup.py::test_language_switch_releases_uncommitted_slot`, `docs/validation/voice-final-tests.json`, `backend/receptionist/locale.py`, `backend/receptionist/routing.py`, `backend/receptionist/voice.py`, `backend/tests/test_core_integrations.py::test_spoken_numbers_ids_and_language_routing_are_deterministic`, `backend/tests/test_core_integrations.py::test_versioned_routing_enforces_global_did_and_current_language_attestation`, `docs/core-extension-contract.md`


### Phase 2 — Single-location PSTN/media operations

#### MEDIA-005 — Speech provider abstraction

**Status:** Partial / full acceptance unverified  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** STT partial/final/keyterms, structured model tools and TTS audio/chunks have comparable contracts.

**Remaining acceptance:**

- Native partial STT, native streaming TTS and generative model tool-stream adapters are not implemented or enabled. Comparable live streaming parity requires a selected approved provider and its adapter/conformance work.

**Evidence:** `backend/receptionist/providers.py::SpeechGateway`, `services/local_speech/app.py`, `backend/receptionist/providers.py`, `backend/receptionist/tool_gateway.py`, `backend/tests/test_core_integrations.py::test_speech_meter_uses_submitted_pcm_and_malformed_tts_degrades_without_erasing_charge`, `backend/tests/test_core_integrations.py::test_strict_tool_boundary_rejects_tenant_and_proof_injection_and_deadline_rolls_back`, `docs/core-extension-contract.md`

#### MEDIA-008 — Browser audio lifecycle

**Status:** Partial / full acceptance unverified  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** User-initiated microphone permission, connected state, stop, reconnect and cleanup are accurately represented.

**Remaining acceptance:**

- Demonstrate an actual interrupted-network reconnect with resumed audio on the supported browser/SDK path; an injected Reconnected event is insufficient.
- Execute physical mobile background/lock/reconnect, microphone/audio-route and interruption acceptance under MEDIA-UAT-004.

**Evidence:** `backend/receptionist/voice.py::end_session`, `backend/tests/test_voice_integrity.py::test_provider_waits_release_database_connections_and_allow_unrelated_writes`, `docs/validation/livekit-loopback.json`, `frontend/src/pages/Talk.tsx`, `frontend/src/LiveCalls.tsx`, `frontend/src/rtcLifecycle.ts`, `docs/validation/browser-audio.json`, `docs/validation/browser-live-ui.json`, `docs/validation/browser-rtc-lifecycle.json`, `docs/validation/v2-browser-rtc-lifecycle.json`

#### MEDIA-009 — WebRTC session isolation

**Status:** Partial / full acceptance unverified  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** Production WebRTC route has scoped room tokens, HTTPS/TURN configuration and per-session privacy.

**Remaining acceptance:**

- Production public HTTPS, ICE/TURN/NAT and cross-device isolation need deployment acceptance; one loopback call is insufficient.

**Evidence:** `backend/receptionist/media_api.py`, `backend/tests/test_voice_integrity.py::test_worker_capacity_and_lease_generation_fence_stale_worker`, `backend/tests/test_voice_integrity.py::test_verified_human_webhook_requires_live_tenant_membership_and_is_idempotent`, `docs/validation/livekit-loopback.json`

#### MEDIA-010 — Voice activity and endpointing

**Status:** Partial / full acceptance unverified  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** Turn endpointing permits slow digits/hesitant speakers and handles silence/noise without hallucinated actions.

**Remaining acceptance:**

- Real hesitant/slow-digit/noisy Persian caller slices need blinded acoustic validation.

**Evidence:** `backend/receptionist/media/audio.py::TurnBuffer`, `backend/tests/test_media_providers.py::test_endpointing_supports_barge_in_and_does_not_transcribe_silence`

#### MEDIA-012 — Latency telemetry

**Status:** Partial / full acceptance unverified  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** Measure end-of-turn to first audible output and STT/model/tool/TTS/transfer subspans separately.

**Remaining acceptance:**

- Measure end-of-turn to first audible output at physical receivers and establish distributions under the deployed network/device/provider conditions. The local RTC received-PCM smoke is not physical speaker output or an acoustic SLO.

**Evidence:** `backend/receptionist/models_voice.py::VoiceTurn`, `backend/receptionist/telemetry.py`, `docs/validation/livekit-loopback.json`, `docs/validation/speech-smoke.json`, `backend/receptionist/voice.py::audio_turn`, `backend/receptionist/voice.py::speech`, `backend/receptionist/media_api.py`, `backend/tests/test_partners_and_tools.py::test_latency_report_is_scoped_and_does_not_invent_audible_measurement`, `backend/receptionist/tool_gateway.py::ToolGateway.call`, `backend/receptionist/tool_gateway.py::persist_tool_spans`, `backend/receptionist/voice.py::execute_turn`, `backend/receptionist/telemetry.py::latency_report`, `backend/tests/test_tool_telemetry_v2.py`, `docs/validation/v2-tool-spans.xml`, `docs/validation/v2-tool-spans.json`, `docs/core-extension-contract.md`

#### MEDIA-015 — Handoff transport truth

**Status:** Partial / full acceptance unverified  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** Requested/ringing/accepted/connected/failed states follow real transport events; a task is not a connected call.

**Remaining acceptance:**

- Select the approved PBX/carrier transport and implement its authenticated requested/ringing/accepted/failed event mapping, ordering/replay handling and warm-transfer/bridge integration.
- Run adapter conformance and failure/recovery tests, then demonstrate actual ringing, acceptance, human audio connection, no-answer fallback and AI shutdown on the intended carrier and staff endpoints.

**External inputs:** Approved PBX/carrier event and transfer contract, authorized test trunk/DID, reachable staff endpoints and accountable operator.

**Evidence:** `backend/tests/test_voice_integrity.py::test_verified_human_webhook_requires_live_tenant_membership_and_is_idempotent`, `backend/tests/test_voice_integrity.py::test_human_connected_stops_text_audio_speech_and_cannot_be_downgraded`, `docs/validation/livekit-loopback.json`, `backend/receptionist/media/contracts.py`, `backend/receptionist/media_api.py`, `backend/receptionist/media/livekit_worker.py`, `deploy/asterisk/extensions_hamava.conf`

#### MEDIA-UAT-001 — Carrier provisioning and line control

**Status:** Blocked by external inputs  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** Approved domestic DID/trunk/forwarding is provisioned by its authorized owner.

**Remaining acceptance:**

- Authorized domestic DID/trunk/forwarding account and owner-controlled provisioning.

**External inputs:** Carrier account, DID ownership, contract, static IP/interconnect specification

**Evidence:** `docs/validation/livekit-loopback.json`, `docs/validation/speech-smoke.json`, `docs/launch-playbook.md`

#### MEDIA-UAT-002 — PSTN codec and DTMF matrix

**Status:** Blocked by external inputs  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** Real target networks pass A-law/u-law, DTMF, one-way audio, NAT, jitter, hold and teardown tests.

**Remaining acceptance:**

- Real target-carrier A-law/u-law/DTMF/NAT/jitter/one-way-audio/hold/teardown matrix.

**External inputs:** Domestic SIP/PBX endpoint and target mobile/fixed networks

**Evidence:** `docs/validation/livekit-loopback.json`, `docs/validation/speech-smoke.json`, `docs/launch-playbook.md`

#### MEDIA-UAT-003 — Warm transfer and fallback

**Status:** Blocked by external inputs  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** Staff actually accepts and receives media/context; busy/no-answer/call-drop preserves original/human/callback route.

**Remaining acceptance:**

- Real staffed warm transfer and busy/no-answer/call-drop fallback over the target PSTN path.

**External inputs:** Staffed queue, PBX/carrier transfer capability

**Evidence:** `docs/validation/livekit-loopback.json`, `docs/validation/speech-smoke.json`, `docs/launch-playbook.md`

#### MEDIA-UAT-004 — Mobile browser matrix

**Status:** Blocked by external inputs  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** iOS Safari, Android Chrome and in-app browsers pass mic, background/lock/reconnect/accessibility checks.

**Remaining acceptance:**

- Run the authorized physical iOS Safari, Android Chrome and in-app-browser matrix for microphone permission, background/lock/reconnect, interruptions, audio/Bluetooth routing and accessibility; retain exact versions and observed outcomes.

**External inputs:** Representative phones/devices, real HTTPS/TURN and approved audio provider

**Evidence:** `docs/validation/livekit-loopback.json`, `docs/validation/speech-smoke.json`, `docs/launch-playbook.md`, `docs/validation/browser-audit.json`, `docs/validation/browser-audio.json`, `docs/validation/browser-live-ui.json`, `frontend/src/pages/Talk.tsx`, `frontend/src/Workspace.tsx`, `docs/validation/v2-browser-audit.json`, `docs/validation/v2-browser-companion.json`, `docs/validation/v2-browser-privacy-notice.json`

#### MEDIA-UAT-005 — Measured speech quality

**Status:** Blocked by external inputs  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** Authorized telephone-grade Persian audio is blindly reviewed by native speakers across defined slices.

**Remaining acceptance:**

- Permissioned telephone-grade corpus and independent native-speaker blind review.

**External inputs:** Permissioned corpus, native reviewers, selected provider accounts

**Evidence:** `docs/validation/livekit-loopback.json`, `docs/validation/speech-smoke.json`, `docs/launch-playbook.md`

#### MEDIA-UAT-006 — Latency and peak channels

**Status:** Blocked by external inputs  
**Responsible role:** Telephony/media engineering (role; actual accountable person not assigned)

**Acceptance:** Measured P50/P95/P99 and successful peak load establish paid limits under actual network conditions.

**Remaining acceptance:**

- Actual network/load sample with sufficient P50/P95/P99 and peak-channel denominators.

**External inputs:** Provisioned channels and representative hosting/carrier load fixture

**Evidence:** `docs/validation/livekit-loopback.json`, `docs/validation/speech-smoke.json`, `docs/launch-playbook.md`

#### OPERATIONS-007 — Clinical incident runbook

**Status:** Partial / full acceptance unverified  
**Responsible role:** Technical operations and service owner (role; actual accountable person not assigned)

**Acceptance:** Urgent phrase/unsafe advice incidents stop affected flow and reach named clinical operations review.

**Remaining acceptance:**

- No real qualified clinical owner has signed/staffed the procedure.

**External inputs:** Named qualified reviewer and real emergency/handoff arrangements.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### OPERATIONS-008 — Privacy incident runbook

**Status:** Partial / full acceptance unverified  
**Responsible role:** Technical operations and service owner (role; actual accountable person not assigned)

**Acceptance:** Wrong-tenant/recipient/export/audio incidents contain exposure and preserve minimal evidence.

**Remaining acceptance:**

- Actual notification/legal obligations and accountable people need local review.

**External inputs:** Qualified privacy/legal owner and real incident contacts.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`

#### OPERATIONS-011 — Operator handover

**Status:** Partial / full acceptance unverified  
**Responsible role:** Technical operations and service owner (role; actual accountable person not assigned)

**Acceptance:** Deployment/configuration, provider registry, support contacts and unresolved risk list are complete.

**Remaining acceptance:**

- Actual accounts, contacts and operator acceptance are not filled with fictional defaults.

**External inputs:** Real technical/clinic/commercial/privacy/clinical/support owners.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`


### Phase 3 — Revenue/attendance workflows

#### MESSAGING-003 — SMS adapter

**Status:** Partial / full acceptance unverified  
**Responsible role:** Messaging engineering and clinic operations (role; actual accountable person not assigned)

**Acceptance:** Configured domestic gateway accepts approved templates, handles structured errors and returns provider receipt identity.

**Remaining acceptance:**

- Native live account/template/receipt behavior has not been verified.

**External inputs:** Approved SMS account, actual contract and delivery tests.

**Evidence:** `backend/receptionist/providers.py`, `backend/tests/test_media_providers.py`, `backend/receptionist/operations.py`, `backend/tests/test_ops.py`, `backend/tests/test_ops_review.py`

#### MESSAGING-012 — Selective voice reminders

**Status:** Blocked by external inputs  
**Responsible role:** Messaging engineering and clinic operations (role; actual accountable person not assigned)

**Acceptance:** Opt-in outbound reminders such as 6-hour follow-up honor routes, quiet hours, budget and cap.

**Remaining acceptance:**

- No invented carrier API or fake dial result is shipped.

**External inputs:** Approved outbound carrier capability, routes/consent/billing and real outcome tests.

**Evidence:** `backend/receptionist/operations_outreach.py`, `backend/tests/test_outreach_workflows.py`, `docs/api-contract.md`

#### PAYMENT-004 — Hosted gateway link

**Status:** Partial / full acceptance unverified  
**Responsible role:** Payments engineering and finance (role; actual accountable person not assigned)

**Acceptance:** Provider-approved link is returned without collecting card secrets in app/call.

**Remaining acceptance:**

- No real merchant payment was executed.

**External inputs:** Provider approval/account and actual hosted-link contract tests.

**Evidence:** `backend/receptionist/payment_policy.py`, `backend/tests/test_payment_policy.py`, `backend/receptionist/providers.py`, `backend/tests/test_media_providers.py`, `backend/receptionist/operations.py`, `backend/tests/test_ops.py`, `backend/tests/test_ops_review.py`

#### PAYMENT-008 — Refund ledger

**Status:** Partial / full acceptance unverified  
**Responsible role:** Payments engineering and finance (role; actual accountable person not assigned)

**Acceptance:** Full/partial/refused/pending/settled refund states are idempotent and reconcile with provider truth.

**Remaining acceptance:**

- Code records authorized evidence but does not execute refunds or authenticate an entered bank reference independently.

**External inputs:** Actual transfer execution, receipts and reconciliation responsibility.

**Evidence:** `backend/receptionist/operations.py`, `backend/tests/test_ops.py`, `backend/tests/test_ops_review.py`, `backend/receptionist/operations_outreach.py`, `backend/tests/test_outreach_workflows.py`


### Phase 5 — Channels and partner scale

#### PARTNER-008 — Multilingual routing extension

**Status:** Partial / full acceptance unverified  
**Responsible role:** Partnerships and integration engineering (role; actual accountable person not assigned)

**Acceptance:** English/Arabic routes are enabled only with tested provider/scripts and authorized staff fallback.

**Remaining acceptance:**

- Test approved language scripts acoustically with the deployed provider and representative callers.
- Provide qualified staff schedules and verified language pickup drills.

**Evidence:** `backend/receptionist/voice.py::Conversation.answer`, `backend/tests/test_voice_followup.py::test_explicit_unsupported_language_gets_truthful_human_route`, `backend/receptionist/routing.py`, `backend/receptionist/voice.py`, `backend/receptionist/locale.py`, `backend/tests/test_core_integrations.py::test_versioned_routing_enforces_global_did_and_current_language_attestation`, `backend/tests/test_core_integrations.py::test_spoken_numbers_ids_and_language_routing_are_deterministic`, `docs/core-extension-contract.md`, `frontend/src/pages/Routing.tsx`, `docs/validation/v2-browser-companion.json`

#### PARTNER-GATE-001 — Booking partner write access

**Status:** Blocked by external inputs  
**Responsible role:** Partnerships and integration engineering (role; actual accountable person not assigned)

**Acceptance:** A selected Paziresh24/Doctoreto/EHR/calendar provider grants clinic-specific create/update/cancel/read rights.

**Remaining acceptance:**

- Supply a selected provider contract, clinic-specific scoped write/read rights, sandbox credentials and actual create/update/cancel/read-back UAT.

**External inputs:** Provider contract, sandbox, scoped credentials, real integration UAT

**Evidence:** `README.md`, `backend/receptionist/providers.py`, `docs/deployment-runbook.md`

#### PARTNER-GATE-002 — Additional calendar breadth

**Status:** Blocked by external inputs  
**Responsible role:** Partnerships and integration engineering (role; actual accountable person not assigned)

**Acceptance:** Cal.com/Google/Bookly/Nobat/clinic integrations are individually verified and advertised only at supported capability.

**Remaining acceptance:**

- Individually implement and verify each selected official calendar integration with clinic authorization and its supported capability matrix.

**External inputs:** Official provider API access and clinic authorization

**Evidence:** `README.md`, `backend/receptionist/providers.py`, `docs/deployment-runbook.md`

#### PARTNER-GATE-003 — Social API access

**Status:** Blocked by external inputs  
**Responsible role:** Partnerships and integration engineering (role; actual accountable person not assigned)

**Acceptance:** Instagram Direct, Telegram/Bale/Eitaa/WhatsApp or Mini App access satisfies actual platform requirements.

**Remaining acceptance:**

- Provide approved platform accounts/permissions, native connector configuration and scoped recipient delivery/webhook UAT for each selected social channel.

**External inputs:** Platform accounts/permissions/webhooks and opt-in recipient policy

**Evidence:** `backend/receptionist/partners.py`, `docs/deployment-runbook.md`

#### PARTNER-GATE-004 — Prescription/insurance portals

**Status:** Blocked by external inputs  
**Responsible role:** Partnerships and integration engineering (role; actual accountable person not assigned)

**Acceptance:** Any dedicated insurance/e-prescription integration requires separate authorization and is never achieved by scraping.

**Remaining acceptance:**

- Obtain dedicated commercial/legal permission and implement/test only the specifically authorized portal API if the product gate is activated.

**External inputs:** Dedicated commercial/legal integration permission

**Evidence:** `README.md`, `docs/blueprint-revision.md`, `docs/launch-playbook.md`

#### PARTNER-GATE-005 — Agency distribution terms

**Status:** Blocked by external inputs  
**Responsible role:** Partnerships and integration engineering (role; actual accountable person not assigned)

**Acceptance:** White-label/revenue share/partner support terms are signed rather than inferred from example 70/30 split.

**Remaining acceptance:**

- Record signed white-label/revenue-share/support agreements and real operating responsibilities; the example 70/30 split is not evidence.

**External inputs:** Partner agreement and operational support capability

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `backend/receptionist/partners.py`


### Phase 6 — Optional Persian speech research/infrastructure

#### RESEARCH-014 — Local serving experiment

**Status:** Partial / full acceptance unverified  
**Responsible role:** Research owner and data/rights reviewers (role; actual accountable person not assigned)

**Acceptance:** Local ASR/TTS/model worker deployment exposes bounded queues, concurrency/cold-start and actual cost metrics.

**Remaining acceptance:**

- Install approved weights and run the bounded benchmark on actual deployment hardware, then compare quality, cost and concurrency to the approved baseline.

**External inputs:** Install approved weights and run the bounded benchmark on actual deployment hardware, then compare quality, cost and concurrency to the approved baseline.

**Evidence:** `services/local_speech/app.py`, `services/local_speech/Dockerfile`, `docs/validation/speech-smoke.json`, `scripts/benchmark_local_speech.py`, `backend/tests/test_research_ops_tools_v2.py`, `backend/tests/test_research_tools.py`, `docs/v2-operations-api.md`, `docs/research-workflow-v2.md`

#### RESEARCH-015 — Realtime protocol evaluation

**Status:** Optional product/research gate  
**Responsible role:** Research owner and data/rights reviewers (role; actual accountable person not assigned)

**Acceptance:** Any compatibility claim requires event/auth/tool/error/client conformance, not an endpoint name alone.

**Remaining acceptance:**

- No enterprise realtime event/auth/tool/error/client conformance suite is implemented.

**External inputs:** Selected protocol/version and independent product demand.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`, `docs/research-workflow.md`, `backend/tests/test_research_tools.py`

#### RESEARCH-GATE-001 — Consented telephone corpus

**Status:** Blocked by external inputs  
**Responsible role:** Research owner and data/rights reviewers (role; actual accountable person not assigned)

**Acceptance:** Representative authorized Persian telephone audio and validated labels exist with auditable provenance.

**Remaining acceptance:**

- No representative authorized Persian telephone corpus/validated real labels exists.

**External inputs:** Clinic/caller rights, approved collection and independent labels.

**Evidence:** `scripts/dataset_curate.py`, `backend/tests/test_research_tools.py`, `docs/evidence/curation-synthetic.json`, `docs/research-workflow.md`

#### RESEARCH-GATE-002 — Model and voice licensing

**Status:** Blocked by external inputs  
**Responsible role:** Research owner and data/rights reviewers (role; actual accountable person not assigned)

**Acceptance:** Selected code/weights/datasets and any cloned voice have valid commercial and derivative rights.

**Remaining acceptance:**

- Metadata validation does not verify legal sufficiency or authorize cloned voices.

**External inputs:** Current licenses and explicit voice-owner permissions where relevant.

**Evidence:** `scripts/train_asr.py`, `scripts/requirements-training.txt`, `backend/tests/test_research_tools.py`, `docs/research-workflow.md`

#### RESEARCH-GATE-003 — Real fine-tuning run

**Status:** Optional product/research gate  
**Responsible role:** Research owner and data/rights reviewers (role; actual accountable person not assigned)

**Acceptance:** A training run completes on eligible data with reproducible checkpoints and logged compute.

**Remaining acceptance:**

- No real fine-tuning/checkpoint/compute log was produced.

**External inputs:** Real eligible data, reviewed weights, approved compute and execution.

**Evidence:** `scripts/train_asr.py`, `scripts/requirements-training.txt`, `backend/tests/test_research_tools.py`

#### RESEARCH-GATE-004 — Held-out superiority

**Status:** Optional product/research gate  
**Responsible role:** Research owner and data/rights reviewers (role; actual accountable person not assigned)

**Acceptance:** Specialized model passes blind held-out quality/cost/non-regression against baselines and accents.

**Remaining acceptance:**

- No specialized trained model or blind superiority result exists.

**External inputs:** Native-listener held-out quality/cost/non-regression study.

**Evidence:** `scripts/evaluate_speech.py`, `backend/tests/test_research_tools.py`, `docs/evidence/speech-synthetic.json`, `docs/research-workflow.md`

#### RESEARCH-GATE-005 — Enterprise infrastructure demand

**Status:** Blocked by external inputs  
**Responsible role:** Research owner and data/rights reviewers (role; actual accountable person not assigned)

**Acceptance:** Independent customers and support/rights/economics justify a domestic/on-prem voice API product.

**Remaining acceptance:**

- No independent enterprise demand/supportable infrastructure business was established.

**External inputs:** Actual customer demand, rights, support and measured economics.

**Evidence:** `docs/blueprint-revision.md`, `docs/launch-playbook.md`, `docs/operations-review.md`, `docs/research-workflow.md`, `backend/tests/test_research_tools.py`


## External acceptance attached to locally verified behavior

These rows are locally verified only within their stated scope. The following requirements still identify real supplier, device, operator or field evidence; the register preserves the full limits.

| Requirement | Acceptance still required |
|---|---|
| FOUNDATION-006 — Configuration validation | Supply actual approved credentials, model rights and processing-region evidence; syntax validation does not certify supplier behavior. |
| FOUNDATION-008 — Health and readiness | Validate actual supplier and deployed failure/recovery behavior with approved accounts and routes. Local mock transports do not establish supplier availability. |
| FOUNDATION-013 — Provider capability registry | Obtain current supplier documentation and owner attestations; a configured flag or operator attestation is not an independent vendor certification. |
| TENANT-003 — Provider and service catalog | Clinic owners must approve actual preparation, insurance and eligibility facts; seeded statements are fictional. |
| TENANT-008 — Approved knowledge facts | An accountable clinic approver must establish fact accuracy; migration preserves technical calendar authority without inventing clinical approvals. |
| TENANT-010 — Routing configuration | Map actual carrier DIDs and verified PBX targets, then perform real routing and human pickup drills. |
| TENANT-012 — Budgets and channel caps | Set actual supplier rates and upstream carrier/PBX account caps. |
| TENANT-014 — Clinic policy UAT | Actual clinic reviewer, truthful test execution, carrier/clinical/legal approvals remain separate. |
| AUTH-002 — Roles and memberships | Assign actual people to least-privilege clinic roles and review memberships operationally. |
| AUTH-014 — Abuse quotas | Set actual supplier rates and upstream carrier/PBX account caps. |
| LOCALE-009 — Approximate time windows | Validate preferred range wording and coverage with representative clinic callers. |
| LOCALE-013 — Persian spoken readback | Listen to representative deployed-provider audio for pronunciation and intelligibility; lexical fixture tests do not establish acoustic quality. |
| LOCALE-015 — Accessibility alternatives | Deploy and verify the authenticated carrier-to-gateway inbound bridge and real outbound deliveries. Perform physical-device and representative accessibility/usability testing. |
| BOOKING-001 — Authoritative calendar selection | Deploy a supplier adapter implementing the published Hamava calendar v1 contract and attest the actual tenant account identity. |
| BOOKING-011 — Unknown external write | Run the same timeout/recovery conformance suite against the contracted supplier, including real remote idempotency retention and lookup behavior. |
| BOOKING-018 — Disruption handling | Real staff must contact affected patients and verify arrangements. |
| BOOKING-022 — Service rule exceptions | Approve actual clinic eligibility and package rules. |
| BOOKING-024 — Calendar sync reconciliation | Validate the deployed supplier webhook authentication, cursor completeness and actual lag/conflict recovery. |
| MEDIA-001 — Transport contract | Run deployed SDK/carrier transfer and media quality conformance on supported devices. |
| MEDIA-013 — Call quotas and admission | Set actual supplier rates and upstream carrier/PBX account caps. |
| MESSAGING-005 — Receipt authentication | Test actual configured vendor receipts and account behavior using authorized non-sensitive messages. |
| MESSAGING-007 — Quiet hours | Validate operator-selected quiet hours and approved carrier behavior in clinic acceptance. |
| MESSAGING-011 — Attempt caps | Provision an approved gateway/carrier and prove duration, idempotency, receipt and failure behavior before enabling actual dialing. |
| MESSAGING-013 — Sensitive notice minimization | Review actual message templates, shared-phone preferences and live gateway voicemail suppression with clinic staff. |
| MESSAGING-014 — Follow-up cadence | Real staff qualifications and actual clinic clinical approval. |
| PAYMENT-001 — Published deposit policy | Actual clinic terms and consumer/payment obligations require authorized review. |
| PAYMENT-003 — Payment intent linkage | Real merchant authorization/ownership and gateway readiness remain unverified. |
| PAYMENT-005 — Server settlement verification | Live gateway account/API verification remains a launch gate. |
| CONSOLE-004 — Task atomic ownership | Named staff and measured pickup capacity. |
| BILLING-001 — Usage event ledger | Publish actual approved supplier rate versions and validate production reconciliation against authenticated receipts. |
| BILLING-002 — Correct call denominators | Connect and reconcile actual CDR/event inventory for carrier-wide denominator coverage. |
| BILLING-003 — Invoice reconciliation | Import and verify real vendor statements, contract rates, taxes and dispute receipts. |
| BILLING-005 — Cost budget enforcement | Validate real carrier billing quanta and independent PBX/provider account toll limits. |
| BILLING-006 — Economics sensitivity | Actual invoices, FX convention, staff costs and contract terms. |
| BILLING-008 — Baseline and uncertainty | Observed baseline/attendance/cost and defensible study design. |
| BILLING-009 — Deduplicated attribution | Collect matched, representative clinic cohorts and review episode attribution against actual calendar outcomes. |
| BILLING-010 — Staff workload accounting | Execute an actual time study with payroll/capacity evidence and independently verify any avoidable labor savings. |
| PRIVACY-001 — Purpose-specific consent | Obtain actual subject permissions and appropriate legal/clinical review for the intended deployment. |
| PRIVACY-004 — Retention scheduler | Execute actual retained-backup expiry/erasure and any legal hold review. |
| PRIVACY-005 — Subject export/correction/deletion | Authorized request and actual lawful-retention determination. |
| PRIVACY-007 — Text redaction | Review the clinic-specific governed term list and actual logging/export samples for the deployment. |
| PRIVACY-008 — Audio redaction separation | Qualified human audio/text privacy review and approved corpus rights. |
| PRIVACY-010 — Processor registry | Review actual provider contracts, storage/processing regions, deletion terms, credentials and approved fallback routes. |
| RESEARCH-001 — Eligibility manifest | Real eligible corpus and permission documents. |
| RESEARCH-002 — Track and acoustic metadata | Acquire separately authorized caller/agent recordings with actual role/rights provenance. |
| RESEARCH-003 — Segmentation quality | Perform native-speaker transcript, privacy and acoustic review on representative eligible captures. |
| RESEARCH-004 — PII review provenance | Qualified privacy reviewers and complete span decisions. |
| RESEARCH-005 — Teacher label QA | Provide an authorized representative corpus and actual independent teacher hypotheses with verified rights/region/model/license evidence. Have qualified, authorized reviewers perform and document the real listening, correction, privacy review and exclusions, then re-freeze and evaluate the revised corpus. Real corpus permission, selected teacher licenses/processor authorization and accountable independent human reviewers. |
| RESEARCH-010 — Workflow metrics | Collect representative paired predictions, authoritative business outcomes and measured stage boundaries. |
| RESEARCH-011 — Latency distributions | Representative actual latency data for any SLO. |
| RESEARCH-012 — Slice and uncertainty reports | Authorized representative labels and reviewed real audio. |
| RESEARCH-013 — Training experiment specification | Supply eligible reviewed data and licensed pinned weights, verify rollback artifact, approve hardware/budget, and execute the actual experiment. |
| PARTNER-001 — Calendar adapter contract | Build/contract the vendor-side adapter and execute the published conformance suite against its actual account, including update, hold expiry and revision conflict semantics. |
| PARTNER-004 — Provider/API exports | Publish an actual successor contract and partner migration notice before enabling a retirement entry. |
| OPERATIONS-001 — Redacted tracing | Verify deployed adapter event coverage and retention against an authorized complete call trace. |
| OPERATIONS-002 — Actionable alerts | Staff the real on-call rotation, execute an acknowledgment drill and connect actual carrier/security event sources. |
| OPERATIONS-003 — Backup automation | Install the actual scheduled encrypted backup job, verify offsite copy and retention, and perform an independent custodian/application recovery drill. |
| OPERATIONS-006 — Outage runbooks | Named operators and actual provisioned dependencies. |
| OPERATIONS-009 — Rollback and stop-ship | Actual release authority and staffed fallback execution. |
| BUSINESS-015 — Source verification discipline | Primary source refresh and qualified review before real claims/contracts. |
