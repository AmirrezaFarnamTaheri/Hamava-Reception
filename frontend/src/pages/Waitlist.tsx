import { useEffect, useState, type FormEvent } from "react";
import { CalendarPlus, Plus } from "lucide-react";
import {
  ApiError,
  errorText,
  faDate,
  faNumber,
  localToday,
  post,
} from "../api";
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
import type {
  Appointment,
  PaymentTerms,
  Practitioner,
  Service,
  Slot,
} from "../types";
import { SlotPicker } from "./Appointments";
import { PaymentTermsDetails } from "./PaymentPolicy";

interface OfferTerms {
  id: string;
  status: string;
  expires_at: string;
  display: string;
  deposit_toman: number;
  price_toman: number;
  payment_terms: PaymentTerms | null;
}
function useOfferAcceptance(id?: string) {
  const result = useRemote<OfferTerms>(
    id ? `/operations/waitlist/offers/${id}/terms` : null,
  );
  const [termsAccepted, setTermsAccepted] = useState(false);
  useEffect(() => {
    setTermsAccepted(false);
  }, [id, result.data]);
  const needsTerms = (result.data?.deposit_toman || 0) > 0;
  const current =
    !!result.data &&
    result.data.status === "OFFERED" &&
    new Date(result.data.expires_at) > new Date();
  const canAccept =
    !!result.data &&
    !result.loading &&
    !result.error &&
    current &&
    (!needsTerms || (!!result.data.payment_terms?.enabled && termsAccepted));
  const paymentFields =
    needsTerms && result.data?.payment_terms
      ? {
          payment_terms_version: result.data.payment_terms.version,
          payment_terms_accepted: termsAccepted,
        }
      : {};
  function handleFailure(error: unknown) {
    if (
      error instanceof ApiError &&
      [
        "PAYMENT_TERMS_CONFIRMATION_REQUIRED",
        "DEPOSIT_POLICY_NOT_PUBLISHED",
        "PAYMENT_POLICY_MERCHANT_CHANGED",
      ].includes(error.code)
    ) {
      setTermsAccepted(false);
      result.refresh();
    }
  }
  return {
    result,
    termsAccepted,
    setTermsAccepted,
    needsTerms,
    current,
    canAccept,
    paymentFields,
    handleFailure,
  };
}
function OfferFinancialReview({
  acceptance,
  busy,
}: {
  acceptance: ReturnType<typeof useOfferAcceptance>;
  busy: boolean;
}) {
  const { result, needsTerms, termsAccepted, setTermsAccepted, current } =
    acceptance;
  if (result.error)
    return <Retry error={result.error} onRetry={result.refresh} />;
  if (result.loading || !result.data) return <Loading rows={1} />;
  return (
    <>
      <div className="service-summary">
        <span>
          هزینهٔ اعلام‌شده:{" "}
          <strong>{faNumber(result.data.price_toman)} تومان</strong>
        </span>
        {needsTerms && (
          <span>بیعانه: {faNumber(result.data.deposit_toman)} تومان</span>
        )}
      </div>
      {!current && (
        <Alert kind="info">
          این پیشنهاد دیگر منتظر پاسخ معتبر نیست. فهرست پیشنهادها را تازه کنید.
        </Alert>
      )}
      {needsTerms &&
        (result.data.payment_terms?.enabled ? (
          <>
            <PaymentTermsDetails terms={result.data.payment_terms} />
            <label className="check-field">
              <input
                type="checkbox"
                required
                disabled={busy}
                checked={termsAccepted}
                onChange={(event) => setTermsAccepted(event.target.checked)}
              />
              <span>
                مراجعه‌کننده مبلغ بیعانه و شرایط لغو و بازپرداخت همین نسخه را
                خوانده یا شنیده و پذیرفته است.
              </span>
            </label>
          </>
        ) : (
          <Alert kind="info">
            پذیرش این پیشنهاد دارای بیعانه، تا انتشار شرایط معتبر مرکز در دسترس
            نیست.
          </Alert>
        ))}
    </>
  );
}
function OfferBookingResult({ booking }: { booking: Appointment }) {
  return (
    <>
      <Alert kind="success">پذیرش پیشنهاد در سامانه ثبت شد.</Alert>
      <div className="selected-appointment">
        <strong>{booking.patient_name}</strong>
        <span>{faNumber(booking.jalali_display)}</span>
        <span>
          کد پیگیری: <bdi>{booking.reference}</bdi>
        </span>
        <Status value={booking.status} />
      </div>
      {booking.status === "PENDING_PAYMENT" && (
        <Alert kind="info">
          نوبت تا تأیید پرداخت قطعی نیست.
          {booking.payment_expires_at &&
            ` مهلت پرداخت: ${faDate(booking.payment_expires_at, true)}.`}
        </Alert>
      )}
      {booking.payment_terms && (
        <PaymentTermsDetails terms={booking.payment_terms} />
      )}
    </>
  );
}

