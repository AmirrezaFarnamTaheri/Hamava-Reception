import { useState, type FormEvent } from "react";
import { FileCheck2, Save } from "lucide-react";
import { api, errorText, faDate, faNumber } from "../api";
import {
  Alert,
  Busy,
  Field,
  Loading,
  Retry,
  SectionTitle,
} from "../components";
import { useRemote } from "../hooks";
import type { PaymentTerms } from "../types";

export interface PaymentPolicy extends PaymentTerms {
  currency: "TOMAN";
  merchant_alias: string | null;
  merchant_ready: boolean;
  merchant_configuration_status: string;
  demonstration: boolean;
  published_at: string | null;
  published_by: string | null;
}

export function PaymentTermsDetails({ terms }: { terms: PaymentTerms }) {
  return (
    <details className="payment-terms">
      <summary>شرایط بیعانه، لغو و بازپرداخت</summary>
      <dl>
        <div>
          <dt>بیعانه</dt>
          <dd>{terms.deposit_terms || "شرایطی منتشر نشده است."}</dd>
        </div>
        <div>
          <dt>لغو نوبت</dt>
          <dd>{terms.cancellation_terms || "شرایطی منتشر نشده است."}</dd>
        </div>
        <div>
          <dt>بازپرداخت</dt>
          <dd>{terms.refund_terms || "شرایطی منتشر نشده است."}</dd>
        </div>
      </dl>
      <p className="field-hint">
        نسخهٔ {faNumber(terms.version)} · مهلت پرداخت:{" "}
        {faNumber(terms.hold_minutes)} دقیقه. نوبتِ منتظر پرداخت تا تأیید نتیجهٔ
        پرداخت قطعی نیست.
      </p>
      {terms.synthetic && (
        <p className="field-hint">
          این شرایط مربوط به پرداخت ساختگی در محیط نمایشی است.
        </p>
      )}
    </details>
  );
}

function PolicyForm({
  policy,
  canEdit,
  onSaved,
}: {
  policy: PaymentPolicy;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const [form, setForm] = useState(policy);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!confirmed || !canEdit) return;
    setBusy(true);
    setError("");
    try {
      await api("/operations/payment-policy", {
        method: "PUT",
        body: JSON.stringify({
          version: policy.version,
          enabled: form.enabled,
          hold_minutes: form.hold_minutes,
          deposit_terms: form.deposit_terms.trim(),
          cancellation_terms: form.cancellation_terms.trim(),
          refund_terms: form.refund_terms.trim(),
          confirmed,
        }),
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
          title="شرایط مالی منتشرشدهٔ مرکز"
          description="پیش از دریافت بیعانه، شرایط برای مراجعه‌کننده نمایش داده می‌شود و پذیرش نسخهٔ همان شرایط ثبت می‌شود."
        />
        {policy.demonstration && (
          <Alert kind="info">
            این مرکز در محیط نمایشی است. پرداخت‌های آزمایشی، دریافت یا انتقال
            واقعی پول را نشان نمی‌دهند.
          </Alert>
        )}
        <fieldset disabled={busy || !canEdit}>
          <label className="check-field">
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) => {
                setForm({ ...form, enabled: event.target.checked });
                setConfirmed(false);
              }}
            />
            <span>دریافت بیعانه با شرایط منتشرشدهٔ مرکز فعال باشد.</span>
          </label>
          <Field
            label="مهلت پرداخت بیعانه (دقیقه)"
            hint="پس از پایان مهلت، ظرفیت نگهداری‌شده طبق نتیجهٔ بررسی پرداخت آزاد می‌شود."
          >
            <input
              type="number"
              required
              min={5}
              max={1440}
              value={form.hold_minutes}
              onChange={(event) => {
                setForm({ ...form, hold_minutes: Number(event.target.value) });
                setConfirmed(false);
              }}
            />
          </Field>
          {(
            [
              ["deposit_terms", "شرایط دریافت بیعانه"],
              ["cancellation_terms", "شرایط لغو نوبت"],
              ["refund_terms", "شرایط بازپرداخت"],
            ] as const
          ).map(([key, label]) => (
            <Field label={label} key={key}>
              <textarea
                rows={4}
                required={form.enabled}
                minLength={form.enabled ? 10 : undefined}
                maxLength={2000}
                value={form[key]}
                onChange={(event) => {
                  setForm({ ...form, [key]: event.target.value });
                  setConfirmed(false);
                }}
              />
            </Field>
          ))}
          {canEdit && (
            <label className="check-field">
              <input
                type="checkbox"
                required
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              <span>
                متن شرایط را با اختیار مرکز بررسی کرده‌ام و انتشار این نسخه را
                تأیید می‌کنم.
              </span>
            </label>
          )}
        </fieldset>
        {policy.published_at && (
          <p className="field-hint">
            نسخهٔ {faNumber(policy.version)} · انتشار در{" "}
            {faDate(policy.published_at, true)}
          </p>
        )}
        {!policy.demonstration && canEdit && (
          <p className="field-hint">
            در محیط عملیاتی، انتشار شرایط در حالت توقف پاسخ‌گویی خودکار انجام
            می‌شود. سپس آمادگی همین پیکربندی دوباره بررسی می‌شود.
          </p>
        )}
        {error && <Alert>{error}</Alert>}
        {canEdit && (
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>
              <Save size={17} />
              انتشار شرایط مالی
            </Busy>
          </button>
        )}
      </section>
      <section className="panel settings-panel">
        <SectionTitle
          title="پذیرندهٔ پرداخت مرکز"
          description="شناسهٔ پذیرنده توسط مسئول اتصال درگاه و به همین مرکز اختصاص داده می‌شود."
        />
        <div className="selected-appointment">
          <FileCheck2 size={22} />
          <strong>
            {policy.merchant_ready
              ? "تنظیمات پذیرنده موجود است"
              : "پذیرندهٔ عملیاتی آماده نیست"}
          </strong>
          {policy.merchant_alias && (
            <span>
              نام پذیرنده: <bdi>{policy.merchant_alias}</bdi>
            </span>
          )}
        </div>
        <p className="field-hint">
          وجود تنظیمات، تأیید تسویه یا آزمون موفق درگاه واقعی نیست. پیش از
          دریافت وجه باید نتیجهٔ آزمون و مجوز پذیرنده بررسی شود.
        </p>
      </section>
    </form>
  );
}

export function PaymentPolicySettings({ canEdit }: { canEdit: boolean }) {
  const result = useRemote<PaymentPolicy>("/operations/payment-policy");
  const [saved, setSaved] = useState(false);
  return (
    <>
      {saved && (
        <Alert kind="success" onClose={() => setSaved(false)}>
          نسخهٔ شرایط مالی مرکز منتشر شد.
        </Alert>
      )}
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading ? (
        <Loading rows={4} />
      ) : (
        result.data && (
          <PolicyForm
            key={result.data.version}
            policy={result.data}
            canEdit={canEdit}
            onSaved={() => {
              setSaved(true);
              result.refresh();
            }}
          />
        )
      )}
    </>
  );
}
