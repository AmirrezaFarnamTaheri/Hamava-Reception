import { lazy, Suspense, useEffect, useState } from "react";
import { HeartPulse, Link2, ShieldCheck, WalletCards } from "lucide-react";
import { Loading, PageTitle } from "../components";
import { hasPermission } from "../permissions";
import type { User } from "../types";

const Costs = lazy(() =>
  import("./Costs").then((module) => ({ default: module.Costs })),
);
const PrivacyGovernance = lazy(() =>
  import("./PrivacyGovernance").then((module) => ({
    default: module.PrivacyGovernance,
  })),
);
const ServiceConnections = lazy(() =>
  import("./ServiceConnections").then((module) => ({
    default: module.ServiceConnections,
  })),
);
const ServiceHealth = lazy(() =>
  import("./ServiceHealth").then((module) => ({
    default: module.ServiceHealth,
  })),
);

export function ControlCenter({
  user,
  search,
}: {
  user: User;
  search: string;
}) {
  const tabs = [
    {
      id: "costs",
      label: "هزینه و بودجه",
      icon: WalletCards,
      permission: "billing:read",
    },
    {
      id: "privacy",
      label: "انتخاب‌ها و نگهداری داده",
      icon: ShieldCheck,
      permission: "privacy:manage",
    },
    {
      id: "connections",
      label: "سرویس‌ها و پردازشگران",
      icon: Link2,
      permission: "integration:read",
    },
    {
      id: "health",
      label: "هشدارها و مسئول پاسخ",
      icon: HeartPulse,
      permission: "health:read",
    },
  ].filter((tab) => hasPermission(user, tab.permission));
  const requested = new URLSearchParams(search).get("tab");
  const [tab, setTab] = useState(
    tabs.find((item) => item.id === requested)?.id || tabs[0]?.id || "",
  );
  useEffect(() => {
    setTab(tabs.find((item) => item.id === requested)?.id || tabs[0]?.id || "");
  }, [requested, user.role]);
  function choose(value: string) {
    setTab(value);
    history.replaceState({}, "", `/controls?tab=${value}`);
  }
  return (
    <>
      <PageTitle
        eyebrow="کنترل روشن، مسئولیت مشخص"
        title="کنترل و نظارت"
        description="بودجهٔ سرویس‌ها، مجوزهای داده و مسئول رسیدگی را مطابق اختیار حساب خود مدیریت کنید."
      />
      <div
        className="control-tabs"
        role="group"
        aria-label="بخش‌های کنترل و نظارت"
      >
        {tabs.map((item) => (
          <button
            key={item.id}
            aria-pressed={tab === item.id}
            onClick={() => choose(item.id)}
          >
            <item.icon size={20} />
            <span>{item.label}</span>
          </button>
        ))}
      </div>
      <Suspense fallback={<Loading rows={4} />}>
        {tab === "costs" ? (
          <Costs canWrite={hasPermission(user, "billing:write")} />
        ) : tab === "privacy" ? (
          <PrivacyGovernance />
        ) : tab === "connections" ? (
          <ServiceConnections user={user} />
        ) : tab === "health" ? (
          <ServiceHealth user={user} />
        ) : null}
      </Suspense>
    </>
  );
}
