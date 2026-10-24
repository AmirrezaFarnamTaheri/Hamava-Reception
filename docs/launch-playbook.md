# Persian Voice Receptionist — launch and operating playbook

**Edition:** 23 October 2026. **Audience:** founders, clinic managers, reception coordinators, technical operators, and the clinical/privacy advisers responsible for a deployment.

This playbook supplies the operational work products needed to turn the application into a service. Worksheets are deliberately unfilled where the necessary real-world evidence has not been supplied. A form, local simulation, or sample configuration is not evidence of a signed agreement, carrier connection, clinical approval, payment settlement, customer pilot, or trained model.

The revised blueprint contains the complete product specification; `requirements.json` is the item-level execution register. Use the verification report for the exact software tested. This playbook defines what a real operator must demonstrate before changing the public operating mode.

## 1. Operating modes and promotion rules

| Mode | Permitted activity | Required evidence | Public wording |
|---|---|---|---|
| Local demonstration | Fictional clinic, synthetic patients, controlled calendar; simulated services clearly labelled. | Local software checks, safe seed data, reset procedure. | «نسخهٔ نمایشی؛ اطلاعات و پیامک‌های این محیط آزمایشی‌اند.» |
| Connected sandbox | Actual provider sandbox or test number with authorized participants; no unapproved patient collection. | Account eligibility, scoped credentials, test endpoints, data-purpose record. | «آزمایش با هماهنگی مجموعه؛ سرویس عمومی فعال نیست.» |
| Supervised pilot | One approved clinic, after-hours/overflow, capped traffic, staff review for uncertain writes. | Clinic sign-off, real carrier/device tests, privacy/clinical review, staffed fallback, monitoring. | Describe actual coverage hours and what is confirmed versus awaiting staff. |
| Paid single location | Agreed production hours/capacity and supported workflows only. | Pilot outcome and renewal decision; delivery/settlement/restore drills; support ownership. | Measured commitments, explicit minute/SMS/channel limits. |
| Shared building | Independent clinic scopes, pooled usage and authorized coordinator workflow. | Per-clinic authority, routing tests, staffing capacity and confidentiality review. | Identify each participating clinic and human coverage. |
| Partner/research product | Contracted channels/adapters or licensed voice experiments. | Separate access, rights, quality and commercial gates. | No implied partner endorsement or protocol/model superiority. |

An unmet gate restricts the affected production behavior; it does not prevent building and exercising safe local software. For example, absence of a SIP contract blocks live PSTN validation, but not AudioSocket parser tests, configuration preparation, or a controlled browser booking demonstration.

## 2. Responsibility worksheet

Assign one person and one backup for each responsibility. A role is not staffed merely because its name exists in the application.

| Responsibility | Named owner | Backup | Authority and evidence required |
|---|---|---|---|
| Product and clinic relationship | To assign | To assign | Approves scope, pilot objectives and customer communication. |
| Technical system and releases | Farnam if accepted | To assign | Owns tests, integration capabilities, deployment and rollback. |
| Commercial discovery and sales | Ali if accepted | To assign | Owns prospective buyers, contract/pricing negotiation and renewal evidence. |
| Clinic appointment policy | Clinic appointee | To assign | Publishes durations, availability, cancellation and approved administrative facts. |
| Clinical escalation content | Qualified clinic reviewer | To assign | Approves urgent-case and post-care wording; handles clinical exceptions. |
| Privacy and legal review | Qualified adviser | To assign | Reviews actual processing, notices, contracts, retention and rights. |
| Human reception coverage | Clinic/coordinator lead | To assign | Maintains shift roster, pickup SLA and alternative route. |
| Carrier/PBX operations | Authorized telecom owner | To assign | Controls DID/forwarding, carrier contact, trunks and fallback. |
| Finance and payments | Merchant/finance owner | To assign | Reconciles settlements, refunds, units, taxes and invoice disputes. |
| On-call incident response | To assign | To assign | May pause automation, revoke tokens and restore human-primary routing. |
| Research data and models | To assign if enabled | To assign | Signs eligibility, annotation, licensing and holdout evidence. |

**Decision log template:** decision ID; date; owner; affected tenants; alternatives; evidence; choice; reversible steps; rollout gate; review date. Record a new supplier, model, voice, policy, price or data purpose as a material decision. An inherited suggestion is not an approved supplier.

