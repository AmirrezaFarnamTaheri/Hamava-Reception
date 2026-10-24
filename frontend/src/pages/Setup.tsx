import {
  ArrowUpLeft,
  BookOpen,
  Check,
  Clock3,
  Link2,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";
import { faNumber } from "../api";
import { Alert, Loading, PageTitle, Retry } from "../components";
import { useRemote } from "../hooks";
import type { Practitioner, Service, Settings } from "../types";

export function SetupGuide({ navigate }: { navigate: (path: string) => void }) {
  const settings = useRemote<Settings>("/settings");
  const providers = useRemote<Practitioner[]>("/practitioners");
  const services = useRemote<Service[]>("/services");
  const loading = settings.loading || providers.loading || services.loading;
  const error = settings.error || providers.error || services.error;
  const refresh = () => {
    settings.refresh();
    providers.refresh();
    services.refresh();
  };
  const steps = [
    {
      title: "اطلاعات و روش پذیرش",
      description: "نام، نشانی، شمارهٔ تماس و نقش دستیار را مشخص کنید.",
      route: "/settings?tab=general",
      icon: Sparkles,
      complete:
        !!settings.data?.name &&
        !!settings.data?.address &&
        !!settings.data?.phone,
    },
    {
      title: "ساعت‌های کاری",
      description: "روزها و بازه‌هایی که مرکز پذیرش دارد را ثبت کنید.",
      route: "/settings?tab=hours",
      icon: Clock3,
      complete:
        !!settings.data &&
        Object.values(settings.data.working_hours).some(
          (shifts) => shifts.length > 0,
        ),
    },
    {
      title: "پزشکان و خدمات",
      description: "ارائه‌دهنده، مدت خدمت، تعرفه و برنامهٔ حضور را تعریف کنید.",
      route: "/settings?tab=catalog",
      icon: Users,
      complete:
        !!providers.data?.some((provider) => provider.active) &&
        !!services.data?.some((service) => service.active !== false),
    },
    {
      title: "پاسخ‌های تأییدشدهٔ مرکز",
      description: "اطلاعاتی که دستیار اجازه دارد به مراجعه‌کننده بگوید.",
      route: "/settings?tab=knowledge",
      icon: BookOpen,
      complete: !!settings.data?.faq?.length,
    },
  ];
  const completed = steps.filter((step) => step.complete).length;
  return (
    <>
      <PageTitle
        eyebrow="شروعی روشن برای تیم"
        title="مرکز را آماده کنید"
        description="هر بخش پس از ذخیره باقی می‌ماند؛ می‌توانید هر زمان از همین‌جا ادامه دهید."
      />
      {error ? (
        <Retry error={error} onRetry={refresh} />
      ) : loading ? (
        <Loading rows={4} />
      ) : (
        <>
          <section className="setup-overview">
            <div>
              <span className="eyebrow">پایه‌های پذیرش</span>
              <h2>
                {faNumber(completed)} از {faNumber(steps.length)} بخش ثبت شده
              </h2>
              <p>
                کامل بودن اطلاعات، جای تأیید نهایی و آزمون راه‌اندازی را
                نمی‌گیرد.
              </p>
            </div>
            <div
              className="setup-progress"
              role="progressbar"
              aria-label="بخش‌های ثبت‌شدهٔ راه‌اندازی"
              aria-valuenow={completed}
              aria-valuemin={0}
              aria-valuemax={steps.length}
            >
              {steps.map((step) => (
                <span
                  key={step.title}
                  className={step.complete ? "complete" : ""}
                />
              ))}
            </div>
          </section>
          <div className="setup-checklist">
            {steps.map((step, index) => (
              <section className="panel setup-card" key={step.route}>
                <span
                  className={`setup-step-icon ${step.complete ? "complete" : ""}`}
                >
                  {step.complete ? (
                    <Check size={23} />
                  ) : (
                    <step.icon size={23} />
                  )}
                </span>
                <div>
                  <span className="setup-step-count">
                    مرحلهٔ {faNumber(index + 1)} ·{" "}
                    {step.complete ? "اطلاعات ثبت شده" : "نیازمند تکمیل"}
                  </span>
                  <h2>{step.title}</h2>
                  <p>{step.description}</p>
                </div>
                <button
                  className={`button ${step.complete ? "secondary" : "primary"}`}
                  onClick={() => navigate(step.route)}
                >
                  {step.complete ? "بازبینی" : "تکمیل این بخش"}
                  <ArrowUpLeft size={17} />
                </button>
              </section>
            ))}
          </div>
          <div className="setup-final-grid">
            <section className="panel setup-next">
              <Link2 size={25} />
              <h2>اتصال‌های واقعی مرکز</h2>
              <p>
                تقویم، پیامک، پرداخت و صوت را بررسی کنید. پیکربندی با تحویل موفق
                سرویس یکسان نیست.
              </p>
              <button
                className="text-link"
                onClick={() => navigate("/settings?tab=integrations")}
              >
                بررسی اتصال‌ها
                <ArrowUpLeft size={17} />
              </button>
            </section>
            <section className="panel setup-next">
              <ShieldCheck size={25} />
              <h2>بازبینی پیش از شروع</h2>
              <p>
                سناریوهای رزرو، لغو، تداخل، خطای سرویس و همراهی انسانی را همراه
                تیم بررسی کنید.
              </p>
              <button
                className="text-link"
                onClick={() => navigate("/settings?tab=launch")}
              >
                آمادگی راه‌اندازی
                <ArrowUpLeft size={17} />
              </button>
            </section>
          </div>
          <Alert kind="info">
            تا زمانی که مسئول مرکز روش پاسخ‌گویی را فعال نکرده، تکمیل این راهنما
            به‌تنهایی دستیار را فعال نمی‌کند.
          </Alert>
        </>
      )}
    </>
  );
}
