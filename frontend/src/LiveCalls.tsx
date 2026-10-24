import { useEffect, useRef, useState } from "react";
import { Headphones, Mic, MicOff, PhoneOff, Radio } from "lucide-react";
import type { Room } from "livekit-client";
import { errorText, faNumber, post } from "./api";
import {
  Alert,
  Busy,
  Dialog,
  Empty,
  Loading,
  Retry,
  SectionTitle,
} from "./components";
import { useRemote } from "./hooks";
import {
  isRtcActive,
  isRtcRecovering,
  observeRoomLifecycle,
  type RtcStatus,
} from "./rtcLifecycle";

interface ActiveCall {
  id: string;
  clinic_name: string;
  channel: string;
  state: string;
  intent: string;
  started_at: string;
  duration_seconds: number;
  phone_masked: string;
  handoff_status: string;
  policy_version: number;
}
interface JoinResult {
  status: "REQUESTED" | "ROOM_READY" | "CALLBACK_QUEUED";
  task_id: string;
  livekit?: { url: string; token: string; room: string };
}
const callIntents: Record<string, string> = {
  book: "دریافت نوبت",
  cancel: "لغو نوبت",
  reschedule: "تغییر نوبت",
  unknown: "بررسی درخواست",
};
const callStates: Record<string, string> = {
  INTENT: "آغاز گفتگو",
  SERVICE: "انتخاب خدمت",
  PROVIDER: "انتخاب پزشک",
  CHANGE_PROVIDER: "اصلاح پزشک",
  DATE: "انتخاب روز",
  DATE_CHOICE: "تأیید روز",
  TIME_CLARIFY: "روشن‌کردن ساعت",
  OFFER: "انتخاب زمان",
  NAME: "دریافت نام",
  PHONE: "دریافت شماره",
  VERIFY: "تأیید شماره",
  REFERENCE: "بررسی نوبت قبلی",
  CONFIRM: "منتظر تأیید نوبت",
  CANCEL_CONFIRM: "منتظر تأیید لغو",
  REMINDER_CONSENT: "انتخاب یادآوری",
  CORRECTION: "اصلاح اطلاعات",
  COMPLETE: "درخواست بررسی شده",
  HANDOFF_PENDING: "منتظر پذیرش انسانی",
  HUMAN_CONNECTED: "در اختیار پذیرش انسانی",
  ENDED: "پایان‌یافته",
};
function CallRoom({
  connection,
  onClose,
}: {
  connection: { url: string; token: string; room: string };
  onClose: () => void;
}) {
  const room = useRef<Room | null>(null);
  const attempt = useRef(0);
  const alive = useRef(true);
  const audioContainer = useRef<HTMLDivElement | null>(null);
  const [status, setStatus] = useState<RtcStatus>("idle");
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      attempt.current++;
      const retired = room.current;
      room.current = null;
      void retired?.disconnect();
    };
  }, []);
  async function connect() {
    if (isRtcActive(status) || room.current) return;
    const generation = ++attempt.current;
    let connectedRoom: Room | null = null;
    const ownsAttempt = () => alive.current && attempt.current === generation;
    setStatus("connecting");
    setMuted(false);
    setBusy(false);
    setError("");
    try {
      const { Room, RoomEvent } = await import("livekit-client");
      if (!ownsAttempt()) return;
      const current = new Room({ adaptiveStream: true, dynacast: true });
      connectedRoom = current;
      room.current = current;
      const ownsRoom = () => ownsAttempt() && room.current === current;
      let microphoneReady = false;
      const updateStatus = (next: RtcStatus) => {
        if (!ownsRoom()) return;
        setStatus(
          next === "connected" && !microphoneReady ? "connecting" : next,
        );
        if (next === "connected" && microphoneReady)
          setMuted(!current.localParticipant.isMicrophoneEnabled);
        if (next === "disconnected") {
          room.current = null;
          setMuted(false);
          setBusy(false);
          audioContainer.current?.replaceChildren();
        }
      };
      observeRoomLifecycle(current, RoomEvent, ownsRoom, updateStatus);
      current.on(RoomEvent.TrackSubscribed, (track) => {
        if (track.kind === "audio" && ownsRoom()) {
          const element = track.attach();
          element.setAttribute("playsinline", "");
          audioContainer.current?.appendChild(element);
        }
      });
      current.on(RoomEvent.TrackUnsubscribed, (track) =>
        track.detach().forEach((el) => el.remove()),
      );
      await current.connect(connection.url, connection.token);
      if (!ownsRoom()) {
        await current.disconnect();
        return;
      }
      await current.localParticipant.setMicrophoneEnabled(true);
      if (!ownsRoom()) {
        await current.disconnect();
        return;
      }
      microphoneReady = true;
      updateStatus(current.state);
    } catch (e) {
      if (ownsAttempt()) {
        room.current = null;
        setError(
          e instanceof DOMException && e.name === "NotAllowedError"
            ? "اجازهٔ میکروفون داده نشد. برای صحبت در تماس، اجازهٔ مرورگر لازم است."
            : "اتصال صوتی برقرار نشد. می‌توانید درخواست را از طریق پیگیری تلفنی ادامه دهید.",
        );
        setStatus("disconnected");
        setBusy(false);
      }
      await connectedRoom?.disconnect();
    }
  }
  async function toggleMute() {
    const current = room.current;
    if (
      !current ||
      current.state !== "connected" ||
      status !== "connected" ||
      busy
    )
      return;
    setBusy(true);
    try {
      await current.localParticipant.setMicrophoneEnabled(muted);
      if (alive.current && room.current === current)
        setMuted(!current.localParticipant.isMicrophoneEnabled);
      else await current.disconnect();
    } catch {
      if (alive.current && room.current === current)
        setError("تغییر وضعیت میکروفون ممکن نشد.");
    } finally {
      if (alive.current && room.current === current) setBusy(false);
    }
  }
  return (
    <Dialog title="همراهی زنده در تماس" onClose={onClose}>
      <div className="modal-body">
        <div className="call-room-status">
          <span className="call-room-orb">
            <Headphones size={32} />
          </span>
          <strong role="status" aria-live="polite">
            {status === "connected"
              ? "به اتاق تماس متصل شدید"
              : status === "connecting"
                ? "در حال برقراری ارتباط…"
                : isRtcRecovering(status)
                  ? "در حال برقراری دوبارهٔ ارتباط…"
                  : status === "disconnected"
                    ? "ارتباط پایان یافت"
                    : "آمادهٔ برقراری ارتباط"}
          </strong>
          <p>
            با شروع اتصال، مرورگر اجازهٔ میکروفون می‌خواهد و صدای شما به اتاق
            همین تماس فرستاده می‌شود.
          </p>
        </div>
        {error && <Alert>{error}</Alert>}
        <div ref={audioContainer} />
        <div className="modal-actions">
          {status === "idle" || status === "disconnected" ? (
            <button className="button primary" onClick={() => void connect()}>
              <Mic size={17} />
              شروع اتصال با میکروفون
            </button>
          ) : status === "connected" || isRtcRecovering(status) ? (
            <button
              className="button secondary"
              disabled={busy || status !== "connected"}
              onClick={() => void toggleMute()}
            >
              {muted ? <Mic size={17} /> : <MicOff size={17} />}
              {muted ? "فعال‌کردن میکروفون" : "بی‌صدا کردن"}
            </button>
          ) : (
            <button className="button secondary" disabled>
              <Busy busy>در حال اتصال</Busy>
            </button>
          )}
          <button className="button danger-quiet" onClick={onClose}>
            <PhoneOff size={17} />
            خروج
          </button>
        </div>
      </div>
    </Dialog>
  );
}

