import { lstat, mkdir, readFile, readdir, writeFile } from "node:fs/promises";
import { createHash } from "node:crypto";
import { fileURLToPath, pathToFileURL } from "node:url";
import { join, resolve } from "node:path";

const defaultRoot = fileURLToPath(new URL("../", import.meta.url));
const metadataNames = new Set([
  "desktop-sbom.cdx.json",
  "android-sbom.cdx.json",
  "frontend-sbom.cdx.json",
  "windows-signatures.json",
]);
const generatedNames = new Set(["SHA256SUMS.txt", "release-manifest.json"]);
const sha256 = (bytes) => createHash("sha256").update(bytes).digest("hex");

function signingFlag(env, name) {
  const value = env[name] ?? "false";
  if (value !== "true" && value !== "false")
    throw new Error(`${name} must be exactly true or false`);
  return value === "true";
}

async function exists(path) {
  try {
    return await lstat(path);
  } catch (error) {
    if (error.code === "ENOENT") return null;
    throw error;
  }
}

async function regularFile(path) {
  const info = await exists(path);
  if (!info?.isFile() || info.isSymbolicLink())
    throw new Error(`Expected a regular release file: ${path}`);
  return readFile(path);
}

function requireComplete(files, names, label, required = false) {
  if (required || names.some((name) => files.has(name))) {
    const missing = names.filter((name) => !files.has(name));
    if (missing.length)
      throw new Error(
        `Incomplete ${label} package set; missing ${missing.join(", ")}`,
      );
  }
}

function validateWindowsSignatures(files, windows, signed) {
  const bytes = files.get("windows-signatures.json");
  if (!signed) {
    if (bytes)
      throw new Error(
        "Unsigned Windows collection rejects stale signature metadata",
      );
    return;
  }
  if (!windows.some((name) => files.has(name)) && !bytes) return;
  requireComplete(files, windows, "Windows", true);
  if (!bytes)
    throw new Error("Signed Windows packages require windows-signatures.json");
  let evidence;
  try {
    evidence = JSON.parse(bytes.toString("utf8"));
  } catch {
    throw new Error("Windows signature metadata must be valid JSON");
  }
  if (!Array.isArray(evidence) || evidence.length !== windows.length)
    throw new Error(
      "Windows signature metadata must contain both exact executable names",
    );
  const matched = new Set();
  for (const item of evidence) {
    if (
      !item ||
      !windows.includes(item.file) ||
      matched.has(item.file) ||
      item.status !== "Valid" ||
      typeof item.sha256 !== "string" ||
      !/^[a-f0-9]{64}$/i.test(item.sha256) ||
      typeof item.thumbprint !== "string" ||
      !/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/i.test(item.thumbprint)
    )
      throw new Error(
        "Windows signature metadata has invalid names, status, digest or certificate identity",
      );
    if (item.sha256.toLowerCase() !== sha256(files.get(item.file)))
      throw new Error(
        `Windows signature digest does not match executable bytes: ${item.file}`,
      );
    matched.add(item.file);
  }
}

