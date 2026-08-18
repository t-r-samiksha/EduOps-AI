"""Top Doubts: cluster recent student questions so a subject teacher sees one
cross-section insight instead of two rooms' worth of disconnected logs.

AGGREGATION UNIT: (school_id, grade_level, subject_id) - NOT class_id
------------------------------------------------------------------------
If Grade 3 - A and Grade 3 - B are both stuck on regrouping, that is ONE thing for
Meera (who teaches Math to both) to re-teach, not two. Aggregating by class_id would
split it in half and bury the signal - each section's five questions would look like
noise where ten together look like a pattern. `sections` on each cluster is what makes
that visible in the UI.

WHY NO scikit-learn
----------------------
The obvious reach is KMeans or DBSCAN. Both are wrong here:
  - KMeans needs k up front. We do not know how many distinct confusions a week holds.
  - DBSCAN is density-based and needs tuning of two parameters against a dataset that
    is, in a real week, a few dozen rows.
Greedy agglomeration against a single cosine threshold is deterministic, inspectable,
explains itself in one sentence to a teacher, and runs in milliseconds on this volume.
scikit-learn IS already a dependency (risk scoring uses it), so this is a deliberate
choice rather than dependency avoidance.

DETERMINISM: logs are pulled in a fixed order (created_at, then id) and assigned to the
FIRST cluster within threshold, so the same input always produces the same clusters.
A non-deterministic clustering would make the widget flicker between refreshes.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models.class_ import SchoolClass
from app.models.knowledge import ChatbotLog
from app.models.subject import Subject
from app.models.timetable import TimetableSlot

DEFAULT_THRESHOLD = 0.40
"""Maximum cosine distance from a cluster's centroid for a question to join it.

TUNED by sweep against the 18 seeded Riverside doubt logs (see SEEDED_DOUBTS in
scripts/seed_riverside_fixtures.py), embedded through the real path. The spec's
starting suggestion of 0.25 proved far too tight for real student phrasing. Measured,
not guessed - all-subjects sweep, 18 logs:

  0.25 -> 15 clusters, only 1 cross-section. Over-split: "why do we carry the one" and
          "i dont get the small number you write on top" are the SAME confusion with
          almost no shared vocabulary, and a tight threshold splits exactly the pair
          this feature exists to join.
  0.30 -> 13 clusters, 3 cross-section. Still fragmented.
  0.35 -> 9 clusters [5,4,3,2,1...]. Concept groups appear.
  0.40 -> CHOSEN. See below.
  0.42 -> Math collapses to [4,3] but ABSORBS "how many marks is the term 1 test" - an
          administrative question, not a confusion - into a concept cluster. That is a
          false positive a teacher would immediately spot, and the reason 0.42 was
          rejected despite producing tidier-looking numbers.
  0.48+ -> everything merges into one blob of 18. Useless.

At 0.40, per subject (the shape the endpoints actually query):
  Math    [3q cross-section] [2q cross-section] + 2 correctly-isolated singletons
  Science [6q cross-section]
  English [4q cross-section] + 2 correctly-isolated singletons

0.40 is a BOUNDARY, not a midpoint: 0.42 already mis-merges. If the corpus grows,
re-run the sweep rather than nudging this. A different embedding model's distance
scale is NOT comparable and would invalidate every number above.
"""

MIN_LOGS_FOR_CLUSTERING = 3
"""Below this, clustering is meaningless - return recent distinct questions unlabelled
instead. An honest degraded state, never a crash or a blank panel."""


@dataclass
class DoubtCluster:
    label: str | None
    description: str | None
    question_count: int
    distinct_student_count: int
    sections: list[str]
    sample_questions: list[str]
    member_ids: list[int] = field(default_factory=list, repr=False)


def _cosine_distance(a: list[float], b: list[float]) -> float:
    """Vectors from services/llm.py are already L2-normalized, so the dot product IS
    cosine similarity. The magnitudes are recomputed anyway rather than assumed:
    centroids are means of unit vectors and are NOT themselves unit length."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 1.0
    return 1.0 - (dot / (norm_a * norm_b))


def _running_mean(centroid: list[float], vector: list[float], count: int) -> list[float]:
    """Incremental centroid update - avoids re-summing every member on each add."""
    return [(c * count + v) / (count + 1) for c, v in zip(centroid, vector)]


