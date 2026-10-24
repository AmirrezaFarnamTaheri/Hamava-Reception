import { useEffect, useRef, useState } from "react";
import { CalendarCheck2, CheckCircle2, ShieldCheck } from "lucide-react";
import { api, errorText, faDate, faNumber, post } from "../api";
import { Alert, Brand, Busy, Loading, Status } from "../components";
interface ResponseView {
  response_id: string;
  clinic: string;
  reference: string;
  display: string;
  booking_status: string;
  response_status: string;
  expires_at: string;
  action: "CONFIRM" | "DECLINE" | null;
  message?: string;
}
const responseText: Record<string, string> = {
  CONFIRMED_ATTENDANCE_INTENT: "قصد مراجعهٔ شما ثبت شد. سپاس که اطلاع دادید.",
  DECLINE_REVIEW_REQUIRED:
    "درخواست شما برای بررسی پذیرش ثبت شد. نوبت هنوز لغو نشده است؛ تیم مرکز پیگیری می‌کند.",
  DECLINED_CANCELED:
    "نوبت با درخواست شما لغو شد. اگر وجهی پرداخت شده، بازپرداخت باید با مرکز پیگیری شود.",
};
export function Respond({ responseId }: { responseId: string }) {
  const token = useRef(location.hash.slice(1));
  const [data, setData] = useState<ResponseView | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [action, setAction] = useState<"CONFIRM" | "DECLINE" | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    history.replaceState(null, "", location.pathname);
  }, []);
  useEffect(() => {
    if (!token.current) {
      setLoading(false);
      setError(
        "برای مشاهدهٔ این نوبت، پیوند کامل ارسال‌شده از طرف مرکز را دوباره باز کنید.",
      );
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api<ResponseView>(
      `/public/appointments/responses/${encodeURIComponent(responseId)}/view`,
      {
        method: "POST",
        body: JSON.stringify({ token: token.current }),
        token: null,
        signal: controller.signal,
      },
    )
      .then(setData)
      .catch((e) => {
        if (e.name !== "AbortError") setError(errorText(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [responseId, retry]);
  async function submit() {
    if (!action || !confirmed) return;
    setBusy(true);
    setError("");
    try {
      setData(
        await post<ResponseView>(
          `/public/appointments/responses/${encodeURIComponent(responseId)}`,
          { token: token.current, action },
          null,
        ),
      );
      setAction(null);
      setConfirmed(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <main className="respond-page">
      <header>
        <Brand />
        <span>
          <ShieldCheck size={15} />
          پاسخ امن به مرکز
        </span>
      </header>
      <section className="panel respond-panel">
        <div className="respond-icon">
          <CalendarCheck2 size={30} />
        </div>
        <h1>هماهنگی مراجعه</h1>
        {loading ? (
          <Loading rows={3} />
        ) : data ? (
          <>
            <h2>{data.clinic}</h2>
            <div className="selected-appointment">
              <strong>{data.display}</strong>
              <span>
                کد نوبت: <bdi>{faNumber(data.reference)}</bdi>
              </span>
              <Status value={data.booking_status} />
            </div>
            {data.response_status !== "AWAITING_RESPONSE" ? (
              <Alert
                kind={
                  data.response_status === "DECLINE_REVIEW_REQUIRED"
                    ? "info"
                    : "success"
                }
              >
                <CheckCircle2 size={18} />
                {data.message ||
                  responseText[data.response_status] ||
                  "پاسخ شما ثبت شده است."}
              </Alert>
            ) : action ? (
              <>
                <p>
                  {action === "CONFIRM"
                    ? "حضور در زمان بالا را تأیید می‌کنید؟"
                    : "عدم امکان مراجعه را اعلام می‌کنید؟ در صورت مجاز بودن طبق قواعد مرکز، نوبت لغو می‌شود؛ در غیر این صورت برای بررسی پذیرش ارسال خواهد شد."}
                </p>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                  />
                  <span>زمان و تصمیم خود را بررسی کرده‌ام.</span>
                </label>
                <div className="modal-actions">
                  <button
                    className={`button ${action === "DECLINE" ? "danger" : "primary"}`}
                    disabled={busy || !confirmed}
                    onClick={() => void submit()}
                  >
                    <Busy busy={busy}>تأیید پاسخ</Busy>
                  </button>
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() => {
                      setAction(null);
                      setConfirmed(false);
                    }}
                  >
                    بازگشت
                  </button>
                </div>
              </>
            ) : (
              <>
                <p>آیا برای مراجعه در این زمان برنامه‌ریزی کرده‌اید؟</p>
                <div className="respond-options">
                  <button
                    className="button primary"
                    onClick={() => setAction("CONFIRM")}
                  >
                    بله، قصد مراجعه دارم
                  </button>
                  <button
                    className="button secondary"
                    onClick={() => setAction("DECLINE")}
                  >
                    امکان مراجعه ندارم
                  </button>
                </div>
                <small className="muted">
                  اعتبار پیوند تا {faDate(data.expires_at, true)}
                </small>
              </>
            )}
          </>
        ) : null}
        {error && <Alert>{error}</Alert>}
        {!loading && !data && token.current && (
          <button
            className="button secondary"
            onClick={() => setRetry((value) => value + 1)}
          >
            تلاش دوباره
          </button>
        )}
        <p className="field-hint">
          تأیید قصد مراجعه جایگزین ثبت حضور در مرکز نیست. برای پرسش پزشکی با
          پزشک خود تماس بگیرید.
        </p>
      </section>
      <footer>هم‌آوا · همراه تیم پذیرش</footer>
    </main>
  );
}
