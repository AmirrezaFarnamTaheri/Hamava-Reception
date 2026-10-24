import { launchBrowser } from "./browser-launch.mjs";
import { mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
const base = process.env.HAMAAVA_BASE_URL || "http://127.0.0.1:8000";
const output =
  process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamaava-ui-validation";
await mkdir(output, { recursive: true });
const browser = await launchBrowser();
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  locale: "fa-IR",
  reducedMotion: "reduce",
});
const page = await context.newPage();
const checks = [];
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
let session;
function passed(name) {
  checks.push(name);
  console.log(JSON.stringify({ passed: name }));
}
async function turn(text, expected) {
  await page.getByRole("textbox", { name: "پیام شما", exact: true }).fill(text);
  const [r] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/turn") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "ارسال پیام", exact: true }).click(),
  ]);
  const data = await r.json();
  assert(r.ok(), JSON.stringify(data));
  if (expected) assert.equal(data.state, expected, JSON.stringify(data));
  await page
    .getByRole("log")
    .getByText(data.reply, { exact: true })
    .last()
    .waitFor();
  return data;
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
  assert.equal(
    (await integrations.json()).mode,
    "demo",
    "Conversation writes require explicit synthetic demo mode",
  );
  await page.goto(base + "/talk/bahar", { waitUntil: "networkidle" });
  assert(
    await page
      .getByRole("button", { name: "شروع گفتگو", exact: true })
      .isDisabled(),
  );
  await page.getByRole("checkbox").check();
  const [start] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().endsWith("/public/sessions") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "شروع گفتگو", exact: true }).click(),
  ]);
  session = await start.json();
  assert(start.ok());
  passed(
    "Processing consent gates session creation; microphone starts only by explicit action",
  );
  let first = true;
  let committed;
  await page.route("**/public/sessions/*/turn", async (route) => {
    if (first) {
      first = false;
      const r = await route.fetch();
      committed = await r.json();
      await route.abort("failed");
    } else await route.continue();
  });
  await page
    .getByRole("textbox", { name: "پیام شما", exact: true })
    .fill("آدرس مرکز کجاست؟");
  await page.getByRole("button", { name: "ارسال پیام", exact: true }).click();
  await page
    .getByRole("button", { name: "تلاش دوباره برای همان درخواست", exact: true })
    .waitFor();
  assert(
    await page
      .getByRole("textbox", { name: "پیام شما", exact: true })
      .isDisabled(),
  );
  const [retry] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/turn") && r.request().method() === "POST",
    ),
    page
      .getByRole("button", {
        name: "تلاش دوباره برای همان درخواست",
        exact: true,
      })
      .click(),
  ]);
  const replay = await retry.json();
  assert.equal(replay.turn_id, committed.turn_id);
  await page.unroute("**/public/sessions/*/turn");
  passed(
    "A lost response retries the same committed request without duplicating its result",
  );
  await turn("نوبت می خواهم", "SERVICE");
  await turn("1", "PROVIDER");
  await turn("1", "DATE");
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + 3);
  await turn(date.toISOString().slice(0, 10), "OFFER");
  await turn("1", "NAME");
  await turn("مراجع آزمایشی گفتگوی مرورگر", "PHONE");
  await turn("09129990003", "VERIFY");
  await turn("246810", "CONFIRM");
  assert.equal(
    await page.locator(".confirmed-booking").count(),
    0,
    "No booking result before confirmation",
  );
  const confirmed = await turn("بله", "REMINDER_CONSENT");
  assert.equal(confirmed.booking.status, "CONFIRMED");
  await page
    .locator(".confirmed-booking")
    .getByText(confirmed.booking.reference, { exact: true })
    .waitFor();
  await turn("خیر", "COMPLETE");
  passed(
    "Mobile public conversation completes verified booking, explicit confirmation, and separate reminder choice",
  );
  await page.screenshot({
    path: output + "/talk-booking-mobile.png",
    fullPage: true,
  });
  const [handoff] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/handoff") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "همراهی انسانی", exact: true }).click(),
  ]);
  assert(handoff.ok());
  const handoffResult = await handoff.json();
  assert.notEqual(handoffResult.status, "CONNECTED");
  passed(
    "Human request queues a real handoff without claiming a live connection",
  );
  await page.getByRole("button", { name: "پایان", exact: true }).click();
  await page
    .getByText("گفتگو پایان یافت. ممنون که با ما همراه بودید.", { exact: true })
    .waitFor();
  assert.equal(
    await page.evaluate(() => document.documentElement.scrollWidth),
    390,
  );
  assert.deepEqual(errors, []);
  passed("Conversation ends cleanly and fits a 390px screen");
} catch (e) {
  await page.screenshot({
    path: output + "/conversation-failure.png",
    fullPage: true,
  });
  console.error(e.stack);
  process.exitCode = 1;
} finally {
  if (session) {
    await context.request.post(
      base + "/api/v1/public/sessions/" + session.session_id + "/end",
      { headers: { Authorization: "Bearer " + session.token }, data: {} },
    );
  }
  await writeFile(
    output + "/conversation.json",
    JSON.stringify({ checks, errors }, null, 2),
  );
  console.log(JSON.stringify({ checks: checks.length, errors }));
  await browser.close();
}
