# External launch and research acceptance gates

No locally generated ZIP, unsigned executable, synthetic speech fixture or document may be promoted into a signed release, clinic approval, legal permission or successful Persian model benchmark. **The missing parties and networks must provide independent evidence.**

| Gate | Concrete owner-provided input | Acceptance test and durable evidence |
|---|---|---|
| Authorized GitHub CI | Destination repo with authorized write access, commit and chosen release tag | Actual `verify.yml` and `release-apps.yml` runs, linked logs, final source commit and artifact digests |
| Windows publisher | Publisher certificate, protected credentials, target Windows 10/11 devices | Authenticode verification of every EXE, installer fresh install, upgrade, first launch/login, uninstall, rollback and SmartScreen policy review |
| Android publisher/store | Keystore/Play App Signing account and devices | Signed APK/AAB verified against declared cert, debug vs release isolation, install/upgrade/logout, mic and secure storage, Android 13–16, store review/acceptance |
| Iranian PSTN and human fallback | Carrier trunk/SBC specification, PBX target, staff operator and DID authority | Answer/transfer/noanswer, packet loss, SIP codec/DTMF, 8-kHz narrowband, bridge membership, intelligible staff audio, fail-back with the AI stopped |
| Clinic onboarding/UAT | Legal controller, approved clinic catalog, authorized scheduler, staff training and backup contacts | Real sandbox then supervised bookings, date/phone exactness, double-booking test, real schedule readback and staff handoff signoff |
| Privacy and clinical safety | Qualified local counsel and clinical reviewer for the deployed system | Actual notice/call recording/messaging/retention/processor contract review and approved urgency script; prohibit training by default |
| Supplier and network | Calendar write authorization, SMS/payment receipts, speech geography/rights and local network | Signed webhook and reconcile failures, failed SMS state, provider cutover and rollback, TLS/ICE/TURN and target mobile operators |
| Speech-model research | Rights-cleared datasets, provenance, independent held-out speakers/tenants, lawful compute and model license | Evaluate number/date exactness, WER/CER, percentile latency/cost per codec/accent; supervised fine-tuning only after eligibility check; regression and withdrawal tests |

Machine-readable evidence inventory (not a certificate):

```bash
python scripts/launch_readiness.py --evidence-dir /private/acceptance \
  --manifest /private/acceptance/evidence-manifest.json \
  --output /private/acceptance/hamava-readiness.json
```

The checker defaults every gate to `MISSING`. A real, hash-matching evidence file is marked `EVIDENCE_SUBMITTED_REVIEW_REQUIRED`, **never production-ready**; a missing/mismatched/out-of-root file is rejected. Only authorized humans and real supplier/staff observations can close these gates. Do not check credentials, patient audio or clinical records into source control.

## Integration-specific acceptance additions (October 2026)

Before any clinic enables streaming, execute a session on the **actual**
contracted Persian processor: caller speech and pauses -> Deepgram streaming
final/interim -> authenticated `/turn` -> licensed Piper 16-kHz framed output ->
LiveKit/AudioSocket playback. Record the approved processor account/geography,
model/voice license, latency distribution and exact-name/digit/date quality.
Re-run disconnection, barge-in, expiry, human presence, budget exhaustion and
network-failure fixtures; preserve idempotency keys and reconcile uncertain
writes before allowing new bookings.

For PBX, a **screened Asterisk pre-bridge transfer** is implemented but has
not been qualified on a real PBX, trunk or handset. Provision the staff DTMF
prompt and run the selected Asterisk version/carrier contract with staff press
`1`, rejected/absent DTMF, ring, answer, actual bridge membership and
intelligible two-way media; busy,
no-answer and interrupted transfer; early caller hangup; duplicate/out-of-order
AMI events and relay reconnect. Require a staffed target and a verified callback
alternative. Do not turn on automated phone answering if the original human
line cannot continue to work when the media service is stopped.

Once signed publisher credentials and actual devices exist, execute the
repository's `verify.yml` and `release-apps.yml` against the target commit, verify
the resulting EXE/APK/AAB signatures and hashes, and test fresh install, upgrade,
login/logout, microphone permission, secure storage and uninstall. Evidence must
be independently reviewed by the relevant clinic, legal, telecom and release
owners; `scripts/launch_readiness.py` will never self-certify approval.
