"""Typed mutation contracts; extra fields are rejected at the tool boundary."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginInput(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class SwitchInput(StrictModel):
    tenant_id: str = Field(min_length=1, max_length=60)


class LogoutInput(StrictModel):
    all_devices: bool = False


class HoldInput(StrictModel):
    slot_id: str = Field(min_length=10, max_length=3000)
    session_id: str | None = Field(default=None, max_length=120)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=160)


class BookingInput(HoldInput):
    patient_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=8, max_length=30)
    idempotency_key: str = Field(min_length=8, max_length=160)
    confirmed: bool
    hold_id: str | None = Field(default=None, max_length=120)
    reminder_opt_in: bool = False
    payment_terms_version: int | None = Field(default=None, ge=0)
    payment_terms_accepted: bool = False
    package_entitlement_id: str | None = Field(default=None, max_length=60)

    @field_validator("patient_name")
    @classmethod
    def no_control_characters(cls, value):
        if any(ord(c) < 32 for c in value):
            raise ValueError("Name cannot include control characters")
        return value


class CancelInput(StrictModel):
    reason: str = Field(default="", max_length=300)
    idempotency_key: str = Field(min_length=8, max_length=160)
    version: int | str

    @field_validator("version")
    @classmethod
    def valid_revision(cls, value):
        if isinstance(value, int) and value >= 1 or isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", value):
            return value
        raise ValueError("A positive local version or bounded external revision is required")


class RescheduleInput(CancelInput):
    slot_id: str = Field(min_length=10, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=160)


class VersionInput(StrictModel):
    version: int = Field(ge=1)


class OutcomeInput(VersionInput):
    outcome: Literal["ATTENDED", "NO_SHOW"]


class TaskResolution(StrictModel):
    resolution: str = Field(min_length=2, max_length=500)


class FAQ(StrictModel):
    question: str = Field(min_length=2, max_length=200)
    answer: str = Field(min_length=2, max_length=1000)
    category: str = Field(default="general", max_length=50)
    source: str = Field(default="owner-approved clinic policy", min_length=3, max_length=300)
    approved_by: str | None = Field(default=None, max_length=120)
    effective_at: str | None = Field(default=None, max_length=60)
    expires_at: str | None = Field(default=None, max_length=60)
    keywords: list[str] = Field(default_factory=list, max_length=30)


class SettingsInput(VersionInput):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    mode: Literal["after_hours", "overflow", "human_primary", "supervised", "ai_primary", "paused"] | None = None
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=40)
    website: str | None = Field(default=None, max_length=300)
    working_hours: dict[str, list[list[str]]] | None = None
    holidays: list[str] | None = Field(default=None, max_length=200)
    faq: list[FAQ] | None = Field(default=None, max_length=50)
    retention_days: int | None = Field(default=None, ge=1, le=365)
    lead_time_minutes: int | None = Field(default=None, ge=0, le=10080)
    booking_horizon_days: int | None = Field(default=None, ge=1, le=365)
    cancellation_notice_hours: int | None = Field(default=None, ge=0, le=720)
    quiet_hours: dict[str, str] | None = None
    monthly_minute_budget: int | None = Field(default=None, ge=1, le=1000000)


class ClinicCreate(StrictModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(min_length=3, max_length=60, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    address: str = Field(default="", max_length=500)
    phone: str = Field(default="", max_length=40)


class PractitionerInput(StrictModel):
    name: str = Field(min_length=2, max_length=160)
    specialty: str = Field(default="", max_length=100)
    active: bool = True
    working_hours: dict[str, list[list[str]]] | None = None

    @field_validator("working_hours")
    @classmethod
    def valid_shifts(cls, hours):
        if hours is None:
            return hours
        if any(day not in {str(n) for n in range(7)} for day in hours):
            raise ValueError("Shift weekdays must be 0 through 6")
        for intervals in hours.values():
            if len(intervals) > 8:
                raise ValueError("At most eight shifts are allowed per day")
            previous_end = None
            for interval in intervals:
                if len(interval) != 2 or any(not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value) for value in interval):
                    raise ValueError("Shifts must use local HH:MM opening and closing times")
                begin, end = interval
                if begin >= end or (previous_end and begin < previous_end):
                    raise ValueError("Shifts must be ordered, nonoverlapping, and within one day")
                previous_end = end
        return hours


class ServiceInput(StrictModel):
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=1000)
    provider_ids: list[str] = Field(min_length=1, max_length=50)
    resource_ids: list[str] = Field(default_factory=list, max_length=20)
    duration_minutes: int = Field(ge=5, le=480)
    buffer_minutes: int = Field(default=0, ge=0, le=120)
    price_toman: int = Field(default=0, ge=0, le=1000000000)
    deposit_toman: int = Field(default=0, ge=0, le=1000000000)
    requires_approval: bool = False
    active: bool = True
