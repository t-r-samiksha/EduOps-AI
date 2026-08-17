"""Tests for the fee payment confirmation loop.

The security tests here are the point of the feature, not an accessory: the whole
value of a claim-and-review model is that the claimant cannot approve their own
claim. Each one is marked below.
"""

import uuid
from datetime import date, timedelta

import pytest

from app.main import app
from app.models.audit import AuditLogEntry
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.fees import FeePaymentRequest, FeeRecord, FeeReminder, FeeSchedule
from app.models.notification import Notification
from app.models.parent_student import ParentStudent
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user

ACADEMIC_YEAR = "2026-27"


def _override_user(role: str, user_id: int, school_id: int | None):
    def _fake_user():
        return CurrentUser(
            id=user_id, sub=str(uuid.uuid4()), email="test@example.com", role=role, school_id=school_id
        )

    app.dependency_overrides[get_current_user] = _fake_user


@pytest.fixture(autouse=True)
def _clear_user_override():
    yield
    app.dependency_overrides.pop(get_current_user, None)


def _user(db, role_name: str, school_id: int, name: str) -> User:
    role = db.query(Role).filter(Role.name == role_name).one()
    row = User(
        supabase_id=uuid.uuid4(),
        email=f"{name.replace(' ', '.').lower()}-{uuid.uuid4()}@example.com",
        full_name=name,
        role_id=role.id,
        school_id=school_id,
    )
    db.add(row)
    db.flush()
    return row


@pytest.fixture()
def seed(db_session):
    """One school with an overdue fee for a linked child, plus a second school with
    its own admin/parent/fee for the cross-tenant checks."""
    school = School(name="Payment Test School")
    other_school = School(name="Other Payment School")
    db_session.add_all([school, other_school])
    db_session.flush()

    admin = _user(db_session, "admin", school.id, "Admin One")
    principal = _user(db_session, "principal", school.id, "Principal One")
    teacher = _user(db_session, "teacher", school.id, "Teacher One")
    parent = _user(db_session, "parent", school.id, "Parent One")
    other_parent = _user(db_session, "parent", school.id, "Parent Two")
    student = _user(db_session, "student", school.id, "Child One")
    other_student = _user(db_session, "student", school.id, "Child Two")

    other_admin = _user(db_session, "admin", other_school.id, "Admin Two")
    other_school_parent = _user(db_session, "parent", other_school.id, "Parent Three")
    other_school_student = _user(db_session, "student", other_school.id, "Child Three")

    school_class = SchoolClass(
        name="Grade 5 - A", academic_year=ACADEMIC_YEAR, grade_level=5, section="A", school_id=school.id
    )
    db_session.add(school_class)
    db_session.flush()
    db_session.add_all(
        [
            Enrollment(student_id=student.id, class_id=school_class.id, is_primary=True),
            Enrollment(student_id=other_student.id, class_id=school_class.id, is_primary=True),
        ]
    )

    db_session.add_all(
        [
            ParentStudent(parent_id=parent.id, student_id=student.id),
            ParentStudent(parent_id=other_parent.id, student_id=other_student.id),
            ParentStudent(parent_id=other_school_parent.id, student_id=other_school_student.id),
        ]
    )

    due = date.today() - timedelta(days=20)
    schedule = FeeSchedule(
        school_id=school.id, class_id=None, academic_year=ACADEMIC_YEAR,
        fee_type="Term 1 Tuition", amount=4500.0, due_date=due,
    )
    other_schedule = FeeSchedule(
        school_id=other_school.id, class_id=None, academic_year=ACADEMIC_YEAR,
        fee_type="Term 1 Tuition", amount=4500.0, due_date=due,
    )
    db_session.add_all([schedule, other_schedule])
    db_session.flush()

    record = FeeRecord(
        student_id=student.id, fee_schedule_id=schedule.id, amount_due=4500.0,
        amount_paid=0.0, status="overdue", due_date=due,
    )
    paid_record = FeeRecord(
        student_id=other_student.id, fee_schedule_id=schedule.id, amount_due=4500.0,
        amount_paid=4500.0, status="paid", due_date=due,
    )
    other_record = FeeRecord(
        student_id=other_school_student.id, fee_schedule_id=other_schedule.id, amount_due=4500.0,
        amount_paid=0.0, status="overdue", due_date=due,
    )
    db_session.add_all([record, paid_record, other_record])
    db_session.commit()
    for row in (record, paid_record, other_record):
        db_session.refresh(row)

    return {
        "school": school, "other_school": other_school,
        "admin": admin, "principal": principal, "teacher": teacher,
        "parent": parent, "other_parent": other_parent,
        "student": student, "other_student": other_student,
        "other_admin": other_admin,
        "other_school_parent": other_school_parent, "other_school_student": other_school_student,
        "record": record, "paid_record": paid_record, "other_record": other_record,
        "schedule": schedule,
    }


def _submit_form(amount: float = 4500.0, method: str = "UPI", reference: str = "UPI/428817263541"):
    return {"payment_method": method, "payment_reference": reference, "amount": str(amount)}


def _submit(client, seed, *, amount: float = 4500.0, method: str = "UPI", reference: str = "UPI/428817263541",
            student=None, record=None):
    student = student or seed["student"]
    record = record or seed["record"]
    return client.post(
        f"/parent/child/{student.id}/fees/{record.id}/payment-request",
        data=_submit_form(amount, method, reference),
    )