# Queries that are not academic doubts. Kept as a token set rather than an LLM call
# because this runs over every log on every widget load, and a greeting filter that
# needs a model round-trip is worse than no filter.
_NON_DOUBT_TOKENS = {
    "hi", "hii", "hiii", "hey", "hello", "helo", "hlo", "yo", "sup", "hola",
    "good", "morning", "afternoon", "evening", "night", "gm", "gn",
    "thanks", "thank", "thanku", "thx", "ty", "ok", "okay", "k", "kk",
    "bye", "goodbye", "cool", "nice", "great", "lol", "haha", "hmm", "oh",
    "test", "testing", "hi!", "sir", "maam", "ma'am", "miss", "teacher",
    "please", "pls", "u", "r",
}


def _is_academic_doubt(query: str) -> bool:
    """False for greetings, thanks and other small talk.

    The teacher-facing widget was leading with a cluster labelled "Casual Greetings -
    students are opening the chat with casual greetings without asking academic
    questions". That is technically a true summary of the data and useless as an
    insight: the feature exists to show what students are STUCK on.

    A query is kept if anything survives after removing pure small-talk tokens, so
    "hi miss why do we carry the one" is kept (it contains a real question) while
    "hi", "thanks sir" and "ok" are dropped.
    """
    if not query or not query.strip():
        return False
    words = [w.strip(".,!?;:'\"()") .lower() for w in query.split()]
    meaningful = [w for w in words if w and w not in _NON_DOUBT_TOKENS]
    return len(meaningful) > 0


