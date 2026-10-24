import { chromium as playwrightChromium } from "playwright";
import chromium from "@sparticuz/chromium";

// Browser suites must not turn off web security or accidentally run in single-process mode.
const DISALLOWED_FLAGS = new Set([
  "--single-process",
  "--disable-web-security",
  "--allow-running-insecure-content",
  "--disable-site-isolation-trials",
]);

/**
 * Keep the Chromium package's ESM default export in one place. Test journeys
 * share the same launch flags, while media tests may append synthetic-device
 * options without weakening the normal browser security settings.
 */
export async function chromiumLaunchOptions({
  packaged = chromium,
  executablePath = process.env.CHROMIUM_EXECUTABLE,
  extraArgs = [],
} = {}) {
  if (!Array.isArray(packaged?.args) || typeof packaged.executablePath !== "function") {
    throw new TypeError("Expected the Chromium ESM default export (args and executablePath)");
  }
  return {
    headless: true,
    args: [
      ...packaged.args.filter((arg) => !DISALLOWED_FLAGS.has(arg)),
      ...extraArgs,
    ],
    executablePath: executablePath || (await packaged.executablePath()),
  };
}

export async function launchBrowser(options = {}) {
  return playwrightChromium.launch(await chromiumLaunchOptions(options));
}
