"""RAG chatbots. Student Doubt Bot today; teacher/parent bots reuse this core later.

SECURITY MODEL - read before adding another bot
--------------------------------------------------
`class_id` arrives in the request body and is a SECURITY BOUNDARY, not a filter. It is
validated against the caller's own enrollment (retrieval.assert_student_class_access)
BEFORE anything is embedded or retrieved. A student who edits the number in the request
must get a 403, not another class's notes. Any future bot must resolve its own scope
the same way - a teacher's taught classes, a parent's children's classes - and must
never pass a caller-supplied class_id straight into search_chunks().
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.knowledge import ChatbotLog
from app.models.resource import Resource
from app.models.school import School
from app.services.auth import CurrentUser, require_role
from app.routers.parent import child_summary
from app.services.doubt_insights import grade_subject_pairs_for_teacher, top_doubts
from app.services.ingestion import ingest_pending, ingest_resource
from app.services.llm import embed_query, generate
from app.services.scoping import assert_parent_linked
from app.services.retrieval import (
    DEFAULT_TOP_K,
    assert_student_class_access,
    infer_subject_id,
    search_chunks,
)

router = APIRouter(prefix="/bots", tags=["bots"])

def student_bot_system_prompt(*, school_name: str, grade_level: int) -> str:
    """Build the Doubt Bot's system prompt for THIS student's own school and grade.

    Both were hardcoded ("a Grade 3 student at Riverside Public School") in the first
    version, which meant a Grade 1 student at another school was greeted with the wrong
    school's name and had their reading level pitched at the wrong grade. Neither is a
    constant - they come from the class the caller already had to prove enrollment in.

    The grounded refusal is a FEATURE. An off-syllabus question should produce "that
    isn't in your notes", not a plausible general-knowledge answer - that is what makes
    the citations meaningful. The instruction to prefer the notes' own naming is what
    stops the model overriding school-specific conventions (the notes call a method the
    "Ladder Method"; a general model would happily rename it "partial products").
    """
    # Rough reading age for the grade, so the answer is pitched for the actual child.
    reading_age = grade_level + 5
    return f"""You are a patient teaching assistant for a Grade {grade_level} student at {school_name}.

Answer ONLY from the CONTEXT provided below. The context is the student's own class notes.

