import { useRef, useState, type FormEvent } from "react";
import {
  AlertTriangle,
  ArrowLeftRight,
  CalendarDays,
  Check,
  Plus,
  RefreshCw,
} from "lucide-react";
import { errorText, faDate, faNumber, localToday, newId, post } from "../api";
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
import type { Appointment, Practitioner, Settings } from "../types";
import { AppointmentCorrection } from "./Appointments";

type Kind = "LATE_ARRIVAL" | "PROVIDER_DELAY" | "EMERGENCY_CLOSURE";
interface Impact {
  id: string;
  appointment_id: string;
  state: string;
  original_start_at: string;
}
interface Disruption {
  id: string;
  kind: Kind;
  provider_id: string | null;
  start_at: string;
  end_at: string;
  delay_minutes: number;
  status: string;
  version: number;
  reason: string;
  created_at: string;
  resolved_at: string | null;
  impacts: Impact[];
}
interface Input {
  kind: Kind;
  provider_id?: string;
  appointment_id?: string;
  start_at?: string;
  end_at?: string;
  delay_minutes: number;
  reason: string;
  expected_policy_version: number;
  idempotency_key: string;
  confirmed: boolean;
}
interface Preview {
  policy_version: number;
  kind: Kind;
  provider_id: string | null;
  start_at: string;
  end_at: string;
  affected_count: number;
  appointments: Appointment[];
}
const labels: Record<Kind, string> = {
  LATE_ARRIVAL: "تأخیر مراجعه‌کننده",
  PROVIDER_DELAY: "تأخیر پزشک",
  EMERGENCY_CLOSURE: "تعطیلی اضطراری",
};
function tomorrow() {
  const date = new Date(localToday() + "T12:00:00Z");
  date.setUTCDate(date.getUTCDate() + 1);
  return date.toISOString().slice(0, 10);
}
function toIso(value: string) {
  return new Date(value + ":00+03:30").toISOString();
}

