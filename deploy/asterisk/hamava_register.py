#!/usr/bin/env python3
"""Minimal AGI registration. Only AGI commands go to stdout; no credentials log.

Install executable under Asterisk's approved AGI directory. Supply private
RECEPTION_API_URL and MEDIA_API_TOKEN through the Asterisk service environment.
The dialplan must play the reviewed processing notice before invoking this AGI.
"""
import json
import os
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


def set_variable(name, value):
    if not re.fullmatch(r"[A-Z_]+", name) or not re.fullmatch(r"[a-zA-Z0-9_@.:+/-]{0,120}", value):
        raise ValueError("Unsafe AGI variable")
    print(f'SET VARIABLE {name} "{value}"', flush=True)
    result = sys.stdin.readline()
    if not result.startswith("200"):
        raise RuntimeError("AGI command was not accepted")


def approved_target(value):
    """Both the API and the PBX must authorize the literal channel destination."""
    approved = {item.strip() for item in os.getenv("HUMAN_TRANSFER_TARGETS", "").split(",") if item.strip()}
    return (isinstance(value, str) and value in approved and
            re.fullmatch(r"(?:PJSIP|Local|IAX2)/[A-Za-z0-9_@.:+/-]{1,110}", value) is not None)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        return None


def main():
    for line in sys.stdin:
        if not line.strip():
            break
    set_variable("HAMAVA_REGISTERED", "0")
    if len(sys.argv) not in {3, 5} or sys.argv[2] not in {"incoming", "busy", "no_answer", "after_hours"}:
        return 1
    did, reason = sys.argv[1:3]
    linkedid, caller_uniqueid = sys.argv[3:5] if len(sys.argv) == 5 else (None, None)
    if linkedid is not None and (not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", linkedid) or
                                not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", caller_uniqueid)):
        return 1
    if not re.fullmatch(r"[+a-zA-Z0-9_-]{1,80}", did):
        return 1
    base = os.getenv("RECEPTION_API_URL", "http://127.0.0.1:8000").rstrip("/")
    parsed = urlparse(base)
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return 1
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
        return 1
    secret = os.getenv("MEDIA_API_TOKEN", "")
    if len(secret) < 32:
        return 1
    call_uuid = str(uuid4())
    payload = {"call_uuid": call_uuid, "did": did, "routing_reason": reason, "processing_notice_played": True}
    if linkedid is not None:
        payload.update(pbx_linkedid=linkedid, pbx_caller_uniqueid=caller_uniqueid)
    request = Request(base+"/api/v1/internal/media/register", method="POST",
        headers={"Authorization": "Bearer "+secret, "Content-Type": "application/json"},
        data=json.dumps(payload).encode())
    try:
        with build_opener(NoRedirect).open(request, timeout=4) as response:
            body = json.loads(response.read(8192))
        if body.get("registered") is not True or body.get("call_uuid") != call_uuid:
            return 0
        target, queue = body.get("transfer_target"), body.get("queue_id")
        if target is not None:
            if not approved_target(target) or not isinstance(queue, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", queue):
                return 1
            set_variable("HAMAVA_TRANSFER_TARGET", target)
            set_variable("HAMAVA_QUEUE", queue)
        set_variable("HAMAVA_UUID", call_uuid)
        set_variable("HAMAVA_REGISTERED", "1")
        return 0
    except (HTTPError, URLError, TimeoutError, ValueError):
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
