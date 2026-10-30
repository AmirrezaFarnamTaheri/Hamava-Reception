# Handle privacy permissions and subject requests

[فارسی](privacy-operations.fa.md) · [Documentation](README.md) · [Operations](operations.md)

A patient can agree to an administrative conversation without agreeing to recordings, model training, follow-up messages or cross-border processing. Hamava treats these as separate purposes and keeps the clinic responsible for the notice, the permission record and any outside processor it uses.

This guide is for the clinic's authorized privacy operator. It describes the controls implemented in `backend/receptionist/privacy_controls.py` and `backend/receptionist/operations.py`. An API success response records the action performed in Hamava; the clinic must also manage its external copies, contracts and applicable obligations.

## Decide which purpose is being requested

The purpose registry includes `processing`, `recording`, `qa`, `marketing`, `training`, `cross_border`, `memory`, `reminder`, `waitlist` and `followup`. The purposes are independent. A general processing notice does not grant permission to store an audio sample for quality assurance or to use it for training.

For each purpose, the privacy operator publishes the current notice, whether the purpose is enabled, its retention limit, backup expiry, permission validity and evidence reference.

~~~http
GET /api/v1/operations/privacy-controls/purposes
Authorization: Bearer <privacy-authorized-staff-token>
~~~

The publishing route is `PUT /api/v1/operations/privacy-controls/purposes`. The caller needs `privacy:manage`. Its `PurposeInput` includes `purpose`, `enabled`, `notice`, `retention_days`, `backup_expiry_days`, `consent_valid_days` and `evidence_reference`. Read the current policy before recording a new permission so the patient is not asked to agree to an obsolete version.

Recording an independent choice uses `POST /api/v1/operations/privacy-controls/permissions`. The request names the phone, purpose, `granted` choice, current numeric `policy_version`, evidence reference and SHA-256, the collection method and `subject_request_confirmed`. Supported methods are `signed_form`, `recorded_verbal_request` and `verified_subject_request`.

Do not infer permission from a telephone number or from the fact that the patient completed a booking. A withdrawn choice must be recorded as `granted: false` against the current policy. The API can expire stored artifacts and end active sessions when the corresponding purpose is withdrawn.

For a verified request to withdraw **recording** permission, the request body has this shape:

~~~http
POST /api/v1/operations/privacy-controls/permissions
Authorization: Bearer <privacy-authorized-staff-token>
Content-Type: application/json

{
  "phone": "<verified-phone>",
  "purpose": "recording",
  "granted": false,
  "policy_version": 1,
  "evidence_reference": "<private-evidence-id>",
  "evidence_sha256": "<64-character-hex-digest>",
  "method": "verified_subject_request",
  "subject_request_confirmed": true
}
~~~

This is a template. Replace the private identifiers and the evidence digest, and use the numeric version returned by the current purpose policy rather than the illustrative `1`. Set `subject_request_confirmed` only after verifying the person's actual choice. The server checks that the policy version matches and records a tenant-scoped audit event.

## Approve the outside processor separately

`PUT /api/v1/operations/privacy-controls/processors` needs both `privacy:manage` and `integration:write`. The processor approval records the provider key, approved purposes and regions, origin region, retention, fallback eligibility, contract reference and digest, expiry and enabled state. The service checks expiry and purpose before sensitive provider work.

A provider with a working API key is not automatically allowed to process every purpose or send data to another region. Keep the processing route closed when the required approval is missing. [Provider integrations](provider-integrations.md) explains the separate capability and health checks.

## A request to stop reminders or outreach

If a patient asks to stop reminders, waitlist messages or follow-up, confirm the subject and the particular choices being withdrawn. An authorized appointment staff member can use:

~~~http
POST /api/v1/operations/consents/revoke
Authorization: Bearer <authorized-staff-token>
Content-Type: application/json

{"phone":"<verified-phone>","purposes":["reminder","waitlist","followup"]}
~~~

The service suppresses queued eligible messages, changes relevant opt-in records, and withdraws affected waitlist offers or follow-up enrollment. The response includes counts such as `suppressed_messages`, `released_holds` and `dispatches_inflight`.

**Already dispatched messages cannot be recalled.** The response explicitly reports in-flight work because an external provider may still deliver it. Staff should explain this limit accurately and reconcile any outgoing attempt that remains uncertain.

For independent recording, training, processing or other purpose permissions, use the purpose-specific `/privacy-controls/permissions` route with the verified subject request instead of treating every withdrawal as a reminder unsubscribe.

## Export or erase a subject's information

Confirm the identity and the clinic before acting. The staff member needs `privacy:manage` and must deliver any export through the clinic's approved secure route. The API uses a phone number to identify matching records; do not put the number in a public ticket.

~~~http
POST /api/v1/operations/privacy/export
Authorization: Bearer <privacy-authorized-staff-token>
Content-Type: application/json

{"phone":"<verified-phone>"}
~~~

The returned data can contain sensitive appointments and conversations. Record who received it and how it was transferred. Do not store the response in routine logs.

Deletion is a separate, explicit operation:

~~~http
POST /api/v1/operations/privacy/delete
Authorization: Bearer <privacy-authorized-staff-token>
Content-Type: application/json

{"phone":"<verified-phone>","confirm":true}
~~~

If no active future booking needs review, the result can be `ANONYMIZED`. If future appointments must remain to avoid an unannounced cancellation, the result is `REVIEW_REQUIRED`, with `active_bookings_retained`. Assign a person to resolve that exception. Never report the whole request as completely erased merely because an API call returned HTTP success.

The service records a tombstone and an audit event. Backups, authorized research exports and downstream processor copies need separate expiry or deletion follow-up. The privacy-controls API exposes `GET /api/v1/operations/privacy-controls/erasures` and `POST /api/v1/operations/privacy-controls/erasures/{erasure_id}/backup-evidence` for the corresponding evidence. Only record backup erasure evidence after the retained copies really expired or were erased.

## Handle a suspected disclosure or wrong recipient

If data may have reached the wrong patient, staff member, clinic or provider, stop the affected route and restrict access to the exposed records. Assign a technical responder and a privacy owner immediately. Preserve safe request IDs, time windows, recipient references and the relevant audit events without copying the underlying sensitive content into an ordinary issue.

Determine whether a message was queued, dispatched or delivered, and whether another tenant's data was actually exposed. Record what is known and unknown, the affected scope, corrective action and the owner of any required notification. Use the clinic's incident procedure for legal or contractual reporting decisions.

Privacy work is complete only when outstanding effects have owners: an in-flight message, an active booking retained for review, a backup awaiting expiry or an external processor awaiting confirmation. See [Troubleshooting](troubleshooting.md) for operational symptoms and [Deployment](deployment.md) for backup custody.
