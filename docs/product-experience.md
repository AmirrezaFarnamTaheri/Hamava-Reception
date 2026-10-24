# Hamava product experience

## Purpose and scope

Hamava is a Persian reception workspace. The desktop application supports a staffed reception desk; the mobile companion helps an authorized colleague check today's work, own a follow-up, and join an available call. The public receptionist is a separate, consent-first experience for patients. These are three views of the same authenticated service, not separate calendars or offline copies of patient records.

This document records the UI implementation contract for the companion-app expansion. The user requested completion, proper UI/UX, installers/APKs, and companion applications. The existing requirement register remains the authority for product behavior. Native packaging, transport configuration, backend capabilities, and external acceptance are owned by their implementation records; this document does not certify them.

## Experience map

| Surface | Primary job | Navigation and first action | Boundary |
|---|---|---|---|
| Desktop workspace | Run reception throughout the day | Grouped side navigation; Today, appointments, tasks, calls; searchable actions | Administrative features follow the account's permissions |
| Mobile companion | Act on the next relevant request | Persistent Today / Tasks / Calls / More navigation; readable touch controls | No claim of offline writes, background calling, or native-device qualification |
| Patient reception | Ask, book, correct, or reach a person | Clinic identity and processing notice before conversation; typed fallback always recoverable | Booking/payment/handoff success comes only from trusted server state |
| First connection | Reach the correct service and account | Explicit service address, connection check, clear success/failure, then sign-in | No credential transmission to an unconfirmed replacement service |
| Center setup | Make the center usable without code | Saved setup checklist linking to identity, hours, catalog, approved answers, integration and launch review | Completing configuration is distinct from authorizing live activation |

## Information hierarchy

Daily work leads. Today shows actual appointments, open requests, and active sessions, followed by a concise activity trail. A status summary explains how reception is operating. Appointments retain exact booking status, attendance, and payment distinctions. Task cards lead with what needs attention and who owns it; secondary actions are recoverable and clearly named. Calls display active sessions and the actual takeover result. More contains the complete authorized navigation, account and service information, and setup tools.

The command menu searches **destinations and available actions**, not patient data. Its scope is stated in the interface. Keyboard users open it with Control/Command + K, move through results with arrow keys, select with Enter, and close with Escape. Navigation shortcuts never submit a clinical, scheduling, or financial mutation.

On a narrow phone, today's schedule appears before the secondary metrics and integration summary. Appointment cards use chronological order and retain the booking, payment and attendance distinctions. Additional actions are grouped behind a labeled disclosure; the last control has enough scroll clearance above persistent companion navigation. The desktop keeps a table where its wider comparison is useful.

## Administrative workflows

The **Control and oversight** area separates four tasks and only exposes sections allowed by the signed-in account's server permissions:

| Section | Implemented workflow | Decision that remains explicit |
|---|---|---|
| Costs and budgets | Exact decimal cost display, versioned provider rates, budget caps, invoice-line review and unresolved-cost reconciliation | An unknown cost is retained until reviewed evidence supports an outcome; lack of a tariff is not a zero price |
| Data choices | Purpose-specific publication and independent, version-bound subject permission | Publishing a notice does not grant consent; individual permission starts with no preselected answer |
| Service connections | Configuration, operator attestation and actual observation shown separately; processor terms; calendar authority; allowlisted routing | Saved configuration is not proof of delivery, settlement, carrier operation or provider availability |
| Service health | In-app alerts, ordered responsible colleagues, evidence-bearing acknowledgment/resolution and observed latency | No external paging or first-audible latency is claimed from an administrative record |

Evidence forms calculate a SHA-256 fingerprint locally when a reviewer selects a document. They send the reference and fingerprint, not the file. This binds the operator's record to the reviewed document without representing a local upload as independent verification. Permission and publication forms show the purpose, current version and explicit review action together. Editing the underlying values clears the prior confirmation.

Service configuration also includes source-backed visit conditions, preparation and insurance notes, approved catalog facts and named Persian time windows. These are administrative inputs with source and expiry, not generated medical advice. The external-calendar workflow keeps cached inventory, unknown operations and fresh verified results distinct. A cached remote appointment requires a fresh authoritative read before change controls appear; a pending mutation remains a trackable operation and never becomes a fabricated successful booking.

