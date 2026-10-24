#!/usr/bin/env python3
"""Isolated PBX AMI observer: emits signed, correlated events to private API.

Run ON the approved Asterisk host with dedicated read-only AMI credentials.
Only the PBX may create dial/bridge events; a model never selects endpoints.
A restarted relay cannot recover past events without PBX evidence replay; it
must never claim connection based on a successful blind transfer response.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import re
import ssl
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse
from uuid import UUID

import httpx


ID = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")


def parse_ami_frame(data: bytes):
    if len(data) > 16384:
        return {}
    try:
        lines = data.decode("utf-8").strip("\r\n").split("\r\n")
    except UnicodeDecodeError:
        return {}
    fields = {}
    for line in lines:
        if ": " not in line:
            return {}
        key, value = line.split(": ", 1)
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,50}", key) or key in fields or len(value) > 500:
            return {}
        fields[key] = value
    return fields


class AMIProjector:
    def __init__(self, *, approved_targets: set[str]):
        self.targets = approved_targets
        self.calls = {}  # linkedid -> (registered UUID, caller uniqueid); never caller phone

    def _staff(self, channel):
        return any(channel == target or (channel.startswith(target + "-") and
            re.fullmatch(r"[A-Fa-f0-9]{6,16}", channel[len(target)+1:])) for target in self.targets)

    def project(self, event: dict):
        kind = event.get("Event")
        linkedid = event.get("Linkedid", "")
        if kind == "UserEvent" and event.get("UserEvent") == "HamavaRegistered":
            try:
                call_uuid = str(UUID(event.get("CallUUID", "")))
            except ValueError:
                return []
            caller_uniqueid = event.get("CallerUniqueid", linkedid)
            if ID.fullmatch(linkedid) and ID.fullmatch(caller_uniqueid):
                self.calls[linkedid] = (call_uuid, caller_uniqueid)
                if len(self.calls) > 1000:
                    self.calls.pop(next(iter(self.calls)))
            return []
        if linkedid not in self.calls:
            return []
        stage, channel, uniqueid, bridge = None, "", "", None
        if kind == "UserEvent" and event.get("UserEvent") in {"HamavaStaffAccepted", "HamavaStaffDeclined"}:
            # A private PBX pre-bridge subroutine, not a caller digit or SIP
            # header, produces this event. Correlate to the registration.
            if event.get("CallUUID") != self.calls[linkedid][0]:
                return []
            channel, uniqueid = event.get("StaffChannel", ""), event.get("StaffUniqueid", "")
            if not self._staff(channel):
                return []
            stage = "SCREENED" if event["UserEvent"] == "HamavaStaffAccepted" else "SCREEN_DECLINED"
        if stage is None and kind in {"DialBegin", "DialEnd"}:
            channel, uniqueid = event.get("DestChannel", ""), event.get("DestUniqueid", "")
            if not self._staff(channel):
                return []
            if kind == "DialBegin":
                stage = "RINGING"
            elif event.get("DialStatus") == "ANSWER":
                stage = "ACCEPTED"
            elif event.get("DialStatus") in {"NOANSWER", "BUSY", "CANCEL", "CONGESTION", "CHANUNAVAIL", "TIMEDOUT", "DONTCALL", "TORTURE"}:
                stage = "FAILED"
        elif stage is None and kind in {"BridgeEnter", "BridgeLeave"}:
            bridge = event.get("BridgeUniqueid")
            if not ID.fullmatch(bridge or "") or event.get("BridgeTechnology") == "holding_bridge":
                return []
            channel, uniqueid = event.get("Channel", ""), event.get("Uniqueid", "")
            if uniqueid == self.calls[linkedid][1]:
                stage = "BRIDGE_CALLER" if kind == "BridgeEnter" else "BRIDGE_CALLER_LEFT"
            elif self._staff(channel):
                stage = "BRIDGE_STAFF" if kind == "BridgeEnter" else "BRIDGE_STAFF_LEFT"
        # A successful BlindTransfer does not prove staff pickup or a bridge.
        if not stage or not ID.fullmatch(uniqueid) or not re.fullmatch(r"[A-Za-z0-9_@.:+/-]{1,160}", channel):
            return []
        digest = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()[:32]
        result = {"call_uuid": self.calls[linkedid][0], "linkedid": linkedid,
                  "event_key": digest, "stage": stage, "occurred_at": datetime.now(timezone.utc).isoformat(),
                  "channel": channel, "uniqueid": uniqueid}
        if bridge:
            result["bridge_id"] = bridge
        return [result]


def validate_config():
    host = os.getenv("PBX_AMI_HOST", "127.0.0.1")
    tls = os.getenv("PBX_AMI_TLS", "false").lower() == "true"
    try:
        local = ipaddress.ip_address(host).is_loopback
    except ValueError:
        local = host == "localhost"
    if not local and not tls:
        raise ValueError("External AMI endpoints require TLS")
    api = os.getenv("RECEPTION_API_URL", "http://127.0.0.1:8000")
    parsed = urlparse(api)
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"}):
        raise ValueError("PBX relay requires HTTPS or loopback API")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Invalid API origin")
    username = os.getenv("PBX_AMI_USER", "")
    secret = os.getenv("PBX_AMI_SECRET", "")
    event_token = os.getenv("PBX_EVENT_TOKEN", "")
    targets = {value.strip() for value in os.getenv("HUMAN_TRANSFER_TARGETS", "").split(",") if value.strip()}
    if (not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", username) or len(secret) < 32
        or len(event_token) < 32 or not targets or not all(re.fullmatch(r"(?:PJSIP|Local|IAX2)/[A-Za-z0-9_@.:+/-]{1,110}", t) for t in targets)):
        raise ValueError("PBX event credentials or approved staff targets missing")
    return host, tls, api.rstrip("/"), username, secret, event_token, targets


async def frames(reader):
    """AMI frames are double-CRLF-delimited. Reject oversized frames."""
    while True:
        data = await reader.readuntil(b"\r\n\r\n")
        if len(data) > 16384:
            raise ValueError("Oversized AMI event")
        yield parse_ami_frame(data[:-4])


async def main():
    host, tls, api, username, secret, token, targets = validate_config()
    port = int(os.getenv("PBX_AMI_PORT", "5039" if tls else "5038"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid AMI port")
    observer = AMIProjector(approved_targets=targets)
    headers = {"Authorization": "Bearer " + token}
    async with httpx.AsyncClient(timeout=httpx.Timeout(5, connect=3), follow_redirects=False) as client:
        # Reconnect conservatively. Unobserved events remain unverified in the
        # server; never reconstruct a human connection from guesses.
        while True:
            writer = None
            try:
                reader, writer = await asyncio.open_connection(host, port, ssl=ssl.create_default_context() if tls else None, limit=16384)
                banner = await asyncio.wait_for(reader.readline(), 5)
                if not banner.startswith(b"Asterisk Call Manager/"):
                    raise ValueError("Unexpected AMI banner")
                login = f"Action: Login\r\nUsername: {username}\r\nSecret: {secret}\r\nEvents: on\r\n\r\n"
                writer.write(login.encode("ascii"))
                await writer.drain()
                response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
                if parse_ami_frame(response[:-4]).get("Response") != "Success":
                    raise ValueError("AMI login rejected")
                async for raw in frames(reader):
                    for payload in observer.project(raw):
                        # Payload is not retried with a new timestamp/event key.
                        # A rejected observation is operator-visible but never
                        # elevated into a connected state.
                        for attempt in range(3):
                            try:
                                response = await client.post(api + "/api/v1/internal/media/pbx-transfer", headers=headers, json=payload)
                                if response.status_code in {200, 409, 404}:
                                    break
                            except httpx.HTTPError:
                                pass
                            if attempt < 2:
                                await asyncio.sleep(1 + attempt)
                        else:
                            # Stop consuming unbounded events if the durable API
                            # is unavailable. The PBX human fallback is still real.
                            raise ConnectionError("PBX event recording unavailable")
            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError, ValueError):
                # Never log AMI frames, credentials, patient phone or raw audio.
                print("AMI observation unavailable; human connection remains unverified", file=sys.stderr, flush=True)
                await asyncio.sleep(3)
            finally:
                if writer:
                    writer.close()
                    await writer.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
