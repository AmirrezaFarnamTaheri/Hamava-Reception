import {
  cloneElement,
  isValidElement,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  Inbox,
  Loader2,
  RefreshCw,
  Waves,
  X,
} from "lucide-react";
import { faNumber } from "./api";

export function NetworkStatus() {
  const [offline, setOffline] = useState(!navigator.onLine);
  useEffect(() => {
    const update = () => setOffline(!navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  return offline ? (
    <div className="network-status" role="alert">
      اتصال شبکه قطع است. اطلاعات ممکن است به‌روز نباشد؛ نتیجهٔ درخواست‌ها را پس
      از اتصال دوباره بررسی کنید.
    </div>
  ) : null;
}

export function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className="brand">
      <span className="brand-mark" aria-hidden="true">
        <Waves size={25} />
      </span>
      {!compact && (
        <span>
          <strong>هم‌آوا</strong>
          <small>دستیار پذیرش شما</small>
        </span>
      )}
    </div>
  );
}
export function PageTitle({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow?: string;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <header className="page-title">
      <div>
        {eyebrow && <div className="eyebrow">{eyebrow}</div>}
        <h1>{title}</h1>
        {description && <p>{description}</p>}
      </div>
      {action && <div className="page-actions">{action}</div>}
    </header>
  );
}
export function SectionTitle({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="section-title">
      <div>
        <h2>{title}</h2>
        {description && <p>{description}</p>}
      </div>
      {action}
    </div>
  );
}
export function Alert({
  children,
  kind = "error",
  onClose,
}: {
  children: ReactNode;
  kind?: "error" | "success" | "info";
  onClose?: () => void;
}) {
  return (
    <div
      className={`alert ${kind}`}
      role={kind === "error" ? "alert" : "status"}
    >
      {kind === "success" ? (
        <CheckCircle2 size={18} />
      ) : (
        <AlertCircle size={18} />
      )}
      <span>{children}</span>
      {onClose && (
        <button
          type="button"
          className="icon-button"
          aria-label="بستن پیام"
          onClick={onClose}
        >
          <X size={16} />
        </button>
      )}
    </div>
  );
}
export function Empty({
  title,
  description,
  action,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="empty-icon">
        <Inbox size={26} />
      </div>
      <h3>{title}</h3>
      {description && <p>{description}</p>}
      {action}
    </div>
  );
}
export function Loading({ rows = 3 }: { rows?: number }) {
  return (
    <div
      className="skeleton-stack"
      role="status"
      aria-label="در حال دریافت اطلاعات"
      aria-busy="true"
    >
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" />
      ))}
      <span className="sr-only">در حال دریافت اطلاعات</span>
    </div>
  );
}
export function Retry({
  error,
  onRetry,
}: {
  error: string;
  onRetry: () => void;
}) {
  return (
    <div className="retry">
      <Alert>{error}</Alert>
      <button className="button secondary" onClick={onRetry}>
        <RefreshCw size={16} />
        تلاش دوباره
      </button>
    </div>
  );
}
export function Busy({
  busy,
  children,
}: {
  busy: boolean;
  children: ReactNode;
}) {
  return (
    <>
      {busy && <Loader2 size={17} className="spin" />}
      {children}
    </>
  );
}
const stateLabels: Record<string, [string, string]> = {
  READBACK_REQUIRED: ["نیازمند بازخوانی تقویم", "warning"],
  PENDING_CONFIRMATION: ["منتظر پاسخ تقویم", "warning"],
  CANCEL_PENDING: ["لغو در انتظار تأیید", "warning"],
  RESCHEDULE_PENDING: ["جابه‌جایی در انتظار تأیید", "warning"],
  FAILED_REVIEW: ["نیازمند بررسی نتیجه", "danger"],
  CONFIRMED: ["تأیید شده", "success"],
  PENDING_PAYMENT: ["منتظر پرداخت", "warning"],
  PENDING_STAFF_APPROVAL: ["نیازمند تأیید", "warning"],
  DISABLED: ["خاموش", "neutral"],
  CANCELED: ["لغو شده", "neutral"],
  CANCELLED: ["لغو شده", "neutral"],
  EXPIRED: ["منقضی شده", "neutral"],
  FAILED: ["ناموفق", "danger"],
  QUEUED: ["در صف ارسال", "neutral"],
  SENDING: ["در حال ارسال", "info"],
  SENT: ["ارسال شده", "info"],
  DELIVERED: ["تحویل داده شده", "success"],
  UNKNOWN: ["نیازمند بررسی", "warning"],
  SIMULATED: ["آزمایشی؛ ارسال نشده", "neutral"],
  SUPPRESSED: ["ارسال متوقف شده", "neutral"],
  OPEN: ["منتظر رسیدگی", "warning"],
  RESOLVED: ["رسیدگی شده", "success"],
  IN_PROGRESS: ["در حال رسیدگی", "info"],
  CALLBACK: ["تماس مجدد زمان‌بندی‌شده", "info"],
  ARRIVAL_REVIEW: ["تأخیر مراجعه؛ نیازمند هماهنگی", "warning"],
  DELAY_REVIEW: ["تأخیر پزشک؛ نیازمند هماهنگی", "warning"],
  CLOSURE_REVIEW: ["تعطیلی؛ نیازمند هماهنگی", "danger"],
  WITHDRAWN: ["پس گرفته شده", "neutral"],
  ATTENDED: ["مراجعه کرده", "success"],
  NO_SHOW: ["مراجعه نکرده", "danger"],
  PAID: ["پرداخت شده", "success"],
  UNPAID: ["پرداخت نشده", "neutral"],
  DEMO_PENDING: ["منتظر پرداخت آزمایشی", "warning"],
  SETTLED: ["پرداخت تأییدشده", "success"],
  LATE_REQUIRES_REFUND: ["دیرهنگام؛ بررسی بازپرداخت", "warning"],
  PARTIALLY_REFUNDED: ["بخشی بازپرداخت شده", "info"],
  REFUNDED: ["بازپرداخت شده", "neutral"],
  REFUSED: ["درخواست رد شده", "neutral"],
  RECONCILING: ["در حال تطبیق", "warning"],
  RECONCILIATION_REQUIRED: ["نیازمند تطبیق", "warning"],
  REJECTED: ["پذیرفته نشده", "neutral"],
  UNDER_REVIEW: ["در حال بررسی ارائه‌دهنده", "info"],
  WON: ["نتیجه به نفع مرکز", "success"],
  LOST: ["نتیجه به زیان مرکز", "danger"],
  CLOSED: ["پرونده بسته شده", "neutral"],
  REQUESTED: ["درخواست ثبت‌شده", "warning"],
  COMPLETED: ["تکمیل شده", "success"],
  DRAFT: ["پیش‌نویس ثبت‌شده", "neutral"],
  WAITING: ["منتظر زمان مناسب", "neutral"],
  OFFERED: ["پیشنهاد فعال", "warning"],
  BOOKED: ["نوبت ثبت‌شده", "success"],
  ACCEPTED: ["پذیرفته شده", "success"],
  EXHAUSTED: ["سقف پیشنهاد تکمیل", "neutral"],
  configured: ["پیکربندی شده", "success"],
  configured_unverified: ["پیکربندی؛ نیازمند آزمون", "warning"],
  demo_disabled: ["محیط نمایشی", "neutral"],
  active: ["فعال", "success"],
  not_configured: ["نیازمند اتصال", "neutral"],
  ready: ["آماده", "success"],
  unavailable: ["در دسترس نیست", "warning"],
  HIGH: ["اولویت بالا", "danger"],
  URGENT: ["فوری", "danger"],
  NORMAL: ["عادی", "neutral"],
  LOW: ["کم", "neutral"],
};
export function Status({
  value,
  status,
  label,
}: {
  value?: string | null;
  status?: string | null;
  label?: string;
}) {
  const current = value ?? status;
  const item = stateLabels[current || ""];
  return (
    <span className={`badge ${item?.[1] || "neutral"}`}>
      <span className="badge-dot" />
      {label ||
        item?.[0] ||
        (
          {
            PENDING: "در انتظار",
            ACTIVE: "فعال",
            ENDED: "پایان یافته",
          } as Record<string, string>
        )[current || ""] ||
        "در حال بررسی"}
    </span>
  );
}
export function Metric({
  label,
  value,
  detail,
  icon,
  accent = false,
  onClick,
}: {
  label: string;
  value: number | string;
  detail: string;
  icon: ReactNode;
  accent?: boolean;
  onClick?: () => void;
}) {
  const content = (
    <>
      <div className="metric-top">
        <span>{label}</span>
        <span className="metric-icon">{icon}</span>
      </div>
      <strong>{faNumber(value)}</strong>
      <small>{detail}</small>
    </>
  );
  if (onClick)
    return (
      <button
        type="button"
        className={`metric metric-button ${accent ? "accent" : ""}`}
        onClick={onClick}
      >
        {content}
      </button>
    );
  return (
    <div className={`metric ${accent ? "accent" : ""}`}>
      <div className="metric-top">
        <span>{label}</span>
        <span className="metric-icon">{icon}</span>
      </div>
      <strong>{faNumber(value)}</strong>
      <small>{detail}</small>
    </div>
  );
}
export function TextLink({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button className="text-link" onClick={onClick}>
      {children}
      <ArrowLeft size={16} />
    </button>
  );
}
export function Dialog({
  title,
  onClose,
  children,
  wide = false,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    ref.current?.showModal();
    const node = ref.current;
    return () => node?.close();
  }, []);
  return (
    <dialog
      ref={ref}
      className={wide ? "modal wide" : "modal"}
      aria-labelledby={titleId}
      onCancel={(event) => {
        event.preventDefault();
        onClose();
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal-header">
        <h2 id={titleId}>{title}</h2>
        <button
          type="button"
          className="icon-button"
          onClick={onClose}
          aria-label="بستن پنجره"
        >
          <X size={20} />
        </button>
      </div>
      {children}
    </dialog>
  );
}
export function Field({
  label,
  hint,
  children,
  className = "",
  controlId,
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
  controlId?: string;
}) {
  const generatedId = useId();
  const child = isValidElement<{ id?: string; "aria-describedby"?: string }>(
    children,
  )
    ? children
    : null;
  const id = controlId || child?.props.id || generatedId;
  const hintId = `${id}-hint`;
  return (
    <div className={`field ${className}`}>
      <label className="field-label" htmlFor={id}>
        {label}
      </label>
      {child && !controlId
        ? cloneElement(child, {
            id,
            "aria-describedby":
              [child.props["aria-describedby"], hint ? hintId : undefined]
                .filter(Boolean)
                .join(" ") || undefined,
          })
        : children}
      {hint && <small id={hintId}>{hint}</small>}
    </div>
  );
}
