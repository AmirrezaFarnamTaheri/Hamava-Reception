"""Executable acceptance for consent-bound outreach and financial reconciliation."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import threading

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import delete, func, select, update

from receptionist.core import ReceptionService
from receptionist.db import get_db, now_utc
from receptionist.models import Appointment, AuditEvent, Membership, MessageOutbox, Occupancy, SlotHold, StaffTask, Tenant, User
from receptionist.models_ext import PaymentAdjustment, PaymentDispute, RefundReview
from receptionist.models_ops import RefundLedger, WaitlistEntry, WaitlistOffer
from receptionist.models_outreach import AppointmentResponse, CapacityRelease, FollowupEnrollment, OutreachPolicy
from receptionist.models_partner import ChannelPermission
from receptionist.operations import (
    RefundEvidence,
    RefundInput,
    RevokeConsentInput,
    accept_offer,
    delete_subject,
    offer_waitlist,
    payment_callback,
    record_refund,
    request_refund,
    revoke_consent,
    run_jobs,
    run_once,
)
from receptionist.operations_extensions import (
    DisputeInput,
    DisputeUpdateInput,
    RefundReviewInput,
    create_dispute,
    review_refund,
    router as extensions_router,
    update_dispute,
)
from receptionist.operations_outreach import (
    ApproveOutreachInput,
    FollowupInput,
    OutreachPolicyInput,
    PatientResponseInput,
    RejectWaitlistInput,
    ResponseLinkInput,
    ResponseTokenInput,
    approve_outreach,
    approved_followup,
    create_response_link,
    enroll_followup,
    patient_response,
    process_auto_offers,
    publish_outreach_policy,
    reject_waitlist_offer,
    router,
    schedule_outreach,
    view_response,
)
from receptionist.security import actor_for, decrypt, issue_token
from test_core import database as database
from test_core import create, slot_for
from test_ops import _waitlist
from test_ops_review import settled_payment


def owner(db, tenant="clinic-bahar"):
    return actor_for(db, db.get(User, "demo-owner"), tenant)


def publish(db, **changes):
    row = db.get(OutreachPolicy, "clinic-bahar")
    data = {"version": row.version if row else 1, "reminder_offsets_minutes": []}
    return publish_outreach_policy(OutreachPolicyInput(**{**data, **changes}), owner(db), db)


def clinician(db):
    user = User(
        id="review-clinician",
        name="مسئول بالینی آزمایشی",
        email="clinical@example.test",
        password_hash=db.get(User, "demo-owner").password_hash,
    )
    db.add(user)
    db.flush()
    db.add(Membership(user_id=user.id, tenant_id="clinic-bahar", role="clinician"))
    db.commit()
    return actor_for(db, user, "clinic-bahar")


def reminder_booking(db, minutes=120):
    db.execute(delete(MessageOutbox))
    db.execute(update(Appointment).values(reminder_opt_in=False))
    result = create(db, reminder_opt_in=True)
    booking = db.get(Appointment, result["id"])
    booking.start_at = now_utc() + timedelta(minutes=minutes)
    booking.end_at = booking.start_at + timedelta(minutes=30)
    booking.occupied_until = booking.end_at
    db.get(Tenant, booking.tenant_id).quiet_hours = {"start": "00:00", "end": "00:01"}
    db.commit()
    return booking


def enrollment(db):
    result = create(db)
    booking = db.get(Appointment, result["id"])
    booking.attendance = "ATTENDED"
    booking.start_at = now_utc() - timedelta(days=1, hours=2)
    booking.end_at = booking.start_at + timedelta(minutes=30)
    booking.occupied_until = booking.end_at
    db.get(Tenant, booking.tenant_id).quiet_hours = {"start": "00:00", "end": "00:01"}
    db.commit()
    policy = publish(db, followup_enabled=True, followup_offsets_days=[1, 7])
    clinical = clinician(db)
    approve_outreach(ApproveOutreachInput(version=policy["version"], confirmed=True), clinical, db)
    result = enroll_followup(
        FollowupInput(appointment_id=booking.id, policy_version=policy["version"], confirmed_consent=True), owner(db), db
    )
    return booking, result, clinical


def response_link(db, booking):
    link = create_response_link(booking.id, ResponseLinkInput(version=booking.version), owner(db), db)
    return link, link["public_path"].split("#", 1)[1]


def test_reminder_offsets_choose_latest_due_once_without_backlog_burst(database):
    with database() as db:
        booking = reminder_booking(db, minutes=50)
        publish(db, reminder_offsets_minutes=[1440, 120, 30])
        tenant = db.get(Tenant, booking.tenant_id)
        first = schedule_outreach(db, tenant, now_utc())
        db.commit()
        assert first["reminders_queued"] == 1
        rows = list(db.scalars(select(MessageOutbox).where(MessageOutbox.purpose == "reminder")))
        assert len(rows) == 1 and rows[0].payload["offset_minutes"] == 120
        assert schedule_outreach(db, tenant, now_utc())["reminders_queued"] == 0
        assert schedule_outreach(db, tenant, booking.start_at - timedelta(minutes=20))["reminders_queued"] == 1
        db.commit()
        assert db.scalar(select(func.count()).select_from(AppointmentResponse)) == 1
        assert db.scalar(select(func.count()).select_from(MessageOutbox).where(MessageOutbox.purpose == "reminder")) == 2


@pytest.mark.asyncio
async def test_disabled_offset_suppresses_already_queued_reminder(database):
    with database() as db:
        booking = reminder_booking(db)
        publish(db, reminder_offsets_minutes=[1440])
        schedule_outreach(db, db.get(Tenant, booking.tenant_id), now_utc())
        db.commit()
        message_id = db.scalar(select(MessageOutbox.id).where(MessageOutbox.purpose == "reminder"))
        publish(db, reminder_offsets_minutes=[])
    await run_once(database)
    with database() as db:
        assert db.get(MessageOutbox, message_id).status == "SUPPRESSED"


@pytest.mark.asyncio
async def test_channel_denial_overrides_grant_at_schedule_and_dispatch(database):
    with database() as db:
        booking = reminder_booking(db)
        publish(db, reminder_offsets_minutes=[1440])
        row = ChannelPermission(
            tenant_id=booking.tenant_id,
            subject_hash=booking.phone_hash,
            channel="sms",
            purpose="reminder",
            granted=False,
            evidence_reference="synthetic patient denial",
            recorded_by="demo-owner",
        )
        db.add(row)
        db.commit()
        assert schedule_outreach(db, db.get(Tenant, booking.tenant_id), now_utc())["reminders_queued"] == 0
        row.granted = True
        db.commit()
        assert schedule_outreach(db, db.get(Tenant, booking.tenant_id), now_utc())["reminders_queued"] == 1
        db.commit()
        message_id = db.scalar(select(MessageOutbox.id).where(MessageOutbox.purpose == "reminder"))
        row.granted = False
        db.commit()
    await run_once(database)
    with database() as db:
        assert db.get(MessageOutbox, message_id).status == "SUPPRESSED"


def test_followup_requires_current_clinician_approval_attendance_and_consent(database):
    with database() as db:
        booking = db.get(Appointment, create(db)["id"])
        policy = publish(db, followup_enabled=True, followup_offsets_days=[1, 7])
        data = FollowupInput(appointment_id=booking.id, policy_version=policy["version"], confirmed_consent=True)
        with pytest.raises(HTTPException) as error:
            enroll_followup(data, owner(db), db)
        assert error.value.detail["code"] == "CLINICIAN_APPROVAL_REQUIRED"
        with pytest.raises(HTTPException):
            approve_outreach(ApproveOutreachInput(version=policy["version"], confirmed=True), owner(db), db)
        clinical = clinician(db)
        approve_outreach(ApproveOutreachInput(version=policy["version"], confirmed=True), clinical, db)
        with pytest.raises(HTTPException) as error:
            enroll_followup(data, owner(db), db)
        assert error.value.detail["code"] == "FOLLOWUP_CONSENT_REQUIRED"
        booking.attendance = "ATTENDED"
        db.commit()
        with pytest.raises(HTTPException):
            enroll_followup(data.model_copy(update={"confirmed_consent": False}), owner(db), db)
        created = enroll_followup(data, owner(db), db)
        assert enroll_followup(data, owner(db), db)["id"] == created["id"]
        assert db.scalar(select(func.count()).select_from(FollowupEnrollment)) == 1
        publish(db, followup_enabled=True, followup_offsets_days=[1, 14])
        assert not approved_followup(db, db.get(OutreachPolicy, "clinic-bahar"))


@pytest.mark.asyncio
@pytest.mark.parametrize("revocation", ["patient", "clinician", "policy", "channel"])
async def test_followup_rechecks_all_approvals_at_dispatch(database, revocation):
    with database() as db:
        booking, enrolled, clinical = enrollment(db)
        schedule_outreach(db, db.get(Tenant, booking.tenant_id), now_utc())
        db.commit()
        message_id = db.scalar(select(MessageOutbox.id).where(MessageOutbox.purpose == "followup"))
        assert message_id is not None
        if revocation == "patient":
            revoke_consent(RevokeConsentInput(phone="09123456789", purposes=["followup"]), owner(db), db)
            assert db.get(FollowupEnrollment, enrolled["id"]).status == "REVOKED"
        elif revocation == "clinician":
            db.get(User, clinical.id).active = False
        elif revocation == "policy":
            publish(db, followup_enabled=True, followup_offsets_days=[1, 7])
        else:
            db.add(
                ChannelPermission(
                    tenant_id=booking.tenant_id,
                    subject_hash=booking.phone_hash,
                    channel="sms",
                    purpose="followup",
                    granted=False,
                    evidence_reference="synthetic denial",
                    recorded_by="demo-owner",
                )
            )
        db.commit()
    await run_once(database)
    with database() as db:
        assert db.get(MessageOutbox, message_id).status == "SUPPRESSED"


def test_response_token_is_minimal_versioned_and_records_intent_not_attendance(database):
    with database() as db:
        booking = db.get(Appointment, create(db)["id"])
        link, token = response_link(db, booking)
        view = view_response(link["response_id"], ResponseTokenInput(token=token), db)
        assert {"clinic", "reference", "display", "response_status"} <= view.keys()
        serialized = json.dumps(view, ensure_ascii=False)
        assert "09123456789" not in serialized and "مراجع آزمایشی" not in serialized
        with pytest.raises(HTTPException) as error:
            view_response(link["response_id"], ResponseTokenInput(token="x" * 32), db)
        assert error.value.status_code == 404
        action = PatientResponseInput(token=token, action="CONFIRM")
        result = patient_response(link["response_id"], action, db)
        assert result["response_status"] == "CONFIRMED_ATTENDANCE_INTENT"
        assert booking.attendance is None and booking.status == "CONFIRMED"
        assert patient_response(link["response_id"], action, db)["action"] == "CONFIRM"
        with pytest.raises(HTTPException) as error:
            patient_response(link["response_id"], action.model_copy(update={"action": "DECLINE"}), db)
        assert error.value.detail["code"] == "RESPONSE_ALREADY_USED"


@pytest.mark.parametrize("late", [False, True])
def test_patient_decline_applies_actual_cancellation_window(database, late):
    with database() as db:
        booking = db.get(Appointment, create(db)["id"])
        if late:
            booking.start_at = now_utc() + timedelta(minutes=30)
            db.commit()
        link, token = response_link(db, booking)
        result = patient_response(link["response_id"], PatientResponseInput(token=token, action="DECLINE"), db)
        if late:
            assert result["response_status"] == "DECLINE_REVIEW_REQUIRED" and booking.status == "CONFIRMED"
            assert db.scalar(select(func.count()).select_from(StaffTask).where(StaffTask.reason == "PATIENT_DECLINE_REVIEW")) == 1
            assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == booking.id)) > 0
        else:
            assert result["response_status"] == "DECLINED_CANCELED" and booking.status == "CANCELED"
            assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == booking.id)) == 0
            assert db.scalar(select(func.count()).select_from(CapacityRelease).where(CapacityRelease.source_id == booking.id)) == 1


@pytest.mark.parametrize("invalidator", ["revision", "expiry", "erasure"])
def test_response_token_stale_expired_or_erased_is_rejected(database, invalidator):
    with database() as db:
        booking = db.get(Appointment, create(db)["id"])
        link, token = response_link(db, booking)
        if invalidator == "revision":
            booking.version += 1
            db.commit()
        elif invalidator == "expiry":
            db.get(AppointmentResponse, link["response_id"]).expires_at = now_utc() - timedelta(seconds=1)
            db.commit()
        else:
            delete_subject(db, booking.tenant_id, "09123456789")
        with pytest.raises(HTTPException) as error:
            patient_response(link["response_id"], PatientResponseInput(token=token, action="CONFIRM"), db)
        assert error.value.status_code == {"revision": 409, "expiry": 410, "erasure": 404}[invalidator]
        assert booking.status == "CONFIRMED"


def test_public_response_stops_when_clinic_disruption_requires_staff_decision(database):
    from receptionist.operations_extensions import create_disruption
    from test_operations_extensions import closure_input

    with database() as db:
        booking = db.get(Appointment, create(db)["id"])
        link, token = response_link(db, booking)
        create_disruption(closure_input(db, booking.start_at), owner(db), db)
        with pytest.raises(HTTPException) as error:
            patient_response(link["response_id"], PatientResponseInput(token=token, action="CONFIRM"), db)
        assert error.value.detail["code"] == "SCHEDULE_DISRUPTED"
        assert booking.status == "CONFIRMED" and db.get(AppointmentResponse, link["response_id"]).action is None


def cancel_for_capacity(db):
    booking = create(db)
    ReceptionService(db, "clinic-bahar").cancel_appointment(booking["id"], "auto-capacity-cancel", booking["version"], verified=True)
    return booking


def test_auto_offer_requires_opt_in_and_real_capacity_before_holding(database):
    with database() as db:
        _waitlist(db)
        booking = cancel_for_capacity(db)
        assert process_auto_offers(db)["automatic_offers"] == 0
        publish(db, waitlist_auto_offer=True, waitlist_offer_limit_per_run=1)
        result = process_auto_offers(db)
        assert result["automatic_offers"] == 1 and result["capacity_events_checked"] == 1
        event = db.scalar(select(CapacityRelease).where(CapacityRelease.source_id == booking["id"]))
        assert event.status == "PROCESSED" and event.offer_id
        offer = db.get(WaitlistOffer, event.offer_id)
        assert db.get(SlotHold, offer.hold_id).status == "HELD"
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == offer.hold_id)) > 0
        assert process_auto_offers(db)["automatic_offers"] == 0
        accepted = accept_offer(db, offer.id, decrypt(offer.token_encrypted), True)
        assert accepted["status"] == "CONFIRMED"


def test_capacity_event_does_not_override_a_new_authoritative_booking(database):
    with database() as db:
        _waitlist(db)
        first = cancel_for_capacity(db)
        original = db.get(Appointment, first["id"])
        service = ReceptionService(db, "clinic-bahar")
        token = service._encode_slot(service.tenant(), original.provider_id, original.service_id, original.start_at)
        current = create(db, token, key="capacity-new-booking")
        publish(db, waitlist_auto_offer=True)
        assert process_auto_offers(db)["automatic_offers"] == 0
        event = db.scalar(select(CapacityRelease).where(CapacityRelease.source_id == first["id"]))
        assert event.status == "SKIPPED"
        assert db.get(Appointment, current["id"]).status == "CONFIRMED"
        assert db.scalar(select(func.count()).select_from(WaitlistOffer)) == 0


def test_concurrent_auto_workers_claim_capacity_once(database):
    with database() as db:
        _waitlist(db)
        cancel_for_capacity(db)
        publish(db, waitlist_auto_offer=True)
    barrier = threading.Barrier(2)

    def worker(_):
        with database() as db:
            barrier.wait()
            return process_auto_offers(db)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, [0, 1]))
    assert sum(row["automatic_offers"] for row in results) == 1
    with database() as db:
        assert db.scalar(select(func.count()).select_from(WaitlistOffer)) == 1


def test_waitlist_rejection_and_expiry_audit_and_release_holds(database):
    with database() as db:
        _waitlist(db)
        offer = offer_waitlist(db, "clinic-bahar", slot_for(db))
        rejected = reject_waitlist_offer(offer["id"], RejectWaitlistInput(confirmed=True, reason="no_longer_needed"), owner(db), db)
        assert rejected["status"] == "REJECTED" and rejected["entry_status"] == "WITHDRAWN"
        assert db.get(SlotHold, db.get(WaitlistOffer, offer["id"]).hold_id).status == "RELEASED"
        with pytest.raises(HTTPException):
            accept_offer(db, offer["id"], offer["accept_token"], True)
        _waitlist(db, "09123456788")
        later = offer_waitlist(db, "clinic-bahar", slot_for(db))
        row = db.get(WaitlistOffer, later["id"])
        row.expires_at = now_utc() - timedelta(seconds=1)
        db.commit()
        run_jobs(db)
        db.refresh(row)
        assert row.status == "EXPIRED"
        assert db.get(WaitlistEntry, row.entry_id).status == "WAITING"
        actions = set(db.scalars(select(AuditEvent.action)))
        assert {"waitlist.rejected", "waitlist.expired"} <= actions
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == row.hold_id)) == 0


@pytest.mark.asyncio
async def test_refund_refusal_releases_reservation_once_and_preserves_money_fact(database):
    with database() as db:
        payment, actor = await settled_payment(db)
        refund = request_refund(
            payment.id, RefundInput(amount_toman=60000, reason="درخواست آزمایشی", idempotency_key="refusal-request"), actor, db
        )
        data = RefundReviewInput(action="REFUSE", reason="سیاست بازپرداخت بررسی شد", confirmed=True, idempotency_key="refusal-review")
        result = review_refund(refund["id"], data, actor, db)
        assert result["status"] == "REFUSED" and result["external_transfer_performed"] is False
        assert review_refund(refund["id"], data, actor, db)["status"] == "REFUSED"
        db.refresh(payment)
        assert payment.refund_reserved_toman == 0 and payment.status == "SETTLED"
        assert db.scalar(select(func.count()).select_from(RefundReview)) == 1
        request_refund(
            payment.id, RefundInput(amount_toman=100000, reason="درخواست اصلاح‌شده", idempotency_key="refusal-new-request"), actor, db
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["failure", "completion"])
async def test_uncertain_refund_stays_reserved_until_evidenced_outcome(database, outcome):
    with database() as db:
        payment, actor = await settled_payment(db)
        refund = request_refund(
            payment.id, RefundInput(amount_toman=100000, reason="بررسی آزمایشی", idempotency_key="reconcile-request"), actor, db
        )
        pending = RefundReviewInput(
            action="RECONCILE_PENDING",
            reason="در انتظار تطبیق درگاه",
            provider_reference="synthetic-case-01",
            confirmed=True,
            idempotency_key="reconcile-pending",
        )
        assert review_refund(refund["id"], pending, actor, db)["status"] == "RECONCILING"
        with pytest.raises(HTTPException) as error:
            review_refund(refund["id"], pending.model_copy(update={"action": "REFUSE", "idempotency_key": "unsafe-refusal"}), actor, db)
        assert error.value.detail["code"] == "REFUND_OUTCOME_UNCERTAIN"
        assert payment.refund_reserved_toman == 100000
        if outcome == "failure":
            result = review_refund(
                refund["id"], pending.model_copy(update={"action": "RECONCILE_FAILED", "idempotency_key": "reconcile-failed"}), actor, db
            )
            assert result["status"] == "FAILED"
            db.refresh(payment)
            assert payment.refund_reserved_toman == 0 and payment.status == "SETTLED"
        else:
            assert (
                record_refund(refund["id"], RefundEvidence(provider_reference="confirmed-refund-evidence", confirmed=True), actor, db)[
                    "status"
                ]
                == "COMPLETED"
            )
            assert db.get(RefundLedger, refund["id"]).status == "COMPLETED"
            db.refresh(payment)
            assert payment.status == "REFUNDED"


@pytest.mark.asyncio
async def test_dispute_loss_appends_one_adjustment_without_rewriting_settlement(database):
    with database() as db:
        payment, actor = await settled_payment(db)
        original_reference = payment.provider_reference
        data = DisputeInput(
            amount_toman=80000,
            provider_case_reference="synthetic-dispute-01",
            reason="اختلاف آزمایشی",
            confirmed=True,
            idempotency_key="dispute-create-01",
        )
        case = create_dispute(payment.id, data, actor, db)
        assert create_dispute(payment.id, data, actor, db)["id"] == case["id"]
        change = DisputeUpdateInput(
            version=case["version"], status="LOST", reason="مدرک نتیجه ثبت شد", confirmed=True, idempotency_key="dispute-lost-01"
        )
        result = update_dispute(case["id"], change, actor, db)
        assert result["adjustment"]["amount_toman"] == -80000
        assert update_dispute(case["id"], change, actor, db)["version"] == 2
        assert db.scalar(select(func.count()).select_from(PaymentAdjustment)) == 1
        db.refresh(payment)
        assert payment.status == "SETTLED" and payment.provider_reference == original_reference
        second = create_dispute(
            payment.id,
            data.model_copy(update={"provider_case_reference": "synthetic-dispute-02", "idempotency_key": "dispute-create-02"}),
            actor,
            db,
        )
        with pytest.raises(HTTPException) as error:
            update_dispute(second["id"], change.model_copy(update={"version": 1, "idempotency_key": "dispute-lost-02"}), actor, db)
        assert error.value.detail["code"] == "CHARGEBACK_EXCEEDS_PAYMENT"
        assert db.get(PaymentDispute, second["id"]).status == "OPEN"
        with pytest.raises(HTTPException) as error:
            request_refund(
                payment.id, RefundInput(amount_toman=30000, reason="مانده آزمایشی", idempotency_key="chargeback-refund-cap"), actor, db
            )
        assert error.value.detail["code"] == "REFUND_EXCEEDS_PAYMENT"
        update_dispute(
            case["id"], change.model_copy(update={"version": 2, "status": "CLOSED", "idempotency_key": "dispute-close-01"}), actor, db
        )
        assert (
            db.scalar(select(func.count()).select_from(StaffTask).where(StaffTask.reason == "PAYMENT_DISPUTE", StaffTask.status == "OPEN"))
            > 0
        )
        update_dispute(
            second["id"], change.model_copy(update={"version": 1, "status": "WON", "idempotency_key": "dispute-won-02"}), actor, db
        )
        update_dispute(
            second["id"], change.model_copy(update={"version": 2, "status": "CLOSED", "idempotency_key": "dispute-close-02"}), actor, db
        )
        assert (
            db.scalar(select(func.count()).select_from(StaffTask).where(StaffTask.reason == "PAYMENT_DISPUTE", StaffTask.status == "OPEN"))
            == 0
        )


@pytest.mark.asyncio
async def test_gateway_verification_holds_no_database_transaction(database, monkeypatch):
    from test_payment_policy import configure_operator, make_intent

    configure_operator(monkeypatch)
    with database() as db:
        payment, _ = await make_intent(db)
        payment.authority, payment.status = "SYNTHETIC-AUTHORITY", "PENDING"
        db.commit()

        class LocalVerifier:
            def __init__(self, **kwargs):
                pass

            async def verify(self, authority, amount):
                assert not db.in_transaction()
                assert authority == "SYNTHETIC-AUTHORITY" and amount == 100000
                return {"reference": "SYNTHETIC-VERIFIED-01"}

        monkeypatch.setattr("receptionist.payment_policy.ZarinpalGateway", LocalVerifier)
        assert (await payment_callback("SYNTHETIC-AUTHORITY", "OK", db))["status"] == "SETTLED"


@pytest.mark.asyncio
async def test_outreach_http_authorization_and_anonymous_capability_response(database):
    app = FastAPI()
    app.include_router(router)
    app.include_router(extensions_router)

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with database() as db:
        booking = create(db)
        owner_token = issue_token(db.get(User, "demo-owner"), "clinic-bahar")
        other_token = issue_token(db.get(User, "demo-owner"), "clinic-niloufar")
        staff_token = issue_token(db.get(User, "demo-receptionist"), "clinic-bahar")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/operations/outreach-policy")).status_code == 401
        payload = {"version": 1, "followup_enabled": True, "followup_offsets_days": [7]}
        assert (
            await client.put("/api/v1/operations/outreach-policy", json=payload, headers={"Authorization": "Bearer " + staff_token})
        ).status_code == 403
        assert (
            await client.post(
                "/api/v1/operations/outreach-policy/approve",
                json={"version": 1, "confirmed": True},
                headers={"Authorization": "Bearer " + owner_token},
            )
        ).status_code == 403
        path = "/api/v1/operations/appointments/" + booking["id"] + "/response-link"
        assert (
            await client.post(path, json={"version": booking["version"]}, headers={"Authorization": "Bearer " + other_token})
        ).status_code == 404
        created = await client.post(path, json={"version": booking["version"]}, headers={"Authorization": "Bearer " + owner_token})
        assert created.status_code == 200
        link = created.json()
        public_path = "/api/v1/public/appointments/responses/" + link["response_id"]
        token = link["public_path"].split("#", 1)[1]
        assert (await client.post(public_path + "/view", json={"token": token})).status_code == 200
        assert (await client.post(public_path, json={"token": token, "action": "CONFIRM"})).json()[
            "response_status"
        ] == "CONFIRMED_ATTENDANCE_INTENT"
