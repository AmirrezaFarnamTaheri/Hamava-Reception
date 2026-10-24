import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  stat,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { collectRelease } from "./collect-release.mjs";

// These bytes are deliberately not executable packages. "Valid" rows below
// exercise metadata association only, never actual cryptographic signatures.
const version = "7.8.9";
const projectRoot = fileURLToPath(new URL("../", import.meta.url));
const hash = (bytes) => createHash("sha256").update(bytes).digest("hex");
const windowsNames = (arch = "x64") =>
  ["setup", "portable"].map(
    (type) => `Hamava-Reception-${version}-windows-${arch}-${type}.exe`,
  );
const androidNames = (signed = false) =>
  [
    "debug.apk",
    signed ? "release.apk" : "release-unsigned.apk",
    signed ? "release.aab" : "release-unsigned.aab",
  ].map((suffix) => `Hamava-Companion-${version}-android-${suffix}`);
const unsigned = {
  HAMAVA_WINDOWS_SIGNED: "false",
  HAMAVA_ANDROID_RELEASE_SIGNED: "false",
};
const signedWindows = { ...unsigned, HAMAVA_WINDOWS_SIGNED: "true" };

async function put(root, path, content) {
  const target = join(root, path);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, content);
}

async function desktop(root, arch = "x64") {
  for (const name of windowsNames(arch))
    await put(
      root,
      `artifacts/desktop/${name}`,
      `SYNTHETIC PACKAGE FIXTURE ${name}\n`,
    );
}

async function android(root, signed = false) {
  for (const path of [
    "apk/debug/app-debug.apk",
    signed
      ? "apk/release/app-release.apk"
      : "apk/release/app-release-unsigned.apk",
    "bundle/release/app-release.aab",
  ])
    await put(
      root,
      `apps/mobile/android/app/build/outputs/${path}`,
      `SYNTHETIC PACKAGE FIXTURE ${path}\n`,
    );
}

async function signatureRows(root, arch = "x64") {
  const rows = [];
  for (const name of windowsNames(arch))
    rows.push({
      file: name,
      status: "Valid",
      thumbprint: "A".repeat(40),
      sha256: hash(await readFile(join(root, "artifacts/desktop", name))),
    });
  return rows;
}

async function signatures(root, rows) {
  await put(
    root,
    "artifacts/desktop-validation/signatures.json",
    JSON.stringify(rows),
  );
}

const collect = (root, kind, env = unsigned) =>
  collectRelease({ projectRoot: root, kind, env });

async function noOutput(root) {
  await assert.rejects(stat(join(root, "artifacts/release")), {
    code: "ENOENT",
  });
}

const cases = [];
const check = (name, run) => cases.push({ name, run });

check(
  "unsigned exact Windows pair excludes source intermediates and other architectures",
  async (root) => {
    await desktop(root);
    await desktop(root, "arm64");
    await put(
      root,
      "artifacts/desktop/__uninstaller-nsis-hamava.exe",
      "SYNTHETIC INTERMEDIATE",
    );
    await put(
      root,
      "artifacts/desktop/Hamava-Reception-0.0.1-windows-x64-setup.exe",
      "SYNTHETIC OLD VERSION",
    );
    const result = await collect(root, "desktop");
    assert.deepEqual(
      result.artifacts.map((item) => item.name).sort(),
      windowsNames().sort(),
    );
    assert.equal(result.windows_arch, "x64");
    assert.equal(result.signing.windows, false);
    assert.ok(result.artifacts.every((item) => item.signing === "unsigned"));
    for (const item of result.artifacts)
      assert.equal(
        item.sha256,
        hash(await readFile(join(root, "artifacts/release", item.name))),
      );
  },
);

