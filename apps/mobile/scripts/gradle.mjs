import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
const cwd = fileURLToPath(new URL("../android", import.meta.url));
const executable = process.platform === "win32" ? "gradlew.bat" : "./gradlew";
const child = spawn(executable, [...process.argv.slice(2), "--no-daemon", "--stacktrace"], {
  cwd, stdio: "inherit", shell: process.platform === "win32",
});
child.on("error", (error) => { console.error(error.message); process.exitCode = 1; });
child.on("exit", (code) => { process.exitCode = code ?? 1; });
