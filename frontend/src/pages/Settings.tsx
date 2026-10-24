import { CoreConversationPolicy } from "./CatalogPolicy";
import { useEffect, useState, type FormEvent } from "react";
import {
  BookOpen,
  Check,
  Clock3,
  Download,
  ExternalLink,
  Link2,
  LockKeyhole,
  Plus,
  Save,
  Settings2,
  ShieldCheck,
  Trash2,
  Users,
} from "lucide-react";
import { api, errorText, faNumber, post } from "../api";
import {
  Alert,
  Busy,
  Dialog,
  Field,
  Loading,
  PageTitle,
  Retry,
  SectionTitle,
  Status,
} from "../components";
import { useRemote } from "../hooks";
import type { Faq, Settings, Practitioner, Service, User } from "../types";
import { hasPermission } from "../permissions";
import { publicUrl } from "../platform";
import { Catalog, CreateClinic } from "./Catalog";
import { ConsentRevocation } from "./ConsentRevocation";
import { AccessSettings, ProfileSettings } from "./Management";
import { Policies } from "./Policies";

type SaveFn = (changes: Partial<Settings>) => Promise<void>;
function SetupProgress({
  settings,
  onChoose,
}: {
  settings: Settings;
  onChoose: (section: string) => void;
}) {
  const practitioners = useRemote<Practitioner[]>("/practitioners");
  const services = useRemote<Service[]>("/services");
  if (practitioners.error || services.error)
    return (
      <Retry
        error={practitioners.error || services.error}
        onRetry={() => {
          practitioners.refresh();
          services.refresh();
        }}
      />
    );
  if (practitioners.loading || services.loading) return <Loading rows={1} />;
  const steps = [
    {
      label: "ساعت کاری مرکز",
      complete: Object.values(settings.working_hours).some(
        (shifts) => shifts.length > 0,
      ),
      section: "hours",
    },
    {
      label: "پزشک یا ارائه‌دهندهٔ فعال",
      complete: !!practitioners.data?.some((provider) => provider.active),
      section: "catalog",
    },
    {
      label: "خدمت قابل رزرو",
      complete: !!services.data?.length,
      section: "catalog",
    },
  ];
  if (steps.every((step) => step.complete)) return null;
  return (
    <section className="panel settings-panel">
      <SectionTitle
        title="پیش‌نویس راه‌اندازی مرکز"
        description="اطلاعات هر بخش ذخیره می‌شود؛ می‌توانید بعداً از همین‌جا ادامه دهید."
      />
      <div className="setup-steps">
        {steps.map((step) => (
          <div key={step.label}>
            <span>
              {step.complete ? <Check size={17} /> : <Clock3 size={17} />}
              {step.label}
            </span>
            {step.complete ? (
              <small>ثبت شده</small>
            ) : (
              <button
                type="button"
                className="mini-button"
                onClick={() => onChoose(step.section)}
              >
                تکمیل این بخش
              </button>
            )}
          </div>
        ))}
      </div>
      <p className="field-hint">
        پس از تکمیل این بخش‌ها، پاسخ‌های مرکز، اتصال‌ها و آمادگی راه‌اندازی را
        بازبینی کنید. فعال‌سازی دستیار تصمیم جداگانهٔ صاحب‌اختیار مرکز است.
      </p>
    </section>
  );
}
function General({
  settings,
  save,
  canEdit,
}: {
  settings: Settings;
  save: SaveFn;
  canEdit: boolean;
}) {
  const [form, setForm] = useState(settings);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const update = <K extends keyof Settings>(key: K, value: Settings[K]) => {
    setForm((old) => ({ ...old, [key]: value }));
    setSaved(false);
  };
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await save({
        name: form.name,
        address: form.address,
        phone: form.phone,
        website: form.website,
        mode: form.mode,
        lead_time_minutes: form.lead_time_minutes,
        booking_horizon_days: form.booking_horizon_days,
        cancellation_notice_hours: form.cancellation_notice_hours,
        monthly_minute_budget: form.monthly_minute_budget,
        retention_days: form.retention_days,
      });
      setSaved(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="settings-form" onSubmit={submit}>
      <section className="panel settings-panel">
        <SectionTitle
          title="اطلاعات مرکز"
          description="این اطلاعات در پذیرش آنلاین و پاسخ‌های دستیار استفاده می‌شوند."
        />
        <fieldset disabled={!canEdit || busy}>
          <div className="form-grid">
            <Field label="نام مرکز">
              <input
                required
                maxLength={140}
                value={form.name}
                onChange={(e) => update("name", e.target.value)}
              />
            </Field>
            <Field label="شمارهٔ تماس مرکز">
              <input
                type="tel"
                dir="ltr"
                value={form.phone}
                onChange={(e) => update("phone", e.target.value)}
                maxLength={25}
              />
            </Field>
          </div>
          <Field label="نشانی">
            <textarea
              rows={2}
              maxLength={500}
              value={form.address}
              onChange={(e) => update("address", e.target.value)}
            />
          </Field>
          <Field label="وب‌سایت (اختیاری)">
            <input
              type="url"
              dir="ltr"
              value={form.website || ""}
              onChange={(e) => update("website", e.target.value)}
              placeholder="https://"
            />
          </Field>
        </fieldset>
      </section>
      <section className="panel settings-panel">
        <SectionTitle
          title="روش پاسخ‌گویی"
          description="نقش دستیار را با شیوهٔ کار تیم پذیرش هماهنگ کنید."
        />
        <fieldset className="mode-options" disabled={!canEdit || busy}>
          {[
            [
              "after_hours",
              "پس از ساعت کاری",
              "دستیار در زمان تعطیلی مرکز پاسخ می‌دهد.",
            ],
            [
              "overflow",
              "تماس‌های بی‌پاسخ",
              "فقط پس از علامت مشغولی یا بی‌پاسخی خط؛ درخواست آنلاین به پذیرش ارجاع می‌شود.",
            ],
            [
              "human_primary",
              "ابتدا پذیرش انسانی",
              "درخواست برای تیم پذیرش ثبت می‌شود.",
            ],
            [
              "supervised",
              "دستیار با تأیید پذیرش",
              "نوبت‌های جدید با تأیید تیم قطعی می‌شوند؛ تغییر و لغو با پذیرش است.",
            ],
            [
              "paused",
              "توقف پاسخ‌گویی خودکار",
              "دستیار متوقف است و درخواست‌ها به تیم پذیرش سپرده می‌شوند.",
            ],
            [
              "ai_primary",
              "ابتدا دستیار",
              "گفت‌وگو با دستیار شروع می‌شود و در صورت نیاز ارجاع می‌شود.",
            ],
          ].map(([value, title, description]) => (
            <label
              key={value}
              className={`mode-option ${form.mode === value ? "selected" : ""}`}
            >
              <input
                type="radio"
                name="mode"
                value={value}
                checked={form.mode === value}
                onChange={() => update("mode", value)}
              />
              <span>
                <strong>{title}</strong>
                <small>{description}</small>
              </span>
              {form.mode === value && <Check size={18} />}
            </label>
          ))}
        </fieldset>
        <p className="field-hint">
          پاسخ‌گویی تلفنی به اتصال و مسیر‌دهی تأییدشدهٔ خط نیاز دارد. تغییر این
          گزینه به‌تنهایی خط تلفن را متصل نمی‌کند.
        </p>
      </section>
      <section className="panel settings-panel">
        <SectionTitle title="قواعد نوبت و مصرف" />
        <fieldset disabled={!canEdit || busy}>
          <div className="form-grid">
            <Field label="حداقل فاصله تا نوبت (دقیقه)">
              <input
                type="number"
                min="0"
                max="10080"
                value={form.lead_time_minutes}
                onChange={(e) =>
                  update("lead_time_minutes", Number(e.target.value))
                }
              />
            </Field>
            <Field label="بازهٔ قابل رزرو (روز)">
              <input
                type="number"
                min="1"
                max="365"
                value={form.booking_horizon_days}
                onChange={(e) =>
                  update("booking_horizon_days", Number(e.target.value))
                }
              />
            </Field>
            <Field label="مهلت لغو پیش از نوبت (ساعت)">
              <input
                type="number"
                min="0"
                max="720"
                value={form.cancellation_notice_hours}
                onChange={(e) =>
                  update("cancellation_notice_hours", Number(e.target.value))
                }
              />
            </Field>
            <Field label="سقف زمان ماهانه (دقیقه)">
              <input
                type="number"
                min="1"
                max="1000000"
                value={form.monthly_minute_budget}
                onChange={(e) =>
                  update("monthly_minute_budget", Number(e.target.value))
                }
              />
            </Field>
            <Field
              label="مدت نگهداری گفتگوها (روز)"
              hint="سیاست نگهداری مرکز باید با الزامات قراردادی و مجوز پردازش هماهنگ باشد."
            >
              <input
                type="number"
                min="1"
                max="365"
                value={form.retention_days}
                onChange={(e) =>
                  update("retention_days", Number(e.target.value))
                }
              />
            </Field>
          </div>
        </fieldset>
      </section>
      {error && <Alert>{error}</Alert>}
      {saved && <Alert kind="success">تنظیمات مرکز منتشر شد.</Alert>}
      <div className="settings-save-bar">
        <small>تغییرات با نسخهٔ جدید ثبت می‌شوند.</small>
        <button className="button primary" disabled={!canEdit || busy}>
          <Busy busy={busy}>
            <Save size={17} />
            ذخیره و انتشار
          </Busy>
        </button>
      </div>
    </form>
  );
}

