"""THE one place attendance is counted. Every surface that shows a percentage calls this.

WHY THIS EXISTS. Four surfaces each computed attendance their own way and produced three
different numbers for the same child on the same day:

    parent portal     Aarav 81.5%   Diya 59.1%     30-day window, present-only
    student analytics       88.9%        71.0%     ALL time, late counted as present
    report card             88.9%        71.0%     ALL time, late counted as present
    risk scorer       (fed the portal's window, so it agreed with the portal)

Two independent divergences: the window, and whether `late` counts as present. A judge
comparing the parent portal to the report card saw two different numbers for one child
with no explanation. A third defect was shared: zero attendance records returned
**100.0%**, so a student with no data read as perfect rather than unknown.

THE RULES, now singular:

  1. `present_pct` counts ONLY `status == "present"`. Late is real information and is
     returned separately as `late_count`, but a late arrival is not a present day and
     folding it in silently inflates every figure.
  2. Zero records returns `present_pct = None`, never 0.0 and never 100.0. No data is
     not the same as perfect attendance, and it is not the same as total absence.
     Callers decide how to render None; none of them may invent a number for it.
  3. The WINDOW is the caller's choice and is returned in the result, so a surface can
     label what it is showing.

DIFFERENT WINDOWS ARE FINE - UNLABELLED ONES ARE NOT. The portal, the risk scorer and
student analytics all pass the 30-day lookback and therefore agree exactly. The report
card deliberately passes the academic year, because a transcript covering the last 30
days would be a strange document. That number is legitimately different and is labelled
"Attendance — 2026-27" wherever it appears, so it reads as a different measure rather
than a contradiction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models.attendance import AttendanceRecord


@dataclass(frozen=True)
class AttendanceSnapshot:
    """Counts plus the window they were taken over."""

    present_count: int
    absent_count: int
    late_count: int
    total_records: int
    present_pct: float | None
    """present / total, as a percentage. None when total_records == 0 - see rule 2."""
    start_date: date | None
    end_date: date | None
    label: str
    """Human-readable description of the window, for the UI to render beside the number
    (e.g. "Last 30 days" or "Attendance — 2026-27"). Resolved here so two surfaces
    cannot describe the same window differently."""


def attendance_snapshot(
    db: Session,
    student_id: int,
    *,
    start: date | None = None,
    end: date | None = None,
    label: str = "",
) -> AttendanceSnapshot:
    """Attendance counts for one student over an inclusive [start, end] date range.

    `start=None` means "no lower bound" (all history); `end=None` means "up to today".
    """
    query = db.query(AttendanceRecord).filter(AttendanceRecord.student_id == student_id)
    if start is not None:
        query = query.filter(AttendanceRecord.date >= start)
    if end is not None:
        query = query.filter(AttendanceRecord.date <= end)
    records = query.all()

    present = sum(1 for r in records if r.status == "present")
    absent = sum(1 for r in records if r.status == "absent")
    late = sum(1 for r in records if r.status == "late")
    total = len(records)

    return AttendanceSnapshot(
        present_count=present,
        absent_count=absent,
        late_count=late,
        total_records=total,
        # Rule 1: present-only. Rule 2: None, not 0.0 and not 100.0, when there is nothing.
        present_pct=round(100.0 * present / total, 1) if total else None,
        start_date=start,
        end_date=end,
        label=label,
    )


def lookback_snapshot(db: Session, student_id: int, days: int) -> AttendanceSnapshot:
    """The rolling window the parent portal, risk scorer and student analytics share.

    All three call this, so all three agree by construction rather than by three
    independent implementations happening to match.
    """
    return attendance_snapshot(
        db,
        student_id,
        start=date.today() - timedelta(days=days),
        label=f"Last {days} days",
    )


def academic_year_bounds(academic_year: str) -> tuple[date, date]:
    """(start, end) for an academic year string like "2026-27".

    Convention: 1 April of the first year to 31 March of the second, matching the Indian
    school year this project models. Deliberately derived from the string the report card
    already carries rather than from a new term table or from SyllabusPlan - most classes
    have no syllabus plan, so depending on one would make attendance unavailable for them.
    """
    start_year = int(academic_year.split("-")[0])
    return date(start_year, 4, 1), date(start_year + 1, 3, 31)


def academic_year_snapshot(db: Session, student_id: int, academic_year: str) -> AttendanceSnapshot:
    """The report card's window: the whole academic year, labelled as such."""
    start, end = academic_year_bounds(academic_year)
    return attendance_snapshot(
        db,
        student_id,
        start=start,
        end=end,
        label=f"Attendance — {academic_year}",
    )
