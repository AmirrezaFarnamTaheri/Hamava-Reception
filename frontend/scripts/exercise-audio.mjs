import { launchBrowser } from "./browser-launch.mjs";
import { access, mkdir, writeFile } from "node:fs/promises";
import assert from "node:assert/strict";
const base = process.env.HAMAAVA_BASE_URL || "http://127.0.0.1:8000";
const source =
  process.env.HAMAAVA_TEST_AUDIO || "/tmp/hamava-synthetic-speech.wav";
const output =
  process.env.HAMAAVA_ARTIFACTS_DIR || "/tmp/hamaava-ui-validation";
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
  permissions: ["microphone"],
  locale: "fa-IR",
  reducedMotion: "reduce",
});
const page = await context.newPage();
const checks = [];
const errors = [];
let session;
let result;
let synthesis;
let failure;
function passed(name) {
  checks.push(name);
  console.log(JSON.stringify({ passed: name }));
}
page.on("pageerror", (e) => errors.push(e.message));
await page.addInitScript(() => {
  window.__testStreams = [];
  window.__speechEvidence = [];
  const realFetch = window.fetch.bind(window);
  window.fetch = async function (...args) {
    const response = await realFetch(...args);
    if (String(args[0]).includes("/speech?turn_id=")) {
      const copy = response.clone();
      copy
        .arrayBuffer()
        .then((buffer) =>
          window.__speechEvidence.push({
            status: response.status,
            content_type: response.headers.get("content-type"),
            content_length: response.headers.get("content-length"),
            byte_length: buffer.byteLength,
            signature: Array.from(new Uint8Array(buffer).slice(0, 4)),
          }),
        )
        .catch((error) =>
          window.__speechEvidence.push({ error: error.message }),
        );
    }
    return response;
  };
  const capture = navigator.mediaDevices?.getUserMedia.bind(
    navigator.mediaDevices,
  );
  if (capture)
    navigator.mediaDevices.getUserMedia = async function (constraints) {
      const stream = await capture(constraints);
      window.__testStreams.push(stream);
      return stream;
    };
});
try {
  const authResult = await context.request.post(base + "/api/v1/auth/login", {
    data: { email: "owner@example.test", password: "DemoReception2026!" },
  });
  assert(authResult.ok());
  const auth = await authResult.json();
  const mode = await context.request.get(
    base + "/api/v1/operations/integrations",
    { headers: { Authorization: "Bearer " + auth.access_token } },
  );
  assert.equal((await mode.json()).mode, "demo");
  await page.goto(base + "/talk/bahar", { waitUntil: "networkidle" });
  await page.getByRole("checkbox").check();
  const [start] = await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().endsWith("/public/sessions") && r.request().method() === "POST",
    ),
    page.getByRole("button", { name: "شروع گفتگو", exact: true }).click(),
  ]);
  session = await start.json();
  assert(start.ok());
  assert.equal(
    session.capabilities.audio_input,
    true,
    "This optional check requires a provisioned local speech processor",
  );
  assert.equal(session.capabilities.audio_output, true);
  assert.equal(await page.evaluate(() => window.__testStreams.length), 0);
  passed("No microphone stream exists before explicit record action");
  await page
    .getByRole("button", { name: "ضبط پیام صوتی", exact: true })
    .click();
  await page
    .getByRole("button", { name: "پایان ضبط و ارسال", exact: true })
    .waitFor();
  await page.waitForTimeout(4100);
  const speech = page.waitForResponse(
    (r) =>
      r.url().includes("/speech?turn_id=") && r.request().method() === "GET",
    { timeout: 90000 },
  );
  const [audio] = await Promise.all([
    page.waitForResponse(
      (r) => r.url().endsWith("/audio") && r.request().method() === "POST",
      { timeout: 90000 },
    ),
    page
      .getByRole("button", { name: "پایان ضبط و ارسال", exact: true })
      .click(),
  ]);
  result = await audio.json();
  assert(audio.ok(), JSON.stringify(result));
  assert.equal(typeof result.transcript, "string");
  assert(result.transcript.trim());
  assert(result.turn_id && result.reply);
  assert(audio.request().headers()["content-type"].startsWith("audio/webm"));
  await page
    .getByRole("log")
    .getByText(result.transcript, { exact: true })
    .waitFor();
  passed(
    "Real MediaRecorder webm reaches local ASR and an authoritative conversation turn",
  );
  const synthesized = await speech;
  assert(synthesized.ok());
  assert(synthesized.headers()["content-type"].startsWith("audio/wav"));
  await page.waitForFunction(() => window.__speechEvidence.length > 0, null, {
    timeout: 90000,
  });
  synthesis = await page.evaluate(() => window.__speechEvidence[0]);
  assert(synthesis.byte_length > 44, JSON.stringify(synthesis));
  assert.deepEqual(synthesis.signature, [82, 73, 70, 70]);
  passed("Trusted persisted reply is synthesized to a real WAV response");
  assert(
    await page.evaluate(() =>
      window.__testStreams.every((stream) =>
        stream.getTracks().every((track) => track.readyState === "ended"),
      ),
    ),
  );
  passed("Microphone tracks are stopped after sending the message");
  await page.screenshot({
    path: output + "/talk-synthetic-audio-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "پایان", exact: true }).click();
  await page
    .getByText("گفتگو پایان یافت. ممنون که با ما همراه بودید.", { exact: true })
    .waitFor();
  assert.deepEqual(errors, []);
  passed("Audio conversation ends cleanly");
} catch (e) {
  failure = e.message;
  await page.screenshot({
    path: output + "/audio-failure.png",
    fullPage: true,
  });
  console.error(e.stack);
  process.exitCode = 1;
} finally {
  if (session)
    await context.request.post(
      base + "/api/v1/public/sessions/" + session.session_id + "/end",
      { headers: { Authorization: "Bearer " + session.token }, data: {} },
    );
  await writeFile(
    output + "/audio.json",
    JSON.stringify(
      {
        checks,
        errors,
        synthetic_input: true,
        transcript: result?.transcript,
        turn_state: result?.state,
        synthetic_reply: result?.reply,
        synthesis,
        failure,
        accuracy_claim:
          "Transport/processing verified; no recognition accuracy claim.",
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      checks: checks.length,
      errors,
      transcript: result?.transcript,
      state: result?.state,
    }),
  );
  await browser.close();
}
