"""Production gates and provider validation that protect persisted outcomes."""
import io
import wave

from cryptography.fernet import Fernet
import httpx
import pytest
from sqlalchemy import text

from receptionist.config import Settings
from receptionist.db import Base, make_engine, validate_schema
from receptionist import providers
from receptionist import models, models_ext, models_ops, models_outreach, models_partner, models_voice  # noqa: F401
from receptionist.providers import ProviderError, SpeechGateway
from receptionist.telemetry import safe_error_fields


def production(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("JWT_SECRET", "synthetic-test-secret-with-at-least-forty-characters")
    monkeypatch.setenv("ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("LOOKUP_HASH_KEY", "synthetic-independent-lookup-key-at-least32")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://test@localhost/test")
    monkeypatch.setenv("CORS_ORIGINS", "https://reception.example.test")


@pytest.mark.parametrize("name,value", [
    ("DEMO_MODE", "true"), ("JWT_SECRET", "development-only-change-this-secret-before-production-2026"),
    ("DATABASE_URL", "sqlite:///demo.db"), ("CORS_ORIGINS", "*"), ("CORS_ORIGINS", "http://insecure.example.test"),
    ("ENCRYPTION_KEY", ""), ("LOOKUP_HASH_KEY", ""),
])
def test_production_rejects_unsafe_startup(monkeypatch, name, value):
    production(monkeypatch)
    Settings().validate()
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        Settings().validate()


def test_schema_drift_is_detected_without_mutation(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path/'drift.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        validate_schema(connection)
        connection.execute(text("ALTER TABLE users DROP COLUMN name"))
        with pytest.raises(RuntimeError, match="missing columns users: name"):
            validate_schema(connection)
        # Validation neither recreates the column nor erases the existing table.
        names = [row[1] for row in connection.execute(text("PRAGMA table_info(users)"))]
        assert "id" in names and "name" not in names
    engine.dispose()


def pcm_wav(*, frames=320, rate=16000, channels=1):
    output = io.BytesIO()
    with wave.open(output, "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(b"\x01\x00" * frames * channels)
    return output.getvalue()


def speech_environment(monkeypatch):
    monkeypatch.setenv("SPEECH_GATEWAY_URL", "https://speech.example.test")
    monkeypatch.setenv("SPEECH_GATEWAY_TOKEN", "synthetic-speech-token")
    monkeypatch.setenv("SPEECH_PROCESSOR_APPROVED", "true")
    monkeypatch.setenv("APPROVED_PROVIDER_HOSTS", "speech.example.test")
    providers._speech_cache.clear()
    providers._breakers.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [pcm_wav(frames=0), pcm_wav(rate=8000), pcm_wav(channels=2), pcm_wav()[:-10]])
async def test_invalid_tts_audio_cannot_be_played_or_cached(monkeypatch, data):
    speech_environment(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=data))) as client:
        with pytest.raises(ProviderError, match="INVALID_TTS_AUDIO"):
            await SpeechGateway(client).synthesize("سلام", cache_scope="fixture:policy1")
    assert not providers._speech_cache


@pytest.mark.asyncio
async def test_static_tts_cache_scoped_versioned_and_revocable(monkeypatch):
    speech_environment(monkeypatch)
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, content=pcm_wav())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        gateway = SpeechGateway(client)
        await gateway.synthesize("سلام", cache_scope="clinic-a:policy1")
        assert not gateway.last_cache_hit
        await gateway.synthesize("سلام", cache_scope="clinic-a:policy1")
        assert gateway.last_cache_hit and len(calls) == 1
        await gateway.synthesize("سلام", cache_scope="clinic-b:policy1")
        await gateway.synthesize("سلام", cache_scope="clinic-a:policy2")
        monkeypatch.setenv("SPEECH_VOICE_VERSION", "voice-v2")
        await gateway.synthesize("سلام", cache_scope="clinic-a:policy1")
        assert len(calls) == 4
        await gateway.synthesize("patient readback")
        await gateway.synthesize("patient readback")
        assert len(calls) == 6
        monkeypatch.setenv("SPEECH_PROCESSOR_APPROVED", "false")
        with pytest.raises(ProviderError, match="SPEECH_NOT_CONFIGURED"):
            await gateway.synthesize("سلام", cache_scope="clinic-a:policy1")
        assert len(calls) == 6


def test_database_error_diagnostic_never_includes_sql_or_parameters():
    import sqlite3
    from sqlalchemy.exc import OperationalError
    original = sqlite3.OperationalError("patient-private-data must not be logged")
    original.sqlite_errorname = "SQLITE_BUSY"
    error = OperationalError("SELECT secret FROM patients", {"phone": "09123456789"}, original)
    assert safe_error_fields(error) == {"error_type": "OperationalError", "database_error_code": "SQLITE_BUSY"}


def test_concurrent_backup_publication_never_overwrites_first_archive(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("backup_script", Path(__file__).resolve().parents[2]/"scripts"/"backup.py")
    backup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(backup)
    target = tmp_path/"backup.gpg"
    def attempt(index):
        source = tmp_path/f"encrypted-{index}.partial"
        source.write_bytes(f"unique-encrypted-fixture-{index}".encode())
        try:
            backup.publish_once(source, target)
            return index
        except FileExistsError:
            return None
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(attempt, range(24)))
    winners = [value for value in results if value is not None]
    assert len(winners) == 1
    assert target.read_bytes() == f"unique-encrypted-fixture-{winners[0]}".encode()


