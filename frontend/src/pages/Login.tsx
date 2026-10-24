import { useState, type FormEvent } from "react";
import {
  ArrowUpLeft,
  CalendarDays,
  Check,
  Eye,
  EyeOff,
  Headphones,
  Link2,
  ShieldCheck,
} from "lucide-react";
import { errorText, post } from "../api";
import { Alert, Brand, Busy, Field } from "../components";
import { getRuntime } from "../platform";
import type { LoginResponse } from "../types";

export function Login({
  onLogin,
  onConnection,
}: {
  onLogin: (data: LoginResponse) => Promise<void>;
  onConnection: () => void;
}) {
  const runtime = getRuntime();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [visiblePassword, setVisiblePassword] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onLogin(
        await post<LoginResponse>("/auth/login", { email, password }),
      );
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="login-page workspace-login">
      <section className="login-story">
        <Brand />
        <div className="login-copy">
          <span className="eyebrow light">همراه تیم پذیرش</span>
          <h1>
            کارهای مرکز،
            <br />
            هماهنگ‌تر از همیشه.
          </h1>
          <p>
            از اولین گفت‌وگو تا نوبت و پیگیری؛ یک فضای روشن برای تیمی که هر روز
            پاسخ‌گوی آدم‌هاست.
          </p>
          <div className="login-workflow" aria-label="مسیر پذیرش">
            <span>
              <Headphones size={21} />
              <b>گفت‌وگو</b>
              <small>شنیدن درخواست</small>
            </span>
            <i aria-hidden="true" />
            <span>
              <CalendarDays size={21} />
              <b>نوبت</b>
              <small>تأیید زمان واقعی</small>
            </span>
            <i aria-hidden="true" />
            <span>
              <Check size={21} />
              <b>پیگیری</b>
              <small>ثبت نتیجهٔ روشن</small>
            </span>
          </div>
        </div>
        <div className="login-bottom">
          <ShieldCheck size={18} />
          <span>دسترسی هر همکار، متناسب با مسئولیت او</span>
        </div>
      </section>
      <section className="login-form-area">
        <div className="login-mobile-brand">
          <Brand />
        </div>
        <form className="login-form" onSubmit={submit}>
          <div className="eyebrow">خوش آمدید</div>
          <h2>ورود به فضای پذیرش</h2>
          <p className="muted">
            با حسابی که مدیر مرکز برای شما ساخته، وارد شوید.
          </p>
          <button className="login-server" type="button" onClick={onConnection}>
            <span className="login-server-icon">
              <Link2 size={19} />
            </span>
            <span>
              <small>سامانهٔ مرکز</small>
              <bdi>
                {runtime.serverUrl
                  ? new URL(runtime.serverUrl).host
                  : location.host}
              </bdi>
            </span>
            <span>بررسی اتصال</span>
          </button>
          {error && <Alert>{error}</Alert>}
          <Field label="ایمیل">
            <input
              required
              type="email"
              autoComplete="username"
              inputMode="email"
              autoCapitalize="none"
              spellCheck={false}
              dir="ltr"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="name@clinic.example"
            />
          </Field>
          <Field label="گذرواژه" controlId="login-password">
            <div className="password-field">
              <input
                id="login-password"
                required
                type={visiblePassword ? "text" : "password"}
                autoComplete="current-password"
                dir="ltr"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <button
                type="button"
                className="icon-button"
                aria-label={
                  visiblePassword ? "پنهان کردن گذرواژه" : "نمایش گذرواژه"
                }
                aria-pressed={visiblePassword}
                onClick={() => setVisiblePassword((value) => !value)}
              >
                {visiblePassword ? <EyeOff size={19} /> : <Eye size={19} />}
              </button>
            </div>
          </Field>
          <button className="button primary full" disabled={busy}>
            <Busy busy={busy}>ورود به هم‌آوا</Busy>
            <ArrowUpLeft size={18} />
          </button>
          {runtime.demoMode === true && (
            <div className="demo-login">
              <span className="demo-badge">محیط نمایشی</span>
              <p>
                برای آشنایی با برنامه، از داده‌های ساختگی مرکز نمونه استفاده
                کنید.
              </p>
              <button
                type="button"
                className="button secondary full"
                disabled={busy}
                onClick={() => {
                  setEmail("owner@example.test");
                  setPassword("DemoReception2026!");
                  setError("");
                }}
              >
                استفاده از حساب نمایشی
              </button>
            </div>
          )}
          <p className="login-support">
            برای دریافت حساب یا بازیابی گذرواژه، با مدیر مرکز تماس بگیرید.
          </p>
        </form>
        <span className="login-footer">
          هم‌آوا · ارتباط انسانی، پذیرش هوشمند
        </span>
      </section>
    </main>
  );
}
