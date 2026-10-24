import { launchBrowser } from "./browser-launch.mjs";
import { access, mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
const base = process.env.HAMAAVA_BASE_URL || "http://127.0.0.1:8000",
  source = process.env.HAMAAVA_TEST_AUDIO || "/tmp/hamava-synthetic-speech.wav",
  output = process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamaava-ui-validation";
await access(source);
await mkdir(output, { recursive: true });
const browser = await launchBrowser({
  extraArgs: [
    "--use-fake-ui-for-media-stream",
    "--use-fake-device-for-media-stream",
    `--use-file-for-fake-audio-capture=${source}`,
  ],
});
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  locale: "fa-IR",
  reducedMotion: "reduce",
  permissions: ["microphone"],
});
const page = await context.newPage();
const checks = [],
  errors = [];
let session, failure, transcript;
page.on("pageerror", (e) => errors.push(e.message));
function passed(name) {
  checks.push(name);
  console.log(JSON.stringify({ passed: name }));
}
await page.addInitScript(() => {
  window.__testStreams = [];
  const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  navigator.mediaDevices.getUserMedia = async (constraints) => {
    const stream = await real(constraints);
    window.__testStreams.push(stream);
    return stream;
  };
});
try {
  const auth = await context.request.post(base + "/api/v1/auth/login", {
    data: { email: "owner@example.test", password: "DemoReception2026!" },
  });
  assert(auth.ok());
  const { access_token } = await auth.json();
  assert.equal(
    (
      await (
        await context.request.get(base + "/api/v1/operations/integrations", {
          headers: { Authorization: "Bearer " + access_token },
        })
      ).json()
    ).mode,
    "demo",
  );
  await page.goto(base + "/talk/bahar", { waitUntil: "networkidle" });
  await page.getByRole("checkbox").check();
  const [response] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().endsWith("/public/sessions") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "شروع گفتگو", exact: true }).click(),
  ]);
  session = await response.json();
  assert.equal(
    session.capabilities.livekit,
    true,
    "Optional check needs approved live local server, worker and speech processor",
  );
  assert.equal(await page.evaluate(() => window.__testStreams.length), 0);
  passed(
    "Live capability is authoritative and no microphone starts before explicit call action",
  );
  const [admission] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/livekit") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "شروع تماس زنده", exact: true }).click(),
  ]);
  assert(admission.ok());
  await page
    .getByRole("button", { name: "بی‌صدا کردن", exact: true })
    .waitFor({ timeout: 60000 });
  assert(await page.getByRole("textbox").isDisabled());
  assert(
    await page.evaluate(() =>
      window.__testStreams.some((stream) =>
        stream.getAudioTracks().some((track) => track.readyState === "live"),
      ),
    ),
  );
  passed(
    "Real LiveKit JavaScript client connects and publishes the explicitly requested microphone",
  );
  await page.locator(".chat-message.user").first().waitFor({ timeout: 90000 });
  transcript = await page
    .locator(".chat-message.user .chat-bubble p")
    .first()
    .innerText();
  assert(transcript.trim());
  passed(
    "Trusted live agent data renders an actual synthetic speech transcript",
  );
  await page.getByRole("button", { name: "بی‌صدا کردن", exact: true }).click();
  await page
    .getByRole("button", { name: "فعال‌کردن صدا", exact: true })
    .waitFor();
  passed("Caller can mute the live microphone");
  await page
    .getByRole("button", { name: "ادامه با نوشتن", exact: true })
    .click();
  await page
    .getByRole("button", { name: "شروع تماس زنده", exact: true })
    .waitFor();
  assert.equal(await page.getByRole("textbox").isDisabled(), false);
  await page.waitForFunction(() =>
    window.__testStreams.every((stream) =>
      stream.getTracks().every((track) => track.readyState === "ended"),
    ),
  );
  passed(
    "Disconnect releases microphone tracks and returns to the typed fallback",
  );
  await page.getByRole("button", { name: "پایان", exact: true }).click();
  await page
    .getByText("گفتگو پایان یافت. ممنون که با ما همراه بودید.", { exact: true })
    .waitFor();
  assert.deepEqual(errors, []);
  passed("Live browser conversation ends cleanly");
} catch (e) {
  failure = e.message.split("Browser logs:")[0];
  console.error(failure);
  process.exitCode = 1;
  if (!page.isClosed())
    await page.screenshot({
      path: output + "/live-ui-failure.png",
      fullPage: true,
    });
} finally {
  if (session)
    await context.request
      .post(base + "/api/v1/public/sessions/" + session.session_id + "/end", {
        headers: { Authorization: "Bearer " + session.token },
        data: {},
      })
      .catch(() => {});
  await writeFile(
    output + "/live-ui.json",
    JSON.stringify(
      {
        checks,
        errors,
        failure,
        synthetic_input: true,
        transcript,
        accuracy_claim:
          "Live transport and trusted data rendering only; no speech-recognition accuracy claim.",
      },
      null,
      2,
    ),
  );
  console.log(JSON.stringify({ checks: checks.length, errors, failure }));
  await browser.close();
}
