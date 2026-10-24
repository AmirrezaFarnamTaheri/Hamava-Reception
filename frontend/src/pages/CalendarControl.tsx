import { useState, type FormEvent } from "react";
import { CalendarClock, RefreshCw, Save } from "lucide-react";
import { api, errorText, faDate, faNumber, post } from "../api";
import {
  Alert,
  Busy,
  Dialog,
  Empty,
  Field,
  Loading,
  Retry,
  SectionTitle,
  Status,
} from "../components";
import { useRemote } from "../hooks";
import type { Appointment } from "../types";

export interface CalendarOperation {
  operation_id: string;
  operation: string;
  operation_status: string;
  status: string;
  result: {
    reference?: string;
    status?: string;
    start_at?: string;
    id?: string;
  } | null;
  error_code: string | null;
  verified_at: string | null;
  requires_reconciliation: boolean;
  booking?: Appointment | null;
}
const names: Record<string, string> = {
  create: "ثبت نوبت",
  cancel: "لغو نوبت",
  update: "جابه‌جایی نوبت",
  slots: "بررسی زمان‌ها",
  hold: "نگه‌داشتن زمان",
  release: "آزادکردن زمان",
  get: "خواندن نوبت",
};
const statuses: Record<string, string> = {
  PENDING: "در انتظار پاسخ تقویم",
  SENDING: "در حال بررسی در تقویم",
  UNKNOWN: "نتیجه نامشخص؛ نیازمند تطبیق",
  REVIEW_REQUIRED: "نیازمند بررسی پذیرش",
  READBACK_REQUIRED: "زمان یا نسخه تغییر کرده؛ تأیید تازه لازم است",
  FAILED_REVIEW: "نتیجه نیازمند بررسی پذیرش",
  SUCCEEDED: "نتیجه در تقویم تأیید شد",
  FAILED: "ناموفق؛ نیازمند بررسی",
};

function OperationCard({
  item,
  canWrite,
  onChanged,
}: {
  item: CalendarOperation;
  canWrite: boolean;
  onChanged: (result: CalendarOperation) => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function reconcile() {
    setBusy(true);
    setError("");
    try {
      onChanged(
        await post<CalendarOperation>(
          `/calendar/operations/${encodeURIComponent(item.operation_id)}/reconcile`,
          {},
        ),
      );
    } catch (error) {
      setError(errorText(error));
    } finally {
      setBusy(false);
    }
  }
  return (
    <article className="calendar-operation">
      <div className="card-heading">
        <h3>{names[item.operation] || "عملیات تقویم"}</h3>
        <Status
          value={
            item.operation_status === "SUCCEEDED"
              ? "COMPLETED"
              : item.operation_status === "FAILED"
                ? "FAILED"
                : "PENDING"
          }
          label={statuses[item.operation_status] || "نیازمند بررسی"}
        />
      </div>
      {item.operation_status === "SUCCEEDED" ? (
        <>
          <p>
            {(item.booking?.reference || item.result?.reference) && (
              <bdi>{item.booking?.reference || item.result?.reference} · </bdi>
            )}
            <Status
              value={item.booking?.status || item.result?.status || item.status}
            />
          </p>
          {item.result?.start_at && (
            <p className="field-hint">{faDate(item.result.start_at, true)}</p>
          )}
          {item.verified_at && (
            <p className="field-hint">
              تأیید نتیجه در {faDate(item.verified_at, true)}
            </p>
          )}
        </>
      ) : (
        <p className="field-hint">
          {item.operation_status === "READBACK_REQUIRED"
            ? "جزئیات نوبت تغییر کرده است. ابتدا اطلاعات فعلی را بخوانید و پیش از درخواست جدید، زمان و اطلاعات را دوباره با مراجعه‌کننده تأیید کنید."
            : "این درخواست هنوز نتیجهٔ قطعی ندارد. نوبت یا تغییر آن را به مراجعه‌کننده قطعی اعلام نکنید و درخواست جدید تکراری نفرستید."}
        </p>
      )}
      {item.error_code && (
        <details className="compact-details">
          <summary>شناسهٔ بررسی فنی</summary>
          <bdi>{item.error_code}</bdi>
        </details>
      )}
      <small className="operation-reference">
        شناسهٔ پیگیری: <bdi>{item.operation_id}</bdi>
      </small>
      {error && <Alert>{error}</Alert>}
      {canWrite &&
        ![
          "SUCCEEDED",
          "FAILED",
          "FAILED_REVIEW",
          "READBACK_REQUIRED",
          "REVIEW_REQUIRED",
        ].includes(item.operation_status) && (
          <button
            className="button secondary small"
            disabled={busy}
            onClick={() => void reconcile()}
          >
            <Busy busy={busy}>
              <RefreshCw size={16} />
              بررسی نتیجه در تقویم
            </Busy>
          </button>
        )}
    </article>
  );
}

export function PendingCalendarDialog({
  initial,
  onClose,
}: {
  initial: CalendarOperation;
  onClose: () => void;
}) {
  const [item, setItem] = useState(initial);
  return (
    <Dialog title="پیگیری نتیجهٔ تقویم" onClose={onClose}>
      <div className="modal-body">
        <OperationCard item={item} canWrite onChanged={setItem} />
        <p className="field-hint">
          این درخواست در فهرست «پیگیری تقویم» نگهداری می‌شود؛ بستن این پنجره آن
          را لغو نمی‌کند.
        </p>
        <div className="modal-actions">
          <button type="button" className="button secondary" onClick={onClose}>
            بستن و ادامهٔ کار
          </button>
          <button
            type="button"
            className="button quiet"
            onClick={() => {
              history.pushState({}, "", "/capacity?tab=calendar");
              window.dispatchEvent(new PopStateEvent("popstate"));
            }}
          >
            همهٔ عملیات تقویم
          </button>
        </div>
      </div>
    </Dialog>
  );
}

export function CalendarOperations({ canWrite }: { canWrite: boolean }) {
  const result = useRemote<CalendarOperation[]>("/calendar/operations", 20000);
  const actionable =
    result.data?.filter((row) =>
      ["create", "update", "cancel"].includes(row.operation),
    ) || [];
  return (
    <section className="panel">
      <SectionTitle
        title="پیگیری تقویم همکار"
        description="نتیجهٔ ثبت، لغو و جابه‌جایی فقط پس از بازخوانی معتبر تقویم قطعی گزارش می‌شود."
        action={
          <button
            className="icon-button"
            aria-label="تازه‌سازی عملیات تقویم"
            onClick={result.refresh}
          >
            <RefreshCw size={19} />
          </button>
        }
      />
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading ? (
        <Loading rows={3} />
      ) : !actionable.length ? (
        <Empty
          title="عملیات بیرونی برای نمایش نیست"
          description="درخواست‌های تقویم همکار، در صورت استفادهٔ مرکز از آن، همراه با وضعیت واقعی در این فهرست دیده می‌شوند."
        />
      ) : (
        <div className="administration-list">
          {actionable.map((row) => (
            <OperationCard
              item={row}
              key={`${row.operation_id}:${row.operation_status}`}
              canWrite={canWrite}
              onChanged={result.refresh}
            />
          ))}
        </div>
      )}
    </section>
  );
}

