import { useRef, useState, type FormEvent } from "react";
import {
  CreditCard,
  ExternalLink,
  Plus,
  RefreshCw,
  RotateCcw,
} from "lucide-react";
import { errorText, faDate, faNumber, newId, post } from "../api";
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
interface PaymentAppointment {
  id: string;
  reference: string;
  deposit_toman: number;
  status: string;
}

import { RefundReviewDialog, NewDispute, Disputes } from "./FinanceReview";

interface Payment {
  id: string;
  appointment_id: string;
  appointment_reference?: string;
  amount_toman: number;
  status: string;
  payment_url: string | null;
  expires_at: string;
  provider_reference: string | null;
}
interface Refund {
  id: string;
  status: string;
  amount_toman: number;
  message?: string;
  payment_id?: string;
  reason?: string;
  provider_reference?: string | null;
  created_at?: string;
  completed_at?: string | null;
}
function PaymentLink({
  onClose,
  onDone,
}: {
  onClose: () => void;
  onDone: () => void;
}) {
  const appointments = useRemote<PaymentAppointment[]>(
    "/operations/payments/appointments?status=PENDING_PAYMENT",
  );
  const [selected, setSelected] = useState("");
  const [payment, setPayment] = useState<Payment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function create(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setPayment(
        await post<Payment>("/operations/payments", {
          appointment_id: selected,
        }),
      );
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="ایجاد درخواست بیعانه"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={create}>
        {payment ? (
          <>
            <div className="selected-appointment">
              <strong>{faNumber(payment.amount_toman)} تومان</strong>
              <Status value={payment.status} />
              <span>مهلت: {faDate(payment.expires_at, true)}</span>
            </div>
            {payment.payment_url?.startsWith("https://") ? (
              <a
                className="button primary"
                href={payment.payment_url}
                target="_blank"
                rel="noreferrer"
              >
                <ExternalLink size={17} />
                باز کردن درگاه پرداخت
              </a>
            ) : (
              <Alert kind="info">
                {payment.status === "DEMO_PENDING"
                  ? "این درخواست آزمایشی است؛ وجهی دریافت نمی‌شود. ثبت پرداخت آزمایشی از فهرست پرداخت‌ها در دسترس است."
                  : "لینک پرداخت در دسترس نیست. وضعیت اتصال درگاه یا درخواست را بررسی کنید."}
              </Alert>
            )}
            <div className="modal-actions">
              <button
                type="button"
                className="button secondary"
                onClick={onClose}
              >
                بستن
              </button>
            </div>
          </>
        ) : (
          <>
            <p className="muted">
              مبلغ بیعانه از تعرفهٔ تأییدشدهٔ خدمت خوانده می‌شود.
            </p>
            {appointments.error ? (
              <Retry
                error={appointments.error}
                onRetry={appointments.refresh}
              />
            ) : appointments.loading ? (
              <Loading rows={2} />
            ) : (
              <Field label="نوبت منتظر پرداخت">
                <select
                  required
                  value={selected}
                  onChange={(e) => setSelected(e.target.value)}
                >
                  <option value="">انتخاب کنید</option>
                  {appointments.data?.map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.reference} — {faNumber(a.deposit_toman)} تومان
                    </option>
                  ))}
                </select>
              </Field>
            )}
            {appointments.data?.length === 0 && (
              <Alert kind="info">
                نوبتی با وضعیت «منتظر پرداخت» وجود ندارد.
              </Alert>
            )}
            <div className="modal-actions">
              <button className="button primary" disabled={busy || !selected}>
                <Busy busy={busy}>ایجاد درخواست پرداخت</Busy>
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
function RefundDialog({
  payment,
  existingRefund,
  onClose,
  onDone,
}: {
  payment?: Payment;
  existingRefund?: Refund;
  onClose: () => void;
  onDone: () => void;
}) {
  const [amount, setAmount] = useState(
    payment?.amount_toman || existingRefund?.amount_toman || 0,
  );
  const [reason, setReason] = useState("");
  const [refund, setRefund] = useState<Refund | null>(existingRefund || null);
  const [reference, setReference] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [recorded, setRecorded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(newId());
  async function request(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      setRefund(
        await post<Refund>(`/operations/payments/${payment?.id}/refunds`, {
          amount_toman: amount,
          reason,
          idempotency_key: requestId.current,
        }),
      );
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function record(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(`/operations/refunds/${refund?.id}/record`, {
        provider_reference: reference,
        confirmed: true,
      });
      setRecorded(true);
      onDone();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="پیگیری بازپرداخت"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="modal-body">
        {recorded ? (
          <>
            <Alert kind="success">
              مدرک اجرای بازپرداخت در دفتر مالی ثبت شد.
            </Alert>
            <button className="button secondary" onClick={onClose}>
              بستن
            </button>
          </>
        ) : refund ? (
          <form onSubmit={record}>
            <Alert kind="info">
              درخواست ثبت شده است؛ هنوز پولی منتقل نشده. بازپرداخت واقعی را از
              مسیر درگاه یا بانک انجام دهید و سپس مدرک آن را ثبت کنید.
            </Alert>
            <Field label="شناسهٔ تأیید بانک یا درگاه">
              <input
                required
                dir="ltr"
                minLength={6}
                maxLength={120}
                value={reference}
                onChange={(e) => setReference(e.target.value)}
              />
            </Field>
            <label className="check-field">
              <input
                type="checkbox"
                required
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <span>بازگشت وجه واقعاً انجام شده و شناسه را بررسی کرده‌ام.</span>
            </label>
            <div className="modal-actions">
              <button className="button primary" disabled={busy || !confirmed}>
                <Busy busy={busy}>ثبت مدرک بازپرداخت</Busy>
              </button>
              <button
                type="button"
                className="button secondary"
                disabled={busy}
                onClick={onClose}
              >
                پیگیری در زمانی دیگر
              </button>
            </div>
          </form>
        ) : (
          <form onSubmit={request}>
            <p className="muted">
              ثبت درخواست، وجهی را خودکار منتقل نمی‌کند. اجرای واقعی و مدرک
              درگاه باید جداگانه بررسی شود.
            </p>
            <Field label="مبلغ بازپرداخت (تومان)">
              <input
                type="number"
                required
                min="1"
                max={payment?.amount_toman}
                value={amount}
                onChange={(e) => setAmount(Number(e.target.value))}
              />
            </Field>
            <Field label="دلیل بازپرداخت">
              <textarea
                required
                minLength={3}
                maxLength={100}
                rows={3}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </Field>
            <div className="modal-actions">
              <button className="button primary" disabled={busy}>
                <Busy busy={busy}>ثبت درخواست بازپرداخت</Busy>
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
        {error && <Alert>{error}</Alert>}
      </div>
    </Dialog>
  );
}

export function Payments({ admin }: { admin: boolean }) {
  const result = useRemote<Payment[]>("/operations/payments", 20000);
  const refunds = useRemote<Refund[]>(
    admin ? "/operations/refunds" : null,
    20000,
  );
  const appointments = useRemote<PaymentAppointment[]>(
    "/operations/payments/appointments",
  );
  const [existingRefund, setExistingRefund] = useState<Refund | null>(null);
  const [reviewRefund, setReviewRefund] = useState<Refund | null>(null);
  const [dispute, setDispute] = useState<Payment | null>(null);
  const [disputeVersion, setDisputeVersion] = useState(0);
  const [creating, setCreating] = useState(false);
  const [refund, setRefund] = useState<Payment | null>(null);
  const [simulate, setSimulate] = useState<Payment | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  function refresh() {
    result.refresh();
    refunds.refresh();
  }
  async function simulatePayment() {
    setBusy(true);
    setError("");
    try {
      await post(`/operations/payments/${simulate?.id}/simulate`, {});
      setSimulate(null);
      result.refresh();
      appointments.refresh();
      setMessage("رویداد پرداخت آزمایشی ثبت شد. هیچ وجهی دریافت نشده است.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      {error && <Alert onClose={() => setError("")}>{error}</Alert>}
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <section className="panel">
        <SectionTitle
          title="بیعانه و بازپرداخت"
          description="نوبت پرداخت‌دار فقط پس از تأیید معتبر درگاه قطعی می‌شود."
          action={
            <div className="inline-actions">
              <button
                className="icon-button"
                aria-label="تازه‌سازی پرداخت‌ها"
                onClick={result.refresh}
              >
                <RefreshCw size={18} />
              </button>
              <button
                className="button primary small"
                onClick={() => setCreating(true)}
              >
                <Plus size={16} />
                درخواست بیعانه
              </button>
            </div>
          }
        />
        {result.error ? (
          <Retry error={result.error} onRetry={result.refresh} />
        ) : result.loading ? (
          <Loading rows={3} />
        ) : result.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
          >
            <table>
              <thead>
                <tr>
                  <th>نوبت</th>
                  <th>مبلغ</th>
                  <th>وضعیت</th>
                  <th>مهلت پرداخت</th>
                  <th>اقدام</th>
                </tr>
              </thead>
              <tbody>
                {result.data.map((payment) => (
                  <tr key={payment.id}>
                    <td>
                      <strong>
                        {payment.appointment_reference ||
                          appointments.data?.find(
                            (a) => a.id === payment.appointment_id,
                          )?.reference ||
                          "نوبت مرکز"}
                      </strong>
                    </td>
                    <td>{faNumber(payment.amount_toman)} تومان</td>
                    <td>
                      <Status value={payment.status} />
                    </td>
                    <td>{faDate(payment.expires_at, true)}</td>
                    <td>
                      <div className="inline-actions">
                        {payment.payment_url?.startsWith("https://") &&
                          payment.status === "PENDING" && (
                            <a
                              className="button secondary small"
                              href={payment.payment_url}
                              target="_blank"
                              rel="noreferrer"
                            >
                              <ExternalLink size={15} />
                              درگاه
                            </a>
                          )}
                        {admin &&
                          [
                            "SETTLED",
                            "LATE_REQUIRES_REFUND",
                            "PARTIALLY_REFUNDED",
                            "REFUNDED",
                          ].includes(payment.status) && (
                            <button
                              className="button secondary small"
                              onClick={() => setDispute(payment)}
                            >
                              اختلاف درگاه
                            </button>
                          )}
                        {admin && payment.status === "DEMO_PENDING" && (
                          <button
                            className="button secondary small"
                            onClick={() => setSimulate(payment)}
                          >
                            پرداخت آزمایشی
                          </button>
                        )}
                        {admin &&
                          [
                            "SETTLED",
                            "LATE_REQUIRES_REFUND",
                            "PARTIALLY_REFUNDED",
                          ].includes(payment.status) && (
                            <button
                              className="button secondary small"
                              onClick={() => setRefund(payment)}
                            >
                              <RotateCcw size={14} />
                              بازپرداخت
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
            title="درخواست پرداختی ثبت نشده"
            description="برای نوبت‌های دارای بیعانه، درخواست پرداخت ایجاد کنید. اطلاعات کارت در هم‌آوا دریافت نمی‌شود."
          />
        )}
      </section>
      {admin && (
        <section className="panel catalog-panel">
          <SectionTitle
            title="دفتر بازپرداخت"
            description="درخواست‌های ثبت‌شده و مدرک اجرای واقعی را پیگیری کنید."
          />
          {refunds.error ? (
            <Retry error={refunds.error} onRetry={refunds.refresh} />
          ) : refunds.loading ? (
            <Loading rows={2} />
          ) : refunds.data?.length ? (
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
            >
              <table>
                <thead>
                  <tr>
                    <th>درخواست</th>
                    <th>مبلغ</th>
                    <th>وضعیت</th>
                    <th>مدرک</th>
                    <th>اقدام</th>
                  </tr>
                </thead>
                <tbody>
                  {refunds.data.map((item) => (
                    <tr key={item.id}>
                      <td>
                        <strong>{item.reason || "درخواست بازپرداخت"}</strong>
                        <small className="table-subline">
                          {item.created_at && faDate(item.created_at, true)}
                        </small>
                      </td>
                      <td>{faNumber(item.amount_toman)} تومان</td>
                      <td>
                        <Status value={item.status} />
                      </td>
                      <td>
                        <span className="ltr">
                          {item.provider_reference || "هنوز ثبت نشده"}
                        </span>
                      </td>
                      <td>
                        {[
                          "REQUESTED",
                          "RECONCILING",
                          "RECONCILIATION_REQUIRED",
                        ].includes(item.status) && (
                          <button
                            className="button secondary small"
                            onClick={() => setReviewRefund(item)}
                          >
                            بررسی و تطبیق
                          </button>
                        )}
                        {[
                          "REQUESTED",
                          "RECONCILING",
                          "RECONCILIATION_REQUIRED",
                        ].includes(item.status) && (
                          <button
                            className="button secondary small"
                            onClick={() => setExistingRefund(item)}
                          >
                            ثبت مدرک اجرا
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
              title="درخواست بازپرداختی ثبت نشده"
              description="درخواست‌های جدید پس از ثبت، تا زمان تکمیل در این بخش باقی می‌مانند."
            />
          )}
        </section>
      )}
      {admin && <Disputes key={disputeVersion} />}
      {reviewRefund && (
        <RefundReviewDialog
          refund={reviewRefund}
          onClose={() => setReviewRefund(null)}
          onSaved={() => {
            setReviewRefund(null);
            refresh();
            setMessage("نتیجهٔ بررسی بازپرداخت ثبت شد.");
          }}
        />
      )}
      {dispute && (
        <NewDispute
          payment={dispute}
          onClose={() => setDispute(null)}
          onSaved={() => {
            setDispute(null);
            setDisputeVersion((value) => value + 1);
            setMessage("پروندهٔ اختلاف درگاه ثبت شد.");
          }}
        />
      )}
      <div className="note-line">
        <CreditCard size={17} />
        <span>
          لغو نوبت، پرداخت دیرهنگام و بازپرداخت، وضعیت‌های جداگانه دارند. ثبت
          مدرک مالی به معنی انجام انتقال وجه توسط هم‌آوا نیست.
        </span>
      </div>
      {creating && (
        <PaymentLink
          onClose={() => setCreating(false)}
          onDone={result.refresh}
        />
      )}
      {refund && (
        <RefundDialog
          payment={refund}
          onClose={() => setRefund(null)}
          onDone={refresh}
        />
      )}
      {existingRefund && (
        <RefundDialog
          existingRefund={existingRefund}
          onClose={() => setExistingRefund(null)}
          onDone={refresh}
        />
      )}
      {simulate && (
        <Dialog
          title="پرداخت آزمایشی"
          onClose={() => {
            if (!busy) setSimulate(null);
          }}
        >
          <div className="modal-body">
            <Alert kind="info">
              این کار فقط مسیر تأیید پرداخت را در محیط نمایشی آزمایش می‌کند. هیچ
              پولی جابجا نمی‌شود.
            </Alert>
            <p>مبلغ نمایشی: {faNumber(simulate.amount_toman)} تومان</p>
            <div className="modal-actions">
              <button
                className="button primary"
                disabled={busy}
                onClick={() => void simulatePayment()}
              >
                <Busy busy={busy}>ثبت رویداد آزمایشی</Busy>
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => setSimulate(null)}
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
