"""Authentication, cryptography, and minimal identity normalization."""

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet, MultiFernet
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .db import get_db, now_utc
from .models import Membership, Tenant, User
from .models_core import StaffTokenRevocation

password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)
_dummy_hash = password_hasher.hash("not-a-user-password")
bearer = HTTPBearer(auto_error=False)
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

ALL_PERMISSIONS = frozenset({
    "appointment:read", "appointment:write", "task:read", "task:write", "policy:read", "policy:write",
    "catalog:read", "catalog:write", "billing:read", "billing:write", "privacy:manage", "integration:read",
    "integration:write", "routing:write", "audit:read", "partner:manage", "team:manage", "building:read",
    "reports:read", "health:read",
})
_CLINICAL = frozenset({"appointment:read", "appointment:write", "task:read", "task:write", "catalog:read", "policy:read"})
ROLE_PERMISSIONS = {
    "owner": ALL_PERMISSIONS,
    "admin": ALL_PERMISSIONS - {"team:manage"},
    "manager": _CLINICAL | {"policy:write", "catalog:write", "reports:read", "audit:read", "building:read", "integration:read", "health:read"},
    "coordinator": _CLINICAL | {"building:read", "reports:read"},
    "receptionist": _CLINICAL,
    "clinician": _CLINICAL,
    "billing": frozenset({"billing:read", "billing:write", "reports:read"}),
    "technical": frozenset({"integration:read", "integration:write", "routing:write", "health:read", "audit:read"}),
    "partner": frozenset({"reports:read"}),
}


def has_permission(actor, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(actor.role, frozenset())


def fail(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


def encrypt(value: str) -> str:
    return Fernet(settings.encryption_key.encode()).encrypt(value.encode()).decode()


def decrypt(value: str) -> str:
    keys = [settings.encryption_key, *settings.previous_encryption_keys]
    return MultiFernet([Fernet(key.encode()) for key in keys]).decrypt(value.encode()).decode()


def normalize_phone(value: str) -> str:
    normalized = re.sub(r"[\s()\-]", "", value.translate(_DIGITS))
    if normalized.startswith("0098"):
        normalized = "0" + normalized[4:]
    elif normalized.startswith("+98"):
        normalized = "0" + normalized[3:]
    elif normalized.startswith("98") and len(normalized) == 12:
        normalized = "0" + normalized[2:]
    if not re.fullmatch(r"09[0-9]{9}", normalized):
        fail(422, "INVALID_PHONE", "شماره همراه معتبر ایران را وارد کنید.")
    return normalized


def hash_phone(value: str) -> str:
    # The lookup key remains stable during ciphertext-key rotation. Development
    # alone retains the original fallback for reproducible synthetic fixtures.
    key = settings.lookup_hash_key or settings.encryption_key
    return hmac.new(key.encode(), normalize_phone(value).encode(), hashlib.sha256).hexdigest()


def mask_phone(value: str) -> str:
    return value[:3] + "•••••" + value[-3:] if len(value) >= 8 else "••••"


def hash_password(value: str) -> str:
    return password_hasher.hash(value)


def check_password(value: str, encoded: str | None) -> bool:
    try:
        valid = password_hasher.verify(encoded or _dummy_hash, value)
        return bool(encoded) and valid
    except (VerificationError, InvalidHashError):
        return False


@dataclass(frozen=True)
class Actor:
    user_id: str
    tenant_id: str
    role: str
    name: str
    email: str
    tenant_name: str
    session_id: str | None = None
    token_expires_at: datetime | None = None

    @property
    def id(self):
        return self.user_id

    def as_dict(self):
        return {
            "id": self.user_id,
            "email": self.email,
            "name": self.name,
            "role": self.role,
            "tenant_id": self.tenant_id,
            "tenant_name": self.tenant_name,
            "permissions": sorted(ROLE_PERMISSIONS.get(self.role, frozenset())),
        }


def issue_token(user: User, tenant_id: str, *, session_id: str | None = None, expires_at: datetime | None = None) -> str:
    now = now_utc()
    return jwt.encode(
        {
            "sub": user.id,
            "tenant": tenant_id,
            "ver": user.token_version,
            "iat": now,
            "exp": expires_at or now + timedelta(minutes=settings.access_token_minutes),
            "jti": session_id or secrets.token_urlsafe(32),
            "iss": "persian-receptionist",
            "aud": "staff",
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def actor_for(db: Session, user: User, tenant_id: str) -> Actor:
    membership = db.scalar(
        select(Membership).where(Membership.user_id == user.id, Membership.tenant_id == tenant_id, Membership.active.is_(True))
    )
    tenant = db.get(Tenant, tenant_id)
    if not user.active or membership is None or tenant is None or not tenant.active:
        fail(403, "MEMBERSHIP_REQUIRED", "دسترسی به این مرکز مجاز نیست.")
    return Actor(user.id, tenant.id, membership.role, user.name, user.email, tenant.name)


def current_actor(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db), request: Request = None) -> Actor:
    if not credentials or credentials.scheme.lower() != "bearer":
        fail(401, "AUTH_REQUIRED", "لطفاً وارد حساب شوید.")
    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
            audience="staff",
            issuer="persian-receptionist",
            options={"require": ["exp", "iat", "sub", "tenant", "ver", "jti"]},
        )
    except jwt.PyJWTError:
        fail(401, "INVALID_TOKEN", "نشست منقضی یا نامعتبر است.")
    if not isinstance(claims["jti"], str) or not 20 <= len(claims["jti"]) <= 100 or db.get(StaffTokenRevocation, claims["jti"]):
        fail(401, "INVALID_TOKEN", "نشست منقضی یا نامعتبر است.")
    user = db.get(User, claims["sub"])
    if not user or not user.active or user.token_version != claims["ver"]:
        fail(401, "INVALID_TOKEN", "نشست منقضی یا نامعتبر است.")
    actor = replace(actor_for(db, user, claims["tenant"]), session_id=claims["jti"],
                    token_expires_at=datetime.fromtimestamp(claims["exp"], timezone.utc))
    if request is not None:
        request.state.actor = actor
    return actor


def require_roles(*roles):
    def dependency(actor: Actor = Depends(current_actor)):
        if actor.role not in roles:
            fail(403, "ROLE_REQUIRED", "دسترسی لازم برای این عملیات را ندارید.")
        return actor

    return dependency


def require_permissions(*permissions):
    if not permissions or any(p not in ALL_PERMISSIONS for p in permissions):
        raise ValueError("Unknown or empty permission requirement")

    def dependency(actor: Actor = Depends(current_actor)):
        if any(not has_permission(actor, p) for p in permissions):
            fail(403, "PERMISSION_REQUIRED", "دسترسی لازم برای این عملیات را ندارید.")
        return actor

    return dependency
