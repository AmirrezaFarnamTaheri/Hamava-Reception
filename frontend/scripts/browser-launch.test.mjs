import assert from "node:assert/strict";
import test from "node:test";
import chromium from "@sparticuz/chromium";
import { chromiumLaunchOptions } from "./browser-launch.mjs";

const fakeChromium = {
  args: [
    "--single-process",
    "--no-sandbox",
    "--disable-web-security",
    "--disable-site-isolation-trials",
    "--allow-running-insecure-content",
    "--hide-scrollbars",
  ],
  async executablePath() {
    return "/test/chromium";
  },
};

test("the installed Chromium package exposes its supported ESM default export", () => {
  assert.ok(Array.isArray(chromium.args));
  assert.equal(typeof chromium.executablePath, "function");
});

test("unsafe flags are excluded while synthetic media flags remain opt-in", async () => {
  const options = await chromiumLaunchOptions({
    packaged: fakeChromium,
    executablePath: "",
    extraArgs: ["--use-fake-ui-for-media-stream"],
  });
  assert.equal(options.headless, true);
  assert.deepEqual(options.args, [
    "--no-sandbox",
    "--hide-scrollbars",
    "--use-fake-ui-for-media-stream",
  ]);
  assert.equal(options.executablePath, "/test/chromium");
});

test("an explicit browser binary avoids decompressing the packaged Chromium", async () => {
  const options = await chromiumLaunchOptions({
    packaged: {
      args: ["--no-sandbox"],
      executablePath() {
        throw new Error("unwanted extraction");
      },
    },
    executablePath: "/usr/bin/chromium",
  });
  assert.equal(options.executablePath, "/usr/bin/chromium");
});

test("the obsolete CommonJS namespace is rejected with an actionable error", async () => {
  await assert.rejects(
    chromiumLaunchOptions({ packaged: { default: fakeChromium } }),
    /Expected the Chromium ESM default export/,
  );
});
