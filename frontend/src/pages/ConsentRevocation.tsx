import { useState, type FormEvent } from "react";
import { post, errorText, faNumber } from "../api";
import { Alert, Busy, Dialog, Field } from "../components";

const choices = [
  ["reminder", "یادآوری نوبت"],
  ["waitlist", "پیشنهاد زمان آزاد"],
  ["followup", "پیگیری‌های اختیاری"],
];
interface RevocationResult {
  status: string;
  purposes: string[];
  phone_masked: string;
  revoked_grants: number;
  suppressed_messages: number;
  canceled_waitlist_entries: number;
  released_holds: number;
  dispatches_inflight?: number;
}
export function ConsentRevocation({
  onClose,
  onSaved,
}: {
  onClose: () => void;
  onSaved: () => void;
}) {
  const [phone, setPhone] = useState("");
  const [purposes, setPurposes] = useState(choices.map(([id]) => id));
  const [confirmed, setConfirmed] = useState(false);
  const [result, setResult] = useState<RevocationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!confirmed || !purposes.length) return;
    setBusy(true);
    setError("");
    try {
      setResult(
        await post<RevocationResult>("/operations/consents/revoke", {
          phone: phone.trim(),
          purposes,
        }),
      );
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="انصراف از پیام‌های اختیاری"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        {result ? (
          <>
            <Alert kind="success">
              انصراف برای شمارهٔ <bdi>{result.phone_masked}</bdi> ثبت شد.
            </Alert>
            <div className="selected-appointment">
              <strong>
                {result.purposes
                  .map((id) => choices.find(([key]) => key === id)?.[1])
                  .filter(Boolean)
                  .join("، ")}
              </strong>
              <span>
                {faNumber(result.suppressed_messages)} پیام در صف متوقف شد.
              </span>
              <span>
                {faNumber(result.canceled_waitlist_entries)} درخواست فهرست
                انتظار بسته شد.
              </span>
              <span>
                {faNumber(result.released_holds)} زمان نگه‌داشته‌شده آزاد شد.
              </span>
            </div>
            {!!result.dispatches_inflight && (
              <Alert kind="info">
                {faNumber(result.dispatches_inflight)} پیام قبلاً برای ارسال
                تحویل شده است و ممکن است قابل توقف نباشد.
              </Alert>
            )}
            <p className="field-hint">
              نوبت‌های ثبت‌شده و پیام‌های ضروری تأیید یا لغو نوبت تحت تأثیر این
              انتخاب نیستند.
            </p>
            <button
              type="button"
              className="button secondary"
              onClick={onClose}
            >
              بستن
            </button>
          </>
        ) : (
          <>
            <p className="muted">
              انتخاب مراجعه‌کننده را ثبت کنید. نوبت‌های او حفظ می‌شوند و
              پیام‌های اختیاری انتخاب‌شده دیگر ارسال نخواهند شد.
            </p>
            <Field label="شمارهٔ همراه مراجعه‌کننده">
              <input
                required
                type="tel"
                inputMode="tel"
                dir="ltr"
                maxLength={30}
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                autoComplete="off"
              />
            </Field>
            <fieldset className="provider-checklist">
              <legend>انصراف از دریافت</legend>
              {choices.map(([id, label]) => (
                <label className="check-field" key={id}>
                  <input
                    type="checkbox"
                    checked={purposes.includes(id)}
                    onChange={(e) =>
                      setPurposes((old) =>
                        e.target.checked
                          ? [...old, id]
                          : old.filter((item) => item !== id),
                      )
                    }
                  />
                  <span>{label}</span>
                </label>
              ))}
            </fieldset>
            <label className="check-field">
              <input
                required
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
              />
              <span>
                هویت و درخواست مراجعه‌کننده را بررسی کرده‌ام و انتخاب او را ثبت
                می‌کنم.
              </span>
            </label>
            <div className="modal-actions">
              <button
                className="button primary"
                disabled={busy || !confirmed || !purposes.length}
              >
                <Busy busy={busy}>ثبت انصراف</Busy>
              </button>
              <button
                type="button"
                className="button secondary"
                disabled={busy}
                onClick={onClose}
              >
                بازگشت
              </button>
            </div>
          </>
        )}
        {error && <Alert>{error}</Alert>}
      </form>
    </Dialog>
  );
}
