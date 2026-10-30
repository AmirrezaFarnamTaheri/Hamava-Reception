# Architecture: one authoritative reception service

[فارسی](architecture.fa.md) · [Documentation](README.md)

Hamava is deliberately a server-owned application. A web page, a desktop app, an Android app or a phone call may all request the same appointment, but none is allowed to invent a second version of the calendar. This choice is what makes retries, handoffs, reconciliation and staff supervision possible.

## The system at a glance

~~~text
Patient / Staff / Partner
        │
        ├── Browser UI ────────────────┐
        ├── Electron / Android ────────┤
        └── Phone / RTC / SMS adapters ┤
                                      ▼
                           FastAPI /api/v1
                           Identity + tenant scope
                                      │
             ┌────────────────────────┼────────────────────────┐
             ▼                        ▼                        ▼
       Scheduling core         Conversation + media      Operations + policy
             │                        │                        │
             └────────────────────────┼────────────────────────┘
                                      ▼
                               PostgreSQL
                      appointments · audit · outbox
                                      │
                                      ▼
                             Background workers
                       delivery · retries · reconciliation
                                      │
                                      ▼
                           Approved external services
~~~

The arrows show responsibility, not a promise that each optional external service has been deployed. The API and background workers use the same persisted records. Production uses PostgreSQL; local single-user demos can use SQLite.

## Component ownership

| Area | Primary implementation | Owns |
| --- | --- | --- |
| HTTP application | `backend/receptionist/main.py`, `api.py` | Request admission, identity-bound routes, health and API composition |
| Scheduling | `core.py`, `bookings_ext.py` | Slots, holds, appointment versions, resource occupancy, booking results |
| Conversations | `voice.py`, `locale.py`, `core_policy.py` | Persian request parsing, approved facts, explicit readback, controlled tool actions |
| Calendar integration | `calendar_bridge.py`, `calendar_contract.py` | Which calendar is authoritative, remote operations, readback and reconciliation |
| Communication | `operations.py`, `messaging_controls.py`, `sms_bridge.py` | Durable message intention, dispatch, receipt handling, outreach and suppression |
| Finance and provider controls | `billing.py`, `payment_policy.py`, `provider_control.py` | Monetary reservations, budgets, merchant binding, external-provider permission |
| Privacy and access | `security.py`, `access_controls.py`, `privacy_controls.py` | Current membership, encryption, processing purposes, retention and access audit |
| Live media | `media_api.py`, `media/`, `deploy/asterisk/` | Admitted sessions, media worker leases, call/bridge observations and human takeover |
| Staff/partner operations | `operations_extensions.py`, `operations_outreach.py`, `partners.py` | Task ownership, waitlist, outreach, partner scope and aggregate reports |
| Platform clients | `frontend/src/`, `apps/desktop/`, `apps/mobile/` | Presentation, server selection, safe session lifecycle and accessibility |

These are ownership boundaries, not separate product databases. The browser never decides whether a payment settled, a patient consented or a booking exists. Server permission checks are authoritative even when the interface hides an action.

## How a local booking is made

1. **Read availability:** a request for provider, service and date passes through the current clinic configuration. The scheduler evaluates shifts, service duration and buffer, holidays, closures, existing appointments and shared-resource occupancy.
2. **Issue an offer or hold:** returned slot IDs are signed and short-lived. The hold reduces the risk of two people selecting the same time but does not guarantee a completed booking.
3. **Confirm:** the caller or staff member supplies the selected slot, required contact fields, explicit confirmation and a bounded idempotency key. Deposit terms and reminder consent are independent inputs where applicable.
4. **Recheck inside the transaction:** the server checks current occupancy, version and applicable policy again. This second check matters because the schedule could have changed since it was displayed.
5. **Commit together:** the appointment, occupancy claims, audit entry, messaging intention and recorded response are coordinated. Replaying the same business operation should return the original result; a conflicting use of the same key should not create a new appointment.
6. **Process follow-up:** a worker eventually attempts permitted communications. Messaging failures do not erase a booking, and a booking's existence does not imply successful delivery.

Appointment mutations require a current version, so one receptionist cannot unknowingly overwrite another's cancellation or reschedule. `ReceptionService` owns these invariants; changes to its semantics need concurrency and idempotency regression tests.

## When the calendar belongs to another system

`calendar_bridge.py` separates **internal** and **external** calendar authority. An external connector must declare supported operations and provide stable remote identities, conditional writes, idempotency or equivalent conflict protection, and verified readback. A network timeout after a write is ambiguous: the remote calendar may have committed it.

For that reason, Hamava records the pending operation with its identity and reconciliation state. It does not claim success on HTTP transport alone, and it must not blindly submit a second fresh write. The staff-facing operations queue lets an authorized person inspect and reconcile unresolved results. Switching calendar authority is a controlled clinic decision, not an invisible frontend preference.

## Conversation state and human handoff

The public session begins after the current notice and consent. The conversation preserves a call clock, normalized Persian input, verified phone/contact steps, a proposed action and the outcome of each tool call. The system asks when dates, times or identities are ambiguous and only speaks approved clinic facts. Each submitted turn has a request identity so a retry cannot accidentally repeat a booking.

Media is not the source of booking truth. Optional AudioSocket and LiveKit workers must be admitted through the API and bound to the intended clinic and session. A worker lease and fencing generation prevent a retired worker from acting on a newer call. Human transfer passes through request, staff screening/acceptance and actual observed bridge membership; the final label depends on real evidence, not a dial attempt.

## Delivery, costs and privacy

Background work follows **intent → dispatch → observed result → reconciliation**. The transactional outbox survives application restarts. Uncertain responses remain visible; retries are bounded and respect quiet hours, consent and recipient policy.

Costs follow **approved rate/policy → maximum liability reservation → provider work → measured usage or unknown liability → reconciliation**. Amounts use exact decimal/micro-Toman representation, avoiding silent floating-point rounding in the browser. A provider being configured is not the same as its health being observed.

Privacy is similarly explicit: a caller's consent to receive a service does not automatically permit training, indefinite recording or unrelated outreach. Processing purpose, provider approval, retention limits, withdrawal and artifact erasure are separate records and checks. Access logs are minimized and avoid recording sensitive request paths or raw patient text.

## Database and failure recovery

Production schema history is **0001 → 0002** in `backend/receptionist/migrations.py`. The first version is a real upgrade predecessor, not dead code. The second creates additional controls and transforms legacy billing notes without discarding financial data. Unknown or partially migrated schemas are rejected instead of being silently “repaired.” Take and test a backup before changing a live database.

| Failure | System behavior | Staff/operator response |
| --- | --- | --- |
| Slot changed between display and confirmation | Reject or require a new selection | Refresh availability; do not invent a booking |
| External calendar timeout | Retain a pending/unknown operation | Read back and reconcile before a new request |
| SMS accepted without delivery receipt | Keep transport and final delivery distinct | Check receipt or contact the patient another way |
| Payment callback without trusted settlement | Keep financial state subject to verification | Reconcile with the merchant before marking paid |
| Media worker or carrier failure | End or recover media; preserve durable task/booking state | Use the approved staff callback route |
| Database/key loss | Stop writers; use the tested restore plan | Restore records and compatible keys, then verify |

For protocol details see [API](api.md); for operational recovery see [Deployment](deployment.md) and [Operations](operations.md).