Rules you must follow:
- If the context does not contain the answer, say plainly that it is not in the class notes and suggest asking their teacher. Do NOT answer from your own general knowledge.
- Where the class notes use a specific name, method or convention, use theirs - even if you know a different common name for the same idea.
- Keep the answer short and use simple words a {reading_age}-year-old can read.
- Never invent numbers, dates or examples that are not in the context.
- Do not greet the student by naming their school; just answer the question.
"""


class StudentAskRequest(BaseModel):
    query: str
    class_id: int
    subject_id: int | None = None


class Citation(BaseModel):
    chunk_id: int
    source_id: int
    title: str | None
    snippet: str


class StudentAskResponse(BaseModel):
    answer: str
    citations: list[Citation]


def _build_context(chunks) -> str:
    return "\n\n---\n\n".join(
        f"[chunk {c.chunk_id}] {c.chunk_text}" for c in chunks
    )


@router.post("/student/ask", response_model=StudentAskResponse)
def student_ask(
    body: StudentAskRequest,
    user: CurrentUser = Depends(require_role("student")),
    db: Session = Depends(get_db),
):
    query = body.query.strip()
    if not query:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "query must not be empty")

    # Security boundary FIRST - before embedding, before retrieval, before any spend.
    # The client still names a CLASS it must prove enrollment in; the widening to
    # grade-level scope happens server-side from that validated class. Accepting a
    # grade_level from the client instead would let a student name any grade.
    school_id, grade_level = assert_student_class_access(db, student_id=user.id, class_id=body.class_id)

    query_embedding = embed_query(query)
    chunks = search_chunks(
        db,
        query_embedding=query_embedding,
        school_id=school_id,
        grade_level=grade_level,
        subject_id=body.subject_id,
        top_k=DEFAULT_TOP_K,
    )

    if not chunks:
        answer = (
            "I couldn't find anything about that in your class notes yet. "
            "Ask your teacher, or try asking about a topic you've covered in class."
        )
    else:
        school = db.query(School).filter(School.id == school_id).one_or_none()
        answer = generate(
            student_bot_system_prompt(
                school_name=school.name if school else "your school",
                grade_level=grade_level,
            ),
            f"CONTEXT:\n{_build_context(chunks)}\n\nSTUDENT'S QUESTION: {query}",
        )

    db.add(
        ChatbotLog(
            user_id=user.id,
            bot_type="student",
            query=query,
            response=answer,
            kb_chunks_used={"chunk_ids": [c.chunk_id for c in chunks]},
            # Reuses the vector already computed above - the query is never embedded
            # twice. This is what Top Doubts clusters on.
            query_embedding=query_embedding,
            # The student's own class, NOT the grade - Top Doubts resolves grade from
            # this at query time and needs the section name for its cross-section badges.
            class_id=body.class_id,
            # Falls back to the subject of the material actually retrieved. The UI
            # never sends subject_id (a student doesn't classify their own question),
            # and Top Doubts filters by subject - so without this inference every real
            # question was logged with a NULL subject and never surfaced in the
            # teacher's widget. See retrieval.infer_subject_id.
            subject_id=body.subject_id or infer_subject_id(chunks),
        )
    )
    db.commit()

    return StudentAskResponse(
        answer=answer,
        citations=[
            Citation(
                chunk_id=c.chunk_id,
                source_id=c.source_id,
                title=c.title,
                snippet=c.chunk_text[:280].strip(),
            )
            for c in chunks
        ],
    )


# --- Parent Assistant Bot -------------------------------------------------------------
# STRUCTURED CONTEXT, NOT RAG. A child's attendance, remarks, risk and fees are never
# embedded and never enter kb_chunks: that corpus is grade-scoped teaching material
# shared across a whole grade, so putting one child's record in it would make another
# family's questions able to retrieve it. Instead the aggregate endpoint's own response
# is serialized straight into the prompt.

PARENT_BOT_SYSTEM_PROMPT = """You are a school assistant talking to a parent about their own child.

You will be given that child's real record: attendance, teacher remarks, any early-warning flag, and fee status.

