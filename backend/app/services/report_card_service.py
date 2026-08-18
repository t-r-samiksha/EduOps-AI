"""Report Card Automation Service - Person B (Classroom & Academics).

Aggregates gradebook scores, Person A attendance, teacher remarks, and GPA
into structured transcripts and formatted report card snapshots.
Optimized for high performance bulk generation (< 30 seconds for 40 students).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from sqlalchemy.orm import Session

from app.models.attendance import AttendanceRecord
from app.models.class_ import SchoolClass
from app.models.enrollment import Enrollment
from app.models.gradebook import GradebookEntry
from app.models.parent_student import ParentStudent
from app.models.remark import Remark
from app.models.report_card import ReportCard
from app.models.school import School
from app.models.subject import Subject
from app.models.user import User
from app.services.gradebook_service import get_student_gradebook_summary
from app.services.notify import dispatch_bulk, dispatch_notification


def generate_single_report_card(
    db: Session,
    student_id: int,
    term: str = "Term 1",
    academic_year: str = "2026-27",
) -> ReportCard:
    """Generates or updates a complete academic report card snapshot for a student."""
    student = db.query(User).filter(User.id == student_id).one_or_none()
    if not student:
        raise ValueError("Student not found")

    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.student_id == student_id, Enrollment.is_primary.is_(True))
        .first()
    )
    class_id = enrollment.class_id if enrollment else 1
    school_class = db.query(SchoolClass).filter(SchoolClass.id == class_id).one_or_none()
    school = db.query(School).filter(School.id == student.school_id).one_or_none()

    # 1. Gradebook summary
    grades_data = get_student_gradebook_summary(db, student_id, term)

    # 2. Person A Attendance aggregation
    attendance_records = (
        db.query(AttendanceRecord)
        .filter(AttendanceRecord.student_id == student_id)
        .all()
    )
    total_days = len(attendance_records)
    present_days = sum(1 for r in attendance_records if r.status in ("present", "late"))
    attendance_pct = round((present_days / total_days) * 100.0, 1) if total_days > 0 else 100.0

    # 3. Teacher Remarks
    remarks = (
        db.query(Remark)
        .filter(Remark.student_id == student_id)
        .order_by(Remark.created_at.desc())
        .limit(5)
        .all()
    )
    remarks_list = [
        {
            "content": r.content,
            "sentiment": r.sentiment_tag,
            "date": r.created_at.strftime("%b %d, %Y"),
        }
        for r in remarks
    ]

    # 4. Structured Snapshot
    snapshot = {
        "school_name": school.name if school else "EduOps AI Academy",
        "student_name": student.full_name or student.email,
        "student_id": student.id,
        "class_name": school_class.name if school_class else f"Class #{class_id}",
        "academic_year": academic_year,
        "term": term,
        "generated_date": datetime.now(timezone.utc).strftime("%B %d, %Y"),
        "subjects": grades_data["subjects"],
        "term_average": grades_data["term_average"],
        "gpa": grades_data["gpa"],
        "letter_grade": grades_data["letter_grade"],
        "attendance": {
            "total_days": total_days,
            "present_days": present_days,
            "percentage": attendance_pct,
        },
        "teacher_remarks": remarks_list,
    }

    # 5. Upsert report card record
    existing = (
        db.query(ReportCard)
        .filter(
            ReportCard.student_id == student_id,
            ReportCard.term == term,
            ReportCard.academic_year == academic_year,
        )
        .first()
    )

    pdf_stub_url = f"/api/report_cards/download/{student_id}_{term.replace(' ', '_')}.pdf"

    if existing:
        existing.class_id = class_id
        existing.pdf_url = pdf_stub_url
        existing.gpa = grades_data["gpa"]
        existing.term_average = grades_data["term_average"]
        existing.attendance_percentage = attendance_pct
        existing.source_data_snapshot = snapshot
        existing.updated_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(existing)
        report_card = existing
    else:
        report_card = ReportCard(
            school_id=student.school_id,
            student_id=student_id,
            class_id=class_id,
            term=term,
            academic_year=academic_year,
            pdf_url=pdf_stub_url,
            gpa=grades_data["gpa"],
            term_average=grades_data["term_average"],
            attendance_percentage=attendance_pct,
            source_data_snapshot=snapshot,
        )
        db.add(report_card)
        db.commit()
        db.refresh(report_card)

    # Person C Parent Notification
    parent_ids = [
        row.parent_id
        for row in db.query(ParentStudent.parent_id).filter(ParentStudent.student_id == student_id).all()
    ]
    if parent_ids:
        dispatch_bulk(
            db,
            user_ids=parent_ids,
            source_type="report_card_ready",
            title=f"Report Card Published ({term})",
            body=f"The academic report card for {snapshot['student_name']} ({term}) is now available with GPA {grades_data['gpa'] or '—'}.",
            priority="important",
            source_id=report_card.id,
        )

    return report_card


def bulk_generate_class_report_cards(
    db: Session,
    class_id: int,
    term: str = "Term 1",
    academic_year: str = "2026-27",
) -> list[ReportCard]:
    """Fast batch generation for all students enrolled in a class section."""
    student_ids = [
        row.student_id
        for row in db.query(Enrollment.student_id)
        .filter(Enrollment.class_id == class_id)
        .distinct()
        .all()
    ]

    cards = []
    for sid in student_ids:
        cards.append(generate_single_report_card(db, sid, term, academic_year))

    return cards
