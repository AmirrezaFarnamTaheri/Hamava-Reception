"""Deterministic Persian administrative date and identifier handling.

Parsing returns uncertainty; it never creates a calendar event or decides that
an ambiguous hour is a valid appointment. The source calendar remains authority.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import jdatetime

TEHRAN = ZoneInfo("Asia/Tehran")
WEEKDAYS = ("دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه")
MONTHS = ("", "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور", "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند")
DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
NUMBER_WORDS = {"صفر": 0, "یک": 1, "یه": 1, "دو": 2, "سه": 3, "چهار": 4, "چار": 4,
                "پنج": 5, "شش": 6, "شیش": 6, "هفت": 7, "هشت": 8, "نه": 9, "نُه": 9,
                "ده": 10, "یازده": 11, "دوازده": 12, "سیزده": 13, "چهارده": 14,
                "پانزده": 15, "شانزده": 16, "هفده": 17, "هجده": 18, "نوزده": 19,
                "بیست": 20, "سی": 30}
ORDINALS = {"اول": 1, "دوم": 2, "سوم": 3, "چهارم": 4, "پنجم": 5, "ششم": 6,
            "هفتم": 7, "هشتم": 8, "نهم": 9, "دهم": 10, "یازدهم": 11, "دوازدهم": 12,
            "سیزدهم": 13, "چهاردهم": 14, "پانزدهم": 15, "شانزدهم": 16, "هفدهم": 17,
            "هجدهم": 18, "نوزدهم": 19, "بیستم": 20, "سی‌ام": 30, "سی ام": 30}


def normalize_digits(text: str) -> str:
    return str(text).translate(DIGITS)


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", normalize_digits(text))
    text = text.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه").replace("\u200c", " ")
    text = re.sub(r"[\u064b-\u065f\u0670\u200e\u200f\u202a-\u202e\u2066-\u2069]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def spoken_digits(text: str) -> str:
    """Accept only individual digit words; ambiguous compound phone numbers fail."""
    norm = normalize_text(text)
    for word, number in sorted(NUMBER_WORDS.items(), key=lambda x: -len(x[0])):
        if number < 10:
            norm = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", str(number), norm)
    return re.sub(r"[\s\-().]", "", norm)


def normalize_phone(text: str) -> str:
    value = spoken_digits(text)
    if value.startswith("0098"):
        value = "+98" + value[4:]
    if value.startswith("+98"):
        value = "0" + value[3:]
    if not re.fullmatch(r"09\d{9}", value):
        raise ValueError("شماره همراه باید ۱۱ رقم باشد و با ۰۹ شروع شود.")
    return value


def valid_national_id(value: str) -> bool:
    value = normalize_digits(value).strip()
    if not re.fullmatch(r"\d{10}", value) or len(set(value)) == 1:
        return False
    rem = sum(int(value[i]) * (10 - i) for i in range(9)) % 11
    return int(value[-1]) == (rem if rem < 2 else 11 - rem)


def jalali_label(day: date, hour: str | None = None) -> str:
    j = jdatetime.date.fromgregorian(date=day)
    label = f"{WEEKDAYS[day.weekday()]}، {j.day} {MONTHS[j.month]} {j.year}"
    if hour:
        label += f"، ساعت {hour}"
    return label.translate(PERSIAN_DIGITS)


def _number(text: str) -> int | None:
    text = normalize_text(text)
    if text.isdigit():
        return int(text)
    for word, number in ORDINALS.items():
        if text == normalize_text(word):
            return number
    if text in NUMBER_WORDS:
        return NUMBER_WORDS[text]
    parts = re.split(r"\s+و\s+", text)
    if len(parts) == 2:
        a, b = _number(parts[0]), _number(parts[1])
        if a in (20, 30) and b is not None and 0 < b < 10:
            return a + b
    return None


def _clock(phrase: str, shifts: list[tuple[int, int]] | None, time_windows: dict | None = None) -> dict:
    period = next((p for p in ("بعدازظهر", "بعد از ظهر", "غروب", "عصر", "صبح", "شب", "ظهر") if p in phrase), None)
    windows = {"صبح": (6, 12), "ظهر": (12, 15), "بعدازظهر": (12, 19),
               "بعد از ظهر": (12, 19), "عصر": (15, 21), "غروب": (17, 21), "شب": (18, 24)}
    if time_windows is not None:
        if any(key not in windows for key in time_windows):
            raise ValueError("Unsupported fuzzy time label")
        for key, bounds in time_windows.items():
            if len(bounds) != 2 or not 0 <= bounds[0] < bounds[1] <= 24:
                raise ValueError("Invalid fuzzy time bounds")
            windows[key] = tuple(bounds)
        if "بعدازظهر" in time_windows:
            windows["بعد از ظهر"] = tuple(time_windows["بعدازظهر"])
    match = re.search(r"ساعت\s+(.+)", phrase)
    fragment = match.group(1) if match else phrase
    digit_match = re.search(r"(?<![\d/\-])([01]?\d|2[0-3]):([0-5]\d)(?!\d)", fragment)
    hour = minute = None
    explicit_24 = False
    if digit_match:
        hour, minute = int(digit_match[1]), int(digit_match[2])
        explicit_24 = hour > 12 or hour == 0
    elif match:
        token = re.match(r"(\d{1,2}|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")(?!\w)", fragment)
        if token:
            hour, minute = _number(token[1]), 0
    else:
        # Colloquial 'چارشنبه شیش و نیم' is supported without reading date digits as hours.
        token = re.search(r"(?<!\w)(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")\s+و\s+(نیم|ربع)(?!\w)", phrase)
        if token:
            hour, minute = _number(token[1]), 0
    if hour is not None and not 0 <= hour < 24:
        return {"times": [], "time_window": None, "time_ambiguous": True, "invalid_time": True}
    if hour is not None:
        if "و نیم" in fragment:
            minute = 30
        elif "و ربع" in fragment:
            minute = 15
        if "ربع به" in fragment:
            hour, minute = (hour - 1) % 24, 45
        candidates = [hour] if explicit_24 else sorted(set([hour % 12, hour % 12 + 12]))
        if period:
            lower, upper = windows[period]
            candidates = [h for h in candidates if lower <= h + (minute or 0)/60 < upper]
        if shifts:
            candidates = [h for h in candidates if any(lo <= h + (minute or 0) / 60 < hi for lo, hi in shifts)]
        return {"times": [f"{h:02d}:{minute or 0:02d}" for h in candidates],
                "time_window": None, "time_ambiguous": len(candidates) != 1, "invalid_time": not candidates}
    return {"times": [], "time_window": list(windows[period]) if period else None,
            "time_ambiguous": False, "invalid_time": False}


def resolve_persian_datetime(raw_phrase: str, reference_time: datetime,
                             horizon_days: int = 60,
                             shift_hours: list[tuple[int, int]] | None = None,
                             time_windows: dict | None = None) -> dict:
    if reference_time.tzinfo is None or reference_time.utcoffset() is None:
        raise ValueError("reference_time must be timezone-aware")
    if not 1 <= horizon_days <= 366:
        raise ValueError("horizon_days must be between 1 and 366")
    phrase = normalize_text(raw_phrase)
    today = reference_time.astimezone(TEHRAN).date()
    choices: list[date] = []
    reasons: list[str] = []
    inferred_year = False
    earliest = any(word in phrase for word in ("اولین وقت", "زودترین", "هر وقت"))
    numeric = re.search(r"(?<!\d)(\d{4})[-/](\d{1,2})[-/](\d{1,2})(?!\d)", phrase)
    try:
        if numeric:
            y, m, d = map(int, numeric.groups())
            choices = [jdatetime.date(y, m, d).togregorian() if y < 1800 else date(y, m, d)]
        elif any(word in phrase for word in ("پس فردا", "پسفردا")):
            choices = [today + timedelta(days=2)]
        elif "فردا" in phrase:
            choices = [today + timedelta(days=1)]
        elif "امروز" in phrase:
            choices = [today]
        else:
            month_match = next(((i, re.search(rf"(.+?)\s+{month}(?:\s+(\d{{4}}))?(?!\w)", phrase))
                                for i, month in enumerate(MONTHS) if i and re.search(rf"(?<!\w){month}(?!\w)", phrase)), None)
            if month_match and month_match[1]:
                month, match = month_match
                prefix = match[1]
                day_num = None
                for width in (4, 3, 2, 1):
                    candidate = _number(" ".join(prefix.split()[-width:]))
                    if candidate and 1 <= candidate <= 31:
                        day_num = candidate
                        break
                if day_num:
                    year = int(match[2]) if match[2] else jdatetime.date.fromgregorian(date=today).year
                    selected = jdatetime.date(year, month, day_num).togregorian()
                    if not match[2]:
                        inferred_year = True
                        if selected < today:
                            selected = jdatetime.date(year + 1, month, day_num).togregorian()
                    choices = [selected]
            if not choices:
                variants = {"دوشنبه": 0, "دو شنبه": 0, "سه شنبه": 1, "سهشنبه": 1,
                            "چهارشنبه": 2, "چارشنبه": 2, "پنج شنبه": 3, "پنجشنبه": 3,
                            "جمعه": 4, "شنبه": 5, "یکشنبه": 6, "یک شنبه": 6}
                found = next(((name, day) for name, day in sorted(variants.items(), key=lambda x: -len(x[0]))
                              if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", phrase)), None)
                if found:
                    weekday = found[1]
                    upcoming = today + timedelta(days=(weekday - today.weekday()) % 7)
                    if "هفته" in phrase and any(w in phrase for w in ("دیگه", "دیگر", "آینده", "بعد")):
                        saturday = today - timedelta(days=(today.weekday() - 5) % 7)
                        next_week = saturday + timedelta(days=7 + (weekday - 5) % 7)
                        choices = sorted(set([upcoming if upcoming > today else upcoming + timedelta(days=7), next_week]))
                        if len(choices) > 1:
                            reasons.append("next_week_convention")
                    else:
                        choices = [upcoming]
                elif "هفته" in phrase and any(w in phrase for w in ("دیگه", "آینده", "بعد")):
                    start = today - timedelta(days=(today.weekday() - 5) % 7) + timedelta(days=7)
                    choices = [start + timedelta(days=i) for i in range(7)]
                    reasons.append("choose_day")
    except (ValueError, OverflowError):
        reasons.append("invalid_calendar_date")
        choices = []
    if not choices and earliest:
        choices = [today + timedelta(days=i) for i in range(min(14, horizon_days + 1))]
    out_of_range = any(day < today or day > today + timedelta(days=horizon_days) for day in choices)
    choices = [day for day in choices if today <= day <= today + timedelta(days=horizon_days)]
    if out_of_range:
        reasons.append("outside_booking_horizon")
    if not choices:
        reasons.append("date_required")
    if inferred_year:
        reasons.append("year_inferred_confirm")
    clock = _clock(phrase, shift_hours, time_windows)
    if clock["time_ambiguous"]:
        reasons.append("clarify_hour")
    alternatives = [{"local_date": d.isoformat(), "jalali_display": jalali_label(d)} for d in choices]
    return {"timezone": "Asia/Tehran", "reference_time": reference_time.isoformat(),
            "local_date": choices[0].isoformat() if len(choices) == 1 else None,
            "jalali_display": jalali_label(choices[0]) if len(choices) == 1 else None,
            "alternatives": alternatives, "ambiguous": bool(reasons) or (len(choices) > 1 and not earliest),
            "reasons": reasons, "earliest": earliest, "latest": any(word in phrase for word in ("آخر وقت", "آخرین وقت", "آخرین نوبت", "اخر وقت")), "requires_readback": True, **clock}


def generate_shamsi_context(now: datetime, days_ahead: int = 14) -> list[dict]:
    if now.tzinfo is None or not 1 <= days_ahead <= 60:
        raise ValueError("aware now and 1–60 days required")
    today = now.astimezone(TEHRAN).date()
    return [{"local_date": (today + timedelta(days=i)).isoformat(),
             "label": jalali_label(today + timedelta(days=i))} for i in range(days_ahead)]


_UNITS = ("صفر", "یک", "دو", "سه", "چهار", "پنج", "شش", "هفت", "هشت", "نه", "ده", "یازده", "دوازده", "سیزده", "چهارده", "پانزده", "شانزده", "هفده", "هجده", "نوزده")
_TENS = ("", "", "بیست", "سی", "چهل", "پنجاه", "شصت", "هفتاد", "هشتاد", "نود")
_HUNDREDS = ("", "صد", "دویست", "سیصد", "چهارصد", "پانصد", "ششصد", "هفتصد", "هشتصد", "نهصد")
_LETTERS = dict(zip("ABCDEFGHIJKLMNOPQRSTUVWXYZ", ("اِی", "بی", "سی", "دی", "ای", "اِف", "جی", "اِیچ", "آی", "جِی", "کِی", "اِل", "اِم", "اِن", "او", "پی", "کیو", "آر", "اِس", "تی", "یو", "وی", "دبلیو", "اِکس", "وای", "زِد")))


def number_words(value: int) -> str:
    """Lexical Persian integers; never interpret an identifier as an amount."""
    if isinstance(value, bool) or not isinstance(value, int) or abs(value) > 999_999_999_999:
        raise ValueError("Supported integer range is ±999,999,999,999")
    if value < 0:
        return "منفی " + number_words(-value)
    if value < 20:
        return _UNITS[value]
    if value < 100:
        head, tail = divmod(value, 10)
        return _TENS[head] + (" و " + number_words(tail) if tail else "")
    if value < 1000:
        head, tail = divmod(value, 100)
        return _HUNDREDS[head] + (" و " + number_words(tail) if tail else "")
    for scale, label in ((1_000_000_000, "میلیارد"), (1_000_000, "میلیون"), (1000, "هزار")):
        if value >= scale:
            head, tail = divmod(value, scale)
            return ("" if head == 1 and scale == 1000 else number_words(head) + " ") + label + (" و " + number_words(tail) if tail else "")
    raise ValueError("Invalid integer")


def identifier_words(value: str) -> str:
    normalized = normalize_digits(value).upper()
    if not normalized or any(c not in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-+" for c in normalized):
        raise ValueError("Only bounded administrative identifier characters are supported")
    if len(normalized) > 120:
        raise ValueError("Identifier too long")
    return "، ".join(_UNITS[int(c)] if c.isdigit() else _LETTERS[c] if c.isalpha() else "خط تیره" if c == "-" else "مثبت" for c in normalized)


def time_words(value: str) -> str:
    match = re.fullmatch(r"([01]\d|2[0-3]):([0-5]\d)", normalize_digits(value))
    if not match:
        raise ValueError("Clock must be local HH:MM")
    hour, minute = map(int, match.groups())
    return number_words(hour) + (" و " + number_words(minute) + " دقیقه" if minute else " تمام")


def spoken_jalali(day: date, hour: str | None = None) -> str:
    value = jdatetime.date.fromgregorian(date=day)
    label = f"{WEEKDAYS[day.weekday()]}، {number_words(value.day)} {MONTHS[value.month]} {number_words(value.year)}"
    return label + ("، ساعت " + time_words(hour) if hour else "")


def spoken_administrative(text: str) -> str:
    """Render trusted server text for TTS without changing its numeric meaning.

    Money and dates use cardinal words; phones and tracking codes retain every
    digit/letter in order. This function is never applied to user tool arguments.
    """
    value = normalize_digits(text)
    value = re.sub(r"\b(?:B-[A-Fa-f0-9]{8}|DEMO-\d{4})\b", lambda m: identifier_words(m[0]), value)
    value = re.sub(r"(?<!\w)(?:\+98|0098|0)9\d{9}(?!\d)", lambda m: identifier_words(m[0]), value)
    value = re.sub(r"(?<!\d)([01]\d|2[0-3]):([0-5]\d)(?!\d)", lambda m: time_words(m[0]), value)
    value = re.sub(r"(?<!\d)(\d{1,3}(?:[,٬]\d{3})+|\d+)\s*(تومان|ریال)",
                   lambda m: number_words(int(re.sub(r"[,٬]", "", m[1]))) + " " + m[2], value)
    value = re.sub(r"(?<!\d)(\d{6}|\d{10}|\d{11})(?!\d)", lambda m: identifier_words(m[0]), value)
    value = re.sub(r"(?<![\w])\d{1,12}(?!\w)", lambda m: number_words(int(m[0])), value)
    return value


def language_signal(text: str) -> dict:
    """Conservative routing signal, not a language identification quality claim."""
    value = normalize_text(text).casefold()
    english = re.findall(r"\b[a-z]{2,}\b", value)
    en_words = {"hello", "appointment", "cancel", "reschedule", "please", "need", "want", "tomorrow", "doctor", "help", "speak", "book", "thank", "you", "can", "the", "with", "for"}
    ar_cues = ("ارید", "أرید", "موعد", "الغاء", "إلغاء", "طبیب", "عندکم", "من فضلك", "مرحبا", "غدا", "تغییر الموعد")
    ar_count = sum(cue in value for cue in ar_cues)
    fa_count = sum(cue in value for cue in ("می خوا", "میخوا", "فردا", "نوبت", "لطفا", "برای", "هستم", "دارم", "بله"))
    en_count = sum(word in en_words for word in english)
    if en_count >= 2 and fa_count:
        return {"language": "mixed", "confidence": "routing_signal", "requires_clarification": True}
    if en_count >= 2:
        return {"language": "english", "confidence": "routing_signal", "requires_clarification": False}
    if ar_count >= 2 and fa_count:
        return {"language": "mixed", "confidence": "routing_signal", "requires_clarification": True}
    if ar_count >= 2:
        return {"language": "arabic", "confidence": "routing_signal", "requires_clarification": False}
    return {"language": "fa_or_undetermined", "confidence": "not_identified", "requires_clarification": False}
