# Native streaming and verified PBX handoff — engineering acceptance

**Source checkpoint:** restored Hamava 0.2.0 archive, with follow-on integration changes. This is **not** the previously described, unpersisted 0.2.1 release. Real provider and carrier readiness is not inferred from synthetic tests. The existing buffered path stays the default.

## Streaming boundaries

| Component | New implementation | Admission constraint | Remaining live validation |
|---|---|---|---|
| Persian streaming STT | `DeepgramRealtimeSTT` consumes 16-kHz mono PCM via the documented Deepgram WebSocket, emits advisory partials, joins finalized segments, and emits one final at speech-final/utterance-end. | `SPEECH_STREAMING_APPROVED`, `SPEECH_PROCESSOR_APPROVED`, exact approved host and token, `STT_APPROVED_KEYTERMS_JSON` | Contract, vendor geography/terms, representative noisy PSTN audio, timing, numeric exactness, cost reservations, and error-recovery under network loss |
| Streamed TTS | `GatewayPCMStream` receives framed PCM from the implemented local `/synthesize/stream` Piper endpoint, checks signed-linear 16-kHz mono 20-ms packets, exact terminal byte counts, and rejects truncated/post-terminal fragments. Local Piper voice weights must be separately provisioned with approved rights. | Same processor and streaming gates, host allowlist and token | The implemented local Piper gateway has a framed streaming endpoint and a mock ASGI integration test. Real voice weights and endpoint latency/quality still require on-device and provider tests |
| Responses tool stream | `ResponsesToolStream` aggregates tool argument fragments, validates the final schema, and only yields **non-executable proposals** after response completion. | Model-stream approval and exact approved provider base/token | Selected model version, refusal/error/timeout cases, provider semantics, privacy terms, token spend, live tool-gateway orchestration |
| Native turn composition | `NativeTurnCoordinator` sends **only completed** final transcript text to the existing authenticated `/turn` endpoint and handles the authoritative result before TTS. | Separate `NATIVE_STREAMING_CALLS_APPROVED` and streaming approval; correct session token/host | Connected to the LiveKit and AudioSocket worker receive loops behind disabled-by-default gates. Real processor billing/usage receipts, VAD latency, network and interruption/reconciliation quality need production acceptance |

**Security invariants:** partial STT and model JSON fragments do not create appointments, set tenant IDs, or assert payment. A timed-out `/turn` can have committed; preserve the idempotency ID and reconcile before retry. After the server reports `HUMAN_CONNECTED`, no AI speech or automated write resumes. Audio is buffered in memory only by these adapters; recording and training remain off. Do not enable foreign processors just because a key exists.

**Activation sequence:** obtain provider terms and processing-location signoff, register and review operations/voice capabilities for the specific tenant, connect a cost-reserving worker path, run the synthetic protocol suite, then private sandbox provider tests and noisy narrowband Persian benchmark. Only afterward enable a single supervised clinic with a human fallback and defined budget. The checked-in examples keep all streaming gates false.

### Actual worker path and stream framing

Both `receptionist.media.livekit_worker.RoomAgent.listen` and
`receptionist.media.audiosocket.AudioSocketBridge._call` can optionally start
`NativeMediaTurn` when the existing VAD reaches its speech threshold. Incoming
linear16 PCM is bounded and continuously resampled to 16-kHz 20-ms frames.
`DeepgramRealtimeSTT` emits advisory partials; only a complete final transcript
is submitted once to the existing authenticated `/turn` endpoint with its
idempotency request ID. A verified response is spoken using streamed Piper PCM.
LiveKit uses 16-kHz PCM; AudioSocket resamples the output to 8-kHz 20-ms frames.
An interrupted or failed generation never triggers a new booking request.

The local `POST /synthesize/stream` endpoint emits media type
`application/x-hamava-pcm-frames`: each PCM chunk has three header bytes
(`0x10` plus a two-byte big-endian frame size of `640`) followed by signed
little-endian 16-kHz mono PCM. The terminal frame has type `0`, size `8`, and
an eight-byte big-endian audio byte count. The client rejects an absent or
mismatched terminal frame, extra bytes, or a post-terminal audio event.
An HTTP 200 without a correct terminator does **not** mean TTS succeeded.

The feature is enabled only with **both** `NATIVE_STREAMING_CALLS_APPROVED=true`
and `SPEECH_STREAMING_APPROVED=true` and the Deepgram and speech-gateway tokens.
Provider URL and processing approval, tenant scope, operator staffing, spend
controls and trial acceptance must also be approved. All example environments
leave streaming off. No call audio is persisted by this feature.

## Asterisk AMI and handoff state

The original PBX path sends a pre-approved notice, starts the authenticated AGI, and stores the same `CallUUID`, `Linkedid` and **caller** `Uniqueid` used by the AMI observer. `UserEvent(HamavaRegistered)` registers that mapping. Only the PBX, not a generative model, chooses `HUMAN_TRANSFER_TARGETS`. The AMI event observer uses a separate private `PBX_EVENT_TOKEN` and a dedicated least-privilege `PBX_AMI_USER/SECRET`.

