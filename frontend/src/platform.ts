import { Capacitor, registerPlugin } from "@capacitor/core";
import webPackage from "../package.json";

export type AppPlatform = "web" | "desktop" | "android" | "ios";
export interface Runtime {
  platform: AppPlatform;
  version: string;
  serverUrl: string;
  setupRequired: boolean;
  secureStorage: boolean;
  demoMode: boolean | null;
}
interface NativeDevice {
  getInfo(): Promise<{ version: string; secureStorage: boolean }>;
  readSession(options: { server: string }): Promise<{ token: string | null }>;
  writeSession(options: { server: string; token: string }): Promise<void>;
  clearSession(): Promise<void>;
  openExternal(options: { url: string }): Promise<void>;
}
declare global {
  interface Window {
    hamavaNative?: NativeDevice;
  }
}

const SERVER_KEY = "hamava.server.v1";
const TOKEN_KEY = "hamaava_staff_session";
const SIGNED_OUT_KEY = "hamava.session.signedout.v1";
const nativePlatform = Capacitor.getPlatform();
const platform: AppPlatform = window.hamavaNative
  ? "desktop"
  : nativePlatform === "android" || nativePlatform === "ios"
    ? nativePlatform
    : "web";
const device: NativeDevice | undefined =
  window.hamavaNative ||
  (platform !== "web"
    ? registerPlugin<NativeDevice>("HamavaDevice")
    : undefined);
const runtime: Runtime = {
  platform,
  version: webPackage.version,
  serverUrl: "",
  setupRequired: platform !== "web",
  secureStorage: false,
  demoMode: null,
};
let nativeToken: string | null = null;
let vaultQueue: Promise<void> = Promise.resolve();
let vaultRevision = 0;

/** Only a server origin is accepted. Never accept credentials, paths or redirects. */
export function normalizeServerUrl(value: string): string {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    throw new Error(
      "نشانی کامل سرور مرکز را وارد کنید؛ برای مثال https://reception.example.com",
    );
  }
  const loopback = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
  if (platform === "android" && url.protocol !== "https:") {
    throw new Error("در برنامهٔ اندروید، نشانی سرور باید با HTTPS شروع شود.");
  }
  if (
    (url.protocol !== "https:" &&
      !(url.protocol === "http:" && loopback && platform !== "android")) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash ||
    !["", "/"].includes(url.pathname)
  ) {
    throw new Error(
      "نشانی سرور باید HTTPS و بدون مسیر، نام کاربری یا پارامتر باشد.",
    );
  }
  return url.origin;
}

export function getRuntime(): Readonly<Runtime> {
  return { ...runtime };
}

export function apiUrl(path: string): string {
  if (!path.startsWith("/") || path.startsWith("//"))
    throw new Error("مسیر درخواست معتبر نیست.");
  if (runtime.setupRequired)
    throw new Error("ابتدا اتصال به سرور مرکز را تنظیم کنید.");
  return `${runtime.serverUrl}${path}`;
}

export function publicUrl(path: string): string {
  const origin = runtime.serverUrl || window.location.origin;
  if (!path.startsWith("/") || path.startsWith("//"))
    throw new Error("مسیر پیوند معتبر نیست.");
  return `${origin}${path}`;
}

