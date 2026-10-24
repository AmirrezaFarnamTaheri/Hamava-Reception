import {
  PendingCalendarDialog,
  RemoteReadbackDialog,
  type CalendarOperation,
} from "./CalendarControl";
import { useEffect, useRef, useState, type FormEvent } from "react";
import {
  ArrowLeftRight,
  CalendarDays,
  Check,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  Plus,
  Pencil,
  Link2,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import {
  api,
  errorText,
  faDate,
  faNumber,
  faTime,
  localToday,
  newId,
  post,
} from "../api";
import {
  Alert,
  Busy,
  Dialog,
  Empty,
  Field,
  Loading,
  PageTitle,
  Retry,
  Status,
} from "../components";
import { useRemote } from "../hooks";
import type { Appointment, Practitioner, Service, Slot, User } from "../types";
import { hasPermission } from "../permissions";

import { ResponseLinkDialog } from "./ResponseLink";
import { PaymentTermsDetails, type PaymentPolicy } from "./PaymentPolicy";

function DateField({
  date,
  setDate,
}: {
  date: string;
  setDate: (v: string) => void;
}) {
  function shift(offset: number) {
    const next = new Date(date + "T12:00:00Z");
    next.setUTCDate(next.getUTCDate() + offset);
    setDate(next.toISOString().slice(0, 10));
  }
  return (
    <div className="date-control">
      <button
        type="button"
        className="icon-button"
        onClick={() => shift(-1)}
        aria-label="روز قبل"
      >
        <ChevronRight size={18} />
      </button>
      <label>
        <span>{faDate(date + "T12:00:00Z")}</span>
        <input
          type="date"
          value={date}
          onChange={(e) => {
            if (e.target.value) setDate(e.target.value);
          }}
          aria-label="انتخاب تاریخ میلادی"
        />
      </label>
      <button
        type="button"
        className="icon-button"
        onClick={() => shift(1)}
        aria-label="روز بعد"
      >
        <ChevronLeft size={18} />
      </button>
    </div>
  );
}

export function SlotPicker({
  initial,
  onChange,
  onServiceChange,
}: {
  initial?: Appointment;
  onChange: (slot: Slot | null) => void;
  onServiceChange?: (service: Service | null) => void;
}) {
  const providers = useRemote<Practitioner[]>("/practitioners");
  const services = useRemote<Service[]>("/services");
  const [providerId, setProviderId] = useState(initial?.provider_id || "");
  const [serviceId, setServiceId] = useState(initial?.service_id || "");
  const [date, setDate] = useState(initial?.local_date || localToday());
  const [selected, setSelected] = useState("");
  const slots = useRemote<Slot[]>(
    providerId && serviceId
      ? `/slots?provider_id=${encodeURIComponent(providerId)}&service_id=${encodeURIComponent(serviceId)}&date=${date}`
      : null,
  );
  const availableServices =
    services.data?.filter(
      (s) => !s.provider_ids?.length || s.provider_ids.includes(providerId),
    ) || [];
  useEffect(() => {
    setSelected("");
    onChange(null);
  }, [providerId, serviceId, date]); // reset a stale signed slot whenever selection criteria change
  const service = services.data?.find((s) => s.id === serviceId);
  useEffect(() => {
    onServiceChange?.(service || null);
  }, [service, onServiceChange]);
  return (
    <div className="slot-picker">
      {providers.error && (
        <Retry error={providers.error} onRetry={providers.refresh} />
      )}
      <div className="form-grid">
        <Field label="پزشک یا ارائه‌دهنده">
          <select
            value={providerId}
            required
            onChange={(e) => {
              setProviderId(e.target.value);
              setServiceId("");
            }}
          >
            <option value="">انتخاب کنید</option>
            {providers.data
              ?.filter((p) => p.active)
              .map((p) => (
                <option value={p.id} key={p.id}>
                  {p.name}
                </option>
              ))}
          </select>
        </Field>
        <Field label="خدمت">
          <select
            required
            value={serviceId}
            disabled={!providerId}
            onChange={(e) => setServiceId(e.target.value)}
          >
            <option value="">انتخاب کنید</option>
            {availableServices.map((s) => (
              <option value={s.id} key={s.id}>
                {s.name} — {faNumber(s.duration_minutes)} دقیقه
              </option>
            ))}
          </select>
        </Field>
      </div>
      {services.error && (
        <Retry error={services.error} onRetry={services.refresh} />
      )}
      <div className="slot-date">
        <span className="field-label">روز مراجعه</span>
        <DateField date={date} setDate={setDate} />
      </div>
      {service && (
        <div className="service-summary">
          <span>
            هزینهٔ اعلام‌شده:{" "}
            <strong>{faNumber(service.price_toman)} تومان</strong>
          </span>
          {service.deposit_toman > 0 && (
            <span>بیعانه: {faNumber(service.deposit_toman)} تومان</span>
          )}
          {service.requires_approval && (
            <Status value="PENDING_STAFF_APPROVAL" />
          )}
        </div>
      )}
      {slots.loading && providerId && serviceId ? (
        <Loading rows={1} />
      ) : slots.error ? (
        <Retry error={slots.error} onRetry={slots.refresh} />
      ) : slots.data?.length ? (
        <fieldset className="time-fieldset">
          <legend>زمان‌های آزاد</legend>
          <div className="slot-grid">
            {slots.data.map((slot) => (
              <label
                className={`slot-option ${selected === slot.slot_id ? "selected" : ""}`}
                key={slot.slot_id}
              >
                <input
                  type="radio"
                  name="slot"
                  required
                  value={slot.slot_id}
                  checked={selected === slot.slot_id}
                  onChange={() => {
                    setSelected(slot.slot_id);
                    onChange(slot);
                  }}
                />
                <span>{faNumber(slot.local_time)}</span>
                {selected === slot.slot_id && <Check size={14} />}
              </label>
            ))}
          </div>
        </fieldset>
      ) : providerId && serviceId ? (
        <div className="inline-empty">
          <CalendarDays size={20} />
          <p>برای این روز زمان آزادی پیدا نشد. روز دیگری را انتخاب کنید.</p>
        </div>
      ) : (
        <p className="field-hint">
          پزشک و خدمت را انتخاب کنید تا زمان‌های واقعی مرکز نمایش داده شوند.
        </p>
      )}
    </div>
  );
}

function BookingDialog({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: (appointment: Appointment | CalendarOperation) => void;
}) {
  const [slot, setSlot] = useState<Slot | null>(null);
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [reminder, setReminder] = useState(false);
  const [service, setService] = useState<Service | null>(null);
  const [termsAccepted, setTermsAccepted] = useState(false);
  const paymentPolicy = useRemote<PaymentPolicy>(
    service && service.deposit_toman > 0 ? "/operations/payment-policy" : null,
  );
  const depositRequired = !!service && service.deposit_toman > 0;
  const actualDeposit =
    depositRequired &&
    !!paymentPolicy.data &&
    !paymentPolicy.data.demonstration;
  const termsBlocked =
    depositRequired &&
    (paymentPolicy.loading ||
      !!paymentPolicy.error ||
      !paymentPolicy.data ||
      (!!paymentPolicy.data.published_at && !paymentPolicy.data.enabled) ||
      (actualDeposit &&
        (!paymentPolicy.data.enabled ||
          !paymentPolicy.data.merchant_ready ||
          !termsAccepted)));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(newId());
  useEffect(() => {
    setTermsAccepted(false);
  }, [service?.id, paymentPolicy.data?.version]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!slot || !confirmed || termsBlocked) return;
    setBusy(true);
    setError("");
    try {
      const created = await post<Appointment | CalendarOperation>(
        "/appointments",
        {
          slot_id: slot.slot_id,
          patient_name: name.trim(),
          phone: phone.trim(),
          idempotency_key: requestId.current,
          confirmed: true,
          reminder_opt_in: reminder,
          ...(actualDeposit && paymentPolicy.data
            ? {
                payment_terms_version: paymentPolicy.data.version,
                payment_terms_accepted: termsAccepted,
              }
            : {}),
        },
      );
      onSaved(created);
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="ثبت نوبت جدید"
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form onSubmit={submit} className="modal-body">
        <p className="muted">
          نوبت پس از بررسی مجدد زمان و ثبت در تقویم تأیید می‌شود.
        </p>
        <SlotPicker onChange={setSlot} onServiceChange={setService} />
        <div className="form-divider" />
        <div className="form-grid">
          <Field label="نام مراجعه‌کننده">
            <input
              value={name}
              required
              minLength={2}
              maxLength={120}
              autoComplete="name"
              onChange={(e) => setName(e.target.value)}
              placeholder="نام و نام خانوادگی"
            />
          </Field>
          <Field label="شمارهٔ همراه" hint="شمارهٔ مورد تأیید مراجعه‌کننده">
            <input
              value={phone}
              required
              type="tel"
              inputMode="tel"
              autoComplete="tel"
              dir="ltr"
              maxLength={18}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="۰۹۱۲۱۲۳۴۵۶۷"
            />
          </Field>
        </div>
        {slot && (
          <div className="booking-readback">
            <CalendarDays size={18} />
            <span>
              {slot.display ||
                `${faDate(slot.start_at)}، ساعت ${faTime(slot.start_at)}`}
            </span>
          </div>
        )}
        {depositRequired &&
          (paymentPolicy.error ? (
            <Retry
              error={paymentPolicy.error}
              onRetry={paymentPolicy.refresh}
            />
          ) : paymentPolicy.loading ? (
            <Loading rows={2} />
          ) : (
            paymentPolicy.data && (
              <>
                {paymentPolicy.data.demonstration &&
                !paymentPolicy.data.published_at ? (
                  <Alert kind="info">
                    بیعانهٔ این نوبت صرفاً ساختگی است. ثبت و تسویهٔ نمایشی، پول
                    واقعی جابه‌جا نمی‌کند.
                  </Alert>
                ) : (
                  <PaymentTermsDetails
                    terms={{
                      ...paymentPolicy.data,
                      synthetic: paymentPolicy.data.demonstration,
                    }}
                  />
                )}
                {paymentPolicy.data.published_at &&
                  !paymentPolicy.data.enabled && (
                    <Alert kind="info">
                      دریافت بیعانه طبق شرایط منتشرشدهٔ این مرکز غیرفعال است.
                    </Alert>
                  )}
                {actualDeposit &&
                  (!paymentPolicy.data.enabled ||
                    !paymentPolicy.data.merchant_ready) && (
                    <Alert kind="info">
                      ثبت نوبت دارای بیعانه تا انتشار شرایط و آماده‌شدن پذیرندهٔ
                      این مرکز در دسترس نیست.
                    </Alert>
                  )}
                {actualDeposit && (
                  <label className="check-field">
                    <input
                      type="checkbox"
                      required
                      checked={termsAccepted}
                      onChange={(event) =>
                        setTermsAccepted(event.target.checked)
                      }
                    />
                    <span>
                      مراجعه‌کننده شرایط بیعانه، لغو و بازپرداخت همین نسخه را
                      خوانده یا شنیده و پذیرفته است.
                    </span>
                  </label>
                )}
              </>
            )
          ))}
        <label className="check-field">
          <input
            type="checkbox"
            checked={confirmed}
            required
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>زمان و اطلاعات نوبت را با مراجعه‌کننده تأیید کرده‌ام.</span>
        </label>
        <label className="check-field">
          <input
            type="checkbox"
            checked={reminder}
            onChange={(e) => setReminder(e.target.checked)}
          />
          <span>مراجعه‌کننده دریافت یادآوری نوبت را پذیرفته است.</span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            type="submit"
            className="button primary"
            disabled={busy || !slot || !confirmed || termsBlocked}
          >
            <Busy busy={busy}>ثبت نوبت</Busy>
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

export function AppointmentAction({
  appointment,
  action,
  onClose,
  onSaved,
}: {
  appointment: Appointment;
  action: "cancel" | "reschedule";
  onClose: () => void;
  onSaved: (appointment: Appointment | CalendarOperation) => void;
}) {
  const [slot, setSlot] = useState<Slot | null>(null);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(newId());
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const updated = await post<Appointment | CalendarOperation>(
        `/appointments/${appointment.id}/${action}`,
        {
          version: appointment.version,
          idempotency_key: requestId.current,
          ...(action === "cancel" ? { reason } : { slot_id: slot?.slot_id }),
        },
      );
      onSaved(updated);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={action === "cancel" ? "لغو نوبت" : "جابجایی نوبت"}
      onClose={() => {
        if (!busy) onClose();
      }}
      wide={action === "reschedule"}
    >
      <form className="modal-body" onSubmit={submit}>
        <div className="selected-appointment">
          <strong>{appointment.patient_name}</strong>
          <span>
            {appointment.service_name} · {appointment.provider_name}
          </span>
          <span>
            {appointment.jalali_display || faDate(appointment.start_at, true)}
          </span>
        </div>
        {action === "reschedule" ? (
          <>
            <p className="muted">نوبت قبلی تا ثبت موفق زمان جدید حفظ می‌شود.</p>
            <SlotPicker initial={appointment} onChange={setSlot} />
          </>
        ) : (
          <>
            <p>با لغو این نوبت، زمان برای مراجعه‌کنندگان دیگر آزاد می‌شود.</p>
            <Field label="دلیل لغو (اختیاری)">
              <textarea
                maxLength={400}
                value={reason}
                rows={3}
                onChange={(e) => setReason(e.target.value)}
                placeholder="دلیل کوتاه و بدون اطلاعات پزشکی"
              />
            </Field>
            {appointment.deposit_toman > 0 && (
              <Alert kind="info">
                لغو نوبت به‌تنهایی به معنای بازگشت وجه نیست. وضعیت بیعانه را در
                فرایند مالی بررسی کنید.
              </Alert>
            )}
          </>
        )}
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className={`button ${action === "cancel" ? "danger" : "primary"}`}
            disabled={busy || (action === "reschedule" && !slot)}
          >
            <Busy busy={busy}>
              {action === "cancel" ? "تأیید لغو نوبت" : "ثبت زمان جدید"}
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

export function AppointmentCorrection({
  appointment,
  onClose,
  onSaved,
}: {
  appointment: Appointment;
  onClose: () => void;
  onSaved: (appointment: Appointment) => void;
}) {
  const [name, setName] = useState(appointment.patient_name);
  const [phone, setPhone] = useState("");
  const [changeSlot, setChangeSlot] = useState(false);
  const [slot, setSlot] = useState<Slot | null>(null);
  const [acceptPrice, setAcceptPrice] = useState(false);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(newId());
  const changed =
    name.trim() !== appointment.patient_name ||
    !!phone.trim() ||
    (changeSlot && !!slot);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!changed || !confirmed) return;
    setBusy(true);
    setError("");
    try {
      const updated = await api<Appointment>(
        `/operations/appointments/${appointment.id}/details`,
        {
          method: "PATCH",
          body: JSON.stringify({
            version: appointment.version,
            idempotency_key: requestId.current,
            reason,
            confirmed,
            ...(name.trim() !== appointment.patient_name
              ? { patient_name: name.trim() }
              : {}),
            ...(phone.trim() ? { phone: phone.trim() } : {}),
            ...(changeSlot && slot
              ? { slot_id: slot.slot_id, accept_price_change: acceptPrice }
              : {}),
          }),
        },
      );
      onSaved(updated);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="اصلاح اطلاعات نوبت"
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form className="modal-body" onSubmit={submit}>
        <div className="selected-appointment">
          <strong>
            {appointment.patient_name} · {faNumber(appointment.reference)}
          </strong>
          <span>
            {appointment.provider_name} · {appointment.service_name}
          </span>
          <span>{appointment.jalali_display}</span>
          <span>
            تعرفهٔ ثبت‌شده: {faNumber(appointment.price_toman)} تومان · بیعانه:{" "}
            {faNumber(appointment.deposit_toman)} تومان
          </span>
        </div>
        <div className="form-grid">
          <Field label="نام صحیح مراجعه‌کننده">
            <input
              value={name}
              required
              minLength={2}
              maxLength={160}
              onChange={(e) => setName(e.target.value)}
            />
          </Field>
          <Field
            label="شمارهٔ همراه صحیح (در صورت تغییر)"
            hint={`شمارهٔ فعلی: ${appointment.phone_masked}`}
          >
            <input
              type="tel"
              dir="ltr"
              value={phone}
              maxLength={20}
              onChange={(e) => setPhone(e.target.value)}
              placeholder="09…"
            />
          </Field>
        </div>
        {phone.trim() && (
          <Alert kind="info">
            پس از تغییر شماره، پیام‌های صف‌شده برای شمارهٔ قبلی متوقف می‌شوند و
            رضایت یادآوری باید دوباره دریافت شود.
          </Alert>
        )}
        <label className="check-field">
          <input
            type="checkbox"
            checked={changeSlot}
            onChange={(e) => {
              setChangeSlot(e.target.checked);
              setSlot(null);
              setAcceptPrice(false);
            }}
          />
          <span>پزشک، خدمت یا زمان نوبت هم نیاز به اصلاح دارد.</span>
        </label>
        {changeSlot && (
          <>
            <SlotPicker initial={appointment} onChange={setSlot} />
            <label className="check-field">
              <input
                type="checkbox"
                checked={acceptPrice}
                onChange={(e) => setAcceptPrice(e.target.checked)}
              />
              <span>
                در صورت تفاوت تعرفه، قیمت نمایش‌داده‌شدهٔ خدمت جدید را با
                مراجعه‌کننده تأیید کرده‌ام.
              </span>
            </label>
            <p className="field-hint">
              تفاوت بیعانه به بررسی مالی جداگانه نیاز دارد. تا ثبت موفق اصلاح،
              اطلاعات و زمان قبلی حفظ می‌شوند.
            </p>
          </>
        )}
        <Field label="دلیل اصلاح">
          <textarea
            required
            minLength={3}
            maxLength={500}
            rows={3}
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
          <span>
            هویت مراجعه‌کننده و اصلاح‌های بالا را با او تأیید کرده‌ام.
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || !changed || !confirmed || (changeSlot && !slot)}
          >
            <Busy busy={busy}>ثبت اصلاحات</Busy>
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

function AppointmentCards({
  items,
  canWrite,
  busyId,
  onOutcome,
  onManage,
  onCorrect,
  onRespond,
  onApprove,
  onReadback,
}: {
  items: Appointment[];
  canWrite: boolean;
  busyId: string;
  onOutcome: (appointment: Appointment, outcome: string) => void;
  onManage: (appointment: Appointment, action: "cancel" | "reschedule") => void;
  onCorrect: (appointment: Appointment) => void;
  onRespond: (appointment: Appointment) => void;
  onApprove: (appointment: Appointment) => void;
  onReadback: (appointment: Appointment) => void;
}) {
  return (
    <div className="appointment-cards">
      {items.map((appointment) => {
        const active = !["CANCELED", "EXPIRED"].includes(appointment.status);
        const started = new Date(appointment.start_at) <= new Date();
        return (
          <article
            className="appointment-card"
            key={appointment.id}
            data-appointment-id={appointment.id}
          >
            <div className="appointment-card-time">
              <strong>{faTime(appointment.start_at)}</strong>
              <Status value={appointment.status} />
            </div>
            <h2>{appointment.patient_name}</h2>
            <p className="appointment-card-service">
              {appointment.provider_name} <span>·</span>{" "}
              {appointment.service_name}
            </p>
            <div className="appointment-card-reference">
              <span>کد {faNumber(appointment.reference)}</span>
              <bdi>{appointment.phone_masked}</bdi>
            </div>
            {!!appointment.disruptions?.filter(
              (item) => item.state !== "RESOLVED",
            ).length && (
              <div className="appointment-card-notices">
                {appointment.disruptions
                  .filter((item) => item.state !== "RESOLVED")
                  .map((item) => (
                    <Status key={item.id} value={item.state} />
                  ))}
              </div>
            )}
            {appointment.deposit_toman > 0 && (
              <div className="appointment-card-payment">
                <span>بیعانه: {faNumber(appointment.deposit_toman)} تومان</span>
                <Status value={appointment.payment_status} />
                {appointment.status === "PENDING_PAYMENT" &&
                  appointment.payment_expires_at && (
                    <small>
                      مهلت پرداخت:{" "}
                      {faDate(appointment.payment_expires_at, true)}
                    </small>
                  )}
              </div>
            )}
            {appointment.attendance ? (
              <div className="appointment-card-attendance">
                <span>نتیجهٔ مراجعه</span>
                <Status value={appointment.attendance} />
              </div>
            ) : appointment.authority !== "external" &&
              appointment.status === "CONFIRMED" &&
              started &&
              canWrite ? (
              <fieldset
                className="appointment-attendance-actions"
                disabled={busyId === appointment.id}
              >
                <legend>نتیجهٔ مراجعه</legend>
                <button
                  className="button secondary"
                  onClick={() => onOutcome(appointment, "ATTENDED")}
                >
                  مراجعه کرد
                </button>
                <button
                  className="button secondary"
                  onClick={() => onOutcome(appointment, "NO_SHOW")}
                >
                  نیامد
                </button>
              </fieldset>
            ) : null}
            {appointment.authority === "external" && (
              <button
                className="button secondary"
                onClick={() => onReadback(appointment)}
              >
                بررسی در تقویم مرجع
              </button>
            )}
            {canWrite && active && appointment.authority !== "external" && (
              <details className="appointment-card-actions">
                <summary>
                  مدیریت نوبت <ChevronLeft size={16} />
                </summary>
                <fieldset disabled={busyId === appointment.id}>
                  {appointment.status === "PENDING_STAFF_APPROVAL" && (
                    <button
                      className="button primary"
                      onClick={() => onApprove(appointment)}
                    >
                      <CheckCheck size={17} />
                      تأیید نوبت
                    </button>
                  )}
                  {appointment.status === "CONFIRMED" && !started && (
                    <button
                      className="button secondary"
                      onClick={() => onRespond(appointment)}
                    >
                      <Link2 size={17} />
                      پیوند پاسخ به نوبت
                    </button>
                  )}
                  {!appointment.attendance && (
                    <button
                      className="button secondary"
                      onClick={() => onCorrect(appointment)}
                    >
                      <Pencil size={17} />
                      اصلاح اطلاعات
                    </button>
                  )}
                  <button
                    className="button secondary"
                    onClick={() => onManage(appointment, "reschedule")}
                  >
                    <ArrowLeftRight size={17} />
                    جابجایی نوبت
                  </button>
                  <button
                    className="button danger-quiet"
                    onClick={() => onManage(appointment, "cancel")}
                  >
                    <X size={17} />
                    لغو نوبت
                  </button>
                </fieldset>
              </details>
            )}
          </article>
        );
      })}
    </div>
  );
}

export function Appointments({ user, search }: { user: User; search: string }) {
  const canWrite = hasPermission(user, "appointment:write");
  const [compact, setCompact] = useState(
    () => matchMedia("(max-width: 650px)").matches,
  );
  useEffect(() => {
    const media = matchMedia("(max-width: 650px)");
    const update = () => setCompact(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const [date, setDate] = useState(localToday());
  const [query, setQuery] = useState(
    new URLSearchParams(search).get("q") || "",
  );
  const [filter, setFilter] = useState("");
  const [creating, setCreating] = useState(
    canWrite && new URLSearchParams(search).has("new"),
  );
  const [selected, setSelected] = useState<{
    appointment: Appointment;
    action: "cancel" | "reschedule";
  } | null>(null);
  const [correction, setCorrection] = useState<Appointment | null>(null);
  const [responseLink, setResponseLink] = useState<Appointment | null>(null);
  const [remoteReadback, setRemoteReadback] = useState<Appointment | null>(
    null,
  );
  const [pendingCalendar, setPendingCalendar] =
    useState<CalendarOperation | null>(null);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [busyId, setBusyId] = useState("");
  useEffect(() => {
    const params = new URLSearchParams(search);
    if (params.has("new") && canWrite) setCreating(true);
    if (params.has("q")) setQuery(params.get("q") || "");
  }, [search, canWrite]);
  function closeCreating() {
    setCreating(false);
    const url = new URL(location.href);
    url.searchParams.delete("new");
    history.replaceState({}, "", url.pathname + url.search);
    window.dispatchEvent(new PopStateEvent("popstate"));
  }
  const appointments = useRemote<Appointment[]>(
    `/appointments?date=${date}`,
    20000,
  );
  const items =
    appointments.data
      ?.slice()
      .sort(
        (a, b) =>
          new Date(a.start_at).getTime() - new Date(b.start_at).getTime(),
      )
      .filter(
        (a) =>
          (!filter || a.status === filter) &&
          (!query ||
            `${a.patient_name} ${a.reference} ${a.provider_name}`
              .toLowerCase()
              .includes(query.toLowerCase())),
      ) || [];
  async function outcome(a: Appointment, outcome: string) {
    if (!canWrite) return;
    setBusyId(a.id);
    setError("");
    try {
      await api(`/appointments/${a.id}/outcome`, {
        method: "PATCH",
        body: JSON.stringify({ outcome, version: a.version }),
      });
      appointments.refresh();
      setNotice("وضعیت مراجعه ثبت شد.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusyId("");
    }
  }
  async function approve(a: Appointment) {
    if (!canWrite) return;
    setBusyId(a.id);
    setError("");
    try {
      await post(`/appointments/${a.id}/approve`, { version: a.version });
      appointments.refresh();
      setNotice("نوبت پس از بررسی سامانه تأیید شد.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusyId("");
    }
  }
  function saved(appointment: Appointment | CalendarOperation) {
    if ("operation_status" in appointment) {
      closeCreating();
      setSelected(null);
      setPendingCalendar(appointment);
      appointments.refresh();
      return;
    }
    setDate(
      appointment.local_date ||
        new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Tehran" }).format(
          new Date(appointment.start_at),
        ),
    );
    closeCreating();
    setSelected(null);
    setCorrection(null);
    appointments.refresh();
    setNotice("تغییرات نوبت ثبت شد. وضعیت نهایی در فهرست قابل مشاهده است.");
  }
  return (
    <>
      <PageTitle
        eyebrow="تقویم مرکز"
        title="نوبت‌ها"
        description="زمان‌های واقعی، اطلاعات روشن و کنترل کامل بر برنامهٔ مرکز."
        action={
          canWrite && (
            <button
              className="button primary"
              onClick={() => setCreating(true)}
            >
              <Plus size={18} />
              ثبت نوبت
            </button>
          )
        }
      />
      {notice && (
        <Alert kind="success" onClose={() => setNotice("")}>
          {notice}
        </Alert>
      )}
      {error && <Alert onClose={() => setError("")}>{error}</Alert>}
      {!canWrite && (
        <Alert kind="info">
          نوبت‌ها برای حساب شما قابل مشاهده‌اند. ثبت یا تغییر نوبت به دسترسی تیم
          پذیرش نیاز دارد.
        </Alert>
      )}
      <section className="panel">
        <div className="table-toolbar">
          <DateField date={date} setDate={setDate} />
          <div className="toolbar-filters">
            <label className="search-input">
              <Search size={17} />
              <input
                aria-label="جستجوی نوبت"
                placeholder="نام یا کد نوبت…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </label>
            <select
              aria-label="فیلتر وضعیت"
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            >
              <option value="">همهٔ وضعیت‌ها</option>
              <option value="CONFIRMED">تأیید شده</option>
              <option value="PENDING_PAYMENT">منتظر پرداخت</option>
              <option value="PENDING_STAFF_APPROVAL">نیازمند تأیید</option>
              <option value="CANCELED">لغو شده</option>
            </select>
            <button
              className="icon-button"
              aria-label="تازه‌سازی نوبت‌ها"
              onClick={appointments.refresh}
            >
              <RefreshCw size={18} />
            </button>
          </div>
        </div>
        {appointments.error ? (
          <Retry error={appointments.error} onRetry={appointments.refresh} />
        ) : appointments.loading ? (
          <Loading rows={4} />
        ) : items.length ? (
          <>
            {compact ? (
              <AppointmentCards
                items={items}
                canWrite={canWrite}
                busyId={busyId}
                onOutcome={(appointment, value) =>
                  void outcome(appointment, value)
                }
                onManage={(appointment, action) =>
                  setSelected({ appointment, action })
                }
                onCorrect={setCorrection}
                onRespond={setResponseLink}
                onApprove={(appointment) => void approve(appointment)}
                onReadback={setRemoteReadback}
              />
            ) : (
              <div
                className="table-scroll appointments-table"
                tabIndex={0}
                role="region"
                aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
              >
                <table>
                  <thead>
                    <tr>
                      <th>زمان</th>
                      <th>مراجعه‌کننده</th>
                      <th>پزشک و خدمت</th>
                      <th>وضعیت نوبت</th>
                      <th>مراجعه</th>
                      <th>
                        <span className="sr-only">اقدام‌ها</span>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((a) => (
                      <tr key={a.id}>
                        <td>
                          <strong className="time-value">
                            {faTime(a.start_at)}
                          </strong>
                          <small className="table-subline">
                            {faNumber(a.reference)}
                          </small>
                        </td>
                        <td>
                          <strong>{a.patient_name}</strong>
                          <small className="table-subline ltr">
                            {a.phone_masked}
                          </small>
                        </td>
                        <td>
                          <strong>{a.provider_name}</strong>
                          <small className="table-subline">
                            {a.service_name}
                          </small>
                        </td>
                        <td>
                          <Status value={a.status} />
                          {a.disruptions
                            ?.filter((item) => item.state !== "RESOLVED")
                            .map((item) => (
                              <small key={item.id} className="table-subline">
                                <Status value={item.state} />
                              </small>
                            ))}
                          {a.deposit_toman > 0 && (
                            <small className="table-subline">
                              بیعانه: {faNumber(a.deposit_toman)} تومان
                            </small>
                          )}
                          {a.status === "PENDING_PAYMENT" &&
                            a.payment_expires_at && (
                              <small className="table-subline">
                                مهلت پرداخت:{" "}
                                {faDate(a.payment_expires_at, true)}
                              </small>
                            )}
                        </td>
                        <td>
                          {a.attendance ? (
                            <Status value={a.attendance} />
                          ) : canWrite &&
                            a.status === "CONFIRMED" &&
                            new Date(a.start_at) <= new Date() ? (
                            <div className="inline-actions">
                              <button
                                disabled={busyId === a.id}
                                className="mini-button"
                                onClick={() => void outcome(a, "ATTENDED")}
                              >
                                مراجعه کرد
                              </button>
                              <button
                                disabled={busyId === a.id}
                                className="mini-button"
                                onClick={() => void outcome(a, "NO_SHOW")}
                              >
                                نیامد
                              </button>
                            </div>
                          ) : (
                            <span className="muted">—</span>
                          )}
                        </td>
                        <td>
                          {a.authority === "external" && (
                            <button
                              className="button secondary small"
                              onClick={() => setRemoteReadback(a)}
                            >
                              بررسی در تقویم مرجع
                            </button>
                          )}
                          {canWrite && a.authority !== "external" && (
                            <div className="row-actions">
                              {a.status === "CONFIRMED" &&
                                new Date(a.start_at) > new Date() && (
                                  <button
                                    className="icon-button"
                                    title="پیوند پاسخ به نوبت"
                                    aria-label={`پیوند پاسخ ${a.patient_name}`}
                                    onClick={() => setResponseLink(a)}
                                  >
                                    <Link2 size={17} />
                                  </button>
                                )}
                              {a.status === "PENDING_STAFF_APPROVAL" && (
                                <button
                                  className="icon-button"
                                  title="تأیید نوبت"
                                  aria-label={`تأیید نوبت ${a.patient_name}`}
                                  disabled={busyId === a.id}
                                  onClick={() => void approve(a)}
                                >
                                  <CheckCheck size={18} />
                                </button>
                              )}
                              {!["CANCELED", "EXPIRED"].includes(a.status) && (
                                <>
                                  {!a.attendance && (
                                    <button
                                      className="icon-button"
                                      aria-label={`اصلاح اطلاعات ${a.patient_name}`}
                                      title="اصلاح اطلاعات"
                                      onClick={() => setCorrection(a)}
                                    >
                                      <Pencil size={17} />
                                    </button>
                                  )}
                                  <button
                                    className="icon-button"
                                    title="جابجایی نوبت"
                                    aria-label={`جابجایی نوبت ${a.patient_name}`}
                                    onClick={() =>
                                      setSelected({
                                        appointment: a,
                                        action: "reschedule",
                                      })
                                    }
                                  >
                                    <ArrowLeftRight size={18} />
                                  </button>
                                  <button
                                    className="icon-button danger-text"
                                    title="لغو نوبت"
                                    aria-label={`لغو نوبت ${a.patient_name}`}
                                    onClick={() =>
                                      setSelected({
                                        appointment: a,
                                        action: "cancel",
                                      })
                                    }
                                  >
                                    <X size={18} />
                                  </button>
                                </>
                              )}
                            </div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : (
          <Empty
            title={
              query || filter
                ? "نوبتی با این مشخصات پیدا نشد"
                : "برای این روز نوبتی ثبت نشده"
            }
            description="روز دیگری را انتخاب کنید یا یک نوبت جدید ثبت کنید."
          />
        )}
        <div className="table-footer">
          <span>{faNumber(items.length)} نوبت در این روز</span>
          <span>تمام زمان‌ها به وقت تهران</span>
        </div>
      </section>
      {remoteReadback && (
        <RemoteReadbackDialog
          appointmentId={remoteReadback.id}
          canWrite={canWrite}
          onClose={() => setRemoteReadback(null)}
          onManage={(appointment, action) => {
            setRemoteReadback(null);
            setSelected({ appointment, action });
          }}
        />
      )}
      {pendingCalendar && (
        <PendingCalendarDialog
          initial={pendingCalendar}
          onClose={() => {
            setPendingCalendar(null);
            appointments.refresh();
          }}
        />
      )}
      {creating && <BookingDialog onClose={closeCreating} onSaved={saved} />}
      {responseLink && (
        <ResponseLinkDialog
          appointment={responseLink}
          onClose={() => setResponseLink(null)}
        />
      )}
      {correction && (
        <AppointmentCorrection
          appointment={correction}
          onClose={() => setCorrection(null)}
          onSaved={saved}
        />
      )}
      {selected && (
        <AppointmentAction
          {...selected}
          onClose={() => setSelected(null)}
          onSaved={saved}
        />
      )}
    </>
  );
}
