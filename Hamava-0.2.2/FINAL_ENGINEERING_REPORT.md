# Hamava Reception — 0.2.2 source candidate and acceptance handoff

**Prepared:** 24 October 2026  
**Artifact class:** reproducible source package, **not** a signed/authorized production release  
**Provenance:** derived from the latest persisted 0.2.0 source + streaming/PBX follow-on checkpoint. The separately described 0.2.1 source and native binaries were not recovered and are **not** merged into this archive.

## What was implemented in this final engineering pass

The source includes the full pre-existing seven-phase application, Persian RTL web and companion projects, native speech/telephony workers, billing/calendar/consent controls, tests, operations tools and GitHub workflows. This pass focuses on completing software seams left in the media and deployment interfaces rather than inventing external supplier access:

1. **Screened Asterisk transfer with staff consent.** `deploy/asterisk/extensions_hamava.conf` now invokes `Dial(...,U(hamava-screened^${HAMAVA_UUID}))`. The called staff leg is explicitly asked to press `1` within eight seconds. Rejection, absent/invalid DTMF, and timeout return to the preapproved fallback; the caller is not bridged while screening. A `MASTER_CHANNEL` acceptance marker prevents mistaking a declined screening for a successful staff answer.
2. **Observable screening and bridge events.** The private AMI relay maps signed-off `HamavaStaffAccepted` and `HamavaStaffDeclined` UserEvents to a registered call UUID, PBX `Linkedid`, and allowlisted staff unique channel. It sends authenticated `SCREENED` or `SCREEN_DECLINED` observations; no patient narrative or phone number appears in the observer payload. The database reducer requires a matching dial leg and, when `PBX_REQUIRE_STAFF_SCREENING=true`, **a matching screened staff leg** plus a currently shared PBX bridge with the registered caller before declaring `CONNECTED`. A departed bridge becomes `DISCONNECTED`; AI does not resume.
3. **Strictly gated screening defaults.** Both development and production templates, including generated production secrets, specify `PBX_REQUIRE_STAFF_SCREENING=true`. This is a defense-in-depth evidence policy; it cannot itself establish which physical handset received audio. A real deployment must provision the staff prompt and verify supported Asterisk modules/features.
4. **Offline OpenAI Realtime event-semantic validation.** New `receptionist.media.realtime_contract.RealtimeProposalStream` recognizes `response.created`, function-call item and argument delta/final events, and `response.done`. It rejects cancelled/incomplete responses, mismatched response IDs, duplicate calls, oversized events, altered arguments, and invalid action schemas. It yields **non-executable proposals only after full success**. This is **not** an OpenAI Realtime WebSocket/WebRTC server, live provider session, or authorization to mutate records.
5. **Expanded protocol fixture suite.** Adds successful, cancelled and incomplete Realtime scenarios, and distinguishes a screened human bridge from an unscreened coincident bridge. All fixtures use synthetic events.
6. **Deterministic source packaging.** New `scripts/make_source_release.py` generates a manifest of SHA-256 hashes per included file, sorted deterministic ZIP entries, and excludes private environment files, databases, signing keys, recordings, dependency caches and generated binaries. The build itself is source-only and is not a publisher signature or software-bill-of-materials certification.
7. **Version, governance and traceability.** All current source-side version references use `0.2.2`, including package manifests and deployment image. All 263 original requirement rows remain intact; `MEDIA-005`, `MEDIA-015` and `RESEARCH-015` have newly reconciled follow-on evidence without silently promoting unverified live acceptance.

## Verification on these source bytes