export async function testServerUrl(value: string) {
  const serverUrl = normalizeServerUrl(value);
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 8_000);
  try {
    const response = await fetch(`${serverUrl}/api/v1/client-info`, {
      signal: controller.signal,
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
    });
    if (!response.ok) throw new Error("server_status");
    const info = await response.json();
    if (
      info.product !== "hamava" ||
      info.api_version !== 1 ||
      typeof info.app_version !== "string" ||
      typeof info.demo_mode !== "boolean"
    )
      throw new Error("server_incompatible");
    return {
      serverUrl,
      version: info.app_version as string,
      mode: info.demo_mode ? "demo" : "configured",
      demoMode: info.demo_mode as boolean,
    };
  } catch {
    throw new Error(
      "اتصال به سرور هم‌آوا تأیید نشد. نشانی، اینترنت و تنظیمات دسترسی مرکز را بررسی کنید.",
    );
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function refreshRuntime(): Promise<Readonly<Runtime>> {
  if (!runtime.setupRequired) {
    try {
      const result = await testServerUrl(
        runtime.serverUrl || window.location.origin,
      );
      runtime.demoMode = result.demoMode;
    } catch {
      runtime.demoMode = null;
    }
  }
  window.dispatchEvent(new Event("runtime-changed"));
  return getRuntime();
}

export async function initializePlatform(): Promise<void> {
  // Browser sessions remain tab scoped. Native sessions never use WebView storage.
  try {
    const saved = localStorage.getItem(SERVER_KEY);
    if (saved) {
      runtime.serverUrl = normalizeServerUrl(saved);
      runtime.setupRequired = false;
    }
  } catch {
    localStorage.removeItem(SERVER_KEY);
  }
  if (device) {
    try {
      const info = await device.getInfo();
      runtime.version = info.version;
      runtime.secureStorage = info.secureStorage;
      sessionStorage.removeItem(TOKEN_KEY);
      if (
        runtime.serverUrl &&
        info.secureStorage &&
        localStorage.getItem(SIGNED_OUT_KEY) !== "1"
      ) {
        const session = await device.readSession({ server: runtime.serverUrl });
        nativeToken = session.token;
      }
    } catch {
      // An unavailable OS vault must not strand setup or copy tokens to localStorage.
      runtime.secureStorage = false;
      nativeToken = null;
    }
    document.addEventListener("resume", () => {
      window.dispatchEvent(new Event("app-resumed"));
    });
  }
  await refreshRuntime();
}

export const getSessionToken = (): string | null =>
  device ? nativeToken : sessionStorage.getItem(TOKEN_KEY);

function enqueueVault(operation: () => Promise<void>): Promise<void> {
  vaultQueue = vaultQueue.then(operation).catch(() => {
    runtime.secureStorage = false;
    window.dispatchEvent(new Event("native-storage-error"));
  });
  return vaultQueue;
}

export function storeSessionToken(token: string): Promise<void> {
  if (!device) {
    sessionStorage.setItem(TOKEN_KEY, token);
    return Promise.resolve();
  }
  nativeToken = token;
  const revision = ++vaultRevision;
  const server = runtime.serverUrl;
  // A failed write must never restore a previous account's vault record.
  localStorage.setItem(SIGNED_OUT_KEY, "1");
  return enqueueVault(async () => {
    await device.writeSession({ server, token });
    if (revision === vaultRevision && nativeToken === token)
      localStorage.removeItem(SIGNED_OUT_KEY);
  });
}

export function removeSessionToken(): Promise<void> {
  vaultRevision++;
  nativeToken = null;
  sessionStorage.removeItem(TOKEN_KEY);
  // The marker contains no credential. It preserves explicit logout even if
  // both the network and OS-vault deletion are unavailable at the same time.
  if (device) localStorage.setItem(SIGNED_OUT_KEY, "1");
  return device ? enqueueVault(() => device.clearSession()) : Promise.resolve();
}

export async function saveServerUrl(value: string): Promise<void> {
  const result = await testServerUrl(value);
  await removeSessionToken();
  // A clinic/server change always requires a new login; no tenant data is cached.
  localStorage.setItem(SERVER_KEY, result.serverUrl);
  runtime.serverUrl = result.serverUrl;
  runtime.demoMode = result.demoMode;
  runtime.setupRequired = false;
  window.location.replace("/");
}

export async function resetServer(): Promise<void> {
  await removeSessionToken();
  localStorage.removeItem(SERVER_KEY);
  window.location.replace("/connection");
}

export async function openExternal(url: string): Promise<void> {
  const parsed = new URL(url);
  if (!["https:", "http:"].includes(parsed.protocol))
    throw new Error("این پیوند قابل باز کردن نیست.");
  if (device) await device.openExternal({ url: parsed.href });
  else window.open(parsed.href, "_blank", "noopener,noreferrer");
}
