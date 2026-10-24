import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import {
  Bell,
  Building2,
  CalendarDays,
  ChartNoAxesCombined,
  ChevronLeft,
  CircleHelp,
  ClipboardList,
  Command,
  ExternalLink,
  Headphones,
  Home,
  Laptop,
  LogOut,
  MoreHorizontal,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  Smartphone,
  Sparkles,
  Wifi,
  type LucideIcon,
} from "lucide-react";
import { Dialog, Empty, PageTitle } from "./components";
import { hasPermission, roleNames } from "./permissions";
import { getRuntime, publicUrl } from "./platform";
import type { Clinic, User } from "./types";

export interface NavigationItem {
  path: string;
  label: string;
  description: string;
  icon: LucideIcon;
  group: "روزمره" | "مدیریت مرکز" | "حساب و برنامه";
  permission?: string;
  anyPermissions?: string[];
  keywords?: string;
}

export const navigation: NavigationItem[] = [
  {
    path: "/",
    label: "امروز",
    description: "برنامه و کارهای پیش روی تیم",
    icon: Home,
    group: "روزمره",
  },
  {
    path: "/appointments",
    label: "نوبت‌ها",
    description: "رزرو، جابه‌جایی و ثبت مراجعه",
    icon: CalendarDays,
    group: "روزمره",
    permission: "appointment:read",
    keywords: "تقویم مراجعه رزرو وقت",
  },
  {
    path: "/tasks",
    label: "پیگیری‌ها",
    description: "درخواست‌ها، مسئول و نتیجهٔ پیگیری",
    icon: ClipboardList,
    group: "روزمره",
    permission: "task:read",
    keywords: "درخواست ارجاع کار",
  },
  {
    path: "/calls",
    label: "تماس‌ها",
    description: "نشست‌های فعال و همراهی انسانی",
    icon: Headphones,
    group: "روزمره",
    permission: "appointment:read",
    keywords: "صدا زنده تلفن همراهی",
  },
  {
    path: "/notifications",
    label: "پیام‌ها",
    description: "وضعیت ارسال و تحویل پیام‌ها",
    icon: Bell,
    group: "روزمره",
    permission: "task:read",
    keywords: "پیامک یادآوری ارسال",
  },
  {
    path: "/capacity",
    label: "ظرفیت و امور مالی",
    description: "فهرست انتظار، پرداخت و تغییر برنامه",
    icon: ClipboardList,
    group: "مدیریت مرکز",
    anyPermissions: ["appointment:read", "billing:read"],
    keywords: "پرداخت بیعانه بازپرداخت انتظار",
  },
  {
    path: "/reports",
    label: "گزارش عملکرد",
    description: "مراجعه، استفاده و هزینهٔ ثبت‌شده",
    icon: ChartNoAxesCombined,
    group: "مدیریت مرکز",
    permission: "reports:read",
  },
  {
    path: "/building",
    label: "مرکز مشترک",
    description: "تصویر کلی مرکزهای مجاز شما",
    icon: Building2,
    group: "مدیریت مرکز",
    permission: "building:read",
  },
  {
    path: "/settings",
    label: "تنظیمات مرکز",
    description: "اطلاعات، قواعد، تیم و اتصال‌ها",
    icon: Settings2,
    group: "مدیریت مرکز",
    permission: "policy:read",
  },
  {
    path: "/controls",
    label: "کنترل و نظارت",
    description: "بودجه، مجوزهای داده و سلامت سرویس‌ها",
    icon: ShieldCheck,
    group: "مدیریت مرکز",
    anyPermissions: [
      "billing:read",
      "privacy:manage",
      "integration:read",
      "health:read",
    ],
    keywords: "هزینه تعرفه رضایت حریم هشدار پردازشگر",
  },
  {
    path: "/setup",
    label: "راهنمای راه‌اندازی",
    description: "تکمیل مرحله‌به‌مرحلهٔ مرکز",
    icon: Sparkles,
    group: "مدیریت مرکز",
    permission: "policy:write",
    keywords: "شروع مرکز جدید پزشک ساعت",
  },
  {
    path: "/more",
    label: "بیشتر",
    description: "همهٔ بخش‌ها، حساب و اتصال برنامه",
    icon: MoreHorizontal,
    group: "حساب و برنامه",
  },
];

export const canVisit = (user: User, item: NavigationItem) =>
  (!item.permission || hasPermission(user, item.permission)) &&
  (!item.anyPermissions ||
    item.anyPermissions.some((permission) => hasPermission(user, permission)));
export const visibleNavigation = (user: User) =>
  navigation.filter((item) => canVisit(user, item));

export function followNavigation(
  event: MouseEvent<HTMLAnchorElement>,
  path: string,
  navigate: (path: string) => void,
) {
  if (
    event.button === 0 &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey
  ) {
    event.preventDefault();
    navigate(path);
  }
}

