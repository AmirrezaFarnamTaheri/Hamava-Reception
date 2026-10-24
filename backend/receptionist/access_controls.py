"""Privileged access receipts and explicitly configured API retirement headers."""
import json
import os
import re
import secrets
from datetime import datetime, timezone
from email.utils import format_datetime

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from .db import SessionLocal, now_utc
from .models import AuditEvent
from .security import encrypt


def retirement_policies(raw=None):
    try:
        rows = json.loads(raw if raw is not None else os.getenv("API_DEPRECATIONS_JSON", "[]"))
        if not isinstance(rows, list) or len(rows) > 10:
            raise ValueError
        prefixes = set()
        result = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != {"prefix", "deprecated_at", "sunset_at", "successor"}:
                raise ValueError
            pattern = r"/api/v[1-9][0-9]*(?:/partner/v[1-9][0-9]*)?"
            if not re.fullmatch(pattern, row["prefix"]) or row["prefix"] in prefixes:
                raise ValueError
            if not re.fullmatch(pattern, row["successor"]) or row["successor"] == row["prefix"]:
                raise ValueError
            deprecated, sunset = (datetime.fromisoformat(row[key].replace("Z", "+00:00")) for key in ("deprecated_at", "sunset_at"))
            if deprecated.tzinfo is None or sunset.tzinfo is None or sunset <= deprecated:
                raise ValueError
            prefixes.add(row["prefix"])
            result.append({**row, "deprecated": deprecated, "sunset": sunset})
        return sorted(result, key=lambda item: len(item["prefix"]), reverse=True)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError("API_DEPRECATIONS_JSON must contain unique version prefixes, aware retirement dates and a distinct successor version") from None


class AccessControlMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, *, session_factory=SessionLocal, policies=None):
        super().__init__(app)
        self.session_factory = session_factory
        self.policies = retirement_policies() if policies is None else retirement_policies(json.dumps(policies))

    async def dispatch(self, request, call_next):
        reason = request.headers.get("X-Action-Reason")
        if reason is not None and (not 3 <= len(reason) <= 500 or any(ord(char) < 32 for char in reason)):
            return JSONResponse({"detail": {"code": "INVALID_ACTION_REASON", "message": "Provide a bounded, printable action reason."}}, status_code=422)
        policy = next((p for p in self.policies if request.url.path == p["prefix"] or request.url.path.startswith(p["prefix"] + "/")), None)
        if policy and policy["sunset"] <= now_utc():
            response = JSONResponse({"detail": {"code": "API_VERSION_RETIRED", "message": "This API version has retired; use the published successor.", "successor": policy["successor"]}}, status_code=410)
        else:
            response = await call_next(request)
        if policy and policy["deprecated"] <= now_utc():
            response.headers["Deprecation"] = "@" + str(int(policy["deprecated"].timestamp()))
            response.headers["Sunset"] = format_datetime(policy["sunset"].astimezone(timezone.utc), usegmt=True)
            response.headers["Link"] = f'<{policy["successor"]}>; rel="successor-version"'
        actor = getattr(request.state, "actor", None)
        route = getattr(request.scope.get("route"), "path", "unmatched")
        if actor is not None:
            # Template only: raw paths/queries can contain patient identifiers.
            with self.session_factory() as db:
                db.add(AuditEvent(tenant_id=actor.tenant_id, actor_id=actor.id, action="privileged.access",
                    entity_type="api_route", entity_id=secrets.token_hex(16), details={
                        "route": route, "method": request.method, "status": response.status_code, "role": actor.role,
                        "reason_encrypted": encrypt(reason) if reason else None,
                        "reason_basis": "explicit_request_header" if reason else "authorized_route_access",
                        "deprecated": bool(policy and policy["deprecated"] <= now_utc())}))
                db.commit()
        return response
