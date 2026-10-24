import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const packaged = require("@sparticuz/chromium");
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
});
const page = await context.newPage();
const errors = [];
const checks = [];
const run = Date.now().toString(36);
page.on("pageerror", (error) => errors.push(error.message));
function passed(name) {
  checks.push(name);
  console.log(JSON.stringify({ passed: name }));
}
async function api(path) {
  const token = await page.evaluate(() =>
    sessionStorage.getItem("hamaava_staff_session"),
  );
  const r = await context.request.get(base + "/api/v1" + path, {
    headers: { Authorization: "Bearer " + token },
  });
  assert(r.ok(), path + " " + r.status());
  return r.json();
}
async function responseAction(path, action, method = "POST") {
  const [response] = await Promise.all([
    page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/v1" + path &&
        r.request().method() === method,
    ),
    action(),
  ]);
  const result = await response.json();
  assert(
    response.ok(),
    path + " " + response.status() + " " + JSON.stringify(result),
  );
  return result;
}
function datePlus(days) {
  const date = new Date(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Tehran",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date()) + "T12:00:00Z",
  );
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}
async function pickSlot(dialog, provider, service, date) {
  await dialog
    .getByLabel("پزشک یا ارائه‌دهنده", { exact: true })
    .selectOption(provider);
  await dialog.getByLabel("خدمت", { exact: true }).selectOption(service);
  await dialog.getByLabel("انتخاب تاریخ میلادی", { exact: true }).fill(date);
  await dialog.locator(".slot-option").first().waitFor();
  await dialog.locator(".slot-option").first().click();
}
async function book(name, provider, service, date) {
  await page.goto(base + "/appointments", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "ثبت نوبت", exact: true }).click();
  const dialog = page.getByRole("dialog");
  assert(
    await dialog
      .getByRole("button", { name: "ثبت نوبت", exact: true })
      .isDisabled(),
  );
  await pickSlot(dialog, provider, service, date);
  await dialog.getByLabel("نام مراجعه‌کننده", { exact: true }).fill(name);
  await dialog.getByLabel("شمارهٔ همراه", { exact: true }).fill("09129990001");
  await dialog
    .getByRole("checkbox", {
      name: "زمان و اطلاعات نوبت را با مراجعه‌کننده تأیید کرده‌ام.",
    })
    .check();
  const result = await responseAction("/appointments", () =>
    dialog.getByRole("button", { name: "ثبت نوبت", exact: true }).click(),
  );
  await dialog.waitFor({ state: "hidden" });
  await page.getByText(name, { exact: true }).waitFor();
  return result;
}
try {
  await page.goto(base + "/", { waitUntil: "networkidle" });
  await page
    .getByRole("button", { name: "استفاده از حساب نمایشی", exact: true })
    .click();
  await page.getByRole("button", { name: "ورود به هم‌آوا" }).click();
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
  const integration = await api("/operations/integrations");
  assert.equal(
    integration.mode,
    "demo",
    "Workflow exercises are allowed only against explicit synthetic demo mode",
  );
  passed("Demo-only safety gate and staff login");
  const date = datePlus(4);
  let booking = await book(
    "مراجع آزمایش مرورگر " + run,
    "provider-bahar-1",
    "service-consultation",
    date,
  );
  assert.equal(booking.status, "CONFIRMED");
  passed(
    "Staff booking waits for explicit confirmation and displays authoritative result",
  );
  await page
    .getByRole("button", {
      name: "جابجایی نوبت " + booking.patient_name,
      exact: true,
    })
    .click();
  let dialog = page.getByRole("dialog");
  await pickSlot(dialog, booking.provider_id, booking.service_id, datePlus(5));
  booking = await responseAction(
    "/appointments/" + booking.id + "/reschedule",
    () =>
      dialog
        .getByRole("button", { name: "ثبت زمان جدید", exact: true })
        .click(),
  );
  await dialog.waitFor({ state: "hidden" });
  assert.equal(booking.local_date, datePlus(5));
  await page.getByText(booking.patient_name, { exact: true }).waitFor();
  passed("Reschedule changes the real calendar and selected day");
  await page
    .getByRole("button", {
      name: "لغو نوبت " + booking.patient_name,
      exact: true,
    })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("دلیل لغو (اختیاری)")
    .fill("پایان آزمون نمایشی مرورگر");
  booking = await responseAction(
    "/appointments/" + booking.id + "/cancel",
    () =>
      dialog
        .getByRole("button", { name: "تأیید لغو نوبت", exact: true })
        .click(),
  );
  assert.equal(booking.status, "CANCELED");
  await dialog.waitFor({ state: "hidden" });
  passed("Cancellation is explicit, versioned, and visible");
  await page.goto(base + "/tasks", { waitUntil: "networkidle" });
  const resolve = page
    .getByRole("button", { name: "ثبت نتیجهٔ پیگیری", exact: true })
    .first();
  if (await resolve.count()) {
    await resolve.click();
    dialog = page.getByRole("dialog");
    await dialog
      .getByLabel("چه اقدامی انجام شد؟")
      .fill("نتیجهٔ نمایشی برای بررسی عملکرد فرم ثبت شد.");
    const [response] = await Promise.all([
      page.waitForResponse(
        (r) => r.url().endsWith("/actions") && r.request().method() === "POST",
      ),
      dialog.getByRole("button", { name: "ثبت نتیجه و بستن" }).click(),
    ]);
    assert(response.ok());
    assert.equal((await response.json()).status, "RESOLVED");
    await dialog.waitFor({ state: "hidden" });
    passed("Staff task resolution persists");
  }
  await page.goto(base + "/capacity", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "افزودن", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("نام مراجعه‌کننده", { exact: true })
    .fill("انتظار آزمایشی " + run);
  await dialog.getByLabel("شماره همراه", { exact: true }).fill("09129990002");
  await dialog
    .getByLabel("پزشک", { exact: true })
    .selectOption("provider-bahar-1");
  await dialog
    .getByLabel("خدمت", { exact: true })
    .selectOption("service-consultation");
  await dialog.getByLabel("از تاریخ", { exact: true }).fill(datePlus(6));
  await dialog.getByLabel("تا تاریخ", { exact: true }).fill(datePlus(6));
  await dialog.getByRole("checkbox").check();
  const entry = await responseAction("/operations/waitlist", () =>
    dialog
      .getByRole("button", { name: "ثبت در فهرست انتظار", exact: true })
      .click(),
  );
  assert.equal(entry.status, "WAITING");
  await dialog.waitFor({ state: "hidden" });
  passed("Waitlist entry requires outreach consent");
  await page.getByRole("button", { name: "پیشنهاد زمان", exact: true }).click();
  dialog = page.getByRole("dialog");
  await pickSlot(
    dialog,
    "provider-bahar-1",
    "service-consultation",
    datePlus(6),
  );
  const offer = await responseAction("/operations/waitlist/offer", () =>
    dialog
      .getByRole("button", { name: "انتخاب فرد و نگه‌داشتن زمان", exact: true })
      .click(),
  );
  if (offer.status === "OFFERED") {
    await dialog
      .getByRole("button", { name: "بستن پنجره", exact: true })
      .click();
    await page.reload({ waitUntil: "networkidle" });
    const row = page
      .getByRole("row")
      .filter({ has: page.getByText("انتظار آزمایشی " + run, { exact: true }) })
      .last();
    await row
      .getByRole("button", { name: "ثبت پاسخ مراجعه‌کننده", exact: true })
      .click();
    dialog = page.getByRole("dialog");
    assert(
      await dialog
        .getByRole("button", { name: "ثبت پذیرش پیشنهاد", exact: true })
        .isDisabled(),
    );
    await dialog.getByRole("checkbox").check();
    const waitBooking = await responseAction(
      "/operations/waitlist/offers/" + offer.id + "/accept",
      () =>
        dialog
          .getByRole("button", { name: "ثبت پذیرش پیشنهاد", exact: true })
          .click(),
    );
    assert(
      ["CONFIRMED", "PENDING_PAYMENT", "PENDING_STAFF_APPROVAL"].includes(
        waitBooking.status,
      ),
    );
    await dialog.getByRole("button", { name: "بستن", exact: true }).click();
    passed(
      "Waitlist offer survives reload and accepts only after patient confirmation",
    );
  } else {
    assert.equal(offer.status, "QUIET_HOURS");
    await dialog
      .getByRole("button", { name: "بستن پنجره", exact: true })
      .click();
    passed("Waitlist quiet-hours boundary is honestly displayed");
  }
  await responseAction("/auth/switch", () =>
    page
      .getByLabel("انتخاب مرکز", { exact: true })
      .selectOption("clinic-niloufar"),
  );
  await page.waitForFunction(
    () => document.querySelector("#clinic-switch")?.value === "clinic-niloufar",
  );
  const depositBooking = await book(
    "بیعانه آزمایشی " + run,
    "provider-niloufar-1",
    "service-salon",
    datePlus(4),
  );
  assert.equal(depositBooking.status, "PENDING_PAYMENT");
  await page.goto(base + "/capacity", { waitUntil: "networkidle" });
  await page
    .getByRole("button", { name: "بیعانه و بازپرداخت", exact: true })
    .click();
  await page
    .getByRole("button", { name: "درخواست بیعانه", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("نوبت منتظر پرداخت", { exact: true })
    .selectOption(depositBooking.id);
  const payment = await responseAction("/operations/payments", () =>
    dialog
      .getByRole("button", { name: "ایجاد درخواست پرداخت", exact: true })
      .click(),
  );
  assert.equal(payment.status, "DEMO_PENDING");
  await dialog.getByRole("button", { name: "بستن", exact: true }).click();
  let row = page
    .getByRole("row")
    .filter({ has: page.getByText(depositBooking.reference, { exact: true }) });
  await row
    .getByRole("button", { name: "پرداخت آزمایشی", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await responseAction("/operations/payments/" + payment.id + "/simulate", () =>
    dialog
      .getByRole("button", { name: "ثبت رویداد آزمایشی", exact: true })
      .click(),
  );
  await dialog.waitFor({ state: "hidden" });
  passed("Deposit intent and explicit demo payment settlement");
  row = page
    .getByRole("row")
    .filter({ has: page.getByText(depositBooking.reference, { exact: true }) });
  await row.getByRole("button", { name: "بازپرداخت", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("دلیل بازپرداخت", { exact: true })
    .fill("آزمون نمایشی پیگیری بازپرداخت");
  const refund = await responseAction(
    "/operations/payments/" + payment.id + "/refunds",
    () =>
      dialog
        .getByRole("button", { name: "ثبت درخواست بازپرداخت", exact: true })
        .click(),
  );
  assert.equal(refund.status, "REQUESTED");
  await dialog
    .getByRole("button", { name: "پیگیری در زمانی دیگر", exact: true })
    .click();
  await page.reload({ waitUntil: "networkidle" });
  await page
    .getByRole("button", { name: "بیعانه و بازپرداخت", exact: true })
    .click();
  await page
    .getByRole("button", { name: "ثبت مدرک اجرا", exact: true })
    .first()
    .click();
  dialog = page.getByRole("dialog");
  assert(
    await dialog
      .getByRole("button", { name: "ثبت مدرک بازپرداخت", exact: true })
      .isDisabled(),
  );
  await dialog
    .getByRole("button", { name: "پیگیری در زمانی دیگر", exact: true })
    .click();
  passed(
    "Refund request persists across reload; execution evidence remains explicitly unrecorded",
  );
  await responseAction("/auth/switch", () =>
    page
      .getByLabel("انتخاب مرکز", { exact: true })
      .selectOption("clinic-bahar"),
  );
  await page.waitForFunction(
    () => document.querySelector("#clinic-switch")?.value === "clinic-bahar",
  );
  await page.goto(base + "/settings", { waitUntil: "networkidle" });
  await page.getByRole("tab", { name: "پزشکان و خدمات", exact: true }).click();
  await page.getByRole("button", { name: "افزودن", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("نام نمایشی", { exact: true })
    .fill("همکار آزمایشی " + run);
  await dialog
    .getByLabel("تخصص یا نقش", { exact: true })
    .fill("هماهنگی نمایشی");
  const provider = await responseAction("/practitioners", () =>
    dialog.getByRole("button", { name: "ذخیره", exact: true }).click(),
  );
  await dialog.waitFor({ state: "hidden" });
  await page.getByRole("button", { name: "افزودن خدمت", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("نام خدمت", { exact: true })
    .fill("خدمت آزمایشی " + run);
  await dialog
    .getByRole("checkbox", { name: "همکار آزمایشی " + run, exact: true })
    .check();
  const service = await responseAction("/services", () =>
    dialog
      .getByRole("button", { name: "تأیید و انتشار خدمت", exact: true })
      .click(),
  );
  assert(service.provider_ids.includes(provider.id));
  await dialog.waitFor({ state: "hidden" });
  passed(
    "No-code practitioner and service creation publishes an actual catalog",
  );
  await page.screenshot({
    path: output + "/catalog-workflow.png",
    fullPage: true,
  });
  assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({
    path: output + "/workflow-failure.png",
    fullPage: true,
  });
  console.error(error.stack);
  process.exitCode = 1;
} finally {
  await writeFile(
    output + "/workflows.json",
    JSON.stringify({ checks, errors }, null, 2),
  );
  console.log(
    JSON.stringify({
      checks: checks.length,
      errors,
      report: output + "/workflows.json",
    }),
  );
  await browser.close();
}
