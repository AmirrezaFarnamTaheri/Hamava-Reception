"""Versioned, conditional calendar connector contract.

This is Hamava's published partner protocol. It requires a provider-specific
account credential; implementing it does not establish access to a named vendor.
"""
from datetime import datetime
from typing import Literal, Protocol
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .providers import ProviderError, approved_url, provider_request


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CalendarCapabilities(ContractModel):
    protocol: Literal["hamava-calendar-v1"]
    account_id: str = Field(min_length=1, max_length=120)
    revision: str = Field(min_length=1, max_length=120)
    conditional_create: bool
    conditional_update: bool
    idempotency: bool
    readback: bool
    slots: bool
    holds: bool
    cancel: bool
    update: bool
    reconciliation: bool
    changes: bool


class RemoteSlot(ContractModel):
    id: str = Field(min_length=1, max_length=200)
    provider_id: str = Field(min_length=1, max_length=60)
    service_id: str = Field(min_length=1, max_length=60)
    start_at: str
    end_at: str
    revision: str = Field(min_length=1, max_length=120)
    expires_at: str

    @field_validator("start_at", "end_at", "expires_at")
    @classmethod
    def aware(cls, value):
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("Timezone-aware timestamp required")
        return value

    @model_validator(mode="after")
    def interval(self):
        if datetime.fromisoformat(self.end_at.replace("Z", "+00:00")) <= datetime.fromisoformat(self.start_at.replace("Z", "+00:00")):
            raise ValueError("End must be after start")
        return self


class RemoteAppointment(ContractModel):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    account_id: str = Field(min_length=1, max_length=120)
    revision: str = Field(min_length=1, max_length=120)
    status: Literal["CONFIRMED", "CANCELED", "PENDING_STAFF_APPROVAL", "PENDING_PAYMENT", "EXPIRED"]
    slot_id: str = Field(min_length=1, max_length=200)
    provider_id: str = Field(min_length=1, max_length=60)
    service_id: str = Field(min_length=1, max_length=60)
    patient_token: str = Field(min_length=1, max_length=120)
    start_at: str
    end_at: str
    reference: str = Field(min_length=1, max_length=100)
    payment_url: str | None = None
    payment_expires_at: str | None = None

    _aware = field_validator("start_at", "end_at")(RemoteSlot.aware.__func__)
    _interval = model_validator(mode="after")(RemoteSlot.interval)


class RemoteHold(ContractModel):
    account_id: str = Field(min_length=1, max_length=120)
    id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    slot_id: str = Field(min_length=1, max_length=200)
    status: Literal["HELD"]
    expires_at: str

    _aware = field_validator("expires_at")(RemoteSlot.aware.__func__)


class CalendarConnector(Protocol):
    async def capabilities(self) -> dict: ...
    async def slots(self, provider_id: str, service_id: str, day: str) -> list[dict]: ...
    async def get(self, remote_id: str) -> dict: ...
    async def hold(self, request: dict, key: str) -> dict: ...
    async def release(self, hold_id: str, key: str) -> dict: ...
    async def create(self, request: dict, key: str) -> dict: ...
    async def cancel(self, remote_id: str, revision: str, key: str) -> dict: ...
    async def update(self, remote_id: str, request: dict, revision: str, key: str) -> dict: ...
    async def reconcile(self, key: str) -> dict: ...
    async def changes(self, cursor: str | None) -> dict: ...


