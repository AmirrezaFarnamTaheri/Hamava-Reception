# Accept a clinic configuration for production

[فارسی](clinic-acceptance.fa.md) · [Documentation](README.md) · [Operations](operations.md)

Production activation depends on the exact clinic configuration being tested. A receptionist may have used Hamava successfully in a demo, but that does not establish that a particular service catalog, schedule, payment policy and handoff route are safe to use together.

The production gate in `backend/receptionist/operations_uat.py` is an **operator attestation of five synthetic checks**. An owner or administrator records the evidence and approves a configuration fingerprint. The system checks whether that attestation is current; it cannot judge whether the evidence is convincing or whether a real carrier, bank or clinic has independently accepted the service.

## Before running the checks

Keep automated intake **paused** while setting up a clinic. Confirm its timezone, practitioners, working hours, service durations and buffers, shared resources, closures, payment policy and approved answers. Identify the receptionist who will receive callbacks and the technical owner who can stop the service.

Choose the intended mode before testing. Valid acceptance targets are `after_hours`, `overflow`, `human_primary`, `supervised` and `ai_primary`. The `paused` mode does not need an activation attestation. A production catalog change requires pausing automated intake first; otherwise the server can return `PAUSE_BEFORE_CATALOG_CHANGE`.

Run the checks with synthetic contacts and appointments in a controlled environment. Keep the evidence in the clinic's approved private review location, not in Git, a public issue or an API request body.

## Run the five checks against the intended configuration

| Check | What the operator must demonstrate | Evidence to retain |
| --- | --- | --- |
| `booking` | A valid service and practitioner can be selected, confirmed and read back as the correct appointment state | Synthetic appointment reference and observed result |
| `cancellation` | A permitted cancellation changes the intended booking and its occupancy without affecting another booking | Before/after appointment references |
| `conflict` | Two incompatible requests cannot both occupy the same provider or shared resource; a stale version is rejected | Test run and rejected result |
| `provider_failure` | A configured external service failure or unknown write remains visible, recoverable and does not produce false confirmation | Synthetic failure case and reconciliation/task reference |
| `handoff` | A request that needs staff creates the appropriate task or transfer flow; a requested transfer is not mislabeled as a connected call | Staff task or controlled handoff result |

Record the result, code revision, configuration and reviewer for each check. A previous clinic's evidence does not cover a different clinic. If a check fails, repair the underlying issue and rerun the affected path before requesting approval.

## Read the fingerprint and record approval

An authorized owner or administrator reads:

~~~http
GET /api/v1/operations/uat?target_mode=after_hours
Authorization: Bearer <staff-access-token>
~~~

The response includes `configuration_fingerprint`, `required_checks`, `approved`, `production_enforced` and any current attestation. A fingerprint is a hash of the clinic's mode, published settings and catalog, selected extensions and latest payment-policy publication. It is not a secret.

Once the reviewer has independently checked the evidence, approval has this shape:

~~~http
POST /api/v1/operations/uat/approve
Authorization: Bearer <staff-access-token>
Content-Type: application/json

{
  "target_mode": "after_hours",
  "configuration_fingerprint": "<fingerprint-from-current-GET>",
  "checks": {
    "booking": true,
    "cancellation": true,
    "conflict": true,
    "provider_failure": true,
    "handoff": true
  },
  "evidence_refs": {
    "booking": "<private-evidence-reference>",
    "cancellation": "<private-evidence-reference>",
    "conflict": "<private-evidence-reference>",
    "provider_failure": "<private-evidence-reference>",
    "handoff": "<private-evidence-reference>"
  },
  "confirmed": true
}
~~~

This is a request **format**, not a completed attestation. Never fill all checks with `true` to bypass a gate. Each reference must identify real, reviewed evidence without patient data. The endpoint rejects incomplete checks or missing references.

Read the UAT endpoint again with the same target mode. The response must show `approved: true` for the current fingerprint.

To activate that approved mode, read the clinic's settings, then submit the current version through the authorized settings route:

~~~http
GET /api/v1/settings
Authorization: Bearer <staff-access-token>
~~~

~~~http
PUT /api/v1/settings
Authorization: Bearer <policy-authorized-staff-token>
Content-Type: application/json

{"version":1,"mode":"after_hours"}
~~~

The `version: 1` above is **illustrative**. Replace it with the `settings_version` returned by the preceding GET. The change requires `policy:write`; if it fails with `STALE_VERSION`, read settings again. If it fails with `CLINIC_UAT_REQUIRED`, the current configuration has no matching approval. Do not bundle an unreviewed service or policy change into the same request. Read settings again to confirm the published mode and complete a supervised workflow check.

## When the approval stops applying

Attestations last **30 days**. The fingerprint also changes when relevant clinic settings, catalog entries, extensions or payment-policy publication change. The system can reject activation with `CLINIC_UAT_REQUIRED` or approval of stale evidence with `STALE_UAT_CONFIGURATION`. Read the new fingerprint, repeat the affected checks and approve the new state. Do not reuse a previous attestation ID.

Approval does not replace live integration acceptance. A clinic using real telephone transfers still needs an observed two-way call; SMS needs a delivery result; payment needs trusted settlement evidence; external calendars need authoritative readback. Use [Provider integrations](provider-integrations.md) for those checks and [Deployment](deployment.md) for backups and recovery.

If production safety becomes uncertain, pause automated intake and assign a human owner to the outstanding work. Preserve pending external operations for reconciliation. A new attestation cannot retroactively confirm an uncertain booking or payment.
