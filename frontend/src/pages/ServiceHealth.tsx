import { LatencyReport } from "./Latency";
import { useState, type FormEvent } from "react";
import {
  BellRing,
  Check,
  ChevronDown,
  ChevronUp,
  HeartPulse,
  Plus,
  Save,
  UserCheck,
  X,
} from "lucide-react";
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
import { hasPermission, roleNames } from "../permissions";
import type { User } from "../types";

interface OnCallPolicy {
  version: number;
  enabled: boolean;
  user_ids: string[];
  escalation_minutes: number;
  spike_window_minutes: number;
  spike_cap_toman: number;
  provider_failure_threshold: number;
}
interface Member {
  user_id: string;
  name: string;
  role: string;
}
interface OperationalAlert {
  id: string;
  kind: string;
  severity: string;
  status: string;
  evidence: Record<string, unknown>;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  created_at: string;
  resolved_at: string | null;
  deliveries: {
    level: number;
    user_id: string;
    task_id: string;
    status: string;
  }[];
}
const kindNames: Record<string, string> = {
  cost_spike: "افزایش سریع هزینه",
  provider_failure: "خطای سرویس",
  budget_soft_limit: "نزدیک‌شدن به سقف بودجه",
  budget_exceeded: "عبور از بودجه",
  unpriced_cost: "مصرف بدون تعرفه",
  unknown_reservation: "هزینهٔ نیازمند تطبیق",
  privacy_failure: "رویداد حریم خصوصی",
};
const alertLabels: Record<string, string> = {
  OPEN: "منتظر مسئول",
  ACKNOWLEDGED: "رسیدگی پذیرفته شده",
  RESOLVED: "رسیدگی بسته شده",
};

