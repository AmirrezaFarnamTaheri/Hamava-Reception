import { useState } from "react";
import { faNumber } from "../api";
import { Empty, Field, Loading, Retry, SectionTitle } from "../components";
import { useRemote } from "../hooks";

interface TimingReport {
  hours: number;
  stages: Record<
    string,
    {
      count: number;
      p50_ms: number | null;
      p95_ms: number | null;
      p99_ms: number | null;
    }
  >;
  truncated: boolean;
  successful_observations_only: boolean;
}
const names: Record<string, string> = {
  stt_provider: "تبدیل گفتار به متن",
  tts_or_static_cache: "آماده‌سازی صدای پاسخ",
  staff_task_to_verified_room_join: "درخواست پیگیری تا پیوستن تأییدشدهٔ پذیرش",
  conversation_and_calendar: "بررسی گفتگو و تقویم",
  tool_slots: "جست‌وجوی نوبت‌های آزاد",
  tool_hold: "نگهداری موقت نوبت",
  tool_book: "ثبت نوبت",
  tool_cancel: "لغو نوبت",
  tool_reschedule: "تغییر زمان نوبت",
};
export function LatencyReport() {
  const [hours, setHours] = useState(24);
  const result = useRemote<TimingReport>(`/operations/latency?hours=${hours}`);
  return (
    <section className="panel settings-panel">
      <SectionTitle
        title="زمان پردازش و تحویل"
        description="زمان‌های ثبت‌شده در مراحل انجام درخواست؛ معیار شنیده‌شدن اولین صدای پاسخ نیست."
      />
      <Field label="بازهٔ بررسی زمان پاسخ">
        <select
          value={hours}
          onChange={(event) => setHours(Number(event.target.value))}
        >
          <option value={24}>۲۴ ساعت گذشته</option>
          <option value={168}>۷ روز گذشته</option>
        </select>
      </Field>
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading ? (
        <Loading rows={3} />
      ) : (
        result.data && (
          <>
            {Object.values(result.data.stages).some(
              (stage) => stage.count > 0,
            ) ? (
              <div
                className="table-scroll"
                tabIndex={0}
                role="region"
                aria-label="زمان پردازش مراحل؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
              >
                <table>
                  <thead>
                    <tr>
                      <th>مرحله</th>
                      <th>نمونهٔ موفق</th>
                      <th>میانه</th>
                      <th>صدک ۹۵</th>
                      <th>صدک ۹۹</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(result.data.stages).map(([key, stage]) => (
                      <tr key={key}>
                        <td>{names[key] || "مرحلهٔ پردازش"}</td>
                        <td>{faNumber(stage.count)}</td>
                        {[stage.p50_ms, stage.p95_ms, stage.p99_ms].map(
                          (value, index) => (
                            <td key={index}>
                              {value === null
                                ? "داده‌ای نیست"
                                : `${faNumber(value)} میلی‌ثانیه`}
                            </td>
                          ),
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty
                title="هنوز نمونه‌ای ثبت نشده"
                description="پس از انجام درخواست‌های واقعی یا آزمایشی، مدت هر مرحله در اینجا دیده می‌شود."
              />
            )}
            <p className="field-hint">
              میانه یعنی نیمی از نمونه‌ها در این مدت یا کمتر انجام شده‌اند؛ صدک
              ۹۵ و ۹۹ زمان تجربه‌های کندتر را نشان می‌دهند. این گزارش فقط
              نمونه‌های موفق را در بر می‌گیرد و نرخ خطا یا تجربهٔ شنیداری
              تماس‌گیرنده را اندازه نمی‌گیرد.
              {result.data.truncated &&
                " نمایش به آخرین ۱۰٬۰۰۰ نمونهٔ هر گروه محدود شده است."}
            </p>
          </>
        )
      )}
    </section>
  );
}
