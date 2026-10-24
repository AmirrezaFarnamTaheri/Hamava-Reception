import { useRef, useState, type FormEvent } from "react";
import {
  CheckCheck,
  Clock3,
  Headphones,
  RefreshCw,
  Search,
  UserCheck,
} from "lucide-react";
import { errorText, faDate, faNumber, newId, post } from "../api";
import {
  Alert,
  Busy,
  Dialog,
  Empty,
  Field,
  Loading,
  PageTitle,
  Retry,
  Status,
} from "../components";
import { useRemote } from "../hooks";
import type { StaffTask, User } from "../types";
import { LiveCalls } from "../LiveCalls";
import { hasPermission } from "../permissions";
interface Task extends StaffTask {
  version: number;
  assignee_id: string | null;
  assignee_name: string | null;
  callback_at: string | null;
}
interface Assignee {
  user_id: string;
  name: string;
  role: string;
}
const actions: Record<string, string> = {
  claim: "پذیرفتن پیگیری",
  reassign: "واگذاری به همکار",
  pending: "در انتظار پاسخ",
  callback: "زمان‌بندی تماس مجدد",
  resolve: "ثبت نتیجه و بستن",
  reopen: "بازگشایی درخواست",
  reject: "بازگرداندن به صف",
  redirect: "ارجاع به همکار",
};
function taskReason(value: string) {
  const reason = value.toLowerCase();
  if (reason.includes("human") || reason.includes("transfer"))
    return "همراهی انسانی";
  if (reason.includes("urgent") || reason.includes("emergency"))
    return "پیگیری فوری";
  if (reason.includes("disruption")) return "تغییر برنامهٔ مراجعه";
  if (reason.includes("refund")) return "پیگیری بازپرداخت";
  if (reason.includes("payment")) return "بررسی پرداخت";
  if (reason.includes("booking") || reason.includes("appointment"))
    return "هماهنگی نوبت";
  if (reason.includes("notification") || reason.includes("sms"))
    return "بررسی پیام";
  return "پیگیری پذیرش";
}
function TaskAction({
  task,
  action,
  onClose,
  onSaved,
}: {
  task: Task;
  action: string;
  onClose: () => void;
  onSaved: (updated: Task) => void;
}) {
  const [reason, setReason] = useState("");
  const [assignee, setAssignee] = useState("");
  const [callback, setCallback] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const requestId = useRef(newId());
  const needsAssignee = ["redirect", "reassign"].includes(action);
  const assignees = useRemote<Assignee[]>(
    needsAssignee ? "/operations/assignees" : null,
  );
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const updated = await post<Task>(`/operations/tasks/${task.id}/actions`, {
        action,
        version: task.version,
        idempotency_key: requestId.current,
        reason,
        ...(needsAssignee ? { assignee_id: assignee } : {}),
        ...(action === "callback"
          ? { callback_at: new Date(callback + ":00+03:30").toISOString() }
          : {}),
      });
      onSaved(updated);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title={actions[action]}
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <div className="selected-appointment">
          <strong>{task.summary}</strong>
          <span>
            {task.assignee_name
              ? `مسئول فعلی: ${task.assignee_name}`
              : "هنوز به همکاری واگذار نشده"}
          </span>
          <Status value={task.status} />
        </div>
        {needsAssignee && (
          <>
            {assignees.error ? (
              <Retry error={assignees.error} onRetry={assignees.refresh} />
            ) : (
              <Field label="همکار مسئول">
                <select
                  required
                  value={assignee}
                  onChange={(e) => setAssignee(e.target.value)}
                >
                  <option value="">انتخاب کنید</option>
                  {assignees.data?.map((person) => (
                    <option key={person.user_id} value={person.user_id}>
                      {person.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </>
        )}
        {action === "callback" && (
          <Field label="زمان تماس مجدد به وقت تهران">
            <input
              required
              type="datetime-local"
              value={callback}
              onChange={(e) => setCallback(e.target.value)}
            />
          </Field>
        )}
        <Field
          label={
            action === "resolve"
              ? "چه اقدامی انجام شد؟"
              : "دلیل یا نتیجهٔ این اقدام"
          }
          hint="فقط اطلاعات لازم برای پذیرش را ثبت کنید؛ شرح پزشکی وارد نکنید."
        >
          <textarea
            required
            minLength={3}
            maxLength={500}
            rows={4}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
          />
        </Field>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || (needsAssignee && !assignee)}
          >
            <Busy busy={busy}>{actions[action]}</Busy>
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
export function TaskQueue({ user }: { user: User }) {
  const result = useRemote<Task[]>("/operations/tasks", 10000);
  const [filter, setFilter] = useState("active");
  const [query, setQuery] = useState("");
  const [updatedTasks, setUpdatedTasks] = useState<Record<string, Task>>({});
  const [selected, setSelected] = useState<{
    task: Task;
    action: string;
  } | null>(null);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const canWrite = hasPermission(user, "task:write");
  const admin =
    ["owner", "admin", "manager", "coordinator"].includes(user.role) &&
    canWrite;
  const allTasks =
    result.data?.map((task) =>
      updatedTasks[task.id]?.version > task.version
        ? updatedTasks[task.id]
        : task,
    ) || [];
  const items = allTasks.filter(
    (task) =>
      (filter === "all" ||
        (filter === "mine" &&
          task.assignee_id === user.id &&
          task.status !== "RESOLVED") ||
        (filter === "active"
          ? task.status !== "RESOLVED"
          : task.status === filter)) &&
      (!query || `${task.summary} ${task.assignee_name || ""}`.includes(query)),
  );
  async function claim(task: Task) {
    if (!canWrite) return;
    setBusy(task.id);
    setError("");
    try {
      const updated = await post<Task>(`/operations/tasks/${task.id}/actions`, {
        action: "claim",
        version: task.version,
        idempotency_key: newId(),
      });
      setUpdatedTasks((old) => ({ ...old, [updated.id]: updated }));
      result.refresh();
      setMessage("پیگیری این درخواست به شما سپرده شد.");
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  return (
    <>
      <PageTitle
        eyebrow="همراهی انسانی"
        title="پیگیری‌ها"
        description="مسئول، زمان اقدام و نتیجهٔ هر درخواست را روشن نگه دارید."
        action={
          <button className="button secondary" onClick={result.refresh}>
            <RefreshCw size={17} />
            تازه‌سازی
          </button>
        }
      />
      {error && <Alert onClose={() => setError("")}>{error}</Alert>}
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <details className="task-live-disclosure">
        <summary>
          <Headphones size={18} />
          تماس‌های جاری و همراهی انسانی
        </summary>
        <LiveCalls canTakeover={canWrite} />
      </details>
      <div className="task-view-tabs" aria-label="نمای پیگیری‌ها">
        {[
          {
            value: "active",
            label: "همهٔ فعال‌ها",
            count: allTasks.filter((task) => task.status !== "RESOLVED").length,
          },
          {
            value: "mine",
            label: "کارهای من",
            count: allTasks.filter(
              (task) =>
                task.assignee_id === user.id && task.status !== "RESOLVED",
            ).length,
          },
          {
            value: "CALLBACK",
            label: "تماس مجدد",
            count: allTasks.filter((task) => task.status === "CALLBACK").length,
          },
        ].map((item) => (
          <button
            type="button"
            key={item.value}
            aria-pressed={filter === item.value}
            onClick={() => setFilter(item.value)}
          >
            {item.label}
            {!result.loading && !result.error && (
              <span>{faNumber(item.count)}</span>
            )}
          </button>
        ))}
      </div>
      <div className="table-toolbar task-filters">
        <label className="search-input">
          <Search size={18} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            aria-label="جست‌وجوی پیگیری‌ها"
            placeholder="عنوان درخواست یا مسئول…"
          />
        </label>
        <label className="sr-only" htmlFor="task-filter">
          فیلتر پیگیری‌ها
        </label>
        <select
          id="task-filter"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        >
          <option value="active">همهٔ درخواست‌های فعال</option>
          <option value="mine">کارهای من</option>
          <option value="OPEN">منتظر پذیرش همکار</option>
          <option value="IN_PROGRESS">در حال رسیدگی</option>
          <option value="PENDING">در انتظار پاسخ</option>
          <option value="CALLBACK">تماس مجدد</option>
          <option value="RESOLVED">رسیدگی‌شده</option>
          <option value="all">همهٔ درخواست‌ها</option>
        </select>
      </div>
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading ? (
        <Loading rows={4} />
      ) : items.length ? (
        <div className="work-list">
          {items.map((task) => {
            const mine = task.assignee_id === user.id;
            const canAct = canWrite && (admin || mine);
            return (
              <article
                className="panel work-card"
                key={task.id}
                data-task-id={task.id}
              >
                <span
                  className={`work-icon ${["HIGH", "URGENT"].includes(task.priority.toUpperCase()) ? "urgent" : ""}`}
                >
                  <Headphones size={23} />
                </span>
                <div className="work-content">
                  <div className="work-card-heading">
                    <h2>{taskReason(task.reason)}</h2>
                    <Status value={task.priority.toUpperCase()} />
                    <Status value={task.status} />
                  </div>
                  <p>{task.summary}</p>
                  <div className="work-meta">
                    <Clock3 size={14} />
                    <span>{faDate(task.created_at, true)}</span>
                    <span>
                      {task.assignee_name
                        ? `مسئول: ${task.assignee_name}`
                        : "بدون مسئول"}
                    </span>
                    {task.callback_at && (
                      <strong>
                        تماس مجدد: {faDate(task.callback_at, true)}
                      </strong>
                    )}
                  </div>
                  {task.resolution && (
                    <div className="resolution">
                      <CheckCheck size={16} />
                      {task.resolution}
                    </div>
                  )}
                  <fieldset
                    className="inline-actions task-actions"
                    disabled={busy === task.id}
                  >
                    {canWrite &&
                      task.status !== "RESOLVED" &&
                      (!task.assignee_id || mine) && (
                        <button
                          className="button secondary small"
                          disabled={
                            busy === task.id ||
                            (task.status === "IN_PROGRESS" && mine)
                          }
                          onClick={() => void claim(task)}
                        >
                          <Busy busy={busy === task.id}>
                            <UserCheck size={15} />
                            {mine ? "مسئولیت شما" : "پذیرفتن پیگیری"}
                          </Busy>
                        </button>
                      )}
                    {task.status !== "RESOLVED" && canAct && (
                      <>
                        <button
                          className="button primary small"
                          onClick={() =>
                            setSelected({ task, action: "resolve" })
                          }
                        >
                          ثبت نتیجهٔ پیگیری
                        </button>
                        <button
                          className="button secondary small"
                          onClick={() =>
                            setSelected({ task, action: "callback" })
                          }
                        >
                          تماس مجدد
                        </button>
                        <button
                          className="button secondary small"
                          onClick={() =>
                            setSelected({ task, action: "pending" })
                          }
                        >
                          در انتظار پاسخ
                        </button>
                        <button
                          className="button secondary small"
                          onClick={() =>
                            setSelected({ task, action: "reject" })
                          }
                        >
                          بازگشت به صف
                        </button>
                      </>
                    )}
                    {admin && task.status !== "RESOLVED" && (
                      <>
                        <button
                          className="button secondary small"
                          onClick={() =>
                            setSelected({ task, action: "reassign" })
                          }
                        >
                          واگذاری
                        </button>
                        <button
                          className="button secondary small"
                          onClick={() =>
                            setSelected({ task, action: "redirect" })
                          }
                        >
                          ارجاع
                        </button>
                      </>
                    )}
                    {task.status === "RESOLVED" && canAct && (
                      <button
                        className="button secondary small"
                        onClick={() => setSelected({ task, action: "reopen" })}
                      >
                        بازگشایی
                      </button>
                    )}
                  </fieldset>
                </div>
              </article>
            );
          })}
        </div>
      ) : (
        <section className="panel">
          <Empty
            title="درخواستی در این بخش نیست"
            description="درخواست‌های مراجعه‌کنندگان و موارد نیازمند تصمیم پذیرش، در این فهرست ثبت می‌شوند."
          />
        </section>
      )}
      {selected && (
        <TaskAction
          {...selected}
          onClose={() => setSelected(null)}
          onSaved={(updated) => {
            setUpdatedTasks((old) => ({ ...old, [updated.id]: updated }));
            setSelected(null);
            result.refresh();
            setMessage("وضعیت و نتیجهٔ پیگیری ثبت شد.");
          }}
        />
      )}
    </>
  );
}
