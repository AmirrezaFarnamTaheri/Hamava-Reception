import { CatalogEvidence, ServicePolicyDialog } from "./CatalogPolicy";
import { useState, type FormEvent } from "react";
import { Edit3, Plus, Stethoscope, X } from "lucide-react";
import { api, errorText, faNumber, post } from "../api";
import {
  Alert,
  Busy,
  Dialog,
  Empty,
  Field,
  Loading,
  Retry,
  SectionTitle,
  Status,
} from "../components";
import { useRemote } from "../hooks";
import type { Clinic, Practitioner, Service } from "../types";

export function CreateClinic({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (id: string) => Promise<void>;
}) {
  const [form, setForm] = useState({
    name: "",
    slug: "",
    phone: "",
    address: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const clinic = await post<Clinic>("/clinics", form);
      await onCreated(clinic.id);
      onClose();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="راه‌اندازی مرکز جدید"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <p className="muted">
          اطلاعات هر مرکز جدا نگه داشته می‌شود. پس از ایجاد، ساعت کاری، پزشکان و
          خدمات را تنظیم کنید.
        </p>
        <Field label="نام مرکز">
          <input
            required
            minLength={2}
            maxLength={160}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </Field>
        <Field
          label="نشانی کوتاه پذیرش آنلاین"
          hint="فقط حروف کوچک انگلیسی، عدد و خط تیره؛ مانند bahar-clinic"
        >
          <input
            required
            dir="ltr"
            minLength={3}
            maxLength={60}
            pattern="[a-z0-9]+(-[a-z0-9]+)*"
            value={form.slug}
            onChange={(e) => setForm({ ...form, slug: e.target.value })}
            placeholder="bahar-clinic"
          />
        </Field>
        <Field label="تلفن مرکز">
          <input
            type="tel"
            dir="ltr"
            maxLength={40}
            value={form.phone}
            onChange={(e) => setForm({ ...form, phone: e.target.value })}
          />
        </Field>
        <Field label="نشانی">
          <textarea
            rows={2}
            maxLength={500}
            value={form.address}
            onChange={(e) => setForm({ ...form, address: e.target.value })}
          />
        </Field>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy}>
            <Busy busy={busy}>ایجاد و ورود به مرکز</Busy>
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={onClose}
          >
            بازگشت
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function PractitionerForm({
  initial,
  onClose,
  onSaved,
}: {
  initial?: Practitioner;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    name: initial?.name || "",
    specialty: initial?.specialty || "",
    active: initial?.active ?? true,
  });
  const [customHours, setCustomHours] = useState(
    initial?.working_hours != null,
  );
  const [hours, setHours] = useState<Record<string, string[][]>>(
    initial?.working_hours || {},
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(initial ? `/practitioners/${initial.id}` : "/practitioners", {
        method: initial ? "PUT" : "POST",
        body: JSON.stringify({
          ...form,
          working_hours: customHours ? hours : null,
        }),
      });
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={initial ? "ویرایش پزشک یا همکار" : "افزودن پزشک یا همکار"}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <Field label="نام نمایشی">
          <input
            required
            minLength={2}
            maxLength={160}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </Field>
        <Field label="تخصص یا نقش">
          <input
            maxLength={100}
            value={form.specialty}
            onChange={(e) => setForm({ ...form, specialty: e.target.value })}
          />
        </Field>
        <label className="check-field">
          <input
            type="checkbox"
            checked={form.active}
            onChange={(e) => setForm({ ...form, active: e.target.checked })}
          />
          <span>برای هماهنگی نوبت فعال باشد.</span>
        </label>
        <label className="check-field">
          <input
            type="checkbox"
            checked={customHours}
            onChange={(event) => setCustomHours(event.target.checked)}
          />
          <span>برنامهٔ حضور اختصاصی داشته باشد.</span>
        </label>
        {customHours ? (
          <div className="shift-editor">
            <p className="field-hint">
              روز بدون بازه، روز بدون حضور است. بازه‌ها باید به ترتیب و بدون
              هم‌پوشانی باشند. تعطیلی‌ها و محدودیت‌های مرکز همچنان اعمال
              می‌شوند.
            </p>
            {[
              ["5", "شنبه"],
              ["6", "یکشنبه"],
              ["0", "دوشنبه"],
              ["1", "سه‌شنبه"],
              ["2", "چهارشنبه"],
              ["3", "پنجشنبه"],
              ["4", "جمعه"],
            ].map(([day, label]) => (
              <div className="shift-day" key={day}>
                <div className="shift-day-title">
                  <strong>{label}</strong>
                  <button
                    type="button"
                    className="mini-button"
                    disabled={(hours[day]?.length || 0) >= 8}
                    onClick={() =>
                      setHours({
                        ...hours,
                        [day]: [...(hours[day] || []), ["09:00", "13:00"]],
                      })
                    }
                  >
                    <Plus size={14} />
                    افزودن بازه
                  </button>
                </div>
                {hours[day]?.map((interval, index) => (
                  <div className="shift-interval" key={index}>
                    <Field label={`شروع ${label}، بازهٔ ${index + 1}`}>
                      <input
                        type="time"
                        required
                        value={interval[0]}
                        onChange={(event) =>
                          setHours({
                            ...hours,
                            [day]: hours[day].map((entry, i) =>
                              i === index
                                ? [event.target.value, entry[1]]
                                : entry,
                            ),
                          })
                        }
                      />
                    </Field>
                    <Field label={`پایان ${label}، بازهٔ ${index + 1}`}>
                      <input
                        type="time"
                        required
                        value={interval[1]}
                        onChange={(event) =>
                          setHours({
                            ...hours,
                            [day]: hours[day].map((entry, i) =>
                              i === index
                                ? [entry[0], event.target.value]
                                : entry,
                            ),
                          })
                        }
                      />
                    </Field>
                    <button
                      type="button"
                      className="icon-button danger-text"
                      aria-label={`حذف بازهٔ ${index + 1} ${label}`}
                      onClick={() =>
                        setHours({
                          ...hours,
                          [day]: hours[day].filter((_, i) => i !== index),
                        })
                      }
                    >
                      <X size={16} />
                    </button>
                  </div>
                ))}
                {!hours[day]?.length && (
                  <small className="muted">بدون حضور</small>
                )}
              </div>
            ))}
          </div>
        ) : (
          <p className="field-hint">
            برنامهٔ حضور از ساعت کاری مرکز پیروی می‌کند.
          </p>
        )}
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy}>
            <Busy busy={busy}>ذخیره</Busy>
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={onClose}
          >
            بازگشت
          </button>
        </div>
      </form>
    </Dialog>
  );
}

