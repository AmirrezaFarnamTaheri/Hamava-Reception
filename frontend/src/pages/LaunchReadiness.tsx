import { useState, type FormEvent } from "react";
import { ClipboardCheck, ShieldCheck } from "lucide-react";
import { errorText, faDate, post } from "../api";
import {
  Alert,
  Busy,
  Field,
  Loading,
  Retry,
  SectionTitle,
  Status,
} from "../components";
import { useRemote } from "../hooks";
interface Readiness {
  current_mode: string;
  target_mode: string;
  configuration_fingerprint: string;
  approved: boolean;
  production_enforced: boolean;
  required_checks: string[];
  verification_kind: string;
  attestation: null | {
    id: string;
    created_at: string;
    valid_until: string;
    reviewer_user_id: string;
    reviewer_name: string;
    checks: Record<string, boolean>;
    evidence_refs: Record<string, string>;
  };
}
const modes: Record<string, string> = {
  after_hours: "پاسخ‌گویی پس از ساعت کاری",
  overflow: "تماس‌های بی‌پاسخ",
  human_primary: "پذیرش انسانی در اولویت",
  supervised: "دستیار با تأیید پذیرش",
  ai_primary: "دستیار در اولویت",
};
const checks: Record<string, { label: string; hint: string }> = {
  booking: {
    label: "ثبت نوبت تأییدشده",
    hint: "نوبت واقعیِ آزمایشی، اطلاعات صحیح و تأیید صریح مراجعه‌کننده بررسی شده است.",
  },
  cancellation: {
    label: "لغو و تغییر نوبت",
    hint: "احراز درخواست، حفظ نوبت قبلی تا موفقیت و نتیجهٔ لغو بررسی شده است.",
  },
  conflict: {
    label: "جلوگیری از تداخل زمان",
    hint: "درخواست‌های هم‌زمان باعث ثبت دو نوبت برای یک ظرفیت نشده‌اند.",
  },
  provider_failure: {
    label: "قطع یا خطای سرویس",
    hint: "شکست ارائه‌دهنده و بازیابی درخواست، نتیجهٔ مبهم یا موفقیت ساختگی ایجاد نکرده است.",
  },
  handoff: {
    label: "تحویل به تیم پذیرش",
    hint: "درخواست همراهی انسانی و مسئولیت پیگیری در مسیر مورد استفادهٔ مرکز بررسی شده است.",
  },
};
function Attest({ data, onSaved }: { data: Readiness; onSaved: () => void }) {
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [evidence, setEvidence] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const valid = data.required_checks.every(
    (check) => selected[check] && evidence[check]?.trim(),
  );
  const pausedRequired =
    data.production_enforced && data.current_mode !== "paused";
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/operations/uat/approve", {
        target_mode: data.target_mode,
        configuration_fingerprint: data.configuration_fingerprint,
        checks: Object.fromEntries(
          data.required_checks.map((check) => [check, !!selected[check]]),
        ),
        evidence_refs: Object.fromEntries(
          data.required_checks.map((check) => [check, evidence[check].trim()]),
        ),
        confirmed,
      });
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="settings-form" onSubmit={submit}>
      <section className="panel settings-panel">
        <SectionTitle
          title="مرور شواهد آزمون مرکز"
          description="صاحب‌اختیار مرکز، نتایج آزمون‌های ساختگی را برای همین برنامه و قواعد بررسی و ثبت می‌کند."
        />
        {pausedRequired && (
          <Alert kind="info">
            برای بررسی و تغییر پیکربندی عملیاتی، ابتدا حالت «توقف پذیرش خودکار»
            را در اطلاعات و پذیرش انتخاب کنید.
          </Alert>
        )}
        <fieldset disabled={busy || pausedRequired}>
          {data.required_checks.map((check) => (
            <div className="uat-check" key={check}>
              <label className="check-field">
                <input
                  type="checkbox"
                  required
                  checked={!!selected[check]}
                  onChange={(event) =>
                    setSelected({ ...selected, [check]: event.target.checked })
                  }
                />
                <span>
                  <strong>{checks[check]?.label || "آزمون مرکز"}</strong>
                  <small>{checks[check]?.hint}</small>
                </span>
              </label>
              <Field
                label={`مرجع شواهد ${checks[check]?.label || "آزمون"}`}
                hint="شمارهٔ صورت‌جلسه، مسیر گزارش یا مرجع قابل بررسی؛ رمز و اطلاعات بیمار وارد نکنید."
              >
                <input
                  required
                  minLength={3}
                  maxLength={300}
                  value={evidence[check] || ""}
                  onChange={(event) =>
                    setEvidence({ ...evidence, [check]: event.target.value })
                  }
                />
              </Field>
            </div>
          ))}
          <label className="check-field">
            <input
              type="checkbox"
              required
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            <span>
              با اختیار مرکز، شواهد همین پیکربندی و روش پذیرش را مرور کرده‌ام و
              مسئولیت این تأیید را می‌پذیرم.
            </span>
          </label>
        </fieldset>
        <p className="field-hint">
          تأیید تا ۳۰ روز اعتبار دارد. تغییر قواعد، خدمات، اطلاعات مالی یا
          اختیار تأییدکننده می‌تواند آن را بی‌اعتبار کند. آمادگی خط واقعی و
          ارائه‌دهندگان باید با شواهد همان مسیر نیز بررسی شود.
        </p>
        {error && <Alert>{error}</Alert>}
        <button
          className="button primary"
          disabled={busy || !valid || !confirmed || pausedRequired}
        >
          <Busy busy={busy}>
            <ClipboardCheck size={17} />
            ثبت تأیید آمادگی مرکز
          </Busy>
        </button>
      </section>
    </form>
  );
}
export function LaunchReadiness() {
  const [mode, setMode] = useState("ai_primary");
  const result = useRemote<Readiness>(`/operations/uat?target_mode=${mode}`);
  const [message, setMessage] = useState("");
  return (
    <>
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <section className="panel settings-panel">
        <SectionTitle
          title="آمادگی راه‌اندازی"
          description="فعال‌سازی پذیرش عملیاتی بر پایهٔ پیکربندی مشخص و شواهد تأییدشدهٔ مرکز."
        />
        <Field label="روش پذیرش مورد تأیید">
          <select
            value={mode}
            onChange={(event) => setMode(event.target.value)}
          >
            {Object.entries(modes).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </Field>
        {result.data && (
          <Alert kind="info">
            {result.data.production_enforced
              ? "برای فعال‌سازی در محیط عملیاتی، تأیید معتبر همین پیکربندی لازم است."
              : "در محیط نمایشی، این بررسی ثبت می‌شود و مانع استفادهٔ آزمایشی نیست."}
          </Alert>
        )}
      </section>
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading ? (
        <Loading rows={4} />
      ) : (
        result.data &&
        (result.data.approved && result.data.attestation ? (
          <section className="panel settings-panel">
            <SectionTitle
              title="تأیید معتبر مرکز"
              description="این سابقه به روش پذیرش و پیکربندی جاری مربوط است."
            />
            <div className="selected-appointment">
              <Status value="CONFIRMED" />
              <strong>{result.data.attestation.reviewer_name}</strong>
              <span>
                ثبت در {faDate(result.data.attestation.created_at, true)}
              </span>
              <span>
                اعتبار تا {faDate(result.data.attestation.valid_until, true)}
              </span>
            </div>
            <dl className="policy-facts">
              {result.data.required_checks.map((check) => (
                <div key={check}>
                  <dt>{checks[check]?.label || "آزمون مرکز"}</dt>
                  <dd>{result.data?.attestation?.evidence_refs[check]}</dd>
                </div>
              ))}
            </dl>
            <p className="field-hint">
              پس از اطمینان از آمادگی مسیر مورد استفاده، روش پذیرش را در بخش
              اطلاعات و پذیرش انتخاب کنید.
            </p>
          </section>
        ) : (
          <Attest
            key={`${result.data.target_mode}:${result.data.configuration_fingerprint}`}
            data={result.data}
            onSaved={() => {
              result.refresh();
              setMessage("تأیید صاحب‌اختیار مرکز و مراجع شواهد ثبت شد.");
            }}
          />
        ))
      )}
      <div className="note-line">
        <ShieldCheck size={17} />
        <span>
          ثبت این فرم، گواهی خودکار اپراتور تلفن یا درگاه پرداخت صادر نمی‌کند.
        </span>
      </div>
    </>
  );
}
