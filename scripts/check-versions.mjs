import { readFile } from "node:fs/promises";
import assert from "node:assert/strict";
const root = new URL("../", import.meta.url);
const pkg = JSON.parse(await readFile(new URL("package.json", root), "utf8"));
assert.match(pkg.version, /^\d+\.\d+\.\d+$/);
for (const file of ["frontend/package.json", "apps/desktop/package.json", "apps/mobile/package.json"]) {
  const data = JSON.parse(await readFile(new URL(file, root), "utf8"));
  assert.equal(data.version, pkg.version, `${file}: align release versions`);
}
const python = await readFile(new URL("pyproject.toml", root), "utf8");
assert.ok(python.includes(`version = "${pkg.version}"`), "Python package version must match");
const compose = await readFile(new URL("compose.yaml", root), "utf8");
const imageVersion = compose.match(/^\s*image:\s*hamava-receptionist:([^\s]+)\s*$/m);
assert.equal(imageVersion?.[1], pkg.version, "Deployment image version must match the release");
if (process.env.GITHUB_REF_TYPE === "tag")
  assert.equal(process.env.GITHUB_REF_NAME, `v${pkg.version}`, "Release tag must match package versions");
console.log(`Release version ${pkg.version}: consistent across server, web, desktop, Android and deployment image.`);