## 3. Buyer discovery and site selection

### 3.1 Interview worksheet

Record actual numbers separately from estimates. Accept anonymized aggregate logs where possible; discovery does not require copying patient audio or health records.

| Topic | Questions and fields |
|---|---|
| Clinic identity | Legal operator, segment, sites, decision-maker, purchasing authority, existing receptionist and clinic scheduler. |
| Call demand | Attempts by hour/day, answered, busy/rejected, no answer, abandoned, after-hours share, campaigns and holidays. |
| Request mix | Booking, existing appointment, cancellation, hours/location, insurance/payment, complaints, wrong numbers, urgent/clinical requests. |
| Appointment supply | Providers, available capacity, first/follow-up service mix, durations, equipment/rooms, cancellation and no-show rate. |
| Economics | Contribution per additional kept visit, real spare capacity, recoverable staff time, supervision/correction burden. |
| Appointment authority | Actual software/paper book, authorized owner, supported write API, current staff/website writes, conflict process. |
| Telecom | DID ownership, carrier, PBX/version, forwarding rules, channels, codecs, transfer and fallback options. |
| Staff workflow | When a person is available, how a caller transfers, private subject handling, correction authority, queue tolerance. |
| Data purposes | Live inference, recording, QA, reminders, marketing, training, external suppliers, retention and patient choices. |
| Customer acceptance | Which errors are unacceptable, agreed pilot indicators, willingness to pay, decision date and signer. |

Suggested discovery sample from the blueprint: five dental/aesthetic clinics, five salons or busy specialty offices, and two building coordinators/IT leads. This is a proposed interview plan; do not report it as completed until interviews exist.

### 3.2 Site scorecard

Score 0–5 with evidence, not impressions. High complexity/sensitivity scores should mean **readiness to handle the complexity**, not greater expected revenue.

| Criterion | Weight | Evidence for a strong score |
|---|---:|---|
| Observable missed eligible demand | 15% | Logs show booking/administrative demand during uncovered windows. |
| Spare appointment capacity | 15% | Additional callers can obtain genuine slots without displacing other channels. |
| Contribution per kept appointment | 10% | Owner can provide a defensible contribution estimate. |
| Calendar integration readiness | 15% | Supported sandbox/atomic writes or explicit first-party calendar adoption. |
| Phone/forwarding control | 10% | Owner can test reversible busy/no-answer routing and fallback. |
| Staff participation | 10% | Named staff will review outcomes and accept escalations. |
| Management commitment | 10% | Authorized decision-maker agrees scope, time and acceptance criteria. |
| Privacy/clinical operational readiness | 10% | Clear policies, advisers, minimum data and approved wording. |
| Willingness to pay | 5% | Concrete budget or conditional paid offer rather than demo enthusiasm. |

`Weighted score = sum(weight × score / 5)`. Keep evidence and uncertainty next to each score. A high total cannot override a failed booking-integrity, clinic-authority or privacy gate. Start with two or three feasible sites and one primary pilot; the source's later building strategy remains an expansion gate.

## 4. Supplier evaluation and integration evidence

### 4.1 Registry fields

For each supplier record: supplier/category; product/model/version; account owner; official documentation URL and retrieval date; intended purposes; operating region; data retention/training terms; commercial eligibility; license; authentication; sandbox/production endpoints; timeout/rate/concurrency limits; idempotency/receipt semantics; price unit and currency; tax/minimum fees; support contact; outage alternative; tested capabilities; failed tests; approval owner; expiry/review date.

Use statuses `candidate`, `documentation_reviewed`, `sandbox_verified`, `contracted`, `production_verified`, `suspended`. These states are factual; a successful connector import is not `production_verified`.

### 4.2 Carrier/PBX request worksheet

Prepare the following questions for the telecom owner or carrier; no outreach is sent automatically by the implementation:

