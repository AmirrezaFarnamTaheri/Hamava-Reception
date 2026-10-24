import {
  Building2,
  CalendarCheck2,
  ClipboardList,
  LogOut,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";
import { faDate } from "../api";
import {
  Alert,
  Brand,
  Loading,
  Metric,
  PageTitle,
  Retry,
  SectionTitle,
  Status,
} from "../components";
import { useRemote } from "../hooks";
import type { Clinic, User } from "../types";
interface PartnerSummary {
  appointment_counts: Record<string, number>;
  open_tasks: number;
  as_of: string;
  contains_patient_records: boolean;
}
export function PartnerDashboard({
  user,
  clinics,
  switching,
  onSwitch,
  onLogout,
}: {
  user: User;
  clinics: Clinic[];
  switching: boolean;
  onSwitch: (id: string) => void;
  onLogout: () => void;
}) {
  const result = useRemote<PartnerSummary>(
    "/operations/partner-summary",
    30000,
  );
  return (
    <div className="partner-page">
      <header className="partner-topbar">
        <Brand />
        <div className="inline-actions">
          <label className="sr-only" htmlFor="partner-clinic">
            انتخاب مرکز
          </label>
          <select
            id="partner-clinic"
            value={user.tenant_id}
            disabled={switching}
            onChange={(e) => onSwitch(e.target.value)}
          >
            {(clinics.length
              ? clinics
              : [{ id: user.tenant_id, name: user.tenant_name }]
            ).map((clinic) => (
              <option key={clinic.id} value={clinic.id}>
                {clinic.name}
              </option>
            ))}
          </select>
          <button
            className="icon-button"
            aria-label="خروج از حساب"
            onClick={onLogout}
          >
            <LogOut size={19} />
          </button>
        </div>
      </header>
      <main className="partner-content">
        <PageTitle
          eyebrow="دسترسی همکار"
          title={`نمای کلی ${user.tenant_name}`}
          description="آمار تجمیعی مرکز در محدودهٔ مجوز همکاری شما."
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
              <div className="metric-grid">
                <Metric
                  label="نوبت‌های تأییدشده"
                  value={result.data.appointment_counts.CONFIRMED || 0}
                  detail="وضعیت فعلی نوبت‌های ثبت‌شده"
                  icon={<CalendarCheck2 size={20} />}
                />
                <Metric
                  label="درخواست‌های باز"
                  value={result.data.open_tasks}
                  detail="در انتظار اقدام تیم مرکز"
                  icon={<ClipboardList size={20} />}
                />
                <Metric
                  label="کل نوبت‌های ثبت‌شده"
                  value={Object.values(result.data.appointment_counts).reduce(
                    (a, b) => a + b,
                    0,
                  )}
                  detail="شامل همهٔ وضعیت‌ها"
                  icon={<Building2 size={20} />}
                />
              </div>
              <section className="panel">
                <SectionTitle
                  title="وضعیت نوبت‌ها"
                  description={`آخرین دریافت: ${faDate(result.data.as_of, true)}`}
                />
                <div
                  className="table-scroll"
                  tabIndex={0}
                  role="region"
                  aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
                >
                  <table>
                    <thead>
                      <tr>
                        <th>وضعیت</th>
                        <th>تعداد</th>
                      </tr>
                    </thead>
                    <tbody>
                      {Object.entries(result.data.appointment_counts).map(
                        ([status, count]) => (
                          <tr key={status}>
                            <td>
                              <Status value={status} />
                            </td>
                            <td>
                              {new Intl.NumberFormat("fa-IR").format(count)}
                            </td>
                          </tr>
                        ),
                      )}
                    </tbody>
                  </table>
                </div>
              </section>
            </>
          )
        )}
        <Alert kind="info">
          <ShieldCheck size={17} />
          این نما فقط آمار تجمیعی را نشان می‌دهد. اطلاعات هویتی مراجعه‌کنندگان و
          ابزار تغییر نوبت در دسترسی همکار قرار ندارند.
        </Alert>
      </main>
    </div>
  );
}
