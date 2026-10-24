import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  ArrowUpLeft,
  Bell,
  Building2,
  ChevronDown,
  Command,
  Headphones,
  LogOut,
  Menu,
  Search,
  ShieldCheck,
  WifiOff,
  X,
} from "lucide-react";
import {
  api,
  ApiError,
  clearToken,
  errorText,
  faDate,
  post,
  setToken,
  getToken,
} from "./api";
import { Alert, Brand, Empty, Loading } from "./components";
import { usePath, useRemote } from "./hooks";
import { getRuntime, publicUrl, refreshRuntime } from "./platform";
import { hasPermission, roleNames } from "./permissions";
import {
  canVisit,
  CommandMenu,
  MobileNavigation,
  MorePage,
  NavigationGroups,
  navigation,
} from "./Workspace";
import { Login } from "./pages/Login";
import { ServerConnection } from "./pages/Connection";
import type { Clinic, LoginResponse, User } from "./types";
import "./style.css";
import "./workspace.css";

const Overview = lazy(() =>
  import("./pages/Overview").then((m) => ({ default: m.Overview })),
);
const Appointments = lazy(() =>
  import("./pages/Appointments").then((m) => ({ default: m.Appointments })),
);
const Notifications = lazy(() =>
  import("./pages/Work").then((m) => ({ default: m.Notifications })),
);
const TaskQueue = lazy(() =>
  import("./pages/TaskQueue").then((m) => ({ default: m.TaskQueue })),
);
const Reports = lazy(() =>
  import("./pages/Reports").then((m) => ({ default: m.Reports })),
);
const Building = lazy(() =>
  import("./pages/Reports").then((m) => ({ default: m.Building })),
);
const ClinicSettings = lazy(() =>
  import("./pages/Settings").then((m) => ({ default: m.ClinicSettings })),
);
const Talk = lazy(() =>
  import("./pages/Talk").then((m) => ({ default: m.Talk })),
);
const Respond = lazy(() =>
  import("./pages/Respond").then((m) => ({ default: m.Respond })),
);
const Capacity = lazy(() =>
  import("./pages/Capacity").then((m) => ({ default: m.Capacity })),
);
const PartnerDashboard = lazy(() =>
  import("./pages/Partner").then((m) => ({ default: m.PartnerDashboard })),
);
const Calls = lazy(() =>
  import("./pages/Calls").then((m) => ({ default: m.Calls })),
);
const SetupGuide = lazy(() =>
  import("./pages/Setup").then((m) => ({ default: m.SetupGuide })),
);
const ControlCenter = lazy(() =>
  import("./pages/ControlCenter").then((m) => ({ default: m.ControlCenter })),
);

function Starting() {
  return (
    <main className="auth-loading">
      <Brand />
      <Loading rows={2} />
    </main>
  );
}

