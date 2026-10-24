from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from receptionist.locale import (
    generate_shamsi_context, normalize_phone, normalize_text,
    resolve_persian_datetime, valid_national_id,
)

NOW = datetime(2026, 10, 23, 23, 50, tzinfo=ZoneInfo("Asia/Tehran"))


def test_tehran_jalali_known_reference():
    result = resolve_persian_datetime("۱۴۰۵/۰۸/۰۵", NOW)
    assert result["local_date"] == "2026-10-27"
    assert "سه‌شنبه" in result["jalali_display"]
    assert "آبان" in result["jalali_display"]


def test_tomorrow_and_ambiguous_time():
    result = resolve_persian_datetime("فردا ساعت چهار و نیم", NOW)
    assert result["local_date"] == "2026-10-24"
    assert result["times"] == ["04:30", "16:30"]
    assert result["ambiguous"] is True
    explicit = resolve_persian_datetime("فردا ساعت چهار و نیم بعدازظهر", NOW)
    assert explicit["times"] == ["16:30"]
    assert explicit["requires_readback"] is True


def test_shift_context_does_not_invent_clock():
    result = resolve_persian_datetime("چارشنبه شیش و نیم", NOW, shift_hours=[(16, 20)])
    assert result["local_date"] == "2026-10-28"
    assert result["times"] == ["18:30"]
    evening = resolve_persian_datetime("پس‌فردا غروب", NOW)
    assert evening["local_date"] == "2026-10-25"
    assert evening["times"] == [] and evening["time_window"] == [17, 21]


def test_explicit_and_inferred_jalali_year():
    inferred = resolve_persian_datetime("بیستم آبان", NOW)
    assert inferred["local_date"] == "2026-11-11"
    assert inferred["ambiguous"] and "year_inferred_confirm" in inferred["reasons"]
    explicit = resolve_persian_datetime("بیستم آبان ۱۴۰۵", NOW)
    assert explicit["local_date"] == "2026-11-11"
    assert "year_inferred_confirm" not in explicit["reasons"]


def test_week_convention_returns_alternatives_when_distinct():
    now = datetime(2026, 10, 24, 12, tzinfo=ZoneInfo("Asia/Tehran"))
    result = resolve_persian_datetime("سه شنبه هفته دیگه", now)
    assert [d["local_date"] for d in result["alternatives"]] == ["2026-10-27", "2026-11-03"]
    assert result["ambiguous"]


def test_frozen_reference_before_midnight_is_used():
    result = resolve_persian_datetime("فردا", NOW)
    assert result["local_date"] == "2026-10-24"
    with pytest.raises(ValueError):
        resolve_persian_datetime("فردا", datetime(2026, 10, 23))


@pytest.mark.parametrize("text", ["۱۴۰۵/۱۲/۳۰", "2026-02-30", "دیروز", "1404/01/01", "2050-01-01"])
def test_invalid_or_out_of_horizon_date_is_never_bookable(text):
    result = resolve_persian_datetime(text, NOW)
    assert result["local_date"] is None and result["ambiguous"]


def test_leap_esfand_and_nowruz_conversion():
    now = datetime(2025, 3, 19, tzinfo=ZoneInfo("Asia/Tehran"))
    assert resolve_persian_datetime("۱۴۰۳/۱۲/۳۰", now)["local_date"] == "2025-03-20"
    assert resolve_persian_datetime("۱۴۰۴/۰۱/۰۱", now)["local_date"] == "2025-03-21"


@pytest.mark.parametrize("text", ["۰۹۱۲۳۴۵۶۷۸۹", "+98 9123456789", "00989123456789", "٠٩١٢٣٤٥٦٧٨٩"])
def test_phone_numeral_variants(text):
    assert normalize_phone(text) == "09123456789"


def test_spoken_digit_phone_and_bad_phone():
    assert normalize_phone("صفر نه یک دو سه چهار پنج شش هفت هشت نه") == "09123456789"
    with pytest.raises(ValueError):
        normalize_phone("شماره من 09123456789 است")
    with pytest.raises(ValueError):
        normalize_phone("09123")


def test_national_id_is_syntax_only_and_rejects_repeated_digits():
    prefix = "123456789"
    rem = sum(int(prefix[i]) * (10-i) for i in range(9)) % 11
    check = rem if rem < 2 else 11-rem
    assert valid_national_id(prefix + str(check))
    assert not valid_national_id("0000000000")
    assert not valid_national_id(prefix + str((check + 1) % 10))


def test_context_weekday_alignment_and_unicode():
    days = generate_shamsi_context(NOW)
    assert len(days) == 14
    assert days[0]["local_date"] == "2026-10-23"
    assert "جمعه" in days[0]["label"]
    assert normalize_text("يک\u200cشنبه ۱۲ كلمه") == "یک شنبه 12 کلمه"

