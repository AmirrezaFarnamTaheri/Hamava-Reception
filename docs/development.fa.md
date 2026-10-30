# راهنمای توسعه‌دهنده و نگهدارنده

[English](development.md) | [مستندات](README.fa.md)

## پوشه‌ها و ابزارها

سرور با Python **3.12** و وابستگی‌های قفل‌شده در `requirements.lock.txt` ساخته می‌شود. برای وب و میزبان‌های بومی، Node **24** و فایل‌های قفل npm هر پوشه لازم است. ساختار پروژه شامل `backend/receptionist/` (سرویس)، `backend/tests/` (آزمون)، `frontend/` (رابط و آزمون مرورگر)، `apps/desktop/` و `apps/mobile/` (میزبان بومی)، `services/local_speech/` (گفتار اختیاری)، `scripts/` (نگهداری/پژوهش) و `deploy/` (قالب زیرساخت) است.

برای توسعه از پایگاه مرکز واقعی یا حساب تأمین‌کنندهٔ عملیاتی استفاده نکنید. فایل `.env.example`، داده‌های ساختگی، SQLite جداگانه یا PostgreSQL مخصوص آزمون را به‌کار ببرید. اسرار، دادهٔ بیمار، بستهٔ اجرایی و خروجی تولیدشده وارد Git نشوند.

## آزمون‌ها

پس از نصب وابستگی‌ها، از ریشه اجرا کنید:

~~~sh
python -m ruff check backend scripts services
python -m pytest -q
python scripts/protocol_conformance.py --output artifacts/backend/protocol-conformance.json
npm --prefix frontend ci --ignore-scripts
npm --prefix frontend run build
npm --prefix frontend run test:browser-launch
python scripts/ci_ui.py test:ui test:workflows test:conversation test:extensions test:release test:outreach test:waitlist-deposit test:privacy-notice test:rtc-lifecycle test:companion test:platform test:latency-labels
npm --prefix apps/desktop test
node scripts/check-versions.mjs
node scripts/check-docs.mjs
node --test scripts/check-docs.test.mjs
~~~

آزمون مرورگر به نسخهٔ ساخته‌شدهٔ رابط و سرور ساختگی جداگانه نیاز دارد؛ `scripts/ci_ui.py` جداسازی را فراهم می‌کند. ابزارهای فشار PostgreSQL و آزمون استقرار فقط باید با پایگاه **مخصوص آزمون** اجرا شوند. معیار اصلی CI فایل `.github/workflows/verify.yml` است. بدون اجرای واقعی ادعای قبولی آزمون نکنید.

## تغییر کد و پوشش آزمون

برای هر تغییر رفتار ابتدا آزمونی بنویسید که خرابی را نشان دهد، کوچک‌ترین اصلاح را انجام دهید و آزمون هدفمند و سپس مجموعهٔ مرتبط را اجرا کنید. نتیجهٔ کسب‌وکار، مجوزها، هویت تراکنش، ماندگاری و بازگشت در آزمون باید صریح باشند. تغییر برنامهٔ بومی به آزمون پل امنیتی و تغییر صوت به آزمون پروتکل، لغو و هم‌زمانی نیاز دارد.

## مهاجرت و پاکسازی

مسیر مهاجرت عملیاتی `backend/receptionist/migrations.py` برابر **0001 → 0002** است و کد موقت یا منسوخ نیست. ابتدا نویسنده‌ها را متوقف، نسخهٔ پشتیبان تهیه و بازیابی را بررسی کنید؛ سپس مهاجرت و بررسی نسخه و داده‌های حفظ‌شده را انجام دهید. طرح‌وارهٔ ناشناخته را نباید بی‌بررسی ثبت یا جدول را برای گذر آزمون حذف کرد. ابزار مستقل `scripts/migrate_privacy_notes.py` فقط با تصمیم بهره‌بردار اجرا می‌شود و جای مهاجرت اصلی نیست.

فایل JUnit، تصویر مرورگر، گزارش اجرای قدیمی یا ابزار آزمایشی موقت را commit نکنید. خروجی محلی در `artifacts/` و شواهد اختصاصی اجرا در GitHub Actions artifacts بماند. `scripts/make_source_release.py` بستهٔ قطعیِ فقط-کدمنبع با فهرست هش تولید می‌کند.

## سیاست مستندات

برای هر `README.md` نگهداری‌شده یا راهنمای `docs/*.md` نسخهٔ متناظر `.fa.md` لازم است. متن را دقیق ترجمه کنید، کد و مسیرها را ثابت نگه دارید، پیوندها را در هر دو زبان اصلاح و آزمون مستندات را اجرا کنید. اطلاعیه‌های حقوقی مجوزهای فایل و قلم به شکل اصلی می‌مانند. برای پذیرش [عملیات](operations.fa.md) و برای راه‌اندازی [استقرار](deployment.fa.md) را ببینید.
