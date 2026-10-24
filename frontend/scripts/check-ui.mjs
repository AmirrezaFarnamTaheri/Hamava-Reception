import { launchBrowser } from "./browser-launch.mjs";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import assert from "node:assert/strict";
const require = createRequire(import.meta.url);
const base = process.env.HAMAAVA_BASE_URL || "http://127.0.0.1:8000";
const output =
  process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamaava-ui-validation";
await mkdir(output, { recursive: true });
const browser = await launchBrowser();
// Disable CSP only in this audit context so axe can inject its checker; app CSP stays intact.
const context = await browser.newContext({
  bypassCSP: true,
  viewport: { width: 1440, height: 1000 },
  locale: "fa-IR",
  reducedMotion: "reduce",
});
const page = await context.newPage();
page.setDefaultTimeout(60000);
const errors = [];
const failedResponses = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("response", (response) => {
  if (response.status() >= 400 && response.url().includes("/api/v1/"))
    failedResponses.push({
      url: new URL(response.url()).pathname,
      status: response.status(),
    });
});
const results = [];
async function inspect(name, screenshot = false) {
  await page.waitForTimeout(350);
  await page.addScriptTag({ path: require.resolve("axe-core/axe.min.js") });
  const audit = await page.evaluate(async () => {
    const report = await window.axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21aa"] },
    });
    return report.violations.map((v) => ({
      id: v.id,
      impact: v.impact,
      help: v.help,
      nodes: v.nodes.map((n) => ({ html: n.html, failure: n.failureSummary })),
    }));
  });
  const layout = await page.evaluate(() => ({
    viewport: window.innerWidth,
    scroll: document.documentElement.scrollWidth,
    direction: document.documentElement.dir,
    title: document.title,
  }));
  results.push({ name, layout, audit });
  if (screenshot)
    await page.screenshot({
      path: join(output, name + ".png"),
      fullPage: true,
      timeout: 120000,
    });
  console.log(
    JSON.stringify({
      name,
      overflow: layout.scroll > layout.viewport,
      violations: audit.map((v) => ({
        id: v.id,
        impact: v.impact,
        count: v.nodes.length,
      })),
    }),
  );
}
try {
  await page.goto(base + "/", { waitUntil: "networkidle" });
  await page
    .getByRole("button", { name: "استفاده از حساب نمایشی", exact: true })
    .click();
  await inspect("login-desktop", true);
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
  await page.waitForLoadState("networkidle");
  await inspect("dashboard-desktop", true);
  await context.setOffline(true);
  await page.getByText("اتصال شبکه قطع است.", { exact: false }).waitFor();
  await inspect("offline-notice");
  await context.setOffline(false);
  await page.locator(".network-status").waitFor({ state: "hidden" });
  await page.waitForLoadState("networkidle");
  for (const [route, name] of [
    ["/appointments", "appointments"],
    ["/tasks", "tasks"],
    ["/notifications", "notifications"],
    ["/capacity", "capacity"],
    ["/reports", "reports"],
    ["/building", "building"],
    ["/settings", "settings"],
  ]) {
    await page.goto(base + route, { waitUntil: "networkidle" });
    await page.getByRole("main").waitFor();
    await inspect(
      name,
      ["appointments", "tasks", "capacity", "reports"].includes(name),
    );
    if (route === "/capacity") {
      for (const label of [
        "تغییر برنامه",
        "پس از مراجعه",
        "بیعانه و بازپرداخت",
        "صورت‌حساب",
      ]) {
        await page.getByRole("button", { name: label, exact: true }).click();
        await page.waitForLoadState("networkidle");
        await inspect(
          "capacity-" +
            {
              صورت‌حساب: "billing",
              "تغییر برنامه": "disruptions",
              "پس از مراجعه": "followups",
              "بیعانه و بازپرداخت": "payments",
            }[label],
        );
      }
    }
    if (route === "/settings") {
      const tabs = await page.getByRole("tab").all();
      for (let i = 1; i < tabs.length; i++) {
        await tabs[i].click();
        await page.waitForLoadState("networkidle");
        await inspect("settings-tab-" + i, i === 2);
      }
    }
  }
  await page.goto(base + "/talk/bahar", { waitUntil: "networkidle" });
  await inspect("talk-consent", true);
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: /شروع گفتگو/ }).click();
  await page.getByRole("textbox").waitFor();
  await inspect("talk-active", true);
  await page.getByRole("textbox").fill("آدرس مرکز کجاست؟");
  await Promise.all([
    page.waitForResponse(
      (response) =>
        response.url().endsWith("/turn") &&
        response.request().method() === "POST",
    ),
    page.getByRole("button", { name: "ارسال پیام", exact: true }).click(),
  ]);
  await inspect("talk-reply", true);
  await page.getByRole("button", { name: "پایان", exact: true }).click();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    for (const [route, name] of [
      ["/", "dashboard"],
      ["/appointments", "appointments"],
      ["/capacity", "capacity"],
      ["/settings", "settings"],
      ["/talk/bahar", "talk"],
    ]) {
      await page.goto(base + route, { waitUntil: "networkidle" });
      await inspect(name + "-mobile-" + width, width === 390);
      if (route === "/" && width === 390) {
        await page
          .getByRole("button", { name: "باز کردن فهرست", exact: true })
          .click();
        await page
          .getByRole("dialog", { name: "فهرست اصلی", exact: true })
          .waitFor();
        await page.keyboard.press("Shift+Tab");
        assert.equal(
          await page.evaluate(() =>
            document.activeElement?.getAttribute("aria-label"),
          ),
          "خروج از حساب",
        );
        await page.keyboard.press("Tab");
        assert.equal(
          await page.evaluate(() =>
            document.activeElement?.getAttribute("aria-label"),
          ),
          "بستن فهرست",
        );
        await inspect("mobile-navigation-keyboard");
        await page.keyboard.press("Escape");
        await page
          .getByRole("dialog", { name: "فهرست اصلی", exact: true })
          .waitFor({ state: "hidden" });
        assert.equal(
          await page.evaluate(() =>
            document.activeElement?.getAttribute("aria-label"),
          ),
          "باز کردن فهرست",
        );
      }
      if (route === "/settings") {
        for (const label of ["شرایط مالی", "آمادگی راه‌اندازی"]) {
          await page
            .locator(".settings-mobile-chooser select")
            .selectOption({ label });
          await page.waitForLoadState("networkidle");
          await inspect(
            (label === "شرایط مالی" ? "payment-policy" : "launch-readiness") +
              "-mobile-" +
              width,
          );
        }
      }
    }
  }
} finally {
  await writeFile(
    join(output, "audit.json"),
    JSON.stringify({ results, errors, failedResponses }, null, 2),
  );
  console.log(
    JSON.stringify({
      errors,
      failedResponses,
      report: join(output, "audit.json"),
    }),
  );
  if (
    errors.length ||
    failedResponses.length ||
    results.some(
      (result) =>
        result.audit.length || result.layout.scroll > result.layout.viewport,
    )
  )
    process.exitCode = 1;
  await browser.close();
}
