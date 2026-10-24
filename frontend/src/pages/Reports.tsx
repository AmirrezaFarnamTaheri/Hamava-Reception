import { useMemo, useState } from "react";
import {
  BarChart3,
  Building2,
  CalendarCheck2,
  CheckCheck,
  Coins,
  Download,
  Phone,
  RefreshCw,
} from "lucide-react";
import { faDate, faNumber } from "../api";
import {
  Empty,
  Loading,
  Metric,
  PageTitle,
  Retry,
  SectionTitle,
} from "../components";
import { useRemote } from "../hooks";
import { hasPermission } from "../permissions";
import type { Appointment, Usage, User } from "../types";
import { DailyDigest } from "./DailyDigest";
import { BuildingContracts } from "./BuildingContracts";
import { LatencyReport } from "./Latency";

function ScenarioCalculator() {
  const [visits, setVisits] = useState(0);
  const [contribution, setContribution] = useState(0);
  const [cost, setCost] = useState(0);
  const net = visits * contribution - cost;
  return (
    <section className="panel scenario-panel">
      <SectionTitle
        title="ارزش افزوده را با شواهد بسنجید"
        description="این محاسبه فقط یک سناریو است؛ درآمد واقعی یا اثر قطعی هم‌آوا را گزارش نمی‌کند."
      />
      <div className="scenario-grid">
        <label className="field">
          <span className="field-label">مراجعهٔ افزوده نسبت به خط پایه</span>
          <input
            type="number"
            min="0"
            max="100000"
            value={visits}
            onChange={(e) => setVisits(Number(e.target.value))}
          />
        </label>
        <label className="field">
          <span className="field-label">حاشیهٔ هر مراجعه (تومان)</span>
          <input
            type="number"
            min="0"
            max="1000000000"
            value={contribution}
            onChange={(e) => setContribution(Number(e.target.value))}
          />
        </label>
        <label className="field">
          <span className="field-label">کل هزینهٔ دوره (تومان)</span>
          <input
            type="number"
            min="0"
            max="100000000000"
            value={cost}
            onChange={(e) => setCost(Number(e.target.value))}
          />
        </label>
        <div className="scenario-result">
          <small>خالص سناریو</small>
          <strong>{faNumber(net)}</strong>
          <span>تومان</span>
        </div>
      </div>
      <p className="field-hint">
        مراجعهٔ افزوده باید با دوره یا گروه مقایسه سنجیده شود. نوبت ثبت‌شده،
        مراجعهٔ انجام‌شده و درآمد افزوده سه معیار متفاوت‌اند.
      </p>
    </section>
  );
}

