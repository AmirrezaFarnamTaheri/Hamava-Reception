"""Explicitly opted-in SMS continuation over the same transactional voice FSM.

Inbound requests use the documented signed gateway protocol. A raw public
sender field cannot prove phone ownership or choose a clinic. Production native
carrier-to-gateway receipt verification remains a deployment responsibility.
"""
import asyncio
import json
import os

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .core_policy import lock
from .db import get_db, now_utc
from .models import MessageOutbox, Tenant
from .models_core import SmsConversation
from .models_voice import CallSession
from .providers import verify_webhook
from .schemas import StrictModel
from .security import bearer, encrypt, fail, hash_phone, normalize_phone
from .voice import (Conversation, TurnInput, _TurnTransaction, authenticated_call, context,
                    digest, execute_turn, request_handoff, save_context)

router = APIRouter(prefix="/api/v1")


class SMSRequest(StrictModel):
    phone: str = Field(min_length=8, max_length=30)
    sms_consent: bool


@router.post("/public/sessions/{session_id}/sms/request")
def request_sms(session_id: str, body: SMSRequest, credentials=Depends(bearer), db: Session = Depends(get_db)):
    row = authenticated_call(session_id, credentials, db)
    if not body.sms_consent:
        fail(422, "SMS_CONSENT_REQUIRED", "ادامه گفت‌وگو با پیامک به انتخاب صریح شما نیاز دارد.")
    if row.state in {"HUMAN_CONNECTED", "WAIT_CALENDAR", "HANDOFF_PENDING"}:
        fail(409, "SESSION_BUSY", "ابتدا نتیجه درخواست جاری را بررسی کنید.")
    tenant = db.get(Tenant, row.tenant_id)
    try:
        receiver = next((number for number, slug in json.loads(os.getenv("SMS_INBOUND_TENANTS_JSON", "{}")).items() if slug == tenant.slug), None)
    except (ValueError, AttributeError):
        receiver = None
    if not receiver:
        fail(503, "SMS_INBOUND_NOT_CONFIGURED", "مسیر پیامک تعاملی این مرکز هنوز فعال نیست.")
    phone = normalize_phone(body.phone)
    lock(db, row.tenant_id)
    db.refresh(row)
    if row.lease_until and row.lease_until > now_utc():
        fail(409, "TURN_BUSY", "گفت‌وگو در حال پردازش است.")
    conversation = Conversation(_TurnTransaction(db), row)
    conversation.ctx["sms_pending"] = True
    conversation.ctx["sms_return_state"] = row.state
    conversation.ctx["sms_receiver"] = receiver
    result = conversation.otp(phone)
    db.commit()
    return result


class InboundSMS(StrictModel):
    receiver: str = Field(pattern=r"^\+?[0-9]{3,20}$")
    sender: str = Field(min_length=8, max_length=30)
    message_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,120}$")
    text: str = Field(min_length=1, max_length=2000)