export async function collectRelease({
  projectRoot = defaultRoot,
  kind,
  outputDirectory = "artifacts/release",
  env = process.env,
}) {
  if (!["desktop", "android", "manifest"].includes(kind))
    throw new Error("Use desktop, android or manifest");
  const version = JSON.parse(
    await readFile(join(projectRoot, "package.json"), "utf8"),
  ).version;
  if (typeof version !== "string" || !/^\d+\.\d+\.\d+$/.test(version))
    throw new Error("Release version must be a numeric major.minor.patch");
  const arch = env.HAMAVA_WINDOWS_ARCH ?? "x64";
  if (!["x64", "arm64"].includes(arch))
    throw new Error("HAMAVA_WINDOWS_ARCH must be x64 or arm64");
  const windowsSigned = signingFlag(env, "HAMAVA_WINDOWS_SIGNED");
  const androidSigned = signingFlag(env, "HAMAVA_ANDROID_RELEASE_SIGNED");
  const windows = ["setup", "portable"].map(
    (type) => `Hamava-Reception-${version}-windows-${arch}-${type}.exe`,
  );
  const androidSources = [
    ["apk/debug/app-debug.apk", "debug.apk"],
    [
      androidSigned
        ? "apk/release/app-release.apk"
        : "apk/release/app-release-unsigned.apk",
      androidSigned ? "release.apk" : "release-unsigned.apk",
    ],
    [
      "bundle/release/app-release.aab",
      androidSigned ? "release.aab" : "release-unsigned.aab",
    ],
  ];
  const android = androidSources.map(
    ([, suffix]) => `Hamava-Companion-${version}-android-${suffix}`,
  );
  const packageNames = new Set([...windows, ...android]);
  const allowedNames = new Set([
    ...packageNames,
    ...metadataNames,
    ...generatedNames,
  ]);
  const output = resolve(projectRoot, outputDirectory);
  const files = new Map();
  const outputInfo = await exists(output);
  if (outputInfo) {
    if (!outputInfo.isDirectory() || outputInfo.isSymbolicLink())
      throw new Error("Release output must be a regular directory");
    for (const name of await readdir(output)) {
      if (!allowedNames.has(name))
        throw new Error(`Unexpected release output file: ${name}`);
      const bytes = await regularFile(join(output, name));
      if (!generatedNames.has(name)) files.set(name, bytes);
    }
  }
  // A reused output must already be coherent; do not repair mixed releases by
  // silently overwriting selected files while retaining stale evidence.
  requireComplete(files, windows, "Windows");
  requireComplete(files, android, "Android");
  validateWindowsSignatures(files, windows, windowsSigned);

  const additions = new Map();
  if (kind === "desktop") {
    for (const name of windows)
      additions.set(
        name,
        await regularFile(join(projectRoot, "artifacts/desktop", name)),
      );
    const signaturePath = join(
      projectRoot,
      "artifacts/desktop-validation/signatures.json",
    );
    if (windowsSigned)
      additions.set(
        "windows-signatures.json",
        await regularFile(signaturePath),
      );
    else if (await exists(signaturePath))
      throw new Error(
        "Unsigned Windows collection rejects stale source signature metadata",
      );
    validateWindowsSignatures(additions, windows, windowsSigned);
  }
  if (kind === "android") {
    for (const [index, [source]] of androidSources.entries())
      additions.set(
        android[index],
        await regularFile(
          join(projectRoot, "apps/mobile/android/app/build/outputs", source),
        ),
      );
  }
  for (const [name, bytes] of additions) files.set(name, bytes);
  requireComplete(files, windows, "Windows", kind !== "android");
  requireComplete(files, android, "Android", kind !== "desktop");
  validateWindowsSignatures(files, windows, windowsSigned);

  const artifacts = [...files.entries()]
    .sort(([a], [b]) => a.localeCompare(b, "en"))
    .map(([name, bytes]) => ({
      name,
      kind: packageNames.has(name) ? "package" : "verification_metadata",
      bytes: bytes.length,
      sha256: sha256(bytes),
      ...(packageNames.has(name)
        ? {
            signing: windows.includes(name)
              ? windowsSigned
                ? "matched_signature_evidence"
                : "unsigned"
              : name.endsWith("-debug.apk")
                ? "debug"
                : androidSigned
                  ? "signed_build_declared"
                  : "unsigned",
          }
        : {}),
    }));
  const manifest = {
    version,
    windows_arch: arch,
    signing: { windows: windowsSigned, android_release: androidSigned },
    source_commit: env.GITHUB_SHA || null,
    workflow_run: env.GITHUB_RUN_ID || null,
    created_at: new Date().toISOString(),
    artifacts,
    note: "Hashes establish file identity. Windows evidence is checked for matching executable hashes and Valid status from the separate signature verifier. This collector does not verify cryptographic signatures. Debug and unsigned packages are test builds.",
  };
  // Validate complete inputs before modifying the output. Signature associations,
  // copied packages and manifest hashes all use the same bytes read above.
  await mkdir(output, { recursive: true });
  for (const [name, bytes] of additions)
    await writeFile(join(output, name), bytes);
  await writeFile(
    join(output, "SHA256SUMS.txt"),
    artifacts
      .map((artifact) => `${artifact.sha256}  ${artifact.name}\n`)
      .join(""),
  );
  await writeFile(
    join(output, "release-manifest.json"),
    JSON.stringify(manifest, null, 2) + "\n",
  );
  return manifest;
}

if (
  process.argv[1] &&
  pathToFileURL(resolve(process.argv[1])).href === import.meta.url
) {
  try {
    const manifest = await collectRelease({
      kind: process.argv[2],
      outputDirectory: process.argv[3],
    });
    const packages = manifest.artifacts.filter(
      (artifact) => artifact.kind === "package",
    ).length;
    console.log(
      `Collected ${packages} compiled package(s) and ${manifest.artifacts.length - packages} metadata file(s) with SHA-256 checksums.`,
    );
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
