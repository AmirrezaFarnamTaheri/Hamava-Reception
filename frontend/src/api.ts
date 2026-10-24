import {
  apiUrl,
  getSessionToken,
  storeSessionToken,
  removeSessionToken,
} from "./platform";
export const getToken = getSessionToken;
export const setToken = storeSessionToken;
export const clearToken = removeSessionToken;

const messages: Record<string, string> = {
  SLOT_UNAVAILABLE: "این زمان دیگر خالی نیست. لطفاً زمان دیگری انتخاب کنید.",
  slot_unavailable: "این زمان دیگر خالی نیست. لطفاً زمان دیگری انتخاب کنید.",
  VERSION_CONFLICT:
    "اطلاعات تغییر کرده است. صفحه را تازه کنید و دوباره تلاش کنید.",
  STALE_VERSION:
    "اطلاعات تغییر کرده است. صفحه را تازه کنید و دوباره تلاش کنید.",
  IDEMPOTENCY_CONFLICT:
    "این درخواست قبلاً با اطلاعات دیگری ثبت شده است. صفحه را تازه کنید.",
  HOLD_EXPIRED: "مهلت نگه‌داشتن نوبت تمام شده است. یک زمان جدید انتخاب کنید.",
  PAYMENT_TERMS_CONFIRMATION_REQUIRED:
    "شرایط مالی به بررسی دوباره نیاز دارد. مبلغ و شرایط تازه را با مراجعه‌کننده تأیید کنید.",
  DEPOSIT_POLICY_NOT_PUBLISHED:
    "شرایط معتبر دریافت بیعانه هنوز منتشر نشده است. مسئول مرکز باید آن را بررسی کند.",
  PAYMENT_POLICY_MERCHANT_CHANGED:
    "تنظیمات دریافت بیعانه تغییر کرده است. مسئول مرکز باید شرایط مالی را دوباره بررسی کند.",
  UNAUTHORIZED: "نشست شما تمام شده است. دوباره وارد شوید.",
  FORBIDDEN: "برای این کار دسترسی لازم را ندارید.",
  INVALID_CREDENTIALS: "ایمیل یا گذرواژه درست نیست.",
  PROVIDER_NOT_CONFIGURED: "این سرویس هنوز به ارائه‌دهنده متصل نشده است.",
  service_not_configured: "این سرویس هنوز به ارائه‌دهنده متصل نشده است.",
  RATE_LIMITED: "تعداد درخواست‌ها زیاد است. کمی بعد دوباره تلاش کنید.",
};

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
  }
}

export async function api<T>(
  path: string,
  options: RequestInit & { token?: string | null } = {},
): Promise<T> {
  const { token = getToken(), ...request } = options;
  const headers = new Headers(request.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (request.body && typeof request.body === "string")
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(apiUrl(`/api/v1${path}`), {
      ...request,
      headers,
      credentials: "omit",
      cache: "no-store",
      redirect: "error",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "NETWORK",
      "ارتباط با سامانه برقرار نشد. اتصال اینترنت و وضعیت سرویس را بررسی کنید.",
    );
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    const detail = data.detail;
    const code =
      typeof detail === "object" && !Array.isArray(detail)
        ? String(detail?.code || response.status)
        : String(response.status);
    const safeMessage =
      typeof detail?.message === "string" &&
      /[\u0600-\u06ff]/.test(detail.message)
        ? detail.message
        : undefined;
    const validation = Array.isArray(detail)
      ? "برخی اطلاعات درست وارد نشده‌اند. فیلدهای فرم را بررسی کنید."
      : undefined;
    if (
      response.status === 401 &&
      token === getToken() &&
      !path.startsWith("/auth/login") &&
      !path.startsWith("/public/")
    )
      window.dispatchEvent(new Event("session-expired"));
    throw new ApiError(
      response.status,
      code,
      safeMessage ||
        messages[code] ||
        validation ||
        (response.status === 403
          ? messages.FORBIDDEN
          : response.status === 404
            ? "اطلاعات موردنظر پیدا نشد یا دیگر در دسترس نیست."
            : response.status === 409
              ? messages.VERSION_CONFLICT
              : response.status === 503
                ? "سرویس فعلاً در دسترس نیست. کمی بعد دوباره تلاش کنید."
                : "انجام درخواست ممکن نشد. لطفاً دوباره تلاش کنید."),
    );
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const post = <T>(path: string, data: unknown, token?: string | null) =>
  api<T>(path, {
    method: "POST",
    body: JSON.stringify(data),
    ...(token !== undefined ? { token } : {}),
  });
export const faNumber = (value: number | string) =>
  typeof value === "number"
    ? new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 }).format(value)
    : value.replace(/\d/g, (x) => "۰۱۲۳۴۵۶۷۸۹"[Number(x)]);
export const faDate = (value: string | Date, withTime = false) => {
  const date = typeof value === "string" ? new Date(value) : value;
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("fa-IR", {
    timeZone: "Asia/Tehran",
    month: "long",
    day: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
};
export const faTime = (value: string) =>
  new Intl.DateTimeFormat("fa-IR", {
    timeZone: "Asia/Tehran",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
export const localToday = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Tehran",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
export const newId = () => crypto.randomUUID();
export const errorText = (error: unknown) =>
  error instanceof Error ? error.message : "انجام درخواست ممکن نشد.";
