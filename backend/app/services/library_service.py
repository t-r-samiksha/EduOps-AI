"""Digital Library Service - Person B (Classroom & Academics).

Handles library catalog inventory, issuing and returning books/past papers,
and overdue loan tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.library import LibraryItem, LibraryLoan
from app.models.user import User


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def issue_library_item(
    db: Session,
    school_id: int,
    item_id: int,
    student_id: int,
    issuer_id: int | None = None,
    loan_days: int = 14,
) -> LibraryLoan:
    """Issues a library copy to a student with concurrency check."""
    item = (
        db.query(LibraryItem)
        .filter(LibraryItem.id == item_id, LibraryItem.school_id == school_id)
        .with_for_update()
        .first()
    )
    if not item:
        raise ValueError("Library item not found")

    if item.available_copies <= 0:
        raise ValueError(f"No copies of '{item.title}' currently available")

    # Prevent duplicate active loan for same book and student
    active_loan = (
        db.query(LibraryLoan)
        .filter(
            LibraryLoan.library_item_id == item_id,
            LibraryLoan.student_id == student_id,
            LibraryLoan.status.in_(("active", "overdue")),
        )
        .first()
    )
    if active_loan:
        raise ValueError("Student already has an active loan for this item")

    now = datetime.now(timezone.utc)
    due_date = now + timedelta(days=loan_days)

    item.available_copies -= 1

    loan = LibraryLoan(
        school_id=school_id,
        library_item_id=item_id,
        student_id=student_id,
        issued_by=issuer_id,
        issued_at=now,
        due_date=due_date,
        status="active",
    )
    db.add(loan)
    db.commit()
    db.refresh(loan)
    return loan


def return_library_item(
    db: Session,
    school_id: int,
    loan_id: int,
) -> LibraryLoan:
    """Returns a borrowed item and increases available inventory."""
    loan = (
        db.query(LibraryLoan)
        .filter(LibraryLoan.id == loan_id, LibraryLoan.school_id == school_id)
        .first()
    )
    if not loan:
        raise ValueError("Loan record not found")

    if loan.status == "returned":
        return loan

    item = (
        db.query(LibraryItem)
        .filter(LibraryItem.id == loan.library_item_id)
        .with_for_update()
        .first()
    )
    if item and item.available_copies < item.total_copies:
        item.available_copies += 1

    now = datetime.now(timezone.utc)
    loan.returned_at = now
    loan.status = "returned"
    db.commit()
    db.refresh(loan)
    return loan


def update_overdue_loans(db: Session) -> int:
    """Calculates and updates overdue status for loans past their due date."""
    now = datetime.now(timezone.utc)
    active_loans = (
        db.query(LibraryLoan)
        .filter(LibraryLoan.status == "active")
        .all()
    )
    overdue_count = 0
    for l in active_loans:
        if _to_utc(l.due_date) < now:
            l.status = "overdue"
            overdue_count += 1

    if overdue_count > 0:
        db.commit()

    return overdue_count
