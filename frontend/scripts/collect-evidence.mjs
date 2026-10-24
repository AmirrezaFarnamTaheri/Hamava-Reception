import { readFile, writeFile, mkdir, stat } from "node:fs/promises";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import assert from "node:assert/strict";
const frontend = fileURLToPath(new URL("../", import.meta.url));
const root = resolve(frontend, "..");
const input = process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamaava-ui-validation";
const destination = resolve(root, "docs/validation");
await mkdir(destination, { recursive: true });
const digest = (value) => createHash("sha256").update(value).digest("hex");
const suites = {
  audit: "check-ui.mjs",
  workflows: "exercise-workflows.mjs",
  conversation: "exercise-conversation.mjs",
  audio: "exercise-audio.mjs",
  extensions: "exercise-extensions.mjs",
  outreach: "exercise-outreach.mjs",
  "live-ui": "exercise-live-ui.mjs",
  release: "exercise-release.mjs",
  "waitlist-deposit": "exercise-waitlist-deposit.mjs",
  "privacy-notice": "exercise-privacy-notice.mjs",
  "rtc-lifecycle": "exercise-rtc-lifecycle.mjs",
};
const expectedChecks = {
  workflows: 10,
  conversation: 5,
  audio: 5,
  extensions: 13,
  outreach: 8,
  "live-ui": 6,
  release: 7,
  "waitlist-deposit": 8,
  "privacy-notice": 5,
  "rtc-lifecycle": 12,
};
function inspectSecrets(value, path = "report") {
  if (Array.isArray(value))
    return value.forEach((item, index) =>
      inspectSecrets(item, path + "." + index),
    );
  if (value && typeof value === "object")
    return Object.entries(value).forEach(([key, item]) => {
      assert(
        !/^(access_token|refresh_token|authorization|api_key|token|password|secret)$/i.test(
          key,
        ),
        "Credential field at " + path + "." + key,
      );
      inspectSecrets(item, path + "." + key);
    });
  if (typeof value === "string")
    assert(
      !/(Bearer\s+[A-Za-z0-9._-]{12}|eyJ[A-Za-z0-9_-]{15,}\.|DemoReception2026!)/.test(
        value,
      ),
      "Credential value at " + path,
    );
}
const copied = [];
for (const [name, script] of Object.entries(suites)) {
  const source = resolve(input, name + ".json");
  const raw = await readFile(source, "utf8"),
    report = JSON.parse(raw);
  assert(!report.failure, name + " failed: " + report.failure);
  if (name === "audit")
    assert(
      (report.results?.length || 0) >= 40,
      "Audit did not finish the complete screen matrix",
    );
  else
    assert(
      (report.checks?.length || 0) >= expectedChecks[name],
      name + " did not finish its expected workflows",
    );
  assert.equal(report.errors?.length || 0, 0, name + " has runtime errors");
  assert.equal(
    report.unexpectedRequests?.length || 0,
    0,
    name + " has unexpected contract requests",
  );
  assert.equal(
    report.failedResponses?.length || 0,
    0,
    name + " has failed API responses",
  );
  for (const item of report.results || []) {
    assert.equal(item.audit.length, 0, name + " accessibility findings");
    assert(
      item.layout.scroll <= item.layout.viewport,
      name + " viewport overflow",
    );
  }
  for (const item of report.audits || [])
    assert.equal(
      item.findings.length,
      0,
      name + " dialog accessibility findings",
    );
  inspectSecrets(report);
  const file = "browser-" + name + ".json";
  const metadata = {
    schema_version: "1.0",
    suite: name,
    captured_at: new Date((await stat(source)).mtimeMs).toISOString(),
    source_script: "frontend/scripts/" + script,
    current_source_script_sha256: digest(
      await readFile(resolve(frontend, "scripts", script)),
    ),
    report_sha256: digest(raw),
    validation_environment:
      "Local headless Chromium against isolated synthetic demo API",
    scope:
      "Observed browser behavior only. No iOS/Android device, carrier, real vendor settlement/delivery, native-listener quality or production capacity qualification.",
    ...report,
  };
  await writeFile(
    resolve(destination, file),
    JSON.stringify(metadata, null, 2) + "\n",
  );
  copied.push("docs/validation/" + file);
}
const registerText = await readFile(
  resolve(root, "docs/requirements.json"),
  "utf8",
);
const register = JSON.parse(registerText);
const evidence = (name) => "docs/validation/browser-" + name + ".json";
const mappings = {
  "CONSOLE-001": [
    "Persian RTL and mixed-direction fields render without document overflow at desktop, 390px and 320px widths.",
    ["frontend/src/style.css", evidence("audit")],
    [
      "Physical mobile browser and native assistive-technology qualification is tracked separately.",
    ],
  ],
  "CONSOLE-002": [
    "Overview prioritizes today's appointments, active call controls, open tasks, failed notices and honest configured-service statuses.",
    ["frontend/src/pages/Overview.tsx", evidence("audit")],
    [
      "Configured readiness is not a claim of live provider health or carrier availability.",
    ],
  ],
  "CONSOLE-003": [
    "Scoped live-call cards render masked contact, clinic, intent, state and observed duration; no raw transcript/context dump.",
    ["frontend/src/LiveCalls.tsx", evidence("extensions")],
  ],
  "CONSOLE-004": [
    "Claim uses the authoritative versioned task action; UI merges the returned version before another action and disables concurrent local actions.",
    ["frontend/src/pages/TaskQueue.tsx", evidence("extensions")],
    [
      "Cross-process atomic ownership is established by the backend task-concurrency tests, not inferred from one browser.",
    ],
  ],
  "CONSOLE-005": [
    "Task UI supports claim, reassign/redirect, pending, callback, resolve, reject and reopen with reasons and permission-aware controls; callback/resolve/reopen were exercised.",
    ["frontend/src/pages/TaskQueue.tsx", evidence("extensions")],
    [
      "All server transition/concurrency permutations belong to backend regression evidence.",
    ],
  ],
  "CONSOLE-006": [
    "Takeover displays callback/requested versus room-ready; actual browser RTC needs explicit microphone action and connected state follows a successful room connection.",
    [
      "frontend/src/LiveCalls.tsx",
      evidence("live-ui"),
      "docs/validation/livekit-loopback.json",
      evidence("rtc-lifecycle"),
    ],
    [
      "Real carrier warm transfer and staff/device acceptance remain external UAT.",
    ],
  ],
  "CONSOLE-007": [
    "Statuses distinguish confirmed, review, deposit pending, canceled, expired and failed; pending payment includes the authoritative expiry.",
    [
      "frontend/src/components.tsx",
      "frontend/src/pages/Appointments.tsx",
      evidence("workflows"),
    ],
  ],
  "CONSOLE-008": [
    "Staff booking, move and cancellation use signed offers and version/idempotency protected authoritative APIs; real synthetic workflow passed.",
    ["frontend/src/pages/Appointments.tsx", evidence("workflows")],
  ],
  "CONSOLE-009": [
    "Labeled forms, native dialog focus, keyboard settings tabs, mobile menu focus trap/Escape restoration, live statuses and axe WCAG checks are implemented and exercised.",
    [
      "frontend/src/components.tsx",
      "frontend/src/App.tsx",
      evidence("audit"),
      evidence("extensions"),
    ],
    [
      "Automated axe and keyboard checks are not a full screen-reader usability certification.",
    ],
  ],
  "CONSOLE-010": [
    "Public consent, start/end, text fallback, correction/repeat/slow controls, real recording and trusted audio, live mute/disconnect and human request are implemented.",
    [
      "frontend/src/pages/Talk.tsx",
      evidence("conversation"),
      evidence("rtc-lifecycle"),
      evidence("audio"),
      evidence("live-ui"),
    ],
  ],
  "CONSOLE-011": [
    "Offline notice, polled error/retry, stale overview labeling and media disconnection states avoid claiming fresh availability; reconnect refreshes remote data.",
    [
      "frontend/src/hooks.ts",
      "frontend/src/components.tsx",
      "frontend/src/LiveCalls.tsx",
      evidence("audit"),
      evidence("conversation"),
    ],
  ],
  "CONSOLE-012": [
    "Daily digest renders verified bookings, attendance, cancellations, waitlist fills, current open-case backlog and actual usage with definitions.",
    ["frontend/src/pages/DailyDigest.tsx", evidence("extensions")],
  ],
  "CONSOLE-013": [
    "Building UI renders only server-scoped aggregate counts and authorized contract allocations, with no patient listing in aggregate views.",
    [
      "frontend/src/pages/Reports.tsx",
      "frontend/src/pages/BuildingContracts.tsx",
      evidence("extensions"),
    ],
  ],
  "CONSOLE-014": [
    "Clinic switching replaces the scoped credential and remounts patient/task/settings state; switches and separate partner scope were exercised.",
    [
      "frontend/src/App.tsx",
      evidence("workflows"),
      evidence("extensions"),
      evidence("release"),
    ],
  ],
  "CONSOLE-015": [
    "All six automation modes have understandable Persian controls and descriptions; production readiness is explicit and no mode selection silently provisions telephony.",
    [
      "frontend/src/pages/Settings.tsx",
      "frontend/src/pages/LaunchReadiness.tsx",
      evidence("audit"),
      evidence("release"),
    ],
    ["Actual mode routing behavior is covered by backend voice/UAT tests."],
  ],
  "CONSOLE-016": [
    "Staff corrections require reason and explicit confirmation; contact correction resets outreach consent. Caller correction uses trusted conversational turns before a fresh final confirmation.",
    [
      "frontend/src/pages/Appointments.tsx",
      "frontend/src/pages/Talk.tsx",
      evidence("extensions"),
      evidence("conversation"),
    ],
  ],
  "CONSOLE-017": [
    "Application manifest and local fonts are provided; there is no service worker or patient-record offline cache, and offline UI never fabricates committed bookings.",
    [
      "frontend/public/manifest.webmanifest",
      "frontend/README.md",
      evidence("audit"),
      evidence("conversation"),
    ],
    [
      "Installability and behavior on actual target mobile OS/browser versions require the device matrix.",
    ],
  ],
  "TENANT-001": [
    "Owner creates a scoped clinic through UI; persisted hours/catalog forms and an incomplete draft checklist allow returning after reload without YAML edits.",
    [
      "frontend/src/pages/Catalog.tsx",
      "frontend/src/pages/Settings.tsx",
      evidence("release"),
    ],
  ],
  "TENANT-006": [
    "Policy UI shows prior versions and requires an explicit reason/confirmation to restore a reviewed snapshot as a new version.",
    ["frontend/src/pages/Policies.tsx", evidence("extensions")],
  ],
  "TENANT-011": [
    "Human-first, after-hours, overflow, supervised, AI-first and paused settings are exposed with their true behavior descriptions.",
    ["frontend/src/pages/Settings.tsx", evidence("audit")],
    [
      "Production activation and actual call routing are backend/deployment responsibilities.",
    ],
  ],
  "TENANT-014": [
    "Clinic launch review requires five independently identified evidence references, unchecked confirmations, target mode and configuration binding. Browser test verifies incomplete forms do not attest.",
    ["frontend/src/pages/LaunchReadiness.tsx", evidence("release")],
    [
      "No real clinic, carrier, clinical or legal approval was created by the browser tests; backend exact-binding tests provide enforcement evidence.",
    ],
  ],
  "PARTNER-002": [
    "Owner grants/revokes scoped partner access; partner login has a separate aggregate-only dashboard and clinic switch.",
    [
      "frontend/src/pages/Management.tsx",
      "frontend/src/pages/Partner.tsx",
      evidence("extensions"),
    ],
  ],
  "PARTNER-003": [
    "Published identity, brand name/color and bounded pronunciation are configured in owner settings; safe public identity is consumed by the caller page.",
    [
      "frontend/src/pages/Management.tsx",
      "frontend/src/pages/Talk.tsx",
      evidence("extensions"),
    ],
    [
      "Vendor voice selection/rights and representative audible brand quality require separate provider evidence.",
    ],
  ],
  "PARTNER-004": [
    "Owner creates bounded scoped API keys, sees a key once, and can revoke it; list responses never redisclose credentials. Permissioned usage CSV export is implemented.",
    [
      "frontend/src/pages/Management.tsx",
      "frontend/src/pages/Reports.tsx",
      evidence("extensions"),
    ],
    [
      "External connector versioning/deprecation and partner API conformance are assessed in backend/provider evidence.",
    ],
  ],
  "PARTNER-006": [
    "Digest destination form requires recipient consent reference and explicit enable/automatic-daily choices; queue and delivery status distinguish provider acceptance from delivery. Create/disable was exercised without sending reports.",
    ["frontend/src/pages/DigestDestinations.tsx", evidence("extensions")],
    [
      "No platform message was transmitted; platform rights, account provisioning and final delivery remain external gates.",
    ],
  ],
  "PARTNER-007": [
    "Purpose-specific revocation and channel-specific permission forms preserve explicit consent boundaries; the synthetic opt-out flow preserved appointment records.",
    [
      "frontend/src/pages/ConsentRevocation.tsx",
      "frontend/src/pages/Outreach.tsx",
      evidence("outreach"),
    ],
    [
      "Actual multi-platform delivery/suppression is enforced and tested by server adapters and external platform UAT.",
    ],
  ],
  "PARTNER-009": [
    "Unconfigured providers are visibly unconfigured; demo/configured status is not labeled live, retries preserve errors, and public mic/RTC is capability-gated.",
    [
      "frontend/src/pages/Settings.tsx",
      "frontend/src/pages/Talk.tsx",
      evidence("audit"),
      evidence("live-ui"),
    ],
  ],
  "MEDIA-008": [
    "Real MediaRecorder and LiveKit JS connection, mute, end, track release and typed fallback were observed against local speech/RTC. Caller and staff reconnect states, initial microphone readiness, preserved mute, terminal disconnect, stale-room ownership and delayed-operation cleanup now have separately labeled browser SDK-event-contract coverage.",
    [
      "frontend/src/pages/Talk.tsx",
      "frontend/src/LiveCalls.tsx",
      "frontend/src/rtcLifecycle.ts",
      evidence("audio"),
      evidence("live-ui"),
      evidence("rtc-lifecycle"),
    ],
    [
      "Full MEDIA-008 acceptance remains partial: the new reconnect test injects API/SDK events and does not establish actual-network reconnection, media continuity, or mobile background/lock recovery. Those require actual transport and device UAT.",
    ],
    "implemented_unverified",
  ],
  "MEDIA-UAT-004": [
    "Desktop Chromium with mobile-sized viewports was tested, including microphone lifecycle and local RTC. This does not satisfy the physical mobile browser matrix.",
    [evidence("audit"), evidence("audio"), evidence("live-ui")],
    [
      "iOS Safari, Android Chrome hardware, in-app browsers, real lock/background/reconnect, Bluetooth and native assistive technology have not been qualified.",
    ],
    "blocked_external",
  ],
  "BILLING-004": [
    "Owner creates an authorized draft building pool and reviews balanced usage allocation; UI explicitly states no charge or settlement is performed.",
    ["frontend/src/pages/BuildingContracts.tsx", evidence("extensions")],
    [
      "Signed building/clinic commercial terms and live invoicing approval remain external.",
    ],
  ],
  "PAYMENT-001": [
    "Owner publishes versioned deposit/cancellation/refund terms with explicit confirmation; public safe terms omit merchant identity; staff booking and both waitlist acceptance paths send separately accepted current terms. Waitlist deposit results remain pending payment with a capped expiry.",
    [
      "frontend/src/pages/PaymentPolicy.tsx",
      "frontend/src/pages/Appointments.tsx",
      "frontend/src/pages/Talk.tsx",
      "frontend/src/pages/Waitlist.tsx",
      evidence("release"),
      evidence("waitlist-deposit"),
    ],
    [
      "The browser exercise used synthetic policy publication. Actual merchant/provider and legal validation remain external; backend tests enforce actual-mode acceptance.",
    ],
  ],
  "WAITLIST-005": [
    "Authenticated staff accepts only after explicit patient time confirmation and, for a deposit, separate acceptance of freshly loaded versioned terms. Reload and stale-terms failure clear financial acceptance. Immediate and resumed real demo API acceptance were exercised.",
    [
      "frontend/src/pages/Waitlist.tsx",
      evidence("workflows"),
      evidence("waitlist-deposit"),
    ],
    [
      "The browser suite verifies the UI contribution and injects one stale-terms response for recovery coverage. Actual stale-policy rejection, offer authorization and concurrent atomic acceptance are established independently by backend tests.",
    ],
  ],
  "PRIVACY-003": [
    "Public consent renders the exact server notice and configured retention days, distinguishing unretained raw audio from encrypted necessary conversation text and request-recovery results. It describes scheduled cleanup, deletion requests and separate necessary appointment records. The same notice is keyboard accessible during conversation; consent sends recording and training disabled.",
    [
      "frontend/src/pages/Talk.tsx",
      "frontend/src/types.ts",
      evidence("privacy-notice"),
    ],
    [
      "This verifies truthful disclosure and UI consent behavior. Actual retention/deletion processing, provider policy and legal review are independently validated by server tests and deployment approval.",
    ],
  ],
};
const assessed = Object.entries(mappings).map(
  ([id, [behavior, sources, remaining = [], status = "verified_local"]]) => {
    const item = register.requirements.find((row) => row.id === id);
    assert(item, "Unknown requirement " + id);
    return {
      id,
      title: item.title,
      acceptance: item.acceptance,
      status,
      verification_level:
        status === "blocked_external"
          ? "local_evidence_insufficient_for_external_acceptance"
          : "local_browser_test_or_code_inspection",
      verified_behavior: behavior,
      evidence: sources,
      remaining_acceptance: remaining,
      external_dependencies: item.external_dependencies || [],
      assessor: "frontend",
      scope:
        "UI contribution only; merge server enforcement and external readiness evidence independently.",
    };
  },
);
await writeFile(
  resolve(destination, "frontend-requirement-evidence.json"),
  JSON.stringify(
    {
      schema_version: "1.0",
      title: "Frontend requirement evidence proposal",
      generated_at: new Date().toISOString(),
      source_register: "docs/requirements.json",
      source_register_sha256: digest(registerText),
      source_blueprint_sha256: register.source_sha256,
      updates_main_register: false,
      verified_live_supplier_claims: false,
      interpretation:
        "verified_local applies to the explicitly observed browser behavior and named source inspection. Remaining acceptance and external qualification are not inferred from UI implementation or synthetic transport tests.",
      test_trace_files: copied,
      requirements: assessed,
    },
    null,
    2,
  ) + "\n",
);
console.log(
  JSON.stringify(
    {
      copied,
      assessed_requirements: assessed.length,
      credential_scan: "passed",
      output: "docs/validation/frontend-requirement-evidence.json",
    },
    null,
    2,
  ),
);
