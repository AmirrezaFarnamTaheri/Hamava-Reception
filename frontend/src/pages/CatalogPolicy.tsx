import { useState, type FormEvent } from "react";
import { BookOpen, FileCheck2, Save } from "lucide-react";
import { api, errorText, faDate, faNumber, post } from "../api";
import {
  Alert,
  Busy,
  Dialog,
  Field,
  Loading,
  Retry,
  SectionTitle,
  Status,
} from "../components";
import { useRemote } from "../hooks";
import type { Service } from "../types";

interface ServiceRule {
  service_id: string;
  version: number;
  preparation: string;
  insurance_notes: string;
  visit_policy: string;
  prerequisite_service_id: string | null;
  follow_up_days: number;
  package_units: number;
  max_series: number;
}
interface Fact {
  id: string;
  subject_type: string;
  subject_id: string;
  field: string;
  version: number;
  value: unknown;
  source: string;
  effective_at: string;
  expires_at: string;
  current: boolean;
}
const toIso = (value: string) => new Date(value + ":00+03:30").toISOString();
const fieldNames: Record<string, string> = {
  name: "نام",
  address: "نشانی",
  phone: "شماره تماس",
  website: "وب‌سایت",
  working_hours: "برنامهٔ کاری",
  holidays: "تعطیلی‌ها",
  lead_time_minutes: "فاصله تا نوبت",
  booking_horizon_days: "افق رزرو",
  cancellation_notice_hours: "مهلت لغو",
  specialty: "حوزهٔ خدمت",
  active: "وضعیت فعالیت",
  description: "شرح خدمت",
  provider_ids: "ارائه‌دهندگان",
  resource_ids: "منابع مشترک",
  duration_minutes: "مدت خدمت",
  buffer_minutes: "فاصلهٔ بین نوبت‌ها",
  price_toman: "تعرفه",
  deposit_toman: "بیعانه",
  requires_approval: "نیاز به تأیید",
  preparation: "آمادگی قبل مراجعه",
  insurance_notes: "اطلاعات بیمه",
  visit_policy: "نوع مراجعه",
  prerequisite_service_id: "خدمت پیش‌نیاز",
  follow_up_days: "مهلت پیگیری",
  package_units: "جلسات بسته",
  max_series: "حداکثر رزرو متوالی",
};