check(
  "combined unsigned manifest hashes exactly five packages and supplied metadata",
  async (root) => {
    await desktop(root);
    await android(root);
    await put(
      root,
      "artifacts/release/desktop-sbom.cdx.json",
      '{"synthetic":true}\n',
    );
    await collect(root, "desktop");
    await collect(root, "android");
    const result = await collect(root, "manifest", {
      ...unsigned,
      GITHUB_SHA: "fixture-commit",
      GITHUB_RUN_ID: "fixture-run",
    });
    assert.equal(
      result.artifacts.filter((item) => item.kind === "package").length,
      5,
    );
    assert.equal(
      result.artifacts.filter((item) => item.kind === "verification_metadata")
        .length,
      1,
    );
    assert.equal(result.source_commit, "fixture-commit");
    assert.equal(result.workflow_run, "fixture-run");
    const sums = await readFile(
      join(root, "artifacts/release/SHA256SUMS.txt"),
      "utf8",
    );
    for (const item of result.artifacts) {
      const bytes = await readFile(join(root, "artifacts/release", item.name));
      assert.equal(item.sha256, hash(bytes));
      assert.equal(item.bytes, bytes.length);
      assert.ok(sums.includes(`${hash(bytes)}  ${item.name}\n`));
    }
  },
);

for (const [name, unexpected] of [
  ["stale output version", "Hamava-Reception-0.0.1-windows-x64-setup.exe"],
  ["intermediate uninstaller in output", "__uninstaller-nsis-hamava.exe"],
  ["unexpected archive in output", "Hamava-unexpected.zip"],
  ["wrong Windows architecture in output", windowsNames("arm64")[0]],
])
  check(`rejects ${name} without changing existing output`, async (root) => {
    await desktop(root);
    await put(
      root,
      `artifacts/release/${unexpected}`,
      "SYNTHETIC REJECTED INPUT",
    );
    await assert.rejects(
      collect(root, "desktop"),
      /Unexpected release output file/,
    );
    assert.deepEqual(await readdir(join(root, "artifacts/release")), [
      unexpected,
    ]);
  });

check("missing portable cannot produce a partial release", async (root) => {
  await put(root, `artifacts/desktop/${windowsNames()[0]}`, "SYNTHETIC SETUP");
  await assert.rejects(collect(root, "desktop"), /portable\.exe/);
  await noOutput(root);
});

check(
  "mixed-architecture setup and portable cannot satisfy the default pair",
  async (root) => {
    await put(
      root,
      `artifacts/desktop/${windowsNames()[0]}`,
      "SYNTHETIC X64 SETUP",
    );
    await put(
      root,
      `artifacts/desktop/${windowsNames("arm64")[1]}`,
      "SYNTHETIC ARM64 PORTABLE",
    );
    await assert.rejects(collect(root, "desktop"), /windows-x64-portable\.exe/);
    await noOutput(root);
  },
);

check(
  "arm64 requires explicit selection and then requires its exact pair",
  async (root) => {
    await desktop(root, "arm64");
    await assert.rejects(collect(root, "desktop"), /windows-x64-setup\.exe/);
    await noOutput(root);
    const result = await collect(root, "desktop", {
      ...unsigned,
      HAMAVA_WINDOWS_ARCH: "arm64",
    });
    assert.equal(result.windows_arch, "arm64");
    assert.deepEqual(
      result.artifacts.map((item) => item.name).sort(),
      windowsNames("arm64").sort(),
    );
  },
);

check(
  "unsupported architecture and ambiguous signing flags fail closed",
  async (root) => {
    await desktop(root);
    await assert.rejects(
      collect(root, "desktop", { ...unsigned, HAMAVA_WINDOWS_ARCH: "ia32" }),
      /HAMAVA_WINDOWS_ARCH/,
    );
    for (const flag of [
      "HAMAVA_WINDOWS_SIGNED",
      "HAMAVA_ANDROID_RELEASE_SIGNED",
    ])
      await assert.rejects(
        collect(root, "desktop", { ...unsigned, [flag]: "TRUE" }),
        /must be exactly true or false/,
      );
    await noOutput(root);
  },
);

check(
  "unsigned Windows collection rejects stale source signature metadata",
  async (root) => {
    await desktop(root);
    await signatures(root, await signatureRows(root));
    await assert.rejects(
      collect(root, "desktop"),
      /stale source signature metadata/,
    );
    await noOutput(root);
  },
);

