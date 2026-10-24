"use strict";
const path = require("node:path");

function trustedFrame(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "app:" && parsed.host === "hamava" && !parsed.username && !parsed.password;
  } catch { return false; }
}
function serverOrigin(value) {
  const url = new URL(value);
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if ((url.protocol !== "https:" && !(url.protocol === "http:" && loopback)) ||
      url.username || url.password || url.search || url.hash || url.pathname !== "/")
    throw new Error("Invalid server origin");
  return url.origin;
}
function externalUrl(value) {
  const url = new URL(value);
  if (!["https:", "http:"].includes(url.protocol) || url.username || url.password)
    throw new Error("Unsupported external URL");
  return url.href;
}
function assetPath(root, url) {
  if (!trustedFrame(url)) return null;
  let pathname;
  try { pathname = decodeURIComponent(new URL(url).pathname); } catch { return null; }
  if (pathname.includes("\0") || pathname.includes("\\") || pathname.split("/").includes("..")) return null;
  const candidate = path.resolve(root, "." + pathname);
  if (candidate !== root && !candidate.startsWith(root + path.sep)) return null;
  // SPA routes are extensionless; missing assets must remain 404, never HTML.
  return path.extname(candidate) ? candidate : path.join(root, "index.html");
}
function validToken(value) {
  return typeof value === "string" && value.length >= 32 && value.length <= 16_384 &&
    /^[A-Za-z0-9_=-]+\.[A-Za-z0-9_=-]+\.[A-Za-z0-9_=-]+$/.test(value);
}
module.exports = { trustedFrame, serverOrigin, externalUrl, assetPath, validToken };