function ServiceRuleForm({
  initial,
  services,
  canEdit,
  onSaved,
  onClose,
}: {
  initial: ServiceRule;
  services: Service[];
  canEdit: boolean;
  onSaved: () => void;
  onClose: () => void;
}) {
  const [form, setForm] = useState({
      ...initial,
      source: "",
      expires_at: "",
      reason: "",
    }),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const update = (key: string, value: string | number | null) => {
    setForm((old) => ({ ...old, [key]: value }));
    setConfirmed(false);
  };
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { service_id, ...body } = form;
      await api(`/services/${encodeURIComponent(service_id)}/policy`, {
        method: "PUT",
        body: JSON.stringify({
          ...body,
          package_units:
            form.visit_policy === "package" ? Number(form.package_units) : 0,
          expires_at: toIso(form.expires_at),
        }),
      });
      onSaved();
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="modal-body" onSubmit={submit}>
      <p className="field-hint">
        اطلاعات اداری تأییدشدهٔ خدمت را ثبت کنید. توصیهٔ پزشکی شخصی در این بخش
        نوشته نمی‌شود.
      </p>
      <fieldset disabled={!canEdit || busy} className="plain-fieldset">
        <Field label="آمادگی قبل از مراجعه">
          <textarea
            rows={3}
            maxLength={2000}
            value={form.preparation}
            onChange={(event) => update("preparation", event.target.value)}
          />
        </Field>
        <Field label="اطلاعات اداری بیمه">
          <textarea
            rows={3}
            maxLength={2000}
            value={form.insurance_notes}
            onChange={(event) => update("insurance_notes", event.target.value)}
          />
        </Field>
        <div className="form-grid">
          <Field label="نوع مراجعهٔ مجاز">
            <select
              value={form.visit_policy}
              onChange={(event) => update("visit_policy", event.target.value)}
            >
              <option value="any">همهٔ مراجعه‌ها</option>
              <option value="first_visit">مراجعهٔ اول</option>
              <option value="follow_up">مراجعهٔ پیگیری</option>
              <option value="package">جلسه از بستهٔ خدمات</option>
            </select>
          </Field>
          <Field label="خدمت پیش‌نیاز">
            <select
              value={form.prerequisite_service_id || ""}
              onChange={(event) =>
                update("prerequisite_service_id", event.target.value || null)
              }
            >
              <option value="">بدون پیش‌نیاز</option>
              {services
                .filter((service) => service.id !== initial.service_id)
                .map((service) => (
                  <option key={service.id} value={service.id}>
                    {service.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="مهلت مراجعهٔ پیگیری (روز)">
            <input
              required
              type="number"
              min={1}
              max={730}
              value={form.follow_up_days}
              onChange={(event) =>
                update("follow_up_days", Number(event.target.value))
              }
            />
          </Field>
          <Field label="حداکثر نوبت در یک مجموعه">
            <input
              required
              type="number"
              min={1}
              max={12}
              value={form.max_series}
              onChange={(event) =>
                update("max_series", Number(event.target.value))
              }
            />
          </Field>
          {form.visit_policy === "package" && (
            <Field label="تعداد جلسهٔ بسته">
              <input
                required
                type="number"
                min={1}
                max={100}
                value={form.package_units || ""}
                onChange={(event) =>
                  update("package_units", Number(event.target.value))
                }
              />
            </Field>
          )}
        </div>
        {canEdit && (
          <>
            <div className="form-divider" />
            <Field label="مرجع تأیید این اطلاعات">
              <input
                required
                minLength={3}
                maxLength={500}
                value={form.source}
                onChange={(event) => update("source", event.target.value)}
              />
            </Field>
            <Field label="اعتبار اطلاعات تا؛ به وقت تهران">
              <input
                required
                type="datetime-local"
                value={form.expires_at}
                onChange={(event) => update("expires_at", event.target.value)}
              />
            </Field>
            <Field label="دلیل انتشار نسخه">
              <textarea
                required
                rows={2}
                minLength={3}
                maxLength={500}
                value={form.reason}
                onChange={(event) => update("reason", event.target.value)}
              />
            </Field>
            <label className="check-field">
              <input
                required
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              <span>
                شرایط بالا با مرجع مرکز تطبیق داده شده و انتشار نسخهٔ تازه را
                تأیید می‌کنم.
              </span>
            </label>
          </>
        )}
      </fieldset>
      {error && <Alert>{error}</Alert>}
      <div className="modal-actions">
        {canEdit && (
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>
              <Save size={16} />
              انتشار شرایط خدمت
            </Busy>
          </button>
        )}
        <button
          type="button"
          className="button secondary"
          disabled={busy}
          onClick={onClose}
        >
          بستن
        </button>
      </div>
    </form>
  );
}

export function ServicePolicyDialog({
  service,
  services,
  canEdit,
  onClose,
  onSaved,
}: {
  service: Service;
  services: Service[];
  canEdit: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const policy = useRemote<ServiceRule>(
    `/services/${encodeURIComponent(service.id)}/policy`,
  );
  return (
    <Dialog title={`شرایط مراجعه · ${service.name}`} wide onClose={onClose}>
      {policy.error ? (
        <Retry error={policy.error} onRetry={policy.refresh} />
      ) : policy.loading || !policy.data ? (
        <Loading rows={4} />
      ) : (
        <ServiceRuleForm
          initial={policy.data}
          services={services}
          canEdit={canEdit}
          onSaved={onSaved}
          onClose={onClose}
        />
      )}
    </Dialog>
  );
}

export function CatalogEvidence({
  subjectType,
  subjectId,
  label,
  canEdit,
  onClose,
}: {
  subjectType: string;
  subjectId: string;
  label: string;
  canEdit: boolean;
  onClose: () => void;
}) {
  const facts = useRemote<Fact[]>(
    `/catalog/facts?subject_type=${encodeURIComponent(subjectType)}&subject_id=${encodeURIComponent(subjectId)}`,
  );
  const [selected, setSelected] = useState<string[]>([]),
    [source, setSource] = useState(""),
    [effective, setEffective] = useState(""),
    [expires, setExpires] = useState(""),
    [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const latest = new Map<string, Fact>();
  for (const fact of facts.data || [])
    if (!latest.has(fact.field)) latest.set(fact.field, fact);
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/catalog/facts/approve", {
        subject_type: subjectType,
        subject_id: subjectId,
        fields: selected,
        source,
        effective_at: toIso(effective),
        expires_at: toIso(expires),
        reason,
      });
      setSelected([]);
      setConfirmed(false);
      facts.refresh();
      setMessage("اعتبار فیلدهای انتخاب‌شده با منبع جدید ثبت شد.");
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={`منبع و اعتبار · ${label}`}
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form className="modal-body" onSubmit={submit}>
        <p className="field-hint">
          هر فیلد، نسخه و مرجع جداگانه دارد. تأیید مسئول مرکز جای بررسی مستقل
          محتوای پزشکی یا حقوقی را نمی‌گیرد.
        </p>
        {facts.error ? (
          <Retry error={facts.error} onRetry={facts.refresh} />
        ) : facts.loading ? (
          <Loading rows={3} />
        ) : (
          <div className="fact-review-list">
            {[...latest.values()].map((fact) => (
              <article key={fact.field}>
                <label className="check-field">
                  <input
                    type="checkbox"
                    disabled={!canEdit}
                    checked={selected.includes(fact.field)}
                    onChange={(event) => {
                      setSelected((old) =>
                        event.target.checked
                          ? [...old, fact.field]
                          : old.filter((field) => field !== fact.field),
                      );
                      setConfirmed(false);
                    }}
                  />
                  <span>{fieldNames[fact.field] || fact.field}</span>
                </label>
                <Status value={fact.current ? "ACTIVE" : "EXPIRED"} />
                <p>
                  {typeof fact.value === "object"
                    ? JSON.stringify(fact.value)
                    : typeof fact.value === "boolean"
                      ? fact.value
                        ? "بله"
                        : "خیر"
                      : String(fact.value ?? "—")}
                </p>
                <small>
                  {fact.source} · نسخهٔ {faNumber(fact.version)} · اعتبار تا{" "}
                  {faDate(fact.expires_at)}
                </small>
              </article>
            ))}
          </div>
        )}
        {canEdit && selected.length > 0 && (
          <>
            <h3>تأیید نسخهٔ جاری فیلدهای انتخاب‌شده</h3>
            <Field label="منبع تأیید">
              <input
                required
                minLength={3}
                maxLength={500}
                value={source}
                onChange={(event) => {
                  setSource(event.target.value);
                  setConfirmed(false);
                }}
              />
            </Field>
            <div className="form-grid">
              <Field label="شروع اعتبار به وقت تهران">
                <input
                  required
                  type="datetime-local"
                  value={effective}
                  onChange={(event) => {
                    setEffective(event.target.value);
                    setConfirmed(false);
                  }}
                />
              </Field>
              <Field label="پایان اعتبار به وقت تهران">
                <input
                  required
                  type="datetime-local"
                  value={expires}
                  onChange={(event) => {
                    setExpires(event.target.value);
                    setConfirmed(false);
                  }}
                />
              </Field>
            </div>
            <Field label="دلیل بازبینی">
              <input
                required
                minLength={3}
                maxLength={500}
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                  setConfirmed(false);
                }}
              />
            </Field>
            <label className="check-field">
              <input
                required
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              <span>
                مقدار فعلی فیلدهای انتخاب‌شده را با منبع بالا بررسی کرده‌ام.
              </span>
            </label>
          </>
        )}
        {error && <Alert>{error}</Alert>}
        {message && <Alert kind="success">{message}</Alert>}
        <div className="modal-actions">
          {canEdit && (
            <button
              className="button primary"
              disabled={busy || !confirmed || !selected.length}
            >
              <Busy busy={busy}>
                <FileCheck2 size={17} />
                ثبت اعتبار
              </Busy>
            </button>
          )}
          <button
            className="button secondary"
            type="button"
            disabled={busy}
            onClick={onClose}
          >
            بستن
          </button>
        </div>
      </form>
    </Dialog>
  );
}