function OnCallEditor({
  initial,
  members,
  onClose,
  onSaved,
}: {
  initial: OnCallPolicy | null;
  members: Member[];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [enabled, setEnabled] = useState(initial?.enabled ?? false),
    [users, setUsers] = useState(initial?.user_ids || []);
  const [minutes, setMinutes] = useState(
      String(initial?.escalation_minutes ?? 10),
    ),
    [windowMinutes, setWindowMinutes] = useState(
      String(initial?.spike_window_minutes ?? 10),
    ),
    [cap, setCap] = useState(String(initial?.spike_cap_toman ?? 100000)),
    [failures, setFailures] = useState(
      String(initial?.provider_failure_threshold ?? 5),
    );
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  function move(index: number, direction: number) {
    setUsers((old) => {
      const next = [...old];
      [next[index], next[index + direction]] = [
        next[index + direction],
        next[index],
      ];
      return next;
    });
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/operations/oncall", {
        method: "PUT",
        body: JSON.stringify({
          enabled,
          user_ids: users,
          escalation_minutes: Number(minutes),
          spike_window_minutes: Number(windowMinutes),
          spike_cap_toman: Number(cap),
          provider_failure_threshold: Number(failures),
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
      title="مسئول پاسخ به هشدارها"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <p className="field-hint">
          هشدار به‌صورت کار داخل همین برنامه به مسئول‌ها ارجاع می‌شود. پیامک،
          تماس یا اعلان خارج از برنامه در این تنظیم فعال نمی‌شود.
        </p>
        <label className="check-field">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => setEnabled(event.target.checked)}
          />
          <span>ارجاع هشدار به مسئول‌های زیر فعال باشد.</span>
        </label>
        <h3>ترتیب رسیدگی</h3>
        {users.map((id, index) => (
          <div className="oncall-person" key={id}>
            <span className="step-number">{faNumber(index + 1)}</span>
            <div>
              <strong>
                {members.find((member) => member.user_id === id)?.name ||
                  "عضو غیرفعال؛ انتخاب را اصلاح کنید"}
              </strong>
              <small>
                {roleNames[
                  members.find((member) => member.user_id === id)?.role || ""
                ] || "عضو مرکز"}
              </small>
            </div>
            <button
              className="icon-button"
              type="button"
              disabled={index === 0}
              aria-label={`اولویت بالاتر برای مسئول ${faNumber(index + 1)}`}
              onClick={() => move(index, -1)}
            >
              <ChevronUp size={18} />
            </button>
            <button
              className="icon-button"
              type="button"
              disabled={index === users.length - 1}
              aria-label={`اولویت پایین‌تر برای مسئول ${faNumber(index + 1)}`}
              onClick={() => move(index, 1)}
            >
              <ChevronDown size={18} />
            </button>
            <button
              type="button"
              className="icon-button"
              aria-label={`حذف مسئول ${faNumber(index + 1)}`}
              onClick={() =>
                setUsers((old) => old.filter((value) => value !== id))
              }
            >
              <X size={17} />
            </button>
          </div>
        ))}
        {users.length < 5 && (
          <Field label="افزودن مسئول">
            <select
              value=""
              onChange={(event) => {
                if (event.target.value)
                  setUsers((old) => [...old, event.target.value]);
              }}
            >
              <option value="">انتخاب عضو مرکز</option>
              {members
                .filter((member) => !users.includes(member.user_id))
                .map((member) => (
                  <option key={member.user_id} value={member.user_id}>
                    {member.name} · {roleNames[member.role] || member.role}
                  </option>
                ))}
            </select>
          </Field>
        )}
        <div className="form-grid">
          <Field label="ارجاع به نفر بعد پس از (دقیقه)">
            <input
              required
              type="number"
              min={1}
              max={120}
              value={minutes}
              onChange={(event) => setMinutes(event.target.value)}
            />
          </Field>
          <Field label="بازهٔ بررسی افزایش هزینه (دقیقه)">
            <input
              required
              type="number"
              min={1}
              max={60}
              value={windowMinutes}
              onChange={(event) => setWindowMinutes(event.target.value)}
            />
          </Field>
          <Field label="سقف هزینه در این بازه (تومان)">
            <input
              required
              type="number"
              min={1}
              max={1_000_000_000}
              value={cap}
              onChange={(event) => setCap(event.target.value)}
            />
          </Field>
          <Field label="تعداد خطای سرویس برای هشدار">
            <input
              required
              type="number"
              min={1}
              max={1000}
              value={failures}
              onChange={(event) => setFailures(event.target.value)}
            />
          </Field>
        </div>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy || !users.length}>
            <Busy busy={busy}>
              <Save size={17} />
              ذخیرهٔ مسئولیت‌ها
            </Busy>
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
      </form>
    </Dialog>
  );
}

function AlertAction({
  alert,
  action,
  onClose,
  onSaved,
}: {
  alert: OperationalAlert;
  action: "ACKNOWLEDGE" | "RESOLVE";
  onClose: () => void;
  onSaved: () => void;
}) {
  const [reference, setReference] = useState(""),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post(`/operations/alerts/${alert.id}/actions`, {
        action,
        evidence_reference: reference,
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
      title={
        action === "ACKNOWLEDGE"
          ? "پذیرش مسئولیت هشدار"
          : "بستن رسیدگی به هشدار"
      }
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <p>
          {kindNames[alert.kind.toLowerCase()] || "هشدار عملیاتی"} ·{" "}
          {faDate(alert.created_at, true)}
        </p>
        <p className="field-hint">
          {action === "ACKNOWLEDGE"
            ? "این اقدام، رسید خواندن و پذیرش مسئولیت شما را ثبت می‌کند."
            : "پس از بررسی علت و نتیجه، مرجع اقدام اصلاحی را ثبت کنید. بستن هشدار به‌تنهایی سلامت سرویس را تأیید نمی‌کند."}
        </p>
        <Field
          label={
            action === "ACKNOWLEDGE"
              ? "شناسهٔ پیگیری"
              : "شناسهٔ مدرک اقدام اصلاحی"
          }
          hint="یک مرجع داخلی قابل پیگیری با حروف لاتین و عدد."
        >
          <input
            required
            dir="ltr"
            maxLength={160}
            value={reference}
            onChange={(event) => setReference(event.target.value)}
          />
        </Field>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button className="button primary" disabled={busy}>
            <Busy busy={busy}>
              {action === "ACKNOWLEDGE"
                ? "مسئولیت را می‌پذیرم"
                : "ثبت نتیجه و بستن"}
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

export function ServiceHealth({ user }: { user: User }) {
  const alerts = useRemote<{ alerts: OperationalAlert[] }>(
      "/operations/alerts",
    ),
    policy = useRemote<OnCallPolicy | null>("/operations/oncall"),
    members = useRemote<Member[]>("/operations/oncall/members");
  const [editing, setEditing] = useState(false),
    [action, setAction] = useState<{
      alert: OperationalAlert;
      kind: "ACKNOWLEDGE" | "RESOLVE";
    } | null>(null),
    [message, setMessage] = useState("");
  const canWrite = hasPermission(user, "integration:write"),
    canAct = canWrite || !!policy.data?.user_ids.includes(user.id);
  const open = alerts.data?.alerts.filter(
    (row) => row.status !== "RESOLVED",
  ).length;
  return (
    <>
      <section className="panel administration-intro">
        <div className="administration-symbol">
          <HeartPulse size={26} />
        </div>
        <div>
          <h2>هشدار روشن، مسئول مشخص</h2>
          <p>
            این صفحه رویدادهای ثبت‌شدهٔ برنامه و هزینه را پوشش می‌دهد. بررسی
            امنیت اپراتور تلفن و تحویل اعلان‌های بیرونی به شواهد جداگانه نیاز
            دارد.
          </p>
        </div>
        {open !== undefined && (
          <span className="administration-count">
            {faNumber(open)}
            <small>هشدار باز</small>
          </span>
        )}
      </section>
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <section className="panel">
        <SectionTitle
          title="مسئول‌های پاسخ"
          description="برای هشدارهای مهم، پذیرش مسئولیت در همین برنامه ثبت می‌شود."
          action={
            canWrite && (
              <button
                className="button secondary small"
                disabled={
                  policy.loading ||
                  members.loading ||
                  !!policy.error ||
                  !!members.error
                }
                onClick={() => setEditing(true)}
              >
                <Plus size={16} />
                {policy.data ? "ویرایش مسئولیت‌ها" : "تعیین مسئول"}
              </button>
            )
          }
        />
        {policy.error || members.error ? (
          <Retry
            error={policy.error || members.error}
            onRetry={() => {
              policy.refresh();
              members.refresh();
            }}
          />
        ) : policy.loading || members.loading ? (
          <Loading rows={2} />
        ) : !policy.data ? (
          <Empty
            title="مسئول پاسخ تعیین نشده"
            description="مسئول اتصال‌ها می‌تواند افراد و ترتیب ارجاع هشدار را مشخص کند."
          />
        ) : (
          <>
            <div className="oncall-summary">
              <Status
                status={policy.data.enabled ? "ACTIVE" : "DISABLED"}
                label={policy.data.enabled ? "ارجاع فعال" : "ارجاع غیرفعال"}
              />
              <p>
                در صورت نبود رسید پاسخ، ارجاع بعدی پس از{" "}
                {faNumber(policy.data.escalation_minutes)} دقیقه.
              </p>
            </div>
            <ol className="oncall-roster">
              {policy.data.user_ids.map((id) => (
                <li key={id}>
                  <UserCheck size={20} />
                  <span>
                    {members.data?.find((member) => member.user_id === id)
                      ?.name || "عضو خارج از فهرست فعال"}
                  </span>
                </li>
              ))}
            </ol>
            <p className="field-hint">
              ارجاع از طریق کارِ واگذارشده در برنامه انجام می‌شود؛ صرف ارجاع،
              رسید خواندن محسوب نمی‌شود.
            </p>
          </>
        )}
      </section>
      <section className="panel">
        <SectionTitle
          title="هشدارهای اخیر"
          description="حداکثر ۱۰۰ رویداد آخر؛ بدون دادهٔ تازه، سلامت قطعی نتیجه‌گیری نمی‌شود."
        />
        {alerts.error ? (
          <Retry error={alerts.error} onRetry={alerts.refresh} />
        ) : alerts.loading ? (
          <Loading rows={4} />
        ) : !alerts.data?.alerts.length ? (
          <Empty
            title="هشداری در رویدادهای ثبت‌شده نیست"
            description="این نتیجه فقط به رویدادهای دریافت‌شدهٔ همین برنامه مربوط است."
          />
        ) : (
          <div className="administration-list">
            {alerts.data.alerts.map((item) => (
              <article
                className={`operational-alert ${item.status === "RESOLVED" ? "resolved" : ""}`}
                key={item.id}
              >
                <div className="card-heading">
                  <div className="inline-heading">
                    <BellRing size={20} />
                    <h3>
                      {kindNames[item.kind.toLowerCase()] || "هشدار عملیاتی"}
                    </h3>
                  </div>
                  <Status
                    status={item.status}
                    label={alertLabels[item.status] || item.status}
                  />
                </div>
                <p className="field-hint">
                  ثبت در {faDate(item.created_at, true)}
                  {item.acknowledged_at
                    ? ` · پذیرش مسئولیت در ${faDate(item.acknowledged_at, true)}`
                    : ""}
                </p>
                {item.deliveries.length > 0 && (
                  <p className="field-hint">
                    ارجاع به{" "}
                    {item.deliveries
                      .map(
                        (delivery) =>
                          members.data?.find(
                            (member) => member.user_id === delivery.user_id,
                          )?.name || "عضو تیم",
                      )
                      .join("، ")}
                  </p>
                )}
                <details className="compact-details">
                  <summary>شواهد ثبت‌شدهٔ هشدار</summary>
                  <dl className="evidence-values">
                    {Object.entries(item.evidence).map(([key, value]) => (
                      <div key={key}>
                        <dt>
                          <bdi>{key}</bdi>
                        </dt>
                        <dd>
                          <bdi>
                            {typeof value === "object"
                              ? JSON.stringify(value)
                              : String(value ?? "—")}
                          </bdi>
                        </dd>
                      </div>
                    ))}
                  </dl>
                </details>
                {canAct && item.status !== "RESOLVED" && (
                  <div className="card-actions">
                    <button
                      className="button secondary small"
                      onClick={() =>
                        setAction({
                          alert: item,
                          kind:
                            item.status === "ACKNOWLEDGED"
                              ? "RESOLVE"
                              : "ACKNOWLEDGE",
                        })
                      }
                    >
                      <Check size={16} />
                      {item.status === "ACKNOWLEDGED"
                        ? "ثبت نتیجهٔ رسیدگی"
                        : "پذیرش مسئولیت"}
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>
        )}
      </section>
      <LatencyReport />
      {editing && members.data && (
        <OnCallEditor
          initial={policy.data || null}
          members={members.data}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            policy.refresh();
            setMessage("مسئول‌ها و ترتیب ارجاع داخل برنامه ذخیره شدند.");
          }}
        />
      )}
      {action && (
        <AlertAction
          alert={action.alert}
          action={action.kind}
          onClose={() => setAction(null)}
          onSaved={() => {
            setAction(null);
            alerts.refresh();
            setMessage("نتیجهٔ اقدام شما روی هشدار ثبت شد.");
          }}
        />
      )}
    </>
  );
}