export function App() {
  const { path, search, navigate } = usePath();
  const [runtime, setRuntime] = useState(getRuntime);
  const [user, setUser] = useState<User | null>(null);
  const [checking, setChecking] = useState(!!getToken());
  const [authError, setAuthError] = useState("");
  const [sessionMessage, setSessionMessage] = useState("");
  const [mobileNav, setMobileNav] = useState(false);
  const [commands, setCommands] = useState(false);
  const [switching, setSwitching] = useState(false);
  const [mobile, setMobile] = useState(
    () => matchMedia("(max-width: 900px)").matches,
  );
  const sidebar = useRef<HTMLElement>(null);
  const menuButton = useRef<HTMLButtonElement>(null);
  const clinics = useRemote<Clinic[]>(user ? "/clinics" : null);
  const integrations = useRemote<{
    mode: string;
    items: { id: string; name: string; status: string }[];
  }>(
    user && hasPermission(user, "integration:read")
      ? "/operations/integrations"
      : null,
  );
  const activeClinic = clinics.data?.find(
    (clinic) => clinic.id === user?.tenant_id,
  );
  const checkSession = useCallback(async () => {
    if (!getToken()) {
      setChecking(false);
      return;
    }
    setChecking(true);
    setAuthError("");
    try {
      setUser(await api<User>("/me"));
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) await clearToken();
      else setAuthError(errorText(error));
    } finally {
      setChecking(false);
    }
  }, []);
  useEffect(() => {
    void checkSession();
  }, [checkSession]);
  useEffect(() => {
    const changed = () => setRuntime(getRuntime());
    const storageError = () =>
      setSessionMessage(
        "حفظ ورود در این دستگاه ممکن نشد. می‌توانید کار را ادامه دهید؛ پس از بستن برنامه دوباره وارد شوید.",
      );
    const expired = () => {
      void clearToken();
      setUser(null);
      setAuthError("");
      setSessionMessage("نشست شما پایان یافته است. دوباره وارد شوید.");
    };
    window.addEventListener("runtime-changed", changed);
    window.addEventListener("native-storage-error", storageError);
    window.addEventListener("session-expired", expired);
    return () => {
      window.removeEventListener("runtime-changed", changed);
      window.removeEventListener("native-storage-error", storageError);
      window.removeEventListener("session-expired", expired);
    };
  }, []);
  useEffect(() => {
    const query = matchMedia("(max-width: 900px)");
    const update = () => {
      setMobile(query.matches);
      if (!query.matches) setMobileNav(false);
    };
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!mobileNav) return;
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    sidebar.current?.querySelector<HTMLButtonElement>("button")?.focus();
    return () => {
      document.body.style.overflow = previous;
      menuButton.current?.focus();
    };
  }, [mobileNav]);
  useEffect(() => {
    setMobileNav(false);
    const current = navigation.find((item) => item.path === path);
    if (user && current)
      document.title = `${current.label} · ${user.tenant_name} · هم‌آوا`;
  }, [path, search, user]);
  useEffect(() => {
    if (!user || user.role === "partner") return;
    const keyboard = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setCommands((open) => !open);
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => window.removeEventListener("keydown", keyboard);
  }, [user]);
  const login = async (data: LoginResponse) => {
    await setToken(data.access_token);
    setUser(data.user);
    setSessionMessage("");
    setAuthError("");
  };
  async function logout() {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 6000);
    let revoked = false;
    try {
      await api("/auth/logout", {
        method: "POST",
        body: JSON.stringify({ all_devices: false }),
        signal: controller.signal,
      });
      revoked = true;
    } catch {
      /* Local logout must remain available without a server response. */
    } finally {
      window.clearTimeout(timeout);
    }
    await clearToken();
    setUser(null);
    setAuthError("");
    setCommands(false);
    setSessionMessage(
      revoked
        ? ""
        : "از این دستگاه خارج شدید. لغو نشست روی سرور تأیید نشد؛ در صورت نیاز از مدیر مرکز بخواهید نشست‌های حساب را بررسی کند.",
    );
    navigate("/");
  }
  async function switchClinic(id: string) {
    setSwitching(true);
    setSessionMessage("");
    try {
      await login(await post<LoginResponse>("/auth/switch", { tenant_id: id }));
      return true;
    } catch (error) {
      setSessionMessage(errorText(error));
      return false;
    } finally {
      setSwitching(false);
    }
  }
  if (runtime.setupRequired || path === "/connection")
    return (
      <ServerConnection
        onCancel={
          runtime.setupRequired
            ? undefined
            : () => navigate(user ? "/more" : "/")
        }
      />
    );
  if (path.startsWith("/respond/"))
    return (
      <Suspense fallback={<Starting />}>
        <Respond responseId={path.slice(9)} />
      </Suspense>
    );
  if (path.startsWith("/talk/"))
    return (
      <Suspense fallback={<Starting />}>
        <Talk slug={decodeURIComponent(path.slice(6))} />
      </Suspense>
    );
  if (checking) return <Starting />;
  if (authError && !user)
    return (
      <main className="auth-loading">
        <Brand />
        <section className="panel reconnect-panel">
          <WifiOff size={32} />
          <h1>ارتباط با مرکز برقرار نشد</h1>
          <p>
            اطلاعات ورود شما حفظ شده است. اتصال را بررسی کنید و دوباره ادامه
            دهید.
          </p>
          <Alert>{authError}</Alert>
          <div className="inline-actions">
            <button
              className="button primary"
              onClick={() => {
                void refreshRuntime();
                void checkSession();
              }}
            >
              تلاش دوباره
            </button>
            <button
              className="button secondary"
              onClick={() => navigate("/connection")}
            >
              بررسی اتصال
            </button>
            <button className="button quiet" onClick={() => void logout()}>
              ورود با حساب دیگر
            </button>
          </div>
        </section>
      </main>
    );
  if (!user)
    return (
      <>
        {sessionMessage && (
          <div className="session-toast">
            <Alert>{sessionMessage}</Alert>
          </div>
        )}
        <Login onLogin={login} onConnection={() => navigate("/connection")} />
      </>
    );
  if (user.role === "partner")
    return (
      <Suspense fallback={<Starting />}>
        <PartnerDashboard
          key={user.tenant_id}
          user={user}
          clinics={clinics.data || []}
          switching={switching}
          onSwitch={(id) => void switchClinic(id)}
          onLogout={() => void logout()}
        />
      </Suspense>
    );
  const current = navigation.find((item) => item.path === path);
  const allowed = current && canVisit(user, current);
  let page;
  if (!current)
    page = (
      <section className="panel">
        <Empty
          title="این صفحه پیدا نشد"
          description="از فهرست بخش‌ها، مسیر موردنظر را انتخاب کنید."
          action={
            <button className="button primary" onClick={() => navigate("/")}>
              بازگشت به امروز
            </button>
          }
        />
      </section>
    );
  else if (!allowed)
    page = (
      <section className="panel">
        <Empty
          title="این بخش در دسترسی حساب شما نیست"
          description="اگر برای انجام مسئولیت خود به این بخش نیاز دارید، با مدیر مرکز هماهنگ کنید."
          action={
            <button
              className="button primary"
              onClick={() => navigate("/more")}
            >
              دسترسی‌های من
            </button>
          }
        />
      </section>
    );
  else if (path === "/appointments")
    page = <Appointments user={user} search={search} />;
  else if (path === "/tasks") page = <TaskQueue user={user} />;
  else if (path === "/calls")
    page = (
      <Calls user={user} clinicSlug={activeClinic?.slug} navigate={navigate} />
    );
  else if (path === "/notifications") page = <Notifications />;
  else if (path === "/capacity")
    page = <Capacity user={user} search={search} />;
  else if (path === "/controls")
    page = <ControlCenter user={user} search={search} />;
  else if (path === "/reports") page = <Reports user={user} />;
  else if (path === "/building") page = <Building role={user.role} />;
  else if (path === "/setup") page = <SetupGuide navigate={navigate} />;
  else if (
    path === "/more" ||
    (path === "/" &&
      !hasPermission(user, "appointment:read") &&
      !hasPermission(user, "task:read"))
  )
    page = (
      <MorePage
        user={user}
        clinics={clinics.data || []}
        switching={switching}
        onSwitch={(id) => void switchClinic(id)}
        navigate={navigate}
        onLogout={() => void logout()}
        onCommands={() => setCommands(true)}
      />
    );
  else if (path === "/settings")
    page = (
      <ClinicSettings
        user={user}
        role={user.role}
        search={search}
        onCreated={async (id) => {
          if (!(await switchClinic(id)))
            throw new Error(
              "مرکز ایجاد شد، اما ورود به آن ممکن نشد. از فهرست مرکزها دوباره انتخاب کنید.",
            );
          clinics.refresh();
          navigate("/setup");
        }}
      />
    );
  else
    page = (
      <Overview
        user={user}
        navigate={navigate}
        clinicSlug={activeClinic?.slug}
        integrations={integrations.data}
        integrationsError={integrations.error}
      />
    );
  return (
    <div className="app-shell reception-workspace">
      <a className="skip-link" href="#main-content">
        رفتن به محتوای اصلی
      </a>
      {mobileNav && (
        <button
          className="nav-scrim"
          aria-label="بستن فهرست"
          onClick={() => setMobileNav(false)}
        />
      )}
      <aside
        ref={sidebar}
        className={`sidebar ${mobileNav ? "open" : ""}`}
        inert={mobile && !mobileNav}
        role={mobileNav ? "dialog" : undefined}
        aria-modal={mobileNav ? true : undefined}
        aria-label={mobileNav ? "فهرست اصلی" : "فضای کاری مرکز"}
        onKeyDown={(event) => {
          if (!mobileNav) return;
          if (event.key === "Escape") {
            event.preventDefault();
            setMobileNav(false);
          }
          if (event.key === "Tab") {
            const items = [
              ...(sidebar.current?.querySelectorAll<HTMLElement>(
                "button:not(:disabled),a[href],select:not(:disabled)",
              ) || []),
            ].filter(
              (item) =>
                item.getClientRects().length &&
                getComputedStyle(item).visibility !== "hidden",
            );
            const first = items[0],
              last = items[items.length - 1];
            if (event.shiftKey && document.activeElement === first) {
              event.preventDefault();
              last?.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
              event.preventDefault();
              first?.focus();
            }
          }
        }}
      >
        <div className="sidebar-brand">
          <Brand />
          <button
            className="icon-button mobile-only"
            aria-label="بستن فهرست"
            onClick={() => setMobileNav(false)}
          >
            <X size={20} />
          </button>
        </div>
        <div className="clinic-switch">
          <Building2 size={20} />
          <div className="clinic-select-wrap">
            <label className="sr-only" htmlFor="clinic-switch">
              انتخاب مرکز
            </label>
            <select
              id="clinic-switch"
              value={user.tenant_id}
              disabled={switching || !clinics.data}
              onChange={(event) => void switchClinic(event.target.value)}
            >
              {(
                clinics.data || [{ id: user.tenant_id, name: user.tenant_name }]
              ).map((clinic) => (
                <option key={clinic.id} value={clinic.id}>
                  {clinic.name}
                </option>
              ))}
            </select>
            <small>{roleNames[user.role] || "حساب مرکز"}</small>
          </div>
          <ChevronDown size={15} />
        </div>
        <NavigationGroups user={user} path={path} navigate={navigate} />
        <div className="sidebar-bottom">
          {activeClinic && (
            <a
              href={publicUrl(`/talk/${activeClinic.slug}`)}
              className="reception-link"
              target="_blank"
              rel="noreferrer"
            >
              <span>
                <Headphones size={20} />
              </span>
              <div>
                <strong>پذیرش آنلاین</strong>
                <small>صفحهٔ مراجعه‌کنندگان</small>
              </div>
              <ArrowUpLeft size={18} />
            </a>
          )}
          <div className="profile">
            <span className="avatar">{user.name?.slice(0, 1) || "م"}</span>
            <div>
              <strong>{user.name}</strong>
              <small>{roleNames[user.role] || "حساب مرکز"}</small>
            </div>
            <button
              className="icon-button"
              title="خروج"
              aria-label="خروج از حساب"
              onClick={() => void logout()}
            >
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main-wrap" inert={mobileNav}>
        <header className="topbar">
          <div className="breadcrumb">
            <button
              className="icon-button mobile-only"
              ref={menuButton}
              aria-expanded={mobileNav}
              aria-label="باز کردن فهرست"
              onClick={() => setMobileNav(true)}
            >
              <Menu size={22} />
            </button>
            <div className="workspace-context">
              <span>{user.tenant_name}</span>
              <strong>{current?.label || "صفحهٔ پیدا نشد"}</strong>
            </div>
          </div>
          <div className="topbar-right">
            <button
              className="workspace-search"
              aria-label="جست‌وجوی بخش‌ها و اقدام‌ها"
              aria-keyshortcuts="Control+k Meta+k"
              onClick={() => setCommands(true)}
            >
              <Search size={19} />
              <span>رفتن به…</span>
              <kbd>
                <Command size={12} /> K
              </kbd>
            </button>
            {(integrations.data?.mode === "demo" || runtime.demoMode) && (
              <span className="demo-badge">نسخهٔ نمایشی</span>
            )}
            <span className="today-label">
              {faDate(new Date())}
              <small>به وقت تهران</small>
            </span>
            {hasPermission(user, "task:read") && (
              <button
                className="icon-button"
                aria-label="مشاهده پیام‌ها"
                onClick={() => navigate("/notifications")}
              >
                <Bell size={20} />
              </button>
            )}
            <button
              className="topbar-avatar"
              aria-label="حساب و دسترسی‌های من"
              onClick={() => navigate("/more")}
            >
              {user.name?.slice(0, 1) || "م"}
            </button>
          </div>
        </header>
        <main
          id="main-content"
          tabIndex={-1}
          className="page-content"
          key={user.tenant_id}
        >
          {sessionMessage && (
            <Alert onClose={() => setSessionMessage("")}>
              {sessionMessage}
            </Alert>
          )}
          {clinics.error && (
            <Alert kind="info">
              فهرست مرکزها تازه نشد. اطلاعات مرکز فعلی نمایش داده می‌شود؛ برای
              تغییر مرکز اتصال را بررسی کنید.
            </Alert>
          )}
          {switching ? (
            <Loading rows={4} />
          ) : (
            <Suspense fallback={<Loading rows={4} />}>{page}</Suspense>
          )}
        </main>
        <footer className="app-footer">
          <span>
            <ShieldCheck size={14} />
            هم‌آوا · ارتباط انسانی، پذیرش هوشمند
          </span>
          <span>زمان‌ها به وقت تهران نمایش داده می‌شوند.</span>
        </footer>
        <MobileNavigation user={user} path={path} navigate={navigate} />
      </div>
      {commands && (
        <CommandMenu
          user={user}
          onClose={() => setCommands(false)}
          navigate={navigate}
        />
      )}
    </div>
  );
}
