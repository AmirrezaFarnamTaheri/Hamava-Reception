import { readFile, readdir, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { join } from "node:path";

const root = fileURLToPath(new URL("../", import.meta.url));
const frontend = join(root, "frontend");
const lock = JSON.parse(
  await readFile(join(frontend, "package-lock.json"), "utf8"),
);
const parts = [
  "HAMAVA RECEPTION — THIRD-PARTY WEB RUNTIME NOTICES\n",
  "These notices are generated from the installed production dependency graph pinned by frontend/package-lock.json. " +
    "The notices accompany the shared web interface in the web, desktop and Android packages. " +
    "Electron also includes its own runtime license and Chromium notices beside the executable. " +
    "Optional speech models, provider services and training datasets are separate operator-provisioned dependencies.\n",
];
let count = 0;
for (const [relative, pinned] of Object.entries(lock.packages).sort(
  ([a], [b]) => a.localeCompare(b),
)) {
  if (!relative || pinned.dev) continue;
  const directory = join(frontend, relative);
  const manifest = JSON.parse(
    await readFile(join(directory, "package.json"), "utf8"),
  );
  if (manifest.version !== pinned.version)
    throw new Error(
      `Install npm ci before generating notices: ${manifest.name}`,
    );
  const repository =
    typeof manifest.repository === "string"
      ? manifest.repository
      : manifest.repository?.url;
  const title = `${manifest.name}@${manifest.version}`;
  parts.push(
    `\n${"=".repeat(72)}\n${title}\nDeclared license: ${manifest.license || pinned.license || "see package notice"}\nSource: ${repository || manifest.homepage || "see package manifest"}\n`,
  );
  const notices = (await readdir(directory, { withFileTypes: true }))
    .filter(
      (entry) =>
        entry.isFile() &&
        /^(licen[cs]e|copying|notice)(\b|[._-])/i.test(entry.name),
    )
    .map((entry) => entry.name)
    .sort();
  for (const name of notices) {
    parts.push(
      `\n--- ${name} ---\n${await readFile(join(directory, name), "utf8")}\n`,
    );
  }
  if (title === "@bufbuild/protobuf@1.10.1") {
    if (!notices.length)
      parts.push(
        await readFile(
          join(root, "docs/licenses/buf-protobuf-es-1.10.1-LICENSE.txt"),
          "utf8",
        ),
      );
    const source = await readFile(
      join(directory, "dist/esm/google/varint.js"),
      "utf8",
    );
    const header = source.match(/^(?:\/\/[^\n]*\n|\n)+/)?.[0];
    if (
      !header?.includes("Copyright 2008 Google") ||
      !header.includes("DISCLAIMED")
    )
      throw new Error("The locked Protobuf BSD attribution was not found");
    parts.push(`\n--- Bundled Google varint attribution ---\n${header}\n`);
  } else if (!notices.length) {
    throw new Error(`Missing distributable license notice for ${title}`);
  }
  count++;
}
await writeFile(
  join(frontend, "public/THIRD_PARTY_NOTICES.txt"),
  parts.join("\n"),
  "utf8",
);
console.log(
  `Retained license notices for ${count} locked web runtime packages.`,
);
