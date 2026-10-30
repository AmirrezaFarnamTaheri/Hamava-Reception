# Hamava shared web interface

[فارسی](README.fa.md) | [Project](../README.md) | [Development guide](../docs/development.md)

The React/TypeScript/Vite application presents the Persian reception desk and public patient pages. It reads clinic data and sends actions through FastAPI at `/api/v1`. For each action, the page must show the state returned by the server, including pending and failed outcomes.

## Work locally

With the backend listening on `http://127.0.0.1:8000`, run in `frontend/`:

~~~sh
npm ci
npm run dev
~~~

For the production-style static bundle use `npm run typecheck` and `npm run build`. The server serves built assets from `frontend/dist/` when present. Browser journeys must use an isolated synthetic API: `python scripts/ci_ui.py test:ui test:workflows test:conversation test:privacy-notice` from repository root after building.

## Navigation and limits

Staff workflows include Today, Appointments, Tasks, Calls, management and permission-gated controls. The public `/talk/:slug` asks for processing consent before session creation. The `/respond/:id#secret` link keeps the response secret in memory. Mobile navigation emphasizes Today / Tasks / Calls / More. Connection setup never sends credentials before the compatibility check; Android uses HTTPS. Permission and appointment authority remain on the server. Text stays usable if speech or RTC is unavailable; the UI does not claim offline booking or native-device qualification.

Consult [product behavior](../docs/product.md), [API semantics](../docs/api.md) and [native packaging](../docs/clients-and-releases.md) for the full maintained contracts.

## What to change for a given screen

| Part of the experience | Source | Behavior to preserve |
| --- | --- | --- |
| Login and clinic connection | `src/pages/Login.tsx`, `src/pages/Connection.tsx`, `src/platform.ts` | Test server identity without staff credentials; enforce supported HTTPS origins |
| Today and navigation | `src/App.tsx`, `src/pages/Overview.tsx` | Show tasks and appointments in the current clinic; make mobile controls accessible |
| Bookings | `src/pages/Appointments.tsx` | Handle hold expiry, stale versions, missing payment terms and uncertain external results |
| Live calls and tasks | `src/pages/Calls.tsx`, `src/pages/TaskQueue.tsx` | Distinguish requested transfer, actual connection and owned callback |
| Public patient conversation | `src/pages/Talk.tsx` | Display the processing notice first; clarify ambiguous dates and verify changes |
| Finance and policies | `src/pages/Payments.tsx`, `src/pages/Costs.tsx`, `src/pages/PrivacyGovernance.tsx` | Expose pending settlement, budgets, revocation and current permission |
| Backend communication | `src/api.ts`, `src/hooks.ts`, `src/types.ts` | Preserve error codes, request identity, typed responses and clear failure states |

## A safe frontend change

When adding an appointment action, start with its actual API request and typed response, not a local mock of successful booking. Display the pending state while the request runs, disable contradictory actions, and handle conflicts by refreshing the authoritative appointment. For a failed network call, leave the user with a clear retry or escalation path rather than inventing success.

Check layouts at 320px, 390px and desktop widths. Test keyboard tab order, focus restoration after dialogs, Persian/Latin bidirectional text, large typography, empty lists, delayed requests and server-side permission errors. A menu item being hidden never replaces an API permission check.

From the repository root, after building `frontend/dist/`, run:

~~~sh
npm --prefix frontend run test:browser-launch
python scripts/ci_ui.py test:ui test:workflows test:conversation test:privacy-notice --port 8137
~~~

The CI matrix also exercises outreach, waitlist/deposits, RTC lifecycle, companion and platform connection. Each browser suite uses an isolated synthetic server; evidence is stored per run rather than checked in.

## Make loading and failure states explicit

A page that starts a mutation must show the state of that request separately from the state of the appointment. For example, when a receptionist clicks Confirm, disable another submission while the HTTP request is in flight. If the request succeeds, render the returned booking status. If it fails with a version conflict, read the current appointment and ask the employee to review it. If the network fails while an external calendar is writing, surface the saved operation and its reconciliation route.

The visible label matters more than an optimistic animation:

| Response or state | Recommended presentation |
| --- | --- |
| Slot lookup still running | Keep earlier selection visible and label the search as loading |
| No slots meet the chosen service rules | Show an empty result and a way to change date or practitioner |
| Hold expires | Explain that the time is no longer reserved; fetch availability again |
| Appointment is waiting for approval or payment | Show which step remains and avoid a "confirmed" label |
| Request lacks permission | Explain the restriction without exposing another clinic's details |
| Connection is lost | Keep known unsent form fields available where safe; do not claim the server accepted them |
| External result remains unknown | Give staff an explicit path to inspect the original operation |

Check both keyboard focus and accessible announcements when a dialog opens, closes or reports an error. In Persian layouts, test long names, Jalali dates, Latin IDs and numbers together: mixed-direction text often exposes alignment defects missed by English-only fixtures.

## What a frontend PR should include

A useful UI change identifies the route, the affected role and clinic scope, the request it sends, its loading/error states, and one browser regression. If an API response shape changed, update `src/types.ts` and the consuming page together. If an endpoint is permission-gated, verify the server rejects an unauthorized request even when the user opens a route manually.

Screenshots can help review a visual change, but save transient captures with the relevant CI or review artifact. Generated images and browser logs do not belong in the maintained source tree.

## Native host boundary

The same frontend is packaged by Electron and Capacitor. The native host supplies only the approved bridge for connection, session storage and device behavior. `src/platform.ts` checks `/api/v1/client-info` before sign-in and prevents the application from creating a second offline appointment database. On sign-out, client credentials must not be silently restored from an old vault entry. See [Clients and releases](../docs/clients-and-releases.md).