function ServiceForm({
  initial,
  providers,
  onClose,
  onSaved,
}: {
  initial?: Service;
  providers: Practitioner[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    name: initial?.name || "",
    description: initial?.description || "",
    provider_ids: initial?.provider_ids || [],
    resource_ids: initial?.resource_ids || [],
    duration_minutes: initial?.duration_minutes || 20,
    buffer_minutes: initial?.buffer_minutes || 0,
    price_toman: initial?.price_toman || 0,
    deposit_toman: initial?.deposit_toman || 0,
    requires_approval: initial?.requires_approval || false,
    active: initial?.active ?? true,
  });
  const [resources, setResources] = useState(form.resource_ids.join(", "));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const update = <K extends keyof typeof form>(
    key: K,
    value: (typeof form)[K],
  ) => setForm((old) => ({ ...old, [key]: value }));
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(initial ? `/services/${initial.id}` : "/services", {
        method: initial ? "PUT" : "POST",
        body: JSON.stringify({
          ...form,
          resource_ids: resources
            .split(/[,،\s]+/)
            .map((x) => x.trim())
            .filter(Boolean),
        }),
      });
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={initial ? "ویرایش خدمت" : "افزودن خدمت"}
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form className="modal-body" onSubmit={submit}>
        <Field label="نام خدمت">
          <input
            required
            minLength={2}
            maxLength={160}
            value={form.name}
            onChange={(e) => update("name", e.target.value)}
          />
        </Field>
        <Field label="توضیح تأییدشده">
          <textarea
            rows={2}
            maxLength={1000}
            value={form.description}
            onChange={(e) => update("description", e.target.value)}
          />
        </Field>
        <fieldset className="provider-checklist">
          <legend>ارائه‌دهندگان این خدمت</legend>
          {providers
            .filter((p) => p.active)
            .map((provider) => (
              <label key={provider.id} className="check-field">
                <input
                  type="checkbox"
                  checked={form.provider_ids.includes(provider.id)}
                  onChange={(e) =>
                    update(
                      "provider_ids",
                      e.target.checked
                        ? [...form.provider_ids, provider.id]
                        : form.provider_ids.filter((id) => id !== provider.id),
                    )
                  }
                />
                <span>{provider.name}</span>
              </label>
            ))}
        </fieldset>
        <div className="form-grid">
          <Field label="مدت نوبت (دقیقه)">
            <input
              required
              type="number"
              min="5"
              max="480"
              value={form.duration_minutes}
              onChange={(e) =>
                update("duration_minutes", Number(e.target.value))
              }
            />
          </Field>
          <Field label="فاصلهٔ آماده‌سازی پس از نوبت (دقیقه)">
            <input
              required
              type="number"
              min="0"
              max="120"
              value={form.buffer_minutes}
              onChange={(e) => update("buffer_minutes", Number(e.target.value))}
            />
          </Field>
          <Field label="هزینهٔ اعلام‌شده (تومان)">
            <input
              required
              type="number"
              min="0"
              max="1000000000"
              value={form.price_toman}
              onChange={(e) => update("price_toman", Number(e.target.value))}
            />
          </Field>
          <Field label="بیعانه (تومان)">
            <input
              required
              type="number"
              min="0"
              max={form.price_toman}
              value={form.deposit_toman}
              onChange={(e) => update("deposit_toman", Number(e.target.value))}
            />
          </Field>
        </div>
        <Field
          label="اتاق یا تجهیزات مشترک (اختیاری)"
          hint="برای جلوگیری از رزرو هم‌زمان، نام کوتاه یکسان وارد کنید؛ مانند room-1, chair-2"
        >
          <input
            dir="ltr"
            value={resources}
            onChange={(e) => setResources(e.target.value)}
            maxLength={1200}
          />
        </Field>
        <label className="check-field">
          <input
            type="checkbox"
            checked={form.requires_approval}
            onChange={(e) => update("requires_approval", e.target.checked)}
          />
          <span>هر نوبت به تأیید پذیرش نیاز دارد.</span>
        </label>
        <label className="check-field">
          <input
            type="checkbox"
            checked={form.active}
            onChange={(e) => update("active", e.target.checked)}
          />
          <span>این خدمت برای رزرو فعال باشد.</span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || form.provider_ids.length === 0}
          >
            <Busy busy={busy}>تأیید و انتشار خدمت</Busy>
          </button>
          <button
            type="button"
            className="button secondary"
            disabled={busy}
            onClick={onClose}
          >
            بازگشت
          </button>
        </div>
      </form>
    </Dialog>
  );
}