def _as_parent(seed):
    _override_user("parent", seed["parent"].id, seed["school"].id)


def _as_admin(seed):
    _override_user("admin", seed["admin"].id, seed["school"].id)


def _open_request(db, seed):
    """Submit a request directly, bypassing HTTP - for tests about the review side."""
    request = FeePaymentRequest(
        fee_record_id=seed["record"].id,
        student_id=seed["student"].id,
        parent_id=seed["parent"].id,
        amount=4500.0,
        payment_method="UPI",
        payment_reference="UPI/428817263541",
        status="pending",
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


# =============================================================================
# THE FIVE REQUIRED SECURITY TESTS
# =============================================================================


def test_security_parent_cannot_submit_for_unlinked_child(client, seed):
    """SECURITY 1: a parent submitting against a child they aren't linked to."""
    _as_parent(seed)
    resp = _submit(client, seed, student=seed["other_student"], record=seed["paid_record"])
    assert resp.status_code == 403
    assert "Not linked" in resp.json()["detail"]


def test_security_parent_cannot_confirm_their_own_request(client, seed, db_session):
    """SECURITY 2: THE TRUST MODEL. A parent confirming their own claim would make
    the review step decorative and let them mark their own fees paid."""
    request = _open_request(db_session, seed)
    _as_parent(seed)

    resp = client.put(f"/admin/fee-payment-requests/{request.id}/confirm")
    assert resp.status_code == 403

    # And the fee record is untouched - not merely the response rejected.
    db_session.refresh(seed["record"])
    assert seed["record"].amount_paid == 0.0
    assert seed["record"].status == "overdue"
    db_session.refresh(request)
    assert request.status == "pending"


def test_security_parent_cannot_reject_their_own_request(client, seed, db_session):
    """The mirror of the above - a parent must not be able to clear their own claim
    out of the queue either."""
    request = _open_request(db_session, seed)
    _as_parent(seed)
    resp = client.put(
        f"/admin/fee-payment-requests/{request.id}/reject", json={"rejection_reason": "nope"}
    )
    assert resp.status_code == 403


def test_security_teacher_cannot_confirm(client, seed, db_session):
    """SECURITY 3: confirmation is an admin/principal action. A teacher has fee
    powers (PATCH mark-paid for their own class) but not this one."""
    request = _open_request(db_session, seed)
    _override_user("teacher", seed["teacher"].id, seed["school"].id)

    assert client.put(f"/admin/fee-payment-requests/{request.id}/confirm").status_code == 403
    assert client.get("/admin/fee-payment-requests").status_code == 403

    db_session.refresh(seed["record"])
    assert seed["record"].status == "overdue"


def test_security_admin_cannot_see_or_act_on_another_schools_requests(client, seed, db_session):
    """SECURITY 4: cross-tenant. fee_payment_requests has no school_id of its own, so
    scoping goes through fee_records -> users.school_id. This is the repo's documented
    recurring bug class."""
    request = _open_request(db_session, seed)

    # The other school's admin sees an empty queue...
    _override_user("admin", seed["other_admin"].id, seed["other_school"].id)
    queue = client.get("/admin/fee-payment-requests")
    assert queue.status_code == 200
    body = queue.json()
    assert body["items"] == []
    assert body["pending_count"] == 0

    # ...cannot read its proof route, confirm it, or reject it - 404, not 403, so
    # probing ids can't distinguish "exists, not yours" from "doesn't exist".
    assert client.get(f"/admin/fee-payment-requests/{request.id}/proof").status_code == 404
    assert client.put(f"/admin/fee-payment-requests/{request.id}/confirm").status_code == 404
    assert (
        client.put(
            f"/admin/fee-payment-requests/{request.id}/reject", json={"rejection_reason": "x"}
        ).status_code
        == 404
    )

    db_session.refresh(seed["record"])
    assert seed["record"].amount_paid == 0.0
    assert seed["record"].status == "overdue"


def test_security_second_pending_request_for_same_fee_is_rejected(client, seed, db_session):
    """SECURITY 5: without this a parent can flood the admin queue by double-submitting."""
    _as_parent(seed)
    first = _submit(client, seed, amount=1000.0)
    assert first.status_code == 200

    second = _submit(client, seed, amount=1000.0, reference="UPI/999")
    assert second.status_code == 400
    assert "already awaiting review" in second.json()["detail"]

    assert (
        db_session.query(FeePaymentRequest)
        .filter(FeePaymentRequest.fee_record_id == seed["record"].id)
        .count()
        == 1
    )


def test_security_partial_unique_index_blocks_a_second_pending_row_at_the_db_level(seed, db_session):
    """The route pre-check returns a clean 400, but two concurrent submits would both
    pass it - the partial unique index is the actual guarantee. Asserted directly
    against the DB, since HTTP can't produce the race."""
    from sqlalchemy.exc import IntegrityError

    _open_request(db_session, seed)
    duplicate = FeePaymentRequest(
        fee_record_id=seed["record"].id,
        student_id=seed["student"].id,
        parent_id=seed["parent"].id,
        amount=100.0,
        payment_method="Cash",
        payment_reference="dup",
        status="pending",
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


# =============================================================================
# Parent submission
# =============================================================================


def test_submit_creates_pending_request_and_notifies_reviewers(client, seed, db_session):
    _as_parent(seed)
    resp = _submit(client, seed)
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"
    assert body["amount"] == 4500.0
    assert body["payment_method"] == "UPI"
    assert body["has_proof"] is False

    # Every admin AND principal in the student's school, and nobody else.
    notes = (
        db_session.query(Notification)
        .filter(Notification.source_type == "fee_payment_request", Notification.source_id == body["id"])
        .all()
    )
    assert {n.user_id for n in notes} == {seed["admin"].id, seed["principal"].id}
    assert "Parent One" in notes[0].title
    assert "Child One" in notes[0].title
    assert notes[0].priority == "important"


def test_submit_leaves_the_fee_record_untouched(client, seed, db_session):
    """A claim is a claim. Nothing about submitting it may move the canonical record."""
    _as_parent(seed)
    assert _submit(client, seed).status_code == 200
    db_session.refresh(seed["record"])
    assert seed["record"].amount_paid == 0.0
    assert seed["record"].status == "overdue"


def test_submit_rejects_amount_over_outstanding(client, seed):
    _as_parent(seed)
    resp = _submit(client, seed, amount=4500.01)
    assert resp.status_code == 400
    assert "outstanding balance" in resp.json()["detail"]


def test_submit_allows_part_payment(client, seed):
    _as_parent(seed)
    resp = _submit(client, seed, amount=1500.0)
    assert resp.status_code == 200
    assert resp.json()["amount"] == 1500.0


def test_submit_rejects_non_positive_amount(client, seed):
    _as_parent(seed)
    assert _submit(client, seed, amount=0).status_code == 400
    assert _submit(client, seed, amount=-10).status_code == 400


def test_submit_rejects_unknown_payment_method(client, seed):
    _as_parent(seed)
    resp = _submit(client, seed, method="Crypto")
    assert resp.status_code == 400
    assert "payment_method" in resp.json()["detail"]


def test_submit_rejects_blank_reference(client, seed):
    _as_parent(seed)
    resp = _submit(client, seed, reference="   ")
    assert resp.status_code == 400


def test_submit_rejects_already_paid_fee(client, seed):
    """other_parent is properly linked to other_student, whose fee is already paid."""
    _override_user("parent", seed["other_parent"].id, seed["school"].id)
    resp = _submit(client, seed, student=seed["other_student"], record=seed["paid_record"])
    assert resp.status_code == 400
    assert "already fully paid" in resp.json()["detail"]


def test_submit_404_for_fee_belonging_to_a_different_student(client, seed):
    """The parent IS linked to `student`, but names a fee record that isn't theirs."""
    _as_parent(seed)
    resp = client.post(
        f"/parent/child/{seed['student'].id}/fees/{seed['paid_record'].id}/payment-request",
        data=_submit_form(),
    )
    assert resp.status_code == 404


def test_submit_forbidden_for_non_parent_roles(client, seed):
    for role, key in (("admin", "admin"), ("teacher", "teacher"), ("student", "student")):
        _override_user(role, seed[key].id if key in seed else 1, seed["school"].id)
        assert _submit(client, seed).status_code == 403


# =============================================================================
# Parent fee list + derived status
# =============================================================================


def test_parent_fees_derives_unpaid_then_pending_then_paid(client, seed, db_session):
    _as_parent(seed)

    body = client.get(f"/parent/child/{seed['student'].id}/fees").json()
    item = next(i for i in body["items"] if i["fee_record_id"] == seed["record"].id)
    assert item["derived_status"] == "unpaid"
    assert item["outstanding"] == 4500.0
    assert item["request"] is None
    assert body["student_name"] == "Child One"

    request_id = _submit(client, seed).json()["id"]
    item = next(
        i
        for i in client.get(f"/parent/child/{seed['student'].id}/fees").json()["items"]
        if i["fee_record_id"] == seed["record"].id
    )
    assert item["derived_status"] == "payment_pending"
    assert item["request"]["id"] == request_id
    # Still overdue underneath - the claim has not been confirmed.
    assert item["record_status"] == "overdue"

    _as_admin(seed)
    assert client.put(f"/admin/fee-payment-requests/{request_id}/confirm").status_code == 200

    _as_parent(seed)
    item = next(
        i
        for i in client.get(f"/parent/child/{seed['student'].id}/fees").json()["items"]
        if i["fee_record_id"] == seed["record"].id
    )
    assert item["derived_status"] == "paid"
    assert item["record_status"] == "paid"
    assert item["outstanding"] == 0.0


def test_parent_fees_shows_rejected_with_reason(client, seed, db_session):
    _as_parent(seed)
    request_id = _submit(client, seed).json()["id"]

    _as_admin(seed)
    client.put(
        f"/admin/fee-payment-requests/{request_id}/reject",
        json={"rejection_reason": "No matching UPI credit on the 14 Aug statement"},
    )

    _as_parent(seed)
    item = next(
        i
        for i in client.get(f"/parent/child/{seed['student'].id}/fees").json()["items"]
        if i["fee_record_id"] == seed["record"].id
    )
    assert item["derived_status"] == "rejected"
    assert item["request"]["rejection_reason"] == "No matching UPI credit on the 14 Aug statement"
    assert item["record_status"] == "overdue"


def test_parent_fees_403_for_unlinked_child(client, seed):
    _as_parent(seed)
    assert client.get(f"/parent/child/{seed['other_student'].id}/fees").status_code == 403


def test_parent_fees_404_for_student_in_another_school_for_staff(client, seed):
    _as_admin(seed)
    assert client.get(f"/parent/child/{seed['other_school_student'].id}/fees").status_code == 404


def test_parent_can_resubmit_after_rejection(client, seed, db_session):
    """The reject branch has to be recoverable, which is why the uniqueness index is
    partial on status='pending' rather than a plain unique constraint."""
    _as_parent(seed)
    first_id = _submit(client, seed).json()["id"]

    _as_admin(seed)
    client.put(f"/admin/fee-payment-requests/{first_id}/reject", json={"rejection_reason": "wrong ref"})

    _as_parent(seed)
    second = _submit(client, seed, reference="UPI/CORRECTED-1")
    assert second.status_code == 200
    assert second.json()["id"] != first_id
    assert (
        db_session.query(FeePaymentRequest)
        .filter(FeePaymentRequest.fee_record_id == seed["record"].id)
        .count()
        == 2
    )


# =============================================================================
# Admin queue, confirm, reject
# =============================================================================


def test_queue_lists_own_school_with_pending_count(client, seed, db_session):
    _open_request(db_session, seed)
    _as_admin(seed)
    body = client.get("/admin/fee-payment-requests").json()
    assert len(body["items"]) == 1
    assert body["pending_count"] == 1
    item = body["items"][0]
    assert item["student_name"] == "Child One"
    assert item["parent_name"] == "Parent One"
    assert item["class_name"] == "Grade 5 - A"
    assert item["fee_type"] == "Term 1 Tuition"
    assert item["outstanding"] == 4500.0
    assert item["has_proof"] is False


def test_queue_pending_count_ignores_the_status_filter(client, seed, db_session):
    """So the dashboard badge and a filtered view can share one request."""
    _open_request(db_session, seed)
    _as_admin(seed)
    body = client.get("/admin/fee-payment-requests", params={"status": "confirmed"}).json()
    assert body["items"] == []
    assert body["pending_count"] == 1


def test_queue_rejects_unknown_status_filter(client, seed):
    _as_admin(seed)
    assert client.get("/admin/fee-payment-requests", params={"status": "banana"}).status_code == 400


def test_confirm_writes_through_to_the_fee_record(client, seed, db_session):
    request = _open_request(db_session, seed)
    _as_admin(seed)

    resp = client.put(f"/admin/fee-payment-requests/{request.id}/confirm")
    assert resp.status_code == 200
    body = resp.json()
    assert body["request"]["status"] == "confirmed"
    assert body["request"]["reviewed_by_name"] == "Admin One"
    assert body["request"]["reviewed_at"] is not None
    assert body["fee_record"] == {
        "fee_record_id": seed["record"].id,
        "amount_paid": 4500.0,
        "amount_due": 4500.0,
        "status": "paid",
    }

    db_session.refresh(seed["record"])
    assert seed["record"].status == "paid"
    assert seed["record"].amount_paid == 4500.0


def test_confirm_part_payment_lands_on_partial(client, seed, db_session):
    _as_parent(seed)
    request_id = _submit(client, seed, amount=1500.0).json()["id"]
    _as_admin(seed)
    body = client.put(f"/admin/fee-payment-requests/{request_id}/confirm").json()
    assert body["fee_record"]["status"] == "partial"
    assert body["fee_record"]["amount_paid"] == 1500.0
    assert body["request"]["outstanding"] == 3000.0


def test_confirm_notifies_the_parent(client, seed, db_session):
    request = _open_request(db_session, seed)
    _as_admin(seed)
    client.put(f"/admin/fee-payment-requests/{request.id}/confirm")

    note = (
        db_session.query(Notification)
        .filter(Notification.source_type == "fee_payment_confirmed", Notification.source_id == request.id)
        .one()
    )
    assert note.user_id == seed["parent"].id
    assert "fully paid" in note.body


def test_confirm_writes_both_audit_rows(client, seed, db_session):
    """Two entities changed, so two rows: the fee record write reuses the existing
    `record_payment` action, and the review itself is recorded separately."""
    request = _open_request(db_session, seed)
    _as_admin(seed)
    client.put(f"/admin/fee-payment-requests/{request.id}/confirm")

    payment_entry = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.action == "record_payment",
            AuditLogEntry.entity_type == "fee_records",
            AuditLogEntry.entity_id == seed["record"].id,
        )
        .order_by(AuditLogEntry.id.desc())
        .first()
    )
    assert payment_entry is not None
    assert payment_entry.detail["new_status"] == "paid"
    assert payment_entry.detail["fee_payment_request_id"] == request.id

    review_entry = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.action == "confirm_fee_payment_request",
            AuditLogEntry.entity_id == request.id,
        )
        .one()
    )
    assert review_entry.actor_id == seed["admin"].id
    assert review_entry.detail["fee_record_status"] == "paid"