export function Reports({ user }: { user: User }) {
  const role = user.role;
  const clinical = hasPermission(user, "appointment:read");
  const usage = useRemote<Usage>("/usage");
  const appointments = useRemote<Appointment[]>(
    clinical ? "/appointments" : null,
  );
  const totalCost =
    usage.data?.events.reduce(
      (sum, item) => sum + Number(item.cost_toman || 0),
      0,
    ) || 0;
  const attended =
    appointments.data?.filter((a) => a.attendance === "ATTENDED").length || 0;
  const noShow =
    appointments.data?.filter((a) => a.attendance === "NO_SHOW").length || 0;
  const daily = useMemo(() => {
    const values = new Map<string, number>();
    for (let i = 6; i >= 0; i--) {
      const date = new Date();
      date.setUTCDate(date.getUTCDate() - i);
      const key = new Intl.DateTimeFormat("en-CA", {
        timeZone: "Asia/Tehran",
      }).format(date);
      values.set(key, 0);
    }
    for (const event of usage.data?.events || []) {
      const key = new Intl.DateTimeFormat("en-CA", {
        timeZone: "Asia/Tehran",
      }).format(new Date(event.created_at));
      if (values.has(key))
        values.set(key, (values.get(key) || 0) + Number(event.cost_toman || 0));
    }
    return [...values].map(([date, value]) => ({ date, value }));
  }, [usage.data]);
  function exportCsv() {
    if (!usage.data) return;
    const escape = (v: unknown) =>
      '"' + String(v ?? "").replace(/"/g, '""') + '"';
    const rows = [
      ["kind", "quantity", "unit", "cost_toman", "created_at"],
      ...usage.data.events.map((e) => [
        e.kind,
        e.quantity,
        e.unit,
        e.cost_toman,
        e.created_at,
      ]),
    ];
    const blob = new Blob(
      ["\uFEFF" + rows.map((r) => r.map(escape).join(",")).join("\r\n")],
      { type: "text/csv;charset=utf-8" },
    );
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "hamaava-usage.csv";
    anchor.click();
    URL.revokeObjectURL(url);
  }
  return (
    <>
      <PageTitle
        eyebrow="عملکرد و مصرف"
        title="تصمیم بهتر، با دادهٔ روشن"
        description="خروجی‌های تأییدشده و هزینه‌های ثبت‌شده را کنار هم ببینید."
        action={
          <button
            className="button secondary"
            disabled={!usage.data}
            onClick={exportCsv}
          >
            <Download size={17} />
            دریافت گزارش مصرف
          </button>
        }
      />
      {usage.error ? (
        <Retry error={usage.error} onRetry={usage.refresh} />
      ) : usage.loading ? (
        <Loading rows={3} />
      ) : (
        usage.data && (
          <>
            <div className="metric-grid">
              <Metric
                label="نشست‌های پذیرش"
                value={usage.data.calls}
                detail="تعداد ثبت‌شده در دوره"
                icon={<Phone size={20} />}
                accent
              />
              <Metric
                label="نوبت‌های ثبت‌شده"
                value={usage.data.bookings}
                detail="مستقل از وضعیت مراجعه"
                icon={<CalendarCheck2 size={20} />}
              />
              <Metric
                label="زمان استفاده"
                value={usage.data.minutes}
                detail="دقیقهٔ ثبت‌شده"
                icon={<BarChart3 size={20} />}
              />
              <Metric
                label="هزینهٔ ثبت‌شده"
                value={totalCost}
                detail="تومان؛ فقط رویدادهای هزینه‌گذاری‌شده"
                icon={<Coins size={20} />}
              />
            </div>
            <div className="report-grid">
              <section className="panel">
                <SectionTitle
                  title="هزینه‌های هفت روز اخیر"
                  description="بر پایهٔ رویدادهای ثبت‌شده، به تومان"
                />
                {daily.some((x) => x.value > 0) ? (
                  <div
                    className="bar-chart"
                    role="img"
                    aria-label={daily
                      .map(
                        (d) =>
                          `${faDate(d.date + "T12:00:00Z")}: ${faNumber(d.value)} تومان`,
                      )
                      .join("، ")}
                  >
                    {daily.map((item) => (
                      <div className="bar-item" key={item.date}>
                        <span className="bar-value">
                          {faNumber(item.value)}
                        </span>
                        <div className="bar-track">
                          <span
                            style={{
                              height: `${Math.max(2, (item.value / Math.max(...daily.map((d) => d.value), 1)) * 100)}%`,
                            }}
                          />
                        </div>
                        <span className="bar-label">
                          {faDate(item.date + "T12:00:00Z")}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <Empty
                    title="هنوز هزینه‌ای ثبت نشده"
                    description="نبود هزینه در این گزارش به معنی رایگان بودن سرویس نیست. پس از اتصال ارائه‌دهندگان و ثبت مصرف، هزینه‌ها نمایش داده می‌شوند."
                  />
                )}
              </section>
              {clinical && (
                <section className="panel attendance-panel">
                  <SectionTitle
                    title="مراجعه، فراتر از رزرو"
                    description="وضعیت حداکثر ۲۵۰ نوبت آخر مرکز"
                  />
                  {appointments.error ? (
                    <Retry
                      error={appointments.error}
                      onRetry={appointments.refresh}
                    />
                  ) : appointments.loading ? (
                    <Loading rows={2} />
                  ) : (
                    <>
                      <div className="attendance-main">
                        <span className="attendance-icon">
                          <CheckCheck size={29} />
                        </span>
                        <strong>{faNumber(attended)}</strong>
                        <span>مراجعهٔ انجام‌شده</span>
                      </div>
                      <div className="attendance-details">
                        <div>
                          <span>مراجعه نکرده</span>
                          <strong>{faNumber(noShow)}</strong>
                        </div>
                        <div>
                          <span>وضعیت مراجعه ثبت‌نشده</span>
                          <strong>
                            {faNumber(
                              appointments.data?.filter(
                                (a) =>
                                  !a.attendance &&
                                  !["CANCELED", "EXPIRED"].includes(a.status),
                              ).length || 0,
                            )}
                          </strong>
                        </div>
                      </div>
                      <p className="field-hint">
                        وضعیت مراجعه را تیم پذیرش ثبت می‌کند. این اعداد
                        به‌تنهایی اثر افزودهٔ دستیار را نشان نمی‌دهند.
                      </p>
                    </>
                  )}
                </section>
              )}
            </div>
          </>
        )
      )}
      <DailyDigest />
      {["owner", "admin"].includes(role) && <LatencyReport />}
      <ScenarioCalculator />
    </>
  );
}

interface BuildingData {
  clinics: {
    id: string;
    name: string;
    calls: number;
    confirmed: number;
    attended: number;
    open_tasks: number;
    minutes_used: number;
  }[];
  totals?: {
    calls: number;
    confirmed: number;
    attended: number;
    open_tasks: number;
    minutes_used: number;
  };
}
export function Building({ role }: { role: string }) {
  const result = useRemote<BuildingData>("/operations/building", 20000);
  return (
    <>
      <PageTitle
        eyebrow="هماهنگی چند مرکز"
        title="مرکز مشترک پذیرش"
        description="نمای تجمیعی مراکز مجاز؛ بدون نمایش اطلاعات هویتی مراجعان."
        action={
          <button className="button secondary" onClick={result.refresh}>
            <RefreshCw size={17} />
            تازه‌سازی
          </button>
        }
      />
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading ? (
        <Loading rows={4} />
      ) : (
        result.data && (
          <>
            <div className="building-banner">
              <span className="building-banner-icon">
                <Building2 size={34} />
              </span>
              <div>
                <h2>دید مشترک، حریم مستقل</h2>
                <p>
                  تنها آمار مراکزی که برای مشاهدهٔ آن‌ها دسترسی دارید، در این
                  بخش نمایش داده می‌شود. برای رسیدگی به نوبت‌ها، وارد فضای همان
                  مرکز شوید.
                </p>
              </div>
              <strong>
                {faNumber(result.data.clinics.length)}
                <small>مرکز در دسترس</small>
              </strong>
            </div>
            <section className="panel">
              <SectionTitle
                title="وضعیت مراکز"
                description="آمار از داده‌های ثبت‌شدهٔ هر مرکز محاسبه می‌شود."
              />
              {result.data.clinics.length ? (
                <div
                  className="table-scroll"
                  tabIndex={0}
                  role="region"
                  aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
                >
                  <table>
                    <thead>
                      <tr>
                        <th>مرکز</th>
                        <th>نشست‌های پذیرش</th>
                        <th>نوبت تأییدشده</th>
                        <th>مراجعه انجام‌شده</th>
                        <th>پیگیری باز</th>
                        <th>دقیقهٔ مصرف</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.data.clinics.map((clinic) => (
                        <tr key={clinic.id}>
                          <td>
                            <strong>{clinic.name}</strong>
                          </td>
                          <td>{faNumber(clinic.calls)}</td>
                          <td>{faNumber(clinic.confirmed)}</td>
                          <td>{faNumber(clinic.attended)}</td>
                          <td>{faNumber(clinic.open_tasks)}</td>
                          <td>{faNumber(clinic.minutes_used)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <Empty
                  title="مرکزی برای نمایش وجود ندارد"
                  description="پس از اختصاص دسترسی، آمار مراکز در اینجا نمایش داده می‌شود."
                />
              )}
            </section>
          </>
        )
      )}
      {role === "owner" && <BuildingContracts />}
    </>
  );
}
