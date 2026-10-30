# Operations and external acceptance

[فارسی](operations.fa.md) | [Documentation](README.md)

## Roles and controlled promotion

Assign named technical, reception, clinical-script, privacy, billing and incident owners before connecting real accounts. The deployment states are **demo → connected sandbox → supervised pilot → production**. Promotion is a decision based on independent evidence, never a Boolean inferred from local source tests or an operator-uploaded file. Keep reception closed until clinic configuration, staff escalation and service dependencies have been reviewed.

## Onboarding checklist

1. Verify the real clinic identity, lawful operator, current services, practitioners, hours, capacity, holiday and closure rules; publish policy revisions with accountable approvers.
2. Verify tenant membership, role scope, authenticated sessions and clinic switching, including an unauthorized-access test.
3. Rehearse hold/booking, duplicate request, reschedule, cancellation, waitlist and deposit with controlled sandbox data; inspect calendar read-back and financial reconciliation.
4. Independently test provider behavior: SMS delivery receipt vs accepted request, payment final settlement vs initiation, calendar authority vs attempted write and connected staffed bridge vs call attempt.
5. Validate privacy notices, patient consent, withdrawal, retention, artifact deletion and actual staff response for urgent and uncertain requests.
6. Document backups, restore drill, monitoring, out-of-hours contact, operational support and incident escalation.
7. Record real device/signing checks when distributing Windows or Android clients and representative network/acoustic checks when activating media.

## Shift operations

On shift start, check `/ready`, failed/aged outbox items, pending external calendar writes, unknown payment/communication statuses, assigned work, staffing and fallback routes. During service, use the staff task queue and approved correction workflow rather than manually bypassing occupancy or permissions. At shift end, reconcile exceptions, outstanding handoffs, disputes and backlog, and transfer ownership to the next named operator.

## Incidents

**Failed booking or uncertain remote write:** stop repeated fresh submissions, retain the idempotency and correlation identifiers, verify actual calendar state, reconcile or escalate. **Message or payment uncertainty:** do not tell the patient that delivery or settlement succeeded; use trusted receipt/statement evidence. **Carrier/media outage:** disable automated admission or move to the approved staff/callback route, and verify actual bridge quality. **Privacy or wrong-tenant exposure:** restrict access, preserve sanitized forensic metadata, notify responsible reviewers and follow the operator's legal procedure. **Database/key loss:** halt writers and restore only from an independently tested backup.

An incident record should capture UTC/local time, affected tenant scope, owner, symptom, evidence references, mitigation, customer impact, permanent fix and regression test. Do not put patient content in public issues or Actions logs.

## Launch proof

The project includes synthetic conformance, tests and a readiness inventory tool (`scripts/launch_readiness.py`). Those tools intentionally cannot self-certify production. An authorized owner must independently assess signed artifacts, real carrier acceptance, actual clinic UAT, privacy/clinical compliance, physical devices, providers, staff transfer, backups and capacity before go-live.
