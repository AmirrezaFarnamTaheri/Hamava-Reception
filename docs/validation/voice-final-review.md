# Voice and media final review

This review records implemented behavior and observed synthetic verification. It supplements the main requirement register; it does not change that register.

## Verification that actually ran

The final combined run passed **136 tests in 47.61 seconds**. It covers voice, transaction and replay integrity, the 22 new follow-up cases, media decoders and transports, provider adapters, Persian locale handling, calendar integrity, partner integrity and published payment policies. The captured command, timestamps, complete stdout/stderr, dependency versions and source hashes are in `voice-final-tests.json`. This run used cryptography **50.0.2**, FastAPI **0.161.1**, SQLAlchemy **2.0.55** and pytest **9.1.1**.

After that combined run, the final CONFIRM repeat response was made to return the pinned `payment_terms` field consistently. Its focused deposit rerun passed **2 tests in 2.52 seconds**, with final source hashes and stdout in `voice-payment-repeat-tests.json`. These two cases are included in the broader suite and are not additional unique tests.

The earlier independent partner run passed 24 cases. The combined run includes the new 14-case partner-integrity file; these counts are overlapping runs and must not be added together as unique tests.

The isolated PostgreSQL harness executed `new_session`, `media_rooms` and `end_session` directly through independent database connections. It admitted the configured target at every level, rejected two excess calls per level, preserved the reserved duration budgets, enforced eight rooms per worker under competing worker polls, admitted one call under a one-minute clinic budget, and created exactly one duration event and one end audit after two concurrent end requests per accepted call. Each level also includes one accepted budget-test call, so cleanup records equal the target plus one.

| Target sessions | Admitted / attempts | Independent admission connections | Workers | Maximum rooms per worker | Admission P95 ms | Cleanup duration records |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 4 | 4 / 6 | 6 | 1 | 4 | 161.498 | 5 |
| 8 | 8 / 10 | 10 | 1 | 8 | 94.072 | 9 |
| 10 | 10 / 12 | 12 | 2 | 8 | 121.856 | 11 |
| 20 | 20 / 22 | 22 | 3 | 8 | 234.446 | 21 |
| 50 | 50 / 52 | 52 | 7 | 8 | 647.115 | 51 |
| 80 | 80 / 82 | 82 | 10 | 8 | 797.395 | 81 |

The latest report is `media-admission-load.json`. It includes the application/code component identifiers exercised in that run, finite-sample timing distributions, per-case checks and confirmation that the newly created random schema was removed. It did not access application schemas or send audio. Admission timing includes the synthetic durable room-registration step. These are handler timings, not HTTP throughput or acoustic latency distributions.

## Correctness and security changes

### Approved facts and language requests

The conversation engine considers all matching FAQ entries. Each answer needs nonempty approval and source metadata plus timezone-aware effective and expiry dates. Different current answers to the same matched question create a human task; equivalent answers are deduplicated. An expired entry cannot override a current valid answer. A tenant address field by itself is not spoken as a sourced fact.

Explicit English or Arabic requests, including tested mixed-language requests, create a human task and release uncommitted holds. The reply states that this assistant supports Persian, that a human has not yet connected, and that the colleague's language capability still needs checking. The requested language is retained in the encrypted session context and the staff task summary. There is no fabricated multilingual fluency or promised language-qualified pickup.

The recognition rules are bounded patterns, not a comprehensive automatic language detector. Unannounced language or arbitrary code-switching remains outside the demonstrated detection coverage. Real staffing availability is also outside local software tests.

### Reproducible versions

At admission, each new session pins the application version and content hashes of the FSM, locale, authoritative calendar and provider-adapter source. The configured ASR and TTS labels come from `SPEECH_ASR_VERSION` and `SPEECH_VOICE_VERSION`; absent or invalid labels become `not_recorded`. Results, encrypted turn receipts and authenticated reconnect carry the same tuple. Labels are bounded public identifiers, not endpoint URLs, paths or credentials.

These configured labels identify admission configuration. They do not certify which provider model processed a later request or establish provider quality. No generative-model or prompt stage is deployed here, so no such model version is invented.

### OTP budgeting and transactional fencing

