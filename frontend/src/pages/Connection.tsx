import { useState, type FormEvent } from "react";
import {
  ArrowLeft,
  ArrowUpLeft,
  Building2,
  CheckCircle2,
  Link2,
  RefreshCw,
  ShieldCheck,
  Wifi,
} from "lucide-react";
import { Alert, Brand, Busy, Field } from "../components";
import { errorText } from "../api";
import { getRuntime, saveServerUrl, testServerUrl } from "../platform";

export function ServerConnection({ onCancel }: { onCancel?: () => void }) {
  const runtime = getRuntime();
  const [address, setAddress] = useState(
    runtime.serverUrl || (runtime.platform === "web" ? location.origin : ""),
  );
  const [verified, setVerified] = useState<Awaited<
    ReturnType<typeof testServerUrl>
  > | null>(null);
  const [busy, setBusy] = useState<"check" | "save" | "">("");
  const [error, setError] = useState("");
  async function check(event: FormEvent) {
    event.preventDefault();
    setBusy("check");
    setError("");
    setVerified(null);
    try {
      setVerified(await testServerUrl(address));
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy("");
    }
  }
  async function connect() {
    if (!verified) return;
    setBusy("save");
    setError("");
    try {
      await saveServerUrl(verified.serverUrl);
    } catch (error) {
      setError(errorText(error));
      setBusy("");
    }
  }
  return (
    <main className="connection-page">
      <header className="connection-header">
        <Brand />
        {onCancel && !runtime.setupRequired && (
          <button type="button" className="button quiet" onClick={onCancel}>
            <ArrowLeft size={17} />
            بازگشت
          </button>
        )}
      </header>
      <div className="connection-layout">
        <section className="connection-intro">
          <div className="eyebrow">هم‌آوا، کنار تیم شما</div>
          <h1>
            به مرکز خود
            <br />
            متصل شوید.
          </h1>
          <p>
            نشانی سامانه را از مدیر مرکز بگیرید. پس از بررسی اتصال، با حساب
            خودتان وارد می‌شوید.
          </p>
          <ol className="connection-steps">
            <li className="complete">
              <span>۱</span>
              <div>
                <strong>نشانی مرکز</strong>
                <small>همان سامانه‌ای که تیم شما استفاده می‌کند</small>
              </div>
            </li>
            <li className={verified ? "complete" : ""}>
              <span>۲</span>
              <div>
                <strong>بررسی اتصال</strong>
                <small>از دسترس‌پذیری و هویت سامانه مطمئن شوید</small>
              </div>
            </li>
            <li>
              <span>۳</span>
              <div>
                <strong>ورود به فضای کاری</strong>
                <small>با دسترسی مخصوص حساب شما</small>
              </div>
            </li>
          </ol>
          <div className="connection-trust">
            <ShieldCheck size={20} />
            <p>
              پیش از ورود، نشانی را با مدیر مرکز تطبیق دهید. برای بررسی اتصال،
              گذرواژه‌ای ارسال نمی‌شود.
            </p>
          </div>
        </section>
        <section className="panel connection-form-panel">
          <div className="connection-mark">
            <Building2 size={28} />
          </div>
          <h2>سامانهٔ مرکز شما</h2>
          <p className="muted">
            نشانی کامل را وارد کنید؛ مانند <bdi>https://clinic.example</bdi>.
          </p>
          <form onSubmit={check}>
            <Field
              label="نشانی سامانه"
              controlId="server-address"
              hint={
                runtime.platform === "android"
                  ? "در برنامهٔ اندروید، نشانی امن با https:// لازم است. نشانی را از مدیر مرکز بگیرید."
                  : "نشانی باید با https:// شروع شود. برای آزمون روی همین دستگاه، نشانی محلی هم پذیرفته می‌شود."
              }
            >
              <div className="connection-input">
                <Link2 size={18} />
                <input
                  id="server-address"
                  type="url"
                  inputMode="url"
                  autoCapitalize="none"
                  autoCorrect="off"
                  spellCheck={false}
                  autoComplete="url"
                  required
                  dir="ltr"
                  aria-label="نشانی سامانه"
                  value={address}
                  placeholder="https://clinic.example"
                  disabled={!!busy}
                  onChange={(event) => {
                    setAddress(event.target.value);
                    setVerified(null);
                    setError("");
                  }}
                />
              </div>
            </Field>
            {error && <Alert>{error}</Alert>}
            {verified && (
              <div className="connection-verified" role="status">
                <CheckCircle2 size={22} />
                <div>
                  <strong>سامانهٔ هم‌آوا در دسترس است</strong>
                  <bdi>{new URL(verified.serverUrl).host}</bdi>
                  <span>
                    {verified.demoMode
                      ? "این سامانه در حالت نمایشی است."
                      : "با حساب اختصاصی مرکز ادامه دهید."}
                  </span>
                </div>
              </div>
            )}
            {verified ? (
              <>
                <p className="connection-change-note">
                  با ادامه، حساب فعلی این برنامه بسته می‌شود و در سامانهٔ
                  انتخاب‌شده وارد می‌شوید.
                </p>
                <button
                  type="button"
                  className="button primary full"
                  disabled={!!busy}
                  onClick={() => void connect()}
                >
                  <Busy busy={busy === "save"}>اتصال و ادامهٔ ورود</Busy>
                  <ArrowUpLeft size={18} />
                </button>
                <button className="button quiet full" disabled={!!busy}>
                  <RefreshCw size={16} />
                  بررسی دوباره
                </button>
              </>
            ) : (
              <button
                className="button primary full"
                disabled={!!busy || !address.trim()}
              >
                <Busy busy={busy === "check"}>
                  <Wifi size={18} />
                  بررسی اتصال
                </Busy>
              </button>
            )}
          </form>
          <p className="connection-help">
            نشانی را ندارید؟ از مسئول راه‌اندازی مرکز بخواهید آن را برای شما
            بفرستد.
          </p>
        </section>
      </div>
      <footer className="connection-footer">
        هم‌آوا · ارتباط انسانی، پذیرش هوشمند
      </footer>
    </main>
  );
}