interface Authority {
  kind: "internal" | "external";
  provider_key: string;
  version: number;
  capabilities: Record<string, unknown>;
  expires_at: string | null;
  connector_revision: string;
  verification: string;
}
function AuthorityEditor({
  initial,
  onClose,
  onSaved,
}: {
  initial: Authority;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [kind, setKind] = useState(initial.kind),
    [expires, setExpires] = useState(""),
    [reason, setReason] = useState(""),
    [confirmed, setConfirmed] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/calendar/authority", {
        method: "PUT",
        body: JSON.stringify({
          version: initial.version,
          kind,
          expires_at: new Date(expires + ":00+03:30").toISOString(),
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
    <Dialog
      title="انتخاب مرجع قطعی نوبت‌ها"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <Alert kind="info">
          پذیرش خودکار باید هنگام تغییر مرجع متوقف باشد. سامانه وجود نوبت‌ها و
          عملیات باز و قابلیت تقویم بیرونی را دوباره بررسی می‌کند.
        </Alert>
        <Field label="مرجع نوبت">
          <select
            value={kind}
            onChange={(event) => {
              setKind(event.target.value as "internal" | "external");
              setConfirmed(false);
            }}
          >
            <option value="internal">تقویم داخلی هم‌آوا</option>
            <option value="external">تقویم تأییدشدهٔ همکار</option>
          </select>
        </Field>
        <Field label="پایان اعتبار انتخاب به وقت تهران">
          <input
            required
            type="datetime-local"
            value={expires}
            onChange={(event) => {
              setExpires(event.target.value);
              setConfirmed(false);
            }}
          />
        </Field>
        <Field label="دلیل تغییر یا تمدید">
          <textarea
            required
            minLength={3}
            maxLength={500}
            rows={3}
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
          <span>مرجع قطعی و اثر آن بر ثبت نوبت‌ها را بررسی کرده‌ام.</span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !confirmed}>
            <Busy busy={busy}>
              <Save size={17} />
              ثبت مرجع
            </Busy>
          </button>
          <button
            className="button secondary"
            type="button"
            disabled={busy}
            onClick={onClose}
          >
            بازگشت
          </button>
        </div>
      </form>
    </Dialog>
  );
}
export function CalendarAuthority({ canWrite }: { canWrite: boolean }) {
  const result = useRemote<Authority>("/calendar/authority"),
    sync = useRemote<{
      status: string;
      revision: number;
      last_poll_at: string | null;
    }>("/calendar/sync");
  const [editing, setEditing] = useState(false),
    [message, setMessage] = useState("");
  return (
    <section className="panel">
      <SectionTitle
        title="مرجع قطعی تقویم"
        description="برای جلوگیری از دو رزرو مستقل، هر مرکز یک مرجع معتبر نوبت دارد."
        action={
          canWrite &&
          result.data && (
            <button
              className="button secondary small"
              onClick={() => setEditing(true)}
            >
              <CalendarClock size={17} />
              بازبینی مرجع
            </button>
          )
        }
      />
      {message && <Alert kind="success">{message}</Alert>}
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading || !result.data ? (
        <Loading rows={2} />
      ) : (
        <div className="administration-panel-body">
          <h3>
            {result.data.kind === "external"
              ? "تقویم همکار"
              : "تقویم داخلی هم‌آوا"}
          </h3>
          <dl className="compact-facts">
            <div>
              <dt>نسخهٔ تصمیم</dt>
              <dd>{faNumber(result.data.version)}</dd>
            </div>
            <div>
              <dt>اعتبار</dt>
              <dd>
                {result.data.expires_at
                  ? faDate(result.data.expires_at)
                  : "انتخاب پیش‌فرض محیط توسعه"}
              </dd>
            </div>
            <div>
              <dt>ثبت مسئول</dt>
              <dd>
                {result.data.verification === "operator_approved"
                  ? "ثبت شده"
                  : "هنوز ثبت نشده"}
              </dd>
            </div>
          </dl>
          {result.data.kind === "external" &&
            (sync.error ? (
              <Retry error={sync.error} onRetry={sync.refresh} />
            ) : (
              <p className="field-hint">
                آخرین بررسی تغییرات:{" "}
                {sync.data?.last_poll_at
                  ? faDate(sync.data.last_poll_at, true)
                  : "هنوز ثبت نشده"}{" "}
                · نسخهٔ تغییرات:{" "}
                {sync.data ? faNumber(sync.data.revision) : "—"}
              </p>
            ))}
        </div>
      )}
      {editing && result.data && (
        <AuthorityEditor
          initial={result.data}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            result.refresh();
            sync.refresh();
            setMessage("مرجع تقویم پس از بررسی سامانه ثبت شد.");
          }}
        />
      )}
    </section>
  );
}

