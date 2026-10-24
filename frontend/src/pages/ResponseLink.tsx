import { useState } from "react";
import { Copy, Link2 } from "lucide-react";
import { errorText, faDate, post } from "../api";
import { Alert, Busy, Dialog, Field } from "../components";
import type { Appointment } from "../types";
import { publicUrl } from "../platform";
interface ResponseLinkData {
  response_id: string;
  public_path: string;
  expires_at: string;
}
export function ResponseLinkDialog({
  appointment,
  onClose,
}: {
  appointment: Appointment;
  onClose: () => void;
}) {
  const [result, setResult] = useState<ResponseLinkData | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  async function create() {
    setBusy(true);
    setError("");
    try {
      setResult(
        await post<ResponseLinkData>(
          `/operations/appointments/${appointment.id}/response-link`,
          { version: appointment.version },
        ),
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function copy() {
    if (!result) return;
    try {
      await navigator.clipboard.writeText(publicUrl(result.public_path));
      setCopied(true);
    } catch {
      setError("کپی خودکار ممکن نشد. متن پیوند را انتخاب و کپی کنید.");
    }
  }
  return (
    <Dialog
      title="پیوند پاسخ به نوبت"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="modal-body">
        <div className="selected-appointment">
          <strong>{appointment.patient_name}</strong>
          <span>{appointment.jalali_display}</span>
          <span>کد نوبت: {appointment.reference}</span>
        </div>
        <p>
          مراجعه‌کننده با این پیوند، قصد مراجعه یا عدم امکان حضور را ثبت می‌کند.
          این کار به‌تنهایی پیام ارسال نمی‌کند.
        </p>
        {result ? (
          <>
            <Field
              label="پیوند خصوصی پاسخ"
              hint="فقط از مسیر مجاز در اختیار همین مراجعه‌کننده قرار دهید."
            >
              <textarea
                rows={3}
                readOnly
                dir="ltr"
                value={publicUrl(result.public_path)}
                onFocus={(event) => event.target.select()}
              />
            </Field>
            <p className="field-hint">
              پایان اعتبار: {faDate(result.expires_at, true)}
            </p>
            <button className="button secondary" onClick={() => void copy()}>
              <Copy size={16} />
              {copied ? "کپی شد" : "کپی پیوند"}
            </button>
          </>
        ) : (
          <button
            className="button primary"
            disabled={busy}
            onClick={() => void create()}
          >
            <Busy busy={busy}>
              <Link2 size={16} />
              ساخت پیوند پاسخ
            </Busy>
          </button>
        )}
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button secondary"
            disabled={busy}
            onClick={onClose}
          >
            بستن
          </button>
        </div>
      </div>
    </Dialog>
  );
}
