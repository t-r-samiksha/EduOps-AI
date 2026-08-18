"""Populate Person B's features (classroom, assignments, quizzes, gradebook, report
cards, library, remarks) with realistic data for Riverside Public School (5707).

WHY THIS EXISTS. Person B built their features against school 6318 and every one of
their tables had ZERO rows in 5707 - the demo school. Eleven nav entries per role were
clickable and rendered empty. This fills them using the classes, subjects, teachers and
students that already exist in 5707, so the academics screens agree with the
operational ones instead of looking like a different product.

CONSISTENT WITH THE EXISTING STORY, deliberately:
  - Aarav Kumar performs well; Diya Kumar does not, and has a missing submission and a
    late one. That matches her attendance (59%), her negative remarks and her open
    medium risk flag, so a judge who clicks from Early-Warning into Gradebook sees the
    same child, not a contradiction.
  - Meera Iyer teaches Math to BOTH 3-A and 3-B, which is what makes the cross-section
    Top Doubts cluster real.

Dates are anchored to seed_riverside_fixtures.SEED_ANCHOR_DATE rather than
date.today(), for the reasons documented on that constant - re-running on a different
day must not move the fixtures.

Idempotent. Every insert is guarded by a natural key, so re-running creates nothing and
reports "nothing created". Only ever inserts - never updates or deletes rows it finds.

    python -m scripts.seed_person_b_riverside --force
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.assignment import Assignment, AssignmentSubmission
from app.models.class_ import SchoolClass
from app.models.classroom import Classroom, StreamPost
from app.models.gradebook import GradebookEntry, GradebookWeight
from app.models.library import LibraryItem, LibraryLoan
from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
from app.models.remark import Remark
from app.models.report_card import ReportCard
from app.models.subject import Subject
from app.services.attendance_stats import academic_year_snapshot
from app.models.user import User
from scripts.seed_riverside_fixtures import SEED_ANCHOR_DATE

SCHOOL_ID = 5707
ACADEMIC_YEAR = "2026-27"
TERM = "Term 1"

CLASS_A_NAME = "Grade 3 - A"
CLASS_B_NAME = "Grade 3 - B"

ANCHOR = SEED_ANCHOR_DATE


def _dt(days_offset: int, hour: int = 9) -> datetime:
    """A timezone-aware datetime relative to the fixed anchor."""
    return datetime.combine(ANCHOR + timedelta(days=days_offset), time(hour, 0), tzinfo=timezone.utc)


def _counted(counts: dict, key: str, n: int = 1) -> None:
    if n:
        counts[key] = counts.get(key, 0) + n


# --- lookups ------------------------------------------------------------------------


def _resolve(db: Session) -> dict:
    """Resolve every entity by natural key. Nothing here is hardcoded by id, so this
    still works against a rebuilt database."""
    classes = {
        c.name: c
        for c in db.query(SchoolClass).filter(SchoolClass.school_id == SCHOOL_ID).all()
    }
    subjects = {
        s.name: s for s in db.query(Subject).filter(Subject.school_id == SCHOOL_ID).all()
    }
    teachers = {
        u.email: u
        for u in db.query(User).filter(User.school_id == SCHOOL_ID).all()
        if u.email and ".teacher@" in u.email
    }
    missing = []
    for name in (CLASS_A_NAME, CLASS_B_NAME):
        if name not in classes:
            missing.append(f"class {name!r}")
    for name in ("Math", "Science", "English"):
        if name not in subjects:
            missing.append(f"subject {name!r}")
    if missing:
        sys.exit(
            "Riverside base data is missing: "
            + ", ".join(missing)
            + "\nRun `python -m scripts.seed_riverside_fixtures --force` first."
        )
    return {"classes": classes, "subjects": subjects, "teachers": teachers}


def _students_in(db: Session, class_id: int) -> list[User]:
    from app.models.enrollment import Enrollment

    rows = (
        db.query(User)
        .join(Enrollment, Enrollment.student_id == User.id)
        .filter(Enrollment.class_id == class_id, User.school_id == SCHOOL_ID)
        .order_by(User.id)
        .all()
    )
    return rows


def _teacher_for(db: Session, class_id: int, subject_id: int, fallback: User | None) -> User | None:
    """Whoever actually teaches this class+subject on the timetable - not a guess."""
    from app.models.timetable import TimetableSlot

    slot = (
        db.query(TimetableSlot)
        .filter(TimetableSlot.class_id == class_id, TimetableSlot.subject_id == subject_id)
        .first()
    )
    if slot is not None and slot.teacher_id:
        return db.query(User).filter(User.id == slot.teacher_id).one_or_none()
    return fallback


# --- classroom stream ---------------------------------------------------------------

STREAM_POSTS = {
    "Math": [
        ("announcement", "Multiplication tables test on Friday",
         "We'll cover tables 2 through 12. Ten minutes, no calculators. Revise the "
         "regrouping worksheet from last week."),
        ("note", "Why we carry the one",
         "A few of you asked about this in class. When a column adds to more than 9, "
         "the tens digit moves to the next column - that's all carrying is. The small "
         "number written above is the part being carried."),
        ("material", "Regrouping practice sheet",
         "Twenty questions, worked answers on the back. Try them without the answers "
         "first."),
    ],
    "Science": [
        ("announcement", "Bring a leaf on Thursday",
         "Any leaf from your garden or the school grounds. We're looking at how plants "
         "make their food."),
        ("note", "Photosynthesis in one line",
         "Plants use sunlight, water and carbon dioxide to make their own food, and "
         "release oxygen while doing it. They do not eat soil - the soil gives them "
         "water and minerals."),
    ],
    "English": [
        ("announcement", "Reading aloud on Monday",
         "Each of you will read one short paragraph. Practise at home - expression "
         "matters more than speed."),
        ("note", "Nouns and adjectives",
         "A noun names something. An adjective describes it. In 'the red kite', 'kite' "
         "is the noun and 'red' is the adjective."),
    ],
}


def seed_classrooms(db: Session, ctx: dict, counts: dict) -> dict:
    """One classroom per class+subject, each with a few stream posts."""
    made = {}
    for class_name in (CLASS_A_NAME, CLASS_B_NAME):
        school_class = ctx["classes"][class_name]
        for subject_name, posts in STREAM_POSTS.items():
            subject = ctx["subjects"][subject_name]
            teacher = _teacher_for(db, school_class.id, subject.id, None)
            if teacher is None:
                continue

            classroom = (
                db.query(Classroom)
                .filter(
                    Classroom.class_id == school_class.id,
                    Classroom.subject_id == subject.id,
                )
                .one_or_none()
            )
            if classroom is None:
                classroom = Classroom(
                    school_id=SCHOOL_ID,
                    class_id=school_class.id,
                    class_name=f"{class_name} - {subject_name}",
                    subject_id=subject.id,
                    teacher_id=teacher.id,
                )
                db.add(classroom)
                db.flush()
                _counted(counts, "classrooms")
            made[(class_name, subject_name)] = classroom

            for offset, (post_type, title, content) in enumerate(posts):
                existing = (
                    db.query(StreamPost)
                    .filter(StreamPost.classroom_id == classroom.id, StreamPost.title == title)
                    .one_or_none()
                )
                if existing is not None:
                    continue
                db.add(StreamPost(
                    classroom_id=classroom.id,
                    author_id=teacher.id,
                    post_type=post_type,
                    title=title,
                    content=content,
                    created_at=_dt(-10 + offset * 2, 8),
                ))
                _counted(counts, "stream_posts")
    db.flush()
    return made


# --- assignments + submissions ------------------------------------------------------

ASSIGNMENTS = [
    # (subject, title, description, days_from_anchor, max_marks)
    ("Math", "Multiplication worksheet 4",
     "Questions 1-20 on the regrouping sheet. Show your working for the carried digits.",
     -6, 20),
    ("Math", "Word problems: money",
     "Five problems using rupees and paise. Write the full number sentence.", 4, 15),
    ("Science", "Leaf observation",
     "Draw the leaf you brought in and label the parts. One paragraph on what you noticed.",
     -3, 10),
    ("English", "Paragraph: my favourite place",
     "Six to eight sentences. Use at least four adjectives and underline them.", 5, 10),
]

# How each student performs. Aarav strong, Diya struggling - deliberately matching her
# 59% attendance, negative remarks and open risk flag.
PERFORMANCE = {
    "Aarav Kumar":  {"submit": True,  "grade_pct": 0.90, "late": False},
    "Diya Kumar":   {"submit": False, "grade_pct": None,  "late": False},
    "Kabir Sharma": {"submit": True,  "grade_pct": 0.75, "late": False},
    "Anaya Iyer":   {"submit": True,  "grade_pct": 0.85, "late": True},
    "Rohan Das":    {"submit": True,  "grade_pct": 0.60, "late": False},
}
DEFAULT_PERF = {"submit": True, "grade_pct": 0.70, "late": False}


def seed_assignments(db: Session, ctx: dict, counts: dict) -> list[Assignment]:
    created = []
    for class_name in (CLASS_A_NAME, CLASS_B_NAME):
        school_class = ctx["classes"][class_name]
        students = _students_in(db, school_class.id)
        for subject_name, title, description, day_offset, max_marks in ASSIGNMENTS:
            subject = ctx["subjects"][subject_name]
            teacher = _teacher_for(db, school_class.id, subject.id, None)
            if teacher is None:
                continue

            assignment = (
                db.query(Assignment)
                .filter(
                    Assignment.class_id == school_class.id,
                    Assignment.subject_id == subject.id,
                    Assignment.title == title,
                )
                .one_or_none()
            )
            if assignment is None:
                assignment = Assignment(
                    school_id=SCHOOL_ID,
                    class_id=school_class.id,
                    subject_id=subject.id,
                    teacher_id=teacher.id,
                    title=title,
                    description=description,
                    deadline=_dt(day_offset, 17),
                    max_marks=max_marks,
                    created_at=_dt(day_offset - 7, 8),
                )
                db.add(assignment)
                db.flush()
                _counted(counts, "assignments")
            created.append(assignment)

            # Only past-deadline assignments have submissions - an upcoming one with
            # everything already graded would read as fabricated.
            if day_offset >= 0:
                continue

            for student in students:
                perf = PERFORMANCE.get(student.full_name, DEFAULT_PERF)
                if not perf["submit"]:
                    continue  # deliberately missing - this is what nudge-missing is for
                existing = (
                    db.query(AssignmentSubmission)
                    .filter(
                        AssignmentSubmission.assignment_id == assignment.id,
                        AssignmentSubmission.student_id == student.id,
                    )
                    .one_or_none()
                )
                if existing is not None:
                    continue
                submitted = _dt(day_offset + (1 if perf["late"] else -1), 14)
                grade = round(max_marks * perf["grade_pct"], 1) if perf["grade_pct"] else None
                db.add(AssignmentSubmission(
                    assignment_id=assignment.id,
                    student_id=student.id,
                    file_url=f"assignments/{assignment.id}/{student.id}.pdf",
                    file_name=f"{student.full_name.split()[0].lower()}-{assignment.id}.pdf",
                    file_size=182_000,
                    grade=grade,
                    feedback=(
                        "Clear working, well presented." if perf["grade_pct"] and perf["grade_pct"] >= 0.85
                        else "Good effort - check your carrying in questions 7 and 12."
                    ),
                    status="late" if perf["late"] else "graded",
                    submitted_at=submitted,
                    graded_at=_dt(day_offset + 2, 16),
                ))
                _counted(counts, "assignment_submissions")
    db.flush()
    return created


# --- quizzes ------------------------------------------------------------------------

QUIZ_QUESTIONS = [
    ("What is 7 x 8?", "54", "56", "48", "64", "B", 1),
    ("When adding 47 and 38, what do you carry into the tens column?", "1", "2", "7", "0", "A", 1),
    ("What is 12 x 6?", "62", "72", "76", "66", "B", 1),
    ("Which of these is the same as 'regrouping'?", "Sharing", "Carrying", "Halving", "Counting", "B", 1),
]

QUIZ_SCORES = {
    "Aarav Kumar": 4, "Diya Kumar": 2, "Kabir Sharma": 3, "Anaya Iyer": 4, "Rohan Das": 2,
}


def seed_quizzes(db: Session, ctx: dict, counts: dict) -> None:
    subject = ctx["subjects"]["Math"]
    for class_name in (CLASS_A_NAME, CLASS_B_NAME):
        school_class = ctx["classes"][class_name]
        teacher = _teacher_for(db, school_class.id, subject.id, None)
        if teacher is None:
            continue
        title = "Multiplication and regrouping check"

        quiz = (
            db.query(Quiz)
            .filter(Quiz.class_id == school_class.id, Quiz.title == title)
            .one_or_none()
        )
        if quiz is None:
            quiz = Quiz(
                school_id=SCHOOL_ID,
                class_id=school_class.id,
                subject_id=subject.id,
                teacher_id=teacher.id,
                title=title,
                description="Four questions. Ten minutes. Covers tables and carrying.",
                duration_minutes=10,
                available_from=_dt(-5, 9),
                available_until=_dt(2, 17),
                created_at=_dt(-7, 8),
            )
            db.add(quiz)
            db.flush()
            _counted(counts, "quizzes")

        for order, (qt, a, b, c, d, correct, marks) in enumerate(QUIZ_QUESTIONS):
            existing = (
                db.query(QuizQuestion)
                .filter(QuizQuestion.quiz_id == quiz.id, QuizQuestion.question_text == qt)
                .one_or_none()
            )
            if existing is not None:
                continue
            db.add(QuizQuestion(
                quiz_id=quiz.id, question_text=qt,
                option_a=a, option_b=b, option_c=c, option_d=d,
                correct_option=correct, marks=marks, order_index=order,
            ))
            _counted(counts, "quiz_questions")
        db.flush()

        total = sum(q[6] for q in QUIZ_QUESTIONS)
        for student in _students_in(db, school_class.id):
            existing = (
                db.query(QuizAttempt)
                .filter(QuizAttempt.quiz_id == quiz.id, QuizAttempt.student_id == student.id)
                .one_or_none()
            )
            if existing is not None:
                continue
            score = QUIZ_SCORES.get(student.full_name, 3)
            answers = {
                str(i + 1): (q[5] if i < score else "C")
                for i, q in enumerate(QUIZ_QUESTIONS)
            }
            db.add(QuizAttempt(
                quiz_id=quiz.id, student_id=student.id, answers=answers,
                score=score, total_marks=total,
                started_at=_dt(-4, 10), submitted_at=_dt(-4, 10),
            ))
            _counted(counts, "quiz_attempts")
    db.flush()


# --- gradebook ----------------------------------------------------------------------

GRADEBOOK = {
    # student -> {subject: [(assessment_type, score_pct)]}
    "Aarav Kumar":  {"Math": [("assignment", 0.90), ("quiz", 1.00), ("midterm", 0.86)],
                     "Science": [("assignment", 0.88), ("midterm", 0.82)],
                     "English": [("assignment", 0.92), ("midterm", 0.89)]},
    "Diya Kumar":   {"Math": [("assignment", 0.40), ("quiz", 0.50), ("midterm", 0.45)],
                     "Science": [("assignment", 0.52), ("midterm", 0.48)],
                     "English": [("assignment", 0.58), ("midterm", 0.55)]},
    "Kabir Sharma": {"Math": [("assignment", 0.75), ("quiz", 0.75), ("midterm", 0.72)],
                     "Science": [("assignment", 0.70), ("midterm", 0.74)]},
    "Anaya Iyer":   {"Math": [("assignment", 0.85), ("quiz", 1.00), ("midterm", 0.88)],
                     "Science": [("assignment", 0.80), ("midterm", 0.84)]},
    "Rohan Das":    {"Math": [("assignment", 0.60), ("quiz", 0.50), ("midterm", 0.58)],
                     "Science": [("assignment", 0.64), ("midterm", 0.62)]},
}
MAX_SCORE = 100.0


def seed_gradebook(db: Session, ctx: dict, counts: dict) -> None:
    existing_weight = (
        db.query(GradebookWeight)
        .filter(GradebookWeight.school_id == SCHOOL_ID, GradebookWeight.term == TERM)
        .one_or_none()
    )
    if existing_weight is None:
        db.add(GradebookWeight(
            school_id=SCHOOL_ID, term=TERM,
            assignment_weight=0.30, quiz_weight=0.20,
            midterm_weight=0.20, final_weight=0.30,
        ))
        _counted(counts, "gradebook_weights")
        db.flush()

    for class_name in (CLASS_A_NAME, CLASS_B_NAME):
        school_class = ctx["classes"][class_name]
        for student in _students_in(db, school_class.id):
            plan = GRADEBOOK.get(student.full_name)
            if not plan:
                continue
            for subject_name, rows in plan.items():
                subject = ctx["subjects"].get(subject_name)
                if subject is None:
                    continue
                for assessment_type, pct in rows:
                    existing = (
                        db.query(GradebookEntry)
                        .filter(
                            GradebookEntry.student_id == student.id,
                            GradebookEntry.subject_id == subject.id,
                            GradebookEntry.term == TERM,
                            GradebookEntry.assessment_type == assessment_type,
                        )
                        .one_or_none()
                    )
                    if existing is not None:
                        continue
                    db.add(GradebookEntry(
                        school_id=SCHOOL_ID,
                        student_id=student.id,
                        subject_id=subject.id,
                        class_id=school_class.id,
                        term=TERM,
                        assessment_type=assessment_type,
                        score=round(MAX_SCORE * pct, 1),
                        max_score=MAX_SCORE,
                        weight=1.0,
                        created_at=_dt(-8, 12),
                    ))
                    _counted(counts, "gradebook_entries")
    db.flush()


# --- report cards -------------------------------------------------------------------


def seed_report_cards(db: Session, ctx: dict, counts: dict) -> None:
    """Generated from the gradebook rows above, via Person B's own service so the
    numbers agree with what GET /gradebook/{id} returns."""
    from app.services.gradebook_service import get_student_gradebook_summary

    for class_name in (CLASS_A_NAME, CLASS_B_NAME):
        school_class = ctx["classes"][class_name]
        for student in _students_in(db, school_class.id):
            existing = (
                db.query(ReportCard)
                .filter(
                    ReportCard.student_id == student.id,
                    ReportCard.term == TERM,
                    ReportCard.academic_year == ACADEMIC_YEAR,
                )
                .one_or_none()
            )
            if existing is not None:
                continue
            summary = get_student_gradebook_summary(db, student.id, TERM)
            # N-1: this used to pass attendance_percentage=None, so every seeded report
            # card read "No data" for attendance until someone regenerated it. Computed
            # here from the same shared helper the live path uses, over the academic year
            # (see services/attendance_stats.py for why the report card uses that window).
            att = academic_year_snapshot(db, student.id, ACADEMIC_YEAR)
            if not summary.get("subjects"):
                continue
            db.add(ReportCard(
                school_id=SCHOOL_ID,
                student_id=student.id,
                class_id=school_class.id,
                term=TERM,
                academic_year=ACADEMIC_YEAR,
                gpa=summary.get("gpa"),
                term_average=summary.get("term_average"),
                attendance_percentage=att.present_pct,
                source_data_snapshot=summary,
                generated_at=_dt(-1, 11),
            ))
            _counted(counts, "report_cards")
    db.flush()


# --- library ------------------------------------------------------------------------

LIBRARY = [
    ("The Magic Faraway Tree", "Enid Blyton", "9780603566578", "Fiction", "book", 3, 3),
    ("Panchatantra Stories", "Vishnu Sharma", "9788175994461", "Fiction", "book", 4, 4),
    ("How Things Work", "David Macaulay", "9780756619541", "Reference", "book", 2, 2),
    ("Grade 3 Mathematics Workbook", "NCERT", "9788174504890", "Textbook", "book", 6, 6),
    ("The Story of Plants", "Ruskin Bond", "9788129135698", "Science", "book", 2, 2),
    ("Young Scientist Magazine - Issue 12", "Various", None, "Periodical", "magazine", 5, 5),
]

LOANS = [
    # (student full name, item title, issued days ago, due in days, returned?)
    ("Aarav Kumar", "The Story of Plants", -12, -5, True),
    ("Aarav Kumar", "How Things Work", -4, 10, False),
    ("Diya Kumar", "Panchatantra Stories", -21, -7, False),   # overdue, matches her story
    ("Kabir Sharma", "The Magic Faraway Tree", -6, 8, False),
    ("Anaya Iyer", "Grade 3 Mathematics Workbook", -9, 5, False),
]


def seed_library(db: Session, ctx: dict, counts: dict) -> None:
    items = {}
    for title, author, isbn, category, kind, avail, total in LIBRARY:
        item = (
            db.query(LibraryItem)
            .filter(LibraryItem.school_id == SCHOOL_ID, LibraryItem.title == title)
            .one_or_none()
        )
        if item is None:
            item = LibraryItem(
                school_id=SCHOOL_ID, title=title, author=author, isbn=isbn,
                category=category, type=kind,
                available_copies=avail, total_copies=total,
            )
            db.add(item)
            db.flush()
            _counted(counts, "library_items")
        items[title] = item

    students = {}
    for class_name in (CLASS_A_NAME, CLASS_B_NAME):
        for s in _students_in(db, ctx["classes"][class_name].id):
            students[s.full_name] = s

    librarian = next(iter(ctx["teachers"].values()), None)
    for student_name, item_title, issued_offset, due_offset, returned in LOANS:
        student = students.get(student_name)
        item = items.get(item_title)
        if student is None or item is None or librarian is None:
            continue
        existing = (
            db.query(LibraryLoan)
            .filter(
                LibraryLoan.student_id == student.id,
                LibraryLoan.library_item_id == item.id,
                LibraryLoan.issued_at == _dt(issued_offset, 10),
            )
            .one_or_none()
        )
        if existing is not None:
            continue
        db.add(LibraryLoan(
            school_id=SCHOOL_ID,
            library_item_id=item.id,
            student_id=student.id,
            issued_by=librarian.id,
            issued_at=_dt(issued_offset, 10),
            due_date=(ANCHOR + timedelta(days=due_offset)),
            returned_at=_dt(due_offset - 1, 15) if returned else None,
            # Vocabulary is active/returned/overdue (see LibraryLoan.status and
            # library_service.update_overdue_loans, which only sweeps "active").
            # "issued" is NOT recognised - a past-due loan written that way would
            # never flip to overdue.
            status="returned" if returned else "active",
        ))
        _counted(counts, "library_loans")
    db.flush()


# --- remarks (Person B's `remarks` table) -------------------------------------------

REMARKS = {
    "Aarav Kumar": [
        ("Math", "Asks genuinely good questions and helps others at his table.", "appreciation"),
        ("English", "Reads aloud with lovely expression. A pleasure to teach.", "appreciation"),
    ],
    "Diya Kumar": [
        ("Math", "Has missed the last two worksheets. Falling behind on regrouping.", "academic"),
        ("Science", "Disengaged in class and rarely volunteers an answer now.", "behavioral"),
    ],
    "Kabir Sharma": [
        ("Math", "Steady progress this term. Working more carefully.", "academic"),
    ],
    "Anaya Iyer": [
        ("Math", "Excellent recall of tables. Ready for harder problems.", "appreciation"),
    ],
    "Rohan Das": [
        ("Science", "Needs to slow down and check his working.", "academic"),
    ],
}


def seed_remarks(db: Session, ctx: dict, counts: dict) -> None:
    """NOTE: this fills Person B's `remarks` table, which is NOT the same table the
    parent portal, Parent Bot and risk scorer read (`remark_stubs`). The two are
    deliberately not synchronised - see docs/audit/remarks-disconnect.md. The content
    here mirrors the sentiment of the remark_stubs rows on purpose, so the two screens
    tell the same story about the same child even though they read different tables."""
    for class_name in (CLASS_A_NAME, CLASS_B_NAME):
        school_class = ctx["classes"][class_name]
        for student in _students_in(db, school_class.id):
            for subject_name, content, tag in REMARKS.get(student.full_name, []):
                subject = ctx["subjects"].get(subject_name)
                if subject is None:
                    continue
                author = _teacher_for(db, school_class.id, subject.id, None)
                if author is None:
                    continue
                existing = (
                    db.query(Remark)
                    .filter(Remark.student_id == student.id, Remark.content == content)
                    .one_or_none()
                )
                if existing is not None:
                    continue
                db.add(Remark(
                    school_id=SCHOOL_ID,
                    student_id=student.id,
                    author_id=author.id,
                    class_id=school_class.id,
                    subject_id=subject.id,
                    content=content,
                    sentiment_tag=tag,
                    created_at=_dt(-5, 15),
                ))
                _counted(counts, "remarks")
    db.flush()


# --- Syllabus plans (Person A's pace tracker) -----------------------------------------
# Seeded so seam S-N is PROVABLE rather than assumed: school 5707 had zero syllabus
# plans, so GET /syllabus/summary returned items: [] and no "behind plan" warning could
# render on the teacher pace tracker no matter how the feature behaved.
#
# Term dates are anchored to SEED_ANCHOR_DATE and set PER PLAN, because term_start_date
# and term_end_date are per-plan columns - nothing in the schema owns "when is Term 1".
# All three start in the PAST on purpose: a plan whose term_start_date is today or later
# yields elapsed_days <= 0, which _clamp floors to 0, and "Expected 0%" then makes every
# logged checkpoint look ahead of schedule. That is exactly the confusing state observed
# in school 6318, and seeding into it would hide the pace feature rather than show it.
SYLLABUS_PLANS = [
    # (class_name, subject, days_since_term_start, term_length_days, total_units, checkpoints_logged)
    (CLASS_A_NAME, "Math", 40, 120, 10, 5),      # 33% elapsed, 50% done -> AHEAD
    (CLASS_A_NAME, "Science", 40, 120, 10, 3),   # 33% elapsed, 30% done -> on pace
    (CLASS_B_NAME, "Math", 60, 120, 12, 2),      # 50% elapsed, 17% done -> BEHIND
]

CHECKPOINT_TOPICS = [
    "Place value and regrouping", "Multiplication tables 2-5", "Multiplication tables 6-12",
    "Word problems with money", "Perimeter of simple shapes", "Introduction to fractions",
]


def _get_or_create_syllabus_plans(db: Session, ctx: dict, counts: dict) -> int:
    """One plan per class+subject, with some checkpoints logged. Idempotent by
    (class_id, subject_id, academic_year)."""
    from app.models.syllabus import SyllabusCheckpoint, SyllabusPlan

    created = 0
    for class_name, subject_name, since_start, term_len, total_units, logged in SYLLABUS_PLANS:
        school_class = ctx["classes"].get(class_name)
        subject = ctx["subjects"].get(subject_name)
        if school_class is None or subject is None:
            continue
        teacher = _teacher_for(db, school_class.id, subject.id, None)
        if teacher is None:
            continue

        plan = (
            db.query(SyllabusPlan)
            .filter(
                SyllabusPlan.class_id == school_class.id,
                SyllabusPlan.subject_id == subject.id,
                SyllabusPlan.academic_year == ACADEMIC_YEAR,
            )
            .one_or_none()
        )
        if plan is None:
            start = ANCHOR - timedelta(days=since_start)
            plan = SyllabusPlan(
                class_id=school_class.id,
                subject_id=subject.id,
                academic_year=ACADEMIC_YEAR,
                total_units=total_units,
                term_start_date=start,
                term_end_date=start + timedelta(days=term_len),
                created_by=teacher.id,
            )
            db.add(plan)
            db.flush()
            created += 1

        for i in range(logged):
            topic = CHECKPOINT_TOPICS[i % len(CHECKPOINT_TOPICS)]
            exists = (
                db.query(SyllabusCheckpoint)
                .filter(
                    SyllabusCheckpoint.plan_id == plan.id,
                    SyllabusCheckpoint.sequence_number == i + 1,
                )
                .one_or_none()
            )
            if exists is not None:
                continue
            db.add(SyllabusCheckpoint(
                plan_id=plan.id,
                topic_label=topic,
                sequence_number=i + 1,
                logged_by=teacher.id,
                logged_at=_dt(-since_start + (i * 5), 11),
            ))
            _counted(counts, "syllabus_checkpoints")
    if created:
        counts["syllabus_plans"] = counts.get("syllabus_plans", 0) + created
    db.flush()
    return created


# --- entrypoint ---------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="skip the confirmation prompt")
    args = parser.parse_args()

    if not args.force:
        reply = input(f"Seed Person B data into school {SCHOOL_ID} (Riverside)? [y/N] ")
        if reply.strip().lower() not in ("y", "yes"):
            sys.exit("aborted")

    db = SessionLocal()
    counts: dict[str, int] = {}
    try:
        ctx = _resolve(db)
        seed_classrooms(db, ctx, counts)
        seed_assignments(db, ctx, counts)
        seed_quizzes(db, ctx, counts)
        seed_gradebook(db, ctx, counts)
        seed_report_cards(db, ctx, counts)
        seed_library(db, ctx, counts)
        seed_remarks(db, ctx, counts)
        _get_or_create_syllabus_plans(db, ctx, counts)
        db.commit()
    except Exception:
        db.rollback()
        raise

    print(f"\nanchor date: {ANCHOR}  (matches seed_riverside_fixtures)")
    if counts:
        print("Rows created this run:")
        for k in sorted(counts):
            print(f"  {k:26} {counts[k]}")
    else:
        print("Rows created this run: none - everything already existed")

    print(
        "\nCalendar events are NOT written here - they are derived. Call\n"
        "  GET /calendar/{user_id}\n"
        "once per user and the sync builds them from these assignments, quizzes and exams."
    )
    db.close()


if __name__ == "__main__":
    main()
