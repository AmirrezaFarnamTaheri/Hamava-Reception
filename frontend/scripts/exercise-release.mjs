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
const page = await context.newPage();
const checks = [],
  errors = [],
  audits = [];
let failure,
  originalPolicy,
  policyPublished = false,
  uatSubmissions = 0;
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (request) => {
  if (
    new URL(request.url()).pathname === "/api/v1/operations/uat/approve" &&
    request.method() === "POST"
  )
    uatSubmissions++;
});
function passed(name) {
  checks.push(name);
  console.log(JSON.stringify({ passed: name }));
}
async function inspectSetup(label) {
  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const findings = await page.evaluate(async () => {
    const result = await window.axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
    });
    return result.violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      count: item.nodes.length,
    }));
  });
  const viewport = page.viewportSize().width;
  const width = await page.evaluate(() => document.documentElement.scrollWidth);
  audits.push({ label, findings, viewport, width });
  assert.deepEqual(findings, [], JSON.stringify({ label, findings }));
  assert(width <= viewport, label + " horizontal overflow");
}
async function read(path) {
  const token = await page.evaluate(() =>
    sessionStorage.getItem("hamaava_staff_session"),
  );
  const response = await context.request.get(base + "/api/v1" + path, {
    headers: { Authorization: "Bearer " + token },
  });
  assert(response.ok(), path + " " + response.status());
  return response.json();
}
async function settings(label) {
  await page.goto(base + "/settings", { waitUntil: "networkidle" });
  await page.getByRole("tab", { name: label, exact: true }).click();
  await page.waitForLoadState("networkidle");
}
async function fillPolicy(policy) {
  await page
    .getByRole("checkbox", {
      name: "دریافت بیعانه با شرایط منتشرشدهٔ مرکز فعال باشد.",
      exact: true,
    })
    .setChecked(policy.enabled);
  await page
    .getByLabel("مهلت پرداخت بیعانه (دقیقه)", { exact: true })
    .fill(String(policy.hold_minutes));
  for (const [key, label] of [
    ["deposit_terms", "شرایط دریافت بیعانه"],
    ["cancellation_terms", "شرایط لغو نوبت"],
    ["refund_terms", "شرایط بازپرداخت"],
  ])
    await page.getByLabel(label, { exact: true }).fill(policy[key]);
}
async function publish() {
  await page
    .getByRole("checkbox", {
      name: "متن شرایط را با اختیار مرکز بررسی کرده‌ام و انتشار این نسخه را تأیید می‌کنم.",
      exact: true,
    })
    .check();
  const [response] = await Promise.all([
    page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/v1/operations/payment-policy" &&
        r.request().method() === "PUT",
    ),
    page
      .getByRole("button", { name: "انتشار شرایط مالی", exact: true })
      .click(),
  ]);
  const value = await response.json();
  assert(response.ok(), JSON.stringify(value));
  return value;
}
try {
  await page.goto(base + "/", { waitUntil: "networkidle" });
  await page
    .getByRole("button", { name: "استفاده از حساب نمایشی", exact: true })
    .click();
  await page
    .getByRole("button", { name: "ورود به هم‌آوا", exact: true })
    .click();
  await page
    .getByRole("heading", { name: "امروز، با خیال آسوده‌تر" })
    .waitFor();
  // Onboarding can add earlier-sorting memberships; seed fixtures are scoped explicitly.
  if (
    (await page.getByLabel("انتخاب مرکز", { exact: true }).inputValue()) !==
    "clinic-bahar"
  ) {
    const [switched] = await Promise.all([
      page.waitForResponse(
        (response) =>
          new URL(response.url()).pathname === "/api/v1/auth/switch" &&
          response.request().method() === "POST",
      ),
      page
        .getByLabel("انتخاب مرکز", { exact: true })
        .selectOption("clinic-bahar"),
    ]);
    assert(switched.ok(), "Seed clinic switch failed");
    await page.waitForLoadState("networkidle");
  }
  assert.equal((await read("/operations/integrations")).mode, "demo");
  passed("Release control mutations require an explicit isolated demo");
  await settings("آمادگی راه‌اندازی");
  const approve = page.getByRole("button", {
    name: "ثبت تأیید آمادگی مرکز",
    exact: true,
  });
  assert(await approve.isDisabled());
  assert.equal(await page.getByRole("checkbox", { checked: true }).count(), 0);
  assert.equal(await page.getByRole("textbox").count(), 5);
  const before = await read("/operations/uat?target_mode=ai_primary");
  assert.equal(before.approved, false);
  assert.equal(before.production_enforced, false);
  await page.getByRole("checkbox").first().check();
  await page
    .getByRole("textbox")
    .first()
    .fill("Synthetic browser evidence, incomplete review");
  assert(await approve.isDisabled());
  await page
    .getByLabel("روش پذیرش مورد تأیید", { exact: true })
    .selectOption("supervised");
  await page.waitForLoadState("networkidle");
  assert.equal(await page.getByRole("checkbox", { checked: true }).count(), 0);
  assert(await approve.isDisabled());
  assert.equal(uatSubmissions, 0);
  passed(
    "Five independent evidence references and explicit reviewer confirmation are required; changing mode clears the draft; no readiness is fabricated",
  );
  await settings("شرایط مالی");
  originalPolicy = await read("/operations/payment-policy");
  assert(
    await page
      .getByRole("button", { name: "انتشار شرایط مالی", exact: true })
      .isDisabled(),
  );
  const synthetic = {
    enabled: true,
    hold_minutes: 60,
    deposit_terms:
      "شرایط ساختگی آزمون مرورگر؛ هیچ دریافت وجه واقعی انجام نمی‌شود.",
    cancellation_terms:
      "لغو این نوبت ساختگی تابع مهلت لغو مرکز است؛ بررسی واقعی حقوقی انجام نشده است.",
    refund_terms:
      "بازپرداخت این سناریو فقط سابقهٔ ساختگی است و هیچ انتقال بانکی انجام نمی‌شود.",
  };
  await fillPolicy(synthetic);
  assert(
    await page
      .getByRole("button", { name: "انتشار شرایط مالی", exact: true })
      .isDisabled(),
  );
  const published = await publish();
  policyPublished = true;
  assert(published.version > originalPolicy.version);
  assert.equal(published.demonstration, true);
  assert.equal(published.enabled, true);
  passed(
    "Explicit owner confirmation publishes a versioned synthetic policy and does not claim live merchant settlement",
  );
  const publicResponse = await context.request.get(
    base + "/api/v1/public/clinics/bahar/payment-policy",
  );
  assert(publicResponse.ok());
  const publicPolicy = await publicResponse.json();
  assert.equal(publicPolicy.version, published.version);
  assert.equal(publicPolicy.synthetic, true);
  for (const field of [
    "merchant_alias",
    "merchant_identity_hash",
    "merchant_id",
    "published_by",
  ])
    assert(!Object.hasOwn(publicPolicy, field));
  const visitor = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale: "fa-IR",
  });
  const publicPage = await visitor.newPage();
  await publicPage.goto(base + "/talk/bahar", { waitUntil: "networkidle" });
  await publicPage
    .getByText("شرایط بیعانه، لغو و بازپرداخت", { exact: true })
    .click();
  await publicPage.getByText(synthetic.refund_terms, { exact: true }).waitFor();
  assert.equal(
    await publicPage.evaluate(() => document.documentElement.scrollWidth),
    390,
  );
  await visitor.close();
  passed(
    "Public mobile reception shows published safe terms, with no merchant identity or staff credential disclosure",
  );
  await settings("شرایط مالی");
  await fillPolicy(originalPolicy);
  await publish();
  policyPublished = false;
  passed("Original policy values are restored through a new audited version");
  await page.goto(base + "/reports", { waitUntil: "networkidle" });
  await page
    .getByRole("heading", { name: "زمان پردازش و تحویل", exact: true })
    .waitFor();
  const metrics = await read("/operations/latency?hours=24");
  assert.equal(metrics.successful_observations_only, true);
  assert.deepEqual(Object.keys(metrics.stages).sort(), [
    "conversation_and_calendar",
    "staff_task_to_verified_room_join",
    "stt_provider",
    "tool_book",
    "tool_cancel",
    "tool_hold",
    "tool_reschedule",
    "tool_slots",
    "tts_or_static_cache",
  ]);
  await page
    .getByLabel("بازهٔ بررسی زمان پاسخ", { exact: true })
    .selectOption("168");
  await page.waitForLoadState("networkidle");
  passed(
    "Latency panel shows actual bounded stage distributions and distinguishes them from first-audible caller latency",
  );
  await page.goto(base + "/settings", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "افزودن مرکز", exact: true }).click();
  const dialog = page.getByRole("dialog");
  const clinicLabel = "مرکز راه‌اندازی ساختگی " + Date.now().toString(36);
  await dialog.getByLabel("نام مرکز", { exact: true }).fill(clinicLabel);
  await dialog
    .getByLabel("نشانی کوتاه پذیرش آنلاین", { exact: true })
    .fill("ui-setup-" + Date.now().toString(36));
  const [createdResponse] = await Promise.all([
    page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/v1/clinics" &&
        response.request().method() === "POST",
    ),
    dialog
      .getByRole("button", { name: "ایجاد و ورود به مرکز", exact: true })
      .click(),
  ]);
  const created = await createdResponse.json();
  assert(createdResponse.ok(), JSON.stringify(created));
  assert(["human_primary", "paused"].includes(created.mode));
  await page
    .getByRole("heading", { name: "مرکز را آماده کنید", exact: true })
    .waitFor();
  assert.equal(new URL(page.url()).pathname, "/setup");
  await page.getByRole("progressbar").waitFor();
  assert.equal(
    await page.getByRole("progressbar").getAttribute("aria-valuenow"),
    "0",
  );
  assert.equal(
    await page.getByRole("progressbar").getAttribute("aria-valuemax"),
    "4",
  );
  assert.equal((await read("/settings")).name, clinicLabel);
  await inspectSetup("New clinic setup guide at desktop width");
  await page.reload({ waitUntil: "networkidle" });
  await page
    .getByRole("heading", { name: "مرکز را آماده کنید", exact: true })
    .waitFor();
  await page.getByRole("progressbar").waitFor();
  assert.equal(
    await page.getByRole("progressbar").getAttribute("aria-valuenow"),
    "0",
  );
  assert.equal(
    await page
      .getByRole("button", { name: "تکمیل این بخش", exact: true })
      .count(),
    4,
  );
  assert.equal(
    await page.getByLabel("انتخاب مرکز", { exact: true }).inputValue(),
    created.id,
  );
  assert.equal((await read("/settings")).mode, created.mode);
  await page.setViewportSize({ width: 320, height: 760 });
  await inspectSetup("Resumed incomplete clinic setup guide at 320px");
  await page.screenshot({
    path: output + "/setup-guide-320.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page
    .getByLabel("انتخاب مرکز", { exact: true })
    .selectOption("clinic-bahar");
  await page.waitForFunction(
    () => document.querySelector("#clinic-switch")?.value === "clinic-bahar",
  );
  passed(
    "Owner creates a scoped clinic without configuration files; the four-step guide survives reload, remains incomplete and inactive, and fits desktop/320px",
  );
  assert.deepEqual(errors, []);
} catch (error) {
  failure = error.message
    .replace(/Bearer\s+[A-Za-z0-9._~-]+/gi, "Bearer [redacted]")
    .replace(
      /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g,
      "[redacted session credential]",
    )
    .replace(
      /((?:Authorization|Cookie|Set-Cookie|X-Api-Key):)[^\r\n]*/gi,
      "$1 [redacted]",
    )
    .split("Browser logs:")[0];
  console.error(failure);
  process.exitCode = 1;
  if (!page.isClosed())
    await page.screenshot({
      path: output + "/release-failure.png",
      fullPage: true,
    });
} finally {
  if (policyPublished && originalPolicy && !page.isClosed()) {
    try {
      await settings("شرایط مالی");
      await fillPolicy(originalPolicy);
      await publish();
    } catch (error) {
      errors.push(
        "Synthetic policy cleanup failed: " +
          error.message.split("Call log:")[0].split("Browser logs:")[0],
      );
      process.exitCode = 1;
    }
  }
  await writeFile(
    output + "/release.json",
    JSON.stringify(
      {
        checks,
        errors,
        audits,
        failure,
        synthetic_data: true,
        uat_attestation_created: uatSubmissions > 0,
        live_payment_or_external_messages: false,
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ checks: checks.length, errors, failure }));
  await browser.close();
}
