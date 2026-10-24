import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const packaged = require("@sparticuz/chromium");
const base = process.env.HAMAAVA_BASE_URL || "http://127.0.0.1:5173";
const output =
  process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamava-companion-preview-v2";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  headless: true,
  executablePath:
    process.env.CHROMIUM_EXECUTABLE || (await packaged.executablePath()),
  args: packaged.args.filter(
    (arg) =>
      ![
        "--single-process",
        "--disable-web-security",
        "--allow-running-insecure-content",
        "--disable-site-isolation-trials",
      ].includes(arg),
  ),
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1050 },
  locale: "fa-IR",
  reducedMotion: "reduce",
});
const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const captures = [];
async function capture(name) {
  await page.waitForTimeout(250);
  await page.screenshot({
    path: join(output, name + ".png"),
    fullPage: true,
    timeout: 120000,
  });
  captures.push({
    name,
    ...(await page.evaluate(() => ({
      width: innerWidth,
      scroll: document.documentElement.scrollWidth,
      title: document.title,
    }))),
  });
}
try {
  await page.goto(base, { waitUntil: "networkidle", timeout: 90000 });
  await page
    .getByRole("button", { name: "ورود به هم‌آوا" })
    .waitFor({ timeout: 30000 });
  await capture("login-desktop");
  await page.getByRole("button", { name: "استفاده از حساب نمایشی" }).click();
  await page.getByRole("button", { name: "ورود به هم‌آوا" }).click();
  await page
    .getByRole("heading", { name: "امروز، با خیال آسوده‌تر" })
    .waitFor({ timeout: 30000 });
  await page.waitForLoadState("networkidle");
  await capture("today-desktop");
  await page
    .getByRole("button", { name: "جست‌وجوی بخش‌ها و اقدام‌ها" })
    .click();
  await capture("command-desktop");
  await page.keyboard.press("Escape");
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await capture("today-" + width);
    await page
      .getByRole("navigation", { name: "دسترسی سریع همراه" })
      .getByRole("link", { name: "بیشتر", exact: true })
      .click();
    await page.getByRole("heading", { name: "حساب و دسترسی‌ها" }).waitFor();
    await capture("more-" + width);
    await page
      .getByRole("link", { name: "نوبت‌ها رزرو، جابه‌جایی و ثبت مراجعه" })
      .click();
    await page.getByRole("heading", { name: "نوبت‌ها", exact: true }).waitFor();
    await page.waitForLoadState("networkidle");
    await page.locator(".appointment-card").first().waitFor({ timeout: 90000 });
    await page.waitForTimeout(600);
    await capture("appointments-" + width);
    await page
      .getByRole("navigation", { name: "دسترسی سریع همراه" })
      .getByRole("link", { name: "امروز", exact: true })
      .click();
    await page
      .getByRole("heading", { name: "امروز، با خیال آسوده‌تر" })
      .waitFor();
  }
  await page.goto(base + "/connection", { waitUntil: "networkidle" });
  await capture("connection-320");
  await writeFile(
    join(output, "composition.json"),
    JSON.stringify(
      {
        captures,
        errors,
        boundary:
          "Local synthetic service in Chromium. Screenshots are an intermediate composition candidate, not release acceptance.",
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ captures, errors }));
} finally {
  await browser.close();
}