Rules you must follow:
- Use ONLY the data provided. Never invent a number, a date, a subject or a teacher's opinion.
- If the data does not answer the question, say so plainly and suggest they contact the school. Do not speculate.
- Be warm but factual. You are speaking to a worried parent, not writing a report.
- NEVER give medical, psychological or diagnostic opinions. Do not suggest a condition, a diagnosis, or a therapy. If asked, say that is a conversation for the school and a doctor.
- Do not predict the future ("she will fail", "he'll be fine"). Describe what the record shows.
- Plain language, short paragraphs. No jargon, no bullet-point dumps.
- Refer to the child by name.
"""
"""The prohibitions are the load-bearing part. A parent asking "is something wrong with
my daughter" is the likeliest real question, and a model left to its own devices will
happily speculate about attention disorders from an attendance dip. The data is also
genuinely thin (no grades exist in this schema), so "I don't have that" has to be an
acceptable answer rather than something the model talks its way around."""


class ParentAskRequest(BaseModel):
    query: str
    student_id: int
    """SECURITY BOUNDARY - validated with assert_parent_linked on every request. The
    frontend child selector is never trusted."""


@router.post("/parent/ask", response_model=StudentAskResponse)
def parent_ask(
    body: ParentAskRequest,
    user: CurrentUser = Depends(require_role("parent")),
    db: Session = Depends(get_db),
):
    """Answer a parent's question about their own child, grounded in that child's record.

    Reuses the exact aggregate GET /parent/child/{id}/summary returns - calling the same
    function rather than re-querying, so the bot can never disagree with the portal page
    the parent is looking at.
    """
    query = body.query.strip()
    if not query:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "query must not be empty")

    # Security boundary FIRST, before any spend.
    assert_parent_linked(db, user.id, body.student_id)
    summary = child_summary(student_id=body.student_id, user=user, db=db)

    answer = generate(PARENT_BOT_SYSTEM_PROMPT, _parent_context(summary, query))

    db.add(
        ChatbotLog(
            user_id=user.id,
            bot_type="parent",
            query=query,
            response=answer,
            kb_chunks_used=None,  # no retrieval happened - this is structured context
            # DELIBERATELY NULL. Top Doubts clusters chatbot_logs by (school, grade,
            # subject) to show teachers what STUDENTS are confused about. A parent
            # asking "how is my child doing" is not a student doubt, and embedding it
            # here would pull it into Meera's cluster feed as if it were one. The
            # clustering skips null-embedding rows, so this is the isolation.
            query_embedding=None,
            class_id=summary.student.class_id,
            subject_id=None,
        )
    )
    db.commit()

    # Same response shape as the student bot so ChatShell needs no branching. Citations
    # are empty because nothing was retrieved - the "source" is the child's own record,
    # which the parent is already looking at on the portal page.
    return StudentAskResponse(answer=answer, citations=[])


def _parent_context(summary, query: str) -> str:
    """Serialize the child's record as readable lines rather than raw JSON - the model
    follows plain labelled text more reliably than it does nested objects, and it keeps
    the prompt auditable when a bad answer needs explaining."""
    attendance = summary.attendance
    lines = [
        f"CHILD: {summary.student.name}, {summary.student.class_name or 'class unknown'}"
        f" (grade {summary.student.grade_level if summary.student.grade_level is not None else 'unknown'})",
        "",
        f"ATTENDANCE (last {attendance.days} days): {attendance.present_pct}% present "
        f"- {attendance.present_count} present, {attendance.absent_count} absent, {attendance.late_count} late",
    ]

    if summary.risk is not None:
        lines += [
            "",
            f"EARLY-WARNING FLAG: {summary.risk.level} risk. Reasons the school recorded:",
            *[f"  - {reason}" for reason in summary.risk.reasons],
        ]
    else:
        lines += ["", "EARLY-WARNING FLAG: none. This child is not currently flagged."]

    if summary.remarks:
        lines += ["", "TEACHER REMARKS (newest first):"]
        for remark in summary.remarks:
            lines.append(
                f"  - [{remark.sentiment.label}] {remark.teacher_name or 'Teacher'} "
                f"on {remark.created_at.date()}: {remark.remark_text}"
            )
    else:
        lines += ["", "TEACHER REMARKS: none recorded yet."]

    if summary.fees:
        lines += ["", "FEES:"]
        for fee in summary.fees:
            outstanding = round(fee.amount_due - fee.amount_paid, 2)
            lines.append(
                f"  - {fee.fee_type}: {fee.status}, due {fee.due_date}, "
                f"{outstanding} outstanding of {fee.amount_due}"
            )
    else:
        lines += ["", "FEES: nothing outstanding on record."]

    lines += ["", "NOTE: there is no exam-grade data in this system, so you cannot answer questions about marks or grades."]
    lines += ["", f"PARENT'S QUESTION: {query}"]
    return "\n".join(lines)


# --- Top Doubts insights ------------------------------------------------------------


class DoubtClusterOut(BaseModel):
    label: str | None
    description: str | None
    question_count: int
    distinct_student_count: int
    sections: list[str]
    """Class names contributing to this cluster. Two names here is the cross-section
    proof - one insight built from two rooms."""
    sample_questions: list[str]


class TopDoubtsResponse(BaseModel):
    items: list[DoubtClusterOut]


class GradeSubjectDoubtsOut(BaseModel):
    grade_level: int
    subject_id: int
    subject_name: str
    clusters: list[DoubtClusterOut]


class MyTopDoubtsResponse(BaseModel):
    items: list[GradeSubjectDoubtsOut]


def _to_cluster_out(clusters) -> list[DoubtClusterOut]:
    return [
        DoubtClusterOut(
            label=c.label, description=c.description, question_count=c.question_count,
            distinct_student_count=c.distinct_student_count, sections=c.sections,
            sample_questions=c.sample_questions,
        )
        for c in clusters
    ]


@router.get("/insights/top-doubts", response_model=TopDoubtsResponse)
def get_top_doubts(
    grade_level: int,
    subject_id: int | None = None,
    days: int = 7,
    limit: int = 5,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    if user.school_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Your account is not attached to a school")

    if user.role == "teacher":
        # A teacher may only see grades/subjects they ACTUALLY teach (evidenced by
        # timetable slots). Without this, any teacher could read any grade's
        # confusions by editing the query string - the same class of hole the Doubt
        # Bot's class_id check closes.
        taught = grade_subject_pairs_for_teacher(db, teacher_id=user.id)
        if subject_id is None:
            if not any(grade == grade_level for grade, _s, _n in taught):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not teach this grade")
        elif not any(grade == grade_level and sid == subject_id for grade, sid, _n in taught):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "You do not teach this subject at this grade")

    clusters = top_doubts(
        db, school_id=user.school_id, grade_level=grade_level,
        subject_id=subject_id, days=days, limit=limit,
    )
    return TopDoubtsResponse(items=_to_cluster_out(clusters))


@router.get("/insights/my-top-doubts", response_model=MyTopDoubtsResponse)
def get_my_top_doubts(
    days: int = 7,
    limit: int = 5,
    user: CurrentUser = Depends(require_role("teacher", "admin", "principal")),
    db: Session = Depends(get_db),
):
    """The teacher-dashboard call. Admin/principal teach nothing, so they get an empty
    list rather than a 403 - the widget simply doesn't render for them."""
    if user.school_id is None or user.role != "teacher":
        return MyTopDoubtsResponse(items=[])

    items = []
    for grade_level, subject_id, subject_name in grade_subject_pairs_for_teacher(db, teacher_id=user.id):
        clusters = top_doubts(
            db, school_id=user.school_id, grade_level=grade_level,
            subject_id=subject_id, days=days, limit=limit,
        )
        if clusters:
            items.append(
                GradeSubjectDoubtsOut(
                    grade_level=grade_level, subject_id=subject_id,
                    subject_name=subject_name, clusters=_to_cluster_out(clusters),
                )
            )
    return MyTopDoubtsResponse(items=items)


class ReindexRequest(BaseModel):
    resource_id: int | None = None
    """Omit to reindex every not-yet-indexed resource in the caller's own school."""


class ReindexResponse(BaseModel):
    resources_indexed: int
    chunks_written: int


@router.post("/reindex", response_model=ReindexResponse)
def reindex(
    body: ReindexRequest,
    user: CurrentUser = Depends(require_role("admin", "principal")),
    db: Session = Depends(get_db),
):
    if body.resource_id is not None:
        resource = db.query(Resource).filter(Resource.id == body.resource_id).one_or_none()
        if resource is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Resource not found")
        # Same cross-tenant rule as everywhere else - an admin reindexing another
        # school's resource would be doing work on data they cannot otherwise see.
        if resource.school_id != user.school_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "That resource belongs to another school")
        chunks = ingest_resource(db, resource.id)
        db.commit()
        return ReindexResponse(resources_indexed=1, chunks_written=chunks)

    resources, chunks = ingest_pending(db, school_id=user.school_id)
    db.commit()
    return ReindexResponse(resources_indexed=resources, chunks_written=chunks)
