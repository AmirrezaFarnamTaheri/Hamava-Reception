import { useState, type FormEvent } from "react";
import { Bell, CheckCheck, Plus, Send } from "lucide-react";
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
export interface OutreachPolicy {
  version: number;
  reminder_offsets_minutes: number[];
  waitlist_auto_offer: boolean;
  waitlist_offer_limit_per_run: number;
  followup_enabled: boolean;
  followup_offsets_days: number[];
  clinician_approved_version: number | null;
  clinician_user_id: string | null;
  clinician_approved_at: string | null;
  followup_effective: boolean;
  outbound_voice_enabled: boolean;
}
function parseOffsets(value: string) {
  const normalized = value
    .replace(/[۰-۹]/g, (char) => String("۰۱۲۳۴۵۶۷۸۹".indexOf(char)))
    .replace(/[٠-٩]/g, (char) => String("٠١٢٣٤٥٦٧٨٩".indexOf(char)));
  return normalized.trim()
    ? normalized
        .split(/[,،\s]+/)
        .filter(Boolean)
        .map(Number)
    : [];
}
function PolicyForm({
  initial,
  canEdit,
  canApprove,
  onSaved,
}: {
  initial: OutreachPolicy;
  canEdit: boolean;
  canApprove: boolean;
  onSaved: () => void;
}) {
  const [reminders, setReminders] = useState(
    initial.reminder_offsets_minutes.join("، "),
  );
  const [followups, setFollowups] = useState(
    initial.followup_offsets_days.join("، "),
  );
  const [autoOffer, setAutoOffer] = useState(initial.waitlist_auto_offer);
  const [enabled, setEnabled] = useState(initial.followup_enabled);
  const [limit, setLimit] = useState(initial.waitlist_offer_limit_per_run);
  const [approved, setApproved] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const reminderOffsets = parseOffsets(reminders),
        followupOffsets = parseOffsets(followups);
      if (
        [...reminderOffsets, ...followupOffsets].some(
          (value) => !Number.isInteger(value),
        )
      )
        throw new Error("فاصله‌ها باید عدد صحیح باشند و با ویرگول جدا شوند.");
      await api("/operations/outreach-policy", {
        method: "PUT",
        body: JSON.stringify({
          version: initial.version,
          reminder_offsets_minutes: reminderOffsets,
          waitlist_auto_offer: autoOffer,
          waitlist_offer_limit_per_run: limit,
          followup_enabled: enabled,
          followup_offsets_days: followupOffsets,
        }),
      });
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  async function approve() {
    setBusy(true);
    setError("");
    try {
      await post("/operations/outreach-policy/approve", {
        version: initial.version,
        confirmed: approved,
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
          title="یادآوری و فرصت‌های آزاد"
          description="پیام‌ها فقط با رضایت مربوط به همان هدف و رعایت ساعت آرامش آماده می‌شوند."
        />
        <fieldset disabled={!canEdit || busy}>
          <Field
            label="فاصله‌های یادآوری تا نوبت، به دقیقه"
            hint="حداکثر ۶ فاصله با ویرگول؛ از ۵ تا ۱۰۰۸۰ دقیقه. مثال: ۱۴۴۰، ۳۶۰. خالی یعنی بدون یادآوری."
          >
            <input
              value={reminders}
              onChange={(e) => setReminders(e.target.value)}
            />
          </Field>
          <label className="check-field">
            <input
              type="checkbox"
              checked={autoOffer}
              onChange={(e) => setAutoOffer(e.target.checked)}
            />
            <span>
              زمانی که ظرفیت واقعی آزاد شد، پیشنهاد انتظار به‌صورت خودکار آماده
              شود.
            </span>
          </label>
          <Field label="حداکثر پیشنهاد در هر نوبت بررسی">
            <input
              type="number"
              min={1}
              max={20}
              required
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
            />
          </Field>
        </fieldset>
      </section>
      <section className="panel settings-panel">
        <SectionTitle
          title="پیگیری پس از مراجعه"
          description="پیام اداری برای هماهنگی پذیرش؛ بدون توصیهٔ درمانی یا تماس صوتی خودکار."
        />
        <fieldset disabled={!canEdit || busy}>
          <label className="check-field">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => setEnabled(e.target.checked)}
            />
            <span>
              برنامهٔ پیگیری پس از مراجعه برای تأیید مسئول بالینی آماده شود.
            </span>
          </label>
          <Field
            label="روزهای پیگیری پس از مراجعه"
            hint="حداکثر ۶ روز از ۱ تا ۳۶۵؛ با ویرگول جدا کنید."
          >
            <input
              value={followups}
              onChange={(e) => setFollowups(e.target.value)}
            />
          </Field>
        </fieldset>
        <Alert kind={initial.followup_effective ? "success" : "info"}>
          {initial.followup_effective
            ? `نسخهٔ ${faNumber(initial.version)} توسط مسئول بالینی تأیید شده و برای ثبت درخواست مجاز است.`
            : "برنامهٔ پیگیری تا تأیید مسئول بالینی و رضایت مستقل مراجعه‌کننده اجرا نمی‌شود."}
        </Alert>
        {initial.clinician_approved_at && (
          <p className="field-hint">
            زمان تأیید: {faDate(initial.clinician_approved_at, true)}
          </p>
        )}
        {canApprove &&
          initial.followup_enabled &&
          !initial.followup_effective && (
            <>
              <label className="check-field">
                <input
                  type="checkbox"
                  checked={approved}
                  onChange={(e) => setApproved(e.target.checked)}
                />
                <span>
                  به‌عنوان مسئول بالینی مجاز، پیام اداری و روزهای پیگیری نسخهٔ
                  جاری را بررسی و تأیید می‌کنم.
                </span>
              </label>
              <button
                type="button"
                className="button primary"
                disabled={busy || !approved}
                onClick={() => void approve()}
              >
                <Busy busy={busy}>
                  <CheckCheck size={17} />
                  تأیید برنامهٔ پیگیری
                </Busy>
              </button>
            </>
          )}
      </section>
      {error && <Alert>{error}</Alert>}
      {canEdit && (
        <div className="settings-save">
          <p className="field-hint">
            هر انتشار، تأیید قبلیِ برنامهٔ پیگیری را پاک می‌کند و به بررسی
            دوباره نیاز دارد.
          </p>
          <button className="button primary" disabled={busy}>
            <Busy busy={busy}>انتشار قواعد پیام‌رسانی</Busy>
          </button>
        </div>
      )}
    </form>
  );
}
function ChannelPermission() {
  const [phone, setPhone] = useState("");
  const [channel, setChannel] = useState("sms");
  const [purpose, setPurpose] = useState("reminder");
  const [granted, setGranted] = useState(false);
  const [evidence, setEvidence] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await post("/operations/channel-permissions", {
        phone,
        channel,
        purpose,
        granted,
        evidence_reference: evidence,
      });
      setMessage("وضعیت اجازهٔ این مسیر برای همین هدف ثبت شد.");
      setPhone("");
      setEvidence("");
      setGranted(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel settings-panel">
      <SectionTitle
        title="اجازهٔ مسیر ارتباطی"
        description="ترجیح مستند مراجعه‌کننده برای یک مسیر و هدف مشخص؛ مستقل از رضایت کلی و انصراف‌ها."
      />
      <form onSubmit={submit}>
        <div className="form-grid">
          <Field label="شماره همراه صاحب اجازه">
            <input
              type="tel"
              required
              dir="ltr"
              value={phone}
              maxLength={30}
              onChange={(e) => setPhone(e.target.value)}
            />
          </Field>
          <Field label="مسیر ارتباطی">
            <select
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            >
              {[
                ["sms", "پیامک"],
                ["telegram", "تلگرام"],
                ["bale", "بله"],
                ["eitaa", "ایتا"],
                ["whatsapp", "واتس‌اپ"],
                ["email", "ایمیل"],
              ].map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="هدف ارتباط">
            <select
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
            >
              <option value="reminder">یادآوری</option>
              <option value="waitlist">پیشنهاد انتظار</option>
              <option value="followup">پیگیری پس از مراجعه</option>
            </select>
          </Field>
          <Field label="مرجع رضایت یا درخواست">
            <input
              required
              minLength={3}
              maxLength={200}
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
              placeholder="شناسهٔ فرم یا شرح کوتاه درخواست"
            />
          </Field>
        </div>
        <label className="check-field">
          <input
            type="checkbox"
            checked={granted}
            onChange={(e) => setGranted(e.target.checked)}
          />
          <span>
            اجازهٔ استفاده از این مسیر و هدف داده شده است. خاموش یعنی اجازه
            ندارد.
          </span>
        </label>
        <p className="field-hint">
          این ثبت، اتصال ارائه‌دهنده یا رضایت برای هدف دیگری را ایجاد نمی‌کند.
          انصراف قبلی همچنان معتبر است.
        </p>
        {error && <Alert>{error}</Alert>}
        {message && <Alert kind="success">{message}</Alert>}
        <button className="button secondary" disabled={busy}>
          <Busy busy={busy}>ثبت اجازهٔ مسیر</Busy>
        </button>
      </form>
    </section>
  );
}
export function OutreachSettings({
  role,
  canEdit,
}: {
  role: string;
  canEdit: boolean;
}) {
  const result = useRemote<OutreachPolicy>("/operations/outreach-policy");
  const [message, setMessage] = useState("");
  return (
    <>
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      {result.error ? (
        <Retry error={result.error} onRetry={result.refresh} />
      ) : result.loading ? (
        <Loading rows={4} />
      ) : (
        result.data && (
          <PolicyForm
            key={result.data.version + ":" + result.data.clinician_approved_at}
            initial={result.data}
            canEdit={canEdit}
            canApprove={role === "clinician"}
            onSaved={() => {
              result.refresh();
              setMessage("وضعیت قواعد پیام‌رسانی ثبت شد.");
            }}
          />
        )
      )}
      {canEdit && <ChannelPermission />}
      <div className="note-line">
        <Bell size={17} />
        <span>
          وضعیت تحویل هر پیام در بخش «پیام‌ها» قابل بررسی است. ثبت یا صف‌گذاری،
          به معنای تحویل نیست.
        </span>
      </div>
    </>
  );
}
interface Enrollment {
  id: string;
  appointment_id: string;
  policy_version: number;
  offsets_days: number[];
  status: string;
  created_at: string;
}
function Enroll({
  policy,
  onClose,
  onSaved,
}: {
  policy: OutreachPolicy;
  onClose: () => void;
  onSaved: () => void;
}) {
  const appointments = useRemote<Appointment[]>("/appointments");
  const [appointment, setAppointment] = useState("");
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await post("/operations/followups", {
        appointment_id: appointment,
        policy_version: policy.version,
        confirmed_consent: consent,
      });
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Dialog
      title="ثبت پیگیری پس از مراجعه"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <form className="modal-body" onSubmit={submit}>
        <p>
          روزهای تأییدشده:{" "}
          {policy.followup_offsets_days.map(faNumber).join("، ")} روز پس از
          مراجعه.
        </p>
        {appointments.error ? (
          <Retry error={appointments.error} onRetry={appointments.refresh} />
        ) : (
          <Field label="نوبت با مراجعهٔ انجام‌شده">
            <select
              required
              value={appointment}
              onChange={(e) => setAppointment(e.target.value)}
            >
              <option value="">انتخاب کنید</option>
              {appointments.data
                ?.filter((item) => item.attendance === "ATTENDED")
                .map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.patient_name} · {item.jalali_display}
                  </option>
                ))}
            </select>
          </Field>
        )}
        <p className="field-hint">حداکثر ۲۵۰ نوبت اخیر نمایش داده می‌شود.</p>
        <label className="check-field">
          <input
            type="checkbox"
            required
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
          />
          <span>
            مراجعه‌کننده با همین پیام اداری و روزهای پیگیری موافقت کرده است.
          </span>
        </label>
        {error && <Alert>{error}</Alert>}
        <div className="modal-actions">
          <button
            className="button primary"
            disabled={busy || !consent || !appointment}
          >
            <Busy busy={busy}>ثبت درخواست پیگیری</Busy>
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
export function Followups() {
  const policy = useRemote<OutreachPolicy>("/operations/outreach-policy");
  const result = useRemote<Enrollment[]>("/operations/followups");
  const appointments = useRemote<Appointment[]>("/appointments");
  const [adding, setAdding] = useState(false);
  const [message, setMessage] = useState("");
  return (
    <>
      {message && (
        <Alert kind="success" onClose={() => setMessage("")}>
          {message}
        </Alert>
      )}
      <section className="panel">
        <SectionTitle
          title="پیگیری پس از مراجعه"
          description="درخواست‌های مجاز برای پیام اداری پس از مراجعهٔ ثبت‌شده."
          action={
            <button
              className="button primary small"
              disabled={!policy.data?.followup_effective}
              onClick={() => setAdding(true)}
            >
              <Plus size={17} />
              افزودن پیگیری
            </button>
          }
        />
        {policy.error ? (
          <Retry error={policy.error} onRetry={policy.refresh} />
        ) : (
          !policy.loading &&
          !policy.data?.followup_effective && (
            <div className="panel-notice">
              <Alert kind="info">
                برنامهٔ پیگیری هنوز تأیید بالینی ندارد. ابتدا قواعد آن را در
                تنظیمات مرکز منتشر و تأیید کنید.
              </Alert>
            </div>
          )
        )}
        {result.error ? (
          <Retry error={result.error} onRetry={result.refresh} />
        ) : result.loading ? (
          <Loading rows={3} />
        ) : result.data?.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
          >
            <table>
              <thead>
                <tr>
                  <th>نوبت</th>
                  <th>روزهای پیگیری</th>
                  <th>نسخهٔ برنامه</th>
                  <th>وضعیت</th>
                  <th>زمان ثبت</th>
                </tr>
              </thead>
              <tbody>
                {result.data.map((row) => (
                  <tr key={row.id}>
                    <td>
                      {appointments.data?.find(
                        (item) => item.id === row.appointment_id,
                      )?.patient_name || "نوبت مرکز"}
                    </td>
                    <td>{row.offsets_days.map(faNumber).join("، ")}</td>
                    <td>{faNumber(row.policy_version)}</td>
                    <td>
                      <Status value={row.status} />
                    </td>
                    <td>{faDate(row.created_at, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="درخواست پیگیری ثبت نشده"
            description="پس از مراجعه و با رضایت مستقل بیمار، درخواست پیگیری را ثبت کنید."
          />
        )}
      </section>
      <div className="note-line">
        <Send size={16} />
        <span>
          انصراف از این پیام‌ها از بخش حریم خصوصی ثبت می‌شود. پیام‌ها فقط پس از
          اتصال مسیر مجاز و بررسی رضایت ارسال می‌شوند.
        </span>
      </div>
      {adding && policy.data && (
        <Enroll
          policy={policy.data}
          onClose={() => setAdding(false)}
          onSaved={() => {
            setAdding(false);
            result.refresh();
            setMessage("درخواست پیگیری با رضایت مشخص ثبت شد.");
          }}
        />
      )}
    </>
  );
}