export function RemoteReadbackDialog({
  appointmentId,
  canWrite,
  onClose,
  onManage,
}: {
  appointmentId: string;
  canWrite: boolean;
  onClose: () => void;
  onManage: (appointment: Appointment, action: "cancel" | "reschedule") => void;
}) {
  const result = useRemote<Appointment | CalendarOperation>(
    `/appointments/${encodeURIComponent(appointmentId)}`,
  );
  return (
    <Dialog title="بررسی نوبت در تقویم مرجع" onClose={onClose}>
      <div className="modal-body">
        {result.error ? (
          <Retry error={result.error} onRetry={result.refresh} />
        ) : result.loading || !result.data ? (
          <Loading rows={3} />
        ) : "operation_status" in result.data ? (
          <OperationCard
            item={result.data}
            canWrite={canWrite}
            onChanged={result.refresh}
          />
        ) : (
          <>
            <div className="selected-appointment">
              <strong>
                {result.data.patient_name || result.data.reference}
              </strong>
              <span>
                {result.data.provider_name} · {result.data.service_name}
              </span>
              <span>
                {result.data.jalali_display ||
                  faDate(result.data.start_at, true)}
              </span>
              <Status value={result.data.status} />
            </div>
            <p className="field-hint">
              وضعیت بالا از پاسخ تازهٔ مرجع تقویم خوانده شده است. هر تغییر با
              نسخهٔ همین پاسخ دوباره بررسی می‌شود.
            </p>
            {canWrite &&
              [
                "CONFIRMED",
                "PENDING_PAYMENT",
                "PENDING_STAFF_APPROVAL",
              ].includes(result.data.status) && (
                <div className="modal-actions">
                  <button
                    className="button secondary"
                    onClick={() =>
                      onManage(result.data as Appointment, "reschedule")
                    }
                  >
                    جابجایی نوبت
                  </button>
                  <button
                    className="button danger-quiet"
                    onClick={() =>
                      onManage(result.data as Appointment, "cancel")
                    }
                  >
                    لغو نوبت
                  </button>
                </div>
              )}
          </>
        )}
        <div className="modal-actions">
          <button className="button secondary" onClick={onClose}>
            بستن
          </button>
          <button
            className="button quiet"
            disabled={result.loading}
            onClick={result.refresh}
          >
            <RefreshCw size={16} />
            بازخوانی تازه
          </button>
        </div>
      </div>
    </Dialog>
  );
}
