"use strict";
const { app, BrowserWindow, dialog, ipcMain, Menu, net, protocol, safeStorage, session, shell } = require("electron");
const fs = require("node:fs/promises");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { trustedFrame, serverOrigin, externalUrl, assetPath, validToken } = require("./security.cjs");

app.setAppUserModelId("ir.hamava.reception");
protocol.registerSchemesAsPrivileged([{ scheme: "app", privileges: {
  standard: true, secure: true, supportFetchAPI: true, corsEnabled: true, stream: true,
} }]);
let mainWindow;
const webRoot = path.resolve(__dirname, "../dist");
const sessionPath = () => path.join(app.getPath("userData"), "session.enc");
let queue = Promise.resolve();
const serialized = (operation) => {
  const current = queue.then(operation);
  queue = current.catch(() => {});
  return current;
};
async function vaultAvailable() {
  if (!(await safeStorage.isAsyncEncryptionAvailable())) return false;
  // Never persist under Linux's documented plaintext fallback.
  if (process.platform === "linux" && ["basic_text", "unknown"].includes(safeStorage.getSelectedStorageBackend())) return false;
  return true;
}
async function writeVault(data) {
  if (!(await vaultAvailable())) throw new Error("Secure session storage is unavailable");
  const encrypted = await safeStorage.encryptStringAsync(JSON.stringify(data));
  const target = sessionPath();
  await fs.mkdir(path.dirname(target), { recursive: true, mode: 0o700 });
  await fs.writeFile(target + ".tmp", encrypted, { mode: 0o600 });
  await fs.rename(target + ".tmp", target);
}
function checkCaller(event) {
  if (!mainWindow || event.sender !== mainWindow.webContents ||
      event.senderFrame !== mainWindow.webContents.mainFrame || !trustedFrame(event.senderFrame.url))
    throw new Error("Untrusted application frame");
}
function handle(channel, fn) {
  ipcMain.handle(channel, async (event, ...args) => {
    checkCaller(event);
    return fn(...args);
  });
}
function registerBridge() {
  handle("hamava:info", async () => ({ version: app.getVersion(), secureStorage: await vaultAvailable() }));
  handle("hamava:read-session", (options) => serialized(async () => {
    const server = serverOrigin(options?.server);
    if (!(await vaultAvailable())) return { token: null };
    try {
      const stat = await fs.stat(sessionPath());
      if (stat.size > 32_768) throw new Error("Invalid session file");
      const decrypted = await safeStorage.decryptStringAsync(await fs.readFile(sessionPath()));
      const data = JSON.parse(decrypted.result);
      if (data.server !== server || !validToken(data.token)) return { token: null };
      if (decrypted.shouldReEncrypt) await writeVault(data);
      return { token: data.token };
    } catch {
      await fs.rm(sessionPath(), { force: true });
      return { token: null };
    }
  }));
  handle("hamava:write-session", (options) => serialized(async () => {
    const server = serverOrigin(options?.server);
    if (!validToken(options?.token)) throw new Error("Invalid session");
    await writeVault({ server, token: options.token });
  }));
  handle("hamava:clear-session", () => serialized(async () => {
    await fs.rm(sessionPath(), { force: true });
    await fs.rm(sessionPath() + ".tmp", { force: true });
  }));
  handle("hamava:open-external", (options) => shell.openExternal(externalUrl(options?.url)));
}
async function createWindow() {
  mainWindow = new BrowserWindow({
    title: "Hamava · هم‌آوا", width: 1380, height: 920, minWidth: 780, minHeight: 600,
    backgroundColor: "#f4f6f3", show: false,
    icon: path.join(__dirname, "../assets/icon.png"),
    webPreferences: {
      preload: path.join(__dirname, "preload.cjs"),
      contextIsolation: true, sandbox: true, nodeIntegration: false,
      webSecurity: true, allowRunningInsecureContent: false,
      devTools: !app.isPackaged, spellcheck: false,
    },
  });
  mainWindow.once("ready-to-show", () => mainWindow.show());
  mainWindow.webContents.on("will-navigate", (event, url) => {
    if (!trustedFrame(url)) event.preventDefault();
  });
  mainWindow.webContents.on("will-attach-webview", (event) => event.preventDefault());
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    // Public links leave the privileged renderer and use the user's browser.
    try { void shell.openExternal(externalUrl(url)); } catch { /* deny every other scheme */ }
    return { action: "deny" };
  });
  await mainWindow.loadURL("app://hamava/");
}

if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.on("second-instance", () => { if (mainWindow) { if (mainWindow.isMinimized()) mainWindow.restore(); mainWindow.focus(); } });
  app.whenReady().then(async () => {
    protocol.handle("app", async (request) => {
      const file = assetPath(webRoot, request.url);
      if (!file || request.method !== "GET") return new Response("Not found", { status: 404 });
      try {
        const response = await net.fetch(pathToFileURL(file).href);
        const headers = new Headers(response.headers);
        headers.set("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self' https: wss: http://localhost:* http://127.0.0.1:* ws://localhost:* ws://127.0.0.1:*; media-src 'self' blob:; object-src 'none'; frame-src 'none'; base-uri 'self'; form-action 'self'");
        headers.set("X-Content-Type-Options", "nosniff");
        headers.set("Referrer-Policy", "no-referrer");
        return new Response(response.body, { status: response.status, headers });
      } catch { return new Response("Not found", { status: 404 }); }
    });
    session.defaultSession.setPermissionCheckHandler((webContents, permission, origin) =>
      webContents === mainWindow?.webContents && trustedFrame(origin) && permission === "media");
    session.defaultSession.setPermissionRequestHandler(async (webContents, permission, callback, details) => {
      const audioOnly = details.mediaTypes?.length === 1 && details.mediaTypes[0] === "audio";
      if (webContents !== mainWindow?.webContents || !trustedFrame(details.requestingUrl) || permission !== "media" || !audioOnly) {
        callback(false); return;
      }
      const answer = await dialog.showMessageBox(mainWindow, {
        type: "question", title: "هم‌آوا", message: "اجازهٔ استفاده از میکروفون برای تماس پذیرش؟",
        buttons: ["اجازه می‌دهم", "فعلاً نه"], defaultId: 1, cancelId: 1,
      });
      callback(answer.response === 0);
    });
    registerBridge();
    Menu.setApplicationMenu(Menu.buildFromTemplate([
      ...(process.platform === "darwin" ? [{ role: "appMenu" }] : []),
      { label: "File", submenu: [{ role: "close" }, { role: "quit" }] },
      { role: "editMenu" },
      { label: "View", submenu: [{ role: "reload" }, { role: "resetZoom" }, { role: "zoomIn" }, { role: "zoomOut" }, { role: "togglefullscreen" }] },
      { label: "Help", submenu: [{ label: "About Hamava", click: () => dialog.showMessageBox(mainWindow, {
        title: "Hamava Reception", message: `هم‌آوا ${app.getVersion()}`, detail: "سامانهٔ پذیرش مرکز · اتصال به سرور مرکز از بخش تنظیمات اتصال", type: "info",
      }) }] },
    ]));
    await createWindow();
  }).catch(() => { dialog.showErrorBox("Hamava", "The application could not start. Reinstall from a trusted build."); app.quit(); });
  app.on("activate", () => { if (BrowserWindow.getAllWindows().length === 0) void createWindow(); });
  app.on("window-all-closed", () => { if (process.platform !== "darwin") app.quit(); });
}