class HTTPPartnerCalendar:
    def __init__(self, base_url, token, account_id, *, client: httpx.AsyncClient | None = None):
        self.base = approved_url(base_url, "CALENDAR_PARTNER_APPROVED", allow_local=True)
        if not token or not account_id or len(account_id) > 120:
            raise ProviderError("CALENDAR_SCOPE_NOT_CONFIGURED")
        self.token, self.account_id, self.client = token, account_id, client
        self._caps = None
        self.request_count = 0

    async def _request(self, method, path, *, operation, write=False, key=None, revision=None, **kwargs):
        headers = {"Authorization": "Bearer " + self.token, "X-Calendar-Account": self.account_id,
                   "X-Hamava-Protocol": "hamava-calendar-v1"}
        if key:
            headers["Idempotency-Key"] = key
        if revision:
            headers["If-Match"] = revision
        # Every path identifier is percent-encoded; redirects are prohibited by provider_request.
        self.request_count += 1
        response = await provider_request(method, self.base + path, operation="calendar:" + operation,
                                          write=write, headers=headers, client=self.client, **kwargs)
        if len(response.content) > 1_000_000:
            raise ProviderError("CALENDAR_RESPONSE_TOO_LARGE", unknown_outcome=write)
        try:
            result = response.json()
            if not isinstance(result, dict) or result.get("account_id") != self.account_id:
                raise ValueError
            return result
        except (TypeError, ValueError) as exc:
            raise ProviderError("CALENDAR_INVALID_SCOPE_OR_RESPONSE", unknown_outcome=write) from exc

    async def capabilities(self):
        try:
            result = CalendarCapabilities.model_validate(await self._request("GET", "/capabilities", operation="capabilities")).model_dump()
        except ValueError as exc:
            raise ProviderError("CALENDAR_INVALID_CAPABILITIES") from exc
        if not all(result[k] for k in ("conditional_create", "conditional_update", "idempotency", "readback", "reconciliation")):
            raise ProviderError("CALENDAR_ATOMICITY_NOT_SUPPORTED")
        self._caps = result
        return result

    async def _require(self, field):
        if not (self._caps or await self.capabilities()).get(field):
            raise ProviderError("CALENDAR_OPERATION_NOT_SUPPORTED")

    async def slots(self, provider_id, service_id, day):
        await self._require("slots")
        result = await self._request("GET", "/slots", operation="slots", params={"provider_id": provider_id, "service_id": service_id, "date": day})
        try:
            values = result["slots"]
            if not isinstance(values, list) or len(values) > 500:
                raise ValueError
            rows = [RemoteSlot.model_validate(value).model_dump() for value in values]
            if any(row["provider_id"] != provider_id or row["service_id"] != service_id for row in rows):
                raise ValueError
            return rows
        except (KeyError, ValueError, TypeError) as exc:
            raise ProviderError("CALENDAR_INVALID_SLOTS") from exc

    async def get(self, remote_id):
        try:
            result = RemoteAppointment.model_validate(await self._request("GET", "/appointments/" + quote(remote_id, safe=""), operation="get")).model_dump()
            if result["id"] != remote_id:
                raise ValueError
            return result
        except ValueError as exc:
            raise ProviderError("CALENDAR_READBACK_MISMATCH") from exc

    async def hold(self, request, key):
        await self._require("holds")
        try:
            value = RemoteHold.model_validate(await self._request("POST", "/holds", operation="hold", write=True, key=key,
                                   revision=request["revision"], json=request)).model_dump()
            if value["slot_id"] != request["slot_id"]:
                raise ValueError("Slot mismatch")
            return value
        except ValueError as exc:
            raise ProviderError("CALENDAR_INVALID_HOLD", unknown_outcome=True) from exc

    async def release(self, hold_id, key):
        await self._require("holds")
        value = await self._request("POST", "/holds/" + quote(hold_id, safe="") + "/release", operation="release", write=True, key=key, json={})
        if value.get("id") != hold_id or value.get("status") not in {"RELEASED", "EXPIRED"}:
            raise ProviderError("CALENDAR_INVALID_RELEASE", unknown_outcome=True)
        return value

    async def _verified_write(self, method, path, request, key, revision, expected_status=None, expected_id=None):
        response = await self._request(method, path, operation="write", write=True, key=key, revision=revision, json=request)
        remote_id = response.get("id")
        if not isinstance(remote_id, str) or not remote_id or len(remote_id) > 120 or expected_id and remote_id != expected_id:
            raise ProviderError("CALENDAR_UNKNOWN_OUTCOME", unknown_outcome=True)
        try:
            current = await self.get(remote_id)
        except ProviderError as exc:
            raise ProviderError("CALENDAR_READBACK_UNAVAILABLE", unknown_outcome=True) from exc
        if (expected_status and current["status"] != expected_status or
            any(current.get(k) != request[k] for k in ("slot_id", "patient_token", "provider_id", "service_id") if k in request)):
            raise ProviderError("CALENDAR_READBACK_MISMATCH", unknown_outcome=True)
        return current

    async def create(self, request, key):
        await self._require("conditional_create")
        return await self._verified_write("POST", "/appointments", request, key, request["revision"])

    async def cancel(self, remote_id, revision, key):
        await self._require("cancel")
        return await self._verified_write("POST", "/appointments/" + quote(remote_id, safe="") + "/cancel", {}, key, revision, "CANCELED", remote_id)

    async def update(self, remote_id, request, revision, key):
        await self._require("update")
        return await self._verified_write("PUT", "/appointments/" + quote(remote_id, safe=""), request, key, revision, expected_id=remote_id)

    async def reconcile(self, key):
        await self._require("reconciliation")
        result = await self._request("GET", "/operations/by-idempotency-key", operation="reconcile", params={"key": key})
        state = result.get("state")
        if state not in {"COMMITTED", "NOT_COMMITTED", "PENDING"}:
            raise ProviderError("CALENDAR_INVALID_RECONCILIATION")
        if state == "COMMITTED" and result.get("appointment_id"):
            result["appointment"] = await self.get(result["appointment_id"])
        return result

    async def changes(self, cursor):
        await self._require("changes")
        result = await self._request("GET", "/changes", operation="changes", params={"cursor": cursor or ""})
        if not isinstance(result.get("events"), list) or len(result["events"]) > 500 or not isinstance(result.get("cursor"), str):
            raise ProviderError("CALENDAR_INVALID_CHANGES")
        return result
