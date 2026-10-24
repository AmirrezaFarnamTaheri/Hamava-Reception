"""Business regressions for policy history, staff ownership and disruptions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import threading

from fastapi import FastAPI, HTTPException
import httpx
import pytest
from sqlalchemy import delete, func, select, update

from receptionist.api import dashboard, resolve_task
from receptionist.core import ReceptionService
from receptionist.db import get_db, now_utc
from receptionist.models import Appointment, AuditEvent, MessageOutbox, Occupancy, Service, SlotHold, StaffTask, Tenant, UsageEvent, User
from receptionist.models_ext import AppointmentImpact, CorrectionRecord, Disruption, PolicyRevision, TaskControl
from receptionist.operations import building, delete_subject, export_subject, run_once
from receptionist.operations_extensions import (
    CorrectionInput,
    DisruptionInput,
    ImpactDecisionInput,
    ResolveDisruptionInput,
    RestorePolicyInput,
    TaskActionInput,
    apply_task_action,
    correct_appointment,
    create_disruption,
    daily_digest,
    decide_impact,
    eligible_assignees,
    policy_history,
    preview_disruption,
    resolve_disruption,
    restore_policy,
    router,
)
from receptionist.schemas import TaskResolution
from receptionist.security import Actor, actor_for, current_actor, decrypt
from test_core import database as database
from test_core import create, slot_for


def actor_for_tenant(db, tenant="clinic-bahar", user="demo-owner"):
    return actor_for(db, db.get(User, user), tenant)


def make_task(db):
    row = StaffTask(tenant_id="clinic-bahar", reason="REVIEW_TEST", summary="درخواست آزمایشی")
    db.add(row)
    db.commit()
    return row


def test_privacy_export_and_erasure_cover_linked_staff_notes(database):
    with database() as db:
        actor = actor_for_tenant(db)
        booking = create(db)
        task = StaffTask(
            tenant_id=actor.tenant_id, appointment_id=booking["id"], reason="CONTACT_REVIEW", summary="اطلاعات خصوصی ساختگی مراجع آزمایشی"
        )
        unrelated = StaffTask(tenant_id="clinic-niloufar", reason="OTHER_TENANT", summary="متن مستقل مرکز دیگر")
        db.add_all([task, unrelated])
        db.commit()
        current = apply_task_action(db, actor, task.id, TaskActionInput(action="claim", version=1, idempotency_key="privacy-task-claim"))
        private_note = "یادداشت خصوصی ساختگی مراجع آزمایشی"
        apply_task_action(
            db,
            actor,
            task.id,
            TaskActionInput(action="resolve", version=current["version"], reason=private_note, idempotency_key="privacy-task-resolve"),
        )
        exported = export_subject(db, actor.tenant_id, "09123456789")
        exported_task = next(row for row in exported["staff_tasks"] if row["id"] == task.id)
        assert exported_task["notes"][-1]["text"] == private_note
        result = delete_subject(db, actor.tenant_id, "09123456789")
        assert result["staff_task_texts_erased"] == 1
        assert task.status == "RESOLVED" and private_note not in task.resolution
        assert unrelated.summary == "متن مستقل مرکز دیگر"
        erased = export_subject(db, actor.tenant_id, "09123456789")
        assert private_note not in json.dumps(erased, ensure_ascii=False)
        events = db.scalars(select(AuditEvent).where(AuditEvent.entity_type == "task", AuditEvent.entity_id == task.id))
        assert all(
            decrypt(event.details["reason_encrypted"]) == "privacy_erasure" for event in events if event.details.get("reason_encrypted")
        )


def closure_input(db, start, **overrides):
    values = {
        "kind": "EMERGENCY_CLOSURE",
        "start_at": start,
        "end_at": start + timedelta(hours=3),
        "reason": "تعطیلی آزمایشی برنامه",
        "expected_policy_version": db.get(Tenant, "clinic-bahar").settings_version,
        "idempotency_key": "review-closure-001",
        "confirmed": True,
    }
    return DisruptionInput(**{**values, **overrides})


def test_policy_restore_appends_history_and_rejects_stale_version(database):
    with database() as db:
        actor = actor_for_tenant(db)
        service = ReceptionService(db, actor.tenant_id, actor.id)
        before = service.settings_dict()
        changed = service.update_settings({"version": before["settings_version"], "name": "نام جدید آزمایشی"})
        assert changed["settings_version"] == before["settings_version"] + 1
        restored = restore_policy(
            before["settings_version"],
            RestorePolicyInput(expected_version=changed["settings_version"], reason="بازگردانی نسخه تاییدشده", confirmed=True),
            actor,
            db,
        )
        assert restored["name"] == before["name"] and restored["settings_version"] == before["settings_version"] + 2
        history = policy_history(actor, db)
        assert len(history["revisions"]) == 3
        assert history["revisions"][0]["restored_from"] == before["settings_version"]
        with pytest.raises(HTTPException) as error:
            restore_policy(
                before["settings_version"],
                RestorePolicyInput(expected_version=changed["settings_version"], reason="نسخه قدیمی", confirmed=True),
                actor,
                db,
            )
        assert error.value.detail["code"] == "STALE_VERSION"
        assert db.scalar(select(func.count()).select_from(PolicyRevision)) == 3


def test_policy_history_does_not_cross_tenants(database):
    with database() as db:
        actor = actor_for_tenant(db)
        ReceptionService(db, actor.tenant_id, actor.id).update_settings({"version": 1, "name": "نسخه دوم"})
        other = actor_for_tenant(db, "clinic-niloufar")
        assert len(policy_history(other, db)["revisions"]) == 1
        with pytest.raises(HTTPException) as error:
            restore_policy(2, RestorePolicyInput(expected_version=1, reason="کوشش آزمایشی", confirmed=True), other, db)
        assert error.value.status_code == 404


def test_concurrent_task_claim_has_one_owner(database):
    with database() as db:
        task_id = make_task(db).id
        actors = [actor_for_tenant(db), actor_for_tenant(db, user="demo-receptionist")]
    barrier = threading.Barrier(2)

    def claim(index):
        with database() as db:
            barrier.wait()
            try:
                return apply_task_action(
                    db, actors[index], task_id, TaskActionInput(action="claim", version=1, idempotency_key=f"claim-review-{index}")
                )["assignee_id"]
            except HTTPException as error:
                return error.detail["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(claim, [0, 1]))
    assert sum(value in {actor.id for actor in actors} for value in outcomes) == 1
    assert sum(value in {"TASK_ALREADY_CLAIMED", "STALE_VERSION"} for value in outcomes) == 1
    with database() as db:
        assert db.get(StaffTask, task_id).status == "IN_PROGRESS"
        assert db.get(TaskControl, task_id).version == 2


def test_task_lifecycle_idempotence_and_legacy_ownership(database):
    with database() as db:
        owner, receptionist = actor_for_tenant(db), actor_for_tenant(db, user="demo-receptionist")
        task = make_task(db)
        claim = TaskActionInput(action="claim", version=1, idempotency_key="lifecycle-claim-001")
        current = apply_task_action(db, owner, task.id, claim)
        assert apply_task_action(db, owner, task.id, claim)["version"] == 2
        with pytest.raises(HTTPException) as error:
            resolve_task(task.id, TaskResolution(resolution="بسته شود"), receptionist, db)
        assert error.value.detail["code"] == "TASK_OWNER_REQUIRED"
        for i, (action, status) in enumerate(
            [("pending", "PENDING"), ("callback", "CALLBACK"), ("resolve", "RESOLVED"), ("reopen", "OPEN")]
        ):
            current = apply_task_action(
                db,
                owner,
                task.id,
                TaskActionInput(
                    action=action,
                    version=current["version"],
                    idempotency_key=f"lifecycle-action-{i}",
                    reason="پیگیری آزمایشی",
                    callback_at=now_utc() + timedelta(hours=2) if action == "callback" else None,
                ),
            )
            assert current["status"] == status
        current = apply_task_action(
            db,
            owner,
            task.id,
            TaskActionInput(
                action="redirect",
                version=current["version"],
                idempotency_key="lifecycle-redirect",
                reason="واگذاری به پذیرش",
                assignee_id=receptionist.id,
            ),
        )
        assert current["assignee_id"] == receptionist.id and current["status"] == "IN_PROGRESS"
        current = apply_task_action(
            db,
            receptionist,
            task.id,
            TaskActionInput(action="reject", version=current["version"], idempotency_key="lifecycle-reject", reason="نیاز به مسئول دیگر"),
        )
        assert current["status"] == "OPEN" and current["assignee_id"] is None
        closed = resolve_task(task.id, TaskResolution(resolution="انجام شد"), receptionist, db)
        assert closed["status"] == "RESOLVED" and closed["assignee_id"] == receptionist.id


def test_task_invalid_callback_and_cross_tenant_assignee_are_rejected(database):
    with database() as db:
        owner = actor_for_tenant(db)
        task = make_task(db)
        current = apply_task_action(db, owner, task.id, TaskActionInput(action="claim", version=1, idempotency_key="callback-claim"))
        for action, values, code in [
            ("callback", {"callback_at": now_utc() - timedelta(minutes=1)}, "INVALID_CALLBACK_TIME"),
            ("reassign", {"assignee_id": "demo-other"}, "INVALID_ASSIGNEE"),
        ]:
            with pytest.raises(HTTPException) as error:
                apply_task_action(
                    db,
                    owner,
                    task.id,
                    TaskActionInput(
                        action=action,
                        version=current["version"],
                        idempotency_key="invalid-action-" + action,
                        reason="درخواست آزمایشی",
                        **values,
                    ),
                )
            assert error.value.detail["code"] == code
        assert {row["user_id"] for row in eligible_assignees(owner, db)} == {"demo-owner", "demo-receptionist"}


def test_contact_correction_audit_redacts_and_erasure_covers_previous_number(database):
    with database() as db:
        actor = actor_for_tenant(db)
        booking = create(db, reminder_opt_in=True)
        data = CorrectionInput(
            version=booking["version"],
            idempotency_key="correct-contact-review",
            reason="اصلاح درخواست مراجعه‌کننده",
            confirmed=True,
            patient_name="نام اصلاح شده",
            phone="09123456788",
        )
        corrected = correct_appointment(db, actor, booking["id"], data)
        assert corrected["patient_name"] == "نام اصلاح شده" and corrected["phone_masked"].endswith("788")
        assert not corrected["reminder_opt_in"]
        assert correct_appointment(db, actor, booking["id"], data)["version"] == corrected["version"]
        record = db.scalar(select(CorrectionRecord).where(CorrectionRecord.appointment_id == booking["id"]))
        assert "09123456788" not in record.changes_encrypted
        events = list(db.scalars(select(AuditEvent).where(AuditEvent.action == "appointment.corrected")))
        assert all(
            "09123456788" not in json.dumps(event.details) and "نام اصلاح" not in json.dumps(event.details, ensure_ascii=False)
            for event in events
        )
        assert len(export_subject(db, "clinic-bahar", "09123456789")["corrections"]) == 1
        delete_subject(db, "clinic-bahar", "09123456789")
        db.refresh(record)
        assert decrypt(record.changes_encrypted) == "{}"
        assert db.get(Appointment, booking["id"]).status == "CONFIRMED"


def test_manual_time_correction_collision_retains_original_calendar_and_name(database):
    with database() as db:
        actor = actor_for_tenant(db)
        first_slot, second_slot = slot_for(db, index=0), slot_for(db, index=4)
        booking = create(db, first_slot)
        create(db, second_slot, key="second-for-conflict")
        count_before = db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == booking["id"]))
        with pytest.raises(HTTPException) as error:
            correct_appointment(
                db,
                actor,
                booking["id"],
                CorrectionInput(
                    version=booking["version"],
                    idempotency_key="correction-conflict",
                    reason="اصلاح آزمایشی",
                    confirmed=True,
                    slot_id=second_slot,
                    patient_name="نباید ثبت شود",
                ),
            )
        assert error.value.detail["code"] == "SLOT_TAKEN"
        row = db.get(Appointment, booking["id"])
        assert row.start_at.isoformat().replace("+00:00", "Z") == booking["start_at"]
        assert decrypt(row.patient_name_encrypted) == booking["patient_name"]
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == booking["id"])) == count_before


def test_service_correction_uses_new_duration_resources_price_approval(database):
    with database() as db:
        actor = actor_for_tenant(db)
        booking = create(db)
        db.add(
            Service(
                id="review-replacement",
                tenant_id="clinic-bahar",
                name="خدمت جایگزین",
                provider_ids=["provider-bahar-1"],
                duration_minutes=45,
                buffer_minutes=15,
                price_toman=700000,
                deposit_toman=0,
                resource_ids=["review-room"],
            )
        )
        db.commit()
        new_slot = slot_for(db, service="review-replacement", index=4)
        payload = CorrectionInput(
            version=booking["version"],
            idempotency_key="service-correction",
            reason="تغییر خدمت با تایید مراجعه‌کننده",
            confirmed=True,
            slot_id=new_slot,
        )
        with pytest.raises(HTTPException) as error:
            correct_appointment(db, actor, booking["id"], payload)
        assert error.value.detail["code"] == "PRICE_CONFIRMATION_REQUIRED"
        changed = correct_appointment(db, actor, booking["id"], payload.model_copy(update={"accept_price_change": True}))
        assert changed["service_id"] == "review-replacement" and changed["price_toman"] == 700000
        row = db.get(Appointment, booking["id"])
        assert row.end_at - row.start_at == timedelta(minutes=45) and row.occupied_until - row.start_at == timedelta(minutes=60)
        assert (
            db.scalar(
                select(func.count())
                .select_from(Occupancy)
                .where(Occupancy.owner_id == row.id, Occupancy.resource_id == "resource:review-room")
            )
            == 60
        )


@pytest.mark.asyncio
async def test_closure_blocks_new_slots_preserves_bookings_releases_holds_and_suppresses_stale_notice(database):
    with database() as db:
        actor = actor_for_tenant(db)
        slot, free_slot = slot_for(db), slot_for(db, index=4)
        booking = create(db, slot)
        original = db.get(Appointment, booking["id"])
        hold = ReceptionService(db, "clinic-bahar").hold(free_slot, "closure-hold")
        payload = closure_input(db, original.start_at)
        preview = preview_disruption(payload, actor, db)
        assert preview["affected_count"] == 1
        result = create_disruption(payload, actor, db)
        assert result["impacts"][0]["state"] == "CLOSURE_REVIEW"
        assert original.status == "CONFIRMED" and db.get(SlotHold, hold["id"]).status == "RELEASED"
        assert db.scalar(select(func.count()).select_from(Occupancy).where(Occupancy.owner_id == original.id)) > 0
        assert create_disruption(payload, actor, db)["id"] == result["id"]
        with pytest.raises(HTTPException) as error:
            create(db, free_slot, key="booking-closed-slot")
        assert error.value.detail["code"] == "STALE_POLICY"
        fresh_signed = ReceptionService(db, "clinic-bahar")._encode_slot(
            db.get(Tenant, "clinic-bahar"), original.provider_id, original.service_id, original.start_at + timedelta(hours=1)
        )
        with pytest.raises(HTTPException) as error:
            create(db, fresh_signed, key="fresh-closed-slot")
        assert error.value.detail["code"] == "SCHEDULE_DISRUPTED"
    await run_once(database)
    with database() as db:
        notice = db.scalar(select(MessageOutbox).where(MessageOutbox.appointment_id == booking["id"], MessageOutbox.purpose == "confirmed"))
        assert notice.status == "SUPPRESSED"
        disruption_notice = db.scalar(
            select(MessageOutbox).where(MessageOutbox.appointment_id == booking["id"], MessageOutbox.purpose == "disruption")
        )
        assert disruption_notice.status == "SIMULATED"


def test_closure_race_cannot_leave_untracked_new_booking(database):
    with database() as db:
        actor = actor_for_tenant(db)
        signed = slot_for(db)
        _, _, _, start, _ = ReceptionService(db, "clinic-bahar")._decode_slot(signed)
        db.commit()
        payload = closure_input(db, start)
    barrier = threading.Barrier(2)

    def contender(kind):
        with database() as db:
            barrier.wait()
            try:
                if kind == "booking":
                    return create(db, signed, key="booking-racing-closure")["id"]
                return create_disruption(payload, actor, db)["id"]
            except HTTPException as error:
                return error.detail["code"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(contender, ["booking", "closure"]))
    with database() as db:
        assert db.scalar(select(func.count()).select_from(Disruption)) == 1
        overlapping = list(db.scalars(select(Appointment).where(Appointment.tenant_id == "clinic-bahar", Appointment.start_at == start)))
        for booking in overlapping:
            assert db.scalar(select(AppointmentImpact.id).where(AppointmentImpact.appointment_id == booking.id))
        assert len(overlapping) in {0, 1}
        if not overlapping:
            assert results[0] in {"STALE_POLICY", "SCHEDULE_DISRUPTED"}


def test_disruption_resolution_never_silently_confirms_patient_outcome(database):
    with database() as db:
        actor = actor_for_tenant(db)
        booking = create(db)
        row = db.get(Appointment, booking["id"])
        closure = create_disruption(closure_input(db, row.start_at), actor, db)
        impact = closure["impacts"][0]
        with pytest.raises(HTTPException) as error:
            decide_impact(
                impact["id"],
                ImpactDecisionInput(
                    version=row.version,
                    decision="KEEP_ORIGINAL",
                    reason="زمان قبلی تایید شد",
                    confirmed=True,
                    idempotency_key="keep-before-unblock",
                ),
                actor,
                db,
            )
        assert error.value.detail["code"] == "DISRUPTION_STILL_ACTIVE"
        resolve_disruption(closure["id"], ResolveDisruptionInput(version=1, reason="محدودیت برطرف شد", confirmed=True), actor, db)
        assert db.get(AppointmentImpact, impact["id"]).state == "CLOSURE_REVIEW"
        kept = decide_impact(
            impact["id"],
            ImpactDecisionInput(
                version=row.version,
                decision="KEEP_ORIGINAL",
                reason="با مراجعه‌کننده هماهنگ شد",
                confirmed=True,
                idempotency_key="keep-after-unblock",
            ),
            actor,
            db,
        )
        assert kept["status"] == "CONFIRMED" and kept["disruptions"] == []


def test_late_arrival_records_review_without_extending_calendar(database):
    with database() as db:
        actor = actor_for_tenant(db, user="demo-receptionist")
        booking = create(db)
        row = db.get(Appointment, booking["id"])
        old_start, old_end = row.start_at, row.occupied_until
        payload = DisruptionInput(
            kind="LATE_ARRIVAL",
            appointment_id=row.id,
            delay_minutes=15,
            reason="مراجعه‌کننده تاخیر دارد",
            expected_policy_version=1,
            idempotency_key="late-arrival-review",
            confirmed=True,
        )
        result = create_disruption(payload, actor, db)
        assert result["impacts"][0]["state"] == "ARRIVAL_REVIEW"
        assert row.start_at == old_start and row.occupied_until == old_end


def test_digest_counts_duration_without_stt_and_keeps_unknown_attendance(database):
    with database() as db:
        actor = actor_for_tenant(db)
        db.execute(delete(UsageEvent))
        db.execute(update(Appointment).where(Appointment.tenant_id == actor.tenant_id).values(attendance=None))
        db.add_all(
            [
                UsageEvent(tenant_id=actor.tenant_id, kind="call_seconds", quantity=120, unit="second", cost_toman=40),
                UsageEvent(tenant_id=actor.tenant_id, kind="stt_audio_seconds", quantity=120, unit="second", cost_toman=10),
                UsageEvent(tenant_id="clinic-niloufar", kind="call_seconds", quantity=600, unit="second", cost_toman=100),
            ]
        )
        db.commit()
        result = daily_digest(None, actor, db)
        assert result["metrics"]["billable_minutes"] == 2 and result["usage"]["provider_cost_toman"] == 50
        assert result["metrics"]["attendance_unknown"] > 0 and result["metrics"]["attended"] == 0
        assert "not a reconstructed historical backlog" in result["definitions"]["open_cases"]


def test_dashboard_and_building_count_all_active_task_states_beyond_list_cap(database):
    with database() as db:
        actor = actor_for_tenant(db)
        db.add_all(
            [
                StaffTask(
                    tenant_id=actor.tenant_id,
                    reason="REVIEW_COUNT",
                    summary="کار آزمایشی",
                    status=["OPEN", "IN_PROGRESS", "PENDING", "CALLBACK"][i % 4],
                )
                for i in range(55)
            ]
        )
        db.commit()
        expected = db.scalar(
            select(func.count())
            .select_from(StaffTask)
            .where(StaffTask.tenant_id == actor.tenant_id, StaffTask.status.in_(["OPEN", "IN_PROGRESS", "PENDING", "CALLBACK"]))
        )
        panel = dashboard(actor, db)
        assert panel["metrics"]["pending_tasks"] == expected and len(panel["tasks"]) == 50
        assert next(row for row in building(actor, db)["clinics"] if row["id"] == actor.tenant_id)["open_tasks"] == expected


@pytest.mark.asyncio
async def test_extension_routes_enforce_roles_and_tenant_scope(database):
    app = FastAPI()
    app.include_router(router)

    def override_db():
        with database() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    actor = Actor("demo-receptionist", "clinic-bahar", "receptionist", "test", "test@example.invalid", "test")
    app.dependency_overrides[current_actor] = lambda: actor
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test.invalid") as client:
        assert (await client.get("/api/v1/operations/policies")).status_code == 403
        assert (await client.get("/api/v1/operations/assignees")).status_code == 200
        assert (await client.get("/api/v1/operations/digest")).status_code == 403
        actor = Actor("demo-owner", "clinic-niloufar", "owner", "test", "test@example.invalid", "test")
        with database() as db:
            task_id = make_task(db).id
        response = await client.post(
            f"/api/v1/operations/tasks/{task_id}/actions", json={"action": "claim", "version": 1, "idempotency_key": "other-clinic-claim"}
        )
        assert response.status_code == 404
