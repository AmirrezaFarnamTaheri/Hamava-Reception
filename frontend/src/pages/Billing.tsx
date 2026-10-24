import { useRef, useState, type FormEvent } from "react";
import { Download, FilePlus2, Plus } from "lucide-react";
import { errorText, faNumber, localToday, newId, post } from "../api";
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

interface Invoice {
  id: string;
  period: string;
  status: string;
  amount_toman: number;
  snapshot: Record<string, unknown>;
}
function previousMonth() {
  const date = new Date(localToday() + "T12:00:00Z");
  date.setUTCDate(1);
  date.setUTCMonth(date.getUTCMonth() - 1);
  return date.toISOString().slice(0, 7);
}
function InvoiceForm({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [form, setForm] = useState({
    period: previousMonth(),
    base_fee_toman: 0,
    included_minutes: 0,
    per_minute_toman: 0,
    pricing_approved: false,
  });
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
      await post("/operations/billing/invoices", form);
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="ثبت صورت‌حساب دوره"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <Alert kind="info">
          صورت‌حساب فقط برای دورهٔ پایان‌یافته ثبت می‌شود و ارقام آن بعد از ثبت
          ثابت می‌مانند. مالیات و الزامات قراردادی باید جداگانه بررسی شوند.
        </Alert>
        <Field label="دورهٔ میلادی">
          <input
            required
            type="month"
            value={form.period}
            onChange={(e) => update("period", e.target.value)}
          />
        </Field>
        <Field label="مبلغ ثابت دوره (تومان)">
          <input
            required
            type="number"
            min="0"
            max="1000000000"
            value={form.base_fee_toman}
            onChange={(e) => update("base_fee_toman", Number(e.target.value))}
          />
        </Field>
        <div className="form-grid">
          <Field label="دقیقهٔ شامل قرارداد">
            <input
              required
              type="number"
              min="0"
              max="1000000"
              value={form.included_minutes}
              onChange={(e) =>
                update("included_minutes", Number(e.target.value))
              }
            />
          </Field>
          <Field label="هر دقیقهٔ مازاد (تومان)">
            <input
              required
              type="number"
              min="0"
              max="1000000"
              value={form.per_minute_toman}
              onChange={(e) =>
                update("per_minute_toman", Number(e.target.value))
              }
            />
          </Field>
        </div>
        <label className="check-field">
          <input
            required
            type="checkbox"
            checked={form.pricing_approved}
            onChange={(e) => update("pricing_approved", e.target.checked)}
          />
          <span>این تعرفه را با قرارداد تأییدشدهٔ مرکز تطبیق داده‌ام.</span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || !form.pricing_approved}
          >
            <Busy busy={busy}>ثبت صورت‌حساب</Busy>
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
function AdjustmentForm({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const [period, setPeriod] = useState(previousMonth());
  const [amount, setAmount] = useState(0);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const key = useRef(newId());
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/operations/billing/adjustments", {
        period,
        amount_toman: amount,
        reason,
        idempotency_key: key.current,
      });
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="اصلاح مبلغ دوره"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <p className="muted">
          اصلاح باید پیش از ثبت صورت‌حساب انجام شود. مبلغ منفی از هزینه کم و
          مبلغ مثبت به آن اضافه می‌شود.
        </p>
        <Field label="دورهٔ میلادی">
          <input
            required
            type="month"
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
          />
        </Field>
        <Field label="مبلغ اصلاح (تومان)">
          <input
            required
            type="number"
            min="-1000000000"
            max="1000000000"
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
          />
        </Field>
        <Field label="دلیل اصلاح">
          <textarea
            required
            minLength={3}
            maxLength={200}
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy}>
            <Busy busy={busy}>ثبت اصلاح</Busy>
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

export function Billing() {
  const invoices = useRemote<Invoice[]>("/operations/billing/invoices");
  const [dialog, setDialog] = useState<"invoice" | "adjustment" | null>(null);
  const [message, setMessage] = useState("");
  function done() {
    setDialog(null);
    invoices.refresh();
    setMessage("سند مالی با موفقیت ثبت شد.");
  }
  function download(invoice: Invoice) {
    const blob = new Blob([JSON.stringify(invoice, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `invoice-${invoice.period}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }
  return (
    <>
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <section className="panel">
        <SectionTitle
          title="صورت‌حساب و اصلاحات"
          description="ارقام ثابت هر دوره با جزئیات مصرف، تعرفه و اصلاحات ثبت‌شده."
          action={
            <div className="inline-actions">
              <button
                className="button secondary small"
                onClick={() => setDialog("adjustment")}
              >
                <Plus size={15} />
                اصلاح مبلغ
              </button>
              <button
                className="button primary small"
                onClick={() => setDialog("invoice")}
              >
                <FilePlus2 size={15} />
                صورت‌حساب جدید
              </button>
            </div>
          }
        />
        {invoices.error ? (
          <Retry error={invoices.error} onRetry={invoices.refresh} />
        ) : invoices.loading ? (
          <Loading rows={3} />
        ) : invoices.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
          >
            <table>
              <thead>
                <tr>
                  <th>دورهٔ میلادی</th>
                  <th>مبلغ (تومان)</th>
                  <th>وضعیت</th>
                  <th>جزئیات</th>
                </tr>
              </thead>
              <tbody>
                {invoices.data.map((invoice) => (
                  <tr key={invoice.id}>
                    <td dir="ltr">{invoice.period}</td>
                    <td>{faNumber(invoice.amount_toman)}</td>
                    <td>
                      <Status value={invoice.status} />
                      <small className="table-subline">
                        پیش از صدور رسمی، مالیات بررسی شود.
                      </small>
                    </td>
                    <td>
                      <button
                        className="button secondary small"
                        onClick={() => download(invoice)}
                      >
                        <Download size={15} />
                        دریافت سند
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="صورت‌حسابی ثبت نشده"
            description="پس از پایان دوره و تأیید تعرفهٔ قرارداد، صورت‌حساب آن دوره را ثبت کنید."
          />
        )}
      </section>
      {dialog === "invoice" && (
        <InvoiceForm onClose={() => setDialog(null)} onDone={done} />
      )}
      {dialog === "adjustment" && (
        <AdjustmentForm onClose={() => setDialog(null)} onDone={done} />
      )}
    </>
  );
}
