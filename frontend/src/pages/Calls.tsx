import {
  ArrowUpLeft,
  Headphones,
  MessageSquareText,
  ShieldCheck,
} from "lucide-react";
import { PageTitle } from "../components";
import { LiveCalls } from "../LiveCalls";
import { hasPermission } from "../permissions";
import { publicUrl } from "../platform";
import type { User } from "../types";

export function Calls({
  user,
  clinicSlug,
  navigate,
}: {
  user: User;
  clinicSlug?: string;
  navigate: (path: string) => void;
}) {
  return (
    <>
      <PageTitle
        eyebrow="پشت هر تماس، یک نفر"
        title="تماس‌ها"
        description="گفت‌وگوهای فعال را ببینید و درخواست همراهی را با وضعیت روشن پیگیری کنید."
        action={
          <button
            className="button secondary"
            onClick={() => navigate("/tasks")}
          >
            <Headphones size={18} />
            پیگیری‌های تیم
          </button>
        }
      />
      <LiveCalls canTakeover={hasPermission(user, "task:write")} />
      <div className="calls-guidance">
        <section>
          <ShieldCheck size={24} />
          <div>
            <h2>همراهی، با تأیید اتصال</h2>
            <p>
              وقتی اتصال صوتی آماده باشد، می‌توانید با اجازهٔ میکروفون به تماس
              بپیوندید. در غیر این صورت، درخواست تماس مجدد ثبت می‌شود.
            </p>
          </div>
        </section>
        <section>
          <MessageSquareText size={24} />
          <div>
            <h2>پذیرش آنلاین هم در دسترس است</h2>
            <p>
              مراجعه‌کننده می‌تواند با نوشتن ادامه دهد یا از پذیرش انسانی کمک
              بخواهد.
            </p>
            {clinicSlug && (
              <a
                className="text-link"
                href={publicUrl(`/talk/${clinicSlug}`)}
                target="_blank"
                rel="noreferrer"
              >
                باز کردن پذیرش مرکز
                <ArrowUpLeft size={16} />
              </a>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
