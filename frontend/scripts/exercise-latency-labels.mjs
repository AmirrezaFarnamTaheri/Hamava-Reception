import { launchBrowser } from "./browser-launch.mjs";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const base = process.env.HAMAAVA_BASE_URL || "http://127.0.0.1:8000";
const output =
  process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamava-latency-labels-validation";
await mkdir(output, { recursive: true });
const browser = await launchBrowser();
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  locale: "fa-IR",
  reducedMotion: "reduce",
  bypassCSP: true,
});
const page = await context.newPage();
page.setDefaultTimeout(45000);
const labels = {
  tool_slots: "جست‌وجوی نوبت‌های آزاد",
  tool_hold: "نگهداری موقت نوبت",
  tool_book: "ثبت نوبت",
  tool_cancel: "لغو نوبت",
  tool_reschedule: "تغییر زمان نوبت",
};
const expectedStages = [
  "conversation_and_calendar",
  "staff_task_to_verified_room_join",
  "stt_provider",
  ...Object.keys(labels),
  "tts_or_static_cache",
].sort();
const checks = [],
  audits = [],
  errors = [],
  unexpectedResponses = [];
let staffCredential, publicSession, observation, failure;
function sanitize(value) {
  return String(value)
    .split("Call log:")[0]
    .replace(/Bearer\s+\S+/gi, "Bearer [redacted]")
    .replace(/eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9._-]+/g, "[redacted]");
}
page.on("pageerror", (error) => errors.push(sanitize(error.message)));
page.on("response", (response) => {
  const path = new URL(response.url()).pathname;
  if (response.status() >= 400 && path.includes("/api/v1/"))
    unexpectedResponses.push({ path, status: response.status() });
});
function passed(name) {
  checks.push(name);
  console.log(JSON.stringify({ passed: name }));
}
async function request(path, body, credential = staffCredential) {
  const response = await context.request.fetch(base + "/api/v1" + path, {
    method: body ? "POST" : "GET",
    ...(credential
      ? { headers: { Authorization: "Bearer " + credential } }
      : {}),
    ...(body ? { data: body } : {}),
  });
  assert(response.ok(), `${path} returned ${response.status()}`);
  return response.json();
}
async function turn(text, expected) {
  const result = await request(
    `/public/sessions/${publicSession.session_id}/turn`,
    { text, request_id: crypto.randomUUID() },
    publicSession.token,
  );
  assert.equal(result.state, expected);
  return result;
}
try {
  const info = await request("/client-info");
  assert.equal(info.product, "hamava");
  assert.equal(info.demo_mode, true, "An isolated synthetic demo is required");
  await page.goto(base + "/", { waitUntil: "networkidle", timeout: 90000 });
  await page
    .getByRole("button", { name: "استفاده از حساب نمایشی", exact: true })
    .click();
  await page
    .getByRole("button", { name: "ورود به هم‌آوا", exact: true })
    .click();
  await page.locator(".reception-workspace").waitFor();
  await page.waitForLoadState("networkidle");
  assert.equal(
    await page.getByLabel("انتخاب مرکز", { exact: true }).inputValue(),
    "clinic-bahar",
  );
  staffCredential = await page.evaluate(() =>
    sessionStorage.getItem("hamaava_staff_session"),
  );
  assert.equal((await request("/operations/integrations")).mode, "demo");

  let day;
  for (let offset = 1; offset <= 14 && !day; offset++) {
    const date = new Date();
    date.setUTCDate(date.getUTCDate() + offset);
    const candidate = date.toISOString().slice(0, 10);
    const slots = await request(
      "/slots?provider_id=provider-bahar-1&service_id=service-consultation&date=" +
        candidate,
    );
    if (slots.length) day = candidate;
  }
  assert(day, "A future synthetic clinic slot is required");
  const clinic = await request("/public/clinics/bahar", undefined, null);
  publicSession = await request(
    "/public/sessions",
    {
      clinic_slug: "bahar",
      processing_consent: true,
      processing_notice_fingerprint: clinic.processing_notice_fingerprint,
      recording_consent: false,
      training_consent: false,
    },
    null,
  );
  await turn("نوبت می خواهم", "SERVICE");
  await turn("1", "PROVIDER");
  await turn("1", "DATE");
  const offered = await turn(day, "OFFER");
  assert(offered.offers.length > 0);
  await request(
    `/public/sessions/${publicSession.session_id}/end`,
    {},
    publicSession.token,
  );
  publicSession = null;
  observation = await request("/operations/latency?hours=24");
  assert.deepEqual(Object.keys(observation.stages).sort(), expectedStages);
  assert.equal(observation.successful_observations_only, true);
  assert(observation.stages.tool_slots.count >= 1);
  assert(observation.stages.tool_slots.p50_ms >= 0);
  passed(
    "A real synthetic conversation records a successful slots tool span; the actual latency API exposes the five exact tool stages and the four existing stages",
  );

  for (const width of [1440, 390, 320]) {
    await page.setViewportSize({ width, height: width === 1440 ? 1000 : 844 });
    await page.goto(base + "/reports", {
      waitUntil: "networkidle",
      timeout: 90000,
    });
    const panel = page.locator("section.panel").filter({
      has: page.getByRole("heading", {
        name: "زمان پردازش و تحویل",
        exact: true,
      }),
    });
    const table = panel.getByRole("table");
    await table.waitFor();
    const visibleLabels = await table
      .locator("tbody tr td:first-child")
      .allTextContents();
    assert.equal(visibleLabels.length, expectedStages.length);
    assert.equal(new Set(visibleLabels).size, expectedStages.length);
    assert(!visibleLabels.includes("مرحلهٔ پردازش"));
    for (const [stage, label] of Object.entries(labels)) {
      const row = table.getByRole("row").filter({
        has: page.getByRole("cell", { name: label, exact: true }),
      });
      assert.equal(
        await row.count(),
        1,
        stage + " must have one distinct label",
      );
      const cells = await row.getByRole("cell").allTextContents();
      assert.equal(
        cells[1],
        new Intl.NumberFormat("fa-IR").format(observation.stages[stage].count),
      );
      if (!observation.stages[stage].count)
        assert.deepEqual(cells.slice(2), [
          "داده‌ای نیست",
          "داده‌ای نیست",
          "داده‌ای نیست",
        ]);
    }
    assert.match(
      await panel.innerText(),
      /معیار شنیده‌شدن اولین صدای پاسخ نیست/,
    );
    assert.match(await panel.innerText(), /فقط نمونه‌های موفق/);
    await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
    const result = await page.evaluate(async () => {
      const audit = await window.axe.run(document, {
        runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
      });
      return {
        viewport: innerWidth,
        width: document.documentElement.scrollWidth,
        violations: audit.violations.map((item) => ({
          id: item.id,
          impact: item.impact,
          nodes: item.nodes.map((node) => ({
            target: node.target,
            summary: node.failureSummary,
          })),
        })),
      };
    });
    audits.push({ name: "latency-labels-" + width, ...result });
    assert.deepEqual(result.violations, []);
    assert(result.width <= result.viewport, "Document must not overflow");
    await panel.screenshot({ path: output + `/latency-labels-${width}.png` });
    passed(
      `At ${width}px all five tool rows have distinct Persian labels, actual counts and honest empty timing cells; accessibility and document overflow checks are clean`,
    );
  }
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpectedResponses, []);
} catch (error) {
  failure = sanitize(error.stack || error);
  console.error(failure);
  process.exitCode = 1;
} finally {
  if (publicSession) {
    try {
      await request(
        `/public/sessions/${publicSession.session_id}/end`,
        {},
        publicSession.token,
      );
    } catch (error) {
      errors.push(sanitize(error.message));
      process.exitCode = 1;
    }
  }
  await writeFile(
    output + "/latency-labels.json",
    JSON.stringify(
      {
        passed:
          !failure && errors.length === 0 && unexpectedResponses.length === 0,
        checks,
        audits,
        errors,
        unexpected_api_failures: unexpectedResponses,
        failure,
        stages: observation?.stages,
        tool_labels: labels,
        scope:
          "Actual local synthetic API and rendered production UI; one successful slots dispatch is observed. Zero-sample tool rows retain empty percentiles. No provider, physical-device, first-audible or latency-SLO qualification is claimed.",
      },
      null,
      2,
    ),
  );
  await browser.close();
}
