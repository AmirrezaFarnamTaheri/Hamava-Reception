import { useRef, useState, type FormEvent } from "react";
import { FileSearch } from "lucide-react";
import { api, errorText, faDate, faNumber, newId, post } from "../api";
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
interface RefundReference {
  id: string;
  status: string;
  amount_toman: number;
}
interface PaymentReference {
  id: string;
  amount_toman: number;
}
export function RefundReviewDialog({
  refund,
  onClose,
  onSaved,
}: {
  refund: RefundReference;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [action, setAction] = useState(
    refund.status === "REQUESTED" ? "REFUSE" : "RECONCILE_PENDING",
  );
  const [reason, setReason] = useState("");
  const [reference, setReference] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(newId());
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(`/operations/refunds/${refund.id}/review`, {
        action,
        reason,
        ...(reference ? { provider_reference: reference } : {}),
        confirmed,
        idempotency_key: requestId.current,
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
      title="بررسی و تطبیق بازپرداخت"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <div className="selected-appointment">
          <strong>{faNumber(refund.amount_toman)} تومان</strong>
          <Status value={refund.status} />
        </div>
        <Field label="نتیجهٔ بررسی">
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            {refund.status === "REQUESTED" && (
              <option value="REFUSE">رد درخواست پیش از اجرا</option>
            )}
            <option value="RECONCILE_PENDING">
              در انتظار نتیجهٔ تطبیق ارائه‌دهنده
            </option>
            <option value="RECONCILE_FAILED">
              عدم انجام بازپرداخت طبق مدرک ارائه‌دهنده
            </option>
          </select>
        </Field>
        {action !== "REFUSE" && (
          <Field label="شماره پیگیری واقعی ارائه‌دهنده">
            <input
              required
              minLength={6}
              maxLength={120}
              dir="ltr"
              value={reference}
              onChange={(e) => setReference(e.target.value)}
            />
          </Field>
        )}
        <Field label="دلیل و مرجع نتیجه">
          <textarea
            required
            minLength={3}
            maxLength={500}
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <Alert kind="info">
          این اقدام فقط نتیجهٔ بررسی را ثبت می‌کند. مدرک اجرای موفق بازپرداخت،
          از اقدام جداگانهٔ «ثبت مدرک اجرا» ثبت می‌شود.
        </Alert>
        <label className="check-field">
          <input
            type="checkbox"
            required
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>
            مدارک مربوط به این نتیجه را بررسی کرده‌ام و ثبت آن را تأیید می‌کنم.
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>ثبت نتیجهٔ بررسی</Busy>
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
interface Dispute {
  id: string;
  payment_id: string;
  amount_toman: number;
  provider_case_reference: string;
  status: string;
  version: number;
  reason: string;
  created_at: string;
  closed_at: string | null;
  adjustment: { id: string; amount_toman: number; kind: string } | null;
}
export function NewDispute({
  payment,
  onClose,
  onSaved,
}: {
  payment: PaymentReference;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [amount, setAmount] = useState(payment.amount_toman);
  const [reference, setReference] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(newId());
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(`/operations/payments/${payment.id}/disputes`, {
        amount_toman: amount,
        provider_case_reference: reference,
        reason,
        confirmed,
        idempotency_key: requestId.current,
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
      title="ثبت اختلاف درگاه"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <p className="muted">
          فقط پروندهٔ واقعی ارائه‌دهنده و مبلغ مربوط به همین پرداخت را ثبت کنید.
        </p>
        <Field label="مبلغ مورد اختلاف (تومان)">
          <input
            type="number"
            min={1}
            max={payment.amount_toman}
            required
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
          />
        </Field>
        <Field label="شماره پروندهٔ ارائه‌دهنده">
          <input
            dir="ltr"
            required
            minLength={6}
            maxLength={120}
            value={reference}
            onChange={(e) => setReference(e.target.value)}
          />
        </Field>
        <Field label="شرح اختلاف و مدرک">
          <textarea
            rows={3}
            minLength={3}
            maxLength={500}
            required
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <label className="check-field">
          <input
            required
            type="checkbox"
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>مبلغ و مدارک پرونده را بررسی کرده‌ام.</span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>ثبت پروندهٔ اختلاف</Busy>
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
const outcomes: Record<string, string> = {
  UNDER_REVIEW: "در حال بررسی ارائه‌دهنده",
  WON: "نتیجهٔ قطعی به نفع مرکز",
  LOST: "نتیجهٔ قطعی به زیان مرکز",
  CLOSED: "بستن پرونده پس از ثبت نتیجه",
};
function UpdateDispute({
  item,
  onClose,
  onSaved,
}: {
  item: Dispute;
  onClose: () => void;
  onSaved: () => void;
}) {
  const choices: Record<string, string[]> = {
    OPEN: ["UNDER_REVIEW", "WON", "LOST"],
    UNDER_REVIEW: ["WON", "LOST"],
    WON: ["CLOSED"],
    LOST: ["CLOSED"],
    CLOSED: [],
  };
  const [status, setStatus] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(newId());
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api(`/operations/disputes/${item.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          version: item.version,
          status,
          reason,
          confirmed,
          idempotency_key: requestId.current,
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
      title="ثبت نتیجهٔ اختلاف"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <div className="selected-appointment">
          <strong>{faNumber(item.amount_toman)} تومان</strong>
          <span dir="ltr">{item.provider_case_reference}</span>
          <Status value={item.status} />
        </div>
        <Field label="نتیجهٔ جدید پرونده">
          <select
            required
            value={status}
            onChange={(e) => setStatus(e.target.value)}
          >
            <option value="">انتخاب کنید</option>
            {choices[item.status]?.map((value) => (
              <option key={value} value={value}>
                {outcomes[value]}
              </option>
            ))}
          </select>
        </Field>
        {status === "LOST" && (
          <Alert kind="info">
            نتیجهٔ قطعی به زیان مرکز، اصلاح منفیِ مربوط به این مبلغ را در دفتر
            مالی ثبت می‌کند. مبلغی از طریق این فرم جابه‌جا نمی‌شود.
          </Alert>
        )}
        <Field label="شرح نتیجه و مدرک ارائه‌دهنده">
          <textarea
            required
            rows={3}
            minLength={3}
            maxLength={500}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        <label className="check-field">
          <input
            type="checkbox"
            required
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>نتیجه با مدرک ارائه‌دهنده تطبیق داده شده است.</span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || !confirmed || !status}
          >
            <Busy busy={busy}>ثبت نتیجهٔ پرونده</Busy>
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
export function Disputes() {
  const result = useRemote<Dispute[]>("/operations/disputes");
  const [selected, setSelected] = useState<Dispute | null>(null);
  const [message, setMessage] = useState("");
  return (
    <>
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <section className="panel catalog-panel">
        <SectionTitle
          title="اختلاف‌های درگاه"
          description="پرونده و نتیجهٔ مستند ارائه‌دهنده؛ مستقل از پرداخت و بازپرداخت."
        />
        {result.error ? (
          <Retry error={result.error} onRetry={result.refresh} />
        ) : result.loading ? (
          <Loading rows={2} />
        ) : result.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="جدول اختلاف‌های مالی"
          >
            <table>
              <thead>
                <tr>
                  <th>پرونده</th>
                  <th>مبلغ</th>
                  <th>وضعیت</th>
                  <th>اصلاح دفتر</th>
                  <th>اقدام</th>
                </tr>
              </thead>
              <tbody>
                {result.data.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>
                        <bdi>{item.provider_case_reference}</bdi>
                      </strong>
                      <small className="table-subline">
                        {faDate(item.created_at, true)}
                      </small>
                    </td>
                    <td>{faNumber(item.amount_toman)} تومان</td>
                    <td>
                      <Status value={item.status} />
                    </td>
                    <td>
                      {item.adjustment
                        ? `${faNumber(item.adjustment.amount_toman)} تومان`
                        : "ثبت نشده"}
                    </td>
                    <td>
                      {item.status !== "CLOSED" && (
                        <button
                          className="button secondary small"
                          onClick={() => setSelected(item)}
                        >
                          <FileSearch size={15} />
                          ثبت نتیجه
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
            title="پروندهٔ اختلافی ثبت نشده"
            description="برای یک پرداخت تسویه‌شده، از اقدام «اختلاف درگاه» پروندهٔ مستند ثبت کنید."
          />
        )}
      </section>
      {selected && (
        <UpdateDispute
          item={selected}
          onClose={() => setSelected(null)}
          onSaved={() => {
            setSelected(null);
            result.refresh();
            setMessage("نتیجهٔ مستند پرونده در دفتر مالی ثبت شد.");
          }}
        />
      )}
    </>
  );
}
