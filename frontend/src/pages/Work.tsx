import { useState } from "react";
import { MessageSquareText, RefreshCw } from "lucide-react";
import { errorText, faDate, faNumber, post } from "../api";
import {
  Alert,
  Busy,
  Empty,
  Loading,
  PageTitle,
  Retry,
  Status,
} from "../components";
import { useRemote } from "../hooks";
import type { Notice } from "../types";

function purposeLabel(purpose: string) {
  const v = purpose.toLowerCase();
  if (v.includes("cancel")) return "اطلاع‌رسانی لغو";
  if (v.includes("remind")) return "یادآوری نوبت";
  if (v.includes("verify") || v.includes("otp")) return "تأیید شماره";
  if (v.includes("waitlist")) return "پیشنهاد زمان آزاد";
  if (v.includes("payment")) return "هماهنگی پرداخت";
  return "اطلاع‌رسانی نوبت";
}

export function Notifications() {
  const notices = useRemote<Notice[]>("/notifications", 15000);
  const [filter, setFilter] = useState("");
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const filtered =
    notices.data?.filter(
      (n) =>
        !filter ||
        (filter === "attention"
          ? ["FAILED", "UNKNOWN"].includes(n.status)
          : n.status === filter),
    ) || [];
  async function retry(item: Notice) {
    setBusyId(item.id);
    setError("");
    setNotice("");
    try {
      await post(`/operations/notifications/${item.id}/retry`, {});
      notices.refresh();
      setNotice(
        "درخواست بررسی و ارسال مجدد ثبت شد. وضعیت تحویل پس از پاسخ ارائه‌دهنده به‌روزرسانی می‌شود.",
      );
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusyId("");
    }
  }
  return (
    <>
      <PageTitle
        eyebrow="اطلاع‌رسانی به مراجعان"
        title="پیام‌ها"
        description="وضعیت ارسال و تحویل پیام‌ها را مستقل از وضعیت نوبت پیگیری کنید."
        action={
          <button className="button secondary" onClick={notices.refresh}>
            <RefreshCw size={17} />
            تازه‌سازی
          </button>
        }
      />
      {error && <Alert onClose={() => setError("")}>{error}</Alert>}
      {notice && (
        <Alert kind="success" onClose={() => setNotice("")}>
          {notice}
        </Alert>
      )}
      <section className="panel">
        <div className="table-toolbar">
          <div className="toolbar-title">
            <MessageSquareText size={21} />
            <strong>پیام‌های مرکز</strong>
            <span className="count-pill">{faNumber(filtered.length)}</span>
          </div>
          <select
            aria-label="فیلتر وضعیت پیام"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          >
            <option value="">همهٔ وضعیت‌ها</option>
            <option value="attention">نیازمند بررسی</option>
            <option value="QUEUED">در صف</option>
            <option value="SENT">ارسال شده</option>
            <option value="DELIVERED">تحویل داده شده</option>
          </select>
        </div>
        {notices.error ? (
          <Retry error={notices.error} onRetry={notices.refresh} />
        ) : notices.loading ? (
          <Loading rows={4} />
        ) : filtered.length ? (
          <div
            className="table-scroll"
            tabIndex={0}
            role="region"
            aria-label="جدول؛ برای مشاهدهٔ ستون‌های بیشتر پیمایش کنید"
          >
            <table>
              <thead>
                <tr>
                  <th>نوع پیام</th>
                  <th>گیرنده</th>
                  <th>وضعیت</th>
                  <th>تلاش‌ها</th>
                  <th>زمان ایجاد</th>
                  <th>اقدام</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => (
                  <tr key={item.id}>
                    <td>
                      <strong>{purposeLabel(item.purpose)}</strong>
                    </td>
                    <td>
                      <span className="ltr">{item.recipient_masked}</span>
                    </td>
                    <td>
                      <Status value={item.status} />
                    </td>
                    <td>{faNumber(item.attempts)}</td>
                    <td>{faDate(item.created_at, true)}</td>
                    <td>
                      {item.status === "FAILED" ? (
                        <button
                          className="button secondary small"
                          disabled={busyId === item.id}
                          onClick={() => void retry(item)}
                        >
                          <Busy busy={busyId === item.id}>تلاش مجدد</Busy>
                        </button>
                      ) : (
                        <span className="muted">
                          {item.status === "UNKNOWN"
                            ? "نیازمند تطبیق با ارائه‌دهنده"
                            : "—"}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty
            title="پیامی در این بخش نیست"
            description="پیام‌های تأیید، لغو و یادآوری نوبت پس از ثبت، اینجا نمایش داده می‌شوند."
          />
        )}
      </section>
      <div className="note-line">
        <MessageSquareText size={17} />
        <span>
          «ارسال شده» با «تحویل داده شده» متفاوت است. شکست ارسال پیام، نوبت
          تأییدشده را لغو نمی‌کند.
        </span>
      </div>
    </>
  );
}