1. Who legally controls the DID, and is busy/no-answer forwarding allowed? What are its billing consequences?
2. Is the trunk REGISTER-based or IP-peered? Which fixed IPs/SBCs and failover ranges apply?
3. Which signaling and RTP ports, codecs, packetization and DTMF methods are supported?
4. Are TLS/SRTP available? What ACLs, authentication and outbound destination restrictions are required?
5. How many simultaneous inbound/outbound channels are provisioned? What happens at capacity?
6. Which caller-ID/header semantics apply? Can hidden caller IDs and different callback numbers be supported?
7. Does SIP REFER work on this account? If not, which bridge/queue transfer method is supported?
8. How are ring, busy, no answer, transfer failure and upstream failure handled? Can the original human route remain available?
9. Where must media terminate, what recording/notice rules apply to the service, and which hosting networks are permitted?
10. What are setup, number, channel, inbound/outbound minute, forwarding, tax and billing-pulse charges?
11. What support hours, escalation contacts, incident response and service commitments are contractual?
12. What test number, packet trace and written interconnect specification can be provided?

Candidate names retained for evaluation include Asiatech, Shatel, Nexfon, TCI, Simutel and existing Issabel/Asterisk providers. Listing a name is not approval or evidence of current availability.

### 4.3 AI and hosting worksheet

Run every candidate against the same permissioned test corpus and script. Ask for explicit support for the selected Persian model, streaming partial/final behavior, keyterms, silence handling, output sample rate, tool schema, interruption and session teardown. Record billed audio/tokens/session seconds, retry costs and maximum concurrency. Verify account/service geography and processing rights; never route around an unavailable region by assumption.

For local models, record hardware, batch size, real-time factor, warm/cold latency, memory, concurrency, model/voice licenses, weights provenance and maintenance owner. An offline model is not automatically cheaper after GPU, on-call and quality costs. For hosting, test fixed IP/UDP/TCP, carrier reachability, NIC behavior, storage/backup, key custody and recovery; geographic proximity alone does not prove call quality.

### 4.4 Calendar integration conformance worksheet

| Capability | Test and expected evidence |
|---|---|
| Authority and permissions | Clinic authorization and token scope prove which patient/appointment actions are permitted. |
| List/get | Provider/service/timezone/status fields and freshness verified against source UI/API. |
| Holds | Ownership, TTL, extension/release and expiry semantics measured; unsupported means unsupported. |
| Create | Atomic/conditional resource exclusion, idempotency fingerprint and durable external ID. |
| Read-back | Returned state matches patient/provider/service/interval/source after the write. |
| Cancel/move | Original booking retained on failed replacement; financial and notice side effects known. |
| Unknown write | Drop response after submit; reconcile without a duplicate. |
| Concurrent writers | Website/secretary/voice races either excluded atomically or sent to explicit review. |
| Events | Authenticate webhook or poll with revision/lag tracking; handle replay and out-of-order delivery. |
| Recovery | 429/500/timeouts/expired token/permission loss cannot create a phantom confirmation. |

Paziresh24, Doctoreto and other named platforms need their own signed access and conformance run. A public repository does not supply private patient-write permission. Insurance/e-prescription portals are a separate integration and are outside a generic scheduling token.

### 4.5 SMS and payment conformance worksheet

SMS: approved template/sender; contact purpose; invalid/blocked destinations; provider-accepted versus delivered; receipt authentication or trusted polling; deduplication behavior; ambiguous timeout; rate limits; opt-out; quiet hours; pricing and escalation contact.

Payments: merchant ownership; sandbox/production distinction; exact currency and Toman/Rial conversion; server-native settlement verification; signature where supported; replay; forged callback; amount/merchant mismatch; late settlement after hold expiry; partial/full refund; dispute/chargeback; reconciliation reports. A successful browser return or HTTP request is never settlement evidence.

## 5. Clinic onboarding acceptance record

Use one record per independent clinic, even when several occupy a building.

| Field group | Required content | Sign-off |
|---|---|---|
| Identity and authority | Legal operator, locations, clinic number, building membership, responsible manager. | Clinic owner |
| Calendar | One source of truth, credential scope, supported capabilities, time horizon and conflict process. | Scheduler + technical owner |
| Providers/services | Actual provider IDs, durations/buffers, rooms/equipment, fees, eligibility and approved preparation. | Clinic policy owner |
| Availability | Working hours, holidays, breaks, absence, lead times, cancellations and late arrival. | Scheduler |
| Knowledge | Source, reviewer, effective/expiry date for address, parking, insurance, prices and preparation. | Clinic policy owner |
| Identity | Minimal patient fields, verification needed for reading/changing existing records, family booking rules. | Clinic + privacy reviewer |
| Human route | Queue/phone, hours, accept/decline/callback behavior, timeout, backup and urgent route. | Reception lead |
| Messaging | Approved template, destination confirmation, preferences, reminder offsets, quiet hours and caps. | Clinic + communications owner |
| Payment | Optional deposit terms, merchant, units, expiry, refunds and disputes. | Finance owner |
| Privacy | Processing map, recording setting, consent purposes, retention, rights request route and processors. | Privacy owner |
| Limits | Concurrent calls, max duration, usage budget, warning/hard cap and fallback. | Owner + technical lead |
| Test evidence | Positive booking, ambiguous date, double-booking race, cancel/move, failed notice, human request and outage. | Clinic + QA |