Billing accounts use a minimal appointment-reference lookup for financial work rather than reading patient appointments. Technical accounts receive connection/health navigation. Coordinators receive reception tasks and appointments without finance controls. Navigation visibility improves usability; the server independently enforces every permission.

Patient processing consent binds the exact notice and retention terms displayed by the clinic. The standard disclosure and any separate purpose notice appear together before the unchecked consent control. If the policy changes before the person starts, the server rejects the old notice fingerprint; the interface retrieves the current text, clears the prior selection, and requires a fresh affirmative choice. It never retries consent automatically. An unavailable notice prevents conversation startup while keeping the clinic's direct contact information visible.

## Visual and interaction decisions

- Preserve the existing Hamava wordmark, local Vazirmatn font, Persian RTL layout, calm sage/teal palette, and warm paper background.
- Use the reception task as the composition: date and center context, next actions, a readable schedule, and ownership of follow-ups. Avoid a decorative marketing hero above operational work.
- Maintain a consistent desktop rhythm and generous mobile touch targets. Narrow layouts use cards for appointments and a contained chooser for administration; they do not shrink essential labels to fit a desktop table.
- Show primary actions as labeled buttons. Use icon-only controls only where the accessible name and nearby context identify the action.
- Separate loading, empty, stale, unavailable, permission-limited, and successful states. Browser connectivity alone never proves the service is healthy.
- Respect reduced motion. Status colors include text. Dialogs retain keyboard focus, Escape behavior, a visible close action, and readable error recovery.
- A public phone session must stop or retire old media operations when leaving a room; a disconnected or reconnecting session cannot claim to be connected.

## Task execution and authority

| Contract field | Decision |
|---|---|
| Task | COMPANION-EXPERIENCE |
| Lead | Frontend implementation |
| Active guidance | implement-high-fidelity-digital-interfaces; shared precision, authority, ownership, visual and assurance references |
| Fixed | Persian RTL identity, existing server contracts and confirmation boundaries, masked operational data, patient consent, installed local typography |
| Targets | Discoverable daily work; accurate state; readable desktop/390 px/320 px layouts; keyboard and touch usability |
| Class-2 discretion | Navigation grouping, layout density, component presentation, explanatory Persian copy within existing product behavior |
| Class-3 discretion | Component extraction, CSS structure, query-state handling, test organization |
| Protected ownership | Root owns native runtime/packaging/CI and API transport plumbing; backend agents own policy and authorization contracts |
| Prohibited | Fake successful outcomes, guessed provider capability, privilege escalation through UI, unsent-message delivery claims, invented patient or business metrics |
| Representation | Semantic browser DOM and CSS; React production candidates; no canvas or external imagery needed |
| Assurance | MATERIAL plus perceptual review; security/financial behavior retains existing server-side gates |
| Acceptance environment | Local real service with synthetic data; built UI in Chromium at desktop, 390 px and 320 px; native-device limits explicit |
| Oracles | Real API results, rendered pixels, keyboard/pointer browser actions, accessible roles, build/type checking |
| Independent review | Parent implementation owner reviews captured real desktop/mobile output and records limitations separately from builder self-review |
| Rollback | Restore the pre-companion source snapshot; no database migration belongs to this UI work |
| Stop condition | A protected contract or permission conflict blocks only its dependent feature; available unrelated work continues |

## Checkpoints and evidence

1. **Composition candidate:** implement the real workspace shell, mobile navigation, Today hierarchy, and connection surface; capture desktop and narrow-phone screenshots for independent review.
2. **Working journeys:** sign-in/recovery, clinic switching, command navigation, appointments, task ownership, calls and More. Connect new backend controls only to documented contracts.
3. **Final verification:** rerun the affected existing browser audit and workflows, add companion-specific failure and keyboard cases, inspect 320 px and 390 px output, run type/build/format checks, and retain sanitized JSON evidence.