def ingest(db, body: InboundSMS):
    try:
        routes = json.loads(os.getenv("SMS_INBOUND_TENANTS_JSON", "{}"))
        slug = routes.get(body.receiver)
    except (ValueError, AttributeError):
        fail(503, "SMS_ROUTE_INVALID", "مسیر پیامک آماده نیست.")
    tenant = db.scalar(select(Tenant).where(Tenant.slug == slug, Tenant.active.is_(True))) if slug else None
    if not tenant:
        fail(403, "SMS_RECEIVER_NOT_AUTHORIZED", "شماره گیرنده پیامک مجاز نیست.")
    phone = normalize_phone(body.sender)
    subject = hash_phone(phone)
    lock(db, tenant.id)
    checksum = digest(json.dumps(body.model_dump(), ensure_ascii=False, sort_keys=True))
    previous = db.scalar(select(SmsConversation).where(SmsConversation.tenant_id == tenant.id, SmsConversation.inbound_reference == body.message_id))
    if previous:
        if previous.request_hash != checksum or previous.phone_hash != subject:
            fail(409, "SMS_RECEIPT_REPLAY_MISMATCH", "رسید تکراری محتوای دیگری دارد.")
        if previous.turn_id:
            return {"status": "ACCEPTED", "receipt_id": previous.id, "reply_status": "QUEUED", "call_id": previous.call_id, "replayed": True}
        row = db.get(CallSession, previous.call_id)
    else:
        rows = [call for call in db.scalars(select(CallSession).where(CallSession.tenant_id == tenant.id,
            CallSession.phone_hash == subject, CallSession.processing_consent.is_(True), CallSession.ended_at.is_(None), CallSession.expires_at > now_utc()))
            if context(call).get("sms_enabled") and context(call).get("sms_subject") == subject]
        if len(rows) != 1:
            fail(409, "SMS_SESSION_REQUIRED", "یک نشست فعال با شماره تاییدشده و رضایت پیامکی لازم است.")
        row = rows[0]
        previous = SmsConversation(tenant_id=tenant.id, call_id=row.id, phone_hash=subject,
                                   inbound_reference=body.message_id, request_hash=checksum)
        db.add(previous)
        db.flush()
    if row.ended_at or row.expires_at <= now_utc() or not row.processing_consent:
        fail(410, "SMS_SESSION_EXPIRED", "نشست پیامکی پایان یافته است.")
    data = context(row)
    if not data.get("sms_enabled") or data.get("sms_subject") != subject or data.get("sms_receiver") != body.receiver:
        fail(403, "SMS_SESSION_REQUIRED", "نشست پیامکی این فرستنده و گیرنده تایید نشده است.")
    data.update(phone=phone, verified_phone=subject)
    save_context(row, data)
    db.commit()
    # Same id and request hash recover a crash after turn commit but before reply enqueue.
    result = execute_turn(db, row, TurnInput(text=body.text, request_id="sms:" + digest(body.message_id)[:64]))
    reply = result["reply"]
    if len(reply.encode("utf-16-be")) // 2 > 670:
        lock(db, tenant.id)
        request_handoff(db, row, "booking_exception")
        reply = "توضیح کامل این درخواست از سقف پیامک بیشتر است. برای جلوگیری از حذف بخشی از شرایط، درخواست پیگیری پذیرش ثبت شد؛ هنوز اتصال انسانی برقرار نشده است."
        data = context(row)
        data["last_reply"] = reply
        save_context(row, data)
    lock(db, tenant.id)
    # Caller identity remains the enrolled SMS sender even when a new booking
    # cycle clears transient patient fields. The signed receipt cannot move it.
    row.phone_hash = subject
    db.refresh(previous)
    if previous.turn_id is None:
        previous.turn_id = result["turn_id"]
        db.add(MessageOutbox(tenant_id=tenant.id, recipient_encrypted=encrypt(phone), purpose="conversation_reply",
            template="conversation_reply_v1", payload={"text_encrypted": encrypt(reply), "call_id": row.id, "turn_id": result["turn_id"]},
            dedupe_key="sms-reply:" + previous.id))
    db.commit()
    return {"status": "ACCEPTED", "receipt_id": previous.id, "reply_status": "QUEUED", "call_id": row.id}


@router.post("/internal/sms/inbound")
async def inbound(request: Request, db: Session = Depends(get_db)):
    db.rollback()
    raw = bytearray()
    try:
        async with asyncio.timeout(10):
            async for chunk in request.stream():
                if len(raw) + len(chunk) > 16_000:
                    fail(413, "SMS_RECEIPT_TOO_LARGE", "رسید پیامک بیش از حد بزرگ است.")
                raw.extend(chunk)
    except TimeoutError:
        fail(408, "SMS_RECEIPT_TIMEOUT", "مهلت دریافت رسید پیامک پایان یافت.")
    if not verify_webhook(bytes(raw), request.headers.get("X-Timestamp", ""), request.headers.get("X-Signature", ""), os.getenv("SMS_INBOUND_WEBHOOK_SECRET", "")):
        fail(401, "INVALID_SIGNATURE", "رسید معتبر درگاه پیامک لازم است.")
    try:
        body = InboundSMS.model_validate_json(raw)
    except ValueError:
        fail(422, "INVALID_SMS_RECEIPT", "ساختار رسید پیامک معتبر نیست.")
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(ingest, db, body)
