# Running a reception team with Hamava

[فارسی](operations.fa.md) · [Documentation](README.md)

This is the day-to-day playbook for the people responsible for a clinic, not a description of backend classes. Its purpose is to keep work visible when a call, appointment, message or payment does not finish automatically.

## Decide who owns what

Before adding the first real patient, assign named people to these responsibilities. One person may cover more than one role at a small clinic, but none should be left implicit.

| Responsibility | Owner's decisions |
| --- | --- |
| Clinic owner | Organization identity, service catalog, operating hours, staff coverage and go-live |
| Reception lead | Appointment corrections, urgent queues, callbacks and daily handover |
| Technical operator | Deployment, integrations, access, monitoring, backups and incident coordination |
| Finance lead | Merchant ownership, deposit/refund policy and reconciliation of uncertain money |
| Privacy/clinical reviewers | Notices, processing purpose, data retention, approved scripts and escalation boundaries |

The application enforces role/tenant permissions; **the organization still decides who is allowed to exercise them**. Grant the smallest practical role and review membership changes promptly.

## Opening a clinic

1. **Create and identify the clinic.** Verify its name, public contact, timezone and authorized owner. Record who can be reached if the assistant cannot continue.
2. **Publish real services.** Add practitioner shifts, service durations, shared rooms/resources, buffers, holidays and booking horizon. Ask the reception lead to review the calendar as a whole rather than approving isolated fields.
3. **Agree on the words used with patients.** Check clinic identity, pronunciation, approved factual answers, processing notice and when the conversation must hand over to a person. A clinic policy in the UI is a statement the operator must stand behind.
4. **Add team members.** Sign in as each role or test its permissions; confirm that switching clinics changes the data scope and that staff cannot see another clinic's records by choosing a different identifier.
5. **Walk through one full booking.** Use a controlled test identity to check search, hold, confirmation, cancellation, reschedule, deposit terms if required, reminders and staff-task creation.
6. **Check each external link on its own.** For an external calendar, verify readback and collision handling. For SMS, check final delivery receipts. For payment, reconcile actual settlement and refund. For telephony, test a real audible staff bridge and a usable fallback.
7. **Rehearse failure and recovery.** Temporarily make a provider unavailable in a controlled test and check the visible state, callback route and support responsibility. Restore a backup to an isolated environment.
8. **Record acceptance.** The API provides an operational UAT review (`/api/v1/operations/uat`) and an approval route, but the evidence references must be checked by responsible humans. Revisit the review when clinic configuration changes.

Keep the clinic paused until the chosen operating mode is supported by the staff rota and integration checks. Start with a small supervised pilot; expand only after reviewing the resulting exceptions.

## A repeatable shift routine

| When | Check | Why |
| --- | --- | --- |
| Before opening | Today's calendar, closures, absent practitioners and shared resources | Prevent promising unavailable time |
| Before opening | `/ready`, service connection status, staff transfer targets and callback number | Know which routes work today |
| During shift | Active call/task queue, unclaimed requests and time-to-response | Give every unresolved request an owner |
| During shift | Pending calendar operations, notifications awaiting receipts and deposits awaiting reconciliation | Separate actual success from a request in flight |
| After a cancellation | Waitlist policy and offers with expiry and consent | Recover slots without contacting people who opted out |
| At close | Overdue tasks, disputed/unknown payments, failed messages and handoffs | Hand over exceptions with the next action and a named owner |
| Periodically | Restore drills, access review, retention/erasure jobs, provider pricing and service policy | Catch slow-moving operational risks |

Use the dashboard for an overview but make changes through the dedicated appointment, task, payment or policy flow. Do not bypass the scheduler with ad hoc database writes.

## Handling the exceptions people actually see

### “The patient says they booked, but the slot is empty”

Check the appointment ID and current authoritative calendar first. If the operation belongs to an external provider, find its recorded pending request and reconcile using the same remote identity. A timeout may have happened *after* the remote system committed the booking. Do not create a second independent appointment while the first result is unknown. Explain to the patient that the confirmation is being checked and give a callback path.

### “The SMS provider accepted the message, but nobody received it”

Inspect the message's attempt and final receipt state. Provider acceptance usually means the provider took the request, not that the handset received it. If the receipt is missing, leave delivery unconfirmed and use a permitted alternative route. A manual retry must respect the same patient purpose, opt-out and quiet-hours policy.

### “The payment page returned, but the deposit is still pending”

The payment intent, redirect callback and settlement record are different facts. Verify the merchant account, amount, intent identity and trusted callback/statement result. Do not mark a deposit paid or trigger a refund from an unauthenticated browser return. Escalate discrepancies to the finance lead with non-sensitive references.

### “The phone transfer says accepted, but the patient reached nobody”

Distinguish transfer request, staff screening/DTMF acceptance and observed bridge membership. Check the PBX event sequence and whether there was intelligible two-way audio. If not, treat it as a failed transfer and initiate the approved callback/staff queue. A ringing or answered staff extension alone does not prove the patient was connected.

### “The service is up, but appointments fail”

Check application `/health`, dependency `/ready`, current clinic policy, provider observations, appointment conflicts and background queue separately. A healthy database does not prove that a provider is reachable or a clinic has published operating hours. Use the request ID and sanitized logs to locate the failing stage, then choose a safe recovery rather than repeatedly submitting the same action.

## Incidents and privacy requests

For an urgent patient-safety concern, route to the clinic's approved human process; do not rely on the assistant as a medical decision-maker. For a wrong-recipient or wrong-tenant disclosure, restrict access, notify the accountable privacy reviewer and preserve minimal, safe evidence before changing records. Deletion/withdrawal requests require checking distinct purposes, necessary appointment records, outstanding processor obligations and backup evidence rather than simply erasing a browser view.

A useful incident entry contains: local and UTC times, clinic, impact, owner, what the system showed, request/correlation identifiers, what was verified externally, immediate mitigation, patient communication, follow-up and a regression test. Keep secrets and identifiable patient content out of public issues and CI logs.

## What a launch decision needs

The checklist is an evidence record, not a score automatically computed by the software:

| Area | Acceptance example |
| --- | --- |
| Scheduling | Conflict and retry tests on the chosen calendar authority; named owner signs off |
| Communications | Actual SMS delivery, opt-out behavior and staffed callback tested |
| Finance | Merchant ownership, final payment settlement, refund/dispute path verified |
| Telephony | Carrier audio, staff acceptance, declined transfer and fallback tested |
| Privacy/clinical | Real notice, permitted processors, retention, urgent-language handoff reviewed |
| Operations | Shift rota, incident contact, restored backup and monitoring demonstrated |
| Native distribution | Publisher signature, upgrade/logout and target-device behavior checked where relevant |

The included `scripts/launch_readiness.py` organizes references to that evidence, but it does not make the decision for the organization. Record what was tested, by whom, against which environment and on what date. Keep the scope of a pilot narrower than the scope of unverified integrations.

For deployment and disaster recovery use [Deployment](deployment.md). The [Product guide](product.md) explains why these state distinctions matter to a patient.
