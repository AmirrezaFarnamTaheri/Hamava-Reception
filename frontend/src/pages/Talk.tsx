import {
  useEffect,
  useRef,
  useState,
  type FormEvent,
  type CSSProperties,
} from "react";
import {
  ArrowLeft,
  Check,
  CheckCircle2,
  Headphones,
  MapPin,
  MessageCircle,
  Mic,
  MicOff,
  Phone,
  PhoneOff,
  Radio,
  Send,
  ShieldCheck,
  Square,
  Volume2,
  VolumeX,
  Waves,
} from "lucide-react";
import type { Room } from "livekit-client";
import {
  api,
  ApiError,
  errorText,
  faDate,
  faNumber,
  newId,
  post,
} from "../api";
import { Alert, Brand, Busy, Loading, Status } from "../components";
import type {
  Appointment,
  PublicClinic,
  VoiceSession,
  VoiceTurn,
  Slot,
  PaymentTerms,
} from "../types";
import { PaymentTermsDetails } from "./PaymentPolicy";
import { apiUrl } from "../platform";
import {
  isRtcActive,
  isRtcRecovering,
  observeRoomLifecycle,
  type RtcStatus,
} from "../rtcLifecycle";

interface ChatMessage {
  id: string;
  role: "assistant" | "user";
  text: string;
  turn_id?: string;
}
function ConversationPrivacyNotice({ clinic }: { clinic: PublicClinic }) {
  const retention = clinic.transcript_retention_days;
  return (
    <div className="conversation-privacy-notice">
      <p>
        {clinic.notice ||
          "صدای خام ذخیره نمی‌شود و گفتگو برای آموزش استفاده نمی‌شود. متن و نتایج ضروری گفتگو برای پذیرش و بازیابی درخواست‌ها به‌صورت رمزگذاری‌شده نگهداری می‌شود. دربارهٔ مدت نگهداری، درخواست حذف یا ادامهٔ خدمت بدون دستیار، با پذیرش مرکز تماس بگیرید."}
      </p>
      {clinic.processing_notice && <p>{clinic.processing_notice}</p>}
      {typeof retention === "number" &&
        Number.isInteger(retention) &&
        retention >= 0 && (
          <p className="privacy-retention">
            مدت نگهداری متن ضروری پس از پایان گفتگو: {faNumber(retention)} روز
          </p>
        )}
    </div>
  );
}
export function Talk({ slug }: { slug: string }) {
  const [clinic, setClinic] = useState<PublicClinic | null>(null);
  const [paymentTerms, setPaymentTerms] = useState<PaymentTerms | null>(null);
  const [paymentTermsError, setPaymentTermsError] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [consent, setConsent] = useState(false);
  const [noticeRefreshRequired, setNoticeRefreshRequired] = useState(false);
  const [session, setSession] = useState<VoiceSession | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [state, setState] = useState("");
  const [booking, setBooking] = useState<Appointment | null>(null);
  const [offers, setOffers] = useState<Slot[]>([]);
  const [ended, setEnded] = useState(false);
  const [recording, setRecording] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [liveStatus, setLiveStatus] = useState<RtcStatus>("idle");
  const liveConnected = liveStatus === "connected";
  const liveConnecting = liveStatus === "connecting";
  const liveReconnecting = isRtcRecovering(liveStatus);
  const liveActive = isRtcActive(liveStatus);
  const [liveMuted, setLiveMuted] = useState(false);
  const [liveMicBusy, setLiveMicBusy] = useState(false);
  const liveRoom = useRef<Room | null>(null);
  const liveAttempt = useRef(0);
  const liveAudio = useRef<HTMLDivElement | null>(null);
  const receivedTurns = useRef(new Set<string>());
  const [failedTurn, setFailedTurn] = useState<{
    text: string;
    id: string;
  } | null>(null);
  const [failedAudio, setFailedAudio] = useState<{
    blob: Blob;
    id: string;
  } | null>(null);
  const [microphonePending, setMicrophonePending] = useState(false);
  const openingMicrophone = useRef(false);
  const ending = useRef(false);
  const [handoffMessage, setHandoffMessage] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const audioUrl = useRef("");
  const speechRequest = useRef(0);
  const speechAbort = useRef<AbortController | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);
  const listEnd = useRef<HTMLDivElement | null>(null);
  const alive = useRef(true);
  const sessionRef = useRef<VoiceSession | null>(null);
  const discardRecording = useRef(false);
  const requestAbort = useRef<AbortController | null>(null);
  const rate = useRef(1);
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    api<PaymentTerms>(
      `/public/clinics/${encodeURIComponent(slug)}/payment-policy`,
      { token: null, signal: controller.signal },
    )
      .then((value) => {
        setPaymentTerms(value);
        setPaymentTermsError(false);
      })
      .catch(() => {
        if (!controller.signal.aborted) setPaymentTermsError(true);
      });
    api<PublicClinic>(`/public/clinics/${encodeURIComponent(slug)}`, {
      token: null,
      signal: controller.signal,
    })
      .then(setClinic)
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorText(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      alive.current = false;
      liveAttempt.current++;
      controller.abort();
      requestAbort.current?.abort();
      speechAbort.current?.abort();
      discardRecording.current = true;
      recorder.current?.state === "recording" && recorder.current.stop();
      stream.current?.getTracks().forEach((t) => t.stop());
      if (timer.current) clearInterval(timer.current);
      audio.current?.pause();
      const retiredRoom = liveRoom.current;
      liveRoom.current = null;
      void retiredRoom?.disconnect();
      if (audioUrl.current) URL.revokeObjectURL(audioUrl.current);
    };
  }, [slug]);
  useEffect(() => {
    sessionRef.current = session;
  }, [session]);
  useEffect(() => {
    listEnd.current?.scrollIntoView({
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : messages.length > 2
          ? "smooth"
          : "auto",
      block: "end",
    });
  }, [messages, busy, booking, offers, handoffMessage, error]);
  useEffect(() => {
    const stop = () => {
      if (document.hidden && recorder.current?.state === "recording")
        recorder.current.stop();
    };
    document.addEventListener("visibilitychange", stop);
    return () => document.removeEventListener("visibilitychange", stop);
  }, []);
  async function refreshNotice() {
    setBusy(true);
    setConsent(false);
    try {
      const updated = await api<PublicClinic>(
        `/public/clinics/${encodeURIComponent(slug)}`,
        { token: null },
      );
      if (!alive.current) return;
      setClinic(updated);
      setNoticeRefreshRequired(false);
      setError(
        "اطلاعیهٔ حریم خصوصی تغییر کرده است. لطفاً متن تازه را بخوانید و در صورت موافقت، دوباره انتخاب کنید.",
      );
    } catch (e) {
      if (alive.current)
        setError(
          "اطلاعیهٔ تازه دریافت نشد. پیش از شروع گفتگو، دریافت دوبارهٔ اطلاعیه را انتخاب کنید. " +
            errorText(e),
        );
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  const noticeReady =
    !!clinic &&
    /^[a-f0-9]{64}$/.test(clinic.processing_notice_fingerprint || "") &&
    !noticeRefreshRequired;
  async function start() {
    if (!consent || !clinic || !noticeReady || busy) return;
    setBusy(true);
    setError("");
    try {
      const created = await post<VoiceSession>(
        "/public/sessions",
        {
          clinic_slug: slug,
          processing_consent: true,
          processing_notice_fingerprint: clinic.processing_notice_fingerprint,
          recording_consent: false,
          training_consent: false,
        },
        null,
      );
      if (!alive.current) return;
      ending.current = false;
      receivedTurns.current.clear();
      setFailedAudio(null);
      setSession(created);
      sessionRef.current = created;
      setMessages([{ id: newId(), role: "assistant", text: created.greeting }]);
      setEnded(false);
      setState("ACTIVE");
      setBooking(null);
      setFailedTurn(null);
      setHandoffMessage("");
    } catch (e) {
      if (!alive.current) return;
      if (e instanceof ApiError && e.code === "PROCESSING_NOTICE_CHANGED") {
        setConsent(false);
        setNoticeRefreshRequired(true);
        await refreshNotice();
      } else setError(errorText(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  function receive(result: VoiceTurn) {
    if (ending.current || !sessionRef.current) return;
    if (result.turn_id && receivedTurns.current.has(result.turn_id)) return;
    if (result.turn_id) receivedTurns.current.add(result.turn_id);
    setMessages((old) => [
      ...old,
      {
        id: newId(),
        role: "assistant",
        text: result.reply,
        turn_id: result.turn_id,
      },
    ]);
    setState(result.state);
    setOffers(result.offers || []);
    if (result.booking) setBooking(result.booking);
    if (result.payment_terms) setPaymentTerms(result.payment_terms);
    if (result.capabilities)
      setSession((old) =>
        old ? { ...old, capabilities: result.capabilities! } : old,
      );
    if (result.handoff)
      setHandoffMessage(
        "درخواست شما برای تیم پذیرش ثبت شده است. اتصال زنده تنها پس از پاسخ همکار انجام می‌شود.",
      );
  }
  async function connectLive() {
    const current = sessionRef.current;
    if (!current?.capabilities.livekit || liveActive || liveRoom.current)
      return;
    const attempt = ++liveAttempt.current;
    let connectedRoom: Room | null = null;
    const ownsAttempt = () =>
      alive.current &&
      !ending.current &&
      liveAttempt.current === attempt &&
      sessionRef.current?.session_id === current.session_id;
    setLiveStatus("connecting");
    setLiveMuted(false);
    setLiveMicBusy(false);
    setError("");
    stopPlayback();
    discardRecording.current = true;
    if (recorder.current?.state === "recording") recorder.current.stop();
    try {
      const connection = await post<{
        url: string;
        token: string;
        room: string;
      }>(`/public/sessions/${current.session_id}/livekit`, {}, current.token);
      if (!ownsAttempt()) return;
      const { Room, RoomEvent } = await import("livekit-client");
      if (!ownsAttempt()) return;
      const room = new Room({ adaptiveStream: true, dynacast: true });
      connectedRoom = room;
      liveRoom.current = room;
      const ownsRoom = () => ownsAttempt() && liveRoom.current === room;
      let microphoneReady = false;
      const updateStatus = (status: RtcStatus) => {
        if (!ownsRoom()) return;
        setLiveStatus(
          status === "connected" && !microphoneReady ? "connecting" : status,
        );
        if (status === "connected" && microphoneReady)
          setLiveMuted(!room.localParticipant.isMicrophoneEnabled);
        if (status === "disconnected") {
          liveRoom.current = null;
          setLiveMuted(false);
          setLiveMicBusy(false);
          liveAudio.current?.replaceChildren();
        }
      };
      observeRoomLifecycle(room, RoomEvent, ownsRoom, updateStatus);
      room.on(RoomEvent.TrackSubscribed, (track, _publication, participant) => {
        const trusted =
          participant.identity === `agent-${current.session_id}` ||
          participant.identity.startsWith("staff-");
        if (ownsRoom() && track.kind === "audio" && trusted) {
          const element = track.attach();
          element.setAttribute("playsinline", "");
          liveAudio.current?.appendChild(element);
        }
      });
      room.on(RoomEvent.TrackUnsubscribed, (track) =>
        track.detach().forEach((element) => element.remove()),
      );
      room.on(RoomEvent.DataReceived, (payload, participant, _kind, topic) => {
        if (
          !ownsRoom() ||
          topic !== "reception.turn" ||
          participant?.identity !== `agent-${current.session_id}` ||
          payload.length > 65536
        )
          return;
        try {
          const result = JSON.parse(
            new TextDecoder().decode(payload),
          ) as VoiceTurn;
          if (
            typeof result.reply !== "string" ||
            typeof result.state !== "string"
          )
            return;
          if (result.turn_id && receivedTurns.current.has(result.turn_id))
            return;
          if (typeof result.transcript === "string" && result.transcript) {
            setMessages((old) => [
              ...old,
              { id: newId(), role: "user", text: result.transcript! },
            ]);
          }
          receive(result);
        } catch {
          /* Malformed room data never changes a booking or renders as markup. */
        }
      });
      await room.connect(connection.url, connection.token);
      if (!ownsRoom()) {
        await room.disconnect();
        return;
      }
      await room.localParticipant.setMicrophoneEnabled(true);
      if (!ownsRoom()) {
        await room.disconnect();
        return;
      }
      microphoneReady = true;
      updateStatus(room.state);
    } catch (e) {
      if (ownsAttempt()) {
        liveRoom.current = null;
        setLiveStatus("disconnected");
        setLiveMicBusy(false);
        setError(
          e instanceof DOMException && e.name === "NotAllowedError"
            ? "برای تماس زنده، اجازهٔ میکروفون لازم است. می‌توانید گفتگو را با نوشتن ادامه دهید."
            : "تماس زنده برقرار نشد. گفتگو با نوشتن پیام همچنان در دسترس است.",
        );
      }
      await connectedRoom?.disconnect();
    }
  }
  async function toggleLiveMic() {
    const room = liveRoom.current;
    if (!room || room.state !== "connected" || !liveConnected || liveMicBusy)
      return;
    setLiveMicBusy(true);
    try {
      await room.localParticipant.setMicrophoneEnabled(liveMuted);
      if (alive.current && liveRoom.current === room)
        setLiveMuted(!room.localParticipant.isMicrophoneEnabled);
      else await room.disconnect();
    } catch {
      if (alive.current && liveRoom.current === room)
        setError("تغییر وضعیت میکروفون ممکن نشد.");
    } finally {
      if (alive.current && liveRoom.current === room) setLiveMicBusy(false);
    }
  }
  async function disconnectLive() {
    liveAttempt.current++;
    const room = liveRoom.current;
    liveRoom.current = null;
    setLiveStatus("disconnected");
    setLiveMuted(false);
    setLiveMicBusy(false);
    liveAudio.current?.replaceChildren();
    await room?.disconnect();
  }
  async function send(text: string, retry?: { id: string; text: string }) {
    const current = sessionRef.current;
    if (
      !current ||
      !text.trim() ||
      busy ||
      ended ||
      ending.current ||
      liveActive ||
      failedAudio
    )
      return;
    stopPlayback();
    setBusy(true);
    setError("");
    const request = retry || { text: text.trim(), id: newId() };
    if (!retry)
      setMessages((old) => [
        ...old,
        { id: request.id, role: "user", text: request.text },
      ]);
    setDraft("");
    const controller = new AbortController();
    requestAbort.current = controller;
    try {
      const result = await api<VoiceTurn>(
        `/public/sessions/${current.session_id}/turn`,
        {
          method: "POST",
          body: JSON.stringify({ text: request.text, request_id: request.id }),
          token: current.token,
          signal: controller.signal,
        },
      );
      if (alive.current) {
        receive(result);
        setFailedTurn(null);
      }
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(errorText(e));
        setFailedTurn(request);
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  function submit(e: FormEvent) {
    e.preventDefault();
    void send(draft);
  }
  function stopPlayback() {
    speechRequest.current++;
    speechAbort.current?.abort();
    audio.current?.pause();
    setSpeaking(false);
  }
  async function speak(message: ChatMessage, slow = false) {
    const current = sessionRef.current;
    if (
      !current ||
      liveActive ||
      !message.turn_id ||
      !current.capabilities.audio_output
    )
      return;
    stopPlayback();
    const sequence = speechRequest.current;
    const controller = new AbortController();
    speechAbort.current = controller;
    rate.current = slow ? 0.8 : 1;
    setError("");
    try {
      const response = await fetch(
        apiUrl(
          `/api/v1/public/sessions/${current.session_id}/speech?turn_id=${encodeURIComponent(message.turn_id)}`,
        ),
        {
          headers: { Authorization: `Bearer ${current.token}` },
          signal: controller.signal,
          credentials: "omit",
          cache: "no-store",
          redirect: "error",
        },
      );
      if (!response.ok)
        throw new Error(
          "پخش صدا فعلاً در دسترس نیست. متن پاسخ در گفتگو قابل مشاهده است.",
        );
      const blob = await response.blob();
      if (!blob.type.startsWith("audio/") || blob.size <= 44)
        throw new Error(
          "پاسخ صوتی کامل دریافت نشد. می‌توانید متن را بخوانید یا دوباره تلاش کنید.",
        );
      if (
        !alive.current ||
        ending.current ||
        speechRequest.current !== sequence ||
        sessionRef.current?.session_id !== current.session_id
      )
        return;
      if (audioUrl.current) URL.revokeObjectURL(audioUrl.current);
      audioUrl.current = URL.createObjectURL(blob);
      audio.current = new Audio(audioUrl.current);
      audio.current.playbackRate = rate.current;
      audio.current.onended = () => setSpeaking(false);
      await audio.current.play();
      setSpeaking(true);
    } catch (e) {
      if (!controller.signal.aborted)
        setError(
          e instanceof Error && /[\u0600-\u06ff]/.test(e.message)
            ? e.message
            : "پخش صدا ممکن نشد. متن پاسخ در گفتگو قابل مشاهده است.",
        );
    }
  }
  async function sendAudio(request: { blob: Blob; id: string }) {
    const current = sessionRef.current;
    if (!current || ending.current) return;
    setBusy(true);
    setError("");
    const controller = new AbortController();
    requestAbort.current = controller;
    try {
      const response = await api<VoiceTurn>(
        `/public/sessions/${current.session_id}/audio`,
        {
          method: "POST",
          body: request.blob,
          headers: {
            "Content-Type": request.blob.type,
            "X-Request-ID": request.id,
          },
          token: current.token,
          signal: controller.signal,
        },
      );
      if (
        alive.current &&
        !ending.current &&
        sessionRef.current?.session_id === current.session_id
      ) {
        setMessages((old) => [
          ...old,
          {
            id: request.id,
            role: "user",
            text: response.transcript || "پیام صوتی",
          },
        ]);
        receive(response);
        setFailedAudio(null);
        if (current.capabilities.audio_output)
          void speak({
            id: response.turn_id,
            role: "assistant",
            text: response.reply,
            turn_id: response.turn_id,
          });
      }
    } catch (e) {
      if (!controller.signal.aborted) {
        setError(errorText(e));
        // Preserve the exact in-memory request after an uncertain result, never record it to storage.
        if (!(
          e instanceof ApiError &&
          e.status >= 400 &&
          e.status < 500 &&
          e.status !== 408
        ))
          setFailedAudio(request);
        else setFailedAudio(null);
      }
    } finally {
      if (alive.current) setBusy(false);
    }
  }
  async function startRecording() {
    const current = sessionRef.current;
    if (
      !current?.capabilities.audio_input ||
      busy ||
      ended ||
      ending.current ||
      liveActive ||
      openingMicrophone.current ||
      failedAudio
    )
      return;
    stopPlayback();
    setError("");
    if (
      !navigator.mediaDevices?.getUserMedia ||
      typeof MediaRecorder === "undefined"
    ) {
      setError(
        "مرورگر شما از ضبط صدا پشتیبانی نمی‌کند. از نوشتن پیام استفاده کنید.",
      );
      return;
    }
    openingMicrophone.current = true;
    setMicrophonePending(true);
    try {
      const media = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          channelCount: 1,
        },
      });
      if (
        !alive.current ||
        ending.current ||
        sessionRef.current?.session_id !== current.session_id
      ) {
        media.getTracks().forEach((t) => t.stop());
        return;
      }
      stream.current = media;
      const mime = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4"].find(
        (t) => MediaRecorder.isTypeSupported(t),
      );
      const rec = new MediaRecorder(media, mime ? { mimeType: mime } : {});
      recorder.current = rec;
      const chunks: BlobPart[] = [];
      discardRecording.current = false;
      rec.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data);
      };
      rec.onstop = async () => {
        media.getTracks().forEach((t) => t.stop());
        stream.current = null;
        recorder.current = null;
        if (timer.current) clearInterval(timer.current);
        if (alive.current) setRecording(false);
        if (discardRecording.current || !alive.current || !chunks.length)
          return;
        await sendAudio({
          blob: new Blob(chunks, { type: rec.mimeType }),
          id: newId(),
        });
      };
      rec.start();
      setRecording(true);
      setRecordSeconds(0);
      let seconds = 0;
      timer.current = setInterval(() => {
        seconds++;
        setRecordSeconds(seconds);
        if (seconds >= 60 && rec.state === "recording") rec.stop();
      }, 1000);
    } catch (e) {
      setError(
        e instanceof DOMException && e.name === "NotAllowedError"
          ? "دسترسی به میکروفون داده نشد. می‌توانید اجازهٔ مرورگر را تغییر دهید یا پیام خود را بنویسید."
          : "میکروفون در دسترس نیست. لطفاً پیام خود را بنویسید.",
      );
      stream.current?.getTracks().forEach((t) => t.stop());
    } finally {
      openingMicrophone.current = false;
      if (alive.current) setMicrophonePending(false);
    }
  }
  async function human() {
    const current = sessionRef.current;
    if (!current || ended || ending.current) return;
    discardRecording.current = true;
    if (recorder.current?.state === "recording") recorder.current.stop();
    stream.current?.getTracks().forEach((t) => t.stop());
    setError("");
    try {
      const result = await post<{ reply?: string; status?: string }>(
        `/public/sessions/${current.session_id}/handoff`,
        { reason: "caller_request" },
        current.token,
      );
      const text =
        result.reply ||
        "درخواست همراهی انسانی ثبت شد. تیم پذیرش باید درخواست را دریافت و پیگیری کند.";
      setHandoffMessage(text);
      setOffers([]);
      setMessages((old) => [...old, { id: newId(), role: "assistant", text }]);
    } catch (e) {
      setError(errorText(e));
    }
  }
  async function end() {
    const current = sessionRef.current;
    if (!current || ending.current) return;
    ending.current = true;
    setFailedAudio(null);
    setFailedTurn(null);
    requestAbort.current?.abort();
    discardRecording.current = true;
    if (recorder.current?.state === "recording") recorder.current.stop();
    stream.current?.getTracks().forEach((t) => t.stop());
    stopPlayback();
    await disconnectLive();
    setBusy(true);
    setError("");
    try {
      await post(
        `/public/sessions/${current.session_id}/end`,
        {},
        current.token,
      );
      setEnded(true);
      setSession(null);
      sessionRef.current = null;
      setState("ENDED");
    } catch (e) {
      ending.current = false;
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const lastReply = [...messages].reverse().find((m) => m.role === "assistant");
  const displayName = clinic?.identity?.brand_name || clinic?.name;
  const brandColor = /^#[0-9a-fA-F]{6}$/.test(
    clinic?.identity?.brand_color || "",
  )
    ? clinic!.identity!.brand_color
    : "#668d55";
  return (
    <div
      className="talk-page"
      style={{ "--clinic-accent": brandColor } as CSSProperties}
    >
      <header className="talk-topbar">
        <Brand />
        <a href="/" className="talk-admin">
          ورود همکاران
          <ArrowLeft size={15} />
        </a>
      </header>
      <main className="talk-main">
        {loading ? (
          <section className="talk-intro">
            <Loading rows={4} />
          </section>
        ) : !clinic ? (
          <section className="talk-intro">
            <Alert>{error || "پذیرش این مرکز پیدا نشد."}</Alert>
            <a className="button secondary" href="/">
              بازگشت
            </a>
          </section>
        ) : !session && !ended ? (
          <section className="talk-intro">
            <div className="talk-orb" aria-hidden="true">
              <Waves size={49} />
              <span className="orb-ring" />
            </div>
            <span className="eyebrow">پذیرش آنلاین {displayName}</span>
            <h1>
              سلام، خوش آمدید.
              <br />
              چطور می‌توانیم کمک کنیم؟
            </h1>
            <p className="talk-intro-copy">
              برای هماهنگی نوبت، ساعت کاری یا نشانی مرکز، با دستیار پذیرش گفتگو
              کنید. هر زمان بخواهید می‌توانید همراهی انسانی درخواست کنید.
            </p>
            <div className="talk-features">
              <span>
                <Check size={16} />
                هماهنگی نوبت
              </span>
              <span>
                <Check size={16} />
                پاسخ به پرسش‌ها
              </span>
              <span>
                <Check size={16} />
                درخواست پیگیری
              </span>
            </div>
            <div className="consent-box">
              <ShieldCheck size={23} />
              <div>
                <strong>انتخاب‌های شما روشن است</strong>
                <ConversationPrivacyNotice clinic={clinic} />
                <label className="check-field">
                  <input
                    type="checkbox"
                    checked={consent}
                    disabled={!noticeReady || busy}
                    onChange={(e) => setConsent(e.target.checked)}
                  />
                  <span>با پردازش گفتگو برای دریافت خدمات پذیرش موافقم.</span>
                </label>
              </div>
            </div>
            {paymentTerms?.enabled && (
              <PaymentTermsDetails terms={paymentTerms} />
            )}
            {paymentTermsError && (
              <p className="field-hint">
                شرایط مالی مرکز دریافت نشد. پیش از هر پرداخت، شرایط را از پذیرش
                دریافت کنید.
              </p>
            )}
            {error && <Alert>{error}</Alert>}
            {!noticeReady && (
              <div className="stack">
                <Alert>
                  برای شروع گفتگو، دریافت اطلاعیهٔ معتبر حریم خصوصی لازم است.
                </Alert>
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => void refreshNotice()}
                >
                  دریافت دوبارهٔ اطلاعیه
                </button>
              </div>
            )}
            <button
              className="button primary start-talk"
              disabled={!consent || busy || !noticeReady}
              onClick={() => void start()}
            >
              <Busy busy={busy}>
                <MessageCircle size={20} />
                شروع گفتگو
              </Busy>
            </button>
            <p className="talk-smallprint">
              گفتگو جایگزین مشاورهٔ پزشکی یا خدمات اورژانس نیست.
            </p>
            {clinic.phone && (
              <a className="clinic-contact" href={`tel:${clinic.phone}`}>
                <Phone size={17} />
                تماس مستقیم با مرکز<span dir="ltr">{clinic.phone}</span>
              </a>
            )}
            {clinic.address && (
              <p className="clinic-address">
                <MapPin size={16} />
                {clinic.address}
              </p>
            )}
          </section>
        ) : (
          <section className="conversation">
            <header className="conversation-header">
              <span className="agent-avatar">
                <Waves size={23} />
              </span>
              <div>
                <h1>پذیرش {displayName}</h1>
                <span role="status" aria-live="polite">
                  <span
                    className={`live-dot ${ended || liveStatus === "disconnected" ? "ended" : liveConnecting || liveReconnecting ? "recovering" : ""}`}
                  />
                  {ended
                    ? "گفتگو پایان یافته است"
                    : liveReconnecting
                      ? "در حال برقراری دوبارهٔ تماس…"
                      : liveConnecting
                        ? "در حال برقراری تماس…"
                        : liveConnected
                          ? "تماس زنده برقرار است"
                          : liveStatus === "disconnected"
                            ? "تماس زنده قطع شده است"
                            : busy
                              ? "در حال بررسی درخواست شما…"
                              : "دستیار هوشمند پذیرش"}
                </span>
              </div>
              {!ended && (
                <button className="button end-talk" onClick={() => void end()}>
                  <PhoneOff size={17} />
                  پایان
                </button>
              )}
            </header>
            <div
              className="conversation-terms"
              tabIndex={0}
              role="region"
              aria-label="حریم خصوصی و شرایط مرکز؛ برای خواندن متن پیمایش کنید"
            >
              <details className="payment-terms">
                <summary>حریم خصوصی و نگهداری گفتگو</summary>
                <ConversationPrivacyNotice clinic={clinic} />
              </details>
              {paymentTerms?.enabled && (
                <PaymentTermsDetails terms={paymentTerms} />
              )}
            </div>
            <div
              className="conversation-body"
              tabIndex={0}
              role="region"
              aria-label="پیام‌های گفتگو؛ برای خواندن پیام‌های پیشین پیمایش کنید"
            >
              <div className="conversation-date">
                این گفتگو فقط برای پذیرش مرکز است
              </div>
              <div
                className="messages"
                role="log"
                aria-live="polite"
                aria-relevant="additions"
                aria-label="گفتگو با پذیرش"
              >
                {messages.map((message) => (
                  <div
                    className={`chat-message ${message.role}`}
                    key={message.id}
                  >
                    {message.role === "assistant" && (
                      <span className="chat-avatar">
                        <Waves size={17} />
                      </span>
                    )}
                    <div className="chat-bubble">
                      <p>{message.text}</p>
                      {message.role === "assistant" &&
                        message.turn_id &&
                        session?.capabilities.audio_output && (
                          <button
                            className="message-audio"
                            aria-label="شنیدن این پاسخ"
                            disabled={liveActive}
                            onClick={() => void speak(message)}
                          >
                            <Volume2 size={15} />
                            شنیدن پاسخ
                          </button>
                        )}
                    </div>
                  </div>
                ))}
                {busy && (
                  <div className="chat-message assistant">
                    <span className="chat-avatar">
                      <Waves size={17} />
                    </span>
                    <div
                      className="typing-indicator"
                      role="status"
                      aria-label="در حال بررسی"
                    >
                      <span />
                      <span />
                      <span />
                    </div>
                  </div>
                )}
              </div>
              {offers.length > 0 && !ended && (
                <div className="offered-times" aria-label="زمان‌های پیشنهادی">
                  {offers.map((offer, index) => (
                    <button
                      key={offer.slot_id}
                      className="button secondary"
                      disabled={
                        busy || !!failedTurn || !!failedAudio || liveActive
                      }
                      onClick={() => void send(String(index + 1))}
                    >
                      {offer.display}
                    </button>
                  ))}
                </div>
              )}
              {booking && (
                <div className="confirmed-booking">
                  <CheckCircle2 size={24} />
                  <div>
                    <strong>نتیجهٔ درخواست نوبت</strong>
                    <Status value={booking.status} />
                    <p>
                      {booking.jalali_display
                        ? faNumber(booking.jalali_display)
                        : `${faNumber(booking.local_date)}${booking.local_time ? ` · ${faNumber(booking.local_time)}` : ""}`}
                    </p>
                    <span>
                      کد پیگیری: <bdi>{booking.reference}</bdi>
                    </span>
                    {booking.status === "PENDING_PAYMENT" && (
                      <small>
                        نوبت هنوز قطعی نیست و به پرداخت نیاز دارد.
                        {booking.payment_expires_at &&
                          ` مهلت پرداخت: ${faDate(booking.payment_expires_at, true)}.`}
                      </small>
                    )}
                    {booking.status === "PENDING_STAFF_APPROVAL" && (
                      <small>
                        نوبت هنوز قطعی نیست و به بررسی پذیرش نیاز دارد.
                      </small>
                    )}
                    {booking.payment_terms && (
                      <PaymentTermsDetails terms={booking.payment_terms} />
                    )}
                  </div>
                </div>
              )}
              {handoffMessage && <Alert kind="info">{handoffMessage}</Alert>}
              {error && <Alert onClose={() => setError("")}>{error}</Alert>}
              {failedTurn && (
                <button
                  className="button secondary"
                  disabled={busy}
                  onClick={() => void send(failedTurn.text, failedTurn)}
                >
                  تلاش دوباره برای همان درخواست
                </button>
              )}
              {failedAudio && (
                <div>
                  <Alert kind="info">
                    نتیجهٔ ارسال صوت روشن نیست. همین پیام فقط تا پایان این گفتگو
                    در حافظهٔ موقت مرورگر می‌ماند؛ با تلاش مجدد همان درخواست
                    پیگیری می‌شود.
                  </Alert>
                  <button
                    className="button secondary"
                    disabled={busy}
                    onClick={() => void sendAudio(failedAudio)}
                  >
                    تلاش دوباره برای همان پیام صوتی
                  </button>
                </div>
              )}
              <div ref={listEnd} />
            </div>
            {ended ? (
              <div className="conversation-ended">
                <CheckCircle2 size={22} />
                <p>گفتگو پایان یافت. ممنون که با ما همراه بودید.</p>
                <button
                  className="button primary"
                  onClick={() => {
                    setEnded(false);
                    setMessages([]);
                    setError("");
                  }}
                >
                  شروع گفتگوی جدید
                </button>
              </div>
            ) : (
              <div className="conversation-controls">
                <div ref={liveAudio} />
                {(session?.capabilities.livekit || liveActive) && (
                  <div className="live-voice-controls">
                    {liveActive ? (
                      <>
                        <span className="live-voice-label">
                          <Radio size={16} />
                          {liveConnected
                            ? "تماس زنده"
                            : liveReconnecting
                              ? "در حال اتصال دوباره…"
                              : "در حال اتصال…"}
                        </span>
                        <button
                          className="button secondary small"
                          disabled={!liveConnected || liveMicBusy}
                          onClick={() => void toggleLiveMic()}
                        >
                          {liveMuted ? <Mic size={15} /> : <MicOff size={15} />}
                          {liveMuted ? "فعال‌کردن صدا" : "بی‌صدا کردن"}
                        </button>
                        <button
                          className="button secondary small"
                          onClick={() => void disconnectLive()}
                        >
                          <PhoneOff size={15} />
                          ادامه با نوشتن
                        </button>
                      </>
                    ) : (
                      <>
                        <button
                          className="button primary small"
                          disabled={
                            busy ||
                            recording ||
                            liveConnecting ||
                            microphonePending ||
                            !!failedTurn ||
                            !!failedAudio
                          }
                          onClick={() => void connectLive()}
                        >
                          <Busy busy={liveConnecting}>
                            <Mic size={16} />
                            شروع تماس زنده
                          </Busy>
                        </button>
                        <small>با شروع تماس، میکروفون شما فعال می‌شود.</small>
                      </>
                    )}
                  </div>
                )}
                <div className="conversation-shortcuts">
                  <button onClick={() => void human()}>
                    <Headphones size={16} />
                    همراهی انسانی
                  </button>
                  <button
                    onClick={() => {
                      if (lastReply)
                        setMessages((old) => [
                          ...old,
                          { ...lastReply, id: newId() },
                        ]);
                    }}
                    disabled={!lastReply || busy}
                  >
                    تکرار پاسخ
                  </button>
                  {session?.capabilities.audio_output && (
                    <button
                      onClick={() => lastReply && void speak(lastReply, true)}
                      disabled={busy || liveActive}
                    >
                      آهسته‌تر
                    </button>
                  )}
                  <button
                    onClick={() => void send("اصلاح اطلاعات")}
                    disabled={
                      busy || !!failedTurn || !!failedAudio || liveActive
                    }
                  >
                    اصلاح اطلاعات
                  </button>
                  {speaking && (
                    <button onClick={stopPlayback}>
                      <VolumeX size={15} />
                      توقف صدا
                    </button>
                  )}
                </div>
                <form className="chat-composer" onSubmit={submit}>
                  <input
                    value={draft}
                    maxLength={2000}
                    onChange={(e) => setDraft(e.target.value)}
                    placeholder="پیام خود را بنویسید…"
                    aria-label="پیام شما"
                    disabled={
                      busy ||
                      recording ||
                      microphonePending ||
                      !!failedTurn ||
                      !!failedAudio ||
                      liveActive
                    }
                    autoComplete="off"
                  />
                  <button
                    type="button"
                    className={`mic-button ${recording ? "recording" : ""}`}
                    disabled={
                      !session?.capabilities.audio_input ||
                      busy ||
                      !!failedTurn ||
                      !!failedAudio ||
                      microphonePending ||
                      liveActive
                    }
                    onClick={() => {
                      if (recording) recorder.current?.stop();
                      else void startRecording();
                    }}
                    aria-label={
                      recording ? "پایان ضبط و ارسال" : "ضبط پیام صوتی"
                    }
                    title={
                      session?.capabilities.audio_input
                        ? "ضبط پیام صوتی"
                        : "دریافت صدا برای این مرکز هنوز فعال نیست"
                    }
                  >
                    {recording ? <Square size={18} /> : <Mic size={21} />}
                  </button>
                  <button
                    className="send-button"
                    disabled={
                      busy ||
                      recording ||
                      !draft.trim() ||
                      !!failedTurn ||
                      !!failedAudio ||
                      microphonePending ||
                      liveActive
                    }
                    aria-label="ارسال پیام"
                  >
                    <Send size={19} />
                  </button>
                </form>
                {recording ? (
                  <p className="recording-hint">
                    <span className="record-dot" />
                    {faNumber(recordSeconds)} ثانیه · برای ارسال، دکمهٔ توقف را
                    بزنید. حداکثر یک دقیقه.
                  </p>
                ) : (
                  <p className="audio-capability-note">
                    {liveReconnecting
                      ? "ارتباط تماس در حال بازیابی است. می‌توانید منتظر بمانید یا «ادامه با نوشتن» را بزنید."
                      : liveActive
                        ? "برای نوشتن پیام، گزینهٔ «ادامه با نوشتن» را بزنید."
                        : session?.capabilities.audio_input
                          ? "برای پیام صوتی، میکروفون را انتخاب کنید. متن همیشه در دسترس است."
                          : "فعلاً از نوشتن پیام استفاده کنید؛ دریافت صدا برای این مرکز فعال نشده است."}
                  </p>
                )}
              </div>
            )}
            <span className="sr-only" role="status">
              {state === "ENDED" ? "گفتگو پایان یافت" : ""}
            </span>
          </section>
        )}
      </main>
      <footer className="talk-footer">
        همراه تیم پذیرش شما <span>·</span> هم‌آوا
      </footer>
    </div>
  );
}