export function LiveCalls({ canTakeover = true }: { canTakeover?: boolean }) {
  const calls = useRemote<ActiveCall[]>("/operations/calls", 5000);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [connection, setConnection] = useState<JoinResult["livekit"]>();
  async function takeover(call: ActiveCall) {
    if (!canTakeover) return;
    setBusy(call.id);
    setError("");
    setMessage("");
    try {
      const result = await post<JoinResult>(
        `/operations/calls/${call.id}/takeover`,
        {},
      );
      if (result.status === "ROOM_READY" && result.livekit)
        setConnection(result.livekit);
      else
        setMessage(
          result.status === "CALLBACK_QUEUED"
            ? "تماس زنده برای این مسیر فعال نیست. درخواست پیگیری در فهرست تیم پذیرش ثبت شد."
            : "درخواست همراهی ثبت شد و منتظر آماده‌شدن مسیر تماس است.",
        );
      calls.refresh();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy("");
    }
  }
  return (
    <section className="panel live-calls-panel">
      <SectionTitle
        title="تماس‌های جاری"
        description="وضعیت نشست‌های فعال و درخواست همراهی تیم"
        action={
          <span className="live-call-count">
            <Radio size={15} />
            {calls.error
              ? "وضعیت تازه در دسترس نیست"
              : calls.loading
                ? "در حال بررسی"
                : `${faNumber(calls.data?.length || 0)} فعال`}
          </span>
        }
      />
      {message && (
        <div className="panel-inline-message">
          <Alert kind="info" onClose={() => setMessage("")}>
            {message}
          </Alert>
        </div>
      )}
      {error && (
        <div className="panel-inline-message">
          <Alert onClose={() => setError("")}>{error}</Alert>
        </div>
      )}
      {calls.error ? (
        <Retry error={calls.error} onRetry={calls.refresh} />
      ) : calls.loading ? (
        <Loading rows={1} />
      ) : calls.data?.length ? (
        <div className="live-call-list">
          {calls.data.map((call) => (
            <div className="live-call-row" key={call.id}>
              <span className="live-call-icon">
                <Radio size={19} />
              </span>
              <div className="live-call-info">
                <strong>{call.phone_masked || "مراجعه‌کنندهٔ آنلاین"}</strong>
                <small>
                  {call.channel === "browser" ? "پذیرش آنلاین" : "تماس ورودی"} ·{" "}
                  {call.clinic_name}
                </small>
                <small>
                  {callIntents[call.intent] || "گفتگوی پذیرش"} ·{" "}
                  {callStates[call.state] || "در حال بررسی درخواست"}
                </small>
                {call.handoff_status === "CONNECTED" && (
                  <small>پیوستن همکار تأیید شده است.</small>
                )}
              </div>
              <span className="live-call-duration">
                {faNumber(Math.floor(call.duration_seconds / 60))}:
                {faNumber(String(call.duration_seconds % 60).padStart(2, "0"))}
              </span>
              {canTakeover && (
                <button
                  className="button secondary small"
                  disabled={busy === call.id}
                  onClick={() => void takeover(call)}
                >
                  <Busy busy={busy === call.id}>
                    <Headphones size={16} />
                    همراهی و پیگیری
                  </Busy>
                </button>
              )}
            </div>
          ))}
        </div>
      ) : (
        <Empty
          title="در حال حاضر تماس فعالی نیست"
          description="نشست‌های پذیرش و درخواست‌های همراهی، هنگام شروع گفتگو نمایش داده می‌شوند."
        />
      )}
      {connection && (
        <CallRoom
          connection={connection}
          onClose={() => setConnection(undefined)}
        />
      )}
    </section>
  );
}
