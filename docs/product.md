# Product and user workflows

[فارسی](product.fa.md) | [Documentation](README.md)

## Mission and users

Hamava supports Persian-speaking appointment-driven organizations that need reliable scheduling, response handling and a staffed fallback. The staff workspace is for receptionists and authorized managers; the public `/talk/:slug` experience is for callers/patients; partners receive only their allowed aggregate views. The desktop and Android clients present the same server-owned work.

**Scope:** administrative reception and communication. The system does **not** diagnose, prescribe, independently validate clinical advice or guarantee that a payment, message or telephone handoff succeeded without authoritative evidence.

## Main journeys

| Journey | Expected outcome | Important boundary |
| --- | --- | --- |
| Find and book a slot | Verify clinic, service, duration, provider/resources, availability; hold and confirm in one authoritative calendar | A tentative offer or hold is not a booked appointment |
| Reschedule or cancel | Check identity/permission and current appointment state, then commit auditable change | Retries must not duplicate or reverse a committed action |
| Conversation | Show processing notice, obtain consent, ask for missing fields, clarify Persian/Jalali dates and repeat the proposed action | Ambiguity triggers clarification or staff assistance |
| Human handoff | Send a scoped request to an approved destination and follow actual bridge/participant evidence | Attempted or screened transfer is not equivalent to connected staff |
| Messages and follow-up | Queue, dispatch, poll receipts where supported and observe quiet hours/opt-outs | Provider acceptance is not final delivery |
| Deposit and refund | Show current terms, obtain explicit consent, record intent and independent reconciliation | A payment initiation or callback is not verified settlement |
| Waitlist and outreach | Respect consent, policy, deadlines and item ownership | No silent enrollment or unapproved outreach |
| Clinic administration | Configure hours, practitioners, services, approved answers, roles, providers and budgets | Publication, tenant authority and observed readiness are separate |

## Operating modes

**Local demo:** synthetic clinics and fictional accounts; simulation results are labeled. **Connected sandbox:** only test accounts and authorized participants, with explicit scoped credentials. **Supervised pilot:** a real approved center and staffed escalation after all relevant reviews. **Production:** independently accepted carrier, clinic, privacy, clinical, scheduling, payment and deployment controls with monitoring and recovery. Passing local tests never promotes a site to a higher mode.

## Design requirements

Persian RTL typography and Jalali chronology are core behaviors, not optional localization. Staff should see actionable appointments, calls and tasks before dense management analytics. Errors and unknown provider states must remain visible and recoverable. Role-aware navigation is for usability only; the API enforces permissions. Mobile workflows must not pretend to work offline or store a second copy of patient records.

## Delivery status

The repository implements the local scheduling and operational surfaces, public text conversation, optional integration contracts and native project templates. External calendar authority, PSTN carrier media, live payment/SMS delivery, model quality, publisher signing, customer value and real device coverage must be demonstrated independently per deployment. Do not infer acceptance from settings appearing in the interface.
