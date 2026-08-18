"""Report Card Automation Service - Person B (Classroom & Academics).

Aggregates gradebook scores, Person A attendance, teacher remarks, and GPA
into structured transcripts and formatted report card snapshots.
Optimized for high performance bulk generation (< 30 seconds for 40 students).

NOTIFY ON FIRST PUBLICATION ONLY - this is a decision, not an oversight. Regenerating a
report card (which the upsert supports, and which bulk-generate does for a whole class)
sends NOTHING. Bulk-regenerating a class of 30 twice would otherwise deliver 60
notifications, and a parent missing a silent republish is the lesser harm. A genuine
republish worth announcing is rare enough to handle by hand.
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
from app.services.attendance_stats import academic_year_snapshot
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
    # M-2: the ACADEMIC YEAR, deliberately - a transcript covering the last 30 days
    # would be a strange document. This number legitimately differs from the parent
    # portal's rolling 30-day figure, so it travels with `attendance_label` and is shown
    # as "Attendance - 2026-27" wherever it appears, including the PDF. A different
    # measure, labelled, rather than a contradiction.
    att = academic_year_snapshot(db, student_id, academic_year)
    total_days = att.total_records
    present_days = att.present_count
    attendance_pct = att.present_pct  # None when there are no records - not 100.0

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
            "absent_days": att.absent_count,
            "late_days": att.late_count,
            "percentage": attendance_pct,
            # Rendered beside the number on screen AND in the PDF.
            "label": att.label,
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

    is_new = existing is None

    if existing:
        existing.class_id = class_id
        existing.pdf_url = pdf_stub_url
        existing.gpa = grades_data["gpa"]
        existing.term_average = grades_data["term_average"]
        existing.attendance_percentage = attendance_pct
        existing.source_data_snapshot = snapshot
        existing.updated_at = datetime.now(timezone.utc)
        db.flush()
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
        db.flush()

    # Parent notification.
    #
    # M-1: this used to sit AFTER a db.commit() in each branch above, with no commit of
    # its own - so the Notification rows were added to the session and silently dropped
    # when the request ended. Four generations produced exactly one notification: in a
    # bulk run each student's pending rows were flushed only by the NEXT student's
    # commit, so the last student's were always lost. The branches now flush, the
    # dispatch joins the same transaction, and one commit at the end covers both.
    #
    # Only on FIRST publication. Regenerating (which the upsert above supports, and
    # which bulk-generate does for a whole class) must not re-notify every parent -
    # bulk-regenerating a class of 30 twice would otherwise send 60 notifications.
    if is_new:
        parent_ids = [
            row.parent_id
            for row in db.query(ParentStudent.parent_id).filter(ParentStudent.student_id == student_id).all()
        ]
        if parent_ids:
            dispatch_bulk(
                db,
                user_ids=parent_ids,
                # M-7: was "report_card_ready", which is not in models/notification.py's
                # SOURCE_TYPES - the bell had no icon or route for it.
                source_type="report_card",
                title=f"Report Card Published ({term})",
                body=f"The academic report card for {snapshot['student_name']} ({term}) is now available with GPA {grades_data['gpa'] or '—'}.",
                priority="important",
                source_id=report_card.id,
            )

    db.commit()
    db.refresh(report_card)
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
