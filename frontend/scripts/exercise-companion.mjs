import { launchBrowser } from "./browser-launch.mjs";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import assert from "node:assert/strict";
const require = createRequire(import.meta.url);
const base = process.env.HAMAAVA_BASE_URL || "http://127.0.0.1:8000";
const output =
  process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamava-companion-validation";
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
const checks = [],
  audits = [],
  errors = [],
  failures = [];
const run = Date.now().toString(36),
  password = "CompanionSynthetic2026!";
let ownerToken, ownerUser, failure;
const evidence = {
  name: "synthetic-reviewed-evidence.txt",
  mimeType: "text/plain",
  buffer: Buffer.from(
    "Synthetic fixture document for local companion workflow verification. No real person or contract.",
  ),
};
function passed(name, kind = "actual-ui-and-local-api") {
  checks.push({ name, kind });
  console.log(JSON.stringify({ passed: name }));
}
function watch(target) {
  target.on("pageerror", (error) => errors.push(error.message));
  target.on("response", (response) => {
    const path = new URL(response.url()).pathname;
    if (
      response.status() >= 400 &&
      path.includes("/api/v1/") &&
      !(path === "/api/v1/operations/costs" && response.status() === 503)
    )
      failures.push({ path, status: response.status() });
  });
}
watch(page);
async function audit(name, target = page, screenshot = false) {
  await target.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const item = await target.evaluate(async () => {
    const result = await window.axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
    });
    return {
      width: innerWidth,
      scroll: document.documentElement.scrollWidth,
      direction: document.documentElement.dir,
      violations: result.violations.map((v) => ({
        id: v.id,
        impact: v.impact,
        nodes: v.nodes.length,
        details: v.nodes.map((node) => ({
          target: node.target,
          summary: node.failureSummary,
        })),
      })),
    };
  });
  audits.push({ name, ...item });
  if (screenshot) {
    await target.evaluate(async () => {
      if (document.activeElement instanceof HTMLElement)
        document.activeElement.blur();
      window.scrollTo({ top: 0, behavior: "instant" });
      await new Promise((resolve) =>
        requestAnimationFrame(() => requestAnimationFrame(resolve)),
      );
    });
    await target.screenshot({
      path: join(output, name + ".png"),
      fullPage: true,
      timeout: 120000,
    });
  }
  console.log(
    JSON.stringify({
      audited: name,
      overflow: item.scroll > item.width + 1,
      violations: item.violations.map((row) => row.id),
    }),
  );
}
async function go(path, target = page) {
  await target.goto(base + path, { waitUntil: "networkidle", timeout: 90000 });
}
async function action(path, callback, method = "POST", target = page) {
  const [response] = await Promise.all([
    target.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/v1" + path &&
        r.request().method() === method,
    ),
    callback(),
  ]);
  assert(response.ok(), `${path} returned ${response.status()}`);
  return response.json();
}
async function request(path, body, method = body ? "POST" : "GET") {
  const r = await context.request.fetch(base + "/api/v1" + path, {
    method,
    headers: { Authorization: "Bearer " + ownerToken },
    ...(body ? { data: body } : {}),
  });
  assert(r.ok(), `${path} returned ${r.status()}`);
  return r.json();
}
const futureDate = (days = 10) => {
  const date = new Date();
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
};
async function upload(dialog) {
  await dialog
    .getByLabel("شناسهٔ مدرک", { exact: true })
    .fill("companion/" + run);
  await dialog
    .getByLabel("انتخاب فایل مدرک", { exact: true })
    .setInputFiles(evidence);
  await dialog.getByText("اثرانگشت آماده است", { exact: false }).waitFor();
}
async function login(target, email, secret) {
  await go("/", target);
  await target.getByLabel("ایمیل", { exact: true }).fill(email);
  await target.getByLabel("گذرواژه", { exact: true }).fill(secret);
  await target
    .getByRole("button", { name: "ورود به هم‌آوا", exact: true })
    .click();
  await target.locator(".reception-workspace").waitFor();
  await target.waitForLoadState("networkidle");
}
try {
  const info = await (
    await context.request.get(base + "/api/v1/client-info")
  ).json();
  assert.equal(
    info.demo_mode,
    true,
    "This suite requires an explicitly synthetic demo server",
  );
  await go("/");
  assert.equal(
    await page.getByLabel("ایمیل", { exact: true }).inputValue(),
    "",
  );
  assert.equal(
    await page.getByLabel("گذرواژه", { exact: true }).inputValue(),
    "",
  );
  await audit("companion-login-desktop", page, true);
  await page
    .getByRole("button", { name: "استفاده از حساب نمایشی", exact: true })
    .click();
  await page
    .getByRole("button", { name: "نمایش گذرواژه", exact: true })
    .click();
  assert.equal(
    await page.getByLabel("گذرواژه", { exact: true }).getAttribute("type"),
    "text",
  );
  await page
    .getByRole("button", { name: "پنهان کردن گذرواژه", exact: true })
    .click();
  const auth = await action("/auth/login", () =>
    page.getByRole("button", { name: "ورود به هم‌آوا", exact: true }).click(),
  );
  ownerToken = auth.access_token;
  ownerUser = auth.user;
  await page
    .getByRole("heading", { name: "امروز، با خیال آسوده‌تر", exact: true })
    .waitFor();
  await page.waitForLoadState("networkidle");
  passed(
    "Sign-in starts empty; explicit demo selection and accessible password visibility work",
  );
  await page.keyboard.press("Control+k");
  const command = page.getByRole("combobox", {
    name: "جست‌وجوی بخش‌ها و اقدام‌ها",
    exact: true,
  });
  assert(await command.evaluate((node) => node === document.activeElement));
  await command.fill("ثبت نوبت جدید");
  await audit("companion-command-keyboard");
  await page.keyboard.press("Enter");
  await page
    .getByRole("dialog", { name: "ثبت نوبت جدید", exact: true })
    .waitFor();
  assert(
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "ثبت نوبت", exact: true })
      .isDisabled(),
  );
  await page.keyboard.press("Escape");
  assert(!new URL(page.url()).searchParams.has("new"));
  passed(
    "Command shortcut searches authorized actions and opens the real booking flow without accidental submission",
  );

  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await go("/");
    await page.locator(".schedule-panel .timeline-row").first().waitFor();
    const order = await page.evaluate(() => ({
      schedule: document
        .querySelector(".schedule-panel")
        .getBoundingClientRect().top,
      metrics: document.querySelector(".metric-grid").getBoundingClientRect()
        .top,
    }));
    assert(order.schedule < order.metrics && order.schedule < 650);
    await audit("companion-today-" + width, page, true);
    const bottom = page.getByRole("navigation", {
      name: "دسترسی سریع همراه",
      exact: true,
    });
    await bottom.getByRole("link", { name: "بیشتر", exact: true }).click();
    await page
      .getByRole("heading", { name: "حساب و دسترسی‌ها", exact: true })
      .waitFor();
    await audit("companion-more-" + width);
    await page
      .getByRole("link", {
        name: "نوبت‌ها رزرو، جابه‌جایی و ثبت مراجعه",
        exact: true,
      })
      .click();
    await page.locator(".appointment-card").first().waitFor();
    const times = await page
      .locator(".appointment-card-time strong")
      .allTextContents();
    const digits = (value) =>
      value.replace(/[۰-۹]/g, (d) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(d)));
    assert(times.length >= 3);
    assert.deepEqual(times.map(digits), [...times.map(digits)].sort());
    const lastAction = page.locator(".appointment-card-actions summary").last();
    if (await lastAction.count()) {
      await lastAction.focus();
      await lastAction.scrollIntoViewIfNeeded();
      await page.evaluate(() =>
        document.activeElement.scrollIntoView({ block: "center" }),
      );
      const positions = await page.evaluate(() => ({
        focus: document.activeElement.getBoundingClientRect().bottom,
        nav: document
          .querySelector(".companion-navigation")
          .getBoundingClientRect().top,
      }));
      assert(positions.focus < positions.nav);
      await lastAction.click();
      await page
        .getByRole("button", { name: "لغو نوبت", exact: true })
        .last()
        .waitFor();
    }
    await audit("companion-appointments-" + width, page, true);
    passed(
      `At ${width}px the schedule leads, appointment cards are chronological and the last action clears bottom navigation`,
    );
    await bottom.getByRole("link", { name: "پیگیری‌ها", exact: true }).click();
    await page
      .getByLabel("جست‌وجوی پیگیری‌ها", { exact: true })
      .fill("عبارت بی‌نتیجهٔ آزمایشی");
    await page
      .getByRole("heading", { name: "درخواستی در این بخش نیست", exact: true })
      .waitFor();
    await audit("companion-task-empty-" + width);
    await bottom.getByRole("link", { name: "تماس‌ها", exact: true }).click();
    await page.getByRole("heading", { name: "تماس‌ها", exact: true }).waitFor();
    await page.waitForLoadState("networkidle");
    await audit("companion-calls-" + width);
    passed(
      `At ${width}px companion tabs navigate real task and call screens with meaningful empty states`,
    );
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await go("/controls?tab=costs");
  await page
    .getByRole("heading", { name: "هزینهٔ سرویس‌های مرکز", exact: true })
    .waitFor();
  await page.getByRole("button", { name: "سقف هزینه", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("سقف ماهانه (تومان)", { exact: true })
    .fill("1000000");
  await dialog
    .getByLabel("سقف هر تماس (تومان)", { exact: true })
    .fill("100000");
  await dialog
    .getByLabel("سقف هر عملیات (تومان)", { exact: true })
    .fill("10000");
  await dialog
    .getByRole("checkbox", {
      name: "سقف‌های بالا را بررسی کرده‌ام و انتشار آن‌ها را تأیید می‌کنم.",
      exact: true,
    })
    .check();
  await dialog.getByLabel("آستانهٔ هشدار (درصد)", { exact: true }).fill("75");
  assert(
    await dialog
      .getByRole("button", { name: "انتشار سقف‌ها", exact: true })
      .isDisabled(),
  );
  await dialog
    .getByRole("checkbox", {
      name: "سقف‌های بالا را بررسی کرده‌ام و انتشار آن‌ها را تأیید می‌کنم.",
      exact: true,
    })
    .check();
  await action(
    "/operations/costs/policy",
    () =>
      dialog
        .getByRole("button", { name: "انتشار سقف‌ها", exact: true })
        .click(),
    "PUT",
  );
  await dialog.waitFor({ state: "hidden" });
  assert.equal(
    (await request("/operations/costs")).policy.monthly_cap_toman,
    1000000,
  );
  passed(
    "Cost budget persists through the real API and editing values clears the prior confirmation",
  );
  await page.getByRole("button", { name: "ثبت تعرفه", exact: true }).click();
  dialog = page.getByRole("dialog");
  for (const [label, value] of [
    ["شناسهٔ سرویس", "companion_fixture"],
    ["شناسهٔ نوع مصرف", "test_units"],
    ["واحد مصرف", "unit"],
    ["قیمت هر واحد", "0.019"],
    ["شروع اعتبار به وقت تهران", futureDate(-1) + "T10:00"],
    ["پایان اعتبار به وقت تهران", futureDate(30) + "T10:00"],
  ])
    await dialog.getByLabel(label, { exact: true }).fill(value);
  await upload(dialog);
  const rate = await action("/operations/costs/rates", () =>
    dialog
      .getByRole("button", { name: "ثبت نسخهٔ تعرفه", exact: true })
      .click(),
  );
  assert.equal(rate.price_per_unit, "0.019");
  await dialog.waitFor({ state: "hidden" });
  passed(
    "Fractional tariff is stored as an exact decimal string with a locally hashed synthetic evidence document",
  );
  await audit("companion-costs-desktop", page, true);

  await go("/controls?tab=privacy");
  const qa = page.locator(".governance-card").filter({
    has: page.getByRole("heading", { name: "بازبینی کیفیت", exact: true }),
  });
  await qa.getByRole("button", { name: "تنظیم قاعده", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByRole("checkbox", {
      name: "این کاربرد با رعایت مجوز مستقل فرد مجاز باشد.",
      exact: true,
    })
    .check();
  await dialog
    .getByLabel("متن اطلاعیه برای مراجعه‌کننده", { exact: true })
    .fill(
      "اطلاعیهٔ ساختگی آزمون: استفاده برای بازبینی کیفیت فقط با انتخاب مستقل فرد و امکان انصراف؛ داده پس از مهلت در پاک‌سازی دوره‌ای حذف می‌شود.",
    );
  await dialog
    .getByLabel("نگهداری دادهٔ این کاربرد (روز)", { exact: true })
    .fill("7");
  await dialog
    .getByLabel("انقضای نسخهٔ پشتیبان (روز)", { exact: true })
    .fill("14");
  await dialog
    .getByLabel("شناسهٔ مدرک تصمیم", { exact: true })
    .fill("companion/qa/" + run);
  await dialog
    .getByRole("checkbox", {
      name: "متن، کاربرد و مدت‌ها را بررسی کرده‌ام و انتشار نسخهٔ جدید را تأیید می‌کنم.",
      exact: true,
    })
    .check();
  await action(
    "/operations/privacy-controls/purposes",
    () =>
      dialog.getByRole("button", { name: "انتشار قاعده", exact: true }).click(),
    "PUT",
  );
  await dialog.waitFor({ state: "hidden" });
  await page
    .getByRole("button", { name: "ثبت انتخاب فرد", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("شماره همراه مراجعه‌کننده", { exact: true })
    .fill("09127770001");
  await dialog.getByLabel("کاربرد مشخص", { exact: true }).selectOption("qa");
  assert.equal(
    await dialog.getByLabel("انتخاب صریح فرد", { exact: true }).inputValue(),
    "",
  );
  await dialog
    .getByLabel("انتخاب صریح فرد", { exact: true })
    .selectOption("grant");
  await dialog
    .getByLabel("روش احراز درخواست", { exact: true })
    .selectOption("signed_form");
  await upload(dialog);
  await dialog
    .getByRole("checkbox", {
      name: "هویت و درخواست واقعی فرد را برای همین کاربرد و همین اطلاعیه بررسی کرده‌ام.",
      exact: true,
    })
    .check();
  const permission = await action(
    "/operations/privacy-controls/permissions",
    () =>
      dialog.getByRole("button", { name: "ثبت انتخاب", exact: true }).click(),
  );
  assert.equal(permission.purpose, "qa");
  assert.equal(permission.granted, true);
  await dialog
    .getByRole("heading", { name: "اجازهٔ این کاربرد ثبت شد", exact: true })
    .waitFor();
  await dialog.getByRole("button", { name: "بستن", exact: true }).click();
  passed(
    "Purpose publication and independently evidenced subject permission are separate real writes; no consent is preselected",
  );
  await audit("companion-privacy-desktop");

  await go("/controls?tab=connections");
  await page
    .getByRole("heading", { name: "مرجع قطعی تقویم", exact: true })
    .waitFor();
  await page.waitForLoadState("networkidle");
  await audit("companion-connections-desktop", page, true);
  assert(
    (await page
      .getByText("هنوز مشاهده‌ای ثبت نشده است.", { exact: true })
      .count()) > 0,
  );
  passed(
    "Connections distinguish configuration, operator approval and absent observations without invented healthy results",
  );
  await go("/controls?tab=health");
  await page.getByRole("button", { name: "تعیین مسئول", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("افزودن مسئول", { exact: true })
    .selectOption(ownerUser.id);
  const oncall = await action(
    "/operations/oncall",
    () =>
      dialog
        .getByRole("button", { name: "ذخیرهٔ مسئولیت‌ها", exact: true })
        .click(),
    "PUT",
  );
  assert.equal(oncall.enabled, false);
  assert.deepEqual(oncall.user_ids, [ownerUser.id]);
  await dialog.waitFor({ state: "hidden" });
  passed(
    "On-call owner and order persist while external notification channels remain unclaimed and opt-in stays off",
  );
  await audit("companion-health-desktop");

  await go("/settings?tab=catalog");
  await page
    .getByRole("button", { name: "شرایط مراجعه", exact: true })
    .first()
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("آمادگی قبل از مراجعه", { exact: true })
    .fill("اطلاعات ساختگی آزمون: زمان مراجعه را با پذیرش هماهنگ کنید.");
  await dialog
    .getByLabel("مرجع تأیید این اطلاعات", { exact: true })
    .fill("companion-service-policy/" + run);
  await dialog
    .getByLabel("اعتبار اطلاعات تا؛ به وقت تهران", { exact: true })
    .fill(futureDate(30) + "T10:00");
  await dialog
    .getByLabel("دلیل انتشار نسخه", { exact: true })
    .fill("بررسی اداری ساختگی در آزمون همراه");
  await dialog
    .getByRole("checkbox", {
      name: "شرایط بالا با مرجع مرکز تطبیق داده شده و انتشار نسخهٔ تازه را تأیید می‌کنم.",
      exact: true,
    })
    .check();
  const [serviceResponse] = await Promise.all([
    page.waitForResponse(
      (r) =>
        /\/api\/v1\/services\/[^/]+\/policy$/.test(new URL(r.url()).pathname) &&
        r.request().method() === "PUT",
    ),
    dialog
      .getByRole("button", { name: "انتشار شرایط خدمت", exact: true })
      .click(),
  ]);
  assert(serviceResponse.ok());
  await dialog.waitFor({ state: "hidden" });
  passed(
    "Service rules publish through the real API with source, future expiry and explicit review",
  );

  // Remote-calendar fixture isolates truthful UI states; it does not qualify a real connector.
  const existing = (await request("/appointments"))[0];
  assert(
    existing,
    "Synthetic seed appointment is required for the calendar contract fixture",
  );
  const remote = {
    ...existing,
    id: "external:companion-fixture",
    reference: "EXT-FIXTURE",
    patient_name: "بررسی ساختگی تقویم",
    authority: "external",
    version: "remote-revision-1",
    status: "READBACK_REQUIRED",
    last_known_status: "CONFIRMED",
    operation_id: "fixture-original-operation",
    attendance: null,
    created_at: null,
    reminder_opt_in: null,
    notification_status: "UNKNOWN",
  };
  let readbackVerified = false;
  await context.route("**/api/v1/appointments?*", (route) =>
    route.fulfill({ json: [remote] }),
  );
  await context.route("**/api/v1/appointments/external*", (route) =>
    route.fulfill({
      json: readbackVerified
        ? { ...remote, status: "CONFIRMED" }
        : {
            operation_id: "fixture-readback-operation",
            operation: "get",
            operation_status: "UNKNOWN",
            status: "PENDING",
            result: null,
            error_code: null,
            verified_at: null,
            requires_reconciliation: true,
          },
    }),
  );
  await go("/appointments");
  assert.equal(
    await page.getByRole("button", { name: "لغو نوبت", exact: true }).count(),
    0,
  );
  await page
    .getByRole("button", { name: "بررسی در تقویم مرجع", exact: true })
    .click();
  dialog = page.getByRole("dialog", {
    name: "بررسی نوبت در تقویم مرجع",
    exact: true,
  });
  await dialog
    .getByText("نتیجه نامشخص؛ نیازمند تطبیق", { exact: true })
    .waitFor();
  assert.equal(
    await dialog.getByRole("button", { name: "لغو نوبت", exact: true }).count(),
    0,
  );
  assert.equal(
    await dialog
      .getByRole("button", { name: "جابجایی نوبت", exact: true })
      .count(),
    0,
  );
  readbackVerified = true;
  await dialog
    .getByRole("button", { name: "بازخوانی تازه", exact: true })
    .click();
  await dialog.getByRole("button", { name: "لغو نوبت", exact: true }).waitFor();
  await dialog
    .getByRole("button", { name: "جابجایی نوبت", exact: true })
    .waitFor();
  await audit("companion-external-readback-contract");
  await dialog.getByRole("button", { name: "بستن", exact: true }).click();
  await context.unroute("**/api/v1/appointments?*");
  await context.unroute("**/api/v1/appointments/external*");
  passed(
    "Cached and unknown external-calendar records cannot be changed; fresh verified readback enables actions even when an operation reference is present",
    "external-calendar-response-contract-fixture",
  );

  // Controlled failure exercises rendered recovery; the subsequent retry reaches the real API.
  let failOnce = true;
  await context.route("**/api/v1/operations/costs", async (route) => {
    if (failOnce) {
      failOnce = false;
      await route.fulfill({
        status: 503,
        json: {
          detail: {
            code: "TEST_UNAVAILABLE",
            message: "سرویس موقتاً در دسترس نیست.",
          },
        },
      });
    } else await route.continue();
  });
  await go("/controls?tab=costs");
  await page.getByRole("alert").waitFor();
  assert.equal(await page.locator(".cost-summary").count(), 0);
  await page.getByRole("button", { name: "تلاش دوباره", exact: true }).click();
  await page.locator(".cost-summary").waitFor();
  await context.unroute("**/api/v1/operations/costs");
  passed(
    "A controlled service failure shows retry and no invented cost summary, then recovers from the real API",
    "controlled-failure-then-real-api",
  );
  await context.setOffline(true);
  await page.locator(".network-status").waitFor();
  await context.setOffline(false);
  await page.locator(".network-status").waitFor({ state: "hidden" });
  passed(
    "Network loss and recovery update the persistent visible connection notice",
  );
  for (const [tab, heading] of [
    ["costs", "هزینهٔ سرویس‌های مرکز"],
    ["privacy", "قواعد استفاده و نگهداری"],
    ["connections", "مرجع قطعی تقویم"],
    ["health", "هشدارهای اخیر"],
  ]) {
    await page.setViewportSize({ width: 320, height: 844 });
    await go("/controls?tab=" + tab);
    await page.getByRole("heading", { name: heading, exact: true }).waitFor();
    await page.waitForLoadState("networkidle");
    await audit("companion-" + tab + "-320", page, tab === "costs");
  }
  for (const role of ["billing", "technical", "coordinator"]) {
    const email = `companion-${role}-${run}@example.test`;
    await request("/operations/team", {
      email,
      name: "همکار ساختگی آزمون " + role,
      role,
      initial_password: password,
    });
    const memberContext = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      locale: "fa-IR",
      bypassCSP: true,
    });
    const member = await memberContext.newPage();
    member.setDefaultTimeout(45000);
    watch(member);
    const requests = [];
    member.on("request", (request) => {
      if (new URL(request.url()).pathname.startsWith("/api/v1/"))
        requests.push(new URL(request.url()).pathname);
    });
    await login(member, email, password);
    if (role === "billing") {
      await go("/capacity?tab=payments", member);
      await member
        .getByRole("heading", { name: "بیعانه و بازپرداخت", exact: true })
        .waitFor();
      await member.waitForLoadState("networkidle");
      assert(!requests.includes("/api/v1/appointments"));
      assert(!requests.includes("/api/v1/operations/tasks"));
      await go("/reports", member);
      await member.waitForLoadState("networkidle");
      assert(!requests.includes("/api/v1/appointments"));
    }
    if (role === "technical") {
      await go("/controls?tab=health", member);
      await member
        .getByRole("heading", { name: "هشدارهای اخیر", exact: true })
        .waitFor();
      await member.waitForLoadState("networkidle");
      assert(!requests.includes("/api/v1/appointments"));
      assert(!requests.includes("/api/v1/operations/tasks"));
    }
    if (role === "coordinator") {
      await go("/tasks", member);
      await member.getByLabel("جست‌وجوی پیگیری‌ها", { exact: true }).waitFor();
      await go("/controls?tab=costs", member);
      await member
        .getByRole("heading", {
          name: "این بخش در دسترسی حساب شما نیست",
          exact: true,
        })
        .waitFor();
      assert(!requests.includes("/api/v1/operations/costs"));
    }
    await audit("companion-role-" + role, member);
    passed(
      `${role} navigation and direct routes respect actual server permissions without inappropriate patient or finance reads`,
    );
    await memberContext.close();
  }
  const noDemoContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
  });
  await noDemoContext.route("**/api/v1/client-info", (route) =>
    route.fulfill({ json: { ...info, demo_mode: false, mode: "live" } }),
  );
  const noDemo = await noDemoContext.newPage();
  await go("/", noDemo);
  assert.equal(
    await noDemo
      .getByRole("button", { name: "استفاده از حساب نمایشی", exact: true })
      .count(),
    0,
  );
  await noDemoContext.close();
  passed(
    "Non-demo runtime metadata never displays the sample account shortcut",
    "runtime-metadata-fixture",
  );
  assert.deepEqual(errors, []);
  assert.deepEqual(failures, []);
  assert.deepEqual(
    audits.filter(
      (item) => item.violations.length || item.scroll > item.width + 1,
    ),
    [],
    "Rendered states must have no audited accessibility violations or horizontal overflow",
  );
} catch (error) {
  failure = error instanceof Error ? error.message : String(error);
  console.error(failure);
} finally {
  await writeFile(
    join(output, "companion.json"),
    JSON.stringify(
      {
        passed: !failure,
        checks,
        audits,
        runtime_errors: errors,
        unexpected_api_failures: failures,
        ...(failure ? { failure } : {}),
        boundaries: [
          "Actual production bundle and isolated synthetic local API unless a check explicitly names a controlled fixture.",
          "Chromium viewports at 1440/390/320 pixels; not physical Android/iOS, OS vault, microphone, carrier or vendor qualification.",
          "Automated axe checks are scoped to the recorded rendered states and do not establish full accessibility conformance.",
          "Uploaded evidence is synthetic and hashed locally; no real person, agreement, approval, financial transfer or external message is asserted.",
        ],
      },
      null,
      2,
    ) + "\n",
  );
  await browser.close();
}
if (failure) process.exitCode = 1;