interface WaitlistEntry {
  id: string;
  provider_id: string;
  service_id: string;
  patient_name: string;
  phone_masked: string;
  date_from: string;
  date_to: string;
  status: string;
  offer_attempts: number;
}
interface Offer {
  id?: string;
  status: string;
  expires_at?: string;
  entry_id?: string;
}
interface SavedOffer {
  id: string;
  entry_id: string;
  status: string;
  expires_at: string;
  appointment_id: string | null;
  patient_name: string;
  phone_masked: string;
  start_at: string;
  display: string;
  created_at: string;
}
function AddWaitlist({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const providers = useRemote<Practitioner[]>("/practitioners");
  const services = useRemote<Service[]>("/services");
  const [form, setForm] = useState({
    provider_id: "",
    service_id: "",
    patient_name: "",
    phone: "",
    date_from: localToday(),
    date_to: localToday(),
    time_from: "09:00",
    time_to: "20:00",
    travel_minutes: 60,
    consent: false,
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
      await post("/operations/waitlist", form);
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="افزودن به فهرست انتظار"
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form className="modal-body" onSubmit={submit}>
        <div className="form-grid">
          <Field label="نام مراجعه‌کننده">
            <input
              required
              minLength={2}
              maxLength={120}
              value={form.patient_name}
              onChange={(e) => update("patient_name", e.target.value)}
            />
          </Field>
          <Field label="شماره همراه">
            <input
              required
              dir="ltr"
              type="tel"
              maxLength={30}
              value={form.phone}
              onChange={(e) => update("phone", e.target.value)}
            />
          </Field>
          <Field label="پزشک">
            <select
              required
              value={form.provider_id}
              onChange={(e) =>
                setForm((old) => ({
                  ...old,
                  provider_id: e.target.value,
                  service_id: "",
                }))
              }
            >
              <option value="">انتخاب کنید</option>
              {providers.data
                ?.filter((p) => p.active)
                .map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="خدمت">
            <select
              required
              value={form.service_id}
              onChange={(e) => update("service_id", e.target.value)}
            >
              <option value="">انتخاب کنید</option>
              {services.data
                ?.filter((s) => s.provider_ids.includes(form.provider_id))
                .map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
            </select>
          </Field>
          <Field label="از تاریخ">
            <input
              required
              type="date"
              value={form.date_from}
              onChange={(e) => update("date_from", e.target.value)}
            />
          </Field>
          <Field label="تا تاریخ">
            <input
              required
              type="date"
              min={form.date_from}
              value={form.date_to}
              onChange={(e) => update("date_to", e.target.value)}
            />
          </Field>
          <Field label="از ساعت">
            <input
              required
              type="time"
              value={form.time_from}
              onChange={(e) => update("time_from", e.target.value)}
            />
          </Field>
          <Field label="تا ساعت">
            <input
              required
              type="time"
              value={form.time_to}
              onChange={(e) => update("time_to", e.target.value)}
            />
          </Field>
        </div>
        <Field label="حداقل فرصت برای رسیدن (دقیقه)">
          <input
            required
            type="number"
            min="0"
            max="1440"
            value={form.travel_minutes}
            onChange={(e) => update("travel_minutes", Number(e.target.value))}
          />
        </Field>
        <label className="check-field">
          <input
            required
            type="checkbox"
            checked={form.consent}
            onChange={(e) => update("consent", e.target.checked)}
          />
          <span>
            مراجعه‌کننده دریافت پیشنهاد زمان آزاد در این بازه را پذیرفته است.
          </span>
        </label>
        {(error || providers.error || services.error) && (
          <Alert>{error || providers.error || services.error}</Alert>
        )}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !form.consent}>
            <Busy busy={busy}>ثبت در فهرست انتظار</Busy>
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

function OfferSlot({
  entries,
  onClose,
  onSaved,
}: {
  entries: WaitlistEntry[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [slot, setSlot] = useState<Slot | null>(null);
  const [offer, setOffer] = useState<Offer | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [booking, setBooking] = useState<Appointment | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selected = entries.find((e) => e.id === offer?.entry_id);
  const acceptance = useOfferAcceptance(offer?.id);
  async function create(e: FormEvent) {
    e.preventDefault();
    if (!slot) return;
    setBusy(true);
    setError("");
    try {
      setOffer(
        await post<Offer>("/operations/waitlist/offer", {
          slot_id: slot.slot_id,
        }),
      );
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function accept() {
    if (!offer?.id || !confirmed || !acceptance.canAccept) return;
    setBusy(true);
    setError("");
    try {
      setBooking(
        await post<Appointment>(
          `/operations/waitlist/offers/${offer.id}/accept`,
          { confirmed: true, ...acceptance.paymentFields },
        ),
      );
      onSaved();
    } catch (e) {
      setError(errorText(e));
      acceptance.handleFailure(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="پیشنهاد زمان آزاد"
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <div className="modal-body">
        {booking ? (
          <OfferBookingResult booking={booking} />
        ) : offer?.status === "OFFERED" ? (
          <>
            <Alert kind="info">
              زمان به‌طور موقت برای نخستین فرد واجد شرایط نگه داشته شده است. ثبت
              نهایی فقط پس از تأیید مراجعه‌کننده انجام می‌شود.
            </Alert>
            <div className="selected-appointment">
              <strong>{selected?.patient_name || "مراجعه‌کنندهٔ منتخب"}</strong>
              <span dir="ltr">{selected?.phone_masked}</span>
              <span>{slot?.display}</span>
              <span>
                پایان مهلت: {offer.expires_at && faDate(offer.expires_at, true)}
              </span>
            </div>
            <OfferFinancialReview acceptance={acceptance} busy={busy} />
            <label className="check-field">
              <input
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <span>
                مراجعه‌کننده این زمان را پذیرفته و به ثبت آن اجازه داده است.
              </span>
            </label>
            <button
              className="button primary"
              disabled={!confirmed || busy || !acceptance.canAccept}
              onClick={() => void accept()}
            >
              <Busy busy={busy}>ثبت پذیرش پیشنهاد</Busy>
            </button>
          </>
        ) : (
          <form onSubmit={create}>
            <p className="muted">
              سامانه بر اساس ترتیب ثبت، بازهٔ زمانی، فرصت رسیدن و رضایت، نخستین
              فرد واجد شرایط را انتخاب می‌کند.
            </p>
            {offer && (
              <Alert kind="info">
                {offer.status === "QUIET_HOURS"
                  ? "اکنون در ساعت آرامش مرکز هستیم. پیشنهاد را در زمان مجاز انجام دهید."
                  : "فرد واجد شرایطی برای این زمان پیدا نشد."}
              </Alert>
            )}
            <SlotPicker onChange={setSlot} />
            <div className="modal-actions">
              <button className="button primary" disabled={!slot || busy}>
                <Busy busy={busy}>انتخاب فرد و نگه‌داشتن زمان</Busy>
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
        {booking && (
          <button className="button secondary" onClick={onClose}>
            بستن
          </button>
        )}
      </div>
    </Dialog>
  );
}

function AcceptSavedOffer({
  offer,
  onClose,
  onSaved,
}: {
  offer: SavedOffer;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [booking, setBooking] = useState<Appointment | null>(null);
  const acceptance = useOfferAcceptance(offer.id);
  async function accept(e: FormEvent) {
    e.preventDefault();
    if (!confirmed || !acceptance.canAccept) return;
    setBusy(true);
    setError("");
    try {
      setBooking(
        await post<Appointment>(
          `/operations/waitlist/offers/${offer.id}/accept`,
          { confirmed: true, ...acceptance.paymentFields },
        ),
      );
      onSaved();
    } catch (e) {
      setError(errorText(e));
      acceptance.handleFailure(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="پاسخ به پیشنهاد زمان"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={accept}>
        {booking ? (
          <>
            <OfferBookingResult booking={booking} />
            <button
              type="button"
              className="button secondary"
              onClick={onClose}
            >
              بستن
            </button>
          </>
        ) : (
          <>
            <div className="selected-appointment">
              <strong>{offer.patient_name}</strong>
              <span dir="ltr">{offer.phone_masked}</span>
              <span>{offer.display}</span>
              <span>پایان مهلت: {faDate(offer.expires_at, true)}</span>
            </div>
            <OfferFinancialReview acceptance={acceptance} busy={busy} />
            <label className="check-field">
              <input
                required
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <span>
                مراجعه‌کننده این زمان را پذیرفته و به ثبت آن اجازه داده است.
              </span>
            </label>
            <div className="modal-actions">
              <button
                className="button primary"
                disabled={!confirmed || busy || !acceptance.canAccept}
              >
                <Busy busy={busy}>ثبت پذیرش پیشنهاد</Busy>
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

function RejectSavedOffer({
  offer,
  onClose,
  onSaved,
}: {
  offer: SavedOffer;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [reason, setReason] = useState("declined");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(`/operations/waitlist/offers/${offer.id}/reject`, {
        confirmed,
        reason,
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
      title="ثبت عدم پذیرش پیشنهاد"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <div className="selected-appointment">
          <strong>{offer.patient_name}</strong>
          <span>{offer.display}</span>
        </div>
        <Field label="نتیجهٔ پیگیری پیشنهاد">
          <select value={reason} onChange={(e) => setReason(e.target.value)}>
            <option value="declined">مراجعه‌کننده پیشنهاد را نپذیرفت</option>
            <option value="unreachable">دسترسی به مراجعه‌کننده ممکن نشد</option>
            <option value="timing">زمان پیشنهادی مناسب نبود</option>
            <option value="no_longer_needed">
              دیگر به فهرست انتظار نیاز ندارد
            </option>
          </select>
        </Field>
        <p className="field-hint">
          زمان نگه‌داشته‌شده آزاد می‌شود. انتخاب «دیگر نیاز ندارد»، فرد را از
          انتظار خارج می‌کند؛ در سایر موارد تا سقف مجاز پیشنهاد در فهرست باقی
          می‌ماند.
        </p>
        <label className="check-field">
          <input
            type="checkbox"
            required
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>
            نتیجهٔ بالا را بررسی کرده‌ام و آزاد شدن زمان را تأیید می‌کنم.
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>ثبت نتیجه و آزادسازی</Busy>
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

export function Waitlist() {
  const result = useRemote<WaitlistEntry[]>("/operations/waitlist", 20000);
  const offers = useRemote<SavedOffer[]>("/operations/waitlist/offers", 20000);
  const services = useRemote<Service[]>("/services");
  const [adding, setAdding] = useState(false);
  const [offering, setOffering] = useState(false);
  const [selectedOffer, setSelectedOffer] = useState<SavedOffer | null>(null);
  const [rejecting, setRejecting] = useState<SavedOffer | null>(null);
  const [message, setMessage] = useState("");
  function refresh() {
    result.refresh();
    offers.refresh();
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
          title="فهرست انتظار"
          description="زمان‌های آزاد را با رضایت و فرصت کافی به مراجعان پیشنهاد دهید."
          action={
            <div className="inline-actions">
              <button
                className="button secondary small"
                onClick={() => setOffering(true)}
              >
                <CalendarPlus size={16} />
                پیشنهاد زمان
              </button>
              <button
                className="button primary small"
                onClick={() => setAdding(true)}
              >
                <Plus size={16} />
                افزودن
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
                  <th>مراجعه‌کننده</th>
                  <th>خدمت</th>
                  <th>بازهٔ موردنظر</th>
                  <th>وضعیت</th>
                  <th>پیشنهادها</th>
                </tr>
              </thead>
              <tbody>
                {result.data.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{item.patient_name}</strong>
                      <small className="table-subline ltr">
                        {item.phone_masked}
                      </small>
                    </td>
                    <td>
                      {services.data?.find((s) => s.id === item.service_id)
                        ?.name || "خدمت مرکز"}
                    </td>
                    <td>
                      {faDate(item.date_from + "T12:00:00Z")} تا{" "}
                      {faDate(item.date_to + "T12:00:00Z")}
                    </td>
                    <td>
                      <Status value={item.status} />
                    </td>
                    <td>{faNumber(item.offer_attempts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="فهرست انتظار خالی است"
            description="افرادی که مایل‌اند از زمان‌های آزاد باخبر شوند، با رضایت خودشان به فهرست اضافه کنید."
          />
        )}
      </section>
      <section className="panel catalog-panel">
        <SectionTitle
          title="پیگیری پیشنهادها"
          description="پیشنهادهای باز را پس از دریافت پاسخ مراجعه‌کننده تکمیل کنید."
        />
        {offers.error ? (
          <Retry error={offers.error} onRetry={offers.refresh} />
        ) : offers.loading ? (
          <Loading rows={2} />
        ) : offers.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
          >
            <table>
              <thead>
                <tr>
                  <th>مراجعه‌کننده</th>
                  <th>زمان پیشنهادی</th>
                  <th>مهلت پاسخ</th>
                  <th>وضعیت</th>
                  <th>اقدام</th>
                </tr>
              </thead>
              <tbody>
                {offers.data.map((offer) => (
                  <tr key={offer.id}>
                    <td>
                      <strong>{offer.patient_name}</strong>
                      <small className="table-subline ltr">
                        {offer.phone_masked}
                      </small>
                    </td>
                    <td>{offer.display}</td>
                    <td>{faDate(offer.expires_at, true)}</td>
                    <td>
                      <Status
                        value={
                          offer.status === "OFFERED" &&
                          new Date(offer.expires_at) <= new Date()
                            ? "EXPIRED"
                            : offer.status
                        }
                      />
                    </td>
                    <td>
                      {offer.status === "OFFERED" &&
                      new Date(offer.expires_at) > new Date() ? (
                        <div className="inline-actions">
                          <button
                            className="button secondary small"
                            onClick={() => setSelectedOffer(offer)}
                          >
                            ثبت پاسخ مراجعه‌کننده
                          </button>
                          <button
                            className="button secondary small"
                            onClick={() => setRejecting(offer)}
                          >
                            عدم پذیرش
                          </button>
                        </div>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="هنوز پیشنهادی ثبت نشده"
            description="پس از انتخاب زمان آزاد، پیشنهاد و مهلت پاسخ اینجا نمایش داده می‌شود."
          />
        )}
      </section>
      {adding && (
        <AddWaitlist
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            refresh();
            setMessage("درخواست انتظار ثبت شد.");
          }}
        />
      )}
      {offering && (
        <OfferSlot
          entries={result.data || []}
          onClose={() => setOffering(false)}
          onSaved={refresh}
        />
      )}
      {rejecting && (
        <RejectSavedOffer
          offer={rejecting}
          onClose={() => setRejecting(null)}
          onSaved={() => {
            setRejecting(null);
            refresh();
            setMessage("عدم پذیرش پیشنهاد و آزاد شدن زمان ثبت شد.");
          }}
        />
      )}
      {selectedOffer && (
        <AcceptSavedOffer
          offer={selectedOffer}
          onClose={() => setSelectedOffer(null)}
          onSaved={refresh}
        />
      )}
    </>
  );
}
