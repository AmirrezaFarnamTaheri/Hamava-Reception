const { test } = require("node:test");
const assert = require("node:assert/strict");
const { trustedFrame, serverOrigin, externalUrl, assetPath, validToken } = require("../src/security.cjs");
test("only the packaged top-level app origin is trusted", () => {
  assert.equal(trustedFrame("app://hamava/tasks"), true);
  for (const value of ["https://hamava/", "app://evil/", "app://user@hamava/", "file:///tmp/test.html", "javascript:alert(1)"])
    assert.equal(trustedFrame(value), false);
});
test("server profiles reject credentials, mixed transport, path and query surprises", () => {
  assert.equal(serverOrigin("https://clinic.example/"), "https://clinic.example");
  assert.equal(serverOrigin("http://127.0.0.1:8000"), "http://127.0.0.1:8000");
  for (const value of ["http://clinic.example", "https://user:secret@clinic.example", "https://clinic.example/api", "https://clinic.example/?token=1", "file:///tmp/x"])
    assert.throws(() => serverOrigin(value));
});
test("asset lookup confines filesystem reads and preserves SPA navigation", () => {
  assert.equal(assetPath("/bundle", "app://hamava/tasks"), "/bundle/index.html");
  assert.equal(assetPath("/bundle", "app://hamava/assets/app.js"), "/bundle/assets/app.js");
  for (const value of ["app://hamava/%2e%2e%2fsecret.txt", "app://hamava/%00a", "app://hamava/a%5c..%5cx", "https://evil/a"])
    assert.equal(assetPath("/bundle", value), null);
});
test("external navigation cannot launch local applications", () => {
  assert.equal(externalUrl("https://clinic.example/talk/bahar"), "https://clinic.example/talk/bahar");
  for (const value of ["file:///etc/passwd", "javascript:alert(1)", "powershell:execute", "https://user:pass@clinic.example"])
    assert.throws(() => externalUrl(value));
});
test("vault accepts bounded token shapes only", () => {
  assert.equal(validToken("a".repeat(20) + "." + "b".repeat(20) + "." + "c".repeat(20)), true);
  for (const value of [null, "hi", "not a token", "x".repeat(20_000)]) assert.equal(validToken(value), false);
});