export function NavigationGroups({
  user,
  path,
  navigate,
}: {
  user: User;
  path: string;
  navigate: (path: string) => void;
}) {
  const items = visibleNavigation(user);
  return (
    <nav aria-label="فهرست اصلی" className="workspace-navigation">
      {(["روزمره", "مدیریت مرکز", "حساب و برنامه"] as const).map((group) => {
        const groupItems = items.filter((item) => item.group === group);
        if (!groupItems.length) return null;
        return (
          <div className="nav-group" key={group}>
            <div className="nav-group-label">{group}</div>
            {groupItems.map((item) => (
              <a
                key={item.path}
                href={item.path}
                onClick={(event) =>
                  followNavigation(event, item.path, navigate)
                }
                className={`nav-item ${path === item.path ? "active" : ""}`}
                aria-current={path === item.path ? "page" : undefined}
              >
                <item.icon size={19} />
                <span>{item.label}</span>
                {path === item.path && <span className="nav-active-dot" />}
              </a>
            ))}
          </div>
        );
      })}
    </nav>
  );
}

export function MobileNavigation({
  user,
  path,
  navigate,
}: {
  user: User;
  path: string;
  navigate: (path: string) => void;
}) {
  const primary = ["/", "/tasks", "/calls", "/more"];
  const allowed = visibleNavigation(user);
  const items = primary
    .map((route) => allowed.find((item) => item.path === route))
    .filter((item): item is NavigationItem => !!item);
  return (
    <nav className="companion-navigation" aria-label="دسترسی سریع همراه">
      {items.map((item) => {
        const active =
          path === item.path ||
          (item.path === "/more" && !primary.includes(path));
        return (
          <a
            href={item.path}
            key={item.path}
            className={active ? "active" : ""}
            aria-current={active ? "page" : undefined}
            onClick={(event) => followNavigation(event, item.path, navigate)}
          >
            <span>
              <item.icon size={22} />
            </span>
            <strong>{item.label}</strong>
          </a>
        );
      })}
    </nav>
  );
}

function normalize(value: string) {
  return value
    .toLocaleLowerCase("fa")
    .replace(/ي/g, "ی")
    .replace(/ك/g, "ک")
    .replace(/[\u064b-\u065f\u200c]/g, "")
    .trim();
}

export function CommandMenu({
  user,
  onClose,
  navigate,
}: {
  user: User;
  onClose: () => void;
  navigate: (path: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const choices = useMemo(() => {
    const items = visibleNavigation(user).map((item) => ({
      ...item,
      key: item.path,
    }));
    if (hasPermission(user, "appointment:write"))
      items.unshift({
        path: "/appointments?new=1",
        key: "new-appointment",
        label: "ثبت نوبت جدید",
        description: "انتخاب پزشک، زمان و تأیید اطلاعات",
        icon: Plus,
        group: "روزمره",
        keywords: "رزرو وقت",
      });
    if (hasPermission(user, "catalog:write"))
      items.push({
        path: "/settings?tab=catalog",
        key: "catalog",
        label: "پزشکان و خدمات",
        description: "تعریف خدمت و برنامهٔ ارائه‌دهندگان",
        icon: CalendarDays,
        group: "مدیریت مرکز",
      });
    if (hasPermission(user, "policy:write"))
      items.push({
        path: "/settings?tab=hours",
        key: "hours",
        label: "ساعت کاری مرکز",
        description: "روزها و بازه‌های پذیرش",
        icon: Settings2,
        group: "مدیریت مرکز",
      });
    return items;
  }, [user]);
  const results = choices.filter((item) =>
    normalize(
      `${item.label} ${item.description} ${item.keywords || ""}`,
    ).includes(normalize(query)),
  );
  useEffect(() => {
    input.current?.focus();
  }, []);
  useEffect(() => {
    setActive(0);
  }, [query]);
  useEffect(() => {
    document
      .getElementById(`command-option-${active}`)
      ?.scrollIntoView({ block: "nearest" });
  }, [active]);
  function choose(index: number) {
    const item = results[index];
    if (!item) return;
    onClose();
    navigate(item.path);
  }
  return (
    <Dialog title="کجا می‌خواهید بروید؟" onClose={onClose}>
      <div className="command-menu">
        <div className="command-search">
          <Search size={21} />
          <input
            ref={input}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="نام بخش یا کاری که می‌خواهید انجام دهید…"
            aria-label="جست‌وجوی بخش‌ها و اقدام‌ها"
            role="combobox"
            aria-autocomplete="list"
            aria-expanded="true"
            aria-controls="command-results"
            aria-activedescendant={
              results.length ? `command-option-${active}` : undefined
            }
            onKeyDown={(event) => {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault();
                setActive((current) =>
                  results.length
                    ? (current +
                        (event.key === "ArrowDown" ? 1 : -1) +
                        results.length) %
                      results.length
                    : 0,
                );
              } else if (event.key === "Enter") {
                event.preventDefault();
                choose(active);
              }
            }}
          />
        </div>
        <p className="command-scope">جست‌وجو در بخش‌ها و اقدام‌های حساب شما</p>
        <div
          id="command-results"
          role="listbox"
          aria-label="نتیجه‌های جست‌وجو"
          className="command-results"
        >
          {results.map((item, index) => (
            <button
              type="button"
              tabIndex={-1}
              key={item.key}
              id={`command-option-${index}`}
              role="option"
              aria-selected={active === index}
              className={`command-option ${active === index ? "active" : ""}`}
              onPointerMove={() => setActive(index)}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(index)}
            >
              <item.icon size={20} />
              <span>
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
              <ChevronLeft size={18} />
            </button>
          ))}
        </div>
        {!results.length && (
          <Empty
            title="بخشی با این نام پیدا نشد"
            description="نام کوتاه‌تری وارد کنید؛ مثلاً نوبت، تماس یا تنظیمات."
          />
        )}
        <div className="command-footer">
          <span>
            <kbd>↑</kbd>
            <kbd>↓</kbd> انتخاب
          </span>
          <span>
            <kbd>Enter</kbd> رفتن
          </span>
          <span>
            <kbd>Esc</kbd> بستن
          </span>
        </div>
      </div>
    </Dialog>
  );
}