function CreateDisruption({
  admin,
  onClose,
  onSaved,
}: {
  admin: boolean;
  onClose: () => void;
  onSaved: () => void;
}) {
  const settings = useRemote<Settings>("/settings");
  const providers = useRemote<Practitioner[]>("/practitioners");
  const [kind, setKind] = useState<Kind>("LATE_ARRIVAL");
  const [date, setDate] = useState(localToday());
  const appointments = useRemote<Appointment[]>(
    kind === "LATE_ARRIVAL" ? `/appointments?date=${date}` : null,
  );
  const [provider, setProvider] = useState("");
  const [appointment, setAppointment] = useState("");
  const [start, setStart] = useState(tomorrow() + "T09:00");
  const [end, setEnd] = useState(tomorrow() + "T17:00");
  const [delay, setDelay] = useState(15);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [review, setReview] = useState<{
    input: Input;
    preview: Preview;
  } | null>(null);
  const requestId = useRef(newId());
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!settings.data) return;
    setBusy(true);
    setError("");
    try {
      if (review) {
        if (!confirmed) return;
        await post("/operations/disruptions", {
          ...review.input,
          expected_policy_version: review.preview.policy_version,
          confirmed: true,
        });
        onSaved();
      } else {
        const input: Input = {
          kind,
          delay_minutes: kind === "EMERGENCY_CLOSURE" ? 0 : delay,
          reason,
          expected_policy_version: settings.data.settings_version,
          idempotency_key: requestId.current,
          confirmed: false,
          ...(kind === "LATE_ARRIVAL"
            ? { appointment_id: appointment }
            : {
                ...(provider ? { provider_id: provider } : {}),
                start_at: toIso(start),
                end_at: toIso(end),
              }),
        };
        const preview = await post<Preview>(
          "/operations/disruptions/preview",
          input,
        );
        setReview({ input, preview });
      }
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={review ? "مرور اثر تغییر برنامه" : "ثبت تغییر برنامهٔ مرکز"}
      wide
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        {settings.error ? (
          <Retry error={settings.error} onRetry={settings.refresh} />
        ) : settings.loading ? (
          <Loading rows={2} />
        ) : !review ? (
          <>
            <Field label="نوع تغییر">
              <select
                value={kind}
                onChange={(e) => setKind(e.target.value as Kind)}
              >
                <option value="LATE_ARRIVAL">تأخیر مراجعه‌کننده</option>
                {admin && (
                  <>
                    <option value="PROVIDER_DELAY">تأخیر پزشک</option>
                    <option value="EMERGENCY_CLOSURE">تعطیلی اضطراری</option>
                  </>
                )}
              </select>
            </Field>
            {kind === "LATE_ARRIVAL" ? (
              <>
                <Field label="روز نوبت">
                  <input
                    type="date"
                    required
                    value={date}
                    onChange={(e) => {
                      setDate(e.target.value);
                      setAppointment("");
                    }}
                  />
                </Field>
                {appointments.error ? (
                  <Retry
                    error={appointments.error}
                    onRetry={appointments.refresh}
                  />
                ) : (
                  <Field label="نوبت مراجعه‌کننده">
                    <select
                      required
                      value={appointment}
                      onChange={(e) => setAppointment(e.target.value)}
                    >
                      <option value="">انتخاب کنید</option>
                      {appointments.data
                        ?.filter(
                          (row) =>
                            row.status === "CONFIRMED" && !row.attendance,
                        )
                        .map((row) => (
                          <option key={row.id} value={row.id}>
                            {row.patient_name} · {row.local_time} ·{" "}
                            {row.provider_name}
                          </option>
                        ))}
                    </select>
                  </Field>
                )}
              </>
            ) : (
              <>
                {providers.error ? (
                  <Retry error={providers.error} onRetry={providers.refresh} />
                ) : (
                  <Field label="پزشک یا محدودهٔ تعطیلی">
                    <select
                      required={kind === "PROVIDER_DELAY"}
                      value={provider}
                      onChange={(e) => setProvider(e.target.value)}
                    >
                      <option value="">
                        {kind === "EMERGENCY_CLOSURE"
                          ? "همهٔ پزشکان مرکز"
                          : "انتخاب کنید"}
                      </option>
                      {providers.data?.map((row) => (
                        <option key={row.id} value={row.id}>
                          {row.name}
                        </option>
                      ))}
                    </select>
                  </Field>
                )}
                <div className="form-grid">
                  <Field label="شروع بازه به وقت تهران">
                    <input
                      required
                      type="datetime-local"
                      value={start}
                      onChange={(e) => setStart(e.target.value)}
                    />
                  </Field>
                  <Field label="پایان بازه به وقت تهران">
                    <input
                      required
                      type="datetime-local"
                      value={end}
                      onChange={(e) => setEnd(e.target.value)}
                    />
                  </Field>
                </div>
              </>
            )}
            {kind !== "EMERGENCY_CLOSURE" && (
              <Field label="مدت تأخیر به دقیقه">
                <input
                  type="number"
                  min={1}
                  max={720}
                  required
                  value={delay}
                  onChange={(e) => setDelay(Number(e.target.value))}
                />
              </Field>
            )}
            <Field
              label="علت تغییر برنامه"
              hint="توضیح کوتاه برای پیگیری پذیرش؛ اطلاعات پزشکی وارد نکنید."
            >
              <textarea
                required
                rows={3}
                minLength={3}
                maxLength={500}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </Field>
          </>
        ) : (
          <>
            <div className="selected-appointment">
              <strong>{labels[review.input.kind]}</strong>
              <span>
                {faDate(review.preview.start_at, true)} تا{" "}
                {faDate(review.preview.end_at, true)}
              </span>
              {review.input.delay_minutes > 0 && (
                <span>{faNumber(review.input.delay_minutes)} دقیقه تأخیر</span>
              )}
              <p>{review.input.reason}</p>
            </div>
            <Alert kind="info">
              {review.input.kind === "LATE_ARRIVAL"
                ? "این نوبت برای تصمیم پذیرش علامت‌گذاری می‌شود."
                : "رزرو جدید در این محدوده متوقف می‌شود. نگه‌داشتن‌های موقت و پیشنهادهای انتظارِ متأثر آزاد می‌شوند."}{" "}
              زمان نوبت‌های قبلی خودکار تغییر نمی‌کند؛ برای هر مراجعه‌کننده باید
              تصمیم مشخص ثبت کنید. پیام اطلاع‌رسانی در صف ارسال قرار می‌گیرد.
            </Alert>
            <h3>{faNumber(review.preview.affected_count)} نوبت برای بررسی</h3>
            {review.preview.appointments.length ? (
              <div className="disruption-preview-list">
                {review.preview.appointments.map((row) => (
                  <div key={row.id}>
                    <strong>{row.patient_name}</strong>
                    <span>
                      {row.provider_name} · {row.service_name}
                    </span>
                    <span>{row.jalali_display}</span>
                    <Status value={row.status} />
                  </div>
                ))}
              </div>
            ) : (
              <p className="muted">
                در این بازه نوبت فعالی ثبت نشده است. محدودیت زمان‌های جدید
                همچنان اعمال می‌شود.
              </p>
            )}
            <label className="check-field">
              <input
                required
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <span>
                محدوده و نوبت‌های متأثر را مرور کردم و ثبت این تغییر را تأیید
                می‌کنم.
              </span>
            </label>
          </>
        )}
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || !settings.data || (!!review && !confirmed)}
          >
            <Busy busy={busy}>
              {review ? "تأیید و ثبت تغییر برنامه" : "بررسی نوبت‌های متأثر"}
            </Busy>
          </button>
          {review && (
            <button
              type="button"
              className="button secondary"
              disabled={busy}
              onClick={() => {
                setReview(null);
                setConfirmed(false);
                setError("");
              }}
            >
              ویرایش محدوده
            </button>
          )}
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
function ResolveDisruption({
  item,
  onClose,
  onSaved,
}: {
  item: Disruption;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(`/operations/disruptions/${item.id}/resolve`, {
        version: item.version,
        reason,
        confirmed,
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
      title="رفع محدودیت برنامه"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <Alert kind="info">
          با رفع محدودیت، زمان‌های آزاد دوباره قابل رزرو می‌شوند. وضعیت نوبت‌های
          متأثر همچنان به تصمیم جداگانهٔ پذیرش نیاز دارد.
        </Alert>
        <Field label="دلیل رفع محدودیت">
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
          <span>آمادگی مرکز برای پذیرش در این محدوده را تأیید می‌کنم.</span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>تأیید رفع محدودیت</Busy>
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
function ImpactReview({
  item,
  impact,
  onClose,
  onSaved,
}: {
  item: Disruption;
  impact: Impact;
  onClose: () => void;
  onSaved: () => void;
}) {
  const result = useRemote<Appointment>(
    `/operations/appointments/${impact.appointment_id}`,
  );
  const [correcting, setCorrecting] = useState(false);
  const [decision, setDecision] = useState("");
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(newId());
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!result.data || !decision) return;
    setBusy(true);
    setError("");
    try {
      await post(`/operations/disruptions/impacts/${impact.id}/decision`, {
        version: result.data.version,
        decision,
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
  if (correcting && result.data)
    return (
      <AppointmentCorrection
        appointment={result.data}
        onClose={() => setCorrecting(false)}
        onSaved={onSaved}
      />
    );
  return (
    <Dialog
      title="تعیین تکلیف نوبت متأثر"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        {result.error ? (
          <Retry error={result.error} onRetry={result.refresh} />
        ) : result.loading ? (
          <Loading rows={3} />
        ) : (
          result.data && (
            <>
              <div className="selected-appointment">
                <strong>
                  {result.data.patient_name} · {faNumber(result.data.reference)}
                </strong>
                <span>
                  {result.data.provider_name} · {result.data.service_name}
                </span>
                <span>{result.data.jalali_display}</span>
                <span dir="ltr">{result.data.phone_masked}</span>
                <Status value={result.data.status} />
              </div>
              <button
                type="button"
                className="button secondary"
                onClick={() => setCorrecting(true)}
              >
                <ArrowLeftRight size={17} />
                انتخاب زمان یا خدمت جایگزین
              </button>
              <Field label="تصمیم توافق‌شده">
                <select
                  required
                  value={decision}
                  onChange={(e) => setDecision(e.target.value)}
                >
                  <option value="">انتخاب کنید</option>
                  {(item.kind === "LATE_ARRIVAL" ||
                    item.status === "RESOLVED") &&
                    result.data.status === "CONFIRMED" && (
                      <option value="KEEP_ORIGINAL">
                        حفظ زمان اصلی با تأیید مراجعه‌کننده
                      </option>
                    )}
                  <option value="CANCEL">
                    لغو نوبت با هماهنگی مراجعه‌کننده
                  </option>
                </select>
              </Field>
              {item.kind !== "LATE_ARRIVAL" && item.status === "ACTIVE" && (
                <p className="field-hint">
                  تأیید زمان اصلی پس از رفع محدودیت برنامه ممکن است.
                </p>
              )}
              {decision === "CANCEL" && result.data.deposit_toman > 0 && (
                <Alert kind="info">
                  لغو نوبت، وجه پرداخت‌شده را خودکار بازنمی‌گرداند. بازپرداخت
                  باید جداگانه بررسی و اجرا شود.
                </Alert>
              )}
              <Field label="شرح توافق و اقدام">
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
                <span>این تصمیم با مراجعه‌کننده تأیید شده است.</span>
              </label>
            </>
          )
        )}
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className={`button ${decision === "CANCEL" ? "danger" : "primary"}`}
            disabled={busy || !result.data || !decision || !confirmed}
          >
            <Busy busy={busy}>ثبت تصمیم نوبت</Busy>
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
export function Disruptions({ admin }: { admin: boolean }) {
  const result = useRemote<Disruption[]>("/operations/disruptions", 20000);
  const providers = useRemote<Practitioner[]>("/practitioners");
  const [creating, setCreating] = useState(false);
  const [resolve, setResolve] = useState<Disruption | null>(null);
  const [selected, setSelected] = useState<{
    item: Disruption;
    impact: Impact;
  } | null>(null);
  const [message, setMessage] = useState("");
  function saved() {
    setCreating(false);
    setResolve(null);
    setSelected(null);
    result.refresh();
    setMessage("تغییر برنامه و وضعیت پیگیری ثبت شد.");
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
          title="تغییرات برنامه و تأخیرها"
          description="اثر تغییر برنامه را بررسی کنید و برای هر نوبت، تصمیمی روشن ثبت کنید."
          action={
            <div className="inline-actions">
              <button
                className="icon-button"
                aria-label="تازه‌سازی تغییرات برنامه"
                onClick={result.refresh}
              >
                <RefreshCw size={17} />
              </button>
              <button
                className="button primary small"
                onClick={() => setCreating(true)}
              >
                <Plus size={16} />
                ثبت تغییر برنامه
              </button>
            </div>
          }
        />
        {result.error ? (
          <Retry error={result.error} onRetry={result.refresh} />
        ) : result.loading ? (
          <Loading rows={3} />
        ) : result.data?.length ? (
          <div className="disruptions-list">
            {result.data.map((item) => (
              <article key={item.id} className="disruption-card">
                <div className="disruption-heading">
                  <div>
                    <h3>
                      <AlertTriangle size={18} />
                      {labels[item.kind]}
                    </h3>
                    <p>
                      {item.provider_id
                        ? providers.data?.find(
                            (provider) => provider.id === item.provider_id,
                          )?.name || "برنامهٔ پزشک"
                        : "همهٔ مرکز"}
                    </p>
                  </div>
                  <Status value={item.status} />
                </div>
                <p>{item.reason}</p>
                <div className="work-meta">
                  <CalendarDays size={15} />
                  {faDate(item.start_at, true)} تا {faDate(item.end_at, true)}
                  {item.delay_minutes > 0 && (
                    <span>· {faNumber(item.delay_minutes)} دقیقه تأخیر</span>
                  )}
                </div>
                <div className="disruption-impacts">
                  {item.impacts.length ? (
                    item.impacts.map((impact, index) => (
                      <div key={impact.id}>
                        <span>
                          نوبت {faNumber(index + 1)} ·{" "}
                          {faDate(impact.original_start_at, true)}
                        </span>
                        <Status value={impact.state} />
                        {impact.state !== "RESOLVED" && (
                          <button
                            className="button secondary small"
                            onClick={() => setSelected({ item, impact })}
                          >
                            مرور و تعیین تکلیف
                          </button>
                        )}
                      </div>
                    ))
                  ) : (
                    <p className="field-hint">
                      نوبت قبلی در این محدوده وجود نداشت.
                    </p>
                  )}
                </div>
                {admin && item.status === "ACTIVE" && (
                  <button
                    className="button secondary small"
                    onClick={() => setResolve(item)}
                  >
                    <Check size={16} />
                    رفع محدودیت برنامه
                  </button>
                )}
              </article>
            ))}
          </div>
        ) : (
          <Empty
            title="تغییر برنامهٔ بازی وجود ندارد"
            description="تأخیر مراجعه‌کننده یا پزشک و تعطیلی اضطراری را از این بخش ثبت کنید."
          />
        )}
      </section>
      {creating && (
        <CreateDisruption
          admin={admin}
          onClose={() => setCreating(false)}
          onSaved={saved}
        />
      )}{" "}
      {resolve && (
        <ResolveDisruption
          item={resolve}
          onClose={() => setResolve(null)}
          onSaved={saved}
        />
      )}{" "}
      {selected && (
        <ImpactReview
          {...selected}
          onClose={() => setSelected(null)}
          onSaved={saved}
        />
      )}
    </>
  );
}