| Test / gate | Result | Limitation |
|---|---|---|
| Focused streaming, media worker, local TTS, AMI, screening, protocol, readiness and packaging tests | **73 / 73 passed** | Python 3.13 local test runner; contract/synthetic and mock transport, not provider certification |
| Offline protocol replay | **15 / 15 passed** | Synthetic JSON/SSE, PCM and AMI events; not real Realtime or carrier hardware |
| Python syntax compilation | Passed for `backend`, `scripts`, `services`, `deploy/asterisk` | Does not import/execute missing optional dependencies |
| Cross-package version alignment | Passed | Node 22 used only for the version check; build requires Node 24 |
| GitHub workflow YAML and selected JS syntax | Parsed successfully | GitHub Actions not executed remotely; actionlint/container builds not run here |
| Production readiness guard | Exit 2, `production_ready=false` | All external gates remain unverified, by design |
| Wider backend attempted | **173 passing**, **7 dependency-related failures**, **27 collection errors** | `jdatetime` missing in this offline Python 3.13 runtime; not a passing full suite |
| Web dependency installation | Blocked (`npm ci --offline` lacks cached packages) | Node 24 and registry access needed; no current EXE/APK/AAB build |
| Python distributable wheel | Blocked (`requires-python >=3.12,<3.13`) | Current host only has Python 3.13; no 3.12 runtime obtainable offline |
| Live PBX/processor/device tests | Not performed | No Asterisk executable, SIP trunk, managed voice weights, signing identity or physical devices supplied |

The historic 485-test/13-browser-suite outcome belongs to a different earlier development snapshot. It **cannot be transferred to this release candidate**. The `0.2.0` report included in this archive is preserved for context only.

## Live deployment: critical must-pass acceptance

**This project is not qualified for unattended use with real patients.** Before enabling inbound clinic calls, an authorized operator must demonstrate all of the following on the selected service and network:

- **PBX:** control of the DID, a supported Asterisk/Issabel version and audio/DTMF modules, lawful notice, authentic AMI event registration, a recorded Persian staff offer, staff press-1 screening, actual two-way verified bridge, busy/noanswer/reject/hangup handling, and original human routing that survives AI shutdown.
- **Speech:** documented commercial rights to the chosen Persian voice weights, processor regional eligibility and contract, measured partial/final STT, real PCM TTS, cancellation and loss handling, emergency human fallback, representative narrowband digit/date accuracy, call-level latency and provider billing receipts.
- **Booking/consent:** real authorized calendar writes/reads with no silent phantom confirmations, approved clinic facts/insurance/urgent-case scripts, tenant isolation, audited user permissions, plain-language service notice, appropriate recording/training consent and lawful retention/processing arrangements.
- **Money and notifications:** actual merchant identity and signed payment webhooks, real SMS receipts and reconciliation, audited budgets, staff exception ownership and production support.
- **Release:** remote GitHub quality workflow against the exact candidate commit; Windows publisher-signed EXE verification and fresh install/upgrade/uninstall; Android publisher-signed APK/AAB and physical-device mic/Keystore/lifecycle tests; authorized store review and network/TLS/ICE/TURN acceptance.
- **Research:** do not ingest or train on patient recordings without separately approved rights; held-out, independently reviewed results and actual target hardware remain absent.

The production-readiness checker is deliberately unable to certify these gates. Evidence must be reviewed by the relevant carrier, device, legal/clinical, clinic, provider, release and research owners. Check `docs/remaining-external-acceptance.md` and `docs/requirements-follow-on.csv` for the complete register.

## Reproduction and deployment path

From the extracted `voice-receptionist/` directory, on a host with **Python 3.12** and **Node 24**:

```sh
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade -r requirements-bootstrap.txt
python -m pip install -c requirements.lock.txt '.[test,media]'
pytest -q
python scripts/protocol_conformance.py --output artifacts/backend/protocol-conformance.json
npm --prefix frontend ci
npm --prefix frontend run build
node scripts/check-versions.mjs
```

For deployment, generate an environment with `scripts/generate_env.py`, configure approved supplier and network routes, review the PBX screening dialplan, and use `verify.yml` and `release-apps.yml` on an authorized repository. **Do not set the streaming/model/provider production switches to true solely because these local tests passed.** The GitHub release workflow requires a passing quality gate and requests actual signing secrets when signing is selected.

**Deliverable claim:** inspectable, tested source candidate and explicit external acceptance handoff. **Not claimed:** a published GitHub release, signed installer, approved Iranian telecom route, real clinical trial, real speech-model training, or production-ready autonomous medical system.