def test_confirm_is_not_repeatable(client, seed, db_session):
    """Guards against a double-click paying the fee twice."""
    request = _open_request(db_session, seed)
    _as_admin(seed)
    assert client.put(f"/admin/fee-payment-requests/{request.id}/confirm").status_code == 200

    second = client.put(f"/admin/fee-payment-requests/{request.id}/confirm")
    assert second.status_code == 400
    assert "already been confirmed" in second.json()["detail"]

    db_session.refresh(seed["record"])
    assert seed["record"].amount_paid == 4500.0


def test_principal_can_confirm(client, seed, db_session):
    request = _open_request(db_session, seed)
    _override_user("principal", seed["principal"].id, seed["school"].id)
    assert client.put(f"/admin/fee-payment-requests/{request.id}/confirm").status_code == 200


def test_reject_requires_a_reason(client, seed, db_session):
    request = _open_request(db_session, seed)
    _as_admin(seed)
    assert client.put(f"/admin/fee-payment-requests/{request.id}/reject", json={}).status_code == 422
    blank = client.put(
        f"/admin/fee-payment-requests/{request.id}/reject", json={"rejection_reason": "   "}
    )
    assert blank.status_code == 400


def test_reject_leaves_the_fee_record_alone_and_notifies(client, seed, db_session):
    request = _open_request(db_session, seed)
    _as_admin(seed)
    resp = client.put(
        f"/admin/fee-payment-requests/{request.id}/reject",
        json={"rejection_reason": "No matching credit on the statement"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert resp.json()["rejection_reason"] == "No matching credit on the statement"

    db_session.refresh(seed["record"])
    assert seed["record"].amount_paid == 0.0
    assert seed["record"].status == "overdue"

    note = (
        db_session.query(Notification)
        .filter(Notification.source_type == "fee_payment_rejected", Notification.source_id == request.id)
        .one()
    )
    assert note.user_id == seed["parent"].id
    assert "No matching credit on the statement" in note.body

    entry = (
        db_session.query(AuditLogEntry)
        .filter(AuditLogEntry.action == "reject_fee_payment_request", AuditLogEntry.entity_id == request.id)
        .one()
    )
    assert entry.detail["rejection_reason"] == "No matching credit on the statement"


def test_reject_is_not_repeatable(client, seed, db_session):
    request = _open_request(db_session, seed)
    _as_admin(seed)
    client.put(f"/admin/fee-payment-requests/{request.id}/reject", json={"rejection_reason": "a"})
    second = client.put(
        f"/admin/fee-payment-requests/{request.id}/reject", json={"rejection_reason": "b"}
    )
    assert second.status_code == 400


def test_proof_404_when_none_attached(client, seed, db_session):
    request = _open_request(db_session, seed)
    _as_admin(seed)
    resp = client.get(f"/admin/fee-payment-requests/{request.id}/proof")
    assert resp.status_code == 404
    assert "no proof" in resp.json()["detail"]


# =============================================================================
# Step 4: the reminder interaction
# =============================================================================


def test_reminders_still_fire_while_a_payment_request_is_pending(client, seed, db_session):
    """A CLAIM IS NOT A PAYMENT. If a pending request silenced reminders, a parent
    could mute the school's alert chain by asserting they had paid. Reminders read
    FeeRecord.status, which a claim never touches - this pins that.
    """
    _as_parent(seed)
    assert _submit(client, seed).status_code == 200

    _as_admin(seed)
    resp = client.post("/admin/fees/reminders", json={"overdue_only": True})
    assert resp.status_code == 200
    assert resp.json()["sent_count"] == 1
    assert (
        db_session.query(FeeReminder).filter(FeeReminder.fee_record_id == seed["record"].id).count() == 1
    )


def test_reminders_stop_once_the_request_is_confirmed(client, seed, db_session):
    """The other half: confirmation moves the record to `paid`, which both reminder
    filters exclude, so the alert chain goes quiet for the right reason."""
    _as_parent(seed)
    request_id = _submit(client, seed).json()["id"]
    _as_admin(seed)
    assert client.put(f"/admin/fee-payment-requests/{request_id}/confirm").status_code == 200

    before = db_session.query(FeeReminder).filter(FeeReminder.fee_record_id == seed["record"].id).count()
    assert client.post("/admin/fees/reminders", json={"overdue_only": True}).json()["sent_count"] == 0
    assert client.post("/admin/fees/reminders", json={"overdue_only": False}).json()["sent_count"] == 0
    after = db_session.query(FeeReminder).filter(FeeReminder.fee_record_id == seed["record"].id).count()
    assert after == before


def test_reminders_resume_after_a_rejection(client, seed, db_session):
    """A rejected claim must leave the fee exactly as exposed as it was before."""
    _as_parent(seed)
    request_id = _submit(client, seed).json()["id"]
    _as_admin(seed)
    client.put(f"/admin/fee-payment-requests/{request_id}/reject", json={"rejection_reason": "no credit"})

    assert client.post("/admin/fees/reminders", json={"overdue_only": True}).json()["sent_count"] == 1


# =============================================================================
# Claim visibility on the canonical fee list, and closing stranded claims
# =============================================================================


def test_fee_status_exposes_the_open_claim(client, seed, db_session):
    """The admin's own fee list must not contradict the parent's view: a fee with an
    open claim used to read plainly "overdue" here, so an admin could chase a parent
    who was in fact waiting on the school."""
    _as_parent(seed)
    request_id = _submit(client, seed).json()["id"]

    _as_admin(seed)
    body = client.get("/admin/fees/status").json()
    item = next(i for i in body["items"] if i["fee_record_id"] == seed["record"].id)
    # Canonical status is untouched...
    assert item["status"] == "overdue"
    assert item["outstanding"] == 4500.0
    # ...but the claim is now visible alongside it.
    assert item["claim"]["id"] == request_id
    assert item["claim"]["status"] == "pending"
    assert item["claim"]["payment_reference"] == "UPI/428817263541"
    assert item["claim"]["has_proof"] is False


def test_fee_status_claim_is_null_without_any_request(client, seed):
    _as_admin(seed)
    body = client.get("/admin/fees/status").json()
    item = next(i for i in body["items"] if i["fee_record_id"] == seed["record"].id)
    assert item["claim"] is None


def test_fee_status_keeps_showing_a_rejected_claim(client, seed):
    """So a rejection stays visible to staff, not just to the parent."""
    _as_parent(seed)
    request_id = _submit(client, seed).json()["id"]
    _as_admin(seed)
    client.put(f"/admin/fee-payment-requests/{request_id}/reject", json={"rejection_reason": "no credit found"})

    item = next(
        i for i in client.get("/admin/fees/status").json()["items"] if i["fee_record_id"] == seed["record"].id
    )
    assert item["claim"]["status"] == "rejected"
    assert item["claim"]["rejection_reason"] == "no credit found"


def test_recording_payment_directly_closes_the_open_claim(client, seed, db_session):
    """THE STUCK-BADGE BUG. Only confirm/reject used to close a claim, but they are
    not the only things that pay a fee - an admin recording the same payment through
    the fee record left the claim pending forever, so pending_count never returned to
    zero and the dashboard badge lied."""
    _as_parent(seed)
    request_id = _submit(client, seed).json()["id"]

    _as_admin(seed)
    assert client.get("/admin/fee-payment-requests").json()["pending_count"] == 1

    resp = client.post(
        f"/admin/fees/records/{seed['record'].id}/payment", json={"amount": 4500.0, "paid_at": None}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"

    # The claim is closed, and the badge can reach zero.
    request = db_session.query(FeePaymentRequest).filter(FeePaymentRequest.id == request_id).one()
    assert request.status == "confirmed"
    assert request.reviewed_by == seed["admin"].id
    assert request.reviewed_at is not None
    assert client.get("/admin/fee-payment-requests").json()["pending_count"] == 0


def test_indirect_close_is_marked_as_such_in_the_audit_log(client, seed, db_session):
    """It must never read as an admin who sat down and reviewed the claim on merit."""
    _as_parent(seed)
    request_id = _submit(client, seed).json()["id"]
    _as_admin(seed)
    client.post(f"/admin/fees/records/{seed['record'].id}/payment", json={"amount": 4500.0, "paid_at": None})

    entry = (
        db_session.query(AuditLogEntry)
        .filter(
            AuditLogEntry.action == "confirm_fee_payment_request",
            AuditLogEntry.entity_id == request_id,
        )
        .one()
    )
    assert entry.detail["closed_indirectly"] is True
    assert entry.detail["via"] == "record_payment"


def test_indirect_close_notifies_the_parent(client, seed, db_session):
    _as_parent(seed)
    request_id = _submit(client, seed).json()["id"]
    _as_admin(seed)
    client.post(f"/admin/fees/records/{seed['record'].id}/payment", json={"amount": 4500.0, "paid_at": None})

    note = (
        db_session.query(Notification)
        .filter(
            Notification.source_type == "fee_payment_confirmed",
            Notification.source_id == request_id,
        )
        .one()
    )
    assert note.user_id == seed["parent"].id


def test_part_payment_does_not_close_the_claim(client, seed, db_session):
    """A part payment leaves a real balance, so the claim for the rest is still a
    live question - only a fee reaching `paid` closes it."""
    _as_parent(seed)
    request_id = _submit(client, seed).json()["id"]
    _as_admin(seed)
    resp = client.post(
        f"/admin/fees/records/{seed['record'].id}/payment", json={"amount": 1000.0, "paid_at": None}
    )
    assert resp.json()["status"] == "partial"

    request = db_session.query(FeePaymentRequest).filter(FeePaymentRequest.id == request_id).one()
    assert request.status == "pending"
    assert client.get("/admin/fee-payment-requests").json()["pending_count"] == 1


# =============================================================================
# A PART PAYMENT MUST NOT SILENCE A DEBT
# =============================================================================
# Every one of these was broken: recording any payment flipped status to "partial",
# and both the reminder scope and the alert feed filtered on status == "overdue", so
# paying 1 rupee of 350 removed the fee from both while 349 stayed unpaid and late.


def _record_payment(client, seed, amount: float):
    return client.post(
        f"/admin/fees/records/{seed['record'].id}/payment", json={"amount": amount, "paid_at": None}
    )


def test_part_payment_stays_in_the_reminder_scope(client, seed, db_session):
    """THE BUG: default scope is "overdue only", and a part payment left that scope."""
    _as_admin(seed)
    assert _record_payment(client, seed, 100.0).json()["status"] == "partial"

    preview = client.get("/admin/fees/reminders/preview", params={"overdue_only": "true"}).json()
    assert preview["in_scope"] == 1, "a partly paid, past-due fee must still be in scope"
    assert preview["due_now"] == 1

    assert client.post("/admin/fees/reminders", json={"overdue_only": True}).json()["sent_count"] == 1


def test_part_payment_reminder_quotes_the_remaining_balance(client, seed, db_session):
    _as_admin(seed)
    _record_payment(client, seed, 100.0)
    client.post("/admin/fees/reminders", json={"overdue_only": True})

    note = (
        db_session.query(Notification)
        .filter(Notification.source_type == "fee_reminder", Notification.source_id == seed["record"].id)
        .order_by(Notification.id.desc())
        .first()
    )
    assert note is not None
    assert "4400.00" in note.body, "must quote the REMAINDER, not the original amount"
    assert "100.00 already paid" in note.body


def test_reminder_priority_comes_from_the_tier_not_the_status(client, seed, db_session):
    """A part payment used to downgrade a 30-days-late reminder to `normal` because
    priority was `urgent if status == "overdue"`. The escalated tier fired but arrived
    quietly - the tier severity and the notification disagreed."""
    seed["record"].due_date = date.today() - timedelta(days=45)
    db_session.commit()
    _as_admin(seed)
    _record_payment(client, seed, 100.0)
    assert client.post("/admin/fees/reminders", json={"overdue_only": True}).json()["sent_count"] == 1

    note = (
        db_session.query(Notification)
        .filter(Notification.source_type == "fee_reminder", Notification.source_id == seed["record"].id)
        .order_by(Notification.id.desc())
        .first()
    )
    # 45 days overdue reaches the urgent 30-day tier, and the status is "partial".
    assert note.priority == "urgent"


def test_part_payment_stays_in_the_command_center_alert_feed(client, seed, db_session):
    """The feed filtered on status == "overdue", so a part payment removed the fee
    entirely - the school stopped tracking a debt because some of it arrived."""
    _as_admin(seed)
    before = [a for a in client.get("/admin/alerts").json()["items"] if a["source"] == "fee_overdue"]
    assert any(a["entity_id"] == seed["record"].id for a in before)

    _record_payment(client, seed, 100.0)

    after = [a for a in client.get("/admin/alerts").json()["items"] if a["source"] == "fee_overdue"]
    mine = [a for a in after if a["entity_id"] == seed["record"].id]
    assert len(mine) == 1, "a partly paid overdue fee must still raise an alert"
    assert "4400.0" in mine[0]["message"]
    assert "100.0 of 4500.0 paid" in mine[0]["message"]
    assert mine[0]["title"] == "Partly paid fee overdue"


def test_a_fully_paid_fee_leaves_reminders_and_alerts(client, seed, db_session):
    """The other side: `paid` is the only settled state, and it must go quiet."""
    _as_admin(seed)
    assert _record_payment(client, seed, 4500.0).json()["status"] == "paid"

    assert client.get("/admin/fees/reminders/preview", params={"overdue_only": "true"}).json()["in_scope"] == 0
    assert client.post("/admin/fees/reminders", json={"overdue_only": True}).json()["sent_count"] == 0
    alerts = [
        a
        for a in client.get("/admin/alerts").json()["items"]
        if a["source"] == "fee_overdue" and a["entity_id"] == seed["record"].id
    ]
    assert alerts == []


def test_parent_sees_partially_paid_not_unpaid(client, seed, db_session):
    """A 4500 fee with 100 recorded read exactly like one with nothing paid."""
    _as_admin(seed)
    _record_payment(client, seed, 100.0)

    _as_parent(seed)
    item = next(
        i
        for i in client.get(f"/parent/child/{seed['student'].id}/fees").json()["items"]
        if i["fee_record_id"] == seed["record"].id
    )
    assert item["derived_status"] == "partially_paid"
    assert item["record_status"] == "partial"
    assert item["amount_paid"] == 100.0
    assert item["outstanding"] == 4400.0


def test_parent_partial_fee_is_only_settled_when_fully_paid(client, seed, db_session):
    """Walks the whole way up: nothing -> part -> all."""
    _as_parent(seed)

    def derived():
        return next(
            i
            for i in client.get(f"/parent/child/{seed['student'].id}/fees").json()["items"]
            if i["fee_record_id"] == seed["record"].id
        )["derived_status"]

    assert derived() == "unpaid"

    _as_admin(seed)
    _record_payment(client, seed, 200.0)
    _as_parent(seed)
    assert derived() == "partially_paid"

    _as_admin(seed)
    _record_payment(client, seed, 4300.0)
    _as_parent(seed)
    assert derived() == "paid"


def test_an_open_claim_outranks_partially_paid(client, seed, db_session):
    """Precedence: the parent needs "awaiting confirmation" more than the balance."""
    _as_admin(seed)
    _record_payment(client, seed, 100.0)

    _as_parent(seed)
    assert _submit(client, seed, amount=4400.0).status_code == 200
    item = next(
        i
        for i in client.get(f"/parent/child/{seed['student'].id}/fees").json()["items"]
        if i["fee_record_id"] == seed["record"].id
    )
    assert item["derived_status"] == "payment_pending"


# =============================================================================
# Reminder preview: explaining why a run would do nothing
# =============================================================================


def test_reminder_preview_explains_a_due_run(client, seed):
    """The seeded fee is 20 days overdue with no reminders sent, so a run would fire
    the highest reached tier."""
    _as_admin(seed)
    body = client.get("/admin/fees/reminders/preview").json()
    assert body["in_scope"] == 1
    assert body["due_now"] == 1
    assert body["by_tier"] == [
        {"cadence_reason": "14 days overdue - second reminder", "severity": "normal", "count": 1}
    ]
    assert body["not_yet_due"] == 0


def test_reminder_preview_explains_zero_and_names_the_next_date(client, seed, db_session):
    """The case that made this endpoint necessary: records the UI calls overdue that
    the cadence engine is not ready to remind about yet."""
    # Move the fee to 3 days overdue and mark the day-1 notice as already sent, so
    # nothing is due until the 7-day tier.
    seed["record"].due_date = date.today() - timedelta(days=3)
    db_session.add(FeeReminder(fee_record_id=seed["record"].id, cadence_reason="due date passed - first notice"))
    db_session.commit()

    _as_admin(seed)
    body = client.get("/admin/fees/reminders/preview").json()
    assert body["in_scope"] == 1
    assert body["due_now"] == 0
    assert body["waiting_for_next_tier"] == 1
    # due_date + 7 days is when the next tier becomes eligible.
    assert body["next_due_date"] == (seed["record"].due_date + timedelta(days=7)).isoformat()
    assert body["next_due_count"] == 1


def test_reminder_preview_counts_not_yet_due_records(client, seed, db_session):
    """With the scope widened past overdue, records that aren't past their due date
    are counted separately - they can never fire today, which is why widening the
    scope looks like it should help and doesn't."""
    seed["record"].due_date = date.today() + timedelta(days=5)
    seed["record"].status = "pending"
    db_session.commit()

    _as_admin(seed)
    body = client.get("/admin/fees/reminders/preview", params={"overdue_only": "false"}).json()
    assert body["due_now"] == 0
    assert body["not_yet_due"] == 1
    assert body["next_due_date"] == (date.today() + timedelta(days=6)).isoformat()


def test_reminder_preview_matches_what_triggering_actually_does(client, seed):
    """The preview and the trigger share one scope query and one determine_reminder
    call, so `due_now` must equal `sent_count`."""
    _as_admin(seed)
    predicted = client.get("/admin/fees/reminders/preview").json()["due_now"]
    actual = client.post("/admin/fees/reminders", json={"overdue_only": True}).json()["sent_count"]
    assert predicted == actual == 1

    # And immediately after, the preview reflects the tier having fired.
    after = client.get("/admin/fees/reminders/preview").json()
    assert after["due_now"] == 0
    assert after["waiting_for_next_tier"] == 1


def test_reminder_preview_writes_nothing(client, seed, db_session):
    _as_admin(seed)
    before = db_session.query(FeeReminder).count()
    client.get("/admin/fees/reminders/preview")
    assert db_session.query(FeeReminder).count() == before


def test_reminder_preview_is_school_scoped(client, seed):
    """The other school's overdue record must not appear in this admin's preview."""
    _as_admin(seed)
    assert client.get("/admin/fees/reminders/preview").json()["in_scope"] == 1

    _override_user("admin", seed["other_admin"].id, seed["other_school"].id)
    assert client.get("/admin/fees/reminders/preview").json()["in_scope"] == 1


def test_reminder_preview_forbidden_for_non_staff(client, seed):
    _override_user("parent", seed["parent"].id, seed["school"].id)
    assert client.get("/admin/fees/reminders/preview").status_code == 403
    _override_user("teacher", seed["teacher"].id, seed["school"].id)
    assert client.get("/admin/fees/reminders/preview").status_code == 403


def test_one_day_overdue_now_fires_a_reminder(client, seed, db_session):
    """THE BUG THIS TIER FIXES: a fee one day past due showed as `overdue` on the fee
    list while triggering reminders reported zero, which read as a broken button."""
    seed["record"].due_date = date.today() - timedelta(days=1)
    db_session.commit()

    _as_admin(seed)
    body = client.get("/admin/fees/reminders/preview").json()
    assert body["due_now"] == 1
    assert body["by_tier"][0]["cadence_reason"] == "due date passed - first notice"

    assert client.post("/admin/fees/reminders", json={"overdue_only": True}).json()["sent_count"] == 1


def test_teacher_mark_paid_does_not_confirm_the_claim(client, seed, db_session):
    """The trust-model boundary holds through the side door too. Teachers are
    excluded from confirm/reject on purpose, so a teacher's paid/unpaid toggle must
    not confirm a claim indirectly - it stays pending for an admin to close out."""
    _as_parent(seed)
    request_id = _submit(client, seed).json()["id"]

    # Make the fee's student belong to a class this teacher is class teacher of.
    school_class = (
        db_session.query(SchoolClass).filter(SchoolClass.school_id == seed["school"].id).one()
    )
    school_class.class_teacher_id = seed["teacher"].id
    db_session.commit()

    _override_user("teacher", seed["teacher"].id, seed["school"].id)
    resp = client.patch(f"/admin/fees/records/{seed['record'].id}/mark-paid", json={"paid": True})
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"

    request = db_session.query(FeePaymentRequest).filter(FeePaymentRequest.id == request_id).one()
    assert request.status == "pending", "a teacher must not confirm a claim indirectly"
    assert request.reviewed_by is None
