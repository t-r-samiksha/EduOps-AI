"""Digital Library Router - Person B (Classroom & Academics).

Implements library catalog browsing, past paper / ebook access,
and book loan issue/return inventory management.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.library import LibraryItem, LibraryLoan
from app.models.user import User
from app.services.auth import CurrentUser, get_current_user, require_role
from app.services.library_service import (
    issue_library_item,
    return_library_item,
    update_overdue_loans,
)

router = APIRouter(tags=["library"])


# --- Pydantic Schemas ---------------------------------------------------------------


class LibraryItemCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    author: str | None = None
    isbn: str | None = None
    category: str = "General"
    type: str = "book"  # book, past_paper, journal, ebook
    total_copies: int = Field(default=1, gt=0)
    file_url: str | None = None


class LibraryItemOut(BaseModel):
    id: int
    school_id: int
    title: str
    author: str | None = None
    isbn: str | None = None
    category: str
    type: str
    available_copies: int
    total_copies: int
    file_url: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class IssueBookRequest(BaseModel):
    item_id: int
    student_id: int
    loan_days: int = Field(default=14, gt=0)


class LoanOut(BaseModel):
    id: int
    library_item_id: int
    item_title: str | None = None
    student_id: int
    student_name: str | None = None
    issued_at: datetime
    due_date: datetime
    returned_at: datetime | None = None
    status: str

    model_config = ConfigDict(from_attributes=True)


# --- Endpoints ----------------------------------------------------------------------


@router.get("/library/catalog", response_model=list[LibraryItemOut])
def get_library_catalog(
    category: str | None = None,
    type: str | None = None,
    q: str | None = None,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Browse library catalog with category, format, and title search filters."""
    query = db.query(LibraryItem).filter(LibraryItem.school_id == user.school_id)

    if category:
        query = query.filter(LibraryItem.category.ilike(f"%{category}%"))
    if type:
        query = query.filter(LibraryItem.type == type)
    if q:
        query = query.filter(
            or_(
                LibraryItem.title.ilike(f"%{q}%"),
                LibraryItem.author.ilike(f"%{q}%"),
                LibraryItem.isbn.ilike(f"%{q}%"),
            )
        )

    return query.order_by(LibraryItem.title.asc()).all()


@router.post("/library/items", response_model=LibraryItemOut, status_code=status.HTTP_201_CREATED)
def add_library_item(
    body: LibraryItemCreate,
    user: CurrentUser = Depends(require_role("admin", "principal", "teacher")),
    db: Session = Depends(get_db),
):
    """Add a new book, past paper, or ebook to the library catalog."""
    item = LibraryItem(
        school_id=user.school_id or 1,
        title=body.title.strip(),
        author=body.author.strip() if body.author else None,
        isbn=body.isbn.strip() if body.isbn else None,
        category=body.category.strip(),
        type=body.type,
        available_copies=body.total_copies,
        total_copies=body.total_copies,
        file_url=body.file_url,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post("/library/issue", response_model=LoanOut)
def issue_book(
    body: IssueBookRequest,
    user: CurrentUser = Depends(require_role("admin", "principal", "teacher")),
    db: Session = Depends(get_db),
):
    """Issue a library item copy to a student."""
    try:
        loan = issue_library_item(
            db=db,
            school_id=user.school_id or 1,
            item_id=body.item_id,
            student_id=body.student_id,
            issuer_id=user.id,
            loan_days=body.loan_days,
        )
        item = db.query(LibraryItem).filter(LibraryItem.id == loan.library_item_id).first()
        student = db.query(User).filter(User.id == loan.student_id).first()
        return LoanOut(
            id=loan.id,
            library_item_id=loan.library_item_id,
            item_title=item.title if item else None,
            student_id=loan.student_id,
            student_name=student.full_name if student else None,
            issued_at=loan.issued_at,
            due_date=loan.due_date,
            returned_at=loan.returned_at,
            status=loan.status,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))


@router.put("/library/return/{loan_id}", response_model=LoanOut)
def return_book(
    loan_id: int,
    user: CurrentUser = Depends(require_role("admin", "principal", "teacher")),
    db: Session = Depends(get_db),
):
    """Return a borrowed library item."""
    try:
        loan = return_library_item(db=db, school_id=user.school_id or 1, loan_id=loan_id)
        item = db.query(LibraryItem).filter(LibraryItem.id == loan.library_item_id).first()
        student = db.query(User).filter(User.id == loan.student_id).first()
        return LoanOut(
            id=loan.id,
            library_item_id=loan.library_item_id,
            item_title=item.title if item else None,
            student_id=loan.student_id,
            student_name=student.full_name if student else None,
            issued_at=loan.issued_at,
            due_date=loan.due_date,
            returned_at=loan.returned_at,
            status=loan.status,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e))


@router.get("/library/my-loans/{student_id}", response_model=list[LoanOut])
def get_student_loans(
    student_id: int,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """View active and past library loans for a student."""
    if user.role == "student" and user.id != student_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Cannot view another student's loans")

    update_overdue_loans(db)

    loans = (
        db.query(LibraryLoan)
        .filter(LibraryLoan.student_id == student_id)
        .order_by(LibraryLoan.issued_at.desc())
        .all()
    )
    results = []
    for l in loans:
        item = db.query(LibraryItem).filter(LibraryItem.id == l.library_item_id).first()
        student = db.query(User).filter(User.id == l.student_id).first()
        results.append(
            LoanOut(
                id=l.id,
                library_item_id=l.library_item_id,
                item_title=item.title if item else None,
                student_id=l.student_id,
                student_name=student.full_name if student else None,
                issued_at=l.issued_at,
                due_date=l.due_date,
                returned_at=l.returned_at,
                status=l.status,
            )
        )
    return results


@router.get("/library/loans", response_model=list[LoanOut])
def list_all_loans(
    status: str | None = None,
    user: CurrentUser = Depends(require_role("admin", "principal", "teacher")),
    db: Session = Depends(get_db),
):
    """Admin / Librarian views all active and overdue book loans."""
    update_overdue_loans(db)

    query = db.query(LibraryLoan).filter(LibraryLoan.school_id == user.school_id)
    if status:
        query = query.filter(LibraryLoan.status == status)

    loans = query.order_by(LibraryLoan.due_date.asc()).all()
    results = []
    for l in loans:
        item = db.query(LibraryItem).filter(LibraryItem.id == l.library_item_id).first()
        student = db.query(User).filter(User.id == l.student_id).first()
        results.append(
            LoanOut(
                id=l.id,
                library_item_id=l.library_item_id,
                item_title=item.title if item else None,
                student_id=l.student_id,
                student_name=student.full_name if student else None,
                issued_at=l.issued_at,
                due_date=l.due_date,
                returned_at=l.returned_at,
                status=l.status,
            )
        )
    return results
