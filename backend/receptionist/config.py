"""Environment configuration with deliberate production startup gates."""

import base64
import hashlib
import ipaddress
import json
import os
import re
from dataclasses import dataclass, field
from urllib.parse import urlsplit


def _bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"1", "true", "yes", "0", "false", "no"}:
        raise ValueError(f"{name} must be true or false")
    return value in {"1", "true", "yes"}


def integer_setting(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer between {minimum} and {maximum}") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _required(name: str, minimum: int = 1) -> str:
    value = os.getenv(name, "").strip()
    if len(value) < minimum or value in {"not_recorded", "not_configured", "requires_operator_verification"}:
        raise ValueError(f"Enabled provider requires {name} ({minimum} or more characters)")
    return value


def _provider_url(name: str, *, websocket: bool = False) -> None:
    value = _required(name)
    parsed = urlsplit(value)
    allowed = {host.strip().lower() for host in os.getenv("APPROVED_PROVIDER_HOSTS", "").split(",") if host.strip()}
    schemes = {"https", "wss"} if websocket else {"https"}
    local = parsed.hostname in {"localhost", "127.0.0.1", "::1"} and _bool("ALLOW_LOCAL_HTTP_PROVIDERS")
    if local:
        schemes |= {"http", "ws"} if websocket else {"http"}
    if parsed.scheme not in schemes or not parsed.hostname or parsed.hostname.lower() not in allowed:
        raise ValueError(f"{name} must use an approved HTTPS host (explicit loopback development exception only)")
    if parsed.username or parsed.password or parsed.fragment or parsed.query:
        raise ValueError(f"{name} must not include credentials, query parameters or fragments")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError(f"{name} has an invalid port") from exc


def validate_optional_providers(production: bool) -> None:
    """Validate enabled integrations before any request; never echo secret values."""
    flags = (
        "SPEECH_PROCESSOR_APPROVED", "SPEECH_FALLBACK_APPROVED", "SMS_PROVIDER_APPROVED",
        "PAYMENT_PROVIDER_APPROVED", "LIVEKIT_APPROVED", "CALENDAR_PARTNER_APPROVED",
        "DIGEST_PROCESSOR_APPROVED", "ALLOW_LOCAL_HTTP_PROVIDERS", "RUN_WORKER",
    )
    for name in flags:
        _bool(name)
    for prefix, flag in (("SPEECH_GATEWAY", "SPEECH_PROCESSOR_APPROVED"), ("SPEECH_FALLBACK", "SPEECH_FALLBACK_APPROVED")):
        if _bool(flag):
            _provider_url(prefix + "_URL")
            _required(prefix + "_TOKEN", 32)
            if production:
                _required("SPEECH_PROCESSOR_REGION" if prefix == "SPEECH_GATEWAY" else "SPEECH_FALLBACK_REGION")
                _required("SPEECH_ASR_VERSION" if prefix == "SPEECH_GATEWAY" else "SPEECH_FALLBACK_MODEL_VERSION")
                if prefix == "SPEECH_GATEWAY":
                    _required("SPEECH_VOICE_VERSION")
                if not _bool("SPEECH_MODEL_RIGHTS_REVIEWED"):
                    raise ValueError("Enabled speech in production requires SPEECH_MODEL_RIGHTS_REVIEWED=true")
    if _bool("SPEECH_FALLBACK_APPROVED") and not _bool("SPEECH_PROCESSOR_APPROVED"):
        raise ValueError("SPEECH_FALLBACK_APPROVED requires an approved primary speech provider")
    if _bool("SMS_PROVIDER_APPROVED"):
        _required("KAVENEGAR_API_KEY", 8)
        _required("KAVENEGAR_OTP_TEMPLATE")
        _required("KAVENEGAR_SENDER")
        _required("NOTIFICATION_WEBHOOK_SECRET", 32)
        if production:
            _required("SMS_PROCESSOR_REGION")
    if _bool("LIVEKIT_APPROVED"):
        _provider_url("LIVEKIT_URL", websocket=True)
        _required("LIVEKIT_API_KEY")
        _required("LIVEKIT_API_SECRET", 32)
        _required("MEDIA_API_TOKEN", 32)
        if production:
            _required("TELEPHONY_PROCESSOR_REGION")
    if _bool("DIGEST_PROCESSOR_APPROVED"):
        _provider_url("DIGEST_GATEWAY_URL")
        _required("DIGEST_GATEWAY_TOKEN", 32)
        if production:
            _required("DIGEST_PROCESSOR_REGION")
    if _bool("CALENDAR_PARTNER_APPROVED"):
        _provider_url("CALENDAR_PARTNER_URL")
        _required("CALENDAR_WEBHOOK_SECRET", 32)
        try:
            credentials = json.loads(_required("CALENDAR_TENANT_CREDENTIALS_JSON"))
            if not isinstance(credentials, dict) or not credentials:
                raise ValueError
            accounts = set()
            for tenant_id, entry in credentials.items():
                if (not isinstance(tenant_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,60}", tenant_id)
                    or not isinstance(entry, dict) or set(entry) != {"account_id", "token"}
                    or not isinstance(entry["account_id"], str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,120}", entry["account_id"])
                    or not isinstance(entry["token"], str) or len(entry["token"]) < 32 or entry["account_id"] in accounts):
                    raise ValueError
                accounts.add(entry["account_id"])
        except (ValueError, TypeError, KeyError):
            raise ValueError("Calendar requires unique tenant-bound account_id and secret token mappings") from None
        if production:
            _required("CALENDAR_PROCESSOR_REGION")
    if _bool("PAYMENT_PROVIDER_APPROVED"):
        if production:
            _required("PAYMENT_PROCESSOR_REGION")
        try:
            merchants = json.loads(_required("PAYMENT_MERCHANTS_JSON"))
            tenants = json.loads(_required("PAYMENT_TENANT_MERCHANTS_JSON"))
            if not isinstance(merchants, dict) or not isinstance(tenants, dict) or not merchants or not tenants:
                raise ValueError
            for alias in tenants.values():
                entry = merchants[alias]
                if not isinstance(entry, dict) or not entry.get("merchant_id") or entry.get("approved") is not True or not isinstance(entry.get("sandbox"), bool):
                    raise ValueError
            public = urlsplit(_required("PUBLIC_BASE_URL"))
            if public.scheme != "https" or not public.hostname or public.username or public.password or public.query or public.fragment:
                raise ValueError
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError("Enabled payment requires valid tenant-bound approved merchant mappings and HTTPS PUBLIC_BASE_URL") from exc
    try:
        routes = json.loads(os.getenv("MEDIA_DID_TENANTS_JSON", "{}"))
        if not isinstance(routes, dict) or any(not isinstance(k, str) or not k or not isinstance(v, str) or not v for k, v in routes.items()):
            raise ValueError
        for cidr in os.getenv("AUDIOSOCKET_ALLOWED_CIDRS", "127.0.0.0/8,::1/128").split(","):
            ipaddress.ip_network(cidr.strip())
    except (ValueError, TypeError) as exc:
        raise ValueError("MEDIA_DID_TENANTS_JSON and AUDIOSOCKET_ALLOWED_CIDRS must contain valid explicit routes/networks") from exc
    if routes:
        _required("MEDIA_API_TOKEN", 32)
        if production:
            _required("TELEPHONY_PROCESSOR_REGION")
    try:
        sms_routes = json.loads(os.getenv("SMS_INBOUND_TENANTS_JSON", "{}"))
        if not isinstance(sms_routes, dict) or any(not isinstance(k, str) or not re.fullmatch(r"\+?[0-9]{3,20}", k)
                or not isinstance(v, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", v) for k, v in sms_routes.items()):
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("SMS_INBOUND_TENANTS_JSON must map explicit receiver numbers to clinic slugs") from None
    if sms_routes:
        _required("SMS_INBOUND_WEBHOOK_SECRET", 32)
        if production and not _bool("SMS_PROVIDER_APPROVED"):
            raise ValueError("Interactive SMS production routing requires an approved outbound provider")
    for target in filter(None, os.getenv("HUMAN_TRANSFER_TARGETS", "").split(",")):
        if not re.fullmatch(r"[A-Za-z0-9_.+@:/-]{1,120}", target.strip()):
            raise ValueError("HUMAN_TRANSFER_TARGETS must contain explicit safe PBX targets")


def validate_origin(origin: str, production: bool) -> None:
    # The installed desktop origin is deliberately one exact scheme/host.
    # Merely supplying an arbitrary custom scheme never authorizes it.
    if origin == "app://hamava":
        return
    parsed = urlsplit(origin)
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("CORS_ORIGINS contains an invalid port") from exc
    schemes = {"https"} if production else {"http", "https"}
    if parsed.scheme not in schemes or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or "*" in origin:
        raise ValueError("CORS_ORIGINS must contain exact HTTPS origins or the explicit app://hamava origin (HTTP is development-only)")


@dataclass
class Settings:
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./receptionist.db"))
    jwt_secret: str = field(default_factory=lambda: os.getenv("JWT_SECRET", "development-only-change-this-secret-before-production-2026"))
    encryption_key: str = field(
        default_factory=lambda: os.getenv(
            "ENCRYPTION_KEY", base64.urlsafe_b64encode(hashlib.sha256(b"development-only-encryption-key").digest()).decode()
        )
    )
    previous_encryption_keys: list[str] = field(default_factory=lambda: [key.strip() for key in os.getenv("ENCRYPTION_PREVIOUS_KEYS", "").split(",") if key.strip()])
    lookup_hash_key: str | None = field(default_factory=lambda: os.getenv("LOOKUP_HASH_KEY") or None)
    demo_mode: bool = field(default_factory=lambda: _bool("DEMO_MODE", True))
    access_token_minutes: int = field(default_factory=lambda: int(os.getenv("ACCESS_TOKEN_MINUTES", "60")))
    cors_origins: list[str] = field(
        default_factory=lambda: [
            x.strip()
            for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8000").split(",")
            if x.strip()
        ]
    )
    hold_minutes: int = 5
    payment_hold_minutes: int = 60

    def validate(self) -> None:
        from cryptography.fernet import Fernet

        Fernet(self.encryption_key.encode())
        for key in self.previous_encryption_keys:
            Fernet(key.encode())
        production = self.environment.lower() in {"production", "prod"}
        if not 5 <= self.access_token_minutes <= 1440:
            raise ValueError("ACCESS_TOKEN_MINUTES must be between 5 and 1440")
        if not 1 <= self.hold_minutes <= 30 or not 1 <= self.payment_hold_minutes <= 1440:
            raise ValueError("Hold durations must be bounded positive minutes")
        if not self.cors_origins:
            raise ValueError("CORS_ORIGINS must contain at least one explicit origin")
        for origin in self.cors_origins:
            validate_origin(origin, production)
        limits = {
            "MAX_CONCURRENT_CALLS_PER_TENANT": (20, 1, 500), "MAX_MEDIA_CONNECTIONS": (8, 1, 100),
            "MAX_LIVEKIT_ROOMS_PER_WORKER": (8, 1, 100), "MAX_CALL_SECONDS": (1800, 60, 7200),
            "SPEECH_MAX_CONCURRENCY": (2, 1, 8), "WHISPER_CPU_THREADS": (4, 1, 128),
            "AUDIOSOCKET_PORT": (9092, 1, 65535), "PROVIDER_HEALTH_TIMEOUT_SECONDS": (5, 1, 15),
            "PROVIDER_HEALTH_STALE_SECONDS": (120, 10, 3600), "PROVIDER_OPERATION_TIMEOUT_SECONDS": (12, 1, 60),
            "TOOL_TIMEOUT_MS": (3000, 50, 30000), "SHUTDOWN_GRACE_SECONDS": (20, 1, 60),
        }
        for name, bounds in limits.items():
            integer_setting(name, *bounds)
        if production:
            if self.demo_mode:
                raise ValueError("DEMO_MODE must be false in production")
            if not os.getenv("JWT_SECRET") or len(self.jwt_secret) < 40 or "development" in self.jwt_secret:
                raise ValueError("A unique JWT_SECRET with at least 40 characters is required in production")
            development_key = base64.urlsafe_b64encode(hashlib.sha256(b"development-only-encryption-key").digest()).decode()
            if not os.getenv("ENCRYPTION_KEY") or self.encryption_key == development_key:
                raise ValueError("A durable, secret ENCRYPTION_KEY is required in production")
            if not self.lookup_hash_key or len(self.lookup_hash_key) < 32 or self.lookup_hash_key == self.encryption_key:
                raise ValueError("A separate durable LOOKUP_HASH_KEY of at least 32 characters is required in production")
            if not self.database_url.startswith("postgresql"):
                raise ValueError("Production requires PostgreSQL and the database migration step")
        validate_optional_providers(production)
        from .access_controls import retirement_policies
        retirement_policies()


settings = Settings()