check(
  "unsigned reuse rejects stale output signature metadata",
  async (root) => {
    await desktop(root);
    await collect(root, "desktop");
    const before = await readFile(
      join(root, "artifacts/release/release-manifest.json"),
    );
    await put(
      root,
      "artifacts/release/windows-signatures.json",
      JSON.stringify(await signatureRows(root)),
    );
    await assert.rejects(collect(root, "desktop"), /stale signature metadata/);
    assert.deepEqual(
      await readFile(join(root, "artifacts/release/release-manifest.json")),
      before,
    );
  },
);

check("signed Windows collection requires signature metadata", async (root) => {
  await desktop(root);
  await assert.rejects(
    collect(root, "desktop", signedWindows),
    /signatures\.json/,
  );
  await noOutput(root);
});

for (const [name, mutate, pattern] of [
  [
    "non-Valid status",
    (rows) => {
      rows[0].status = "NotSigned";
    },
    /invalid names, status, digest or certificate/,
  ],
  [
    "legacy metadata without executable hashes",
    (rows) => {
      delete rows[0].sha256;
    },
    /invalid names, status, digest or certificate/,
  ],
  [
    "digest for different executable bytes",
    (rows) => {
      rows[0].sha256 = "0".repeat(64);
    },
    /digest does not match executable bytes/,
  ],
  [
    "stale executable name",
    (rows) => {
      rows[0].file = rows[0].file.replace(version, "0.0.1");
    },
    /invalid names, status, digest or certificate/,
  ],
  [
    "duplicate executable association",
    (rows) => {
      rows[1] = { ...rows[0] };
    },
    /invalid names, status, digest or certificate/,
  ],
  [
    "missing portable association",
    (rows) => {
      rows.pop();
    },
    /both exact executable names/,
  ],
])
  check(`signed metadata rejects ${name}`, async (root) => {
    await desktop(root);
    const rows = await signatureRows(root);
    mutate(rows);
    await signatures(root, rows);
    await assert.rejects(collect(root, "desktop", signedWindows), pattern);
    await noOutput(root);
  });

check(
  "signed metadata associates both exact EXE hashes and is itself hashed",
  async (root) => {
    await desktop(root);
    await android(root, true);
    const rows = await signatureRows(root);
    await signatures(root, rows);
    const env = { ...signedWindows, HAMAVA_ANDROID_RELEASE_SIGNED: "true" };
    await collect(root, "desktop", env);
    await collect(root, "android", env);
    const result = await collect(root, "manifest", env);
    assert.equal(
      result.artifacts.filter((item) => item.kind === "package").length,
      5,
    );
    assert.equal(result.signing.windows, true);
    assert.equal(result.signing.android_release, true);
    for (const row of rows) {
      const item = result.artifacts.find(
        (candidate) => candidate.name === row.file,
      );
      assert.equal(item.sha256, row.sha256);
      assert.equal(item.signing, "matched_signature_evidence");
    }
    const evidence = result.artifacts.find(
      (item) => item.name === "windows-signatures.json",
    );
    assert.equal(
      evidence.sha256,
      hash(
        await readFile(join(root, "artifacts/release/windows-signatures.json")),
      ),
    );
    assert.equal(evidence.kind, "verification_metadata");
    assert.match(result.note, /does not verify cryptographic signatures/);
  },
);

check(
  "manifest rejects EXE bytes changed after signature association",
  async (root) => {
    await desktop(root);
    await android(root);
    await signatures(root, await signatureRows(root));
    await collect(root, "desktop", signedWindows);
    await collect(root, "android", signedWindows);
    const before = await readFile(
      join(root, "artifacts/release/release-manifest.json"),
    );
    await put(
      root,
      `artifacts/release/${windowsNames()[0]}`,
      "SYNTHETIC CHANGED BYTES",
    );
    await assert.rejects(
      collect(root, "manifest", signedWindows),
      /digest does not match executable bytes/,
    );
    assert.deepEqual(
      await readFile(join(root, "artifacts/release/release-manifest.json")),
      before,
    );
  },
);

