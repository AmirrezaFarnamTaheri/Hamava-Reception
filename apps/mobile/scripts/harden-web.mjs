import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
const path = fileURLToPath(new URL("../android/app/src/main/assets/public/index.html", import.meta.url));
const policy = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https: wss:; media-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'self'; form-action 'self'";
let html = await readFile(path, "utf8");
if (!html.includes('http-equiv="Content-Security-Policy"'))
  html = html.replace("<head>", `<head>\n    <meta http-equiv="Content-Security-Policy" content="${policy}" />`);
await writeFile(path, html);
console.log("Android bundle policy applied; server configuration stays outside the package.");