def load_script(name):
    import importlib.util
    from pathlib import Path
    import sys
    directory = Path(__file__).resolve().parents[2]/"scripts"
    if str(directory) not in sys.path:
        sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location(name, directory/f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_key_rotation_preserves_lookup_identity_and_resumes(tmp_path, monkeypatch):
    from sqlalchemy.orm import sessionmaker
    from receptionist.config import settings
    from receptionist.models import Appointment, AuditEvent, IdempotencyRecord, MessageOutbox
    from receptionist.security import hash_phone, decrypt, encrypt
    from receptionist.seed import seed_demo
    old, new = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setattr(settings, "encryption_key", old)
    monkeypatch.setattr(settings, "lookup_hash_key", "independent-synthetic-lookup-key-unchanged")
    monkeypatch.setattr(settings, "previous_encryption_keys", [])
    expected_hash = hash_phone("09123456789")
    engine = make_engine(f"sqlite:///{tmp_path/'rotation.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        seed_demo(db)
        booking = db.scalar(__import__('sqlalchemy').select(Appointment))
        booking_id = booking.id
        original = decrypt(booking.patient_name_encrypted)
        original_hash = booking.phone_hash
        audit = AuditEvent(tenant_id=booking.tenant_id, actor_id="synthetic-reviewer", action="synthetic_rotation",
                           entity_type="appointment", entity_id=booking_id,
                           details={"reason_encrypted": encrypt("synthetic refund note"),
                                    "history": [{"note_encrypted": encrypt("synthetic prior note"), "version": 1}],
                                    "reference": "keep-public-reference"})
        receipt = IdempotencyRecord(tenant_id=booking.tenant_id, operation="synthetic", key="rotation-fixture",
                                    request_hash="fixture", entity_id=booking_id,
                                    response={"encrypted": encrypt('{"synthetic":true}')})
        message = db.scalar(__import__('sqlalchemy').select(MessageOutbox))
        message.payload = {"secret": encrypt('{"code":"123456"}'), "template_version": 1}
        db.add_all([audit, receipt])
        db.commit()
        audit_id, receipt_id, message_id = audit.id, receipt.id, message.id
    module = load_script("rotate_encryption")
    planned = module.rotate(engine, new, [old])
    assert planned["fields_needing_rotation"] > 0
    assert planned["nested_fields_needing_rotation"] == 4
    applied = module.rotate(engine, new, [old], apply=True)
    assert applied["fields_needing_rotation"] == planned["fields_needing_rotation"]
    assert module.rotate(engine, new, [old], apply=True)["fields_needing_rotation"] == 0
    monkeypatch.setattr(settings, "encryption_key", new)
    assert hash_phone("09123456789") == expected_hash
    with factory() as db:
        booking = db.get(Appointment, booking_id)
        assert decrypt(booking.patient_name_encrypted) == original
        assert booking.phone_hash == original_hash
        # Old keys are absent: operational notes, replay receipts and queued OTP
        # payloads must still decrypt after their enclosing JSON is rotated.
        audit = db.get(AuditEvent, audit_id)
        assert decrypt(audit.details["reason_encrypted"]) == "synthetic refund note"
        assert decrypt(audit.details["history"][0]["note_encrypted"]) == "synthetic prior note"
        assert audit.details["reference"] == "keep-public-reference" and audit.details["history"][0]["version"] == 1
        assert decrypt(db.get(IdempotencyRecord, receipt_id).response["encrypted"]) == '{"synthetic":true}'
        assert decrypt(db.get(MessageOutbox, message_id).payload["secret"]) == '{"code":"123456"}'
        assert db.get(MessageOutbox, message_id).payload["template_version"] == 1
    engine.dispose()


def test_backup_retention_respects_hold_and_keeps_unverified_files(tmp_path):
    from datetime import UTC, datetime, timedelta
    import hashlib
    import json
    module = load_script("backup_daily")
    now = datetime.now(UTC)
    archive = tmp_path/"hamava-fixture.dump.gpg"
    archive.write_bytes(b"synthetic-ciphertext")
    manifest = archive.with_suffix(archive.suffix+".json")
    manifest.write_text(json.dumps({"format": "pg-custom-gpg-v1", "created_at": (now-timedelta(days=40)).isoformat(),
                                    "encrypted_sha256": hashlib.sha256(archive.read_bytes()).hexdigest()}))
    invalid = tmp_path/"hamava-unverified.dump.gpg.json"
    invalid.write_text("{}")
    assert module.prune(tmp_path, 30, apply=True, legal_hold=True, now=now)["deleted"] == 0
    assert archive.exists()
    result = module.prune(tmp_path, 30, apply=True, now=now)
    assert result["deleted"] == 1 and result["invalid_pairs_preserved"] == 1
    assert not archive.exists() and not manifest.exists() and invalid.exists()