check(
  "Android unsigned collection requires unsigned APK and complete matching trio",
  async (root) => {
    await android(root, true);
    await assert.rejects(collect(root, "android"), /app-release-unsigned\.apk/);
    await noOutput(root);
    await android(root);
    const result = await collect(root, "android");
    assert.deepEqual(
      result.artifacts.map((item) => item.name).sort(),
      androidNames().sort(),
    );
    assert.equal(
      result.artifacts.find((item) => item.name.endsWith("-debug.apk")).signing,
      "debug",
    );
    assert.ok(
      result.artifacts
        .filter((item) => !item.name.endsWith("-debug.apk"))
        .every((item) => item.signing === "unsigned"),
    );
  },
);

check(
  "Android signed collection requires the signed-build APK path",
  async (root) => {
    await android(root);
    const env = { ...unsigned, HAMAVA_ANDROID_RELEASE_SIGNED: "true" };
    await assert.rejects(collect(root, "android", env), /app-release\.apk/);
    await noOutput(root);
    await android(root, true);
    const result = await collect(root, "android", env);
    assert.deepEqual(
      result.artifacts.map((item) => item.name).sort(),
      androidNames(true).sort(),
    );
    assert.ok(
      result.artifacts
        .filter((item) => !item.name.endsWith("-debug.apk"))
        .every((item) => item.signing === "signed_build_declared"),
    );
  },
);

check(
  "Android missing bundle cannot produce a partial release",
  async (root) => {
    await android(root);
    await rm(
      join(
        root,
        "apps/mobile/android/app/build/outputs/bundle/release/app-release.aab",
      ),
    );
    await assert.rejects(collect(root, "android"), /app-release\.aab/);
    await noOutput(root);
  },
);

check(
  "Android output cannot mix signed and unsigned release names",
  async (root) => {
    await android(root);
    await android(root, true);
    await collect(root, "android");
    await assert.rejects(
      collect(root, "android", {
        ...unsigned,
        HAMAVA_ANDROID_RELEASE_SIGNED: "true",
      }),
      /Unexpected release output file/,
    );
  },
);

check(
  "combined manifest requires both complete platform sets",
  async (root) => {
    await desktop(root);
    await collect(root, "desktop");
    await assert.rejects(
      collect(root, "manifest"),
      /Incomplete Android package set/,
    );
  },
);

const args = process.argv.slice(2);
if (args.length && (args.length !== 2 || args[0] !== "--report"))
  throw new Error("Use node scripts/test-collect-release.mjs [--report path]");
const startedAt = new Date().toISOString();
const results = [];
for (const item of cases) {
  const root = await mkdtemp(join(tmpdir(), "hamava-release-fixture-"));
  const started = performance.now();
  try {
    await put(root, "package.json", JSON.stringify({ version }));
    await item.run(root);
    results.push({
      name: item.name,
      status: "passed",
      duration_ms: Math.round(performance.now() - started),
    });
  } catch (error) {
    results.push({
      name: item.name,
      status: "failed",
      duration_ms: Math.round(performance.now() - started),
      error: error.message,
    });
    console.error(`FAIL: ${item.name}: ${error.message}`);
  } finally {
    await rm(root, { recursive: true, force: true });
  }
}
const passed = results.filter((result) => result.status === "passed").length;
const sourceHashes = {};
for (const path of [
  "scripts/collect-release.mjs",
  "scripts/test-collect-release.mjs",
  ".github/workflows/release-apps.yml",
])
  sourceHashes[path] = hash(await readFile(join(projectRoot, path)));
const report = {
  suite: "release-collector-integrity",
  status: passed === results.length ? "passed" : "failed",
  started_at: startedAt,
  finished_at: new Date().toISOString(),
  environment: {
    node: process.version,
    platform: process.platform,
    arch: process.arch,
  },
  total: results.length,
  passed,
  failed: results.length - passed,
  evidence_boundary:
    "Isolated temporary synthetic package bytes and synthetic signature-status metadata only. These checks establish filename/set rejection, hash association and manifest behavior; they do not establish real Authenticode or Android signatures, installer execution, device acceptance, or a remote GitHub Actions run.",
  source_sha256: sourceHashes,
  checks: results,
};
if (args[1]) {
  const target = resolve(projectRoot, args[1]);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, JSON.stringify(report, null, 2) + "\n");
}
console.log(
  `${passed}/${results.length} release collector fixture checks passed (synthetic metadata only).`,
);
if (passed !== results.length) process.exitCode = 1;
