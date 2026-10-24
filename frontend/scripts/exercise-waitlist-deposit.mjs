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
  audits = [],
  observations = [];
const run = Date.now().toString(36);
let failure,
  paymentRequests = 0,
  injectedFailures = 0;
const timeConsent =
  "مراجعه‌کننده این زمان را پذیرفته و به ثبت آن اجازه داده است.";
const termsConsent =
  "مراجعه‌کننده مبلغ بیعانه و شرایط لغو و بازپرداخت همین نسخه را خوانده یا شنیده و پذیرفته است.";
page.on("pageerror", (error) => errors.push(error.message));
page.on("request", (request) => {
  if (
    request.method() === "POST" &&
    /\/operations\/(payments|refunds)(\/|$)/.test(
      new URL(request.url()).pathname,
    )
  )
    paymentRequests++;
});
function passed(name) {
  checks.push(name);
  console.log(JSON.stringify({ passed: name }));
}
async function read(path) {
  const credential = await page.evaluate(() =>
    sessionStorage.getItem("hamaava_staff_session"),
  );
  const response = await context.request.get(base + "/api/v1" + path, {
    headers: { Authorization: "Bearer " + credential },
  });
  assert(response.ok(), path + " " + response.status());
  return response.json();
}
async function action(path, perform, method = "POST") {
  const [response] = await Promise.all([
    page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/v1" + path &&
        r.request().method() === method,
    ),
    perform(),
  ]);
  assert(response.ok(), path + " " + response.status());
  return {
    value: await response.json(),
    payload: response.request().postDataJSON(),
  };
}
async function switchClinic(id) {
  if (
    (await page.getByLabel("انتخاب مرکز", { exact: true }).inputValue()) !== id
  )
    await action("/auth/switch", () =>
      page.getByLabel("انتخاب مرکز", { exact: true }).selectOption(id),
    );
  await page.waitForLoadState("networkidle");
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
    })),
    viewport: window.innerWidth,
    width: document.documentElement.scrollWidth,
  }));
  audits.push({ label, ...result });
  assert.equal(result.findings.length, 0, label + " accessibility findings");
  assert(result.width <= result.viewport, label + " overflow");
}
async function createOffer({ provider, service, day, index }) {
  await page.goto(base + "/capacity", { waitUntil: "networkidle" });
  const name = "انتظار بیعانهٔ آزمایشی " + run + " " + index;
  const phone =
    "091" + String((Date.now() + index) % 100000000).padStart(8, "0");
  await page.getByRole("button", { name: "افزودن", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await dialog.getByLabel("نام مراجعه‌کننده", { exact: true }).fill(name);
  await dialog.getByLabel("شماره همراه", { exact: true }).fill(phone);
  await dialog.getByLabel("پزشک", { exact: true }).selectOption(provider);
  await dialog.getByLabel("خدمت", { exact: true }).selectOption(service);
  await dialog.getByLabel("از تاریخ", { exact: true }).fill(day);
  await dialog.getByLabel("تا تاریخ", { exact: true }).fill(day);
  await dialog.getByRole("checkbox").check();
  const entry = (
    await action("/operations/waitlist", () =>
      dialog
        .getByRole("button", { name: "ثبت در فهرست انتظار", exact: true })
        .click(),
    )
  ).value;
  await dialog.waitFor({ state: "hidden" });
  await page.getByRole("button", { name: "پیشنهاد زمان", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("پزشک یا ارائه‌دهنده", { exact: true })
    .selectOption(provider);
  await dialog.getByLabel("خدمت", { exact: true }).selectOption(service);
  await dialog.getByLabel("انتخاب تاریخ میلادی", { exact: true }).fill(day);
  await dialog.locator(".slot-option").first().click();
  const offer = (
    await action("/operations/waitlist/offer", () =>
      dialog
        .getByRole("button", {
          name: "انتخاب فرد و نگه‌داشتن زمان",
          exact: true,
        })
        .click(),
    )
  ).value;
  assert.equal(
    offer.status,
    "OFFERED",
    "Fixture must run during permitted outreach hours",
  );
  assert.equal(
    offer.entry_id,
    entry.id,
    "The synthetic candidate must be the selected candidate",
  );
  await dialog.getByText("هزینهٔ اعلام‌شده:", { exact: false }).waitFor();
  return {
    id: offer.id,
    name,
    deposit_toman: offer.deposit_toman,
    payment_terms: offer.payment_terms,
  };
}
async function accept(offer) {
  const dialog = page.getByRole("dialog");
  const { value: booking, payload } = await action(
    "/operations/waitlist/offers/" + offer.id + "/accept",
    () =>
      dialog
        .getByRole("button", { name: "ثبت پذیرش پیشنهاد", exact: true })
        .click(),
  );
  assert.equal(payload.confirmed, true);
  if (offer.deposit_toman > 0) {
    assert.equal(payload.payment_terms_accepted, true);
    assert.equal(payload.payment_terms_version, offer.payment_terms.version);
    assert.equal(booking.status, "PENDING_PAYMENT");
    assert.notEqual(booking.payment_status, "PAID");
    assert.equal(booking.payment_terms.version, offer.payment_terms.version);
    assert(new Date(booking.payment_expires_at) > new Date());
    assert(new Date(booking.payment_expires_at) <= new Date(booking.start_at));
    await dialog
      .getByText("نوبت تا تأیید پرداخت قطعی نیست.", { exact: false })
      .waitFor();
  } else {
    assert.equal(payload.payment_terms_accepted, undefined);
    assert.equal(payload.payment_terms_version, undefined);
    assert.equal(booking.status, "CONFIRMED");
  }
  observations.push({
    flow: offer.deposit_toman > 0 ? "deposit" : "no_deposit",
    status: booking.status,
    payment_status: booking.payment_status,
    terms_version: booking.payment_terms?.version ?? null,
    terms_sent_and_accepted: payload.payment_terms_accepted === true,
    expiry_capped_at_visit:
      !booking.payment_expires_at ||
      new Date(booking.payment_expires_at) <= new Date(booking.start_at),
  });
  await dialog
    .getByText("پذیرش پیشنهاد در سامانه ثبت شد.", { exact: true })
    .waitFor();
  return booking;
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
  await switchClinic("clinic-niloufar");
  assert.equal((await read("/operations/integrations")).mode, "demo");
  const catalog = await read("/services");
  const service = catalog.find((item) => item.id === "service-salon");
  assert(service?.deposit_toman > 0);
  passed("Explicit demo gate, selected tenant and real deposit service");

  let offer = await createOffer({
    provider: "provider-niloufar-1",
    service: service.id,
    day: datePlus(12),
    index: 1,
  });
  let dialog = page.getByRole("dialog");
  const terms = await read(
    "/operations/waitlist/offers/" + offer.id + "/terms",
  );
  assert.equal(terms.payment_terms.synthetic, true);
  assert(
    !Object.keys(terms.payment_terms).some((key) => key.includes("merchant")),
  );
  assert.equal(await dialog.getByRole("checkbox").count(), 2);
  await dialog
    .getByRole("checkbox", { name: timeConsent, exact: true })
    .check();
  assert(
    await dialog
      .getByRole("button", { name: "ثبت پذیرش پیشنهاد", exact: true })
      .isDisabled(),
  );
  await dialog.locator(".payment-terms summary").click();
  await dialog
    .getByRole("checkbox", { name: termsConsent, exact: true })
    .check();
  assert(
    await dialog
      .getByRole("button", { name: "ثبت پذیرش پیشنهاد", exact: true })
      .isEnabled(),
  );
  await inspect("Desktop immediate deposit offer with expanded current terms");
  passed(
    "Immediate offer displays safe current terms and separately requires patient time and financial acceptance",
  );

  const acceptPath =
    "/api/v1/operations/waitlist/offers/" + offer.id + "/accept";
  const intercept = async (route) => {
    injectedFailures++;
    await route.fulfill({
      status: 409,
      contentType: "application/json",
      body: JSON.stringify({
        detail: {
          code: "PAYMENT_TERMS_CONFIRMATION_REQUIRED",
          message: "شرایط مالی باید دوباره بررسی شود.",
        },
      }),
    });
  };
  await page.route(base + acceptPath, intercept, { times: 1 });
  const [rejected, refreshed] = await Promise.all([
    page.waitForResponse(
      (r) => new URL(r.url()).pathname === acceptPath && r.status() === 409,
    ),
    page.waitForResponse(
      (r) =>
        new URL(r.url()).pathname ===
          "/api/v1/operations/waitlist/offers/" + offer.id + "/terms" && r.ok(),
    ),
    dialog
      .getByRole("button", { name: "ثبت پذیرش پیشنهاد", exact: true })
      .click(),
  ]);
  assert.equal(rejected.status(), 409);
  await refreshed.finished();
  await page.waitForFunction(
    (label) =>
      [...document.querySelectorAll("label")].some(
        (node) =>
          node.textContent.trim() === label &&
          node.querySelector("input")?.checked === false,
      ),
    termsConsent,
  );
  assert(
    await dialog
      .getByRole("button", { name: "ثبت پذیرش پیشنهاد", exact: true })
      .isDisabled(),
  );
  const unchanged = (await read("/operations/waitlist/offers")).find(
    (item) => item.id === offer.id,
  );
  assert.equal(unchanged.status, "OFFERED");
  assert.equal(unchanged.appointment_id, null);
  passed(
    "Injected stale-terms rejection performs a real terms refresh, clears financial acceptance and creates no reservation",
  );
  await dialog
    .getByRole("checkbox", { name: termsConsent, exact: true })
    .check();
  await accept(offer);
  await inspect("Immediate acceptance remains pending payment");
  await dialog.getByRole("button", { name: "بستن", exact: true }).click();
  passed(
    "Immediate acceptance sends the reviewed version and returns pending payment with authoritative deadline, without settlement",
  );

  offer = await createOffer({
    provider: "provider-niloufar-1",
    service: service.id,
    day: datePlus(13),
    index: 2,
  });
  dialog = page.getByRole("dialog");
  await dialog
    .getByRole("checkbox", { name: timeConsent, exact: true })
    .check();
  await dialog
    .getByRole("checkbox", { name: termsConsent, exact: true })
    .check();
  await dialog.getByRole("button", { name: "بستن پنجره", exact: true }).click();
  await page.reload({ waitUntil: "networkidle" });
  await page.setViewportSize({ width: 390, height: 844 });
  const row = page
    .getByRole("row")
    .filter({ has: page.getByText(offer.name, { exact: true }) })
    .last();
  await row
    .getByRole("button", { name: "ثبت پاسخ مراجعه‌کننده", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByRole("checkbox", { name: termsConsent, exact: true })
    .waitFor();
  assert.equal(
    await dialog.getByRole("checkbox", { checked: true }).count(),
    0,
  );
  await dialog
    .getByRole("checkbox", { name: timeConsent, exact: true })
    .check();
  assert(
    await dialog
      .getByRole("button", { name: "ثبت پذیرش پیشنهاد", exact: true })
      .isDisabled(),
  );
  await dialog.locator(".payment-terms summary").click();
  await inspect("Mobile resumed offer with expanded terms and cleared consent");
  passed(
    "Reloaded offer remains available; mobile resumed acceptance reloads current terms and does not remember earlier checkboxes",
  );
  await dialog
    .getByRole("checkbox", { name: termsConsent, exact: true })
    .check();
  await accept(offer);
  await inspect("Mobile resumed pending-payment result");
  await page.screenshot({
    path: output + "/waitlist-deposit-mobile.png",
    fullPage: true,
  });
  await dialog.getByRole("button", { name: "بستن", exact: true }).click();
  passed(
    "Resumed offer submits versioned acceptance and preserves pending-payment semantics",
  );

  await page.setViewportSize({ width: 1440, height: 1000 });
  await switchClinic("clinic-bahar");
  offer = await createOffer({
    provider: "provider-bahar-1",
    service: "service-consultation",
    day: datePlus(14),
    index: 3,
  });
  dialog = page.getByRole("dialog");
  assert.equal(offer.deposit_toman, 0);
  assert.equal(await dialog.getByRole("checkbox").count(), 1);
  await dialog
    .getByRole("checkbox", { name: timeConsent, exact: true })
    .check();
  await accept(offer);
  await dialog.getByRole("button", { name: "بستن", exact: true }).click();
  passed(
    "No-deposit offers still require explicit patient confirmation and do not send unnecessary financial acceptance",
  );
  assert.equal(paymentRequests, 0);
  assert.equal(injectedFailures, 1);
  assert.deepEqual(errors, []);
  passed(
    "Both deposit paths and the no-deposit regression have no browser errors, accessibility findings, overflow or payment-provider requests",
  );
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
    );
  await page
    .screenshot({
      path: output + "/waitlist-deposit-failure.png",
      fullPage: true,
    })
    .catch(() => {});
  console.error(failure);
  process.exitCode = 1;
} finally {
  await writeFile(
    output + "/waitlist-deposit.json",
    JSON.stringify(
      {
        checks,
        errors,
        audits,
        observations,
        failure,
        synthetic_data: true,
        payment_provider_requests: paymentRequests,
        injected_stale_terms_failures: injectedFailures,
        qualification:
          "The 409 is deliberately injected to test UI recovery; actual-mode stale-policy enforcement is independently covered by backend tests. All successful bookings use the real demo API. No real merchant, transfer or settlement qualification.",
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
      report: output + "/waitlist-deposit.json",
    }),
  );
  await browser.close();
}
