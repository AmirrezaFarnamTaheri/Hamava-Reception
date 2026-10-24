import { useState, type FormEvent } from "react";
import {
  CheckCircle2,
  FilePenLine,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import { api, ApiError, errorText, faDate, faNumber, post } from "../api";
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
import { EvidenceFields } from "../Evidence";
import { useRemote } from "../hooks";

export const purposeNames: Record<string, string> = {
  processing: "پردازش ضروری پذیرش",
  recording: "ذخیرهٔ صدای گفت‌وگو",
  qa: "بازبینی کیفیت",
  marketing: "پیام‌های تبلیغاتی",
  training: "استفاده برای آموزش",
  cross_border: "پردازش خارج از کشور",
  memory: "یادآوری اطلاعات در گفت‌وگوی بعدی",
  reminder: "یادآوری نوبت",
  waitlist: "اطلاع فرصت فهرست انتظار",
  followup: "پیگیری پس از مراجعه",
};
interface PurposePolicy {
  purpose: string;
  version: number | null;
  enabled: boolean;
  notice: string | null;
  retention_days: number | null;
  backup_expiry_days: number | null;
  consent_valid_days: number | null;
}
interface PermissionResult {
  phone_masked: string;
  granted: boolean;
  purpose: string;
  expires_at: string;
  expiring_artifacts: number;
  ended_calls: number;
}

function PurposeEditor({
  initial,
  onClose,
  onSaved,
}: {
  initial: PurposePolicy;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    purpose: initial.purpose,
    enabled: initial.enabled,
    notice: initial.notice || "",
    retention_days: String(initial.retention_days ?? 0),
    backup_expiry_days: String(initial.backup_expiry_days ?? 30),
    consent_valid_days: String(initial.consent_valid_days ?? 30),
    evidence_reference: "",
  });
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  function update(key: keyof typeof form, value: string | boolean) {
    setForm((old) => ({ ...old, [key]: value }));
    setConfirmed(false);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/operations/privacy-controls/purposes", {
        method: "PUT",
        body: JSON.stringify({
          ...form,
          retention_days: Number(form.retention_days),
          backup_expiry_days: Number(form.backup_expiry_days),
          consent_valid_days: Number(form.consent_valid_days),
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
    <Dialog
      title={`قاعدهٔ ${purposeNames[initial.purpose]}`}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <Alert kind="info">
          انتشار این قاعده، رضایت مراجعه‌کننده نیست. انتخاب هر فرد باید جداگانه
          و با نسخهٔ جاری اطلاعیه ثبت شود.
        </Alert>
        <label className="check-field">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(event) => update("enabled", event.target.checked)}
          />
          <span>این کاربرد با رعایت مجوز مستقل فرد مجاز باشد.</span>
        </label>
        <Field
          label="متن اطلاعیه برای مراجعه‌کننده"
          hint="کاربرد داده، ضرورت، نحوهٔ انصراف و محدودیت نگهداری را روشن بیان کنید."
        >
          <textarea
            required
            minLength={20}
            maxLength={4000}
            rows={5}
            value={form.notice}
            onChange={(event) => update("notice", event.target.value)}
          />
        </Field>
        <div className="form-grid">
          <Field label="نگهداری دادهٔ این کاربرد (روز)">
            <input
              required
              type="number"
              min={0}
              max={365}
              value={form.retention_days}
              onChange={(event) => update("retention_days", event.target.value)}
            />
          </Field>
          <Field label="انقضای نسخهٔ پشتیبان (روز)">
            <input
              required
              type="number"
              min={1}
              max={365}
              value={form.backup_expiry_days}
              onChange={(event) =>
                update("backup_expiry_days", event.target.value)
              }
            />
          </Field>
          <Field label="اعتبار انتخاب فرد (روز)">
            <input
              required
              type="number"
              min={1}
              max={365}
              value={form.consent_valid_days}
              onChange={(event) =>
                update("consent_valid_days", event.target.value)
              }
            />
          </Field>
          <Field label="شناسهٔ مدرک تصمیم">
            <input
              required
              maxLength={160}
              dir="ltr"
              value={form.evidence_reference}
              onChange={(event) =>
                update("evidence_reference", event.target.value)
              }
            />
          </Field>
        </div>
        <p className="field-hint">
          انقضا، زمان مجاز نگهداری را تعیین می‌کند. پاک‌سازی در اجرای دوره‌ای
          انجام می‌شود و پایان مهلت به معنی تأیید حذف نسخهٔ پشتیبان نیست.
        </p>
        <label className="check-field">
          <input
            required
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            متن، کاربرد و مدت‌ها را بررسی کرده‌ام و انتشار نسخهٔ جدید را تأیید
            می‌کنم.
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>انتشار قاعده</Busy>
          </button>
          <button
            className="button secondary"
            type="button"
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

function PermissionEditor({
  policies,
  onClose,
  onRefresh,
}: {
  policies: PurposePolicy[];
  onClose: () => void;
  onRefresh: () => void;
}) {
  const [phone, setPhone] = useState(""),
    [purpose, setPurpose] = useState(""),
    [choice, setChoice] = useState("");
  const [method, setMethod] = useState(""),
    [reference, setReference] = useState(""),
    [hash, setHash] = useState("");
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [stale, setStale] = useState(false),
    [result, setResult] = useState<PermissionResult | null>(null);
  const policy = policies.find((row) => row.purpose === purpose);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!policy?.version || !choice) return;
    setBusy(true);
    setError("");
    try {
      setResult(
        await post<PermissionResult>(
          "/operations/privacy-controls/permissions",
          {
            phone,
            purpose,
            granted: choice === "grant",
            policy_version: policy.version,
            method,
            evidence_reference: reference,
            evidence_sha256: hash,
            subject_request_confirmed: confirmed,
          },
        ),
      );
    } catch (error) {
      setError(errorText(error));
      if (
        error instanceof ApiError &&
        error.code === "PURPOSE_POLICY_CHANGED"
      ) {
        setStale(true);
        setConfirmed(false);
        setError(
          "نسخهٔ اطلاعیه تغییر کرده است. ابتدا قواعد را تازه کنید و انتخاب فرد را با متن جدید دوباره بررسی کنید.",
        );
      }
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="ثبت انتخاب مستقل مراجعه‌کننده"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      {result ? (
        <div className="modal-body">
          <div className="confirmation-icon">
            <CheckCircle2 size={32} />
          </div>
          <h3>
            {result.granted
              ? "اجازهٔ این کاربرد ثبت شد"
              : "انصراف از این کاربرد ثبت شد"}
          </h3>
          <p>
            {purposeNames[result.purpose]} · <bdi>{result.phone_masked}</bdi>
          </p>
          <p className="field-hint">
            اعتبار ثبت: تا {faDate(result.expires_at)}. این نتیجه فقط به همین
            کاربرد و مدرک ثبت‌شده مربوط است.
          </p>
          {!result.granted && (
            <p className="field-hint">
              {faNumber(result.expiring_artifacts)} مورد برای انقضا علامت‌گذاری
              شد و {faNumber(result.ended_calls)} گفت‌وگوی فعال پایان یافت.
              پاک‌سازی داده در فرایند دوره‌ای انجام می‌شود.
            </p>
          )}
          <button className="button primary" onClick={onClose}>
            بستن
          </button>
        </div>
      ) : (
        <form className="modal-body" onSubmit={submit}>
          <p className="field-hint">
            فقط درخواست واقعی و احراز‌شدهٔ فرد را ثبت کنید. این فرم اجازهٔ یک
            کاربرد را به کاربردهای دیگر تعمیم نمی‌دهد.
          </p>
          <Field label="شماره همراه مراجعه‌کننده">
            <input
              required
              type="tel"
              inputMode="tel"
              dir="ltr"
              maxLength={30}
              autoComplete="off"
              value={phone}
              onChange={(event) => {
                setPhone(event.target.value);
                setConfirmed(false);
              }}
            />
          </Field>
          <Field label="کاربرد مشخص">
            <select
              required
              value={purpose}
              onChange={(event) => {
                setPurpose(event.target.value);
                setChoice("");
                setConfirmed(false);
              }}
            >
              <option value="">انتخاب کاربرد</option>
              {policies
                .filter((row) => row.version !== null)
                .map((row) => (
                  <option key={row.purpose} value={row.purpose}>
                    {purposeNames[row.purpose]}
                  </option>
                ))}
            </select>
          </Field>
          {policy && (
            <section className="review-snapshot">
              <strong>اطلاعیهٔ نسخهٔ {faNumber(policy.version || 0)}</strong>
              <p>{policy.notice}</p>
              <small>
                اعتبار انتخاب {faNumber(policy.consent_valid_days || 0)} روز ·
                نگهداری {faNumber(policy.retention_days || 0)} روز
              </small>
            </section>
          )}
          <Field label="انتخاب صریح فرد">
            <select
              required
              value={choice}
              onChange={(event) => {
                setChoice(event.target.value);
                setConfirmed(false);
              }}
            >
              <option value="">انتخاب فرد را ثبت کنید</option>
              <option value="grant" disabled={!policy?.enabled}>
                اجازه می‌دهد
              </option>
              <option value="revoke">اجازه نمی‌دهد / انصراف می‌دهد</option>
            </select>
          </Field>
          {purpose === "processing" && choice === "revoke" && (
            <Alert kind="info">
              انصراف از پردازش ضروری، گفت‌وگوهای فعال این فرد را پایان می‌دهد و
              زمان‌های موقت نگه‌داشته‌شده آزاد می‌شوند. هماهنگی ادامهٔ کار با
              پذیرش ضروری است.
            </Alert>
          )}
          <Field label="روش احراز درخواست">
            <select
              required
              value={method}
              onChange={(event) => {
                setMethod(event.target.value);
                setConfirmed(false);
              }}
            >
              <option value="">انتخاب روش</option>
              <option value="signed_form">فرم امضاشده</option>
              <option value="recorded_verbal_request">
                درخواست شفاهی مستندشده
              </option>
              <option value="verified_subject_request">
                درخواست مستقیمِ احراز‌شده
              </option>
            </select>
          </Field>
          <EvidenceFields
            reference={reference}
            hash={hash}
            onReference={(value) => {
              setReference(value);
              setConfirmed(false);
            }}
            onHash={(value) => {
              setHash(value);
              setConfirmed(false);
            }}
            label="مدرک انتخاب فرد"
          />
          <label className="check-field">
            <input
              required
              type="checkbox"
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>
              هویت و درخواست واقعی فرد را برای همین کاربرد و همین اطلاعیه بررسی
              کرده‌ام.
            </span>
          </label>
          {error && <Alert>{error}</Alert>}
          {stale && (
            <button
              type="button"
              className="button secondary"
              onClick={onRefresh}
            >
              تازه‌کردن قواعد و بررسی دوباره
            </button>
          )}
          <div className="modal-actions">
            <button
              className="button primary"
              disabled={
                busy ||
                stale ||
                !confirmed ||
                !/^[a-f0-9]{64}$/.test(hash) ||
                !policy?.version
              }
            >
              <Busy busy={busy}>
                <UserCheck size={17} />
                ثبت انتخاب
              </Busy>
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
      )}
    </Dialog>
  );
}

export function PrivacyGovernance() {
  const policies = useRemote<PurposePolicy[]>(
    "/operations/privacy-controls/purposes",
  );
  const [editing, setEditing] = useState<PurposePolicy | null>(null),
    [permission, setPermission] = useState(false),
    [message, setMessage] = useState("");
  return (
    <>
      <section className="panel administration-intro">
        <div className="administration-symbol">
          <ShieldCheck size={25} />
        </div>
        <div>
          <h2>هر کاربرد، یک انتخاب مستقل</h2>
          <p>
            قاعدهٔ مرکز، مدرک تصمیم و درخواست واقعی فرد را جداگانه ثبت کنید.
            خاموش بودن یک کاربرد را به‌منزلهٔ داشتن مجوز فرض نکنید.
          </p>
        </div>
        <button
          className="button primary"
          disabled={!policies.data?.some((row) => row.version)}
          onClick={() => setPermission(true)}
        >
          <UserCheck size={18} />
          ثبت انتخاب فرد
        </button>
      </section>
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <section className="panel">
        <SectionTitle
          title="قواعد استفاده و نگهداری"
          description="انتشار هر تغییر یک نسخهٔ تازه می‌سازد. مجوز فرد باید به نسخهٔ جاری مربوط باشد."
        />
        {policies.error ? (
          <Retry error={policies.error} onRetry={policies.refresh} />
        ) : policies.loading ? (
          <Loading rows={4} />
        ) : (
          <div className="governance-grid">
            {policies.data?.map((row) => (
              <article className="governance-card" key={row.purpose}>
                <div className="card-heading">
                  <h3>{purposeNames[row.purpose] || row.purpose}</h3>
                  <Status
                    status={
                      row.version
                        ? row.enabled
                          ? "ACTIVE"
                          : "DISABLED"
                        : "DRAFT"
                    }
                    label={
                      row.version
                        ? row.enabled
                          ? "مجاز با رضایت"
                          : "غیرفعال"
                        : "منتشر نشده"
                    }
                  />
                </div>
                <p>
                  {row.notice ||
                    "برای این کاربرد هنوز قاعده‌ای منتشر نشده است."}
                </p>
                {row.version && (
                  <dl className="compact-facts">
                    <div>
                      <dt>نسخه</dt>
                      <dd>{faNumber(row.version)}</dd>
                    </div>
                    <div>
                      <dt>نگهداری</dt>
                      <dd>{faNumber(row.retention_days || 0)} روز</dd>
                    </div>
                    <div>
                      <dt>اعتبار انتخاب</dt>
                      <dd>{faNumber(row.consent_valid_days || 0)} روز</dd>
                    </div>
                  </dl>
                )}
                <button
                  className="button secondary small"
                  onClick={() => setEditing(row)}
                >
                  <FilePenLine size={16} />
                  {row.version ? "بازبینی قاعده" : "تنظیم قاعده"}
                </button>
              </article>
            ))}
          </div>
        )}
      </section>
      {editing && (
        <PurposeEditor
          initial={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            policies.refresh();
            setMessage(
              "نسخهٔ جدید قاعده منتشر شد. ثبت انتخاب افراد همچنان به درخواست مستقل آن‌ها نیاز دارد.",
            );
          }}
        />
      )}
      {permission && policies.data && (
        <PermissionEditor
          policies={policies.data}
          onClose={() => setPermission(false)}
          onRefresh={() => {
            setPermission(false);
            policies.refresh();
          }}
        />
      )}
    </>
  );
}
