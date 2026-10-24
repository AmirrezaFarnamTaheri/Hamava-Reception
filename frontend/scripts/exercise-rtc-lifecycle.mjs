import { createRequire } from "node:module";
import { createServer } from "node:http";
import { readFile, mkdir, writeFile } from "node:fs/promises";
import { resolve, extname, sep } from "node:path";
import { fileURLToPath } from "node:url";
import assert from "node:assert/strict";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright"),
  packaged = require("@sparticuz/chromium");
const dist = fileURLToPath(new URL("../dist/", import.meta.url));
const output =
  process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamaava-ui-validation";
const fixture = await readFile(
  new URL("./fixtures/rtc-room.mjs", import.meta.url),
  "utf8",
);
await mkdir(output, { recursive: true });
const mime = {
  ".js": "application/javascript",
  ".css": "text/css",
  ".html": "text/html",
  ".svg": "image/svg+xml",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".webmanifest": "application/manifest+json",
};
// Serves only the existing production build. No API, speech, RTC or vendor is started.
const server = createServer(async (request, response) => {
  const pathname = new URL(request.url, "http://127.0.0.1").pathname;
  const file = resolve(
    dist,
    "." + (extname(pathname) ? pathname : "/index.html"),
  );
  if (!file.startsWith(dist.endsWith(sep) ? dist : dist + sep)) {
    response.writeHead(403).end();
    return;
  }
  try {
    response.writeHead(200, {
      "Content-Type": mime[extname(file)] || "application/octet-stream",
      "Cache-Control": "no-store",
    });
    response.end(await readFile(file));
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = "http://127.0.0.1:" + server.address().port;
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
  viewport: { width: 390, height: 844 },
  locale: "fa-IR",
  reducedMotion: "reduce",
});
await context.addInitScript(() => {
  window.__rtcHarness = { rooms: [], next: {} };
});
await context.route(/\/assets\/livekit-client[^/]*\.js$/, (route) =>
  route.fulfill({ contentType: "application/javascript", body: fixture }),
);
const caps = {
  audio_input: true,
  audio_output: true,
  livekit: true,
  mode: "synthetic-event-contract",
  configured: true,
};
const clinic = {
  id: "clinic-event",
  name: "مرکز آزمایش رویداد",
  slug: "event",
  role: "owner",
  timezone: "Asia/Tehran",
  settings_version: 1,
};
const user = {
  id: "staff-event",
  name: "همکار آزمایشی",
  email: "event@example.test",
  role: "owner",
  tenant_id: clinic.id,
  tenant_name: clinic.name,
};
const unexpectedRequests = [],
  errors = [],
  checks = [],
  audits = [];
let failure, caller, staff;
await context.route("**/api/v1/**", async (route) => {
  const path = new URL(route.request().url()).pathname.slice(7);
  const method = route.request().method();
  let value;
  if (path === "/client-info")
    value = {
      product: "hamava",
      api_version: 1,
      app_version: "fixture",
      mode: "demo",
      demo_mode: true,
      native_clients: true,
    };
  else if (path === "/public/clinics/event")
    value = {
      ...clinic,
      capabilities: caps,
      notice:
        "اطلاعات ساختگی برای آزمون رویدادهای اتصال؛ این صفحه به سرویس تماس متصل نیست.",
      transcript_retention_days: 30,
      processing_notice_fingerprint: "a".repeat(64),
    };
  else if (path === "/public/clinics/event/payment-policy")
    value = { enabled: false, version: 1 };
  else if (path === "/public/sessions" && method === "POST")
    value = {
      session_id: "rtc-event-session",
      token: "fixture-only",
      greeting: "سلام؛ این یک آزمون ساختگی رویدادهای اتصال است.",
      capabilities: caps,
    };
  else if (path === "/public/sessions/rtc-event-session/livekit")
    value = {
      url: "ws://event-fixture.invalid",
      token: "fixture-only",
      room: "event-room",
    };
  else if (path === "/public/sessions/rtc-event-session/end")
    value = { status: "ENDED" };
  else if (path === "/auth/login")
    value = { access_token: "fixture-only", token_type: "bearer", user };
  else if (path === "/me") value = user;
  else if (path === "/clinics") value = [clinic];
  else if (path === "/operations/integrations")
    value = { mode: "demo", items: [] };
  else if (path === "/dashboard")
    value = {
      clinic: { ...clinic, mode: "ai_primary" },
      date: "2026-10-23",
      metrics: {
        appointments_today: 0,
        confirmed_today: 0,
        pending_tasks: 0,
        active_calls: 1,
        notifications_failed: 0,
        minutes_used: 0,
      },
      appointments: [],
      tasks: [],
      notifications: [],
      recent_activity: [],
    };
  else if (path === "/operations/calls")
    value = [
      {
        id: "event-call",
        clinic_name: clinic.name,
        channel: "browser",
        state: "HANDOFF_PENDING",
        intent: "unknown",
        started_at: "2026-10-23T12:00:00Z",
        duration_seconds: 0,
        phone_masked: "",
        handoff_status: "REQUESTED",
        policy_version: 1,
      },
    ];
  else if (path === "/operations/calls/event-call/takeover")
    value = {
      status: "ROOM_READY",
      task_id: "event-task",
      livekit: {
        url: "ws://event-fixture.invalid",
        token: "fixture-only",
        room: "event-room",
      },
    };
  else {
    unexpectedRequests.push({ path, method });
    await route.fulfill({
      status: 500,
      json: { detail: { message: "Unexpected contract request" } },
    });
    return;
  }
  await route.fulfill({ json: value });
});
function passed(name) {
  checks.push(name);
  console.log(JSON.stringify({ passed: name }));
}
async function makePage() {
  const page = await context.newPage();
  page.on("pageerror", (error) => errors.push(error.message));
  return page;
}
async function transition(page, index, state, mode = "both") {
  await page.evaluate(
    ({ index, state, mode }) =>
      window.__rtcHarness.rooms[index].transition(state, mode),
    { index, state, mode },
  );
}
async function micPending(page, index) {
  await page.waitForFunction(
    (index) => window.__rtcHarness.rooms[index]?.pendingMic,
    index,
  );
}
async function releaseMic(page, index) {
  await page.evaluate(
    (index) => window.__rtcHarness.rooms[index].releaseMic(),
    index,
  );
  await page.waitForFunction(
    (index) => !window.__rtcHarness.rooms[index].pendingMic,
    index,
  );
}
async function configure(page, next) {
  await page.evaluate((next) => {
    window.__rtcHarness.next = next;
  }, next);
}
async function roomCount(page) {
  return page.evaluate(() => window.__rtcHarness.rooms.length);
}
async function join(page, staffMode = false, next = {}) {
  await configure(page, next);
  const index = await roomCount(page);
  await page
    .getByRole("button", {
      name: staffMode ? "شروع اتصال با میکروفون" : "شروع تماس زنده",
      exact: true,
    })
    .click();
  await page.waitForFunction(
    (count) => window.__rtcHarness.rooms.length === count + 1,
    index,
  );
  if (next.deferMic) await micPending(page, index);
  else if (!next.failConnect) await connected(page, staffMode);
  return index;
}
async function connected(page, staffMode = false) {
  await page
    .getByText(staffMode ? "به اتاق تماس متصل شدید" : "تماس زنده برقرار است", {
      exact: true,
    })
    .waitFor();
}
async function recovering(page, staffMode = false) {
  await page
    .getByText(
      staffMode
        ? "در حال برقراری دوبارهٔ ارتباط…"
        : "در حال برقراری دوبارهٔ تماس…",
      { exact: true },
    )
    .waitFor();
  assert.equal(
    await page
      .getByText(
        staffMode ? "به اتاق تماس متصل شدید" : "تماس زنده برقرار است",
        { exact: true },
      )
      .count(),
    0,
  );
  const scope = staffMode
    ? page.getByRole("dialog")
    : page.locator(".live-voice-controls");
  assert(
    await scope
      .getByRole("button", { name: /بی‌صدا کردن|فعال‌کردن/ })
      .isDisabled(),
  );
  assert(
    await scope
      .getByRole("button", {
        name: staffMode ? "خروج" : "ادامه با نوشتن",
        exact: true,
      })
      .isEnabled(),
  );
  if (!staffMode) {
    assert(
      await page
        .getByRole("textbox", { name: "پیام شما", exact: true })
        .isDisabled(),
    );
    assert(
      await page
        .getByRole("button", { name: "ضبط پیام صوتی", exact: true })
        .isDisabled(),
    );
    assert.equal(
      await page
        .getByRole("button", { name: "شروع تماس زنده", exact: true })
        .count(),
      0,
    );
  }
}
async function audit(page, label) {
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
  assert.equal(result.findings.length, 0, label + " axe findings");
  assert(result.width <= result.viewport, label + " overflow");
}
try {
  caller = await makePage();
  await caller.goto(base + "/talk/event", { waitUntil: "networkidle" });
  await caller.getByRole("checkbox").check();
  await caller.getByRole("button", { name: "شروع گفتگو", exact: true }).click();
  await caller
    .getByRole("button", { name: "شروع تماس زنده", exact: true })
    .waitFor();
  let index = await join(caller, false, { deferMic: true });
  await caller.getByText("در حال برقراری تماس…", { exact: true }).waitFor();
  assert.equal(
    await caller.getByText("تماس زنده برقرار است", { exact: true }).count(),
    0,
  );
  await transition(caller, index, "reconnecting");
  await recovering(caller);
  await releaseMic(caller, index);
  await recovering(caller);
  passed(
    "Caller stays connecting until microphone readiness; recovery during that await remains visibly reconnecting",
  );
  await transition(caller, index, "connected");
  await connected(caller);
  await caller
    .getByRole("button", { name: "بی‌صدا کردن", exact: true })
    .click();
  await caller
    .getByRole("button", { name: "فعال‌کردن صدا", exact: true })
    .waitFor();
  const callerMicChanges = await caller.evaluate(
    (index) => window.__rtcHarness.rooms[index].micChanges.length,
    index,
  );
  await transition(caller, index, "reconnecting", "named");
  await recovering(caller);
  await audit(caller, "Caller media recovery at 390px");
  await transition(caller, index, "connected", "named");
  await connected(caller);
  assert(
    await caller
      .getByRole("button", { name: "فعال‌کردن صدا", exact: true })
      .isEnabled(),
  );
  assert.equal(
    await caller.evaluate(
      (index) => window.__rtcHarness.rooms[index].micChanges.length,
      index,
    ),
    callerMicChanges,
  );
  passed(
    "Caller named media reconnect/reconnected events disable unsafe controls, retain exit and preserve mute without enabling the microphone again",
  );
  for (const mode of ["state", "named"]) {
    await transition(caller, index, "signalReconnecting", mode);
    await recovering(caller);
    await transition(caller, index, "connected", mode);
    await connected(caller);
  }
  passed(
    "Caller signaling recovery and restoration respond to both state-change and named SDK events",
  );
  await transition(caller, index, "disconnected", "state");
  await caller.getByText("تماس زنده قطع شده است", { exact: true }).waitFor();
  assert(
    await caller
      .getByRole("textbox", { name: "پیام شما", exact: true })
      .isEnabled(),
  );
  assert(
    await caller
      .getByRole("button", { name: "شروع تماس زنده", exact: true })
      .isEnabled(),
  );
  passed(
    "Caller terminal disconnect removes the connected claim and restores typed fallback and explicit rejoin",
  );
  index = await join(caller, false, { deferMic: true });
  await caller
    .getByRole("button", { name: "ادامه با نوشتن", exact: true })
    .click();
  await releaseMic(caller, index);
  await caller.waitForFunction(
    (index) =>
      window.__rtcHarness.rooms[index].disconnects >= 2 &&
      !window.__rtcHarness.rooms[index].localParticipant.isMicrophoneEnabled,
    index,
  );
  const freshCaller = await join(caller);
  await caller.evaluate((index) => {
    const old = window.__rtcHarness.rooms[index];
    old.transition("connected");
    old.transition("disconnected");
    old.emitRetiredDataAndTrack();
  }, index);
  await connected(caller);
  assert.equal(
    await caller.getByText("پیام اتاق بازنشسته", { exact: true }).count(),
    0,
  );
  assert.equal(await caller.locator("[data-retired-room]").count(), 0);
  await caller.evaluate((index) => {
    window.__rtcHarness.rooms[index].deferMic = true;
  }, freshCaller);
  await caller
    .getByRole("button", { name: "بی‌صدا کردن", exact: true })
    .click();
  await micPending(caller, freshCaller);
  await transition(caller, freshCaller, "reconnecting");
  await recovering(caller);
  await caller
    .getByRole("button", { name: "ادامه با نوشتن", exact: true })
    .click();
  const replacementCaller = await join(caller);
  assert(
    await caller
      .getByRole("button", { name: "بی‌صدا کردن", exact: true })
      .isEnabled(),
  );
  await releaseMic(caller, freshCaller);
  await connected(caller);
  assert.equal(
    await caller.evaluate(
      (index) => window.__rtcHarness.rooms[index].disconnects,
      replacementCaller,
    ),
    0,
  );
  passed(
    "Caller exits invalidate pending microphone work and stale data/track/status callbacks; replacement room controls do not inherit retired busy state",
  );
  await caller
    .getByRole("button", { name: "ادامه با نوشتن", exact: true })
    .click();
  await join(caller, false, { failConnect: true });
  await caller
    .getByRole("alert")
    .filter({ hasText: "تماس زنده برقرار نشد" })
    .waitFor();
  assert(
    await caller
      .getByRole("textbox", { name: "پیام شما", exact: true })
      .isEnabled(),
  );
  await caller.getByRole("button", { name: "پایان", exact: true }).click();
  passed(
    "Caller failure alert survives SDK disconnect-before-rejection ordering and the session remains endable",
  );

  staff = await makePage();
  await staff.setViewportSize({ width: 1440, height: 1000 });
  await staff.goto(base + "/", { waitUntil: "networkidle" });
  await staff
    .getByRole("button", { name: "استفاده از حساب نمایشی", exact: true })
    .click();
  await staff
    .getByRole("button", { name: "ورود به هم‌آوا", exact: true })
    .click();
  await staff
    .getByRole("button", { name: "همراهی و پیگیری", exact: true })
    .click();
  index = await join(staff, true, { deferMic: true });
  await staff.getByText("در حال برقراری ارتباط…", { exact: true }).waitFor();
  assert.equal(
    await staff.getByText("به اتاق تماس متصل شدید", { exact: true }).count(),
    0,
  );
  await transition(staff, index, "reconnecting");
  await recovering(staff, true);
  await releaseMic(staff, index);
  await recovering(staff, true);
  passed(
    "Staff setup and recovery remain accurate when the initial microphone operation is delayed",
  );
  await transition(staff, index, "connected");
  await connected(staff, true);
  await staff.getByRole("button", { name: "بی‌صدا کردن", exact: true }).click();
  await staff
    .getByRole("button", { name: "فعال‌کردن میکروفون", exact: true })
    .waitFor();
  const staffMicChanges = await staff.evaluate(
    (index) => window.__rtcHarness.rooms[index].micChanges.length,
    index,
  );
  await transition(staff, index, "reconnecting", "named");
  await recovering(staff, true);
  await audit(staff, "Staff media recovery dialog");
  await transition(staff, index, "connected", "named");
  await connected(staff, true);
  assert(
    await staff
      .getByRole("button", { name: "فعال‌کردن میکروفون", exact: true })
      .isEnabled(),
  );
  assert.equal(
    await staff.evaluate(
      (index) => window.__rtcHarness.rooms[index].micChanges.length,
      index,
    ),
    staffMicChanges,
  );
  passed(
    "Staff media recovery disables mic changes, preserves exit and restores the existing muted state",
  );
  for (const mode of ["state", "named"]) {
    await transition(staff, index, "signalReconnecting", mode);
    await recovering(staff, true);
    await transition(staff, index, "connected", mode);
    await connected(staff, true);
  }
  passed(
    "Staff signaling recovery handles both named events and ConnectionStateChanged",
  );
  await transition(staff, index, "disconnected", "named");
  await staff.getByText("ارتباط پایان یافت", { exact: true }).waitFor();
  const freshStaff = await join(staff, true);
  assert(
    await staff
      .getByRole("button", { name: "بی‌صدا کردن", exact: true })
      .isEnabled(),
  );
  await staff.evaluate((index) => {
    window.__rtcHarness.rooms[index].transition("disconnected");
    window.__rtcHarness.rooms[index].emitRetiredDataAndTrack();
  }, index);
  await connected(staff, true);
  assert.equal(await staff.locator("[data-retired-room]").count(), 0);
  passed(
    "Staff terminal disconnect permits explicit rejoin; fresh mute state and room ownership ignore retired callbacks",
  );
  await staff.evaluate((index) => {
    window.__rtcHarness.rooms[index].deferMic = true;
  }, freshStaff);
  await staff.getByRole("button", { name: "بی‌صدا کردن", exact: true }).click();
  await micPending(staff, freshStaff);
  await transition(staff, freshStaff, "reconnecting");
  await recovering(staff, true);
  await staff.getByRole("button", { name: "خروج", exact: true }).click();
  await staff.getByRole("dialog").waitFor({ state: "hidden" });
  await staff
    .getByRole("button", { name: "همراهی و پیگیری", exact: true })
    .click();
  const replacementStaff = await join(staff, true);
  assert(
    await staff
      .getByRole("button", { name: "بی‌صدا کردن", exact: true })
      .isEnabled(),
  );
  await releaseMic(staff, freshStaff);
  await staff.evaluate(
    (index) => window.__rtcHarness.rooms[index].transition("connected"),
    freshStaff,
  );
  await connected(staff, true);
  assert.equal(
    await staff.evaluate(
      (index) => window.__rtcHarness.rooms[index].disconnects,
      replacementStaff,
    ),
    0,
  );
  await staff.getByRole("button", { name: "خروج", exact: true }).click();
  await staff
    .getByRole("button", { name: "همراهی و پیگیری", exact: true })
    .click();
  const pendingStaff = await join(staff, true, { deferMic: true });
  await staff.getByRole("button", { name: "خروج", exact: true }).click();
  await releaseMic(staff, pendingStaff);
  await staff.waitForFunction(
    (index) =>
      window.__rtcHarness.rooms[index].disconnects >= 2 &&
      !window.__rtcHarness.rooms[index].localParticipant.isMicrophoneEnabled,
    pendingStaff,
  );
  assert.equal(await staff.getByRole("dialog").count(), 0);
  passed(
    "Staff exit remains effective during recovery or pending microphone setup; retired operations cannot disable or disconnect a replacement room",
  );
  await staff
    .getByRole("button", { name: "همراهی و پیگیری", exact: true })
    .click();
  await join(staff, true, { failConnect: true });
  await staff
    .getByRole("alert")
    .filter({ hasText: "اتصال صوتی برقرار نشد" })
    .waitFor();
  await audit(staff, "Staff recoverable connection failure dialog");
  await staff.getByRole("button", { name: "خروج", exact: true }).click();
  assert.deepEqual(errors, []);
  assert.deepEqual(unexpectedRequests, []);
  passed(
    "Staff failure alert survives SDK terminal-event ordering; all event-contract checks have no runtime errors or unexpected API requests",
  );
} catch (error) {
  failure = error.message;
  console.error(error.stack);
  process.exitCode = 1;
} finally {
  await writeFile(
    output + "/rtc-lifecycle.json",
    JSON.stringify(
      {
        checks,
        errors,
        audits,
        unexpectedRequests,
        failure,
        verification_kind: "browser_component_event_contract",
        validation_environment:
          "Actual production frontend build in local Chromium; explicit API fixtures and LiveKit Room event double; no live API or RTC services",
        qualification:
          "Verifies caller/staff event-to-UI wiring, current-room ownership and deferred-operation cleanup. No actual network reconnect, media continuity, physical mobile background/lock, carrier or production qualification. Existing real-transport evidence remains separate; full MEDIA-008 reconnect acceptance remains partial.",
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
      report: output + "/rtc-lifecycle.json",
    }),
  );
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
}
