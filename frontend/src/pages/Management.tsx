import { useState, type FormEvent } from "react";
import {
  Copy,
  KeyRound,
  Plus,
  ShieldCheck,
  Trash2,
  UserPlus,
} from "lucide-react";
import { api, errorText, faDate, faNumber, post } from "../api";
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

interface Pronunciation {
  written: string;
  asr_aliases: string[];
  spoken: string;
}
interface ClinicProfile {
  version: number;
  legal_operator: string;
  location_label: string;
  ownership_reference: string;
  brand_name: string;
  brand_color: string;
  pronunciation: Pronunciation[];
  published_at?: string | null;
}
function ProfileForm({
  initial,
  onSaved,
}: {
  initial: ClinicProfile;
  onSaved: () => void;
}) {
  const [form, setForm] = useState(initial);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  function update<K extends keyof ClinicProfile>(
    key: K,
    value: ClinicProfile[K],
  ) {
    setForm((old) => ({ ...old, [key]: value }));
    setApproved(false);
  }
  function pronunciation(index: number, changes: Partial<Pronunciation>) {
    update(
      "pronunciation",
      form.pronunciation.map((item, i) =>
        i === index ? { ...item, ...changes } : item,
      ),
    );
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/operations/profile", {
        method: "PUT",
        body: JSON.stringify({
          version: form.version,
          legal_operator: form.legal_operator,
          location_label: form.location_label,
          ownership_reference: form.ownership_reference,
          brand_name: form.brand_name,
          brand_color: form.brand_color,
          pronunciation: form.pronunciation.map((item) => ({
            ...item,
            asr_aliases: item.asr_aliases
              .map((alias) => alias.trim())
              .filter(Boolean),
          })),
          publication_approved: approved,
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
    <form className="settings-form" onSubmit={submit}>
      <section className="panel settings-panel">
        <SectionTitle
          title="هویت مرکز"
          description="هویت بهره‌بردار و نامی که در پذیرش آنلاین نمایش داده می‌شود."
        />
        <fieldset disabled={busy}>
          <div className="form-grid">
            <Field label="نام بهره‌بردار قانونی">
              <input
                maxLength={200}
                value={form.legal_operator}
                onChange={(e) => update("legal_operator", e.target.value)}
              />
            </Field>
            <Field label="نام شعبه یا محل">
              <input
                maxLength={200}
                value={form.location_label}
                onChange={(e) => update("location_label", e.target.value)}
              />
            </Field>
            <Field
              label="مرجع اختیار بهره‌برداری"
              hint="شماره یا عنوان قرارداد تأییدشده؛ اطلاعات محرمانه وارد نکنید."
            >
              <input
                maxLength={200}
                value={form.ownership_reference}
                onChange={(e) => update("ownership_reference", e.target.value)}
              />
            </Field>
            <Field label="نام نمایشی پذیرش">
              <input
                maxLength={160}
                value={form.brand_name}
                onChange={(e) => update("brand_name", e.target.value)}
              />
            </Field>
            <Field label="رنگ نشانهٔ مرکز">
              <input
                type="color"
                value={form.brand_color}
                onChange={(e) => update("brand_color", e.target.value)}
              />
            </Field>
          </div>
        </fieldset>
      </section>
      <section className="panel settings-panel">
        <SectionTitle
          title="تلفظ نام‌های مرکز"
          description="تلفظ با افزودن حرکت‌های فارسی اصلاح می‌شود؛ کلمه و معنی تغییر نمی‌کند."
          action={
            <button
              className="button secondary small"
              type="button"
              disabled={busy || form.pronunciation.length >= 100}
              onClick={() =>
                update("pronunciation", [
                  ...form.pronunciation,
                  { written: "", spoken: "", asr_aliases: [] },
                ])
              }
            >
              <Plus size={16} />
              افزودن نام
            </button>
          }
        />
        <fieldset disabled={busy}>
          {form.pronunciation.length ? (
            form.pronunciation.map((item, index) => (
              <div className="faq-editor" key={index}>
                <div className="faq-editor-top">
                  <strong>نام {faNumber(index + 1)}</strong>
                  <button
                    type="button"
                    className="icon-button danger-text"
                    aria-label={`حذف تلفظ ${index + 1}`}
                    onClick={() =>
                      update(
                        "pronunciation",
                        form.pronunciation.filter((_, i) => i !== index),
                      )
                    }
                  >
                    <Trash2 size={16} />
                  </button>
                </div>
                <div className="form-grid">
                  <Field label="نوشتار نام">
                    <input
                      required
                      maxLength={100}
                      value={item.written}
                      onChange={(e) =>
                        pronunciation(index, { written: e.target.value })
                      }
                      placeholder="فاطمی"
                    />
                  </Field>
                  <Field label="تلفظ با حرکت‌گذاری">
                    <input
                      required
                      maxLength={150}
                      value={item.spoken}
                      onChange={(e) =>
                        pronunciation(index, { spoken: e.target.value })
                      }
                      placeholder="فاطِمی"
                    />
                  </Field>
                </div>
                <Field
                  label="شکل‌های شنیداری احتمالی (اختیاری)"
                  hint="هر شکل را در یک خط بنویسید؛ حداکثر ۱۰ مورد."
                >
                  <textarea
                    rows={2}
                    maxLength={1010}
                    value={item.asr_aliases.join("\n")}
                    onChange={(e) =>
                      pronunciation(index, {
                        asr_aliases: e.target.value.split("\n"),
                      })
                    }
                  />
                </Field>
              </div>
            ))
          ) : (
            <p className="field-hint">
              تلفظ اختصاصی ثبت نشده است. از صدای پیکربندی‌شدهٔ سرویس استفاده
              می‌شود.
            </p>
          )}
        </fieldset>
      </section>
      <label className="check-field">
        <input
          required
          type="checkbox"
          checked={approved}
          onChange={(e) => setApproved(e.target.checked)}
        />
        <span>
          هویت، اختیار بهره‌برداری و تلفظ‌های واردشده را برای انتشار تأیید
          می‌کنم.
        </span>
      </label>
      {error && <Alert>{error}</Alert>}
      <div className="settings-save-bar">
        <small>انتشار، نسخهٔ قواعد پذیرش را نیز به‌روز می‌کند.</small>
        <button className="button primary" disabled={busy || !approved}>
          <Busy busy={busy}>تأیید و انتشار هویت</Busy>
        </button>
      </div>
    </form>
  );
}
export function ProfileSettings({ onChanged }: { onChanged: () => void }) {
  const result = useRemote<ClinicProfile>("/operations/profile");
  const [saved, setSaved] = useState(false);
  return (
    <>
      {saved && (
        <Alert kind="success" onClose={() => setSaved(false)}>
          هویت مرکز با موفقیت منتشر شد.
        </Alert>
      )}
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading ? (
        <Loading rows={4} />
      ) : (
        result.data && (
          <ProfileForm
            key={result.data.version}
            initial={result.data}
            onSaved={() => {
              result.refresh();
              onChanged();
              setSaved(true);
            }}
          />
        )
      )}
    </>
  );
}

interface Member {
  user_id: string;
  membership_id: string;
  name: string;
  email: string;
  role: string;
  active: boolean;
}
const roles: Record<string, string> = {
  owner: "مالک مرکز",
  admin: "مدیر",
  receptionist: "پذیرش",
  clinician: "پزشک یا درمانگر",
  partner: "همکار؛ فقط آمار تجمیعی",
  manager: "مدیر عملیات مرکز",
  coordinator: "هماهنگ‌کننده",
  billing: "امور مالی",
  technical: "مسئول فنی و اتصال‌ها",
};
function AddMember({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    email: "",
    name: "",
    role: "receptionist",
    initial_password: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/operations/team", {
        ...form,
        initial_password: form.initial_password || undefined,
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
      title="افزودن یا تغییر دسترسی همکار"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <Field label="نام همکار">
          <input
            required
            minLength={2}
            maxLength={160}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </Field>
        <Field label="ایمیل حساب">
          <input
            type="email"
            required
            dir="ltr"
            maxLength={254}
            autoComplete="off"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </Field>
        <Field label="نقش در این مرکز">
          <select
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value })}
          >
            {[
              "admin",
              "manager",
              "coordinator",
              "receptionist",
              "clinician",
              "billing",
              "technical",
              "partner",
            ].map((role) => (
              <option key={role} value={role}>
                {roles[role]}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label="گذرواژهٔ آغازین برای حساب جدید"
          hint="حداقل ۱۴ نویسه. برای حساب موجود، این فیلد را خالی بگذارید؛ رمز او تغییر نمی‌کند."
        >
          <input
            type="password"
            autoComplete="new-password"
            dir="ltr"
            minLength={14}
            maxLength={256}
            value={form.initial_password}
            onChange={(e) =>
              setForm({ ...form, initial_password: e.target.value })
            }
          />
        </Field>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy}>
            <Busy busy={busy}>ثبت دسترسی</Busy>
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

interface Credential {
  id: string;
  label: string;
  purpose: string;
  scopes: string[];
  active: boolean;
  expires_at: string;
  api_key?: string;
}
const scopes: Record<string, string> = {
  "summary:read": "آمار تجمیعی مرکز",
  "appointments:read": "زمان و وضعیت نوبت‌ها، بدون نام و تلفن",
  "voice_notes:write": "دریافت پیام صوتی با رضایت مراجعه‌کننده",
};
function AddCredential({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    label: "",
    purpose: "",
    scopes: ["summary:read"],
    expires_days: 30,
  });
  const [credential, setCredential] = useState<Credential | null>(null);
  const [approved, setApproved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      setCredential(await post<Credential>("/operations/partner-keys", form));
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function copy() {
    try {
      await navigator.clipboard.writeText(credential?.api_key || "");
      setCopied(true);
    } catch {
      setError(
        "کپی خودکار در این مرورگر در دسترس نیست. کلید را انتخاب و دستی کپی کنید.",
      );
    }
  }
  return (
    <Dialog
      title="مجوز اتصال همکار"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        {credential ? (
          <>
            <Alert kind="info">
              کلید فقط همین یک بار نمایش داده می‌شود. آن را از مسیر امن در
              اختیار مسئول مجاز بگذارید.
            </Alert>
            <Field label="کلید محرمانهٔ اتصال">
              <textarea
                readOnly
                dir="ltr"
                className="secret-value"
                rows={3}
                value={credential.api_key}
              />
            </Field>
            <div className="inline-actions">
              <button
                type="button"
                className="button secondary"
                onClick={() => void copy()}
              >
                <Copy size={16} />
                {copied ? "کپی شد" : "کپی کلید"}
              </button>
              <button
                type="button"
                className="button primary"
                onClick={onClose}
              >
                کلید را نگه داشتم؛ بستن
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="muted">
              این مجوز فقط برای همین مرکز و دامنهٔ انتخاب‌شده معتبر است. اتصال
              یک خدمت بیرونی باید جداگانه تأیید شود.
            </p>
            <Field label="نام همکار یا سامانه">
              <input
                required
                minLength={2}
                maxLength={100}
                value={form.label}
                onChange={(e) => setForm({ ...form, label: e.target.value })}
              />
            </Field>
            <Field label="هدف مجاز همکاری">
              <textarea
                required
                minLength={5}
                maxLength={250}
                rows={2}
                value={form.purpose}
                onChange={(e) => setForm({ ...form, purpose: e.target.value })}
              />
            </Field>
            <fieldset className="provider-checklist">
              <legend>دامنهٔ دسترسی</legend>
              {Object.entries(scopes).map(([id, label]) => (
                <label className="check-field" key={id}>
                  <input
                    type="checkbox"
                    checked={form.scopes.includes(id)}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        scopes: e.target.checked
                          ? [...form.scopes, id]
                          : form.scopes.filter((item) => item !== id),
                      })
                    }
                  />
                  <span>{label}</span>
                </label>
              ))}
            </fieldset>
            <Field label="اعتبار مجوز (روز)">
              <input
                type="number"
                min="1"
                max="90"
                required
                value={form.expires_days}
                onChange={(e) =>
                  setForm({ ...form, expires_days: Number(e.target.value) })
                }
              />
            </Field>
            <label className="check-field">
              <input
                type="checkbox"
                checked={approved}
                onChange={(e) => setApproved(e.target.checked)}
              />
              <span>دامنهٔ دسترسی و هدف همکاری را تأیید می‌کنم.</span>
            </label>
            <div className="modal-actions">
              <button
                className="button primary"
                disabled={busy || !approved || !form.scopes.length}
              >
                <Busy busy={busy}>صدور مجوز</Busy>
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
          </>
        )}
        {error && <Alert>{error}</Alert>}
      </form>
    </Dialog>
  );
}

