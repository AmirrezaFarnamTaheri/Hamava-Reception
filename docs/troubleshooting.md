# Troubleshoot a failed reception workflow

[فارسی](troubleshooting.fa.md) · [Documentation](README.md) · [Operations](operations.md)

Start with the outcome that the patient or receptionist expected. A healthy server may still have an unavailable practitioner, an unresolved calendar operation or a payment waiting for settlement. Treat each as a separate state until the relevant record identifies the actual failure.

For a live clinic, assign someone to handle affected patients before investigating. If a booking might already exist in an external system, preserve its original request identity. Do not create a second booking, charge or message merely to see whether the service works.

## Check the application and its dependencies

From the deployment host, use the private production environment and inspect container status:

~~~sh
docker compose --env-file .env.production ps
docker compose --env-file .env.production logs --tail=100 migrate api jobs
~~~

Then query the approved public HTTPS hostname:

~~~sh
curl --silent --show-error --include https://reception.your-domain.example/health
curl --silent --show-error --include https://reception.your-domain.example/ready
~~~

Replace the hostname with the clinic's actual one. `/health` checks application access to its database. `/ready` also checks configured provider dependencies. It returns `503` for degraded dependencies even when the database is reachable. If migration fails or the database schema is unexpected, stop writers and follow [Deployment and recovery](deployment.md). Do not manually invent a schema version.

With an authorized staff token, the clinic-specific operational view is:

~~~http
GET /api/v1/operations/health
Authorization: Bearer <staff-access-token>
~~~

This endpoint requires `health:read`. It reports active calls, age of due messages and open tasks, delivery states, media worker observations, budget use and alert codes. It does not reveal patient transcripts. Use `X-Request-ID` from a failed HTTP response to correlate a safe diagnostic event. Never paste a bearer token, patient phone number or raw conversation into a public issue.

## Match the symptom to the next safe action

| Symptom | Look at | Next action |
| --- | --- | --- |
| All pages fail, `/health` returns `503` | Database reachability, migration, API logs | Keep patient traffic closed; restore the verified service/database combination |
| `/health` succeeds but `/ready` returns `503` | Integration capability, provider approval, health freshness | Identify the degraded dependency; disable or repair only the affected route |
| No appointment slots appear | Selected clinic, service, practitioner shifts, closures, room occupancy, calendar authority | Refresh availability from the authoritative scheduler |
| Booking says `409` | Current appointment version, policy and `IDEMPOTENCY_MISMATCH` code | For a stale version, read the appointment again; for a reused key with different content, inspect the original request |
| External calendar request remains pending or unknown | `/api/v1/calendar/operations` and provider readback | Reconcile the stored operation by its original ID before any further write |
| SMS was accepted but the patient received nothing | Message outbox, quiet hours, permission, delivery receipts | Keep delivery unconfirmed; reconcile the provider receipt or contact through an approved route |
| Deposit stays pending after a browser redirect | Payment intent, merchant binding, trusted settlement record | Finance checks the provider record; do not mark paid or refund without evidence |
| Phone transfer was requested but no staff answered | Call task, PBX events, worker lease, actual bridge participants | Record the failed connection; assign a staffed callback |
| New clinic configuration is rejected | `/api/v1/operations/uat` and current fingerprint | Pause intake, rerun relevant synthetic checks and obtain fresh attestation |

An unknown result is different from a failed action. A timeout can occur after an external provider has committed a write. Until the authoritative readback arrives, the operator should keep the recorded result pending and make the next staff action explicit.

## Understand the operational alerts

`GET /api/v1/operations/health` uses bounded signals. The current implementation reports `OUTBOX_DELAY` when a due queued message is older than 180 seconds, `STAFF_QUEUE_DELAY` when the oldest active task is older than 900 seconds, and `UNKNOWN_DELIVERY` if unresolved delivery states exist. These thresholds are **signals to investigate**, not proof that a patient was harmed or a provider failed.

Reports of `safety.false_confirmation` or `safety.tenant_exposure` produce critical alerts. Pause the affected automated route, assign an incident owner and preserve safe evidence. The absence of a recorded incident does not prove that none occurred.

For timing, staff with `health:read` can query:

~~~http
GET /api/v1/operations/latency?hours=24
Authorization: Bearer <staff-access-token>
~~~

The latency report uses bounded successful observations and returns `truncated` when the sample cap is exceeded. A favorable percentile excludes some failed or abandoned work. Investigate failures and end-to-end audible experience separately; TTS completion does not show when a caller actually heard speech.

## Close the incident with a verified result

Record the clinic's internal incident reference, affected capability, first observation time, safe request/operation IDs, actual state, owner and next patient communication. Separate what the server reported from what the external provider confirmed.

After repair, exercise one controlled request and its relevant failure path. Check the authoritative record, outbox or bridge result, not only the HTTP status. If you changed the clinic catalog or operating policy, follow [Clinic acceptance](clinic-acceptance.md) before resuming automated intake. If you changed an external account, use [Provider integrations](provider-integrations.md); for requests involving disclosure, use [Privacy operations](privacy-operations.md).