const days: [string, string][] = [
  ["5", "شنبه"],
  ["6", "یکشنبه"],
  ["0", "دوشنبه"],
  ["1", "سه‌شنبه"],
  ["2", "چهارشنبه"],
  ["3", "پنجشنبه"],
  ["4", "جمعه"],
];
function Hours({
  settings,
  save,
  canEdit,
}: {
  settings: Settings;
  save: SaveFn;
  canEdit: boolean;
}) {
  const [hours, setHours] = useState(settings.working_hours);
  const [holidays, setHolidays] = useState(settings.holidays);
  const [quiet, setQuiet] = useState(
    Array.isArray(settings.quiet_hours)
      ? {
          start: settings.quiet_hours[0] || "21:00",
          end: settings.quiet_hours[1] || "08:00",
        }
      : settings.quiet_hours,
  );
  const [newHoliday, setNewHoliday] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  function change(day: string, index: number, part: number, value: string) {
    setHours((old) => ({
      ...old,
      [day]: old[day].map((interval, i) =>
        i === index
          ? interval.map((time, j) => (j === part ? value : time))
          : interval,
      ),
    }));
  }
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await save({ working_hours: hours, holidays, quiet_hours: quiet });
      setMessage("ساعت کاری و تعطیلی‌ها منتشر شدند.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="settings-form" onSubmit={submit}>
      <section className="panel settings-panel">
        <SectionTitle
          title="ساعت کاری هفتگی"
          description="ساعت‌ها به وقت تهران هستند. روز بدون بازه، تعطیل محسوب می‌شود."
        />
        <fieldset disabled={!canEdit || busy}>
          {days.map(([day, label]) => (
            <div className="hours-row" key={day}>
              <strong>{label}</strong>
              <div className="hours-intervals">
                {hours[day]?.length ? (
                  hours[day].map((interval, index) => (
                    <div className="hour-interval" key={index}>
                      <input
                        required
                        type="time"
                        aria-label={`شروع ${label} بازه ${index + 1}`}
                        value={interval[0]}
                        onChange={(e) => change(day, index, 0, e.target.value)}
                      />
                      <span>تا</span>
                      <input
                        required
                        type="time"
                        aria-label={`پایان ${label} بازه ${index + 1}`}
                        value={interval[1]}
                        onChange={(e) => change(day, index, 1, e.target.value)}
                      />
                      <button
                        type="button"
                        className="icon-button danger-text"
                        aria-label={`حذف بازه ${label}`}
                        onClick={() =>
                          setHours((old) => ({
                            ...old,
                            [day]: old[day].filter((_, i) => i !== index),
                          }))
                        }
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  ))
                ) : (
                  <span className="muted">تعطیل</span>
                )}
              </div>
              <button
                type="button"
                className="mini-button"
                disabled={(hours[day]?.length || 0) >= 3}
                onClick={() =>
                  setHours((old) => ({
                    ...old,
                    [day]: [...(old[day] || []), ["09:00", "13:00"]],
                  }))
                }
              >
                <Plus size={14} />
                بازه
              </button>
            </div>
          ))}
        </fieldset>
      </section>
      <section className="panel settings-panel">
        <SectionTitle
          title="تعطیلی‌های موردی"
          description="تاریخ‌ها با تقویم سیستم انتخاب و به‌عنوان روز محلی تهران ذخیره می‌شوند."
        />
        <fieldset disabled={!canEdit || busy}>
          <div className="holiday-add">
            <input
              type="date"
              aria-label="تاریخ تعطیلی"
              value={newHoliday}
              onChange={(e) => setNewHoliday(e.target.value)}
            />
            <button
              type="button"
              className="button secondary"
              disabled={!newHoliday || holidays.includes(newHoliday)}
              onClick={() => {
                setHolidays((old) => [...old, newHoliday].sort());
                setNewHoliday("");
              }}
            >
              <Plus size={16} />
              افزودن تعطیلی
            </button>
          </div>
          <div className="holiday-list">
            {holidays.map((date) => (
              <div className="holiday-tag" key={date}>
                <span>
                  {new Intl.DateTimeFormat("fa-IR", {
                    year: "numeric",
                    month: "long",
                    day: "numeric",
                  }).format(new Date(date + "T12:00:00Z"))}
                </span>
                <button
                  type="button"
                  className="icon-button"
                  aria-label={`حذف تعطیلی ${date}`}
                  onClick={() =>
                    setHolidays((old) => old.filter((d) => d !== date))
                  }
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
            {!holidays.length && (
              <p className="field-hint">تعطیلی موردی ثبت نشده است.</p>
            )}
          </div>
        </fieldset>
      </section>
      <section className="panel settings-panel">
        <SectionTitle
          title="ساعت آرامش مراجعان"
          description="یادآوری‌ها و پیشنهادهای زمان آزاد در این بازه ارسال نمی‌شوند."
        />
        <fieldset disabled={!canEdit || busy}>
          <div className="form-grid">
            <Field label="آغاز ساعت آرامش">
              <input
                required
                type="time"
                value={quiet.start}
                onChange={(e) =>
                  setQuiet((old) => ({ ...old, start: e.target.value }))
                }
              />
            </Field>
            <Field label="پایان ساعت آرامش">
              <input
                required
                type="time"
                value={quiet.end}
                onChange={(e) =>
                  setQuiet((old) => ({ ...old, end: e.target.value }))
                }
              />
            </Field>
          </div>
        </fieldset>
      </section>
      {error && <Alert>{error}</Alert>}
      {message && <Alert kind="success">{message}</Alert>}
      <div className="settings-save-bar">
        <small>تغییر ساعت کاری روی زمان‌های قابل پیشنهاد اثر می‌گذارد.</small>
        <button className="button primary" disabled={!canEdit || busy}>
          <Busy busy={busy}>ذخیره و انتشار</Busy>
        </button>
      </div>
    </form>
  );
}

function Knowledge({
  settings,
  save,
  canEdit,
}: {
  settings: Settings;
  save: SaveFn;
  canEdit: boolean;
}) {
  const [items, setItems] = useState<Faq[]>(settings.faq);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState(false);
  const update = (i: number, key: keyof Faq, value: string) => {
    setItems((old) =>
      old.map((item, index) =>
        i === index ? { ...item, [key]: value } : item,
      ),
    );
    setSuccess(false);
  };
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await save({
        faq: items.map((item) => ({
          question: item.question.trim(),
          answer: item.answer.trim(),
          category: item.category,
          source: item.source?.trim() || "سیاست تأییدشدهٔ مدیر مرکز",
          effective_at: item.effective_at || null,
          expires_at: item.expires_at || null,
          keywords: item.keywords || [],
        })),
      });
      setSuccess(true);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="settings-form" onSubmit={submit}>
      <section className="panel settings-panel">
        <SectionTitle
          title="پاسخ‌های تأییدشدهٔ مرکز"
          description="دستیار فقط بر پایهٔ اطلاعات تأییدشدهٔ شما پاسخ می‌دهد. اطلاعات نامطمئن را منتشر نکنید."
        />
        <fieldset disabled={!canEdit || busy}>
          <div className="faq-editor-list">
            {items.map((item, index) => (
              <div className="faq-editor" key={index}>
                <div className="faq-editor-top">
                  <span className="count-pill">{faNumber(index + 1)}</span>
                  <select
                    aria-label={`دستهٔ پاسخ ${index + 1}`}
                    value={item.category}
                    onChange={(e) => update(index, "category", e.target.value)}
                  >
                    <option value="general">اطلاعات عمومی</option>
                    <option value="hours">ساعت کاری</option>
                    <option value="price">هزینه</option>
                    <option value="insurance">بیمه</option>
                    <option value="preparation">آمادگی پیش از مراجعه</option>
                    <option value="address">نشانی و رفت‌وآمد</option>
                  </select>
                  <button
                    type="button"
                    className="icon-button danger-text"
                    aria-label={`حذف پاسخ ${index + 1}`}
                    onClick={() =>
                      setItems((old) => old.filter((_, i) => i !== index))
                    }
                  >
                    <Trash2 size={17} />
                  </button>
                </div>
                <Field label="پرسش">
                  <input
                    required
                    value={item.question}
                    maxLength={200}
                    onChange={(e) => update(index, "question", e.target.value)}
                  />
                </Field>
                <Field label="پاسخ کوتاه و روشن">
                  <textarea
                    required
                    value={item.answer}
                    maxLength={1000}
                    rows={3}
                    onChange={(e) => update(index, "answer", e.target.value)}
                  />
                </Field>
                <Field label="منبع اطلاعات تأییدشده">
                  <input
                    required
                    minLength={3}
                    maxLength={300}
                    value={item.source || "سیاست تأییدشدهٔ مدیر مرکز"}
                    onChange={(e) => update(index, "source", e.target.value)}
                  />
                </Field>
                <div className="form-grid">
                  <Field label="تاریخ آغاز اعتبار (اختیاری)">
                    <input
                      type="date"
                      value={item.effective_at?.slice(0, 10) || ""}
                      onChange={(e) =>
                        update(
                          index,
                          "effective_at",
                          e.target.value
                            ? `${e.target.value}T00:00:00+03:30`
                            : "",
                        )
                      }
                    />
                  </Field>
                  <Field label="تاریخ پایان اعتبار (اختیاری)">
                    <input
                      type="date"
                      value={item.expires_at?.slice(0, 10) || ""}
                      onChange={(e) =>
                        update(
                          index,
                          "expires_at",
                          e.target.value
                            ? `${e.target.value}T23:59:59+03:30`
                            : "",
                        )
                      }
                    />
                  </Field>
                </div>
              </div>
            ))}
          </div>
          <button
            type="button"
            className="button secondary"
            onClick={() =>
              setItems((old) => [
                ...old,
                { question: "", answer: "", category: "general" },
              ])
            }
          >
            <Plus size={17} />
            افزودن پرسش و پاسخ
          </button>
        </fieldset>
      </section>
      {error && <Alert>{error}</Alert>}
      {success && <Alert kind="success">پاسخ‌های تأییدشده منتشر شدند.</Alert>}
      <div className="settings-save-bar">
        <small>با انتشار، صحت و مجاز بودن این پاسخ‌ها را تأیید می‌کنید.</small>
        <button className="button primary" disabled={!canEdit || busy}>
          <Busy busy={busy}>تأیید و انتشار پاسخ‌ها</Busy>
        </button>
      </div>
    </form>
  );
}

interface Integration {
  id: string;
  name: string;
  configured: boolean;
  status?: string;
  description?: string;
}
interface IntegrationData {
  mode?: string;
  items: Integration[];
}
function Integrations() {
  const result = useRemote<IntegrationData>("/operations/integrations");
  return (
    <section className="panel settings-panel">
      <SectionTitle
        title="وضعیت اتصال سرویس‌ها"
        description="پیکربندی یک سرویس به معنای تأیید عملکرد آن در شبکهٔ واقعی نیست."
      />
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading ? (
        <Loading rows={4} />
      ) : (
        result.data && (
          <>
            <div className="integration-list">
              {result.data.items.map((item) => (
                <div className="integration-item" key={item.id}>
                  <span className="integration-icon">
                    <Link2 size={22} />
                  </span>
                  <div>
                    <h3>{item.name}</h3>
                    {item.description && <p>{item.description}</p>}
                  </div>
                  <Status
                    value={
                      item.status ||
                      (item.configured ? "configured" : "not_configured")
                    }
                  />
                </div>
              ))}
            </div>
            <Alert kind="info">
              کلیدها و اطلاعات اتصال را مسئول فنی مرکز در محیط سرویس تنظیم
              می‌کند. اطلاعات محرمانه در این صفحه نمایش داده نمی‌شوند.
            </Alert>
          </>
        )
      )}
    </section>
  );
}

interface PrivacyData {
  recording_default?: boolean;
  training_default?: boolean;
  retention_days?: number;
  processors?: { name: string; purpose: string; region: string }[];
}
function Privacy({
  settings,
  canEdit,
}: {
  settings: Settings;
  canEdit: boolean;
}) {
  const result = useRemote<PrivacyData>(canEdit ? "/operations/privacy" : null);
  const [phone, setPhone] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [revoking, setRevoking] = useState(false);
  async function action(kind: "export" | "delete") {
    setBusy(kind);
    setError("");
    setMessage("");
    try {
      const data = await post<Record<string, unknown>>(
        `/operations/privacy/${kind}`,
        {
          phone: phone.trim(),
          ...(kind === "delete" ? { confirm: true } : {}),
        },
      );
      if (kind === "export") {
        const blob = new Blob([JSON.stringify(data, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = "hamaava-personal-data.json";
        a.click();
        URL.revokeObjectURL(url);
        setMessage(
          "فایل اطلاعات مجاز آمادهٔ دریافت شد. آن را فقط در اختیار شخص مجاز قرار دهید.",
        );
      } else {
        setMessage(
          "درخواست حذف پردازش شد. نتیجه و استثناهای نگهداری در سابقهٔ سامانه ثبت می‌شوند.",
        );
        setConfirmDelete(false);
        setPhone("");
      }
      result.refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <section className="panel settings-panel">
        <SectionTitle
          title="حریم خصوصی مراجعان"
          description="خدمت‌رسانی، ضبط و آموزش مدل، انتخاب‌های مستقل هستند."
        />
        {result.error ? (
          <Retry error={result.error} onRetry={result.refresh} />
        ) : result.loading ? (
          <Loading rows={2} />
        ) : (
          <div className="privacy-policy-list">
            <div>
              <ShieldCheck size={22} />
              <span>
                <strong>ضبط صدا</strong>
                <small>
                  {result.data?.recording_default
                    ? "فقط مطابق انتخاب و مجوز ثبت‌شدهٔ مراجعه‌کننده"
                    : "ضبط بلندمدت به‌صورت پیش‌فرض خاموش است."}
                </small>
              </span>
              <Status
                value={result.data?.recording_default ? "PENDING" : "DISABLED"}
              />
            </div>
            <div>
              <LockKeyhole size={22} />
              <span>
                <strong>استفاده برای آموزش</strong>
                <small>به رضایت جداگانه و بررسی حقوق داده نیاز دارد.</small>
              </span>
              <span className="badge neutral">انتخاب مستقل</span>
            </div>
            <div>
              <Clock3 size={22} />
              <span>
                <strong>دورهٔ نگهداری تنظیم‌شده</strong>
                <small>
                  انقضا و استثناهای قانونی مطابق سیاست مرکز اعمال می‌شوند.
                </small>
              </span>
              <strong>
                {faNumber(
                  result.data?.retention_days ?? settings.retention_days,
                )}{" "}
                روز
              </strong>
            </div>
          </div>
        )}
        {!!result.data?.processors?.length && (
          <>
            <h3 className="subsection-heading">پردازشگران پیکربندی‌شده</h3>
            <div className="processor-list">
              {result.data.processors.map((p) => (
                <div key={p.name}>
                  <strong>{p.name}</strong>
                  <span>{p.purpose}</span>
                  <small>{p.region}</small>
                </div>
              ))}
            </div>
          </>
        )}
      </section>
      <section className="panel settings-panel">
        <SectionTitle
          title="انتخاب‌های اطلاع‌رسانی"
          description="درخواست انصراف از یادآوری، فهرست انتظار و پیام‌های اختیاری را ثبت کنید."
        />
        <p className="muted">
          این انتخاب، نوبت‌های موجود یا پیام‌های ضروری تأیید و لغو نوبت را تغییر
          نمی‌دهد.
        </p>
        <button
          className="button secondary"
          disabled={!canEdit}
          onClick={() => setRevoking(true)}
        >
          ثبت انصراف از پیام‌های اختیاری
        </button>
      </section>
      <section className="panel settings-panel">
        <SectionTitle
          title="درخواست دسترسی یا حذف"
          description="پیش از اقدام، هویت و اختیار درخواست‌کننده را خارج از این فرم بررسی کنید."
        />
        <div className="privacy-action-form">
          <Field label="شمارهٔ همراه شخص درخواست‌کننده">
            <input
              type="tel"
              inputMode="tel"
              dir="ltr"
              value={phone}
              maxLength={18}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="۰۹۱۲۱۲۳۴۵۶۷"
              disabled={!canEdit || !!busy}
            />
          </Field>
          <div className="privacy-actions">
            <button
              className="button secondary"
              disabled={!canEdit || !phone || !!busy}
              onClick={() => void action("export")}
            >
              <Busy busy={busy === "export"}>
                <Download size={17} />
                دریافت اطلاعات مجاز
              </Busy>
            </button>
            <button
              className="button danger-quiet"
              disabled={!canEdit || !phone || !!busy}
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 size={17} />
              درخواست حذف اطلاعات
            </button>
          </div>
        </div>
        {error && <Alert>{error}</Alert>}
        {message && <Alert kind="success">{message}</Alert>}
      </section>
      {revoking && (
        <ConsentRevocation
          onClose={() => setRevoking(false)}
          onSaved={result.refresh}
        />
      )}
      {confirmDelete && (
        <Dialog
          title="تأیید درخواست حذف"
          onClose={() => {
            if (!busy) setConfirmDelete(false);
          }}
        >
          <div className="modal-body">
            <p>
              این اقدام اطلاعات قابل حذفِ مرتبط با شمارهٔ واردشده را طبق سیاست
              مرکز پاک یا بی‌نام می‌کند. سوابق دارای الزام نگهداری ممکن است حفظ
              شوند.
            </p>
            <p>
              آیا هویت و اختیار درخواست‌کننده را بررسی کرده‌اید و می‌خواهید
              ادامه دهید؟
            </p>
            <div className="modal-actions">
              <button
                className="button danger"
                disabled={!!busy}
                onClick={() => void action("delete")}
              >
                <Busy busy={busy === "delete"}>تأیید و ادامهٔ حذف</Busy>
              </button>
              <button
                className="button secondary"
                disabled={!!busy}
                onClick={() => setConfirmDelete(false)}
              >
                بازگشت
              </button>
            </div>
          </div>
        </Dialog>
      )}
    </>
  );
}

import { OutreachSettings } from "./Outreach";
import { DigestDestinations } from "./DigestDestinations";
import { LaunchReadiness } from "./LaunchReadiness";
import { PaymentPolicySettings } from "./PaymentPolicy";

export function ClinicSettings({
  user,
  role,
  search,
  onCreated,
}: {
  user: User;
  role: string;
  search: string;
  onCreated: (id: string) => Promise<void>;
}) {
  const result = useRemote<Settings>("/settings");
  const [tab, setTab] = useState(
    () => new URLSearchParams(search).get("tab") || "general",
  );
  const [creating, setCreating] = useState(false);
  const canEdit = hasPermission(user, "policy:write");
  const save: SaveFn = async (changes) => {
    if (!result.data) return;
    await api("/settings", {
      method: "PUT",
      body: JSON.stringify({
        version: result.data.settings_version,
        ...changes,
      }),
    });
    result.refresh();
  };
  const tabs = [
    { id: "general", label: "اطلاعات و پذیرش", icon: Settings2 },
    { id: "hours", label: "ساعت کاری", icon: Clock3 },
    { id: "catalog", label: "پزشکان و خدمات", icon: Users },
    { id: "knowledge", label: "پاسخ‌های مرکز", icon: BookOpen },
    ...(hasPermission(user, "integration:read")
      ? [{ id: "integrations", label: "اتصال‌ها", icon: Link2 }]
      : []),
    ...(hasPermission(user, "privacy:manage")
      ? [{ id: "privacy", label: "حریم خصوصی", icon: ShieldCheck }]
      : []),
    { id: "outreach", label: "یادآوری و پیگیری", icon: Clock3 },
    { id: "payment", label: "شرایط مالی", icon: BookOpen },
    ...(canEdit
      ? [
          ...(["owner", "admin"].includes(role)
            ? [{ id: "profile", label: "هویت و تلفظ", icon: Settings2 }]
            : []),
          { id: "policies", label: "نسخه‌های قواعد", icon: BookOpen },
          ...(["owner", "admin"].includes(role)
            ? [{ id: "launch", label: "آمادگی راه‌اندازی", icon: ShieldCheck }]
            : []),
        ]
      : []),
    ...(role === "owner"
      ? [
          { id: "access", label: "تیم و همکاری", icon: Users },
          { id: "digest", label: "گزارش به مدیریت", icon: Clock3 },
        ]
      : []),
  ];
  useEffect(() => {
    const requested = new URLSearchParams(search).get("tab") || "general";
    setTab(tabs.some((item) => item.id === requested) ? requested : "general");
  }, [search, role]);
  function chooseTab(value: string) {
    setTab(value);
    history.replaceState({}, "", `/settings?tab=${encodeURIComponent(value)}`);
  }
  const activeTab = tabs.some((item) => item.id === tab) ? tab : "general";
  return (
    <>
      <PageTitle
        eyebrow="مرکز شما، قواعد شما"
        title="تنظیمات مرکز"
        description="اطلاعاتی که دستیار برای پاسخ‌گویی و هماهنگی نوبت به آن تکیه می‌کند."
        action={
          result.data && (
            <div className="inline-actions">
              {role === "owner" && (
                <button
                  className="button secondary"
                  onClick={() => setCreating(true)}
                >
                  <Plus size={16} />
                  افزودن مرکز
                </button>
              )}
              <a
                className="button secondary"
                href={publicUrl(`/talk/${result.data.slug}`)}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink size={17} />
                پذیرش آنلاین
              </a>
            </div>
          )
        }
      />
      {!canEdit && (
        <Alert kind="info">
          تنظیمات برای شما قابل مشاهده است. انتشار تغییرات به دسترسی مدیر مرکز
          نیاز دارد.
        </Alert>
      )}
      <label className="settings-mobile-chooser">
        <span>بخش تنظیمات</span>
        <select
          value={activeTab}
          onChange={(event) => chooseTab(event.target.value)}
        >
          {tabs.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
      </label>
      <div
        className="settings-tabs"
        role="tablist"
        aria-label="بخش تنظیمات"
        onKeyDown={(event) => {
          const current = tabs.findIndex((item) => item.id === tab);
          let next = current;
          if (event.key === "ArrowLeft") next = (current + 1) % tabs.length;
          else if (event.key === "ArrowRight")
            next = (current - 1 + tabs.length) % tabs.length;
          else if (event.key === "Home") next = 0;
          else if (event.key === "End") next = tabs.length - 1;
          else return;
          event.preventDefault();
          chooseTab(tabs[next].id);
          document.getElementById(`tab-${tabs[next].id}`)?.focus();
        }}
      >
        {tabs.map((item) => (
          <button
            key={item.id}
            role="tab"
            aria-selected={activeTab === item.id}
            aria-controls={
              activeTab === item.id ? `settings-${item.id}` : undefined
            }
            tabIndex={activeTab === item.id ? 0 : -1}
            id={`tab-${item.id}`}
            className={activeTab === item.id ? "active" : ""}
            onClick={() => chooseTab(item.id)}
          >
            <item.icon size={18} />
            {item.label}
          </button>
        ))}
      </div>
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading ? (
        <Loading rows={5} />
      ) : (
        result.data && (
          <div
            role="tabpanel"
            id={`settings-${activeTab}`}
            aria-labelledby={`tab-${activeTab}`}
          >
            <div key={`${result.data.id}-${activeTab}`}>
              {activeTab === "general" ? (
                <>
                  <SetupProgress settings={result.data} onChoose={chooseTab} />
                  <General
                    settings={result.data}
                    save={save}
                    canEdit={canEdit}
                  />
                </>
              ) : activeTab === "hours" ? (
                <>
                  <Hours settings={result.data} save={save} canEdit={canEdit} />
                  <CoreConversationPolicy canEdit={canEdit} />
                </>
              ) : activeTab === "catalog" ? (
                <Catalog
                  canEdit={hasPermission(user, "catalog:write")}
                  onChanged={result.refresh}
                />
              ) : activeTab === "knowledge" ? (
                <Knowledge
                  settings={result.data}
                  save={save}
                  canEdit={canEdit}
                />
              ) : activeTab === "integrations" ? (
                <Integrations />
              ) : activeTab === "profile" ? (
                <ProfileSettings onChanged={result.refresh} />
              ) : activeTab === "access" ? (
                <AccessSettings />
              ) : activeTab === "launch" ? (
                <LaunchReadiness />
              ) : activeTab === "payment" ? (
                <PaymentPolicySettings
                  canEdit={hasPermission(user, "billing:write")}
                />
              ) : activeTab === "digest" ? (
                <DigestDestinations />
              ) : activeTab === "outreach" ? (
                <OutreachSettings role={role} canEdit={canEdit} />
              ) : activeTab === "policies" ? (
                <Policies onChanged={result.refresh} />
              ) : (
                <Privacy settings={result.data} canEdit={canEdit} />
              )}
            </div>
          </div>
        )
      )}
      {creating && (
        <CreateClinic
          onClose={() => setCreating(false)}
          onCreated={onCreated}
        />
      )}
    </>
  );
}
