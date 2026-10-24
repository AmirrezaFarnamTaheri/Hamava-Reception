import { useState } from "react";
import {
  CalendarCheck2,
  CheckCheck,
  Clock3,
  Headphones,
  RefreshCw,
} from "lucide-react";
import { faDate, faNumber, localToday } from "../api";
import { Field, Loading, Metric, Retry, SectionTitle } from "../components";
import { useRemote } from "../hooks";
interface Digest {
  day: string;
  timezone: string;
  generated_at: string;
  metrics: {
    verified_bookings: number;
    attended: number;
    no_shows: number;
    attendance_unknown: number;
    cancellations: number;
    waitlist_fills: number;
    open_cases: number;
    call_sessions: number;
    billable_minutes: number;
    sms_submissions: number;
  };
  usage: { billable_minutes: number; provider_cost_toman: number };
}
export function DailyDigest() {
  const [day, setDay] = useState(localToday());
  const result = useRemote<Digest>(`/operations/digest?day=${day}`);
  return (
    <section className="panel daily-digest">
      <div className="digest-heading">
        <SectionTitle
          title="گزارش روزانهٔ مدیریت"
          description="معیارهای هر روز به وقت تهران؛ با تفکیک ثبت نوبت و مراجعه."
        />
        <div className="inline-actions">
          <Field label="روز گزارش">
            <input
              type="date"
              required
              max={localToday()}
              value={day}
              onChange={(event) => {
                if (event.target.value) setDay(event.target.value);
              }}
            />
          </Field>
          <button
            className="icon-button"
            aria-label="تازه‌سازی گزارش روزانه"
            onClick={result.refresh}
          >
            <RefreshCw size={18} />
          </button>
        </div>
      </div>
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading ? (
        <Loading rows={3} />
      ) : (
        result.data && (
          <>
            <div className="metric-grid">
              <Metric
                label="نوبت قطعیِ ثبت‌شده در روز"
                value={result.data.metrics.verified_bookings}
                detail="اکنون تأییدشده؛ پس از پرداخت یا تأیید لازم"
                icon={<CalendarCheck2 size={20} />}
              />
              <Metric
                label="مراجعهٔ انجام‌شده"
                value={result.data.metrics.attended}
                detail="نوبت‌های برنامه‌ریزی‌شده برای همین روز"
                icon={<CheckCheck size={20} />}
              />
              <Metric
                label="پیگیری‌های بازِ اکنون"
                value={result.data.metrics.open_cases}
                detail="صف فعلی در زمان تهیهٔ گزارش"
                icon={<Headphones size={20} />}
              />
              <Metric
                label="زمان تماس قابل محاسبه"
                value={result.data.metrics.billable_minutes}
                detail="دقیقهٔ ثبت‌شده؛ بدون زمان پردازش گفتار"
                icon={<Clock3 size={20} />}
              />
            </div>
            <dl className="digest-facts">
              {[
                ["نشست‌های پذیرش", result.data.metrics.call_sessions],
                ["لغو ثبت‌شده در روز", result.data.metrics.cancellations],
                [
                  "نوبت قطعی از فهرست انتظار",
                  result.data.metrics.waitlist_fills,
                ],
                ["مراجعه نکرده", result.data.metrics.no_shows],
                [
                  "مراجعهٔ هنوز تعیین‌تکلیف‌نشده",
                  result.data.metrics.attendance_unknown,
                ],
                [
                  "ارسال پیامک به ارائه‌دهنده",
                  result.data.metrics.sms_submissions,
                ],
              ].map(([label, value]) => (
                <div key={label}>
                  <dt>{label}</dt>
                  <dd>{faNumber(value)}</dd>
                </div>
              ))}
              <div>
                <dt>هزینهٔ ثبت‌شدهٔ ارائه‌دهندگان</dt>
                <dd>{faNumber(result.data.usage.provider_cost_toman)} تومان</dd>
              </div>
            </dl>
            <p className="field-hint">
              نوبت‌های قطعی بر اساس روز ثبت، و مراجعه‌ها بر اساس روز برنامهٔ
              نوبت شمرده می‌شوند. ارسال پیامک به ارائه‌دهنده به معنای تحویل آن
              نیست. این گزارش، پیام خارجی ارسال نمی‌کند.
            </p>
            <p className="digest-generated">
              تهیه‌شده در {faDate(result.data.generated_at, true)}
            </p>
          </>
        )
      )}
    </section>
  );
}
