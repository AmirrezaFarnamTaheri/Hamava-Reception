# Connect and verify external providers

[فارسی](provider-integrations.fa.md) · [Documentation](README.md) · [Deployment](deployment.md)

Hamava works as a text receptionist without a carrier, external calendar, SMS gateway or payment merchant. Enable each provider only when the clinic has a reason to use it, a named owner, the required permissions and a way to recover when it fails.

A configured credential does not prove that a provider is approved, reachable or completing real work. The repository separates configuration, operator capability declarations, observed provider health and the result of each business operation.

## Begin with the integration disabled

Decide which clinic owns the account, what information will leave the system, which region processes it, who can revoke access and how an outage reaches reception. Record the provider agreement, permitted purposes, retention, accepted version and expiry in the clinic's private change record.

Keep the relevant production approval flag set to `false` while reviewing configuration. Generate the ordinary production keys with `scripts/generate_env.py`, then edit the private `.env.production` on the deployment host. Do not commit the file or paste its contents into a support ticket.

| Integration | Main production switch | Configuration to review |
| --- | --- | --- |
| Local or approved speech gateway | `SPEECH_PROCESSOR_APPROVED` | Gateway URL and token, processing region, ASR/voice revision and reviewed model rights |
| Calendar partner | `CALENDAR_PARTNER_APPROVED` | Partner URL, webhook secret, unique tenant-bound account IDs and secret tokens, region |
| Outbound SMS | `SMS_PROVIDER_APPROVED` | Kavenegar credentials, sender, OTP template, notification webhook secret, region |
| Payment merchant | `PAYMENT_PROVIDER_APPROVED` | Approved merchant registry, tenant-to-merchant mapping, HTTPS public origin, settlement region |
| LiveKit media | `LIVEKIT_APPROVED` | LiveKit URL and keys, media API token, telephony region, private transfer route |
| Optional digest service | `DIGEST_PROCESSOR_APPROVED` | Approved endpoint, token, region and the governed purpose |

`backend/receptionist/config.py` validates enabled provider variables during startup. Network providers require an approved host in `APPROVED_PROVIDER_HOSTS` and HTTPS or WSS. The `ALLOW_LOCAL_HTTP_PROVIDERS` exception is for explicitly permitted loopback development; do not use it for a production provider.

## Approve the processor and declare its capabilities

Provider access is subject to more than an environment switch. The responsible administrator records the clinic's permitted data purposes, processor terms and regions through the privacy controls described in [Privacy operations](privacy-operations.md).

The capability registry is under `/api/v1/operations/integration-capabilities`. Read it using an authenticated staff account with `integration:read`:

~~~http
GET /api/v1/operations/integration-capabilities
Authorization: Bearer <staff-access-token>
~~~

For a specific provider, an authorized operator publishes its supported operations, endpoint or model version, region, evidence reference, expiry and a current `version` with:

~~~http
PUT /api/v1/operations/integration-capabilities/calendar_primary
Authorization: Bearer <authorized-staff-token>
Content-Type: application/json

<CapabilityInput from the current OpenAPI schema and reviewed evidence>
~~~

The value above is a description of the required request body, not copyable JSON. See `CapabilityInput` in `backend/receptionist/provider_control.py` or `/openapi.json` for the exact schema. Use `declared_unverified` while details have not been checked. Record `operator_attested` only after an accountable person has reviewed the evidence. A declaration expires and is version-checked; publishing it does not make a provider healthy.

The current registry uses these keys: `speech_primary`, `speech_fallback`, `calendar_primary`, `telephony_primary`, `sms_kavenegar`, `payment_primary` and `digest_gateway`.

## Check observation separately from declaration

An authorized operator may request:

~~~http
POST /api/v1/operations/integration-capabilities/calendar_primary/probe
Authorization: Bearer <authorized-staff-token>
~~~

The endpoint performs a bounded provider health or capability request for the speech gateways, calendar partner and digest gateway. **It does not make an SMS delivery, bank settlement or live telephone call for the SMS, payment or telephony providers.** For those providers, the probe returns capability data; real observations must come from their permitted operations and receipts.

`GET /ready` aggregates configured dependencies. Its readiness result uses current operator attestations and recent healthy observations. The default observation freshness is controlled by `PROVIDER_HEALTH_STALE_SECONDS` (120 seconds in the supplied production template). A `503` means at least one configured dependency is not ready; it does not prove the core booking database has failed. Conversely, a `200` cannot replace clinical, carrier or merchant acceptance.

## Prove the complete operation before opening it to patients

| Provider | Controlled acceptance test | Recovery if the outcome is unknown |
| --- | --- | --- |
| External calendar | Read slots, create a synthetic booking, read it back, test conflicting writes and cancellation | Inspect `/api/v1/calendar/operations`; reconcile with the original operation ID |
| SMS | Send to an authorized test handset, inspect provider acceptance and final delivery receipt | Keep `UNKNOWN` separate from `DELIVERED`; reconcile before resending |
| Payment | Create a sandbox or approved test intent, verify trusted settlement, duplicate callback handling and a controlled reversal | Match merchant, intent, amount and provider record; never treat a browser redirect as settlement |
| LiveKit and PBX | Admit a controlled call, request staff transfer and verify actual two-way audible bridge participation | Record whether the caller was connected; assign an owned callback if transfer fails |
| Speech | Test authorized Persian audio, common noise, critical dates/numbers, latency and failure fallback | Return to text or staffed handling without inventing a recognized booking |

An internal-to-external calendar change has additional restrictions. Keep automated intake paused, read `GET /api/v1/calendar/authority`, and use its current `version` when requesting a switch. The server refuses changes that would strand active appointments, holds, pending operations or retained remote confirmations. Resolve these records and obtain a reviewed migration plan; do not force the switch or discard the old authority.

For AudioSocket, do not expose its unauthenticated media transport on the public Internet. The Compose example binds port 9092 to loopback, and the Asterisk route needs explicit private access and `AUDIOSOCKET_ALLOWED_CIDRS`.

## Open, monitor and roll back one provider at a time

After the sandbox evidence passes, confirm the processor approval, capability declaration, current health and clinic-specific acceptance. Enable the intended integration for a supervised cohort. Observe request outcomes and staff tasks, not merely uptime. Record the exact configuration revision and acceptance owner.

If a provider degrades, stop admitting new work to that route or pause automated intake as appropriate. Preserve already-sent request identities and unresolved states. Reconciliation must finish before deciding whether another write is safe. Disabling a feature flag cannot cancel a payment, SMS or calendar write already accepted by the provider.

For the five synthetic production checks and configuration fingerprint, follow [Clinic acceptance](clinic-acceptance.md). For the operator's shift response, use [Operations](operations.md).