export function AccessSettings() {
  const team = useRemote<Member[]>("/operations/team");
  const keys = useRemote<Credential[]>("/operations/partner-keys");
  const [adding, setAdding] = useState(false);
  const [addingKey, setAddingKey] = useState(false);
  const [revoke, setRevoke] = useState<{ path: string; name: string } | null>(
    null,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  async function revokeAccess() {
    if (!revoke) return;
    setBusy(true);
    setError("");
    try {
      await api(revoke.path, { method: "DELETE" });
      setRevoke(null);
      team.refresh();
      keys.refresh();
      setMessage("دسترسی انتخاب‌شده لغو شد.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
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
          title="اعضای تیم"
          description="دسترسی هر حساب فقط در محدودهٔ مرکز انتخاب‌شده اعمال می‌شود."
          action={
            <button
              className="button primary small"
              onClick={() => setAdding(true)}
            >
              <UserPlus size={16} />
              افزودن همکار
            </button>
          }
        />
        {team.error ? (
          <Retry error={team.error} onRetry={team.refresh} />
        ) : team.loading ? (
          <Loading rows={3} />
        ) : team.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
          >
            <table>
              <thead>
                <tr>
                  <th>همکار</th>
                  <th>نقش</th>
                  <th>وضعیت</th>
                  <th>اقدام</th>
                </tr>
              </thead>
              <tbody>
                {team.data.map((member) => (
                  <tr key={member.membership_id}>
                    <td>
                      <strong>{member.name}</strong>
                      <small className="table-subline ltr">
                        {member.email}
                      </small>
                    </td>
                    <td>{roles[member.role] || "همکار مرکز"}</td>
                    <td>
                      <Status value={member.active ? "ACTIVE" : "DISABLED"} />
                    </td>
                    <td>
                      {member.active && member.role !== "owner" && (
                        <button
                          className="button danger-quiet small"
                          onClick={() =>
                            setRevoke({
                              path: `/operations/team/${member.membership_id}`,
                              name: member.name,
                            })
                          }
                        >
                          لغو دسترسی
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="همکاری یافت نشد"
            description="پس از ثبت دسترسی، نام همکار اینجا نمایش داده می‌شود."
          />
        )}
      </section>
      <section className="panel catalog-panel">
        <SectionTitle
          title="مجوزهای اتصال بیرونی"
          description="مجوزهای محدود، قابل لغو و دارای تاریخ پایان برای سامانه‌های تأییدشده."
          action={
            <button
              className="button secondary small"
              onClick={() => setAddingKey(true)}
            >
              <KeyRound size={16} />
              مجوز جدید
            </button>
          }
        />
        {keys.error ? (
          <Retry error={keys.error} onRetry={keys.refresh} />
        ) : keys.loading ? (
          <Loading rows={2} />
        ) : keys.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
          >
            <table>
              <thead>
                <tr>
                  <th>همکار و هدف</th>
                  <th>دسترسی</th>
                  <th>اعتبار</th>
                  <th>اقدام</th>
                </tr>
              </thead>
              <tbody>
                {keys.data.map((key) => (
                  <tr key={key.id}>
                    <td>
                      <strong>{key.label}</strong>
                      <small className="table-subline">{key.purpose}</small>
                    </td>
                    <td>
                      {key.scopes.map((scope) => (
                        <small key={scope} className="table-subline">
                          {scopes[scope] || "مجوز ثبت‌شده"}
                        </small>
                      ))}
                    </td>
                    <td>
                      <Status
                        value={
                          !key.active
                            ? "DISABLED"
                            : new Date(key.expires_at) <= new Date()
                              ? "EXPIRED"
                              : "ACTIVE"
                        }
                      />
                      <small className="table-subline">
                        {faDate(key.expires_at)}
                      </small>
                    </td>
                    <td>
                      {key.active && (
                        <button
                          className="button danger-quiet small"
                          onClick={() =>
                            setRevoke({
                              path: `/operations/partner-keys/${key.id}`,
                              name: key.label,
                            })
                          }
                        >
                          لغو مجوز
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="مجوز فعالی صادر نشده"
            description="در صورت نیاز، برای همکار مورد تأیید مجوز با دسترسی محدود بسازید."
          />
        )}
      </section>
      <div className="note-line">
        <ShieldCheck size={18} />
        <span>
          نام یا آدرس یک پلتفرم، به‌تنهایی نشان‌دهندهٔ قرارداد یا اتصال فعال
          نیست. اعتبار همکاری باید توسط مرکز تأیید شود.
        </span>
      </div>
      {adding && (
        <AddMember
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            team.refresh();
            setMessage("دسترسی همکار ثبت شد.");
          }}
        />
      )}
      {addingKey && (
        <AddCredential
          onClose={() => setAddingKey(false)}
          onSaved={keys.refresh}
        />
      )}
      {revoke && (
        <Dialog
          title="لغو دسترسی"
          onClose={() => {
            if (!busy) setRevoke(null);
          }}
        >
          <div className="modal-body">
            <p>
              دسترسی «{revoke.name}» به این مرکز متوقف می‌شود. آیا ادامه
              می‌دهید؟
            </p>
            {error && <Alert>{error}</Alert>}
            <div className="modal-actions">
              <button
                className="button danger"
                disabled={busy}
                onClick={() => void revokeAccess()}
              >
                <Busy busy={busy}>تأیید لغو دسترسی</Busy>
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => setRevoke(null)}
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