export function Catalog({
  canEdit,
  onChanged,
}: {
  canEdit: boolean;
  onChanged: () => void;
}) {
  const providers = useRemote<Practitioner[]>(
    canEdit ? "/practitioners?include_inactive=true" : "/practitioners",
  );
  const services = useRemote<Service[]>(
    canEdit ? "/services?include_inactive=true" : "/services",
  );
  const [provider, setProvider] = useState<Practitioner | "new" | null>(null);
  const [service, setService] = useState<Service | "new" | null>(null);
  const [policyService, setPolicyService] = useState<Service | null>(null);
  const [evidence, setEvidence] = useState<{
    type: string;
    id: string;
    name: string;
  } | null>(null);
  const [message, setMessage] = useState("");
  function saved() {
    setProvider(null);
    setService(null);
    setPolicyService(null);
    providers.refresh();
    services.refresh();
    onChanged();
    setMessage("فهرست مرکز به‌روزرسانی شد.");
  }
  return (
    <>
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <section className="panel catalog-panel">
        <SectionTitle
          title="پزشکان و همکاران"
          description="افرادی که زمان نوبت به آن‌ها اختصاص پیدا می‌کند."
          action={
            canEdit && (
              <button
                className="button primary small"
                onClick={() => setProvider("new")}
              >
                <Plus size={16} />
                افزودن
              </button>
            )
          }
        />
        {providers.error ? (
          <Retry error={providers.error} onRetry={providers.refresh} />
        ) : providers.loading ? (
          <Loading rows={2} />
        ) : providers.data?.length ? (
          <div className="catalog-providers">
            {providers.data.map((p) => (
              <div className="catalog-provider" key={p.id}>
                <span className="catalog-icon">
                  <Stethoscope size={22} />
                </span>
                <div>
                  <strong>{p.name}</strong>
                  <small>{p.specialty || "همکار مرکز"}</small>
                </div>
                <Status value={p.active ? "ACTIVE" : "CANCELED"} />
                <button
                  className="button quiet small"
                  onClick={() =>
                    setEvidence({
                      type: "practitioner",
                      id: p.id,
                      name: p.name,
                    })
                  }
                >
                  منبع و اعتبار
                </button>
                {canEdit && (
                  <button
                    className="icon-button"
                    aria-label={`ویرایش ${p.name}`}
                    onClick={() => setProvider(p)}
                  >
                    <Edit3 size={17} />
                  </button>
                )}
              </div>
            ))}
          </div>
        ) : (
          <Empty
            title="هنوز همکاری اضافه نشده"
            description="ابتدا پزشک یا ارائه‌دهندهٔ خدمت را اضافه کنید، سپس خدمات او را تعریف کنید."
          />
        )}
      </section>
      <section className="panel catalog-panel">
        <SectionTitle
          title="خدمات و قواعد نوبت"
          description="مدت، هزینه، بیعانه و تجهیزات هر خدمت را مشخص کنید."
          action={
            canEdit && (
              <button
                className="button primary small"
                disabled={!providers.data?.some((p) => p.active)}
                onClick={() => setService("new")}
              >
                <Plus size={16} />
                افزودن خدمت
              </button>
            )
          }
        />
        {services.error ? (
          <Retry error={services.error} onRetry={services.refresh} />
        ) : services.loading ? (
          <Loading rows={2} />
        ) : services.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
          >
            <table>
              <thead>
                <tr>
                  <th>خدمت</th>
                  <th>مدت و فاصله</th>
                  <th>هزینه</th>
                  <th>قواعد</th>
                  <th>اقدام</th>
                </tr>
              </thead>
              <tbody>
                {services.data.map((s) => (
                  <tr key={s.id}>
                    <td>
                      <strong>{s.name}</strong>
                      <small className="table-subline">
                        {s.provider_ids
                          .map(
                            (id) =>
                              providers.data?.find((p) => p.id === id)?.name,
                          )
                          .filter(Boolean)
                          .join("، ")}
                      </small>
                    </td>
                    <td>
                      {faNumber(s.duration_minutes)} دقیقه
                      <small className="table-subline">
                        {faNumber(s.buffer_minutes)} دقیقه آماده‌سازی
                      </small>
                    </td>
                    <td>
                      {faNumber(s.price_toman)} تومان
                      {s.deposit_toman > 0 && (
                        <small className="table-subline">
                          بیعانه: {faNumber(s.deposit_toman)}
                        </small>
                      )}
                    </td>
                    <td>
                      {s.requires_approval ? (
                        <Status value="PENDING_STAFF_APPROVAL" />
                      ) : (
                        <Status
                          value={s.active === false ? "CANCELED" : "ACTIVE"}
                        />
                      )}
                    </td>
                    <td>
                      <div className="inline-actions">
                        <button
                          className="button secondary small"
                          onClick={() => setPolicyService(s)}
                        >
                          شرایط مراجعه
                        </button>
                        <button
                          className="button quiet small"
                          onClick={() =>
                            setEvidence({
                              type: "service",
                              id: s.id,
                              name: s.name,
                            })
                          }
                        >
                          منبع و اعتبار
                        </button>
                        {canEdit && (
                          <button
                            className="icon-button"
                            aria-label={`ویرایش ${s.name}`}
                            onClick={() => setService(s)}
                          >
                            <Edit3 size={17} />
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="هنوز خدمتی تعریف نشده"
            description="خدمت، ارائه‌دهنده و مدت آن باید مشخص باشد تا زمان آزاد به مراجعه‌کننده پیشنهاد شود."
          />
        )}
      </section>
      {provider && (
        <PractitionerForm
          initial={provider === "new" ? undefined : provider}
          onClose={() => setProvider(null)}
          onSaved={saved}
        />
      )}
      {policyService && (
        <ServicePolicyDialog
          service={policyService}
          services={services.data || []}
          canEdit={canEdit}
          onClose={() => setPolicyService(null)}
          onSaved={saved}
        />
      )}
      {evidence && (
        <CatalogEvidence
          subjectType={evidence.type}
          subjectId={evidence.id}
          label={evidence.name}
          canEdit={canEdit}
          onClose={() => setEvidence(null)}
        />
      )}
      {service && (
        <ServiceForm
          initial={service === "new" ? undefined : service}
          providers={providers.data || []}
          onClose={() => setService(null)}
          onSaved={saved}
        />
      )}
    </>
  );
}