Publish the configuration with a version and approval time. Preserve a rollback target. A draft or stale price/insurance entry should produce a staff response, not an improvised answer. Read the final Persian greeting and confirmation aloud before enabling caller traffic.

## 6. Proposed pilot agreement worksheet

This is an operational term sheet to review with the parties and their advisers; it is not a completed legal contract.

**Parties and purpose:** named clinic operator and service operator; catch agreed unanswered/after-hours administrative demand; complete verified bookings in the designated calendar; preserve staff control.

**Pilot dates and coverage:** start/end, daily hours, holidays, ring/no-answer threshold, participating providers, permitted services, maximum concurrent channels and total traffic cap. Proposed duration may be 14 days; choose by actual volume and staff availability.

**Supported actions:** approved FAQ, appointment list/hold/create/move/cancel, notice, human queue/callback and any explicitly activated reminder/deposit workflow. List unsupported or supervised operations visibly. Clinical diagnosis/prescription is excluded.

**Responsibilities:** clinic maintains availability and approved facts; service operator maintains code/integrations/observability; receptionist handles assigned exceptions; merchant owns settlement/refund decisions; named parties handle privacy and incidents.

**Data schedule:** purposes, identifiers, processors/regions, recording status, notices/choices, retention, staff access, rights requests, withdrawal, security incidents and deletion/backup boundaries. Training is a separate opt-in decision and is not a condition of receiving reception service.

**Measurement:** agreed baseline, attempt/answer/eligible definitions, verified bookings and kept visits, staff review/correction time, caller complaints, transfer outcomes, per-call costs and uncertainty. Agree how repeat callers, displaced demand and waitlist replacements are treated.

**Money:** setup; platform; included minutes; unit/rounding; overages; SMS/outbound; human service; taxes; currency; refunds/credits; caps; invoice evidence. Do not use “unlimited” with finite channels or unpriced messages.

**Stop/rollback:** named people may restore human-primary routing; triggers include false confirmation, cross-tenant disclosure, unverified settlement, unconsented audio/training, unsafe medical behavior, or failed human/emergency alternative. Record how already confirmed appointments and pending payments/messages are reconciled.

**End decision:** continue, modify, or stop; customer feedback; independently verified value; willingness-to-pay; unresolved issues; signed paid scope if renewed. No automatic promotion to 24/7 autonomous operation.

## 7. Pilot measurement workbook

### 7.1 Daily record

Capture one row per tenant/date/route/time band, using authorized source facts:

`tenant_id, local_date, route, staffed_hours, offered_attempts, busy_rejected, connected, audible_answered, eligible_requests, confirmed_new, confirmed_rescheduled, cancellations, staff_reviewed, pending_review, waitlist_filled, kept_from_prior_cohort, no_show_from_prior_cohort, handoff_requested, handoff_connected, callback_completed, queue_abandoned, call_seconds, provider_cost, sms_cost, telecom_cost, human_minutes, corrections, severe_incidents, complaints, data_completeness`.

Never join patient details into broad commercial reports unnecessarily. Preserve denominators and observation lag: tomorrow's appointment has not yet had an opportunity to be kept.

### 7.2 Metric definitions

