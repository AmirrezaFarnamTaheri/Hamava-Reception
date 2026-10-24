import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdtemp, mkdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
const require = createRequire(new URL("../../../frontend/package.json", import.meta.url));
const { _electron } = require("playwright");
const desktop = fileURLToPath(new URL("../", import.meta.url));
const localRequire = createRequire(new URL("../package.json", import.meta.url));
const userData = await mkdtemp(resolve(tmpdir(), "hamava-electron-"));
const args = [desktop, `--user-data-dir=${userData}`];
if (process.env.HAMAVA_ELECTRON_TEST_NO_SANDBOX === "true") args.push("--no-sandbox");
if (process.env.HAMAVA_ELECTRON_TEST_HEADLESS === "true") args.push("--ozone-platform=headless", "--disable-gpu");
let app;
const checks = {};
try {
  app = await _electron.launch({ executablePath: localRequire("electron"), args, timeout: 60_000 });
  const page = await app.firstWindow();
  await page.waitForURL("app://hamava/**");
  await page.getByRole("heading", { name: /به مرکز خود/ }).waitFor({ timeout: 20_000 });
  checks.packaged_local_origin = page.url().startsWith("app://hamava/");
  const exposed = await page.evaluate(() => ({
    node: typeof window.require, process: typeof window.process,
    bridge: Object.keys(window.hamavaNative || {}).sort(),
  }));
  assert.equal(exposed.node, "undefined");
  assert.equal(exposed.process, "undefined");
  assert.deepEqual(exposed.bridge, ["clearSession", "getInfo", "openExternal", "readSession", "writeSession"].sort());
  checks.renderer_has_no_node_or_raw_ipc = true;
  const info = await page.evaluate(() => window.hamavaNative.getInfo());
  assert.equal(info.version, "0.2.0");
  checks.native_bridge_version = true;
  const traversal = await page.evaluate(async () => (await fetch("app://hamava/%2e%2e%2fpackage.json")).status);
  assert.equal(traversal, 404);
  checks.protocol_blocks_encoded_traversal = true;
  const unsafe = await page.evaluate(async () => {
    try { await window.hamavaNative.openExternal({ url: "file:///tmp/private" }); return false; }
    catch { return true; }
  });
  assert.equal(unsafe, true);
  checks.native_bridge_rejects_local_file_launch = true;
  const output = resolve(desktop, "../../artifacts/desktop-validation");
  await mkdir(output, { recursive: true });
  await page.screenshot({ path: resolve(output, "desktop-setup.png") });
  await writeFile(resolve(output, "launch.json"), JSON.stringify({
    passed: true, platform: process.platform, checks, native_secure_storage_available: info.secureStorage,
    process_sandbox_disabled_for_root_test: process.env.HAMAVA_ELECTRON_TEST_NO_SANDBOX === "true",
    headless_linux_test: process.env.HAMAVA_ELECTRON_TEST_HEADLESS === "true",
    limits: "Actual Electron renderer/bridge/protocol launch. Does not test Windows installation, publisher signing, real clinic login or device microphone.",
  }, null, 2) + "\n");
  console.log(JSON.stringify({ passed: true, checks }));
} finally {
  if (app) await app.close();
  await rm(userData, { recursive: true, force: true });
}
