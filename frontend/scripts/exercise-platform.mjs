import { launchBrowser } from "./browser-launch.mjs";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import assert from "node:assert/strict";
const base = process.env.HAMAAVA_BASE_URL || "http://127.0.0.1:8000";
const output =
  process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamava-platform-validation";
await mkdir(output, { recursive: true });
const browser = await launchBrowser();
const checks = [],
  errors = [];
let vault = null;
let failClear = false;
const context = await browser.newContext({
  viewport: { width: 1280, height: 900 },
  locale: "fa-IR",
});
await context.exposeBinding("testNativeVault", async (_, method, options) => {
  if (method === "info") return { version: "0.2.0", secureStorage: true };
  if (method === "read")
    return { token: vault?.server === options.server ? vault.token : null };
  if (method === "write") {
    vault = options;
    return;
  }
  if (method === "clear") {
    if (failClear) throw new Error("Synthetic vault unavailable");
    vault = null;
    return;
  }
  throw new Error("Unsupported fixture method");
});
await context.addInitScript(() => {
  window.hamavaNative = {
    getInfo: () => window.testNativeVault("info"),
    readSession: (options) => window.testNativeVault("read", options),
    writeSession: (options) => window.testNativeVault("write", options),
    clearSession: () => window.testNativeVault("clear"),
    openExternal: async () => {
      throw new Error("External navigation not used in this fixture");
    },
  };
});
const page = await context.newPage();
page.on("pageerror", (error) => errors.push(error.message));
let externalRequest = false;
await context.route("**/untrusted.example/**", (route) => {
  externalRequest = true;
  return route.abort();
});
async function login() {
  await page
    .getByRole("button", { name: "استفاده از حساب نمایشی", exact: true })
    .click();
  await page
    .getByRole("button", { name: "ورود به هم‌آوا", exact: true })
    .click();
  await page
    .getByRole("heading", { name: "امروز، با خیال آسوده‌تر", exact: true })
    .waitFor();
}
try {
  await page.goto(base, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /به مرکز خود/ }).waitFor();
  checks.push("native-first-launch-requires-clinic-connection");
  await page
    .getByLabel("نشانی سامانه", { exact: true })
    .fill("http://untrusted.example/");
  await page.getByRole("button", { name: "بررسی اتصال", exact: true }).click();
  await page.getByRole("alert").waitFor();
  assert.equal(externalRequest, false);
  checks.push("insecure-remote-origin-rejected-before-network");
  await page.getByLabel("نشانی سامانه", { exact: true }).fill(base);
  const request = page.waitForRequest(
    (request) => request.url() === base + "/api/v1/client-info",
  );
  await page.getByRole("button", { name: "بررسی اتصال", exact: true }).click();
  assert.equal((await request).headers().authorization, undefined);
  await page
    .getByText("سامانهٔ هم‌آوا در دسترس است", { exact: true })
    .waitFor();
  checks.push("server-handshake-does-not-send-staff-credentials");
  await page
    .getByRole("button", { name: "اتصال و ادامهٔ ورود", exact: true })
    .click();
  await login();
  assert.equal(vault.server, base);
  assert.ok(vault.token?.length > 32);
  const retainedToken = vault.token;
  const leaked = await page.evaluate(
    (token) => ({
      session: Object.values(sessionStorage).some((value) =>
        value.includes(token),
      ),
      local: Object.values(localStorage).some((value) => value.includes(token)),
    }),
    retainedToken,
  );
  assert.deepEqual(leaked, { session: false, local: false });
  checks.push("native-session-persisted-only-through-vault-interface");
  await page.reload({ waitUntil: "networkidle" });
  await page
    .getByRole("heading", { name: "امروز، با خیال آسوده‌تر", exact: true })
    .waitFor();
  checks.push("server-bound-native-session-restores-after-reload");
  await context.route("**/api/v1/me", (route) => route.abort("failed"));
  await page.reload({ waitUntil: "networkidle" });
  await page
    .getByRole("heading", { name: "ارتباط با مرکز برقرار نشد", exact: true })
    .waitFor();
  assert.equal(vault.token, retainedToken);
  checks.push("temporary-network-error-preserves-valid-vault-session");
  await context.unroute("**/api/v1/me");
  await page.getByRole("button", { name: "تلاش دوباره", exact: true }).click();
  await page
    .getByRole("heading", { name: "امروز، با خیال آسوده‌تر", exact: true })
    .waitFor();
  checks.push("session-recovery-retries-without-new-login");
  await page
    .getByRole("button", { name: /خروج از حساب/ })
    .first()
    .click();
  await page
    .getByRole("heading", { name: "ورود به فضای پذیرش", exact: true })
    .waitFor();
  assert.equal(vault, null);
  const revoked = await fetch(base + "/api/v1/me", {
    headers: { Authorization: `Bearer ${retainedToken}` },
  });
  assert.equal(revoked.status, 401);
  checks.push("sign-out-clears-vault-and-revokes-the-server-session");
  await login();
  const offlineToken = vault.token;
  failClear = true;
  await context.route("**/api/v1/auth/logout", (route) =>
    route.abort("failed"),
  );
  await page
    .getByRole("button", { name: /خروج از حساب/ })
    .first()
    .click();
  await page
    .getByRole("heading", { name: "ورود به فضای پذیرش", exact: true })
    .waitFor();
  assert.equal(vault.token, offlineToken);
  const stillValid = await fetch(base + "/api/v1/me", {
    headers: { Authorization: `Bearer ${offlineToken}` },
  });
  assert.equal(stillValid.status, 200);
  await page.reload({ waitUntil: "networkidle" });
  await page
    .getByRole("heading", { name: "ورود به فضای پذیرش", exact: true })
    .waitFor();
  checks.push(
    "offline-logout-cannot-restore-a-vault-record-even-when-deletion-fails",
  );
  failClear = false;
  await context.unroute("**/api/v1/auth/logout");
  await page.evaluate(() =>
    localStorage.setItem(
      "hamava.server.v1",
      "https://user:pass@invalid.example/",
    ),
  );
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("heading", { name: /به مرکز خود/ }).waitFor();
  checks.push("tampered-server-profile-fails-back-to-setup");
  assert.deepEqual(errors, []);
  await writeFile(
    join(output, "platform-contract.json"),
    JSON.stringify(
      {
        passed: true,
        checks,
        runtime_errors: errors,
        evidence:
          "Actual bundled UI and synthetic local API; native bridge is a controlled fixture.",
        limits:
          "Does not claim OS-vault encryption, Android installation, physical microphone or production-server validation.",
      },
      null,
      2,
    ) + "\n",
  );
  console.log(JSON.stringify({ passed: true, checks }));
} finally {
  await browser.close();
}