| Metric | Definition | Common error to prevent |
|---|---|---|
| Audible answer rate | Calls with intelligible greeting / attempts within stated boundary. | Counting SIP 200 or connected socket as a good answer. |
| Eligible task completion | Verified authorized task outcomes / eligible administrative requests. | Counting any polite conversation as completion. |
| Booking conversion | Authoritatively confirmed appointments / eligible booking inquiries. | Counting verbal intent or held slots as confirmed. |
| Kept rate | Clinic-confirmed attended visits / matured confirmed cohort. | Counting future or canceled appointments in the same denominator. |
| Human fulfillment | Actually connected/finished human handling and documented alternatives, reported separately. | Equating task creation with a human pickup. |
| Review burden | Staff handling + correction minutes / relevant call cohort. | Reporting gross receptionist time saved without supervision. |
| False confirmation | Spoken/displayed confirmed outcomes not matched by calendar truth. | Hiding severe errors inside a high average task score. |
| Incremental kept effect | Difference relative to agreed baseline/control, adjusted for supply and displacement. | Valuing every missed call as a lost new patient. |
| Unit cost | All chargeable carrier/provider/SMS/media/human/support costs / stated unit. | Ignoring silence, failures, channel fees and FX. |

### 7.3 Experiment design

Choose matched pre-pilot hours, parallel control routes, or an appropriately designed alternating time/cluster comparison. Record holidays, promotions, seasonality, appointment capacity and policy changes. Avoid switching conditions mid-call or removing a required human route. Separate after-hours recovery from improving routine answered calls. Use confidence intervals only where the sample and method support them; report missing data openly. A small pilot may establish operational feasibility while leaving causal ROI uncertain.

### 7.4 Evidence gates

| Gate | Pass evidence | Failure action |
|---|---|---|
| Integrity | No unresolved false confirmation, wrong clinic/provider or duplicate reservation in required UAT. | Pause autonomous mutation; correct and replay scenarios. |
| Confidentiality | Tenant adversarial tests and real staff scope review pass. | Contain affected surface; investigate access and disclosure. |
| Human route | Real pickup and failed-transfer alternatives exercised on staffed shifts. | Retain human-primary or callback-only mode. |
| Audio/client quality | Target devices/carriers and blind Persian number/date evaluation pass agreed baseline. | Narrow supported route or change provider with approval. |
| Notifications/settlement | Receipts, replay, late payment and refund tests reconcile. | Disable affected paid/outbound workflow. |
| Economics | Actual cost and staff load fit agreed offer under stress scenarios. | Reprice, restrict scope or decline expansion. |
| Customer value | Owners/staff confirm observed benefit and paid renewal willingness. | Iterate or stop; do not claim product-market fit. |

## 8. Human queue and staffing operations

### 8.1 Shift checklist

At shift start: verify correct clinic membership; test queue/phone; confirm overflow and emergency route; inspect active cases and pending reconciliation; check today’s provider absence/holiday changes; verify notification backlog; acknowledge service degradation. At handover: assign unresolved cases with owner, deadline and verified state; confirm who covers next; avoid pasting patient transcripts into unapproved channels.

### 8.2 Handoff card and handling

The handoff card contains clinic/provider, masked contact and verification level, caller purpose, minimal operational context, policy version, last definitive booking/payment state, pending operation, reason, requested time and elapsed queue time. Staff may accept, redirect within authorized scope, request callback, resolve or reopen. Accepting a task alone does not mean the phone caller is connected.

When transfer is supported, ring/accept/bridge events drive status and the AI stops speaking once a human takes over. If busy, rejected or unanswered, the caller hears the actual alternative. Ask permission for callback capture and confirm the intended contact. Never promise an immediate callback when no coverage exists. Sensitive clinical context stays with authorized staff.

### 8.3 Staffing calculation

Start with `escalations/hour = inbound calls/hour × measured handoff rate` and `handling workload minutes/hour = escalations/hour × mean handling minutes`. A rough headcount floor is `workload / (60 × target occupancy × (1 - shrinkage))`; it is not a service-level guarantee. Simulate bursty arrivals, handling-time tails, queue abandonment, callbacks, holidays and simultaneous clinics. Erlang-style calculations apply only when their arrival/service assumptions are defensible.

**Illustrative example:** 40 calls/hour × 20% escalation × 6 minutes produces 48 handling minutes/hour before shrinkage. At 75% target occupancy and 20% shrinkage the simple load floor is 48 / 36 ≈ 1.33 staff, so one person is insufficient even before queue-tail and coverage analysis. These are hypothetical inputs; no “one operator per 40 clinics” promise follows.

Keep independent clinic authorization in the roster. A single shared coordinator cannot view every patient's details merely because staffing is pooled. Coverage must explicitly address nights, holidays, absence, breaks and language needs.

## 9. Incident and recovery runbooks

### 9.1 Severity and first response

