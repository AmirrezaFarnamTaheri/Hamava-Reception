import {
  ArrowUpLeft,
  CalendarCheck2,
  CalendarDays,
  Clock3,
  Headphones,
  MessageSquareText,
  Plus,
  Radio,
  ShieldCheck,
} from "lucide-react";
import { faDate, faNumber, faTime } from "../api";
import {
  Alert,
  Empty,
  Loading,
  Metric,
  PageTitle,
  Retry,
  SectionTitle,
  Status,
  TextLink,
} from "../components";
import { useRemote } from "../hooks";
import type { Dashboard, User } from "../types";
import { LiveCalls } from "../LiveCalls";
import { hasPermission } from "../permissions";
import { publicUrl } from "../platform";

const modeLabels: Record<string, string> = {
  after_hours: "پاسخ‌گویی پس از ساعت کاری",
  overflow: "پاسخ‌گویی به تماس‌های بی‌پاسخ",
  human_primary: "پذیرش انسانی در اولویت",
  supervised: "دستیار با نظارت پذیرش",
  paused: "پاسخ‌گویی خودکار متوقف است",
  ai_primary: "دستیار در اولویت",
};
export function Overview({
  user,
  navigate,
  clinicSlug,
  integrations,
  integrationsError,
}: {
  user: User;
  navigate: (path: string) => void;
  clinicSlug?: string;
  integrations?: {
    items: { id: string; name: string; status: string }[];
  } | null;
  integrationsError?: string;
}) {
  const { data, error, loading, refresh } = useRemote<Dashboard>(
    "/dashboard",
    15000,
  );
  return (
    <>
      <PageTitle
        eyebrow="نمای کلی پذیرش"
        title="امروز، با خیال آسوده‌تر"
        description="نوبت‌ها و درخواست‌هایی که به توجه شما نیاز دارند، همین‌جا هستند."
        action={
          hasPermission(user, "appointment:write") && (
            <button
              className="button primary"
              onClick={() => navigate("/appointments?new=1")}
            >
              <Plus size={18} />
              ثبت نوبت
            </button>
          )
        }
      />
      {error && <Retry error={error} onRetry={refresh} />}
      {error && data && (
        <Alert kind="info">
          اطلاعات زیر آخرین وضعیت دریافت‌شده است و ممکن است تغییر کرده باشد.
          برای بررسی وضعیت فعلی، تازه‌سازی کنید.
        </Alert>
      )}
      {loading ? (
        <Loading rows={5} />
      ) : (
        data && (
          <div className="overview-day">
            <section className="welcome-banner today-focus">
              <div>
                <span className="banner-tag">
                  <span className="live-dot" />
                  {modeLabels[data.clinic.mode] || "وضعیت پذیرش مرکز"}
                </span>
                <h2>
                  {data.metrics.pending_tasks > 0
                    ? `${faNumber(data.metrics.pending_tasks)} درخواست منتظر همراهی تیم است`
                    : "برنامهٔ روز، پیش روی شماست"}
                </h2>
                <p>
                  {data.metrics.pending_tasks > 0
                    ? "پیگیری را به عهده بگیرید، با مراجعه‌کننده هماهنگ کنید و نتیجه را ثبت کنید."
                    : "نوبت‌ها را مرور کنید و وضعیت مراجعه را پس از حضور مراجعه‌کننده به‌روز کنید."}
                </p>
                {clinicSlug && (
                  <a
                    className="button banner-button"
                    href={publicUrl(`/talk/${clinicSlug}`)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    گفت‌وگو با پذیرش
                    <ArrowUpLeft size={17} />
                  </a>
                )}
              </div>
              <div className="today-focus-action">
                <span className="today-focus-icon">
                  <Headphones size={30} />
                </span>
                <button
                  className="button primary"
                  onClick={() =>
                    navigate(
                      data.metrics.pending_tasks > 0
                        ? "/tasks"
                        : "/appointments",
                    )
                  }
                >
                  {data.metrics.pending_tasks > 0
                    ? "رسیدگی به درخواست‌ها"
                    : "دیدن برنامهٔ امروز"}
                  <ArrowUpLeft size={17} />
                </button>
              </div>
            </section>
            <div className="metric-grid">
              <Metric
                label="نوبت‌های امروز"
                value={data.metrics.appointments_today}
                detail={`${faNumber(data.metrics.confirmed_today)} نوبت تأیید شده`}
                icon={<CalendarDays size={20} />}
                accent
                onClick={() => navigate("/appointments")}
              />
              <Metric
                label="درخواست‌های باز"
                value={data.metrics.pending_tasks}
                detail="نیازمند رسیدگی تیم پذیرش"
                icon={<Headphones size={20} />}
                onClick={() => navigate("/tasks")}
              />
              <Metric
                label="تماس‌های جاری"
                value={data.metrics.active_calls}
                detail="نشست‌های فعال ثبت‌شده در سامانه"
                icon={<Radio size={20} />}
                onClick={() => navigate("/calls")}
              />
              <Metric
                label="زمان استفاده"
                value={data.metrics.minutes_used}
                detail="دقیقهٔ ثبت‌شده در این دوره"
                icon={<Clock3 size={20} />}
              />
            </div>
            {integrationsError ? (
              <Alert kind="info">
                وضعیت اتصال سرویس‌ها دریافت نشد؛ جزئیات را در تنظیمات مرکز بررسی
                کنید.
              </Alert>
            ) : (
              integrations && (
                <div
                  className="service-strip"
                  aria-label="وضعیت پیکربندی سرویس‌های پذیرش"
                >
                  {integrations.items
                    .filter((item) =>
                      ["calendar", "speech", "sms", "payments"].includes(
                        item.id,
                      ),
                    )
                    .map((item) => (
                      <span key={item.id}>
                        <span>{item.name}</span>
                        <Status value={item.status} />
                      </span>
                    ))}
                  <button
                    type="button"
                    className="text-link"
                    onClick={() => navigate("/settings?tab=integrations")}
                  >
                    بررسی اتصال‌ها
                  </button>
                </div>
              )
            )}
            {data.metrics.active_calls > 0 &&
              hasPermission(user, "task:read") && (
                <LiveCalls canTakeover={hasPermission(user, "task:write")} />
              )}
            <div className="overview-grid">
              <section className="panel schedule-panel">
                <SectionTitle
                  title="برنامهٔ امروز"
                  description={faDate(data.date + "T12:00:00+03:30")}
                  action={
                    <TextLink onClick={() => navigate("/appointments")}>
                      همهٔ نوبت‌ها
                    </TextLink>
                  }
                />
                {data.appointments.length ? (
                  <div className="appointment-timeline">
                    {data.appointments.slice(0, 6).map((appointment) => (
                      <div className="timeline-row" key={appointment.id}>
                        <div className="timeline-time">
                          {faTime(appointment.start_at)}
                        </div>
                        <div className="timeline-marker" />
                        <div className="timeline-info">
                          <strong>{appointment.patient_name}</strong>
                          <span>
                            {appointment.service_name}{" "}
                            <span className="middot">·</span>{" "}
                            {appointment.provider_name}
                          </span>
                        </div>
                        <Status value={appointment.status} />
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty
                    title="امروز هنوز نوبتی ثبت نشده"
                    description="با ثبت یک نوبت یا دریافت درخواست از پذیرش آنلاین، برنامهٔ روز اینجا نمایش داده می‌شود."
                    action={
                      <button
                        className="button secondary"
                        onClick={() => navigate("/appointments?new=1")}
                      >
                        <Plus size={16} />
                        ثبت نوبت
                      </button>
                    }
                  />
                )}
                <div className="panel-footnote">
                  <ShieldCheck size={15} />
                  فقط نوبت‌هایی با وضعیت «تأیید شده» قطعی هستند.
                </div>
              </section>
              <section className="panel followups-panel">
                <SectionTitle
                  title="نیازمند توجه شما"
                  description="درخواست‌ها و پیام‌های پیگیری"
                  action={
                    <span className="count-pill">
                      {faNumber(
                        data.metrics.pending_tasks +
                          data.metrics.notifications_failed,
                      )}
                    </span>
                  }
                />
                {data.tasks.filter((t) => t.status !== "RESOLVED").length ? (
                  <div className="task-preview-list">
                    {data.tasks
                      .filter((t) => t.status !== "RESOLVED")
                      .slice(0, 3)
                      .map((task) => (
                        <button
                          className="task-preview"
                          key={task.id}
                          onClick={() => navigate("/tasks")}
                        >
                          <span className="task-preview-icon">
                            <Headphones size={18} />
                          </span>
                          <span>
                            <strong>
                              {task.summary || "درخواست پیگیری پذیرش"}
                            </strong>
                            <small>{faDate(task.created_at, true)}</small>
                          </span>
                          <ArrowUpLeft size={16} />
                        </button>
                      ))}
                  </div>
                ) : (
                  <div className="calm-state">
                    <span>
                      <CalendarCheck2 size={28} />
                    </span>
                    <h3>درخواست بازی ندارید</h3>
                    <p>
                      درخواست‌های مراجعه‌کنندگان برای همراهی انسانی، اینجا قرار
                      می‌گیرند.
                    </p>
                  </div>
                )}
                {data.metrics.notifications_failed > 0 && (
                  <button
                    className="message-warning"
                    onClick={() => navigate("/notifications")}
                  >
                    <MessageSquareText size={19} />
                    <span>
                      {faNumber(data.metrics.notifications_failed)} پیام به
                      بررسی نیاز دارد
                    </span>
                    <ArrowUpLeft size={16} />
                  </button>
                )}
                <div className="panel-bottom-action">
                  <TextLink onClick={() => navigate("/tasks")}>
                    باز کردن فهرست پیگیری‌ها
                  </TextLink>
                </div>
              </section>
            </div>
            <section className="panel activity-panel">
              <SectionTitle
                title="آخرین فعالیت‌ها"
                description="رویدادهای ثبت‌شدهٔ مرکز"
              />
              {data.recent_activity.length ? (
                <div className="activity-list">
                  {data.recent_activity.slice(0, 4).map((event) => (
                    <div className="activity-row" key={event.id}>
                      <span className="activity-dot" />
                      <strong>{actionLabel(event.action)}</strong>
                      <span className="muted">
                        {event.entity_type === "appointment"
                          ? "نوبت"
                          : event.entity_type === "tenant"
                            ? "تنظیمات مرکز"
                            : "پذیرش"}
                      </span>
                      <time>{faDate(event.created_at, true)}</time>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="subtle-empty">
                  پس از نخستین اقدام، سابقهٔ فعالیت‌ها در این بخش نمایش داده
                  می‌شود.
                </p>
              )}
            </section>
          </div>
        )
      )}
    </>
  );
}
export function actionLabel(action: string) {
  const value = action.toLowerCase();
  if (value.includes("cancel")) return "لغو نوبت";
  if (value.includes("resched")) return "جابجایی نوبت";
  if (value.includes("appoint") || value.includes("booking"))
    return "ثبت یا به‌روزرسانی نوبت";
  if (value.includes("setting") || value.includes("policy"))
    return "به‌روزرسانی تنظیمات";
  if (value.includes("hold")) return "نگه‌داشتن موقت زمان";
  if (value.includes("task")) return "رسیدگی به درخواست";
  if (value.includes("consent")) return "ثبت انتخاب حریم خصوصی";
  return "رویداد پذیرش";
}