def _fetch_logs(
    db: Session, *, school_id: int, grade_level: int, subject_id: int | None, days: int
) -> list[tuple[ChatbotLog, str]]:
    """Recent logs for this (school, grade[, subject]), each with its section name.

    Joined to classes because chatbot_logs carries class_id but not grade_level - the
    grade is a property of the class, resolved at query time so a log stays correct if
    a class is later re-graded.
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    query = (
        db.query(ChatbotLog, SchoolClass.name)
        .join(SchoolClass, ChatbotLog.class_id == SchoolClass.id)
        .filter(
            SchoolClass.school_id == school_id,
            SchoolClass.grade_level == grade_level,
            ChatbotLog.created_at >= since,
        )
    )
    if subject_id is not None:
        query = query.filter(ChatbotLog.subject_id == subject_id)

    rows = query.order_by(ChatbotLog.created_at, ChatbotLog.id).all()

    # STUDENT DOUBTS ONLY. chatbot_logs is shared by all three bots, and this never
    # filtered - so a teacher's "Top Doubts" was clustering PARENT questions
    # ("how is my child doing?", "does Diya have ADHD or a learning disability?")
    # alongside student doubts. Eight of Riverside's 32 logs were parent queries. Those
    # are a different audience asking a different kind of question, and one of them is
    # exactly the sort of thing that must not surface on a staff dashboard as a
    # "common student doubt".
    #
    # Small talk is dropped for the same reason: the widget led with a cluster labelled
    # "Casual Greetings", which is a true statement about the data and no use to anyone.
    return [
        (log, section)
        for log, section in rows
        if log.bot_type == "student" and _is_academic_doubt(log.query)
    ]


def _label_clusters(clusters: list[DoubtCluster]) -> None:
    """Label every cluster in ONE Gemini call, not one call per cluster.

    Mutates in place. Any failure - API error, malformed JSON, wrong length - leaves
    labels as None, which the degraded UI path already renders. A labelling failure
    must never take down an endpoint whose real value (the grouping and the counts) is
    already computed.
    """
    if not clusters:
        return
    try:
        from app.services.llm import generate

        payload = [
            {"cluster": i, "questions": c.sample_questions[:5]}
            for i, c in enumerate(clusters)
        ]
        raw = generate(
            "You label clusters of student questions for a teacher's dashboard. "
            "Reply with ONLY a JSON array, no markdown fence, one object per cluster in the same order, "
            'each {"cluster": <int>, "label": "<3-6 word concept name>", '
            '"description": "<one sentence on what students are getting stuck on>"}.',
            json.dumps(payload, ensure_ascii=False),
        )
        cleaned = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        for entry in json.loads(cleaned):
            index = int(entry.get("cluster", -1))
            if 0 <= index < len(clusters):
                clusters[index].label = (entry.get("label") or "").strip() or None
                clusters[index].description = (entry.get("description") or "").strip() or None
    except Exception:  # noqa: BLE001 - labels are a nicety; counts and grouping are the feature
        return


def top_doubts(
    db: Session,
    *,
    school_id: int,
    grade_level: int,
    subject_id: int | None = None,
    days: int = 7,
    limit: int = 5,
    threshold: float = DEFAULT_THRESHOLD,
    label: bool = True,
) -> list[DoubtCluster]:
    """Rank the concepts students in this grade are most stuck on.

    `label=False` skips the Gemini call - used by tests and by the weekly job when only
    counts are needed.
    """
    rows = _fetch_logs(db, school_id=school_id, grade_level=grade_level, subject_id=subject_id, days=days)
    usable = [(log, section) for log, section in rows if log.query_embedding is not None]

    if len(usable) < MIN_LOGS_FOR_CLUSTERING:
        # Degraded but honest: recent distinct questions, unlabelled. Deliberately
        # reads from `rows`, not `usable` - a question with no embedding is still a
        # real question worth showing, it just cannot be clustered.
        seen: set[str] = set()
        fallback: list[DoubtCluster] = []
        for log, section in reversed(rows):
            key = log.query.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            fallback.append(
                DoubtCluster(
                    label=None, description=None, question_count=1, distinct_student_count=1,
                    sections=[section], sample_questions=[log.query], member_ids=[log.id],
                )
            )
            if len(fallback) >= limit:
                break
        return fallback

    centroids: list[list[float]] = []
    members: list[list[tuple[ChatbotLog, str]]] = []

    for log, section in usable:
        vector = [float(x) for x in log.query_embedding]
        best_index, best_distance = None, threshold
        for index, centroid in enumerate(centroids):
            distance = _cosine_distance(centroid, vector)
            if distance < best_distance:
                best_index, best_distance = index, distance
        if best_index is None:
            centroids.append(list(vector))
            members.append([(log, section)])
        else:
            centroids[best_index] = _running_mean(centroids[best_index], vector, len(members[best_index]))
            members[best_index].append((log, section))

    clusters = [
        DoubtCluster(
            label=None,
            description=None,
            question_count=len(group),
            distinct_student_count=len({log.user_id for log, _ in group}),
            # Sorted so "Grade 3 - A, Grade 3 - B" renders in a stable order rather
            # than whichever section happened to ask first.
            sections=sorted({section for _, section in group}),
            sample_questions=[log.query for log, _ in group[:3]],
            member_ids=[log.id for log, _ in group],
        )
        for group in members
    ]
    # Size first; ties broken by distinct students so a cluster from five different
    # children outranks one child asking the same thing five times.
    clusters.sort(key=lambda c: (c.question_count, c.distinct_student_count), reverse=True)
    clusters = clusters[:limit]

    if label:
        _label_clusters(clusters)
    return clusters


def teachers_for_grade_subject(db: Session, *, school_id: int, grade_level: int, subject_id: int) -> list[int]:
    """Who actually teaches this subject at this grade.

    PRIMARY: distinct teacher_ids on timetable_slots for classes at this grade - real
    teaching assignment, not mere qualification. FALLBACK: teacher_subjects, for a
    grade with no generated timetable yet (otherwise a school that hasn't run the
    solver would silently have no one to notify).
    """
    slot_teachers = [
        row.teacher_id
        for row in db.query(TimetableSlot.teacher_id)
        .join(SchoolClass, TimetableSlot.class_id == SchoolClass.id)
        .filter(
            SchoolClass.school_id == school_id,
            SchoolClass.grade_level == grade_level,
            TimetableSlot.subject_id == subject_id,
            TimetableSlot.is_active.is_(True),
        )
        .distinct()
    ]
    if slot_teachers:
        return sorted(slot_teachers)

    from app.models.timetable import TeacherSubject
    from app.models.user import User

    return sorted(
        row.teacher_id
        for row in db.query(TeacherSubject.teacher_id)
        .join(User, TeacherSubject.teacher_id == User.id)
        .filter(TeacherSubject.subject_id == subject_id, User.school_id == school_id)
        .distinct()
    )


def grade_subject_pairs_for_teacher(db: Session, *, teacher_id: int) -> list[tuple[int, int, str]]:
    """(grade_level, subject_id, subject_name) this teacher actually teaches.

    Drives GET /bots/insights/my-top-doubts and the teacher's own authorization on
    GET /bots/insights/top-doubts - a teacher may only see grades/subjects in this list.
    """
    rows = (
        db.query(SchoolClass.grade_level, Subject.id, Subject.name)
        .join(TimetableSlot, TimetableSlot.class_id == SchoolClass.id)
        .join(Subject, TimetableSlot.subject_id == Subject.id)
        .filter(TimetableSlot.teacher_id == teacher_id, TimetableSlot.is_active.is_(True))
        .distinct()
        .all()
    )
    return sorted((grade, subject_id, name) for grade, subject_id, name in rows if grade is not None)