| Severity | Examples | Immediate action |
|---|---|---|
| Critical | False confirmed booking; cross-tenant sensitive access; fraudulent settlement accepted; unapproved recording/training; unsafe clinical advice; toll fraud. | Pause affected autonomous/outbound path, restore permitted human route, assign incident owner and preserve minimal evidence. |
| High | Carrier/media outage; unknown calendar write; substantial queue failure; spend cap breach; repeated wrong-recipient risk. | Degrade to honest pending/human/callback behavior; reconcile durable operations; alert responsible operator. |
| Standard | Individual undelivered SMS; unsupported date phrase; isolated microphone denial. | Correct user-facing state, provide alternative, queue appropriate staff/technical review. |

Severity depends on actual impact; the table is a starting point. Do not broadcast patient details to diagnose a fault. Legal/customer notices follow the actual obligations assessed by the responsible advisers, not an invented universal deadline.

### 9.2 Unknown booking write

1. Stop blind retries and prevent “confirmed” speech.
2. Record tenant, operation/idempotency key, intended resource interval and source request reference.
3. Query source by reference or supported reconciliation operation.
4. If a matching confirmed appointment exists, link it and create the one logical notice.
5. If definitively absent, retry only under supported idempotency/conditional semantics.
6. If still unknown, create scoped staff review and tell the caller confirmation is pending.
7. Audit the final outcome and include the response-loss scenario in regression testing.

### 9.3 Wrong-tenant or wrong-recipient exposure

Pause the affected API/export/notification route; revoke exposed access where needed; preserve correlation IDs and minimal event metadata; restrict evidence access; identify tenants/subjects and duration; obtain privacy/clinical/legal assessment; correct recipient/scope mapping; test adversarial cases; resume only after the accountable owner accepts evidence. Do not erase necessary incident evidence while deleting unauthorized copies through the proper process.

### 9.4 SMS accepted but undelivered

Keep the booking truth unchanged. Display accepted/unknown/failed accurately; provide reference through a permitted channel; inspect provider receipt/template/destination; reconcile ambiguous send before retry; honor consent, quiet hours and caps; route persistent failure to staff. Never rebook the appointment to “fix” the text message.

### 9.5 Payment arrives after expiry

Verify settlement server-side and exact amount/currency/merchant; inspect current hold/slot ownership; do not reclaim capacity assigned to another patient. Create finance/scheduling review for a new available slot with caller consent or an approved refund. Record the settlement and refund separately. Replayed callbacks return the existing disposition.

### 9.6 Carrier, model or media outage

Use the documented PBX fallback or authorized callback route. End orphan provider sessions and billable timers. Trip circuit breakers. Do not route audio to an unapproved foreign/domestic provider merely to keep the demo running. Confirm which calls were actually answered and which were rejected. Test restored media in a controlled call before widening traffic.

### 9.7 Urgent medical-language incident

Stop ordinary booking dialogue; use only the clinic-approved urgent-help script and actual human/emergency alternative; do not diagnose, reassure about severity or offer treatment. Preserve the minimal permitted context for clinical review. If the script or routing fails, pause that clinical deployment path until corrected and tested.

### 9.8 Recovery and postmortem template

Incident ID, start/detection/containment/recovery times, affected capabilities and tenants, caller-safe behavior, confirmed versus uncertain operations, data exposure assessment, root cause, contributing conditions, exact corrective changes, verification evidence, owner/date for remaining actions and communication record. Avoid blaming a model where the application failed to validate authority or calendar truth.

## 10. Deployment and disaster-recovery acceptance

Before a deployment: confirm intended environment; immutable code/dependency versions; backup completed; migrations reviewed; secrets and provider accounts assigned; origin/TLS/network rules applied; media ports/ACLs documented; worker concurrency/leases configured; human fallback tested; alert recipient on duty; rollback artifact and thresholds known.

Restore drill record: backup ID/hash/time; encryption/key access; isolated target; restore command and result; schema version; appointment/hold/outbox/payment/consent counts; sample invariant checks; pending jobs safely re-leased; no production SMS/charges emitted from restored test environment; measured recovery time and data-loss window; gaps and owner. A backup command returning zero is not proof of a successful recovery.

Apply least needed networking: public HTTPS for intended browser/API, carrier-approved SIP/RTP only, private database/Redis, authenticated internal media/control endpoints. Do not publish example real SBC credentials, wide unrestricted UDP ranges or unauthenticated debug endpoints. Do not claim TLS/SRTP where the chosen carrier lacks it; document the actual boundary and compensating controls.

