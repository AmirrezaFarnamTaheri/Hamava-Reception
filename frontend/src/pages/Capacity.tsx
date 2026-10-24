import { CalendarOperations } from "./CalendarControl";
import { useEffect, useState } from "react";
import { PageTitle } from "../components";
import { hasPermission } from "../permissions";
import type { User } from "../types";
import { Waitlist } from "./Waitlist";
import { Payments } from "./Payments";
import { Billing } from "./Billing";
import { Disruptions } from "./Disruptions";
import { Followups } from "./Outreach";

export function Capacity({ user, search }: { user: User; search: string }) {
  const clinical = hasPermission(user, "appointment:read"),
    finance = hasPermission(user, "billing:read");
  const tabs = [
    ...(clinical
      ? [
          ["waitlist", "فهرست انتظار"],
          ["disruptions", "تغییر برنامه"],
          ["followups", "پس از مراجعه"],
          ["calendar", "پیگیری تقویم"],
        ]
      : []),
    ...(finance
      ? [
          ["payments", "بیعانه و بازپرداخت"],
          ["billing", "صورت‌حساب"],
        ]
      : []),
  ];
  const requested = new URLSearchParams(search).get("tab");
  const [tab, setTab] = useState(
    tabs.find(([id]) => id === requested)?.[0] || tabs[0]?.[0] || "",
  );
  useEffect(() => {
    setTab(tabs.find(([id]) => id === requested)?.[0] || tabs[0]?.[0] || "");
  }, [requested, user.role]);
  function choose(value: string) {
    setTab(value);
    history.replaceState({}, "", `/capacity?tab=${value}`);
  }
  return (
    <>
      <PageTitle
        eyebrow="پیگیری فرصت‌ها و پرداخت‌ها"
        title="ظرفیت و امور مالی"
        description="کارهای مربوط به ظرفیت و پرداخت را در محدودهٔ مسئولیت خود دنبال کنید."
      />
      <div className="segmented-tabs" role="group" aria-label="بخش عملیات">
        {tabs.map(([id, label]) => (
          <button
            key={id}
            aria-pressed={tab === id}
            className={tab === id ? "selected" : ""}
            onClick={() => choose(id)}
          >
            {label}
          </button>
        ))}
      </div>
      {tab === "waitlist" ? (
        <Waitlist />
      ) : tab === "followups" ? (
        <Followups />
      ) : tab === "disruptions" ? (
        <Disruptions admin={hasPermission(user, "policy:write")} />
      ) : tab === "payments" ? (
        <Payments admin={hasPermission(user, "billing:write")} />
      ) : tab === "billing" ? (
        <Billing />
      ) : tab === "calendar" ? (
        <CalendarOperations
          canWrite={hasPermission(user, "appointment:write")}
        />
      ) : null}
    </>
  );
}
