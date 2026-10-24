import { useEffect, useState, type FormEvent } from "react";
import { FileCheck2, Plus, Save, ShieldCheck, Upload } from "lucide-react";
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
import { documentHash, EvidenceFields, exactToman } from "../Evidence";
import { useRemote } from "../hooks";

interface CostPolicy {
  version: number;
  enabled: boolean;
  monthly_cap_toman: number;
  call_cap_toman: number;
  operation_cap_toman: number;
  soft_percent: number;
  provider_caps_toman: Record<string, number>;
}
interface Rate {
  id: string;
  provider: string;
  meter: string;
  version: number;
  unit: string;
  currency: string;
  price_per_unit: string;
  fx_toman_per_currency: string;
  quantum: string;
  minimum_quantity: string;
  effective_at: string;
  expires_at: string;
  evidence_reference: string;
}
interface CostOverview {
  policy: CostPolicy | null;
  period: string;
  period_timezone: string;
  charged_micro_toman: number;
  reserved_micro_toman: number;
  exposure_micro_toman: number;
  charged_toman?: string;
  reserved_toman?: string;
  exposure_toman?: string;
  money_scale: number;
  unpriced_events: number;
  unknown_reservations: number;
  soft_limit_reached: boolean;
  rates: Rate[];
}
interface LedgerRow {
  id: string;
  provider: string;
  meter: string;
  quantity: string;
  unit: string;
  rate_version: number | null;
  cost_micro_toman: number | null;
  cost_toman_exact?: string | null;
  source_reference: string;
  occurred_at: string;
}
interface StatementLine {
  id: string;
  reference: string;
  charge_id: string | null;
  meter: string;
  quantity: string;
  unit: string;
  currency: string;
  billed_amount: string;
  billed_micro_toman: number;
  billed_toman_exact?: string;
  discrepancy_micro_toman: number | null;
  discrepancy_toman_exact?: string | null;
  status: string;
}
interface Statement {
  id: string;
  provider: string;
  reference: string;
  period: string;
  lines: StatementLine[];
  verification: string;
}
interface Reservation {
  id: string;
  status: string;
  max_quantity: string;
  reserved_toman_exact: string;
  reserved_micro_toman: number;
  rate_version: number | null;
  provider: string;
  meter: string;
  created_at: string;
  started_at: string | null;
}
const currencyNames: Record<string, string> = {
  TOMAN: "تومان",
  IRR: "ریال",
  USD: "دلار آمریکا",
};
const lineLabels: Record<string, string> = {
  MATCHED: "تطبیق شده",
  UNMATCHED: "بدون رویداد متناظر",
  DISCREPANCY: "دارای اختلاف",
  DISPUTED: "در حال پیگیری اختلاف",
  ACCEPTED_VENDOR: "مبلغ ارائه‌دهنده پذیرفته شد",
  RESOLVED_NO_CHANGE: "بسته شده بدون اصلاح مبلغ",
};