The prior 44-state/67-workflow reports and subsequent RTC event-contract report are historical evidence for the earlier UI. New reports must identify the changed surface and their actual run environment. A desktop browser viewport is not an Android/iOS hardware test. Installer creation, signing, distribution, actual vendor delivery, physical mobile media routes, and public-network recovery each require their own evidence.

## Release assessment

The scoped frontend and companion experience is implemented and its retained browser verification is complete. The production build, TypeScript checks and full frontend formatting check passed. The final release uses `/assets/index-DnPskxcg.js` with `/assets/index-DVYiIkCe.css`. The frontend source-tree SHA-256 is `5132a4fd75fca3d9515df28dd3a901e821c25b4913c573d44f7bde01bc620874`. The exact entry, stylesheet, all 61 captured output files and source/config hashes are retained in [the final label-correction record](validation/v2-ui-latency-labels-source-equivalence.json).

The [scoped frontend evidence map](validation/v2-frontend-requirement-evidence.json) records 43 requirement contributions with separate observed behavior, source inspection and acceptance limits. It does not overwrite the main product requirement register. The [frontend guide](../frontend/README.md) documents the surfaces, runtime contract, test commands and environment boundaries.

### Browser results

| Suite | Named passing checks | Audit executions | Executed bundle |
|---|---:|---:|---|
| Baseline workspace and public screens | 0 | 44 | Recorded predecessor; source equivalence retained |
| Booking, scheduling and no-code catalog | 10 | 0 | Recorded predecessor; source equivalence retained |
| Public conversation and recovery | 5 | 0 | Recorded predecessor; source equivalence retained |
| Owner, task and partner operations | 13 | 5 | Recorded predecessor; source equivalence retained |
| Outreach, consent and financial review | 8 | 3 | Recorded predecessor; source equivalence retained |
| Launch review, terms and center setup | 7 | 2 | Final bundle |
| Versioned paid-waitlist acceptance | 8 | 4 | Recorded predecessor; source equivalence retained |
| Notice change and explicit renewed consent | 6 | 5 | Recorded predecessor; source equivalence retained |
| Caller/staff RTC event contract | 12 | 3 | Recorded predecessor; source equivalence retained |
| Desktop/mobile companion workflows | 19 | 24 | Recorded predecessor; source equivalence retained |
| Additive tool-stage labels and actual timing rows | 4 | 3 | Final bundle |
| **Total** | **92** | **93** | Each report retains its actual provenance |

The primary matrix comprises 88 named checks and 90 audit executions. The final focused latency check adds four checks and three audits, for **92 checks and 93 audit executions**. The seven-check release workflow was rerun against the final additive nine-stage contract; its predecessor is preserved separately and is not counted twice. Of the 92 checks, 12 are RTC event-contract checks. Audit executions can revisit a screen in different workflow states; they are not unique requirements or an exhaustive coverage claim. Six additional setup contrast audits, covering configured and incomplete centers at 1440, 390 and 320 pixels, remain separate in [the contrast record](validation/v2-ui-setup-contrast.json).

All successful named audits recorded zero axe findings and no horizontal document overflow. Successful suite monitors recorded no runtime errors. The baseline and companion monitors recorded no unexpected API failures; the focused latency run also recorded none. Deliberate stale-state and service-failure responses remain part of the recovery tests, so this does not claim that every HTTP response was successful. Automated accessibility checks used WCAG 2A/AA and WCAG 2.1AA tags, together with selected keyboard, focus and responsive-layout checks. This is bounded accessibility evidence, not a full conformance certification.

### Final corrections and provenance

Two small corrections followed the broader workflow verification. The first darkened three text colors in `frontend/src/workspace.css`: the setup summary eyebrow, setup explanatory paragraph and mobile center label. No TypeScript file changed during that correction. The affected baseline, companion, release/setup, waitlist and RTC screens were rerun, and six focused setup audits passed. [The color-change record](validation/v2-ui-source-equivalence.json) retains the exact diff and before/after source manifests.

