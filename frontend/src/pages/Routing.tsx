import { useState, type FormEvent } from "react";
import { Plus, Save, Trash2 } from "lucide-react";
import { api, errorText, faNumber } from "../api";
import {
  Alert,
  Busy,
  Empty,
  Field,
  Loading,
  Retry,
  SectionTitle,
  Status,
} from "../components";
import { useRemote } from "../hooks";

interface Route {
  did: string;
  provider: "audiosocket" | "livekit";
  queue_id: string;
  transfer_target: string;
}
interface LanguageRoute {
  enabled: boolean;
  script: string;
  queue_id: string;
  qualified_staff_attested: boolean;
  source: string;
  effective_at: string;
  expires_at: string;
}
interface RoutingPolicy {
  version: number;
  routes: Route[];
  language_routes: Record<string, LanguageRoute>;
  allowed_transfer_targets: string[];
}
const dateInput = (value: string) =>
  value
    ? new Intl.DateTimeFormat("sv-SE", {
        timeZone: "Asia/Tehran",
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      })
        .format(new Date(value))
        .replace(" ", "T")
    : "";
const emptyLanguage = (): LanguageRoute => ({
  enabled: false,
  script: "",
  queue_id: "",
  qualified_staff_attested: false,
  source: "",
  effective_at: "",
  expires_at: "",
});