function BudgetForm({
  initial,
  onClose,
  onSaved,
}: {
  initial: CostPolicy | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [enabled, setEnabled] = useState(initial?.enabled ?? true);
  const [monthly, setMonthly] = useState(
    initial ? String(initial.monthly_cap_toman) : "",
  );
  const [call, setCall] = useState(
    initial ? String(initial.call_cap_toman) : "",
  );
  const [operation, setOperation] = useState(
    initial ? String(initial.operation_cap_toman) : "",
  );
  const [soft, setSoft] = useState(String(initial?.soft_percent || 80));
  const [providers, setProviders] = useState(
    Object.entries(initial?.provider_caps_toman || {}).map(
      ([provider, amount]) => ({ provider, amount: String(amount) }),
    ),
  );
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  useEffect(
    () => setConfirmed(false),
    [enabled, monthly, call, operation, soft, providers],
  );
  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    setBusy(true);
    try {
      if (Number(operation) > Number(call) || Number(call) > Number(monthly))
        throw new Error(
          "سقف هر عملیات باید حداکثر سقف تماس باشد و سقف تماس از بودجهٔ ماهانه بیشتر نباشد.",
        );
      if (
        new Set(providers.map((item) => item.provider.trim())).size !==
        providers.length
      )
        throw new Error("برای هر سرویس فقط یک سقف ثبت کنید.");
      await api("/operations/costs/policy", {
        method: "PUT",
        body: JSON.stringify({
          enabled,
          monthly_cap_toman: Number(monthly),
          call_cap_toman: Number(call),
          operation_cap_toman: Number(operation),
          soft_percent: Number(soft),
          provider_caps_toman: Object.fromEntries(
            providers.map((item) => [
              item.provider.trim(),
              Number(item.amount),
            ]),
          ),
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
      title="سقف هزینهٔ سرویس‌ها"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <p className="field-hint">
          سقف‌ها بر اساس تعرفه‌ها و مصرف ثبت‌شده اعمال می‌شوند. هزینهٔ فاقد
          تعرفه، هزینهٔ صفر محسوب نمی‌شود.
        </p>
        <label className="check-field">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => {
              setEnabled(event.target.checked);
              setConfirmed(false);
            }}
          />
          <span>کنترل سقف هزینه فعال باشد.</span>
        </label>
        <div className="form-grid">
          <Field label="سقف ماهانه (تومان)">
            <input
              required
              type="number"
              min={1}
              max={1_000_000_000_000}
              value={monthly}
              onChange={(event) => setMonthly(event.target.value)}
            />
          </Field>
          <Field label="سقف هر تماس (تومان)">
            <input
              required
              type="number"
              min={1}
              max={1_000_000_000}
              value={call}
              onChange={(event) => setCall(event.target.value)}
            />
          </Field>
          <Field label="سقف هر عملیات (تومان)">
            <input
              required
              type="number"
              min={1}
              max={1_000_000_000}
              value={operation}
              onChange={(event) => setOperation(event.target.value)}
            />
          </Field>
          <Field label="آستانهٔ هشدار (درصد)">
            <input
              required
              type="number"
              min={1}
              max={99}
              value={soft}
              onChange={(event) => setSoft(event.target.value)}
            />
          </Field>
        </div>
        <div className="administration-subheading">
          <h3>سقف جداگانهٔ سرویس‌ها</h3>
          <button
            className="button secondary small"
            type="button"
            onClick={() =>
              setProviders((old) => [...old, { provider: "", amount: "" }])
            }
          >
            <Plus size={15} />
            افزودن
          </button>
        </div>
        {providers.map((item, index) => (
          <div className="budget-provider" key={index}>
            <Field label="شناسهٔ سرویس">
              <input
                required
                dir="ltr"
                maxLength={80}
                value={item.provider}
                onChange={(event) =>
                  setProviders((old) =>
                    old.map((row, i) =>
                      i === index
                        ? { ...row, provider: event.target.value }
                        : row,
                    ),
                  )
                }
              />
            </Field>
            <Field label="سقف سرویس (تومان)">
              <input
                required
                type="number"
                min={1}
                max={Number(monthly) || undefined}
                value={item.amount}
                onChange={(event) =>
                  setProviders((old) =>
                    old.map((row, i) =>
                      i === index
                        ? { ...row, amount: event.target.value }
                        : row,
                    ),
                  )
                }
              />
            </Field>
            <button
              className="button quiet small"
              type="button"
              onClick={() =>
                setProviders((old) => old.filter((_, i) => i !== index))
              }
            >
              حذف
            </button>
          </div>
        ))}
        <label className="check-field">
          <input
            required
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            {enabled
              ? "سقف‌های بالا را بررسی کرده‌ام و انتشار آن‌ها را تأیید می‌کنم."
              : "توقف کنترل سقف هزینه را آگاهانه تأیید می‌کنم."}
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>
              <Save size={17} />
              انتشار سقف‌ها
            </Busy>
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

function RateForm({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    provider: "",
    meter: "",
    unit: "",
    currency: "TOMAN",
    price_per_unit: "",
    fx_toman_per_currency: "1",
    quantum: "1",
    minimum_quantity: "0",
    effective_at: "",
    expires_at: "",
    evidence_reference: "",
    evidence_sha256: "",
  });
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const update = (key: keyof typeof form, value: string) =>
    setForm((old) => ({ ...old, [key]: value }));
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/operations/costs/rates", {
        ...form,
        effective_at: new Date(form.effective_at + ":00+03:30").toISOString(),
        expires_at: new Date(form.expires_at + ":00+03:30").toISOString(),
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
      title="ثبت نسخهٔ تعرفهٔ سرویس"
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form className="modal-body" onSubmit={submit}>
        <p className="field-hint">
          مبلغ و واحد را از قرارداد واقعی سرویس وارد کنید. این ثبت، تأیید شما بر
          مدرک است و استعلام مستقل از ارائه‌دهنده محسوب نمی‌شود.
        </p>
        <div className="form-grid">
          <Field label="شناسهٔ سرویس">
            <input
              required
              maxLength={80}
              dir="ltr"
              value={form.provider}
              onChange={(event) => update("provider", event.target.value)}
            />
          </Field>
          <Field label="شناسهٔ نوع مصرف">
            <input
              required
              maxLength={80}
              dir="ltr"
              value={form.meter}
              onChange={(event) => update("meter", event.target.value)}
            />
          </Field>
          <Field
            label="واحد مصرف"
            hint="شناسهٔ توافق‌شده؛ مانند minute یا message"
          >
            <input
              required
              maxLength={30}
              dir="ltr"
              value={form.unit}
              onChange={(event) => update("unit", event.target.value)}
            />
          </Field>
          <Field label="واحد پول">
            <select
              value={form.currency}
              onChange={(event) => {
                update("currency", event.target.value);
                update(
                  "fx_toman_per_currency",
                  event.target.value === "TOMAN"
                    ? "1"
                    : event.target.value === "IRR"
                      ? "0.1"
                      : "",
                );
              }}
            >
              {Object.entries(currencyNames).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="قیمت هر واحد">
            <input
              required
              inputMode="decimal"
              dir="ltr"
              value={form.price_per_unit}
              onChange={(event) => update("price_per_unit", event.target.value)}
            />
          </Field>
          <Field
            label="تومان به‌ازای یک واحد پول"
            hint="برای دلار، نرخ تبدیل تأییدشدهٔ همین مدرک را ثبت کنید."
          >
            <input
              required
              readOnly={form.currency !== "USD"}
              inputMode="decimal"
              dir="ltr"
              value={form.fx_toman_per_currency}
              onChange={(event) =>
                update("fx_toman_per_currency", event.target.value)
              }
            />
          </Field>
          <Field label="گام گرد کردن مصرف">
            <input
              required
              inputMode="decimal"
              dir="ltr"
              value={form.quantum}
              onChange={(event) => update("quantum", event.target.value)}
            />
          </Field>
          <Field label="حداقل مصرف قابل محاسبه">
            <input
              required
              inputMode="decimal"
              dir="ltr"
              value={form.minimum_quantity}
              onChange={(event) =>
                update("minimum_quantity", event.target.value)
              }
            />
          </Field>
          <Field label="شروع اعتبار به وقت تهران">
            <input
              required
              type="datetime-local"
              value={form.effective_at}
              onChange={(event) => update("effective_at", event.target.value)}
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
        <EvidenceFields
          reference={form.evidence_reference}
          hash={form.evidence_sha256}
          onReference={(value) => update("evidence_reference", value)}
          onHash={(value) => update("evidence_sha256", value)}
          label="مدرک تعرفه و نرخ تبدیل"
        />
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || !/^[a-f0-9]{64}$/.test(form.evidence_sha256)}
          >
            <Busy busy={busy}>ثبت نسخهٔ تعرفه</Busy>
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

function StatementImport({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [provider, setProvider] = useState(""),
    [reference, setReference] = useState(""),
    [period, setPeriod] = useState("");
  const [hash, setHash] = useState(""),
    [lines, setLines] = useState<Record<string, unknown>[]>([]),
    [filename, setFilename] = useState("");
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function read(file?: File) {
    setError("");
    setLines([]);
    setHash("");
    setFilename("");
    setConfirmed(false);
    if (!file) return;
    setBusy(true);
    try {
      const digest = await documentHash(file);
      const parsed = JSON.parse(await file.text());
      if (
        !Array.isArray(parsed.lines) ||
        parsed.lines.length < 1 ||
        parsed.lines.length > 500
      )
        throw new Error("فایل باید آرایهٔ lines با ۱ تا ۵۰۰ ردیف داشته باشد.");
      const allowed = [
        "reference",
        "charge_id",
        "meter",
        "quantity",
        "unit",
        "currency",
        "billed_amount",
        "fx_toman_per_currency",
      ];
      const rows = parsed.lines.map((line: Record<string, unknown>) => {
        if (
          !line ||
          allowed
            .filter((key) => key !== "charge_id")
            .some((key) => typeof line[key] !== "string")
        )
          throw new Error("مقادیر اجباری هر ردیف باید به‌صورت متن ثبت شوند.");
        return Object.fromEntries(
          allowed
            .filter((key) => line[key] !== undefined)
            .map((key) => [key, line[key]]),
        );
      });
      setLines(rows);
      setHash(digest);
      setFilename(file.name);
      if (typeof parsed.provider === "string") setProvider(parsed.provider);
      if (typeof parsed.reference === "string") setReference(parsed.reference);
      if (typeof parsed.period === "string") setPeriod(parsed.period);
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/operations/costs/statements", {
        provider,
        reference,
        period,
        evidence_sha256: hash,
        lines,
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
      title="ورود صورت‌حساب ارائه‌دهنده"
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form className="modal-body" onSubmit={submit}>
        <p className="field-hint">
          صورت‌حساب واقعی ارائه‌دهنده را به قالب مشخص تبدیل کنید. ردیف‌های
          واردشده با دفتر مصرف تطبیق داده می‌شوند؛ این کار پرداخت بانکی انجام
          نمی‌دهد.
        </p>
        <Field label="فایل صورت‌حساب ساخت‌یافته (JSON)">
          <input
            type="file"
            accept=".json,application/json"
            disabled={busy}
            onChange={(event) => void read(event.target.files?.[0])}
          />
        </Field>
        <details className="policy-detail">
          <summary>قالب فایل و مقادیر لازم</summary>
          <p>
            فایل شامل provider، reference، period به شکل YYYY-MM و آرایهٔ lines
            است. هر ردیف این مقادیر متنی را دارد:
          </p>
          <pre dir="ltr">
            {
              "reference, meter, quantity, unit, currency,\nbilled_amount, fx_toman_per_currency\ncharge_id (optional)"
            }
          </pre>
          <p>
            currency یکی از TOMAN، IRR یا USD است. برای اتصال به مصرف ثبت‌شده،
            charge_id همان ردیف را از دفتر مصرف وارد کنید.
          </p>
        </details>
        <div className="form-grid">
          <Field label="شناسهٔ ارائه‌دهنده">
            <input
              required
              maxLength={80}
              dir="ltr"
              value={provider}
              onChange={(event) => setProvider(event.target.value)}
            />
          </Field>
          <Field label="شماره یا شناسهٔ صورت‌حساب">
            <input
              required
              maxLength={160}
              dir="ltr"
              value={reference}
              onChange={(event) => setReference(event.target.value)}
            />
          </Field>
          <Field label="دورهٔ صورت‌حساب (میلادی)">
            <input
              required
              type="month"
              value={period}
              onChange={(event) => setPeriod(event.target.value)}
            />
          </Field>
        </div>
        {lines.length > 0 && (
          <Alert kind="info">
            {filename} · {faNumber(lines.length)} ردیف برای بررسی آماده است.
            فایل به‌عنوان مدرک واردشده توسط شما ثبت می‌شود.
          </Alert>
        )}
        <label className="check-field">
          <input
            required
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            ارائه‌دهنده، دوره، واحد پول و ردیف‌ها را با مدرک بررسی کرده‌ام.
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || !hash || !lines.length || !confirmed}
          >
            <Busy busy={busy}>
              <Upload size={17} />
              ورود و تطبیق صورت‌حساب
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

function ReviewLine({
  line,
  onClose,
  onSaved,
}: {
  line: StatementLine;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [action, setAction] = useState("DISPUTE"),
    [reference, setReference] = useState(""),
    [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(`/operations/costs/statement-lines/${line.id}/review`, {
        action,
        evidence_reference: reference,
        explanation: reason,
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
      title="رسیدگی به ردیف صورت‌حساب"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <div className="selected-appointment">
          <strong>{line.reference}</strong>
          <span>
            مبلغ اعلام‌شده:{" "}
            {exactToman(line.billed_toman_exact, line.billed_micro_toman)} تومان
          </span>
          <span>
            اختلاف:{" "}
            {line.discrepancy_micro_toman === null
              ? "هنوز قابل محاسبه نیست"
              : `${exactToman(line.discrepancy_toman_exact ?? undefined, line.discrepancy_micro_toman)} تومان`}
          </span>
        </div>
        <Field label="تصمیم">
          <select
            value={action}
            onChange={(event) => {
              setAction(event.target.value);
              setConfirmed(false);
            }}
          >
            <option value="DISPUTE">ثبت اختلاف و پیگیری</option>
            <option value="ACCEPT_VENDOR">
              پذیرش مبلغ ارائه‌دهنده و اصلاح دفتر
            </option>
            <option value="RESOLVE_NO_CHANGE">
              بستن بررسی بدون تغییر مبلغ
            </option>
          </select>
        </Field>
        <Field label="شناسهٔ مدرک تصمیم">
          <input
            required
            dir="ltr"
            maxLength={160}
            value={reference}
            onChange={(event) => setReference(event.target.value)}
          />
        </Field>
        <Field label="توضیح بررسی">
          <textarea
            required
            minLength={10}
            maxLength={1000}
            rows={3}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
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
            {action === "ACCEPT_VENDOR"
              ? "ثبت اصلاح مبلغ در دفتر هزینه را تأیید می‌کنم. این اقدام انتقال پول نیست."
              : "نتیجهٔ بررسی بالا را تأیید می‌کنم."}
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>ثبت تصمیم</Busy>
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

function ReservationReview({
  item,
  onClose,
  onSaved,
}: {
  item: Reservation;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [outcome, setOutcome] = useState(""),
    [quantity, setQuantity] = useState("");
  const [reference, setReference] = useState(""),
    [hash, setHash] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(`/operations/costs/reservations/${item.id}/reconcile`, {
        outcome,
        quantity: outcome === "no_charge" ? "0" : quantity,
        source_reference: reference,
        evidence_sha256: hash,
        provider_result_verified: confirmed,
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
      title="تطبیق عملیات با نتیجهٔ ارائه‌دهنده"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <div className="selected-appointment">
          <strong>
            <bdi>{item.provider}</bdi> · <bdi>{item.meter}</bdi>
          </strong>
          <span>
            مبلغ نگه‌داشته‌شده: {exactToman(item.reserved_toman_exact)} تومان
          </span>
        </div>
        <p className="field-hint">
          زمان‌بر بودن یا قطع ارتباط، دلیل رایگان بودن عملیات نیست. فقط نتیجهٔ
          احراز‌شده از ارائه‌دهنده را ثبت کنید.
        </p>
        <Field label="نتیجهٔ ارائه‌دهنده">
          <select
            required
            value={outcome}
            onChange={(event) => {
              setOutcome(event.target.value);
              setConfirmed(false);
            }}
          >
            <option value="">انتخاب نتیجهٔ بررسی‌شده</option>
            <option value="confirmed">مصرف و هزینه تأیید شده است</option>
            <option value="no_charge">
              ارائه‌دهنده نبود هزینه را تأیید کرده است
            </option>
          </select>
        </Field>
        {outcome === "confirmed" && (
          <Field label="مقدار مصرف تأییدشده">
            <input
              required
              inputMode="decimal"
              dir="ltr"
              value={quantity}
              onChange={(event) => {
                setQuantity(event.target.value);
                setConfirmed(false);
              }}
            />
          </Field>
        )}
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
          label="مدرک نتیجهٔ ارائه‌دهنده"
        />
        <label className="check-field">
          <input
            required
            type="checkbox"
            checked={confirmed}
            onChange={(event) => setConfirmed(event.target.checked)}
          />
          <span>
            نتیجه را از ارائه‌دهنده احراز کرده‌ام و تطبیق این مبلغ رزروشده با
            مدرک بالا را تأیید می‌کنم.
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={
              busy || !confirmed || !outcome || !/^[a-f0-9]{64}$/.test(hash)
            }
          >
            <Busy busy={busy}>ثبت نتیجهٔ تطبیق</Busy>
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

export function Costs({ canWrite }: { canWrite: boolean }) {
  const costs = useRemote<CostOverview>("/operations/costs");
  const ledger = useRemote<LedgerRow[]>("/operations/costs/ledger");
  const statements = useRemote<Statement[]>("/operations/costs/statements");
  const reservations = useRemote<Reservation[]>(
    "/operations/costs/reservations",
  );
  const [reservation, setReservation] = useState<Reservation | null>(null);
  const [editing, setEditing] = useState<"budget" | "rate" | "statement" | "">(
    "",
  );
  const [line, setLine] = useState<StatementLine | null>(null),
    [message, setMessage] = useState("");
  const saved = () => {
    setEditing("");
    setLine(null);
    setReservation(null);
    setMessage("اطلاعات پس از بررسی سامانه ثبت شد.");
    costs.refresh();
    ledger.refresh();
    statements.refresh();
    reservations.refresh();
  };
  if (costs.error) return <Retry error={costs.error} onRetry={costs.refresh} />;
  if (costs.loading || !costs.data) return <Loading rows={4} />;
  const data = costs.data;
  return (
    <div className="administration-stack">
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <section className="panel">
        <SectionTitle
          title="هزینهٔ سرویس‌های مرکز"
          description={`دورهٔ میلادی ${faNumber(data.period)} · مرز دوره به وقت UTC`}
          action={
            canWrite && (
              <button
                className="button secondary"
                onClick={() => setEditing("budget")}
              >
                <ShieldCheck size={17} />
                سقف هزینه
              </button>
            )
          }
        />
        <div className="cost-summary">
          {[
            {
              label: "هزینهٔ ثبت‌شده",
              value: exactToman(
                data.charged_toman,
                data.charged_micro_toman,
                data.money_scale,
              ),
            },
            {
              label: "سقف رزروشدهٔ عملیات جاری",
              value: exactToman(
                data.reserved_toman,
                data.reserved_micro_toman,
                data.money_scale,
              ),
            },
            {
              label: "جمع هزینه و رزرو",
              value: exactToman(
                data.exposure_toman,
                data.exposure_micro_toman,
                data.money_scale,
              ),
            },
          ].map((item) => (
            <div key={item.label}>
              <span>{item.label}</span>
              <strong>{item.value}</strong>
              <small>تومان</small>
            </div>
          ))}
        </div>
        <div className="administration-panel-body">
          {data.policy ? (
            <div className="policy-summary">
              <Status value={data.policy.enabled ? "ACTIVE" : "DISABLED"} />
              <span>
                سقف ماهانه:{" "}
                <strong>{faNumber(data.policy.monthly_cap_toman)} تومان</strong>
              </span>
              <span>آستانهٔ هشدار: {faNumber(data.policy.soft_percent)}٪</span>
              <small>نسخهٔ {faNumber(data.policy.version)}</small>
            </div>
          ) : (
            <Alert kind="info">
              هنوز سقف هزینه‌ای برای این مرکز منتشر نشده است.
            </Alert>
          )}
          {data.soft_limit_reached && (
            <Alert>
              مصرف ثبت‌شده و رزروهای جاری به آستانهٔ هشدار رسیده‌اند. پیش از
              ادامه، سقف و عملیات باز را بررسی کنید.
            </Alert>
          )}
          {(data.unpriced_events > 0 || data.unknown_reservations > 0) && (
            <Alert kind="info">
              {faNumber(data.unpriced_events)} رویداد بدون تعرفه و{" "}
              {faNumber(data.unknown_reservations)} رزرو با نتیجهٔ نامشخص وجود
              دارد. جمع بالا شامل برآورد ساختگی برای این موارد نیست.
            </Alert>
          )}
          <p className="field-hint">
            این اعداد دفتر هزینهٔ سرویس‌ها هستند. هزینهٔ واقعی ارائه‌دهنده پس از
            دریافت و بررسی صورت‌حساب او تطبیق داده می‌شود.
          </p>
        </div>
      </section>
      <section className="panel">
        <SectionTitle
          title="تعرفه‌های ثبت‌شده"
          description="هر نسخه با مدرک، واحد پول و بازهٔ اعتبار مشخص"
          action={
            canWrite && (
              <button
                className="button secondary"
                onClick={() => setEditing("rate")}
              >
                <Plus size={17} />
                ثبت تعرفه
              </button>
            )
          }
        />
        {data.rates.length ? (
          <div className="governance-list">
            {data.rates.map((rate) => (
              <article className="governance-row" key={rate.id}>
                <div>
                  <h3>
                    <bdi>{rate.provider}</bdi> · <bdi>{rate.meter}</bdi>
                  </h3>
                  <p>
                    {rate.price_per_unit}{" "}
                    {currencyNames[rate.currency] || rate.currency} /{" "}
                    <bdi>{rate.unit}</bdi> · نسخهٔ {faNumber(rate.version)}
                  </p>
                  <small>
                    {faDate(rate.effective_at, true)} تا{" "}
                    {faDate(rate.expires_at, true)}
                  </small>
                  <small>
                    مدرک: <bdi>{rate.evidence_reference}</bdi>
                  </small>
                </div>
                <Status
                  value={
                    new Date(rate.expires_at) < new Date()
                      ? "EXPIRED"
                      : new Date(rate.effective_at) > new Date()
                        ? "PENDING"
                        : "ACTIVE"
                  }
                />
              </article>
            ))}
          </div>
        ) : (
          <Empty
            title="تعرفه‌ای ثبت نشده"
            description="تعرفهٔ تأییدشده و مدرک آن را از مسئول قرارداد سرویس دریافت کنید."
          />
        )}
      </section>
      <section className="panel">
        <SectionTitle
          title="دفتر مصرف هزینه‌گذاری‌شده"
          description="حداکثر ۱۰۰ رویداد آخر؛ مبلغ نامعلوم با صفر جایگزین نمی‌شود"
        />
        {ledger.error ? (
          <Retry error={ledger.error} onRetry={ledger.refresh} />
        ) : ledger.loading ? (
          <Loading rows={2} />
        ) : ledger.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            aria-label="دفتر مصرف؛ برای ستون‌های بیشتر پیمایش کنید"
          >
            <table>
              <thead>
                <tr>
                  <th>سرویس و مصرف</th>
                  <th>مقدار</th>
                  <th>هزینه به تومان</th>
                  <th>منبع</th>
                </tr>
              </thead>
              <tbody>
                {ledger.data.map((row) => (
                  <tr key={row.id}>
                    <td>
                      <strong>
                        <bdi>{row.provider}</bdi>
                      </strong>
                      <small className="table-subline">
                        <bdi>{row.meter}</bdi>
                      </small>
                      <small className="table-subline">
                        {faDate(row.occurred_at, true)}
                      </small>
                    </td>
                    <td>
                      <bdi>
                        {row.quantity} {row.unit}
                      </bdi>
                    </td>
                    <td>
                      {row.cost_micro_toman === null
                        ? "بدون تعرفه"
                        : exactToman(
                            row.cost_toman_exact ?? undefined,
                            row.cost_micro_toman,
                          )}
                    </td>
                    <td>
                      <bdi>{row.source_reference}</bdi>
                      <details className="record-id">
                        <summary>شناسهٔ رویداد</summary>
                        <bdi>{row.id}</bdi>
                      </details>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="مصرفی در این دفتر ثبت نشده"
            description="خالی بودن دفتر به معنی رایگان بودن سرویس نیست."
          />
        )}
      </section>
      <section className="panel">
        <SectionTitle
          title="تطبیق صورت‌حساب ارائه‌دهندگان"
          description="مستقل از پرداخت‌ها و بازپرداخت‌های مراجعه‌کنندگان"
          action={
            canWrite && (
              <button
                className="button secondary"
                onClick={() => setEditing("statement")}
              >
                <FileCheck2 size={17} />
                ورود صورت‌حساب
              </button>
            )
          }
        />
        {statements.error ? (
          <Retry error={statements.error} onRetry={statements.refresh} />
        ) : statements.loading ? (
          <Loading rows={2} />
        ) : statements.data?.length ? (
          <div className="governance-list">
            {statements.data.map((statement) => (
              <details className="statement-record" key={statement.id}>
                <summary>
                  <strong>
                    <bdi>{statement.provider}</bdi> ·{" "}
                    <bdi>{statement.reference}</bdi>
                  </strong>
                  <span>
                    {faNumber(statement.period)} ·{" "}
                    {faNumber(statement.lines.length)} ردیف
                  </span>
                </summary>
                {statement.lines.map((item) => (
                  <div className="statement-line" key={item.id}>
                    <div>
                      <strong>
                        <bdi>{item.reference}</bdi>
                      </strong>
                      <p>
                        {exactToman(
                          item.billed_toman_exact,
                          item.billed_micro_toman,
                        )}{" "}
                        تومان
                      </p>
                      <small>
                        {lineLabels[item.status] || "نیازمند بررسی"}
                      </small>
                    </div>
                    {canWrite &&
                      ![
                        "MATCHED",
                        "ACCEPTED_VENDOR",
                        "RESOLVED_NO_CHANGE",
                      ].includes(item.status) && (
                        <button
                          className="button secondary small"
                          onClick={() => setLine(item)}
                        >
                          بررسی ردیف
                        </button>
                      )}
                  </div>
                ))}
              </details>
            ))}
          </div>
        ) : (
          <Empty
            title="صورت‌حسابی وارد نشده"
            description="مدرک واقعی را وارد کنید تا اختلاف‌ها و ردیف‌های بدون تطبیق مشخص شوند."
          />
        )}
      </section>
      <section className="panel">
        <SectionTitle
          title="عملیات با هزینهٔ نیازمند تطبیق"
          description="مبلغ نگه‌داشته‌شده تا رسیدن نتیجهٔ معتبر آزاد فرض نمی‌شود."
        />
        {reservations.error ? (
          <Retry error={reservations.error} onRetry={reservations.refresh} />
        ) : reservations.loading ? (
          <Loading rows={2} />
        ) : reservations.data?.length ? (
          <div className="governance-list">
            {reservations.data.map((item) => (
              <article className="governance-row" key={item.id}>
                <div>
                  <h3>
                    <bdi>{item.provider}</bdi> · <bdi>{item.meter}</bdi>
                  </h3>
                  <p>{exactToman(item.reserved_toman_exact)} تومان رزرو</p>
                  <small>
                    {faDate(item.created_at, true)} ·{" "}
                    {item.status === "UNKNOWN"
                      ? "نتیجه نامشخص"
                      : "عملیات شروع شده"}
                  </small>
                </div>
                {canWrite && (
                  <button
                    className="button secondary small"
                    onClick={() => setReservation(item)}
                  >
                    بررسی نتیجه
                  </button>
                )}
              </article>
            ))}
          </div>
        ) : (
          <Empty
            title="عملیات بازی برای تطبیق نیست"
            description="فقط رزروهای شروع‌شده یا با نتیجهٔ نامشخص در این فهرست دیده می‌شوند."
          />
        )}
      </section>
      {editing === "budget" && (
        <BudgetForm
          initial={data.policy}
          onClose={() => setEditing("")}
          onSaved={saved}
        />
      )}
      {editing === "rate" && (
        <RateForm onClose={() => setEditing("")} onSaved={saved} />
      )}
      {editing === "statement" && (
        <StatementImport onClose={() => setEditing("")} onSaved={saved} />
      )}
      {line && (
        <ReviewLine line={line} onClose={() => setLine(null)} onSaved={saved} />
      )}
      {reservation && (
        <ReservationReview
          item={reservation}
          onClose={() => setReservation(null)}
          onSaved={saved}
        />
      )}
    </div>
  );
}