export function MorePage({
  user,
  clinics,
  switching,
  onSwitch,
  navigate,
  onLogout,
  onCommands,
}: {
  user: User;
  clinics: Clinic[];
  switching: boolean;
  onSwitch: (id: string) => void;
  navigate: (path: string) => void;
  onLogout: () => void;
  onCommands: () => void;
}) {
  const runtime = getRuntime();
  const items = visibleNavigation(user).filter(
    (item) => !["/", "/tasks", "/calls", "/more"].includes(item.path),
  );
  const activeClinic = clinics.find((clinic) => clinic.id === user.tenant_id);
  return (
    <>
      <PageTitle
        eyebrow="همراهِ مرکز شما"
        title="حساب و دسترسی‌ها"
        description="همهٔ ابزارهای مجاز شما، در یک جای مشخص."
      />
      <section className="account-card panel">
        <span className="account-avatar">{user.name.slice(0, 1)}</span>
        <div>
          <h2>{user.name}</h2>
          <p>{roleNames[user.role] || "همکار مرکز"}</p>
        </div>
        <span className="account-security">
          <ShieldCheck size={17} /> حساب مرکز
        </span>
        <label className="account-clinic">
          <span>مرکز فعال</span>
          <select
            aria-label="انتخاب مرکز در همراه"
            value={user.tenant_id}
            disabled={switching || !clinics.length}
            onChange={(event) => onSwitch(event.target.value)}
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
        </label>
      </section>
      <div className="more-grid">
        <section className="panel destination-panel">
          <h2>بخش‌های مرکز</h2>
          {items.map((item) => (
            <a
              href={item.path}
              key={item.path}
              className="destination-row"
              onClick={(event) => followNavigation(event, item.path, navigate)}
            >
              <span className="destination-icon">
                <item.icon size={21} />
              </span>
              <span>
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
              <ChevronLeft size={18} />
            </a>
          ))}
        </section>
        <div className="more-secondary">
          <section className="panel destination-panel">
            <h2>برنامه و اتصال</h2>
            <button
              className="destination-row"
              onClick={() => navigate("/connection")}
            >
              <span className="destination-icon">
                <Wifi size={21} />
              </span>
              <span>
                <strong>اتصال به سامانهٔ مرکز</strong>
                <small dir="ltr">
                  {runtime.serverUrl
                    ? new URL(runtime.serverUrl).host
                    : location.host}
                </small>
              </span>
              <ChevronLeft size={18} />
            </button>
            <button className="destination-row" onClick={onCommands}>
              <span className="destination-icon">
                <Command size={21} />
              </span>
              <span>
                <strong>رفتن سریع به بخش‌ها</strong>
                <small>جست‌وجو با Control / Command + K</small>
              </span>
              <ChevronLeft size={18} />
            </button>
            {activeClinic && (
              <a
                className="destination-row"
                href={publicUrl(`/talk/${activeClinic.slug}`)}
                target="_blank"
                rel="noreferrer"
              >
                <span className="destination-icon">
                  <Headphones size={21} />
                </span>
                <span>
                  <strong>پذیرش آنلاین مرکز</strong>
                  <small>باز کردن صفحهٔ مراجعه‌کنندگان</small>
                </span>
                <ExternalLink size={17} />
              </a>
            )}
            <div className="app-version">
              {runtime.platform === "web" || runtime.platform === "desktop" ? (
                <Laptop size={18} />
              ) : (
                <Smartphone size={18} />
              )}
              <span>
                {runtime.platform === "web"
                  ? "نسخهٔ وب هم‌آوا"
                  : runtime.platform === "desktop"
                    ? "هم‌آوا برای رایانه"
                    : "همراه هم‌آوا"}
              </span>
              <bdi>{runtime.version}</bdi>
            </div>
          </section>
          <section className="companion-note">
            <CircleHelp size={21} />
            <div>
              <h2>با همان تیم، در هر دستگاه</h2>
              <p>
                نتیجهٔ هر اقدام پس از ثبت در سامانه نمایش داده می‌شود. هنگام قطع
                ارتباط، پس از اتصال دوباره وضعیت درخواست را بررسی کنید.
              </p>
            </div>
          </section>
          <button className="button secondary logout-action" onClick={onLogout}>
            <LogOut size={18} />
            خروج از حساب
          </button>
        </div>
      </div>
    </>
  );
}