| Event evidence | Server state | What it does **not** prove |
|---|---|---|
| Authenticated request | `QUEUED` | No ringing or human pickup |
| `DialBegin` to exact approved staff channel instance | `RINGING` | Pickup or staff audio |
| `DialEnd: ANSWER` correlated to the ringing leg | `ACCEPTED` | A bridge shared with caller |
| Caller and answered staff `BridgeEnter` on the **same** bridge without subsequent `BridgeLeave` | `CONNECTED` and AI disabled | Intelligible two-way media on every network/device |
| Busy/no-answer/rejected DialEnd, unresolved request | `FAILED` with callback/human fallback | Successful transfer |
| `BlindTransfer: Success` alone | No promotion | An answered or connected human |

Events are scoped to a registered call and its tenant, bounded in time, deduplicated by stable event ID, verified against the **exact** configured target, and rejected if the caller channel identity differs. Observed bridge-leave events transition the prior CONNECTED status to DISCONNECTED; this is not reinterpreted as AI authority or a fresh human pickup. The AMI relay intentionally fails closed after disconnection; it does not synthesize unobserved bridge events. Its memory-only mapping means missed AMI history after restart remains unverified and must be handled as a staff exception. Do not expose the AudioSocket or AMI interfaces publicly. Any remote AMI connection requires TLS, network ACLs and operator approval.

### Screened Asterisk handoff in this source candidate

The included `deploy/asterisk/extensions_hamava.conf` has a pre-bridge
`Dial(...,U(hamava-screened^...))` path. After a caller requests a human or the
AudioSocket worker exits, Asterisk dials the approved staff endpoint. The
called channel plays a locally provisioned notice, asks the **staff member**
to press `1` within eight seconds, and only then permits the bridge. Silence,
rejection, no answer and `READSTATUS != OK` fail closed to an approved caller
fallback; a staff refusal does not allow AI to resume or silently leave a
caller on hold. `MASTER_CHANNEL(HAMAVA_STAFF_SCREENED)` distinguishes staff
acceptance from a mere answered call, preventing erroneous success wording.

The PBX emits `HamavaStaffAccepted`/`HamavaStaffDeclined` AMI UserEvents with
registered UUID, Linkedid and staff leg identifiers. The private relay converts
these to authenticated `SCREENED` or `SCREEN_DECLINED` evidence. When
`PBX_REQUIRE_STAFF_SCREENING=true`, the server requires a same-leg `RINGING`,
`ACCEPTED`, `SCREENED`, simultaneous caller/staff BridgeEnter, and no later
BridgeLeave before it marks **CONNECTED**. Asterisk DialEnd alone is not enough.
This flag is true in both example environment files and generated production
environments. Preserve that policy in real deployments.

**Provisioning required:** the PBX operator must record and install
`custom/hamava-screened-offer` (e.g. «تماس از هم‌آوا برای پذیرش است؛ برای قبول
و اتصال به تماس‌گیرنده عدد یک را فشار دهید») and
`custom/hamava-staff-unavailable`, verify `Read`, `Dial U`, `UserEvent`,
`MASTER_CHANNEL` and the correct manager read privileges on the deployed
Asterisk version, and demonstrate actual two-way staff audio, busy, reject,
caller hangup and reconnection on contracted routes. A staff member can see
clinic-scoped context in the existing dashboard; the pre-bridge prompt does
not disclose patient details. This is a **screened handoff implementation**,
not carrier/handset acceptance or a generic multi-party attended SIP transfer.

This implements a concrete supervised transfer bridge path in the included
Asterisk dialplan, while physical PBX/carrier and staff-consent acceptance
remain open. Other PBX vendors require their own contract-specific integration.


## Synthetic conformance suite

Run:

```bash
PYTHONPATH=backend python scripts/protocol_conformance.py \
  --fixtures fixtures/protocol --output artifacts/backend/protocol-conformance.json
```

The offline suite exercises the implementation with synthetic Deepgram-style JSON, Responses SSE semantic events, OpenAI Realtime response/tool semantic events, framed PCM, and AMI call/bridge events. Additional focused tests run actual worker-loop integration over synthetic RTC/AudioSocket frames and connect the speech service to the PCM client via an ASGI transport. It records only case IDs, fixture hashes and status codes, **not** simulated patient utterances or secrets. These fixtures do not prove a provider is accessible, that a client is compatible with OpenAI's distinct Realtime event/WebRTC protocol, that carrier call recording is lawful, or that a patient call is intelligible.

Reference designs: [Deepgram streaming](https://developers.deepgram.com/reference/speech-to-text/listen-streaming), [OpenAI Responses streaming event definitions](https://developers.openai.com/api/reference/resources/responses/streaming-events), [Asterisk AMI](https://docs.asterisk.org/Configuration/Interfaces/Asterisk-Manager-Interface-AMI/AMI-v2-Specification/).