interface CorePolicy {
  version: number;
  time_windows: Record<string, [number, number]>;
  catalog_provenance_required: boolean;
}
function CorePolicyForm({
  initial,
  canEdit,
  onSaved,
}: {
  initial: CorePolicy;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const [windows, setWindows] = useState(initial.time_windows),
    [provenance, setProvenance] = useState(initial.catalog_provenance_required),
    [reason, setReason] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/core-policy", {
        method: "PUT",
        body: JSON.stringify({
          version: initial.version,
          time_windows: windows,
          catalog_provenance_required: provenance,
          reason,
        }),
      });
      onSaved();
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="administration-panel-body" onSubmit={submit}>
      <fieldset className="plain-fieldset" disabled={!canEdit || busy}>
        <div className="time-window-grid">
          {Object.entries(windows).map(([name, bounds]) => (
            <div className="time-window-row" key={name}>
              <strong>{name}</strong>
              <Field label={`شروع ${name} (ساعت)`}>
                <input
                  required
                  type="number"
                  min={0}
                  max={23.75}
                  step={0.25}
                  value={bounds[0]}
                  onChange={(event) => {
                    setWindows((old) => ({
                      ...old,
                      [name]: [Number(event.target.value), bounds[1]],
                    }));
                    setConfirmed(false);
                  }}
                />
              </Field>
              <Field label={`پایان ${name} (ساعت)`}>
                <input
                  required
                  type="number"
                  min={0.25}
                  max={24}
                  step={0.25}
                  value={bounds[1]}
                  onChange={(event) => {
                    setWindows((old) => ({
                      ...old,
                      [name]: [bounds[0], Number(event.target.value)],
                    }));
                    setConfirmed(false);
                  }}
                />
              </Field>
            </div>
          ))}
        </div>
        <label className="check-field">
          <input
            type="checkbox"
            checked={provenance}
            onChange={(event) => {
              setProvenance(event.target.checked);
              setConfirmed(false);
            }}
          />
          <span>
            استفاده از دادهٔ مرکز فقط با مرجع معتبر و تأیید منقضی‌نشده مجاز
            باشد.
          </span>
        </label>
        <p className="field-hint">
          در محیط عملیاتی، الزام منبع معتبر قابل خاموش کردن نیست. پایان ۲۴ یعنی
          انتهای همان روز؛ نیم‌ساعت با ۰٫۵ و ربع ساعت با ۰٫۲۵ ثبت می‌شود.
        </p>
        {canEdit && (
          <>
            <Field label="دلیل تغییر قواعد">
              <input
                required
                minLength={3}
                maxLength={500}
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                  setConfirmed(false);
                }}
              />
            </Field>
            <label className="check-field">
              <input
                required
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              <span>بازه‌ها و الزام اعتبار داده را بررسی کرده‌ام.</span>
            </label>
          </>
        )}
      </fieldset>
      {error && <Alert>{error}</Alert>}
      {canEdit && (
        <button className="button primary" disabled={busy || !confirmed}>
          <Busy busy={busy}>
            <Save size={17} />
            انتشار قواعد گفت‌وگو
          </Busy>
        </button>
      )}
    </form>
  );
}
export function CoreConversationPolicy({ canEdit }: { canEdit: boolean }) {
  const policy = useRemote<CorePolicy>("/core-policy"),
    [message, setMessage] = useState("");
  return (
    <section className="panel">
      <SectionTitle
        title="معنای بازه‌های زمانی در گفت‌وگو"
        description="وقتی مراجعه‌کننده می‌گوید «صبح» یا «عصر»، زمان‌های داخل این محدوده پیشنهاد می‌شوند."
        action={<BookOpen size={22} />}
      />
      {message && <Alert kind="success">{message}</Alert>}
      {policy.error ? (
        <Retry error={policy.error} onRetry={policy.refresh} />
      ) : policy.loading || !policy.data ? (
        <Loading rows={3} />
      ) : (
        <CorePolicyForm
          key={policy.data.version}
          initial={policy.data}
          canEdit={canEdit}
          onSaved={() => {
            policy.refresh();
            setMessage("قواعد گفت‌وگو ذخیره شدند.");
          }}
        />
      )}
    </section>
  );
}
