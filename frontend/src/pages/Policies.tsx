import { useState, type FormEvent } from "react";
import { History, RotateCcw } from "lucide-react";
import { errorText, faDate, faNumber, post } from "../api";
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
import { useRemote } from "../hooks";
import type { Settings } from "../types";
const fieldNames: Record<string, string> = {
  name: "نام مرکز",
  mode: "روش پذیرش",
  address: "نشانی",
  phone: "تلفن",
  website: "وب‌سایت",
  working_hours: "ساعت کاری",
  holidays: "تعطیلی‌ها",
  faq: "پاسخ‌های تأییدشده",
  retention_days: "نگهداری گفتگو",
  lead_time_minutes: "فاصله تا نوبت",
  booking_horizon_days: "بازهٔ رزرو",
  cancellation_notice_hours: "مهلت لغو",
  quiet_hours: "ساعت آرامش",
  monthly_minute_budget: "سقف مصرف",
};
const modes: Record<string, string> = {
  after_hours: "پس از ساعت کاری",
  overflow: "تماس‌های بی‌پاسخ",
  human_primary: "پذیرش انسانی",
  ai_primary: "ابتدا دستیار",
  supervised: "دستیار با تأیید پذیرش",
  paused: "توقف خودکار",
};
interface Revision {
  version: number;
  created_at: string | null;
  actor_id: string | null;
  changed_fields: string[];
  restored_from: number | null;
  reason: string;
  snapshot: Partial<Settings>;
}
interface HistoryData {
  current_version: number;
  revisions: Revision[];
}
function Restore({
  revision,
  current,
  onClose,
  onSaved,
}: {
  revision: Revision;
  current: number;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const snapshot = revision.snapshot;
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(`/operations/policies/${revision.version}/restore`, {
        expected_version: current,
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
      title={`بازگردانی قواعد نسخهٔ ${faNumber(revision.version)}`}
      onClose={() => {
        if (!busy) onClose();
      }}
      wide
    >
      <form className="modal-body" onSubmit={submit}>
        <Alert kind="info">
          اطلاعات و قواعد پذیرش این نسخه دوباره منتشر می‌شوند. زمان‌های پیشنهادی
          قبلی دوباره بررسی خواهند شد.
        </Alert>
        <dl className="policy-facts">
          <div>
            <dt>نام مرکز</dt>
            <dd>{snapshot.name || "—"}</dd>
          </div>
          <div>
            <dt>روش پذیرش</dt>
            <dd>{modes[snapshot.mode || ""] || "—"}</dd>
          </div>
          <div>
            <dt>نشانی</dt>
            <dd>{snapshot.address || "—"}</dd>
          </div>
          <div>
            <dt>شماره تماس</dt>
            <dd>
              <bdi>{snapshot.phone || "—"}</bdi>
            </dd>
          </div>
          <div>
            <dt>فاصله تا نوبت</dt>
            <dd>{faNumber(snapshot.lead_time_minutes || 0)} دقیقه</dd>
          </div>
          <div>
            <dt>بازهٔ رزرو</dt>
            <dd>{faNumber(snapshot.booking_horizon_days || 0)} روز</dd>
          </div>
          <div>
            <dt>مهلت لغو</dt>
            <dd>{faNumber(snapshot.cancellation_notice_hours || 0)} ساعت</dd>
          </div>
          <div>
            <dt>نگهداری گفتگو</dt>
            <dd>{faNumber(snapshot.retention_days || 0)} روز</dd>
          </div>
          <div>
            <dt>وب‌سایت</dt>
            <dd>
              <bdi>{snapshot.website || "—"}</bdi>
            </dd>
          </div>
          <div>
            <dt>ساعت آرامش</dt>
            <dd>
              {Array.isArray(snapshot.quiet_hours)
                ? snapshot.quiet_hours.join(" تا ")
                : snapshot.quiet_hours
                  ? `${snapshot.quiet_hours.start} تا ${snapshot.quiet_hours.end}`
                  : "—"}
            </dd>
          </div>
          <div>
            <dt>سقف مصرف</dt>
            <dd>{faNumber(snapshot.monthly_minute_budget || 0)} دقیقه</dd>
          </div>
        </dl>
        <details className="policy-detail">
          <summary>مرور ساعت کاری و تعطیلی‌ها</summary>
          {[
            ["5", "شنبه"],
            ["6", "یکشنبه"],
            ["0", "دوشنبه"],
            ["1", "سه‌شنبه"],
            ["2", "چهارشنبه"],
            ["3", "پنجشنبه"],
            ["4", "جمعه"],
          ].map(([id, day]) => (
            <p key={id}>
              <strong>{day}: </strong>
              {snapshot.working_hours?.[id]
                ?.map((interval) => interval.join(" تا "))
                .join("، ") || "تعطیل"}
            </p>
          ))}
          <p>
            تعطیلی‌ها:{" "}
            {snapshot.holidays?.length
              ? snapshot.holidays
                  .map((day) => faDate(day + "T12:00:00Z"))
                  .join("، ")
              : "ثبت نشده"}
          </p>
        </details>
        <details className="policy-detail">
          <summary>
            مرور {faNumber(snapshot.faq?.length || 0)} پاسخ مرکز
          </summary>
          {snapshot.faq?.map((item, index) => (
            <div className="policy-answer" key={index}>
              <strong>{item.question}</strong>
              <p>{item.answer}</p>
              {item.expires_at && (
                <small>پایان اعتبار: {faDate(item.expires_at)}</small>
              )}
            </div>
          ))}
        </details>
        <Field label="دلیل بازگردانی">
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
            اطلاعات این نسخه را مرور کرده‌ام و انتشار دوبارهٔ آن را تأیید
            می‌کنم.
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>تأیید و بازگردانی</Busy>
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
export function Policies({ onChanged }: { onChanged: () => void }) {
  const result = useRemote<HistoryData>("/operations/policies");
  const [selected, setSelected] = useState<Revision | null>(null);
  const [message, setMessage] = useState("");
  return (
    <>
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <section className="panel">
        <SectionTitle
          title="تاریخچهٔ قواعد مرکز"
          description="نسخه‌های منتشرشدهٔ اطلاعات، ساعت کاری و قواعد پذیرش را مرور کنید."
        />
        {result.error ? (
          <Retry error={result.error} onRetry={result.refresh} />
        ) : result.loading ? (
          <Loading rows={3} />
        ) : (
          result.data && (
            <div
              className="table-scroll"
              tabIndex={0}
              role="region"
              aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
            >
              <table>
                <thead>
                  <tr>
                    <th>نسخه</th>
                    <th>زمان انتشار</th>
                    <th>تغییرها</th>
                    <th>اقدام</th>
                  </tr>
                </thead>
                <tbody>
                  {result.data.revisions.map((revision) => (
                    <tr key={revision.version}>
                      <td>
                        <strong>نسخهٔ {faNumber(revision.version)}</strong>
                        {revision.version === result.data?.current_version && (
                          <small className="table-subline">
                            <Status value="ACTIVE" />
                          </small>
                        )}
                      </td>
                      <td>
                        {revision.created_at
                          ? faDate(revision.created_at, true)
                          : "نسخهٔ جاری"}
                      </td>
                      <td>
                        {revision.changed_fields.length
                          ? revision.changed_fields
                              .map(
                                (field) => fieldNames[field] || "برنامهٔ مرکز",
                              )
                              .join("، ")
                          : "اطلاعات و قواعد مرکز"}
                        {revision.restored_from !== null && (
                          <small className="table-subline">
                            بازگردانی از نسخهٔ{" "}
                            {faNumber(revision.restored_from)}
                          </small>
                        )}
                      </td>
                      <td>
                        {revision.version !== result.data?.current_version && (
                          <button
                            className="button secondary small"
                            onClick={() => setSelected(revision)}
                          >
                            <RotateCcw size={15} />
                            مرور و بازگردانی
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        )}
      </section>
      <div className="note-line">
        <History size={17} />
        <span>
          تعرفهٔ خدمات، پرداخت‌ها و تراکنش‌های نوبت تاریخچهٔ مستقل دارند. دامنهٔ
          این بخش، قواعد پذیرش مرکز است.
        </span>
      </div>
      {selected && result.data && (
        <Restore
          revision={selected}
          current={result.data.current_version}
          onClose={() => setSelected(null)}
          onSaved={() => {
            setSelected(null);
            result.refresh();
            onChanged();
            setMessage("قواعد انتخاب‌شده با یک نسخهٔ جدید منتشر شدند.");
          }}
        />
      )}
    </>
  );
}