function RoutingForm({
  initial,
  canEdit,
  onSaved,
}: {
  initial: RoutingPolicy;
  canEdit: boolean;
  onSaved: () => void;
}) {
  const [routes, setRoutes] = useState(initial.routes);
  const [languages, setLanguages] = useState<Record<string, LanguageRoute>>(
    Object.fromEntries(
      Object.entries(initial.language_routes).map(([key, row]) => [
        key,
        {
          ...row,
          effective_at: dateInput(row.effective_at),
          expires_at: dateInput(row.expires_at),
        },
      ]),
    ),
  );
  const [reason, setReason] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  function update(index: number, field: keyof Route, value: string) {
    setRoutes((old) =>
      old.map((row, i) => (i === index ? { ...row, [field]: value } : row)),
    );
    setConfirmed(false);
  }
  function languageUpdate(
    key: string,
    field: keyof LanguageRoute,
    value: string | boolean,
  ) {
    setLanguages((old) => ({
      ...old,
      [key]: {
        ...old[key],
        [field]: value,
        ...(field !== "qualified_staff_attested"
          ? { qualified_staff_attested: false }
          : {}),
      },
    }));
    setConfirmed(false);
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/routing", {
        method: "PUT",
        body: JSON.stringify({
          version: initial.version,
          routes,
          language_routes: Object.fromEntries(
            Object.entries(languages).map(([key, row]) => [
              key,
              {
                ...row,
                effective_at: new Date(
                  row.effective_at + ":00+03:30",
                ).toISOString(),
                expires_at: new Date(
                  row.expires_at + ":00+03:30",
                ).toISOString(),
              },
            ]),
          ),
          reason,
        }),
      });
      onSaved();
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <form className="administration-panel-body" onSubmit={submit}>
      <Alert kind="info">
        تغییر مسیر فقط هنگام توقف پذیرش خودکار ثبت می‌شود. مسئول مرکز باید توقف
        و بازگشت به خدمت را هماهنگ کند. ثبت مسیر به‌تنهایی برقراری انتقال در
        اپراتور تلفن را تأیید نمی‌کند.
      </Alert>
      <fieldset disabled={!canEdit || busy} className="plain-fieldset">
        {!initial.allowed_transfer_targets.length && (
          <p className="field-hint">
            هنوز مقصد انتقال مجازی در پیکربندی این سامانه تعریف نشده است. مسئول
            استقرار باید مقصد واقعی و مجاز مرکز را ثبت کند.
          </p>
        )}
        {routes.length ? (
          routes.map((row, index) => (
            <section className="routing-entry" key={index}>
              <div className="administration-subheading">
                <h3>مسیر {faNumber(index + 1)}</h3>
                {canEdit && (
                  <button
                    className="icon-button"
                    type="button"
                    aria-label={`حذف مسیر ${faNumber(index + 1)}`}
                    onClick={() => {
                      setRoutes((old) => old.filter((_, i) => i !== index));
                      setConfirmed(false);
                    }}
                  >
                    <Trash2 size={17} />
                  </button>
                )}
              </div>
              <div className="form-grid">
                <Field label={`شمارهٔ ورودی مسیر ${faNumber(index + 1)}`}>
                  <input
                    required
                    dir="ltr"
                    inputMode="tel"
                    maxLength={21}
                    value={row.did}
                    onChange={(event) =>
                      update(index, "did", event.target.value)
                    }
                  />
                </Field>
                <Field label={`نوع ارتباط مسیر ${faNumber(index + 1)}`}>
                  <select
                    value={row.provider}
                    onChange={(event) =>
                      update(index, "provider", event.target.value)
                    }
                  >
                    <option value="audiosocket">مرکز تلفن</option>
                    <option value="livekit">تماس اینترنتی</option>
                  </select>
                </Field>
                <Field label={`شناسهٔ صف مسیر ${faNumber(index + 1)}`}>
                  <input
                    required
                    maxLength={80}
                    dir="ltr"
                    value={row.queue_id}
                    onChange={(event) =>
                      update(index, "queue_id", event.target.value)
                    }
                  />
                </Field>
                <Field label={`مقصد انتقال مسیر ${faNumber(index + 1)}`}>
                  <select
                    required
                    dir="ltr"
                    value={row.transfer_target}
                    onChange={(event) =>
                      update(index, "transfer_target", event.target.value)
                    }
                  >
                    <option value="">انتخاب مقصد تأییدشده</option>
                    {initial.allowed_transfer_targets.map((target) => (
                      <option key={target}>{target}</option>
                    ))}
                  </select>
                </Field>
              </div>
            </section>
          ))
        ) : (
          <Empty
            title="مسیر تلفنی اختصاصی ثبت نشده"
            description="افزودن شماره و مقصد انتقال، پس از آماده بودن ارتباط واقعی مرکز انجام می‌شود."
          />
        )}
        {canEdit && (
          <button
            className="button secondary small"
            type="button"
            disabled={
              routes.length >= 40 || !initial.allowed_transfer_targets.length
            }
            onClick={() => {
              setRoutes((old) => [
                ...old,
                {
                  did: "",
                  provider: "audiosocket",
                  queue_id: "",
                  transfer_target: "",
                },
              ]);
              setConfirmed(false);
            }}
          >
            <Plus size={16} />
            افزودن مسیر تلفن
          </button>
        )}
        <div className="form-divider" />
        <h3>ارجاع زبانی به همکار انسانی</h3>
        <p className="field-hint">
          برای زبان‌های دیگر، متن مصوب و صفِ دارای همکار واجد صلاحیت را مشخص
          کنید. این تنظیم، گفت‌وگوی هوشمند چندزبانه را فعال نمی‌کند.
        </p>
        {[
          ["english", "انگلیسی"],
          ["arabic", "عربی"],
        ].map(([key, label]) => (
          <details className="language-route" key={key}>
            <summary>
              {label}{" "}
              <Status value={languages[key]?.enabled ? "ACTIVE" : "DISABLED"} />
            </summary>
            {!languages[key] ? (
              <button
                className="button secondary small"
                type="button"
                onClick={() => {
                  setLanguages((old) => ({ ...old, [key]: emptyLanguage() }));
                  setConfirmed(false);
                }}
              >
                تعریف مسیر {label}
              </button>
            ) : (
              <div>
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={languages[key].enabled}
                    onChange={(event) =>
                      languageUpdate(key, "enabled", event.target.checked)
                    }
                  />
                  <span>ارجاع انسانی {label} فعال باشد.</span>
                </label>
                <Field label={`متن مصوب ${label}`}>
                  <textarea
                    required
                    rows={3}
                    minLength={10}
                    maxLength={1000}
                    value={languages[key].script}
                    onChange={(event) =>
                      languageUpdate(key, "script", event.target.value)
                    }
                  />
                </Field>
                <Field label={`صف همکار ${label}`}>
                  <select
                    required
                    value={languages[key].queue_id}
                    onChange={(event) =>
                      languageUpdate(key, "queue_id", event.target.value)
                    }
                  >
                    <option value="">انتخاب صف همین مرکز</option>
                    {[
                      ...new Set(
                        routes.map((route) => route.queue_id).filter(Boolean),
                      ),
                    ].map((queue) => (
                      <option key={queue}>{queue}</option>
                    ))}
                  </select>
                </Field>
                <Field label={`مرجع تأیید مسیر ${label}`}>
                  <input
                    required
                    minLength={3}
                    maxLength={500}
                    value={languages[key].source}
                    onChange={(event) =>
                      languageUpdate(key, "source", event.target.value)
                    }
                  />
                </Field>
                <div className="form-grid">
                  <Field label={`شروع اعتبار ${label} به وقت تهران`}>
                    <input
                      required
                      type="datetime-local"
                      value={languages[key].effective_at}
                      onChange={(event) =>
                        languageUpdate(key, "effective_at", event.target.value)
                      }
                    />
                  </Field>
                  <Field label={`پایان اعتبار ${label} به وقت تهران`}>
                    <input
                      required
                      type="datetime-local"
                      value={languages[key].expires_at}
                      onChange={(event) =>
                        languageUpdate(key, "expires_at", event.target.value)
                      }
                    />
                  </Field>
                </div>
                <label className="check-field">
                  <input
                    required={languages[key].enabled}
                    type="checkbox"
                    checked={languages[key].qualified_staff_attested}
                    onChange={(event) =>
                      languageUpdate(
                        key,
                        "qualified_staff_attested",
                        event.target.checked,
                      )
                    }
                  />
                  <span>
                    وجود همکار واجد صلاحیت برای پاسخ‌گویی {label} در صف
                    انتخاب‌شده را تأیید می‌کنم.
                  </span>
                </label>
                <button
                  type="button"
                  className="button quiet small"
                  onClick={() => {
                    setLanguages((old) =>
                      Object.fromEntries(
                        Object.entries(old).filter(([name]) => name !== key),
                      ),
                    );
                    setConfirmed(false);
                  }}
                >
                  حذف تعریف این زبان
                </button>
              </div>
            )}
          </details>
        ))}
        {canEdit && (
          <>
            <Field label="دلیل انتشار مسیرها">
              <textarea
                required
                minLength={3}
                maxLength={500}
                rows={2}
                value={reason}
                onChange={(event) => {
                  setReason(event.target.value);
                  setConfirmed(false);
                }}
              />
            </Field>
            <label className="check-field">
              <input
                required
                type="checkbox"
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              />
              <span>
                شماره‌ها، صف‌ها، مقصدهای انتقال و شرایط زبان‌ها را بررسی
                کرده‌ام.
              </span>
            </label>
          </>
        )}
      </fieldset>
      {error && <Alert>{error}</Alert>}
      {canEdit && (
        <button className="button primary" disabled={busy || !confirmed}>
          <Busy busy={busy}>
            <Save size={17} />
            انتشار مسیرها
          </Busy>
        </button>
      )}
    </form>
  );
}

export function RoutingSettings({ canEdit }: { canEdit: boolean }) {
  const result = useRemote<RoutingPolicy>("/routing"),
    [message, setMessage] = useState("");
  return (
    <section className="panel">
      <SectionTitle
        title="مسیر تلفن و انتقال انسانی"
        description="شماره‌های ورودی و مقصدهای مجاز برای همین مرکز"
      />
      {message && <Alert kind="success">{message}</Alert>}
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading || !result.data ? (
        <Loading rows={3} />
      ) : (
        <RoutingForm
          key={result.data.version}
          initial={result.data}
          canEdit={canEdit}
          onSaved={() => {
            result.refresh();
            setMessage(
              "نسخهٔ مسیرها ثبت شد. آزمون انتقال واقعی باید جداگانه تأیید شود.",
            );
          }}
        />
      )}
    </section>
  );
}
