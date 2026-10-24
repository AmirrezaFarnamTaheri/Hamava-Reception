import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const packaged = require("@sparticuz/chromium");
const base = process.env.HAMAAVA_BASE_URL || "http://127.0.0.1:8000",
  output = process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamaava-ui-validation";
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
  bypassCSP: true,
});
const page = await context.newPage();
const checks = [],
  errors = [],
  audits = [];
let failure, originalPolicy;
const run = Date.now().toString(36),
  password = "Synthetic-Clinical-" + run + "!",
  email = "clinical-" + run + "@example.test";
page.on("pageerror", (e) => errors.push(e.message));
function passed(name) {
  checks.push(name);
  console.log(JSON.stringify({ passed: name }));
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
async function seedWrite(path, data) {
  const token = await page.evaluate(() =>
    sessionStorage.getItem("hamaava_staff_session"),
  );
  const response = await context.request.post(base + "/api/v1" + path, {
    headers: { Authorization: "Bearer " + token },
    data,
  });
  assert(
    response.ok(),
    `Synthetic fixture ${path} returned ${response.status()}`,
  );
  return response.json();
}
async function action(path, perform, method = "POST", target = page) {
  const [response] = await Promise.all([
    target.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/v1" + path &&
        r.request().method() === method,
    ),
    perform(),
  ]);
  const value = await response.json();
  assert(
    response.ok(),
    path + " " + response.status() + " " + JSON.stringify(value),
  );
  return value;
}
async function tab(label) {
  await page.goto(base + "/settings", { waitUntil: "networkidle" });
  await page.getByRole("tab", { name: label, exact: true }).click();
  await page.waitForLoadState("networkidle");
}
async function inspect(label, target = page) {
  await target.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const findings = await target.evaluate(async () => {
    const report = await window.axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
    });
    return report.violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      count: item.nodes.length,
    }));
  });
  audits.push({ label, findings });
  assert.equal(findings.length, 0, JSON.stringify({ label, findings }));
}
function datePlus(n) {
  const date = new Date(
    new Intl.DateTimeFormat("en-CA", {
      timeZone: "Asia/Tehran",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(new Date()) + "T12:00:00Z",
  );
  date.setUTCDate(date.getUTCDate() + n);
  return date.toISOString().slice(0, 10);
}
async function publishPolicy(policy) {
  await tab("یادآوری و پیگیری");
  await page
    .getByLabel("فاصله‌های یادآوری تا نوبت، به دقیقه", { exact: true })
    .fill(policy.reminder_offsets_minutes.join(", "));
  await page
    .getByRole("checkbox", {
      name: "زمانی که ظرفیت واقعی آزاد شد، پیشنهاد انتظار به‌صورت خودکار آماده شود.",
    })
    .setChecked(policy.waitlist_auto_offer);
  await page
    .getByLabel("حداکثر پیشنهاد در هر نوبت بررسی", { exact: true })
    .fill(String(policy.waitlist_offer_limit_per_run));
  await page
    .getByRole("checkbox", {
      name: "برنامهٔ پیگیری پس از مراجعه برای تأیید مسئول بالینی آماده شود.",
    })
    .setChecked(policy.followup_enabled);
  await page
    .getByLabel("روزهای پیگیری پس از مراجعه", { exact: true })
    .fill(policy.followup_offsets_days.join(", "));
  return action(
    "/operations/outreach-policy",
    () =>
      page
        .getByRole("button", { name: "انتشار قواعد پیام‌رسانی", exact: true })
        .click(),
    "PUT",
  );
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
  assert.equal((await read("/operations/integrations")).mode, "demo");
  passed("Demo-only gate for consent and finance controls");
  await tab("تیم و همکاری");
  await page.getByRole("button", { name: "افزودن همکار", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("نام همکار", { exact: true })
    .fill("پزشک مجاز آزمایشی " + run);
  await dialog.getByLabel("ایمیل حساب", { exact: true }).fill(email);
  await dialog
    .getByLabel("نقش در این مرکز", { exact: true })
    .selectOption("clinician");
  await dialog
    .getByLabel("گذرواژهٔ آغازین برای حساب جدید", { exact: true })
    .fill(password);
  await action("/operations/team", () =>
    dialog.getByRole("button", { name: "ثبت دسترسی", exact: true }).click(),
  );
  await dialog.waitFor({ state: "hidden" });
  originalPolicy = await read("/operations/outreach-policy");
  const published = await publishPolicy({
    ...originalPolicy,
    followup_enabled: true,
    followup_offsets_days: [365],
    waitlist_auto_offer: false,
  });
  assert.equal(published.followup_effective, false);
  await inspect("outreach-owner-policy");
  passed(
    "Publishing followup cadence requires a new independent clinical approval",
  );
  const clinicalContext = await browser.newContext({
    viewport: { width: 1100, height: 900 },
    locale: "fa-IR",
    bypassCSP: true,
  });
  const clinical = await clinicalContext.newPage();
  await clinical.goto(base + "/", { waitUntil: "networkidle" });
  await clinical.getByLabel("ایمیل", { exact: true }).fill(email);
  await clinical.getByLabel("گذرواژه", { exact: true }).fill(password);
  await clinical.getByRole("button", { name: "ورود به هم‌آوا" }).click();
  await clinical
    .getByRole("button", { name: "خروج از حساب", exact: true })
    .waitFor();
  await clinical.goto(base + "/settings", { waitUntil: "networkidle" });
  await clinical
    .getByRole("tab", { name: "یادآوری و پیگیری", exact: true })
    .click();
  await clinical
    .getByRole("checkbox", {
      name: "به‌عنوان مسئول بالینی مجاز، پیام اداری و روزهای پیگیری نسخهٔ جاری را بررسی و تأیید می‌کنم.",
    })
    .check();
  const approved = await action(
    "/operations/outreach-policy/approve",
    () =>
      clinical
        .getByRole("button", { name: "تأیید برنامهٔ پیگیری", exact: true })
        .click(),
    "POST",
    clinical,
  );
  assert.equal(approved.followup_effective, true);
  await clinicalContext.close();
  passed(
    "Separate tenant clinician account can explicitly approve the current cadence",
  );
  let appointments = await read("/appointments");
  let attended = appointments.find((item) => item.attendance === "ATTENDED");
  if (!attended) {
    const candidate = appointments.find(
      (item) =>
        item.status === "CONFIRMED" &&
        !item.attendance &&
        new Date(item.start_at) < new Date(),
    );
    assert(
      candidate,
      "Synthetic seed must contain an elapsed confirmed appointment to exercise attendance",
    );
    await page.goto(base + "/appointments", { waitUntil: "networkidle" });
    await page
      .getByLabel("انتخاب تاریخ میلادی", { exact: true })
      .fill(candidate.local_date);
    const row = page
      .getByRole("row")
      .filter({ has: page.getByText(candidate.patient_name, { exact: true }) })
      .first();
    await action(
      `/appointments/${candidate.id}/outcome`,
      () =>
        row.getByRole("button", { name: "مراجعه کرد", exact: true }).click(),
      "PATCH",
    );
    attended = await read("/operations/appointments/" + candidate.id);
  }
  await page.goto(base + "/capacity", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "پس از مراجعه", exact: true }).click();
  await page
    .getByRole("button", { name: "افزودن پیگیری", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("نوبت با مراجعهٔ انجام‌شده", { exact: true })
    .selectOption(attended.id);
  assert(
    await dialog
      .getByRole("button", { name: "ثبت درخواست پیگیری", exact: true })
      .isDisabled(),
  );
  await dialog.getByRole("checkbox").check();
  const enrollment = await action("/operations/followups", () =>
    dialog
      .getByRole("button", { name: "ثبت درخواست پیگیری", exact: true })
      .click(),
  );
  assert(enrollment.id);
  await dialog.waitFor({ state: "hidden" });
  const reset = await publishPolicy(originalPolicy);
  assert.equal(reset.followup_effective, false);
  originalPolicy = null;
  passed(
    "Attended-patient enrollment requires separate consent; resetting policy removes approval",
  );
  await tab("پزشکان و خدمات");
  await page.getByRole("button", { name: "افزودن", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("نام نمایشی", { exact: true })
    .fill("پزشک شیفت آزمایشی " + run);
  await dialog
    .getByLabel("تخصص یا نقش", { exact: true })
    .fill("آزمون برنامهٔ حضور");
  await dialog
    .getByRole("checkbox", { name: "برنامهٔ حضور اختصاصی داشته باشد." })
    .check();
  await dialog
    .locator(".shift-day")
    .first()
    .getByRole("button", { name: "افزودن بازه", exact: true })
    .click();
  await dialog.getByLabel("شروع شنبه، بازهٔ 1", { exact: true }).fill("10:00");
  await dialog.getByLabel("پایان شنبه، بازهٔ 1", { exact: true }).fill("12:00");
  await inspect("practitioner-shifts-dialog");
  const provider = await action("/practitioners", () =>
    dialog.getByRole("button", { name: "ذخیره", exact: true }).click(),
  );
  assert.deepEqual(provider.working_hours["5"], [["10:00", "12:00"]]);
  await dialog.waitFor({ state: "hidden" });
  passed(
    "No-code practitioner shifts save actual ordered local-time intervals",
  );
  const before = await read("/appointments");
  await tab("حریم خصوصی");
  await page
    .getByRole("button", {
      name: "ثبت انصراف از پیام‌های اختیاری",
      exact: true,
    })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("شمارهٔ همراه مراجعه‌کننده", { exact: true })
    .fill("09359998889");
  await dialog
    .getByRole("checkbox", {
      name: "هویت و درخواست مراجعه‌کننده را بررسی کرده‌ام و انتخاب او را ثبت می‌کنم.",
    })
    .check();
  const revoked = await action("/operations/consents/revoke", () =>
    dialog.getByRole("button", { name: "ثبت انصراف", exact: true }).click(),
  );
  assert.equal(revoked.status, "REVOKED");
  assert.deepEqual(revoked.purposes.slice().sort(), [
    "followup",
    "reminder",
    "waitlist",
  ]);
  assert.equal((await read("/appointments")).length, before.length);
  await dialog.getByRole("button", { name: "بستن", exact: true }).click();
  passed(
    "Purpose-bound opt-out records revocation and preserves appointment records",
  );
  await action("/auth/switch", () =>
    page
      .getByLabel("انتخاب مرکز", { exact: true })
      .selectOption("clinic-niloufar"),
  );
  await page.waitForFunction(
    () => document.querySelector("#clinic-switch")?.value === "clinic-niloufar",
  );
  let refund = (await read("/operations/refunds")).find(
    (item) => item.status === "REQUESTED",
  );
  if (!refund) {
    // Each CI suite owns a fresh synthetic database; do not depend on prior workflows.
    assert.equal((await read("/operations/integrations")).mode, "demo");
    let slots = [];
    for (let day = 4; day <= 12 && !slots.length; day++)
      slots = await read(
        "/slots?provider_id=provider-niloufar-1&service_id=service-salon&date=" +
          datePlus(day),
      );
    assert(
      slots.length,
      "The isolated synthetic refund fixture needs an available slot",
    );
    const booking = await seedWrite("/appointments", {
      slot_id: slots[0].slot_id,
      patient_name: "بازپرداخت ساختگی آزمون مستقل",
      phone: "09127770009",
      confirmed: true,
      reminder_opt_in: false,
      idempotency_key: "outreach-booking-" + run,
    });
    assert.equal(booking.status, "PENDING_PAYMENT");
    const payment = await seedWrite("/operations/payments", {
      appointment_id: booking.id,
    });
    assert.equal(payment.status, "DEMO_PENDING");
    await seedWrite(`/operations/payments/${payment.id}/simulate`, {});
    const requested = await seedWrite(
      `/operations/payments/${payment.id}/refunds`,
      {
        amount_toman: payment.amount_toman,
        reason: "آزمون مستقل بررسی بازپرداخت " + run,
        idempotency_key: "outreach-refund-" + run,
      },
    );
    refund = (await read("/operations/refunds")).find(
      (item) => item.id === requested.id,
    );
  }
  assert(
    refund?.status === "REQUESTED",
    "The isolated synthetic requested refund must exist",
  );
  await page.goto(base + "/capacity", { waitUntil: "networkidle" });
  await page
    .getByRole("button", { name: "بیعانه و بازپرداخت", exact: true })
    .click();
  const row = page
    .getByRole("row")
    .filter({ has: page.getByText(refund.reason, { exact: true }) })
    .first();
  await row.getByRole("button", { name: "بررسی و تطبیق", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("نتیجهٔ بررسی", { exact: true })
    .selectOption("REFUSE");
  await dialog
    .getByLabel("دلیل و مرجع نتیجه", { exact: true })
    .fill("رد درخواست ساختگی آزمون، بدون اجرای انتقال وجه");
  await dialog.getByRole("checkbox").check();
  const reviewed = await action(`/operations/refunds/${refund.id}/review`, () =>
    dialog
      .getByRole("button", { name: "ثبت نتیجهٔ بررسی", exact: true })
      .click(),
  );
  assert.equal(reviewed.status, "REFUSED");
  assert.equal(reviewed.external_transfer_performed, false);
  await dialog.waitFor({ state: "hidden" });
  const disputeBefore = await read("/operations/disputes");
  await page
    .getByRole("button", { name: "اختلاف درگاه", exact: true })
    .first()
    .click();
  dialog = page.getByRole("dialog");
  assert(
    await dialog
      .getByRole("button", { name: "ثبت پروندهٔ اختلاف", exact: true })
      .isDisabled(),
  );
  await inspect("financial-evidence-dialog");
  await dialog.getByRole("button", { name: "بازگشت", exact: true }).click();
  assert.equal(
    (await read("/operations/disputes")).length,
    disputeBefore.length,
  );
  passed(
    "Refund refusal is audited without a transfer; dispute evidence is required and no fictional case is recorded",
  );
  await action("/auth/switch", () =>
    page
      .getByLabel("انتخاب مرکز", { exact: true })
      .selectOption("clinic-bahar"),
  );
  await page.waitForFunction(
    () => document.querySelector("#clinic-switch")?.value === "clinic-bahar",
  );
  await tab("تیم و همکاری");
  const member = (await read("/operations/team")).find(
    (item) => item.email === email,
  );
  await page
    .getByRole("row")
    .filter({ hasText: email })
    .getByRole("button", { name: "لغو دسترسی", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await action(
    `/operations/team/${member.membership_id}`,
    () =>
      dialog
        .getByRole("button", { name: "تأیید لغو دسترسی", exact: true })
        .click(),
    "DELETE",
  );
  await dialog.waitFor({ state: "hidden" });
  passed("Temporary synthetic clinician membership is revoked");
  assert.deepEqual(errors, []);
} catch (e) {
  failure = e.message
    .replaceAll(password, "[redacted]")
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
      path: output + "/outreach-failure.png",
      fullPage: true,
      mask: [page.locator('input[type="password"],textarea[readonly]')],
    });
} finally {
  if (originalPolicy && !page.isClosed())
    try {
      await publishPolicy(originalPolicy);
    } catch {}
  await writeFile(
    output + "/outreach.json",
    JSON.stringify(
      {
        checks,
        errors,
        audits,
        failure,
        synthetic_data: true,
        financial_transfers_performed: false,
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ checks: checks.length, errors, failure }));
  await browser.close();
}
