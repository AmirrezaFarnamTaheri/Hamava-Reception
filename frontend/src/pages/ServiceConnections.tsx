import { RoutingSettings } from "./Routing";
import { CalendarAuthority } from "./CalendarControl";
import { useState, type FormEvent } from "react";
import { FileCheck2, Link2, Plus, RefreshCw, ShieldCheck } from "lucide-react";
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
import { EvidenceFields } from "../Evidence";
import { useRemote } from "../hooks";
import { hasPermission } from "../permissions";
import type { User } from "../types";
import { purposeNames } from "./PrivacyGovernance";

interface Capability {
  provider_key: string;
  configured: boolean;
  version: number;
  kind: string | null;
  operations: string[];
  endpoint_version: string;
  model_version: string;
  region: string;
  data_terms_reference: string | null;
  verification_state: string;
  evidence_reference: string | null;
  expires_at: string | null;
  health: {
    status: string;
    code: string;
    checked_at: string | null;
    latency_ms: number | null;
  };
}
interface Processor {
  provider_key: string;
  version: number;
  enabled: boolean;
  purposes: string[];
  regions: string[];
  origin_region: string;
  retention_days: number;
  fallback_eligible: boolean;
  contract_reference: string;
  contract_sha256: string;
  expires_at: string;
}
const providers: Record<string, { label: string; kind: string }> = {
  speech_primary: { label: "گفتار اصلی", kind: "speech" },
  speech_fallback: { label: "گفتار جایگزین", kind: "speech" },
  calendar_primary: { label: "تقویم همکار", kind: "calendar" },
  telephony_primary: { label: "تماس زنده", kind: "telephony" },
  sms_kavenegar: { label: "پیامک کاوه‌نگار", kind: "sms" },
  digest_gateway: { label: "ارسال گزارش مدیریت", kind: "digest" },
  payment_primary: { label: "درگاه پرداخت", kind: "payment" },
};
const operationNames: Record<string, string> = {
  transcribe_final: "تشخیص گفتار نهایی",
  transcribe_partial: "تشخیص گفتار حین صحبت",
  keyterms: "واژگان اختصاصی",
  synthesize_wav: "ساخت پاسخ صوتی",
  synthesize_stream: "پخش تدریجی پاسخ",
  slots: "خواندن زمان‌های آزاد",
  get: "خواندن رزرو",
  hold: "نگه‌داشتن موقت زمان",
  release: "آزادکردن زمان",
  create: "ثبت رزرو",
  cancel: "لغو رزرو",
  update: "اصلاح رزرو",
  reconcile: "تطبیق رزروها",
  changes: "دریافت تغییرات",
  webhook: "رویدادهای همکار",
  start: "شروع تماس",
  send_audio: "ارسال صدا",
  interrupt: "قطع پاسخ هنگام صحبت",
  transfer: "انتقال تماس",
  hangup: "پایان تماس",
  send: "ارسال پیام",
  delivery: "رسید تحویل",
  inbound: "دریافت پاسخ",
  generate: "تهیهٔ گزارش",
  request: "درخواست پرداخت",
  verify: "بررسی نتیجهٔ پرداخت",
  refund_review: "بررسی بازپرداخت",
};
const operations: Record<string, string[]> = {
  speech: [
    "transcribe_final",
    "transcribe_partial",
    "keyterms",
    "synthesize_wav",
    "synthesize_stream",
  ],
  calendar: [
    "slots",
    "get",
    "hold",
    "release",
    "create",
    "cancel",
    "update",
    "reconcile",
    "changes",
    "webhook",
  ],
  telephony: ["start", "send_audio", "interrupt", "transfer", "hangup"],
  sms: ["send", "delivery", "inbound"],
  digest: ["generate"],
  payment: ["request", "verify", "refund_review"],
};
const healthNames: Record<string, string> = {
  healthy: "پاسخ سالم در آخرین بررسی",
  degraded: "نیازمند بررسی",
  stale: "بررسی قدیمی",
  unknown: "هنوز بررسی نشده",
  disabled: "پیکربندی نشده",
};
const localInput = (date: string | null) =>
  date
    ? new Intl.DateTimeFormat("sv-SE", {
        timeZone: "Asia/Tehran",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
        .format(new Date(date))
        .replace(" ", "T")
    : "";
const iso = (date: string) => new Date(date + ":00+03:30").toISOString();

function CapabilityEditor({
  item,
  onClose,
  onSaved,
}: {
  item: Capability;
  onClose: () => void;
  onSaved: () => void;
}) {
  const kind = providers[item.provider_key]?.kind || item.kind || "speech";
  const [selected, setSelected] = useState(item.operations),
    [endpoint, setEndpoint] = useState(
      item.version ? item.endpoint_version : "",
    ),
    [model, setModel] = useState(item.version ? item.model_version : "");
  const [region, setRegion] = useState(item.version ? item.region : ""),
    [terms, setTerms] = useState(item.data_terms_reference || ""),
    [evidence, setEvidence] = useState(""),
    [reason, setReason] = useState(""),
    [expires, setExpires] = useState(localInput(item.expires_at));
  const [attested, setAttested] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(
        `/operations/integration-capabilities/${encodeURIComponent(item.provider_key)}`,
        {
          method: "PUT",
          body: JSON.stringify({
            version: item.version,
            kind,
            operations: selected,
            endpoint_version: endpoint,
            model_version: model || "not_applicable",
            region,
            data_terms_reference: terms,
            verification_state: attested
              ? "operator_attested"
              : "declared_unverified",
            evidence_reference: evidence,
            expires_at: iso(expires),
            reason,
          }),
        },
      );
      onSaved();
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={`قابلیت‌های ${providers[item.provider_key]?.label || item.provider_key}`}
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form className="modal-body" onSubmit={submit}>
        <p className="field-hint">
          فقط قابلیت‌های آزموده‌شده یا اعلام‌شده در مدرک ارائه‌دهنده را انتخاب
          کنید. ذخیرهٔ یک اعلام اولیه، مجوز بهره‌برداری ایجاد نمی‌کند.
        </p>
        <fieldset className="choice-fieldset">
          <legend>قابلیت‌های مورد بررسی</legend>
          <div className="check-grid">
            {(operations[kind] || []).map((operation) => (
              <label className="check-field" key={operation}>
                <input
                  type="checkbox"
                  checked={selected.includes(operation)}
                  onChange={(event) => {
                    setAttested(false);
                    setSelected((old) =>
                      event.target.checked
                        ? [...old, operation]
                        : old.filter((value) => value !== operation),
                    );
                  }}
                />
                <span>{operationNames[operation]}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="form-grid">
          <Field label="نسخهٔ رابط ارائه‌دهنده">
            <input
              required
              maxLength={120}
              dir="ltr"
              value={endpoint}
              onChange={(event) => {
                setEndpoint(event.target.value);
                setAttested(false);
              }}
            />
          </Field>
          <Field label="نسخهٔ مدل؛ در صورت کاربرد">
            <input
              maxLength={120}
              dir="ltr"
              value={model}
              onChange={(event) => {
                setModel(event.target.value);
                setAttested(false);
              }}
            />
          </Field>
          <Field label="منطقهٔ پردازش">
            <input
              required
              minLength={2}
              maxLength={80}
              dir="ltr"
              value={region}
              onChange={(event) => {
                setRegion(event.target.value);
                setAttested(false);
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
                setAttested(false);
              }}
            />
          </Field>
          <Field label="مرجع شرایط داده">
            <input
              required
              minLength={3}
              maxLength={500}
              value={terms}
              onChange={(event) => {
                setTerms(event.target.value);
                setAttested(false);
              }}
            />
          </Field>
          <Field label="مرجع بررسی یا آزمون">
            <input
              required
              minLength={3}
              maxLength={500}
              value={evidence}
              onChange={(event) => {
                setEvidence(event.target.value);
                setAttested(false);
              }}
            />
          </Field>
        </div>
        <Field label="دلیل این تغییر">
          <textarea
            required
            minLength={3}
            maxLength={500}
            rows={2}
            value={reason}
            onChange={(event) => {
              setReason(event.target.value);
              setAttested(false);
            }}
          />
        </Field>
        <label className="check-field">
          <input
            type="checkbox"
            checked={attested}
            onChange={(event) => setAttested(event.target.checked)}
          />
          <span>
            قابلیت‌ها را با مدرک یا آزمون مشخص بررسی کرده‌ام و تأیید مسئول مرکز
            را ثبت می‌کنم.
          </span>
        </label>
        {!attested && (
          <p className="field-hint">
            با وضعیت «اعلام اولیه، تأیید نشده» ذخیره می‌شود.
          </p>
        )}
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || !selected.length}
          >
            <Busy busy={busy}>
              {attested ? "ثبت تأیید قابلیت‌ها" : "ثبت اعلام اولیه"}
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
    </Dialog>
  );
}

function ProcessorEditor({
  initial,
  onClose,
  onSaved,
}: {
  initial: Processor | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    provider_key: initial?.provider_key || "",
    enabled: initial?.enabled || false,
    purposes: initial?.purposes || ([] as string[]),
    regions: initial?.regions.join(", ") || "",
    origin_region: initial?.origin_region || "IR",
    retention_days: String(initial?.retention_days ?? 0),
    fallback_eligible: initial?.fallback_eligible || false,
    contract_reference: initial?.contract_reference || "",
    contract_sha256: "",
    expires_at: localInput(initial?.expires_at || null),
  });
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  function update<K extends keyof typeof form>(
    key: K,
    value: (typeof form)[K],
  ) {
    setForm((old) => ({ ...old, [key]: value }));
    setConfirmed(false);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/operations/privacy-controls/processors", {
        method: "PUT",
        body: JSON.stringify({
          ...form,
          regions: [...new Set(form.regions.split(/[,،\s]+/).filter(Boolean))],
          retention_days: Number(form.retention_days),
          expires_at: iso(form.expires_at),
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
      title="بررسی شرایط پردازشگر"
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form className="modal-body" onSubmit={submit}>
        <Alert kind="info">
          این ثبت، تأیید مسئول مرکز بر قرارداد بررسی‌شده است. وضعیت واقعی اتصال
          و پاسخ‌گویی سرویس جداگانه نمایش داده می‌شود.
        </Alert>
        <Field label="شناسهٔ پردازشگر" controlId="processor-key">
          <input
            id="processor-key"
            required
            readOnly={!!initial}
            dir="ltr"
            list="known-processors"
            maxLength={80}
            value={form.provider_key}
            onChange={(event) => update("provider_key", event.target.value)}
          />
          <datalist id="known-processors">
            {Object.entries(providers).map(([key, item]) => (
              <option value={key} key={key}>
                {item.label}
              </option>
            ))}
          </datalist>
        </Field>
        <label className="check-field">
          <input
            type="checkbox"
            checked={form.enabled}
            onChange={(event) => update("enabled", event.target.checked)}
          />
          <span>این پردازشگر در محدودهٔ شرایط زیر مجاز باشد.</span>
        </label>
        <fieldset className="choice-fieldset">
          <legend>کاربردهای مجاز</legend>
          <div className="check-grid">
            {Object.entries(purposeNames).map(([key, label]) => (
              <label className="check-field" key={key}>
                <input
                  type="checkbox"
                  checked={form.purposes.includes(key)}
                  onChange={(event) =>
                    update(
                      "purposes",
                      event.target.checked
                        ? [...form.purposes, key]
                        : form.purposes.filter((value) => value !== key),
                    )
                  }
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="form-grid">
          <Field
            label="منطقه‌های مجاز"
            hint="شناسه‌های توافق‌شده، با ویرگول؛ برای مثال IR"
          >
            <input
              required
              dir="ltr"
              value={form.regions}
              onChange={(event) => update("regions", event.target.value)}
            />
          </Field>
          <Field label="منطقهٔ مبدأ">
            <input
              required
              dir="ltr"
              minLength={2}
              maxLength={40}
              value={form.origin_region}
              onChange={(event) => update("origin_region", event.target.value)}
            />
          </Field>
          <Field label="نگهداری نزد پردازشگر (روز)">
            <input
              required
              type="number"
              min={0}
              max={365}
              value={form.retention_days}
              onChange={(event) => update("retention_days", event.target.value)}
            />
          </Field>
          <Field label="پایان اعتبار به وقت تهران">
            <input
              required
              type="datetime-local"
              value={form.expires_at}
              onChange={(event) => update("expires_at", event.target.value)}
            />
          </Field>
        </div>
        <label className="check-field">
          <input
            type="checkbox"
            checked={form.fallback_eligible}
            onChange={(event) =>
              update("fallback_eligible", event.target.checked)
            }
          />
          <span>
            در صورت اشکال سرویس اصلی، استفادهٔ جایگزین طبق همین قرارداد مجاز
            است.
          </span>
        </label>
        <EvidenceFields
          reference={form.contract_reference}
          hash={form.contract_sha256}
          onReference={(value) => update("contract_reference", value)}
          onHash={(value) => update("contract_sha256", value)}
          label="قرارداد بررسی‌شده"
        />
        <label className="check-field">
          <input
            required
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            کاربرد، منطقه، نگهداری و مهلت را با قرارداد این پردازشگر تطبیق
            داده‌ام.
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={
              busy ||
              !confirmed ||
              !form.purposes.length ||
              !/^[a-f0-9]{64}$/.test(form.contract_sha256)
            }
          >
            <Busy busy={busy}>ثبت نسخهٔ شرایط</Busy>
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

export function ServiceConnections({ user }: { user: User }) {
  const capabilities = useRemote<{ items: Capability[] }>(
    "/operations/integration-capabilities",
  );
  const processors = useRemote<Processor[]>(
    "/operations/privacy-controls/processors",
  );
  const [editing, setEditing] = useState<Capability | null>(null),
    [processor, setProcessor] = useState<Processor | "new" | null>(null);
  const [checking, setChecking] = useState(""),
    [error, setError] = useState(""),
    [message, setMessage] = useState("");
  const canWrite = hasPermission(user, "integration:write"),
    canApproveProcessor = canWrite && hasPermission(user, "privacy:manage");
  async function probe(item: Capability) {
    setChecking(item.provider_key);
    setError("");
    setMessage("");
    try {
      const result = await post<Capability>(
        `/operations/integration-capabilities/${encodeURIComponent(item.provider_key)}/probe`,
        {},
      );
      capabilities.refresh();
      setMessage(
        `${providers[item.provider_key]?.label || item.provider_key}: ${healthNames[result.health.status] || "بررسی انجام شد"}. این نتیجه، آزمون پذیرش تلفن یا پیامک واقعی نیست.`,
      );
    } catch (error) {
      setError(errorText(error));
    } finally {
      setChecking("");
    }
  }
  return (
    <>
      <section className="panel administration-intro">
        <div className="administration-symbol">
          <Link2 size={25} />
        </div>
        <div>
          <h2>وضعیت اتصال، با محدودهٔ روشن</h2>
          <p>
            پیکربندی، تأیید قابلیت و آخرین مشاهده سه وضعیت مستقل‌اند. اطلاعات
            محرمانهٔ اتصال در این صفحه نمایش یا دریافت نمی‌شود.
          </p>
        </div>
      </section>
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      {error && <Alert onClose={() => setError("")}>{error}</Alert>}
      <section className="panel">
        <SectionTitle
          title="سرویس‌های مرکز"
          description="بررسی سلامت فقط پاسخ همان سرویس را می‌سنجد؛ نتیجهٔ یک تماس یا تحویل واقعی پیام را تضمین نمی‌کند."
        />
        {capabilities.error ? (
          <Retry error={capabilities.error} onRetry={capabilities.refresh} />
        ) : capabilities.loading ? (
          <Loading rows={4} />
        ) : (
          <div className="governance-grid">
            {capabilities.data?.items.map((item) => {
              const expired =
                !!item.expires_at &&
                new Date(item.expires_at).getTime() <= Date.now();
              return (
                <article className="governance-card" key={item.provider_key}>
                  <div className="card-heading">
                    <h3>
                      {providers[item.provider_key]?.label || item.provider_key}
                    </h3>
                    <Status
                      status={item.configured ? "ACTIVE" : "DISABLED"}
                      label={item.configured ? "پیکربندی شده" : "پیکربندی نشده"}
                    />
                  </div>
                  <div className={`observed-state ${item.health.status}`}>
                    <span className="status-dot" />
                    <strong>
                      {healthNames[item.health.status] || "وضعیت نامشخص"}
                    </strong>
                  </div>
                  <p className="field-hint">
                    {item.health.checked_at
                      ? `آخرین مشاهده: ${faDate(item.health.checked_at, true)}`
                      : "هنوز مشاهده‌ای ثبت نشده است."}
                  </p>
                  <dl className="compact-facts">
                    <div>
                      <dt>تأیید قابلیت</dt>
                      <dd>
                        {expired
                          ? "منقضی شده"
                          : item.verification_state === "operator_attested"
                            ? "تأیید مسئول مرکز"
                            : item.verification_state === "declared_unverified"
                              ? "اعلام اولیه"
                              : "تأیید نشده"}
                      </dd>
                    </div>
                    <div>
                      <dt>نسخهٔ ثبت</dt>
                      <dd>{item.version ? faNumber(item.version) : "—"}</dd>
                    </div>
                  </dl>
                  {item.operations.length > 0 && (
                    <details className="compact-details">
                      <summary>قابلیت‌ها و اطلاعات سرویس</summary>
                      <ul>
                        {item.operations.map((operation) => (
                          <li key={operation}>
                            {operationNames[operation] || operation}
                          </li>
                        ))}
                      </ul>
                      <p>
                        منطقه: <bdi>{item.region}</bdi> · نسخهٔ رابط:{" "}
                        <bdi>{item.endpoint_version}</bdi>
                      </p>
                      {item.expires_at && (
                        <p>اعتبار تا {faDate(item.expires_at)}</p>
                      )}
                    </details>
                  )}
                  <div className="card-actions">
                    {canWrite && (
                      <button
                        className="button secondary small"
                        onClick={() => setEditing(item)}
                      >
                        <FileCheck2 size={16} />
                        بررسی قابلیت‌ها
                      </button>
                    )}
                    {canWrite &&
                      [
                        "speech_primary",
                        "speech_fallback",
                        "calendar_primary",
                        "digest_gateway",
                      ].includes(item.provider_key) && (
                        <button
                          className="button quiet small"
                          disabled={!!checking}
                          onClick={() => void probe(item)}
                        >
                          <Busy busy={checking === item.provider_key}>
                            <RefreshCw size={15} />
                            بررسی اتصال
                          </Busy>
                        </button>
                      )}
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </section>
      <section className="panel">
        <SectionTitle
          title="شرایط پردازشگران"
          description="مجوز مرکز برای کاربرد و منطقهٔ مشخص، همراه با قرارداد و تاریخ انقضا."
          action={
            canApproveProcessor && (
              <button
                className="button secondary small"
                onClick={() => setProcessor("new")}
              >
                <Plus size={16} />
                افزودن پردازشگر
              </button>
            )
          }
        />
        {processors.error ? (
          <Retry error={processors.error} onRetry={processors.refresh} />
        ) : processors.loading ? (
          <Loading rows={3} />
        ) : !processors.data?.length ? (
          <Empty
            title="هنوز قراردادی ثبت نشده"
            description="مسئول دارای اختیار حریم خصوصی و اتصال‌ها باید قرارداد هر پردازشگر را بررسی و ثبت کند."
          />
        ) : (
          <div className="administration-list">
            {processors.data.map((item) => (
              <article key={item.provider_key} className="administration-row">
                <span className="row-icon">
                  <ShieldCheck size={21} />
                </span>
                <div>
                  <h3>
                    {providers[item.provider_key]?.label || item.provider_key}
                  </h3>
                  <p>
                    {item.purposes
                      .map((purpose) => purposeNames[purpose] || purpose)
                      .join("، ")}
                  </p>
                  <small>
                    منطقه: <bdi>{item.regions.join(" · ")}</bdi> · نگهداری{" "}
                    {faNumber(item.retention_days)} روز · اعتبار تا{" "}
                    {faDate(item.expires_at)}
                  </small>
                </div>
                <Status
                  status={
                    item.enabled &&
                    new Date(item.expires_at).getTime() > Date.now()
                      ? "ACTIVE"
                      : "DISABLED"
                  }
                  label={
                    !item.enabled
                      ? "غیرفعال"
                      : new Date(item.expires_at).getTime() <= Date.now()
                        ? "منقضی"
                        : "تأیید قراردادی"
                  }
                />
                {canApproveProcessor && (
                  <button
                    className="button secondary small"
                    onClick={() => setProcessor(item)}
                  >
                    بازبینی
                  </button>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
      <CalendarAuthority canWrite={canWrite} />
      <RoutingSettings canEdit={hasPermission(user, "routing:write")} />
      {editing && (
        <CapabilityEditor
          item={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            capabilities.refresh();
            setMessage(
              "نسخهٔ قابلیت‌های سرویس ذخیره شد؛ آخرین مشاهدهٔ اتصال جداگانه گزارش می‌شود.",
            );
          }}
        />
      )}
      {processor && (
        <ProcessorEditor
          initial={processor === "new" ? null : processor}
          onClose={() => setProcessor(null)}
          onSaved={() => {
            setProcessor(null);
            processors.refresh();
            setMessage("نسخهٔ شرایط پردازشگر با مدرک بررسی‌شده ثبت شد.");
          }}
        />
      )}
    </>
  );
}