The final correction added five Persian lookup entries in `frontend/src/pages/Latency.tsx`: slot search, temporary hold, booking, cancellation and rescheduling. The API had added these stages, while the interface still rendered the same generic label for all five. The correction changes no layout, stylesheet, control flow or runtime logic; the other 52 application source files are identical to the preceding frozen build. A directly related release-test assertion now checks the exact nine stage keys instead of the obsolete four-stage count.

The focused test created an actual successful slots-dispatch observation through a synthetic conversation and read the real local latency API. It then verified the distinct tool labels, actual counts and empty percentiles for stages without observations at 1440, 390 and 320 pixels. The report continues to distinguish successful local dispatch measurements from caller first-audible time and other unmeasured stages. The UI does not infer generative-model or provider performance from these values; core MEDIA-012 acceptance remains authoritative.

The final bundle directly passed **11 checks and five audit executions**: four focused latency checks plus the seven-check release rerun. **81 checks and 88 audit executions** retain their actual earlier bundles, script hashes and timestamps. They have not been relabeled as final-bundle runs. The final label record and earlier color record form the explicit source-equivalence chain. [The replaced release report](validation/v2-ui-release-before-latency-labels.json) preserves its original evidence without adding it to the current totals.

The build output is pinned independently of the mutable workspace. An initial successful build emitted the corrected entry, but a later workspace read showed the preceding generated tree; that stale tree was rejected. A fresh successful build copied all output immediately into an immutable snapshot, verified the compiled tool keys and recorded a complete file manifest. Both final browser APIs served that snapshot. It also provides the exact web input for separately verified native packaging.

The parent implementation owner independently inspected actual companion Today at 390 pixels, service connections at desktop width and the setup guide at 320 pixels. The review accepted their readability and semantic hierarchy: phone schedule and tasks lead, persistent navigation remains clear, desktop control tabs are readable, and four incomplete setup steps are represented honestly. Earlier desktop Costs review accepted its hierarchy and content fit. Earlier feedback led to two implemented refinements: bringing today's schedule before secondary mobile metrics, and sorting appointment cards chronologically. The builder also inspected the narrow setup and latency views. Fixed navigation and checker-induced focus can appear over full-element or full-page captures; functional focus, label and clearance assertions are recorded separately. This perceptual review is browser-viewport evidence, not physical-device or screen-reader acceptance. Screenshots remain internal review artifacts; sanitized JSON reports are retained.

### Failure history and limits

[Interrupted attempts](validation/v2-ui-interrupted-runs.json) remain visible. One extensions attempt encountered an undetermined local connection reset; a full 13-check retry passed without changing application retry behavior. One release attempt expected the earlier onboarding layout; the harness was updated to verify the actual four-step saved guide and gained desktop/320-pixel audits. Those audits exposed the contrast defect described above, which was corrected and passed. Failed attempts are not counted as passing checks. The final label record additionally notes the rejected stale generated output and an initial launcher attempt that used system Python without uvicorn; it stopped before any browser/API check. The accepted runs used the project virtual environment and the immutable build. No credential values are retained in these reports.

Current real service interactions used isolated synthetic databases with provider transmission disabled. Exact decimal tariffs, budgets, permission records, appointment operations, policy publication and other named writes used the actual local API. External-calendar readback states, one waitlist stale-terms response, non-demo metadata and RTC Room events have explicit fixture boundaries. The privacy-notice race used an actual policy change and server rejection; the final tool-stage observation also used actual local dispatch and telemetry. A document hash records the operator's evidence selection and does not independently verify its claims.

Actual-network RTC recovery remains partial. The tests establish caller/staff controls through SDK event contracts, including delayed and stale operations; they do not establish uninterrupted audio across network changes. This frontend matrix does not qualify physical Android/iPhone devices, native WebViews, screen readers, Bluetooth or microphone routes, background/lock behavior, live carrier/SMS/payment delivery, clinical/legal approvals or representative speech-recognition quality. Repeat and slower-playback controls are implemented and inspected; their clicks are not claimed by this matrix.

The parent-owned platform suite, native runtime checks, signing, installers and device records are assessed separately and are not added to these totals. App source and the captured release bundle remain frozen; the final changes after testing are this documentation and retained evidence.
