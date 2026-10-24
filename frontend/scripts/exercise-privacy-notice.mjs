import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright"),
  packaged = require("@sparticuz/chromium");
const base = process.env.HAMAAVA_BASE_URL || "http://127.0.0.1:8000";
const output =
  process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamaava-ui-validation";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  args: packaged.args.filter(
    (arg) =>
      ![
        "--single-process",
        "--disable-web-security",
        "--allow-running-insecure-content",
        "--disable-site-isolation-trials",
      ].includes(arg),
  ),
  executablePath:
    process.env.CHROMIUM_EXECUTABLE || (await packaged.executablePath()),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  locale: "fa-IR",
  reducedMotion: "reduce",
  bypassCSP: true,
});
await context.addInitScript(() => {
  window.__privacyMicrophoneRequests = 0;
  const original = navigator.mediaDevices?.getUserMedia.bind(
    navigator.mediaDevices,
  );
  if (original)
    navigator.mediaDevices.getUserMedia = (...args) => {
      window.__privacyMicrophoneRequests++;
      return original(...args);
    };
});
const page = await context.newPage();
page.setDefaultTimeout(60000);
const checks = [],
  errors = [],
  audits = [];
let failure, retentionDays;
let sessionRequests = 0;
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (request) => {
  if (
    new URL(request.url()).pathname === "/api/v1/public/sessions" &&
    request.method() === "POST"
  )
    sessionRequests++;
});
function passed(name) {
  checks.push(name);
  console.log(JSON.stringify({ passed: name }));
}
async function inspect(label) {
  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const result = await page.evaluate(async () => ({
    findings: (
      await window.axe.run(document, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
      })
    ).violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      count: item.nodes.length,
      targets: item.nodes.map((node) => node.target),
    })),
    viewport: window.innerWidth,
    width: document.documentElement.scrollWidth,
  }));
  audits.push({ label, ...result });
  assert.equal(result.findings.length, 0, label + " accessibility findings");
  assert(result.width <= result.viewport, label + " overflow");
}
try {
  const login = await context.request.post(base + "/api/v1/auth/login", {
    data: { email: "owner@example.test", password: "DemoReception2026!" },
  });
  assert(login.ok());
  const auth = await login.json();
  const integrations = await context.request.get(
    base + "/api/v1/operations/integrations",
    { headers: { Authorization: "Bearer " + auth.access_token } },
  );
  assert(integrations.ok());
  assert.equal(
    (await integrations.json()).mode,
    "demo",
    "Session exercise is limited to synthetic demonstration mode",
  );
  const response = await context.request.get(
    base + "/api/v1/public/clinics/bahar",
  );
  assert(response.ok());
  let clinic = await response.json();
  assert.match(clinic.processing_notice_fingerprint, /^[a-f0-9]{64}$/);
  retentionDays = clinic.transcript_retention_days;
  assert(Number.isInteger(retentionDays) && retentionDays >= 0);
  assert(clinic.notice.includes("صدای خام ذخیره نمی‌شود"));
  assert(clinic.notice.includes("رمزگذاری‌شده"));
  assert(clinic.notice.includes("بازیابی درخواست‌ها"));
  assert(clinic.notice.includes("درخواست حذف"));
  assert(clinic.notice.includes("برنامه زمان‌بندی‌شده"));
  await page.goto(base + "/talk/bahar", { waitUntil: "networkidle" });
  await page
    .locator(".consent-box")
    .getByText(clinic.notice, { exact: true })
    .waitFor();
  let period = new Intl.NumberFormat("fa-IR", {
    maximumFractionDigits: 0,
  }).format(retentionDays);
  assert(
    (await page.locator(".privacy-retention").innerText()).includes(period),
  );
  passed(
    "Before consent, the exact server notice distinguishes transient raw audio from encrypted recovery text, deletion requests and scheduled retention",
  );
  for (const [width, height] of [
    [1440, 1000],
    [390, 844],
    [320, 740],
  ]) {
    await page.setViewportSize({ width, height });
    assert(
      await page
        .getByRole("button", { name: "شروع گفتگو", exact: true })
        .isDisabled(),
    );
    assert.equal(
      await page.getByRole("checkbox", { checked: true }).count(),
      0,
    );
    await inspect("Public consent notice at " + width + "px");
  }
  await page.screenshot({
    path: output + "/privacy-notice-320.png",
    fullPage: true,
  });
  passed(
    "Desktop, 390px and 320px disclosures have no accessibility findings or horizontal overflow; consent starts unchecked",
  );
  // Exercise a real stale-consent race against this suite's isolated synthetic tenant.
  await page.getByRole("checkbox").check();
  const settings = await context.request.get(base + "/api/v1/settings", {
    headers: { Authorization: "Bearer " + auth.access_token },
  });
  assert(settings.ok());
  const currentSettings = await settings.json();
  assert(
    retentionDays > 1,
    "The synthetic fixture needs a shorten-able retention period",
  );
  const changed = await context.request.put(base + "/api/v1/settings", {
    headers: { Authorization: "Bearer " + auth.access_token },
    data: {
      version: currentSettings.settings_version,
      retention_days: retentionDays - 1,
    },
  });
  assert(changed.ok(), "Synthetic retention policy change must be accepted");
  const [stale] = await Promise.all([
    page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/v1/public/sessions" &&
        r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "شروع گفتگو", exact: true }).click(),
  ]);
  assert.equal(stale.status(), 409);
  assert.equal((await stale.json()).detail.code, "PROCESSING_NOTICE_CHANGED");
  assert.equal(
    stale.request().postDataJSON().processing_notice_fingerprint,
    clinic.processing_notice_fingerprint,
  );
  const refreshed = await context.request.get(
    base + "/api/v1/public/clinics/bahar",
  );
  assert(refreshed.ok());
  const updated = await refreshed.json();
  assert.notEqual(
    updated.processing_notice_fingerprint,
    clinic.processing_notice_fingerprint,
  );
  await page
    .locator(".consent-box")
    .getByText(updated.notice, { exact: true })
    .waitFor();
  await page.waitForLoadState("networkidle");
  assert.equal(await page.getByRole("checkbox").isChecked(), false);
  assert(
    await page
      .getByRole("button", { name: "شروع گفتگو", exact: true })
      .isDisabled(),
  );
  assert.equal(
    await page.getByRole("textbox", { name: "پیام شما", exact: true }).count(),
    0,
  );
  assert.equal(
    sessionRequests,
    1,
    "A changed notice must never auto-retry consent",
  );
  await inspect("Changed privacy notice requires fresh consent at 320px");
  clinic = updated;
  retentionDays = updated.transcript_retention_days;
  period = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 0 }).format(
    retentionDays,
  );
  passed(
    "A real policy change rejects the displayed old fingerprint, refreshes the notice, clears consent and never auto-starts a session",
  );
  await page.getByRole("checkbox").check();
  const [started] = await Promise.all([
    page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/v1/public/sessions" &&
        r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "شروع گفتگو", exact: true }).click(),
  ]);
  assert(started.ok());
  const submitted = started.request().postDataJSON();
  assert.equal(submitted.processing_consent, true);
  assert.equal(
    submitted.processing_notice_fingerprint,
    clinic.processing_notice_fingerprint,
  );
  assert.equal(submitted.recording_consent, false);
  assert.equal(submitted.training_consent, false);
  assert.equal(
    await page.evaluate(() => window.__privacyMicrophoneRequests),
    0,
  );
  await page.getByRole("textbox", { name: "پیام شما", exact: true }).waitFor();
  passed(
    "Fresh explicit consent binds the displayed fingerprint, creates a real session with recording and training disabled and does not request the microphone",
  );
  const summary = page
    .locator("summary")
    .filter({ hasText: "حریم خصوصی و نگهداری گفتگو" });
  assert.equal(
    await page.locator(".conversation-body").getAttribute("tabindex"),
    "0",
    "The server must serve the current build with keyboard-accessible conversation scrolling",
  );
  await summary.focus();
  await page.keyboard.press("Enter");
  await page
    .locator(".conversation-privacy-notice")
    .getByText(clinic.notice, { exact: true })
    .waitFor();
  assert(
    (await page.locator(".privacy-retention").innerText()).includes(period),
  );
  await inspect(
    "Active conversation privacy disclosure expanded by keyboard at 320px",
  );
  await page.screenshot({
    path: output + "/privacy-active-320.png",
    fullPage: true,
  });
  await summary.focus();
  await page.keyboard.press("Enter");
  assert(
    await page
      .getByRole("textbox", { name: "پیام شما", exact: true })
      .isEnabled(),
  );
  passed(
    "The same retention notice remains keyboard accessible during the conversation without blocking typed input",
  );
  const [ended] = await Promise.all([
    page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname.endsWith("/end") &&
        r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "پایان", exact: true }).click(),
  ]);
  assert(ended.ok());
  await page
    .getByText("گفتگو پایان یافت. ممنون که با ما همراه بودید.", { exact: true })
    .waitFor();
  assert.equal(
    await page.evaluate(() => window.__privacyMicrophoneRequests),
    0,
  );
  assert.deepEqual(errors, []);
  passed(
    "The session ends cleanly, with no microphone access or browser errors",
  );
} catch (error) {
  failure = error.message;
  await page
    .screenshot({
      path: output + "/privacy-notice-failure.png",
      fullPage: true,
    })
    .catch(() => {});
  console.error(error.stack);
  process.exitCode = 1;
} finally {
  await writeFile(
    output + "/privacy-notice.json",
    JSON.stringify(
      {
        checks,
        errors,
        audits,
        failure,
        retention_days_received: retentionDays,
        synthetic_data: true,
        qualification:
          "This verifies disclosure, real stale-notice rejection and renewed consent against an isolated synthetic API, plus UI behavior. It does not certify the separate retention worker, deletion completion or legal policy.",
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      checks: checks.length,
      errors: errors.length,
      failure,
      report: output + "/privacy-notice.json",
    }),
  );
  await browser.close();
}
