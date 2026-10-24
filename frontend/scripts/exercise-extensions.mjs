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
  bypassCSP: true,
});
const page = await context.newPage();
const checks = [],
  errors = [],
  audits = [],
  secrets = [];
let failure;
const run = Date.now().toString(36);
const name = "آزمون تکمیلی " + run;
const password = "Synthetic-Only-" + run + "!";
secrets.push(password);
page.on("pageerror", (e) => errors.push(e.message));
function passed(name) {
  checks.push(name);
  console.log(JSON.stringify({ passed: name }));
}
function sanitize(value) {
  let text = String(value);
  for (const secret of secrets)
    if (secret) text = text.replaceAll(secret, "[redacted]");
  return text
    .replace(/\/respond\/[^\s#]+#[^\s]+/g, "/respond/[redacted]")
    .replace(/Bearer\s+[A-Za-z0-9._~-]+/gi, "Bearer [redacted]")
    .replace(
      /eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+/g,
      "[redacted session credential]",
    )
    .replace(
      /((?:Authorization|Cookie|Set-Cookie|X-Api-Key):)[^\r\n]*/gi,
      "$1 [redacted]",
    );
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
async function action(path, perform, method = "POST", target = page) {
  const [response] = await Promise.all([
    target.waitForResponse(
      (r) =>
        new URL(r.url()).pathname === "/api/v1" + path &&
        r.request().method() === method,
    ),
    perform(),
  ]);
  const result = await response.json();
  assert(
    response.ok(),
    sanitize(path + " " + response.status() + " " + JSON.stringify(result)),
  );
  return result;
}
async function inspect(label, target = page) {
  await target.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const findings = await target.evaluate(async () => {
    const r = await window.axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
    });
    return r.violations.map((item) => ({
      id: item.id,
      impact: item.impact,
      count: item.nodes.length,
    }));
  });
  audits.push({ label, findings });
  assert.equal(findings.length, 0, JSON.stringify({ label, findings }));
}
async function settingsTab(label) {
  await page.goto(base + "/settings", { waitUntil: "networkidle" });
  await page.getByRole("tab", { name: label, exact: true }).click();
  await page.waitForLoadState("networkidle");
}
function dayPlus(n) {
  const now = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tehran",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const date = new Date(now + "T12:00:00Z");
  date.setUTCDate(date.getUTCDate() + n);
  return date.toISOString().slice(0, 10);
}
async function addMember(role) {
  await settingsTab("تیم و همکاری");
  await page.getByRole("button", { name: "افزودن همکار", exact: true }).click();
  const dialog = page.getByRole("dialog");
  const email = `${role}-${run}@example.test`;
  await dialog
    .getByLabel("نام همکار", { exact: true })
    .fill("همکار آزمایشی " + role + " " + run);
  await dialog.getByLabel("ایمیل حساب", { exact: true }).fill(email);
  await dialog
    .getByLabel("نقش در این مرکز", { exact: true })
    .selectOption(role);
  await dialog
    .getByLabel("گذرواژهٔ آغازین برای حساب جدید", { exact: true })
    .fill(password);
  await action("/operations/team", () =>
    dialog.getByRole("button", { name: "ثبت دسترسی", exact: true }).click(),
  );
  await dialog.waitFor({ state: "hidden" });
  return email;
}
async function signIn(target, email) {
  await target.goto(base + "/", { waitUntil: "networkidle" });
  await target.getByLabel("ایمیل", { exact: true }).fill(email);
  await target.getByLabel("گذرواژه", { exact: true }).fill(password);
  await target.getByRole("button", { name: "ورود به هم‌آوا" }).click();
  await target
    .getByRole("button", { name: "خروج از حساب", exact: true })
    .waitFor();
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
  passed("Demo-only gate for extended synthetic workflows");
  let date, slots;
  for (let i = 8; i < 15; i++) {
    date = dayPlus(i);
    slots = await read(
      `/slots?provider_id=provider-bahar-1&service_id=service-consultation&date=${date}`,
    );
    if (slots.length) break;
  }
  assert(slots.length);
  await page.goto(base + "/appointments", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "ثبت نوبت", exact: true }).click();
  let dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("پزشک یا ارائه‌دهنده", { exact: true })
    .selectOption("provider-bahar-1");
  await dialog
    .getByLabel("خدمت", { exact: true })
    .selectOption("service-consultation");
  await dialog.getByLabel("انتخاب تاریخ میلادی", { exact: true }).fill(date);
  await dialog.locator(".slot-option").first().click();
  await dialog.getByLabel("نام مراجعه‌کننده", { exact: true }).fill(name);
  await dialog.getByLabel("شمارهٔ همراه", { exact: true }).fill("09359998881");
  await dialog
    .getByRole("checkbox", {
      name: "زمان و اطلاعات نوبت را با مراجعه‌کننده تأیید کرده‌ام.",
    })
    .check();
  let booking = await action("/appointments", () =>
    dialog.getByRole("button", { name: "ثبت نوبت", exact: true }).click(),
  );
  await dialog.waitFor({ state: "hidden" });
  await page
    .getByRole("button", { name: "اصلاح اطلاعات " + name, exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("نام صحیح مراجعه‌کننده", { exact: true })
    .fill(name + " اصلاح");
  await dialog
    .getByLabel("شمارهٔ همراه صحیح (در صورت تغییر)", { exact: true })
    .fill("09359998882");
  await dialog
    .getByLabel("دلیل اصلاح", { exact: true })
    .fill("اصلاح اطلاعات ساختگی در آزمون مرورگر");
  await dialog
    .getByRole("checkbox", {
      name: "هویت مراجعه‌کننده و اصلاح‌های بالا را با او تأیید کرده‌ام.",
    })
    .check();
  await inspect("appointment-correction-dialog");
  const previousVersion = booking.version;
  booking = await action(
    `/operations/appointments/${booking.id}/details`,
    () =>
      dialog.getByRole("button", { name: "ثبت اصلاحات", exact: true }).click(),
    "PATCH",
  );
  assert(booking.version > previousVersion);
  assert.equal(booking.patient_name, name + " اصلاح");
  assert.equal(booking.reminder_opt_in, false);
  await dialog.waitFor({ state: "hidden" });
  passed(
    "Audited patient correction updates the real record and resets reminder consent on phone change",
  );
  await page
    .getByRole("button", {
      name: "پیوند پاسخ " + booking.patient_name,
      exact: true,
    })
    .click();
  dialog = page.getByRole("dialog");
  const link = await action(
    `/operations/appointments/${booking.id}/response-link`,
    () =>
      dialog
        .getByRole("button", { name: "ساخت پیوند پاسخ", exact: true })
        .click(),
  );
  secrets.push(link.public_path.split("#")[1], link.public_path);
  await dialog.getByRole("button", { name: "بستن", exact: true }).click();
  const guest = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale: "fa-IR",
    bypassCSP: true,
  });
  const guestPage = await guest.newPage();
  await guestPage.goto(base + link.public_path, { waitUntil: "networkidle" });
  await guestPage
    .getByRole("button", { name: "بله، قصد مراجعه دارم", exact: true })
    .waitFor();
  assert.equal(await guestPage.evaluate(() => location.hash), "");
  await inspect("public-response-mobile", guestPage);
  await guestPage
    .getByRole("button", { name: "بله، قصد مراجعه دارم", exact: true })
    .click();
  assert(
    await guestPage
      .getByRole("button", { name: "تأیید پاسخ", exact: true })
      .isDisabled(),
  );
  await guestPage.getByRole("checkbox").check();
  const reply = await action(
    `/public/appointments/responses/${link.response_id}`,
    () =>
      guestPage
        .getByRole("button", { name: "تأیید پاسخ", exact: true })
        .click(),
    "POST",
    guestPage,
  );
  assert.equal(reply.response_status, "CONFIRMED_ATTENDANCE_INTENT");
  booking = await read("/operations/appointments/" + booking.id);
  assert.equal(booking.attendance, null);
  await guest.close();
  passed(
    "Private public RSVP removes fragment, requires review, and does not mark actual attendance",
  );
  await page.goto(base + "/capacity", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "تغییر برنامه", exact: true }).click();
  await page
    .getByRole("button", { name: "ثبت تغییر برنامه", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog.getByLabel("روز نوبت", { exact: true }).fill(date);
  await dialog
    .getByLabel("نوبت مراجعه‌کننده", { exact: true })
    .selectOption(booking.id);
  await dialog.getByLabel("مدت تأخیر به دقیقه", { exact: true }).fill("15");
  await dialog
    .getByLabel("علت تغییر برنامه", { exact: true })
    .fill("تأخیر ساختگی " + run);
  const preview = await action("/operations/disruptions/preview", () =>
    dialog
      .getByRole("button", { name: "بررسی نوبت‌های متأثر", exact: true })
      .click(),
  );
  assert.equal(preview.affected_count, 1);
  assert.equal(
    (await read("/operations/appointments/" + booking.id)).version,
    booking.version,
  );
  await dialog.getByRole("checkbox").check();
  await inspect("disruption-preview-dialog");
  const disruption = await action("/operations/disruptions", () =>
    dialog
      .getByRole("button", { name: "تأیید و ثبت تغییر برنامه", exact: true })
      .click(),
  );
  await dialog.waitFor({ state: "hidden" });
  assert.equal(
    (await read("/operations/appointments/" + booking.id)).start_at,
    booking.start_at,
  );
  passed(
    "Disruption preview performs no write; confirmed change preserves original appointment time",
  );
  const tasks = await read("/operations/tasks");
  const task = tasks.find(
    (item) =>
      item.appointment_id === booking.id &&
      item.reason === "SCHEDULE_DISRUPTION",
  );
  assert(task);
  await page.goto(base + "/tasks", { waitUntil: "networkidle" });
  let taskCard = page.locator(`[data-task-id="${task.id}"]`);
  await action(`/operations/tasks/${task.id}/actions`, () =>
    taskCard
      .getByRole("button", { name: "پذیرفتن پیگیری", exact: true })
      .click(),
  );
  await taskCard
    .getByRole("button", { name: "تماس مجدد", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("زمان تماس مجدد به وقت تهران", { exact: true })
    .fill(dayPlus(1) + "T12:00");
  await dialog
    .getByLabel("دلیل یا نتیجهٔ این اقدام", { exact: true })
    .fill("تماس مجدد در آزمون نمایشی");
  const callback = await action(`/operations/tasks/${task.id}/actions`, () =>
    dialog
      .getByRole("button", { name: "زمان‌بندی تماس مجدد", exact: true })
      .click(),
  );
  assert.equal(callback.status, "CALLBACK");
  assert(callback.callback_at);
  await dialog.waitFor({ state: "hidden" });
  await taskCard
    .getByRole("button", { name: "ثبت نتیجهٔ پیگیری", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("چه اقدامی انجام شد؟", { exact: true })
    .fill("اقدام ساختگی آزمون ثبت شد");
  const resolved = await action(`/operations/tasks/${task.id}/actions`, () =>
    dialog
      .getByRole("button", { name: "ثبت نتیجه و بستن", exact: true })
      .click(),
  );
  assert.equal(resolved.status, "RESOLVED");
  await dialog.waitFor({ state: "hidden" });
  await page
    .getByLabel("فیلتر پیگیری‌ها", { exact: true })
    .selectOption("RESOLVED");
  taskCard = page.locator(`[data-task-id="${task.id}"]`);
  await taskCard.getByRole("button", { name: "بازگشایی", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("دلیل یا نتیجهٔ این اقدام", { exact: true })
    .fill("نیاز به تصمیم نهایی نوبت در آزمون");
  assert.equal(
    (
      await action(`/operations/tasks/${task.id}/actions`, () =>
        dialog
          .getByRole("button", { name: "بازگشایی درخواست", exact: true })
          .click(),
      )
    ).status,
    "OPEN",
  );
  await dialog.waitFor({ state: "hidden" });
  passed(
    "Task ownership, callback time, resolution, and reopening persist with versioned actions",
  );
  await page.goto(base + "/capacity", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "تغییر برنامه", exact: true }).click();
  let disruptionCard = page
    .locator(".disruption-card")
    .filter({ hasText: "تأخیر ساختگی " + run });
  await disruptionCard
    .getByRole("button", { name: "مرور و تعیین تکلیف", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("تصمیم توافق‌شده", { exact: true })
    .selectOption("KEEP_ORIGINAL");
  await dialog
    .getByLabel("شرح توافق و اقدام", { exact: true })
    .fill("زمان اصلی در آزمون تأیید شد");
  await dialog.getByRole("checkbox").check();
  const impact = disruption.impacts[0];
  booking = await action(
    `/operations/disruptions/impacts/${impact.id}/decision`,
    () =>
      dialog
        .getByRole("button", { name: "ثبت تصمیم نوبت", exact: true })
        .click(),
  );
  assert.equal(booking.status, "CONFIRMED");
  await dialog.waitFor({ state: "hidden" });
  assert.equal(
    (await read("/operations/tasks")).find((row) => row.id === task.id).status,
    "RESOLVED",
  );
  await disruptionCard
    .getByRole("button", { name: "رفع محدودیت برنامه", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("دلیل رفع محدودیت", { exact: true })
    .fill("پایان تغییر ساختگی آزمون");
  await dialog.getByRole("checkbox").check();
  await action(`/operations/disruptions/${disruption.id}/resolve`, () =>
    dialog
      .getByRole("button", { name: "تأیید رفع محدودیت", exact: true })
      .click(),
  );
  await dialog.waitFor({ state: "hidden" });
  passed(
    "Explicit patient disruption decision resolves its staff case; block resolution remains separate",
  );
  const baseline = await read("/settings");
  await settingsTab("اطلاعات و پذیرش");
  await page
    .getByLabel("نشانی", { exact: true })
    .fill(baseline.address + " · آزمون " + run);
  await action(
    "/settings",
    () =>
      page.getByRole("button", { name: "ذخیره و انتشار", exact: true }).click(),
    "PUT",
  );
  await page.getByRole("tab", { name: "نسخه‌های قواعد", exact: true }).click();
  const history = await read("/operations/policies");
  const old = history.revisions.find(
    (row) => row.version === baseline.settings_version,
  );
  assert(old);
  const oldRow = page.getByRole("row").filter({
    has: page.getByText(
      "نسخهٔ " + new Intl.NumberFormat("fa-IR").format(old.version),
      { exact: true },
    ),
  });
  await oldRow
    .getByRole("button", { name: "مرور و بازگردانی", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("دلیل بازگردانی", { exact: true })
    .fill("بازگردانی پس از آزمون مرورگر");
  await dialog.getByRole("checkbox").check();
  await action(`/operations/policies/${old.version}/restore`, () =>
    dialog
      .getByRole("button", { name: "تأیید و بازگردانی", exact: true })
      .click(),
  );
  await dialog.waitFor({ state: "hidden" });
  assert.equal((await read("/settings")).address, baseline.address);
  passed(
    "Policy history restores an explicitly reviewed snapshot with a new current version",
  );
  const profile = await read("/operations/profile");
  await settingsTab("هویت و تلفظ");
  await page
    .getByLabel("نام نمایشی پذیرش", { exact: true })
    .fill("پذیرش آزمایشی " + run);
  await page.getByRole("checkbox").check();
  await action(
    "/operations/profile",
    () =>
      page
        .getByRole("button", { name: "تأیید و انتشار هویت", exact: true })
        .click(),
    "PUT",
  );
  const publicProfile = await context.request.get(
    base + "/api/v1/public/clinics/bahar",
  );
  assert.equal(
    (await publicProfile.json()).identity.brand_name,
    "پذیرش آزمایشی " + run,
  );
  await page
    .getByLabel("نام نمایشی پذیرش", { exact: true })
    .fill(profile.brand_name || "");
  await page.getByRole("checkbox").check();
  await action(
    "/operations/profile",
    () =>
      page
        .getByRole("button", { name: "تأیید و انتشار هویت", exact: true })
        .click(),
    "PUT",
  );
  passed(
    "Reviewed clinic identity publishes safe public branding and can be restored",
  );
  await settingsTab("تیم و همکاری");
  await page.getByRole("button", { name: "مجوز جدید", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("نام همکار یا سامانه", { exact: true })
    .fill("همکار آزمون " + run);
  await dialog
    .getByLabel("هدف مجاز همکاری", { exact: true })
    .fill("بررسی آمار ساختگی آزمون");
  await dialog
    .getByRole("checkbox", {
      name: "دامنهٔ دسترسی و هدف همکاری را تأیید می‌کنم.",
    })
    .check();
  const key = await action("/operations/partner-keys", () =>
    dialog.getByRole("button", { name: "صدور مجوز", exact: true }).click(),
  );
  secrets.push(key.api_key);
  assert(key.api_key);
  assert.deepEqual(key.scopes, ["summary:read"]);
  await dialog
    .getByRole("button", { name: "کلید را نگه داشتم؛ بستن", exact: true })
    .click();
  assert(
    (await read("/operations/partner-keys")).every(
      (row) => !("api_key" in row),
    ),
  );
  await page
    .getByRole("row")
    .filter({ hasText: "همکار آزمون " + run })
    .getByRole("button", { name: "لغو مجوز", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await action(
    `/operations/partner-keys/${key.id}`,
    () =>
      dialog
        .getByRole("button", { name: "تأیید لغو دسترسی", exact: true })
        .click(),
    "DELETE",
  );
  await dialog.waitFor({ state: "hidden" });
  passed(
    "Scoped partner key is shown once, absent from listings, and revocable",
  );
  const partnerEmail = await addMember("partner");
  const partnerContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale: "fa-IR",
    bypassCSP: true,
  });
  const partnerPage = await partnerContext.newPage();
  await signIn(partnerPage, partnerEmail);
  await partnerPage.getByRole("heading", { name: /نمای کلی/ }).waitFor();
  assert.equal(
    await partnerPage
      .getByRole("link", { name: "نوبت‌ها", exact: true })
      .count(),
    0,
  );
  assert.equal(await partnerPage.locator(".sidebar").count(), 0);
  await inspect("partner-readonly-mobile", partnerPage);
  await partnerContext.close();
  await settingsTab("تیم و همکاری");
  const partnerMember = (await read("/operations/team")).find(
    (member) => member.email === partnerEmail,
  );
  await page
    .getByRole("row")
    .filter({ hasText: partnerEmail })
    .getByRole("button", { name: "لغو دسترسی", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await action(
    `/operations/team/${partnerMember.membership_id}`,
    () =>
      dialog
        .getByRole("button", { name: "تأیید لغو دسترسی", exact: true })
        .click(),
    "DELETE",
  );
  await dialog.waitFor({ state: "hidden" });
  passed(
    "Owner grants and revokes a partner account; partner sees only aggregate mobile UI",
  );
  await settingsTab("گزارش به مدیریت");
  await page.getByRole("button", { name: "افزودن مقصد", exact: true }).click();
  dialog = page.getByRole("dialog");
  await dialog
    .getByLabel("ایمیل گیرندهٔ مجاز", { exact: true })
    .fill("synthetic-" + run + "@example.test");
  await dialog
    .getByLabel("مرجع اجازهٔ دریافت گزارش", { exact: true })
    .fill("آزمون بدون ارسال " + run);
  await dialog
    .getByRole("checkbox", { name: "این مقصد برای ارسال گزارش فعال باشد." })
    .check();
  assert.equal(
    await dialog
      .getByRole("checkbox", {
        name: "گزارش روزِ پایان‌یافته، هر روز خودکار در صف ارسال قرار گیرد.",
      })
      .isChecked(),
    false,
  );
  await dialog
    .getByRole("checkbox", {
      name: "گیرنده و اجازهٔ او برای همین گزارش و روش ارسال را بررسی کرده‌ام.",
    })
    .check();
  const destination = await action("/operations/digest-destinations", () =>
    dialog.getByRole("button", { name: "ثبت مقصد گزارش", exact: true }).click(),
  );
  await dialog.waitFor({ state: "hidden" });
  await page
    .getByRole("button", {
      name: "غیرفعال کردن مقصد آزمون بدون ارسال " + run,
      exact: true,
    })
    .click();
  dialog = page.getByRole("dialog");
  await action(
    `/operations/digest-destinations/${destination.id}`,
    () =>
      dialog
        .getByRole("button", { name: "تأیید غیرفعال‌سازی", exact: true })
        .click(),
    "DELETE",
  );
  await dialog.waitFor({ state: "hidden" });
  assert.equal(
    (await read("/operations/digest-deliveries")).filter(
      (row) => row.destination_id === destination.id,
    ).length,
    0,
  );
  passed(
    "Digest destination consent and disable work; automatic delivery remains off and no report was sent",
  );
  const clinics = await read("/clinics");
  const owned = clinics.filter(
    (item) => item.role === "owner" && item.building_id,
  );
  assert(owned.length);
  await page.goto(base + "/building", { waitUntil: "networkidle" });
  await page
    .getByRole("button", { name: "قرارداد مشترک", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  const group = owned[0].building_id;
  await dialog
    .getByLabel("مجموعهٔ مراکز هم‌ساختمان", { exact: true })
    .selectOption(group);
  for (const clinic of owned.filter((item) => item.building_id === group))
    await dialog
      .getByRole("checkbox", { name: clinic.name, exact: true })
      .check();
  await dialog
    .getByLabel("مرجع قرارداد مصوب", { exact: true })
    .fill("قرارداد نمایشی " + run);
  await dialog
    .getByLabel("دقایق مشترکِ شامل قرارداد", { exact: true })
    .fill("100");
  await dialog
    .getByLabel("هر دقیقهٔ مازاد (تومان)", { exact: true })
    .fill("1000");
  await dialog
    .getByRole("checkbox", {
      name: "اختیار مراکز عضو، مفاد و ارقام قرارداد را بررسی و تأیید کرده‌ام.",
    })
    .check();
  const contract = await action("/operations/building-contracts", () =>
    dialog
      .getByRole("button", { name: "ثبت قرارداد مشترک", exact: true })
      .click(),
  );
  await dialog.waitFor({ state: "hidden" });
  await page
    .getByRole("row")
    .filter({ hasText: "قرارداد نمایشی " + run })
    .getByRole("button", { name: "پیش‌نویس سهم", exact: true })
    .click();
  dialog = page.getByRole("dialog");
  await dialog.getByRole("table").waitFor();
  const allocation = await read(
    `/operations/building-contracts/${contract.id}/allocation?period=${dayPlus(0).slice(0, 7)}`,
  );
  assert.equal(allocation.draft, true);
  assert.equal(
    allocation.items.reduce((sum, row) => sum + row.overage_toman, 0),
    allocation.overage_toman,
  );
  await inspect("building-allocation-dialog");
  await dialog.getByRole("button", { name: "بستن", exact: true }).click();
  passed(
    "Authorized building contract yields balanced draft allocation without a charge",
  );
  await page.goto(base + "/reports", { waitUntil: "networkidle" });
  await page
    .getByRole("heading", { name: "گزارش روزانهٔ مدیریت", exact: true })
    .waitFor();
  assert((await read("/operations/digest")).definitions.open_cases);
  passed(
    "Daily digest exposes explicit current-backlog and attendance definitions",
  );
  assert.deepEqual(errors, []);
} catch (e) {
  failure = sanitize(e.message).split("Browser logs:")[0];
  console.error(sanitize(e.stack));
  process.exitCode = 1;
  if (!page.isClosed())
    await page.screenshot({
      path: output + "/extensions-failure.png",
      fullPage: true,
      mask: [page.locator('input[type="password"], textarea[readonly]')],
    });
} finally {
  await writeFile(
    output + "/extensions.json",
    JSON.stringify(
      {
        checks,
        errors: errors.map(sanitize),
        audits,
        failure,
        synthetic_data: true,
        external_messages_sent: false,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({ checks: checks.length, errors: errors.length, failure }),
  );
  await browser.close();
}