A clinic-and-phone allowance permits three OTP challenges per ten-minute fixed window across all sessions. The pre-existing global phone hourly allowance and per-session challenge/attempt limits remain in force. Phone identifiers in rate keys are hashed. Real mode requires a configured SMS adapter; it never returns the demonstration OTP.

The allowance, encrypted challenge, queued outbox item and encrypted turn receipt share the tenant/turn transaction. A synthetic receipt failure rolls back all four. Four concurrent new sessions for the same clinic and phone create only three challenges and three verification messages. A distinct clinic retains its own clinic-scoped allowance, subject to the global phone cap. No test starts the SMS send worker or contacts a recipient.

### Independent family bookings and reconnect

Two-relative intent keeps each patient's name, phone proof, hold and confirmation separate. After the first booking, reconnect and request replay return its authoritative current status without duplicating it. If the second hold expires, the first booking remains intact and the reply explicitly reports that the next person's appointment has not been registered. Retrying the second selection and explicitly confirming creates exactly one further booking. Returned `bookings` are scoped to this call and tenant; reconnect also returns current `offers` only while selecting an offer.

### Published deposit consent

For a deposit service, the voice confirmation includes the exact amount in toman, pending-payment limit, deposit terms, cancellation terms and refund terms before asking for a yes. The version and full displayed terms are pinned in encrypted conversation context. A changed policy, version or deposit amount triggers a new confirmation and creates no appointment until a new yes. Core receives the accepted version and pins the published policy on the booking.

The real-mode regression uses an approved synthetic merchant and a synthetic SMS availability check, then verifies the actual policy enforcement and PENDING_PAYMENT transaction without calling an external provider. It does not settle money or prove a live merchant account.

The speech adapter accepts at most 2,000 characters. If the complete terms and confirmation would exceed the safe spoken bound, voice explicitly routes to staff rather than silently truncating terms or claiming acceptance. Frontend text policy presentation remains available independently.

### Partner integrity

Pronunciation entries reject Unicode control characters before normalization and at runtime, including bidi overrides, zero-width controls and C1 controls. Only meaning-preserving Arabic letter normalization and permitted vowel marks are allowed; spacing, punctuation and digit substitutions fail. ASR alias hints also reject hidden controls.

Team grants serialize the clinic scope, refresh live user/membership state, preserve existing passwords, and handle global unique-email or membership races with a bounded 409 response. Concurrent creation yields one user, one membership and one creation audit. Existing-account grants reuse the same membership without resetting credentials. A deterministic global-unique conflict regression proves rollback without exposing database parameters.

## Reproduction

Run local synthetic tests from the project root with the installed environment:

```bash
PYTHONPATH=backend ../.venv/bin/pytest -q \
  backend/tests/test_voice.py \
  backend/tests/test_voice_integrity.py \
  backend/tests/test_voice_followup.py \
  backend/tests/test_media_integrity.py \
  backend/tests/test_media_providers.py \
  backend/tests/test_locale.py \
  backend/tests/test_core.py \
  backend/tests/test_partner_integrity.py \
  backend/tests/test_payment_policy.py
```

For the load harness, supply `TEST_DATABASE_URL` securely to a dedicated PostgreSQL test database and run the isolated acknowledgement command. The process must be development mode and the database account must be allowed to create and remove its own temporary schema. Do not put credentials in reports or command history.

```bash
../.venv/bin/python scripts/media_admission_stress.py \
  --acknowledge-isolated-test-database \
  --output docs/validation/media-admission-load.json
```

## Remaining boundaries

The separate map, `voice-requirement-evidence.json`, contains 92 assessed requirements: 64 locally verified, 22 with partial evidence, and 6 requiring external acceptance. Some items span frontend, operations, deployment and clinic ownership; root reconciliation must merge their evidence without treating this assessment as sole coverage.

The harness does not establish STT/TTS/GPU throughput, real telephone channels, public TLS/TURN networking, packet loss/jitter resilience, representative mobile behavior or paid-capacity limits. No handler percentile should be presented as end-of-turn-to-first-audible latency. Actual supplier currency spend enforcement remains separate from duration reservations. Full telephone-audio quality, verified carrier/human pickup, licensed and approved production speech models, and clinic staffing acceptance require their own authorized evidence.
