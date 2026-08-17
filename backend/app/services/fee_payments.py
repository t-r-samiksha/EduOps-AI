"""Applying a payment to a canonical FeeRecord - the single place the
amount/status arithmetic lives.

WHY THIS EXISTS: this logic was inline in
routers/fees.py::record_payment. The fee payment confirmation loop
(PUT /admin/fee-payment-requests/{id}/confirm) has to do exactly the same write
when an admin confirms a parent's claim, and a second copy of "add the amount,
round to 2dp, then derive paid/partial" is precisely the kind of duplication that
drifts - one copy gets a fix and the other silently doesn't, so the same fee reads
differently depending on which door the payment came through.

The extraction is deliberately narrow: it moves the arithmetic and its audit row,
nothing else. Fetching/scoping the record, committing, and building the response
stay with each caller, because those genuinely differ (one is scoped by
school_id off the URL, the other by the request row it is confirming).

DOES NOT COMMIT, same contract as services/notify.py and services/audit_log.py -
the caller's own commit puts the record change, the audit row and whatever else it
is doing in one transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models.fees import FeeRecord
from app.services.audit_log import write_audit_log

__all__ = ["PaymentOutcome", "outstanding_balance", "apply_payment_to_record", "close_open_claim_if_paid"]


@dataclass(frozen=True)
class PaymentOutcome:
    """What the write did, for building a response or an audit detail."""

    fee_record_id: int
    amount_due: float
    previous_amount_paid: float
    amount_paid: float
    previous_status: str
    status: str


def outstanding_balance(record: FeeRecord) -> float:
    """What is still owed, floored at 0 - an overpayment must not report a
    negative balance, which would then read as a credit nothing here models."""
    return round(max(0.0, record.amount_due - record.amount_paid), 2)


def apply_payment_to_record(
    db,
    record: FeeRecord,
    amount: float,
    *,
    actor_id: int,
    audit_detail_extra: dict | None = None,
) -> PaymentOutcome:
    """Add `amount` to a fee record's paid total and re-derive its status.

    Behaviour is byte-for-byte what routers/fees.py::record_payment did inline,
    including the `action="record_payment"` audit row and its detail keys - the
    existing endpoint's contract and its tests are unchanged by the extraction.

    Note the derivation only ever ratchets UPWARD: `paid` at or above the due
    amount, `partial` above zero, and otherwise the existing status is left
    alone. It never moves a record back to `overdue`/`pending`, which is why
    rejecting a payment request deliberately does not call this at all - there is
    nothing to un-apply, because a claim never wrote here in the first place.

    `audit_detail_extra` is merged into the audit detail so a caller can record
    where the payment came from (e.g. which payment request confirmed it) without
    needing its own second audit row for the same fee_records change.
    """
    previous_paid = record.amount_paid
    previous_status = record.status

    record.amount_paid = round(record.amount_paid + amount, 2)
    if record.amount_paid >= record.amount_due:
        record.status = "paid"
    elif record.amount_paid > 0:
        record.status = "partial"

    write_audit_log(
        db,
        actor_id=actor_id,
        action="record_payment",
        entity_type="fee_records",
        entity_id=record.id,
        detail={
            "amount": amount,
            "previous_amount_paid": previous_paid,
            "new_amount_paid": record.amount_paid,
            "new_status": record.status,
            **(audit_detail_extra or {}),
        },
    )

    return PaymentOutcome(
        fee_record_id=record.id,
        amount_due=record.amount_due,
        previous_amount_paid=previous_paid,
        amount_paid=record.amount_paid,
        previous_status=previous_status,
        status=record.status,
    )


def close_open_claim_if_paid(db, record: FeeRecord, *, actor_id: int, via: str):
    """Auto-confirm a parent's open payment claim when the fee has just been paid in
    full through a DIFFERENT door, and return the closed request (or None).

    WHY: confirm/reject are the only endpoints that close a
    fee_payment_requests row, but they are not the only things that can pay a fee.
    An admin who records the same payment through
    POST /admin/fees/records/{id}/payment instead of the review queue leaves the
    claim pending forever - the fee reads paid, the parent's view correctly reads
    paid (their derived status checks the record first), and yet the admin's
    pending badge never returns to zero. A badge that cannot reach zero is worse
    than no badge, because people stop believing it.

    So a full payment closes any claim still open against that record. The audit
    row records `closed_indirectly` and which endpoint did it, so this never looks
    like an admin who sat down and reviewed the claim on its merits.

    DELIBERATELY NOT CALLED FROM THE TEACHER mark-paid PATH. Teachers are excluded
    from confirm/reject on purpose (see routers/fees.py's trust-model note), and
    auto-confirming from a teacher's toggle would hand them that authority through
    a side door. A fee a teacher marked paid while a claim is open is exactly the
    case a human should look at: the queue surfaces it as "fee already paid" so an
    admin can close it in one click.

    Only fires on `paid`, never on `partial`: a part payment leaves a real balance,
    so the claim for the rest is still a live question.
    """
    if record.status != "paid":
        return None

    # Imported here rather than at module scope: models/fees.py imports nothing from
    # this module, but keeping the heavier request model out of the import graph of a
    # pure-arithmetic service keeps that one-way.
    from app.models.fees import FeePaymentRequest

    request = (
        db.query(FeePaymentRequest)
        .filter(
            FeePaymentRequest.fee_record_id == record.id,
            FeePaymentRequest.status == "pending",
        )
        .one_or_none()
    )
    if request is None:
        return None

    request.status = "confirmed"
    request.reviewed_by = actor_id
    request.reviewed_at = datetime.now(timezone.utc)

    write_audit_log(
        db,
        actor_id=actor_id,
        action="confirm_fee_payment_request",
        entity_type="fee_payment_requests",
        entity_id=request.id,
        detail={
            "fee_record_id": record.id,
            "amount": request.amount,
            "payment_reference": request.payment_reference,
            "fee_record_status": record.status,
            "closed_indirectly": True,
            "via": via,
        },
    )
    return request
