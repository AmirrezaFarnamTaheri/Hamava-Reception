import { useState, type FormEvent } from "react";
import { Plus, Send, Trash2 } from "lucide-react";
import { api, errorText, faDate, localToday, post } from "../api";
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
interface Destination {
  id: string;
  channel: string;
  enabled: boolean;
  automatic_daily: boolean;
  local_hour: number;
  created_at: string;
  consent_reference: string;
}
interface Delivery {
  id: string;
  destination_id: string;
  day: string;
  status: string;
  error_code: string | null;
  created_at: string;
}
const channels: Record<string, string> = {
  telegram: "تلگرام",
  bale: "بله",
  eitaa: "ایتا",
  email: "ایمیل",
};
function previousDay() {
  const date = new Date(localToday() + "T12:00:00Z");
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}
function AddDestination({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [channel, setChannel] = useState("email");
  const [recipient, setRecipient] = useState("");
  const [reference, setReference] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [automatic, setAutomatic] = useState(false);
  const [hour, setHour] = useState(8);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/operations/digest-destinations", {
        channel,
        recipient,
        consent_reference: reference,
        enabled,
        automatic_daily: enabled && automatic,
        local_hour: hour,
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
      title="مقصد گزارش مدیریت"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <Field label="مسیر گزارش">
          <select value={channel} onChange={(e) => setChannel(e.target.value)}>
            {Object.entries(channels).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        <Field
          label={
            channel === "email" ? "ایمیل گیرندهٔ مجاز" : "شناسهٔ گیرندهٔ مجاز"
          }
        >
          <input
            type={channel === "email" ? "email" : "text"}
            required
            minLength={3}
            maxLength={250}
            dir="ltr"
            value={recipient}
            onChange={(e) => setRecipient(e.target.value)}
          />
        </Field>
        <Field label="مرجع اجازهٔ دریافت گزارش">
          <input
            required
            minLength={5}
            maxLength={200}
            value={reference}
            onChange={(e) => setReference(e.target.value)}
            placeholder="عنوان یا شمارهٔ تأیید گیرنده"
          />
        </Field>
        <label className="check-field">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
          />
          <span>این مقصد برای ارسال گزارش فعال باشد.</span>
        </label>
        {enabled && (
          <>
            <label className="check-field">
              <input
                type="checkbox"
                checked={automatic}
                onChange={(e) => setAutomatic(e.target.checked)}
              />
              <span>
                گزارش روزِ پایان‌یافته، هر روز خودکار در صف ارسال قرار گیرد.
              </span>
            </label>
            {automatic && (
              <Field label="ساعت ارسال روزانه به وقت تهران">
                <input
                  type="number"
                  required
                  min={0}
                  max={23}
                  value={hour}
                  onChange={(e) => setHour(Number(e.target.value))}
                />
              </Field>
            )}
          </>
        )}
        <p className="field-hint">
          گزارش فقط آمار تجمیعی دارد و اطلاعات هویتی بیمار در آن نیست. فعال‌سازی
          مقصد، به‌تنهایی اتصال مسیر یا تحویل پیام را تأیید نمی‌کند.
        </p>
        <label className="check-field">
          <input
            type="checkbox"
            required
            checked={approved}
            onChange={(e) => setApproved(e.target.checked)}
          />
          <span>
            گیرنده و اجازهٔ او برای همین گزارش و روش ارسال را بررسی کرده‌ام.
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !approved}>
            <Busy busy={busy}>ثبت مقصد گزارش</Busy>
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
function QueueDigest({
  destination,
  onClose,
  onSaved,
}: {
  destination: Destination;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [day, setDay] = useState(previousDay());
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(`/operations/digest-destinations/${destination.id}/queue`, {
        day,
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
      title="ارسال گزارش روزانه"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <div className="selected-appointment">
          <strong>{channels[destination.channel]}</strong>
          <span>اجازهٔ گیرنده: {destination.consent_reference}</span>
        </div>
        <Field label="روز پایان‌یافتهٔ گزارش">
          <input
            required
            type="date"
            max={previousDay()}
            value={day}
            onChange={(e) => setDay(e.target.value)}
          />
        </Field>
        <p>
          آمار تجمیعی ثبت نوبت، مراجعه، لغو، فهرست انتظار، پیگیری باز و مصرف این
          روز برای مقصد بالا در صف قرار می‌گیرد. اطلاعات هویتی بیماران ارسال
          نمی‌شود.
        </p>
        <label className="check-field">
          <input
            type="checkbox"
            required
            checked={confirmed}
            onChange={(e) => setConfirmed(e.target.checked)}
          />
          <span>ارسال گزارش این روز به همین گیرنده را تأیید می‌کنم.</span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>ثبت درخواست ارسال</Busy>
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
export function DigestDestinations() {
  const destinations = useRemote<Destination[]>(
    "/operations/digest-destinations",
  );
  const deliveries = useRemote<Delivery[]>(
    "/operations/digest-deliveries",
    20000,
  );
  const [adding, setAdding] = useState(false);
  const [queue, setQueue] = useState<Destination | null>(null);
  const [disable, setDisable] = useState<Destination | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  async function stop() {
    if (!disable) return;
    setBusy(true);
    setError("");
    try {
      await api(`/operations/digest-destinations/${disable.id}`, {
        method: "DELETE",
      });
      setDisable(null);
      destinations.refresh();
      deliveries.refresh();
      setMessage("مقصد غیرفعال شد و گزارش‌های هنوز در صف آن متوقف شدند.");
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
      <section className="panel">
        <SectionTitle
          title="گزارش برای مدیریت"
          description="مقصدهای مجازِ گزارش تجمیعی را کنترل کنید و نتیجهٔ ارسال را ببینید."
          action={
            <button
              className="button primary small"
              onClick={() => setAdding(true)}
            >
              <Plus size={16} />
              افزودن مقصد
            </button>
          }
        />
        {destinations.error ? (
          <Retry error={destinations.error} onRetry={destinations.refresh} />
        ) : destinations.loading ? (
          <Loading rows={2} />
        ) : destinations.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="مقصدهای گزارش"
          >
            <table>
              <thead>
                <tr>
                  <th>مسیر</th>
                  <th>مرجع اجازهٔ گیرنده</th>
                  <th>وضعیت</th>
                  <th>برنامهٔ خودکار</th>
                  <th>اقدام</th>
                </tr>
              </thead>
              <tbody>
                {destinations.data.map((item) => (
                  <tr key={item.id}>
                    <td>{channels[item.channel] || "مسیر مجاز"}</td>
                    <td>{item.consent_reference}</td>
                    <td>
                      <Status value={item.enabled ? "ACTIVE" : "DISABLED"} />
                    </td>
                    <td>
                      {item.enabled && item.automatic_daily
                        ? `روزانه، ساعت ${new Intl.NumberFormat("fa-IR").format(item.local_hour)}`
                        : "فعال نیست"}
                    </td>
                    <td>
                      {item.enabled && (
                        <div className="inline-actions">
                          <button
                            className="button secondary small"
                            onClick={() => setQueue(item)}
                          >
                            <Send size={14} />
                            ارسال گزارش
                          </button>
                          <button
                            className="icon-button danger-text"
                            aria-label={`غیرفعال کردن مقصد ${item.consent_reference}`}
                            onClick={() => setDisable(item)}
                          >
                            <Trash2 size={16} />
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="مقصد گزارشی ثبت نشده"
            description="گزارش داخل سامانه از بخش گزارش عملکرد قابل مشاهده است. مقصد خارجی اختیاری است."
          />
        )}
      </section>
      <section className="panel catalog-panel">
        <SectionTitle
          title="وضعیت گزارش‌های ارسالی"
          description="ارسال به ارائه‌دهنده و تحویل به گیرنده، وضعیت‌های جداگانه‌اند."
        />
        {deliveries.error ? (
          <Retry error={deliveries.error} onRetry={deliveries.refresh} />
        ) : deliveries.loading ? (
          <Loading rows={2} />
        ) : deliveries.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="وضعیت ارسال گزارش"
          >
            <table>
              <thead>
                <tr>
                  <th>روز گزارش</th>
                  <th>مقصد</th>
                  <th>وضعیت</th>
                  <th>زمان ثبت</th>
                </tr>
              </thead>
              <tbody>
                {deliveries.data.map((item) => (
                  <tr key={item.id}>
                    <td>{faDate(item.day + "T12:00:00Z")}</td>
                    <td>
                      {destinations.data?.find(
                        (destination) => destination.id === item.destination_id,
                      )?.consent_reference || "مقصد ثبت‌شده"}
                    </td>
                    <td>
                      <Status value={item.status} />
                      {item.error_code && (
                        <small className="table-subline">
                          اتصال و اجازهٔ مقصد را بررسی کنید.
                        </small>
                      )}
                    </td>
                    <td>{faDate(item.created_at, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="گزارشی برای ارسال ثبت نشده"
            description="پس از ثبت درخواست، وضعیت واقعی آماده‌سازی، ارسال یا تحویل اینجا دیده می‌شود."
          />
        )}
      </section>
      {adding && (
        <AddDestination
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            destinations.refresh();
            setMessage("مقصد و روش دریافت گزارش ثبت شد.");
          }}
        />
      )}
      {queue && (
        <QueueDigest
          destination={queue}
          onClose={() => setQueue(null)}
          onSaved={() => {
            setQueue(null);
            deliveries.refresh();
            setMessage(
              "درخواست گزارش ثبت شد. وضعیت ارسال را در جدول بررسی کنید.",
            );
          }}
        />
      )}
      {disable && (
        <Dialog
          title="توقف گزارش به این مقصد"
          onClose={() => {
            if (!busy) setDisable(null);
          }}
        >
          <div className="modal-body">
            <p>
              مقصد «{disable.consent_reference}» غیرفعال می‌شود. گزارش‌های
              ارسال‌شده قابل بازخوانی نیستند؛ موارد هنوز در صف متوقف خواهند شد.
            </p>
            {error && <Alert>{error}</Alert>}
            <div className="modal-actions">
              <button
                className="button danger"
                disabled={busy}
                onClick={() => void stop()}
              >
                <Busy busy={busy}>تأیید غیرفعال‌سازی</Busy>
              </button>
              <button
                className="button secondary"
                disabled={busy}
                onClick={() => setDisable(null)}
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
