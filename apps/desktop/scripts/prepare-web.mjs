import { cp, mkdir, readFile, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
const root = fileURLToPath(new URL("../", import.meta.url));
const source = resolve(root, "../../frontend/dist");
const html = await readFile(resolve(source, "index.html"), "utf8").catch(() => {
  throw new Error("Build the shared web app first: npm --prefix frontend run build");
});
if (!html.includes("/assets/")) throw new Error("Expected a production Vite bundle");
await rm(resolve(root, "dist"), { recursive: true, force: true });
await mkdir(resolve(root, "dist"), { recursive: true });
await cp(source, resolve(root, "dist"), { recursive: true });
console.log("Bundled the shared reception app for the secure app://hamava origin.");