For LiveKit, test both signaling and actual bidirectional audio from each deployed client/worker network. Record the configured HTTP(S) proxy, DNS, ICE/TURN and firewall paths. A local native RTC check in this workspace required launching the loopback test process without inherited `HTTP_PROXY`/`HTTPS_PROXY`; `NO_PROXY` alone did not establish that connection. Treat this as environment-specific evidence, not a universal SDK guarantee. Configure an approved direct or proxy route in the deployment environment; the application does not silently override proxy policy. A successful room API request alone does not prove usable media or a human handoff.

## 11. Pricing and economics worksheet

### 11.1 Inputs

| Input family | Explicit variables |
|---|---|
| Demand | Attempts, answered/eligible share, call durations including tails and billed silence, repeat callers, peak channels. |
| Outcomes | Verified bookings, matured kept rate, incremental baseline estimate, displacement, waitlist replacement, refunds. |
| AI | Actual STT audio, model input/output tokens, TTS output audio, session fees, retries and cacheable share. |
| Telecom/media | DID/trunk/channel fees, inbound/outbound/forwarding pulses, TURN/egress, compute/storage/backups. |
| Human/operations | Handoff volume/duration, staffed hours, shrinkage, on-call, QA, support, correction and onboarding. |
| Messaging/payment | Approved messages, receipts, retries, outbound reminders, settlement/refund/dispute fees. |
| Currency/contract | USD and local rates, Toman/Rial unit, FX scenarios, taxes, partner share, included pack/overage. |

`Fully loaded variable call cost = carrier + STT + model + TTS + media + SMS/payment + attributable human/support`. Add allocated fixed infrastructure, channel fees and support coverage when assessing customer contribution and pricing. TTS caching discounts only the cached eligible TTS share, not the whole stack.

`Incremental clinic contribution = incremental kept visits × contribution per kept visit + directly observed avoidable staff value - incremental supervision/rework/overhead`.

`Customer ROI = (incremental clinic contribution - total service fee) / total service fee`. Missing or zero fee inputs need explicit handling. Product gross margin and customer ROI are separate.

### 11.2 Stress scenarios

Run base, high FX, longer calls, elevated handoff, provider failover, low attendance, low incremental demand, heavy SMS, peak channel congestion and double support workload. Record which limits trigger intervention. Low per-minute model spend does not justify a fixed margin promise.

### 11.3 Offer structure

Specify setup, platform per location/provider, monthly included conversation minutes, rounding/overage, SMS and outbound, managed-human coverage, limits, tax/unit, credits and dispute procedure. For buildings, describe pooled allowance and allocation to participating clinics. Any performance fee requires an accepted attribution method. The source's 3.5/7.9/18M packages, 1.9/3.9M hypotheses, 3.5–5M per doctor and 70/30 partner split remain examples until cost and parties validate them.

## 12. Research and data release gates

### 12.1 Per-sample admission record

Record dataset/sample ID; source hash; tenant/speaker pseudonymous group; collection date; recording permission; distinct training purpose; clinic/subject rights evidence; allowed processors/regions; license; retention/withdrawal condition; codec/sample rate/channels; segment start/end; caller/agent track; transcript provenance; audio/text redaction evidence; human privacy review; overlap/noise flags; annotation agreement; split; dataset version; reviewer.

Reject a sample before copying into research storage when rights or required metadata are missing. Public availability on Hugging Face/YouTube is not permission to train, distribute or sell. Common Voice, ManaTTS, Fleurs/Persian and named community corpora are evaluation leads whose licenses and provenance must be inspected individually.

### 12.2 Dataset freeze checklist

Eligibility complete; no expired/withdrawn sample; exact and near-duplicate assessment; speaker/tenant-disjoint split as required; independent held-out tests; both transcript and audio PII treatment; metadata minimization; documented annotator disagreement; immutable manifest/hash; removal/tombstone process; access policy; rights review. Keep raw narrowband provenance; resampling 8 kHz to 16 kHz does not recreate lost frequencies.

### 12.3 Experiment card

