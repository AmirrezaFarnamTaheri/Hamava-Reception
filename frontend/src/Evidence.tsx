import { useRef, useState } from "react";
import { CheckCircle2, FileCheck2 } from "lucide-react";
import { Alert, Field } from "./components";

export async function documentHash(file: File): Promise<string> {
  if (file.size > 10 * 1024 * 1024)
    throw new Error("مدرک باید حداکثر ۱۰ مگابایت باشد.");
  return Array.from(
    new Uint8Array(
      await crypto.subtle.digest("SHA-256", await file.arrayBuffer()),
    ),
    (byte) => byte.toString(16).padStart(2, "0"),
  ).join("");
}

export function EvidenceFields({
  reference,
  hash,
  onReference,
  onHash,
  label = "مدرک بررسی‌شده",
}: {
  reference: string;
  hash: string;
  onReference: (value: string) => void;
  onHash: (value: string) => void;
  label?: string;
}) {
  const [filename, setFilename] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  return (
    <section className="evidence-fields">
      <h3>
        <FileCheck2 size={18} />
        {label}
      </h3>
      <Field
        label="شناسهٔ مدرک"
        hint="شناسهٔ داخلی قابل پیگیری؛ فقط حروف لاتین، عدد و نشانه‌های . : / @ - _"
      >
        <input
          required
          maxLength={160}
          dir="ltr"
          value={reference}
          onChange={(event) => onReference(event.target.value)}
        />
      </Field>
      <Field
        label="انتخاب فایل مدرک"
        hint="فقط اثرانگشت فایل محاسبه و ثبت می‌شود؛ خود فایل از این فرم ارسال نمی‌شود."
      >
        <input
          type="file"
          aria-busy={busy}
          onChange={async (event) => {
            const file = event.target.files?.[0];
            const current = ++generation.current;
            onHash("");
            setFilename("");
            setError("");
            if (!file) return;
            setBusy(true);
            try {
              const result = await documentHash(file);
              if (current === generation.current) {
                onHash(result);
                setFilename(file.name);
              }
            } catch (error) {
              if (current === generation.current)
                setError(
                  error instanceof Error
                    ? error.message
                    : "خواندن فایل ممکن نشد.",
                );
            } finally {
              if (current === generation.current) setBusy(false);
            }
          }}
        />
      </Field>
      {busy && (
        <p role="status" className="field-hint">
          در حال بررسی فایل روی همین دستگاه…
        </p>
      )}
      {filename && hash && (
        <p className="evidence-ready" role="status">
          <CheckCircle2 size={16} />
          <span>{filename} · اثرانگشت آماده است</span>
        </p>
      )}
      {error && <Alert>{error}</Alert>}
      <details className="evidence-manual">
        <summary>وارد کردن اثرانگشت موجود</summary>
        <Field label="اثر انگشت SHA-256">
          <input
            pattern="[a-f0-9]{64}"
            maxLength={64}
            value={hash}
            dir="ltr"
            onChange={(event) => {
              generation.current++;
              onHash(event.target.value.toLowerCase());
              setFilename("");
              setBusy(false);
            }}
          />
        </Field>
      </details>
    </section>
  );
}

export function exactToman(
  value: string | undefined,
  micro?: number,
  scale = 1_000_000,
): string {
  if (
    value === undefined &&
    (micro === undefined || !Number.isSafeInteger(micro))
  )
    return "—";
  const decimal = value ?? String(micro! / scale);
  if (!/^-?\d+(\.\d+)?$/.test(decimal)) return "—";
  const [whole, fraction] = decimal.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, "٬");
  const trimmed = fraction?.replace(/0+$/, "");
  return `${grouped}${trimmed ? `٫${trimmed}` : ""}`.replace(
    /\d/g,
    (digit) => "۰۱۲۳۴۵۶۷۸۹"[Number(digit)],
  );
}
