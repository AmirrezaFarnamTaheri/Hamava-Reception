# Product guide: what the reception desk does

[فارسی](product.fa.md) · [Documentation](README.md)

## The reception problem

A receptionist works across several queues at once: someone calls while another patient arrives, a doctor moves a shift, a cancellation frees a slot, and a payment still has no verified outcome. A useful system must do more than take a booking. It must keep one dependable account of **what has happened**, **what is waiting** and **who owns the next step**.

Hamava joins three experiences around that account:

| Experience | Main user | What matters first |
| --- | --- | --- |
| Staff desk | Receptionist, coordinator or manager | Today's appointments, calls, open tasks, replies and exceptions |
| Public reception | Patient or caller | Understand the notice, ask for a service, confirm details and reach a person |
| Companion app | Authorized staff on Windows/Android | Rejoin the same clinic, act on assigned work and retain clear connection status |

Managers also configure services, shifts, approved answers, team access, policies and integrations; partners can see only permitted aggregate information. All these interfaces work against the same clinic-scoped server.

## A booking, from request to outcome

Consider a fictional patient requesting a consultation with Dr. A on Tuesday afternoon.

1. **Understand the request.** The patient or receptionist selects the clinic and service. Persian date parsing handles Jalali expressions and spoken digits, but ambiguous weekday or time expressions are clarified rather than guessed.
2. **Check the clinic rules.** The scheduler checks the service length and buffers, provider working hours, holidays, shared room/equipment requirements, lead time, closures and existing occupancy.
3. **Offer a real slot.** An available time becomes a signed, short-lived offer. A hold reserves it temporarily; neither is a final booking.
4. **Confirm the particulars.** The proposed clinic, service, practitioner, time and contact are read back. Reminder permission and deposit acceptance, when applicable, are separate choices.
5. **Commit the appointment.** The server checks the current state again. Occupancy, booking, audit record and the intended notification are written together, using idempotency to make a safe repeat return the same result.
6. **Handle the aftermath.** Confirmation delivery may still be pending; the appointment itself has a definite status. Later rescheduling, attendance, cancellation, waitlist fulfillment and disputes remain linked to the original record.

A remote calendar is different. When that provider is the clinic's authority, a write can have an uncertain outcome. Hamava keeps it pending until the provider's authoritative read-back confirms what really happened. Staff must not issue an independent second booking to “fix” an unknown first attempt.

## Conversation and handoff

The patient-facing page starts with the current processing notice. The caller consents before a session is opened, then can use text; microphone or real-time audio appears only when its configured service is available. The conversation works as an administrative state machine: it gathers verified details, asks follow-up questions, reads back actions and delegates changes to the scheduler.

A conversation can end with an appointment, a correction, a cancellation request, a staff task or a human handoff. Medical questions are routed to appropriate human staff instead of being answered as diagnoses. For a telephone transfer, **requested**, **staff accepted** and **caller actually bridged** are different states. A callback task is not a connected transfer.

## The staff's day

**Start of shift:** review today's work, unmatched calendar operations, pending messages, service-health observations and who is available for handoffs.

**During shift:** prioritize actionable calls and tasks; change appointments through the authorized workflow; use the waitlist when a slot opens; check actual payment/deposit and message states before promising an outcome; escalate unclear or urgent requests.

**End of shift:** reconcile unknown results, overdue tasks, disputes and message failures, then hand over unresolved work with clear ownership.

The daily workspace should show the next action before secondary metrics. Administrative screens are deeper, permission-gated areas—not distractions in the main flow. On a phone, the navigation prioritizes Today, Tasks, Calls and More.

## Rules for a trustworthy interface

- Label **held**, **confirmed**, **pending approval**, **deposit pending**, **failed** and **unknown** differently. Do not turn a network acknowledgement into a business success.
- Make tenant, time zone and Jalali date interpretation visible when they can change a decision.
- Preserve the patient's place when a microphone, provider or network connection fails; offer text or staffed fallback where possible.
- Use clear Persian labels, readable number formatting, keyboard navigation, accessible focus/error messages and protected links.
- Show only actions the user can request; always recheck authority on the server.
- Avoid storing an offline copy of appointments on a native client. A connection interruption must not create phantom bookings.

## Scope and deployment stages

The repository provides the scheduling core, web experience, native hosts, operational workflows and opt-in integration adapters. It does not ship with an Iranian carrier trunk, a clinic's payment merchant, live SMS delivery rights or an approved clinical script.

| Stage | What can be done | Who decides the next stage |
| --- | --- | --- |
| Local demo | Explore fictional clinics and synthetic operations | Developer |
| Connected sandbox | Test approved provider accounts and authorized participants | Technical owner and provider |
| Supervised pilot | Serve a consenting real center with staff and recovery on call | Clinic owner plus legal/clinical/technical reviewers |
| Production | Expand after real acceptance, monitoring and restoration drills | Accountable operational owners |

Success should be measured in verified appointments completed, missed requests recovered, staff time saved, error/correction rate, unresolved workload and actual cost—not in the number of messages generated. See [Operations](operations.md) for promotion checks and [Research](research.md) for measurement design.