Experiment ID; research question; baseline model; candidate architecture/LoRA/PEFT; model/code/data version and license; normalization; hardware/budget; reproducible command; train/validation/test partition; hyperparameters; WER/CER; exact digits/dates/names; false confirmations/task completion; audio and workflow latency; cost/concurrency; slice sample counts and uncertainty; native-review findings; non-regression; rollback; release owner.

Training must actually run to claim a trained artifact. Dataset hours alone do not demonstrate superiority. Avoid using a held-out set repeatedly to choose thresholds without a new final test set. Do not infer protected identity attributes to fill benchmark slices. Do not advertise `/v1/realtime` compatibility without an event/auth/tool/error/client conformance suite.

### 12.4 Withdrawal and model-impact record

A withdrawal creates a tombstone, stops queued collection/training, removes eligible files/manifests under applicable retention, and records backup expiry. Assess already shared datasets and trained checkpoints under the rights agreement. Deleting source audio is not proof that a trained model has forgotten it. Any unlearning/retraining claim needs its own method and validation.

## 13. Persian operational templates

These are editable administrative drafts. The clinic must approve actual names, policies, contact routes and any clinical content before live use.

**Greeting:** «سلام، شما با دستیار هوشمند پذیرش [نام مجموعه] صحبت می‌کنید. برای نوبت یا اطلاعات مجموعه کمکتون می‌کنم. هر زمان بخواید می‌تونید درخواست صحبت با پذیرش بدید.»

**Unambiguous readback:** «برای [روز و تاریخ شمسی برگشتی از سامانه] ساعت [زمان]، خدمت [خدمت تأییدشده] نزد [پزشک] ثبت کنم؟»

**Confirmed appointment:** «نوبت شما ثبت و تأیید شد. کد پیگیری [مرجع] است.» Add SMS status only as actually known: queued, sent, delivered or failed.

**Pending source write:** «الان نمی‌تونم ثبت قطعی نوبت رو تأیید کنم. درخواستتون برای بررسی پذیرش ثبت شد؛ تا تأیید نهایی، نوبت قطعی نیست.» Use only if a review task really exists.

**SMS delay:** «نوبت شما ثبت شده، ولی تأیید تحویل پیامک هنوز نرسیده. کد پیگیری [مرجع] است.»

**Human queue:** «درخواست صحبت با پذیرش ثبت شد. [وضعیت واقعی صف یا ساعت پاسخ‌گویی].» Never say a person is connected before actual pickup.

**Callback choice:** «اگر مایل باشید، شمارهٔ تماس‌تون رو برای پیگیری پذیرش ثبت می‌کنم. با کدوم شماره تماس بگیرند؟» Verify the contact under the configured policy.

**Recording choice:** «[بیان کوتاه و تأییدشدهٔ هدف ضبط، مدت نگهداری و راه انتخاب].» Do not use a generic notice as blanket training permission.

**Training choice:** «استفاده از نمونهٔ مجاز تماس برای بهبود مدل، جدا از دریافت خدمات پذیرش و اختیاری است. [شرح دقیق دامنه و روش لغو رضایت].» Activate only with the actual approved policy.

**Medical boundary:** «من برای هماهنگی نوبت و اطلاعات اداری کمک می‌کنم و نمی‌تونم دربارهٔ تشخیص یا درمان نظر بدم. [راه واقعی و تأییدشدهٔ تماس با مسئول مربوط].» Urgent wording and emergency numbers require local clinical approval.

**Short sales copy:** «تماس‌های زمان شلوغی یا خارج از ساعت کاری را به دستیار پذیرش بسپارید. نوبت‌ها بر اساس تقویم واقعی ثبت می‌شوند، وضعیت تأییدیه روشن است و موارد پیچیده به پذیرش ارجاع می‌شود. شروع با یک دورهٔ محدود و قابل‌اندازه‌گیری است؛ هزینه، حدود سرویس و شیوهٔ استفاده از داده از ابتدا مشخص می‌شود.»

## 14. Final release record

Release/version; date; environment; participating tenants; supported channels/providers; code/test evidence; actual carrier/browser UAT; approved policy/clinical/privacy versions; active configuration; known limits; costs/caps; staffed roster; backup/restore evidence; open incidents; rollback owner; external gaps; go/no-go decision and signer.

**Required honest statement:** “This release is verified for [exact scope] in [environment]. The following external gates remain unverified: [items].” Replace those fields with evidence. Do not replace them with “all phases complete” until every applicable software and real-world acceptance item has actually been satisfied.
