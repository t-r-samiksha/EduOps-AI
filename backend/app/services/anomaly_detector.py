"""Anomaly detection across four operational categories, per playbook 11.4.

WHICH CATEGORIES ARE FULLY REAL VS. HONEST-STUB - read before trusting output
--------------------------------------------------------------------------------
- attendance_drop: FULLY REAL. Built from AttendanceRecord, which this codebase owns.
- document_backlog: FULLY REAL. Built from Document (the OCR session's own table).
- teacher_overload: FULLY REAL. Built from TimetableSlot, which this codebase owns.
- submission_rate: HONEST STUB. Checked backend/app/models/ before writing this (same
  check as Early-Warning's grades-signal gap and OCR's admissions-table gap): Person
  B's assignments/submissions tables do not exist in this repo yet - only documented
  as a future contract in docs/api-contract.md's Person B section ("POST /classroom/
  {class_id}/assignments" etc. are stubs, never implemented). SubmissionRateSignal
  below is a pure dataclass INTERFACE with no backing table, exactly like
  risk_scorer.py's GradeSignal. scripts/run_nightly_syllabus_anomaly_scan.py never
  calls detect_low_submission_rates today for exactly this reason (see that script's
  own docstring) - wire a real caller in once Person B's submissions table exists;
  nothing else in this module changes.

scikit-learn CHOICE - IsolationForest for teacher_overload only, with a fallback
--------------------------------------------------------------------------------------
Per the tech stack doc ("Anomaly detection model (scikit-learn)"). Only
teacher_overload genuinely poses a "is this an outlier among peers" question - a
real fit for 1-D unsupervised outlier detection. attendance_drop and
document_backlog are plain threshold rules ("did this one thing cross a line") -
running a model there would be theater, not rigor, so they deliberately aren't ML.

Same honesty pattern as staffing_forecast.py's PoissonRegressor hybrid: an
IsolationForest fit on a handful of points is statistically meaningless, so it only
engages with MIN_TEACHERS_FOR_MODEL+ teachers; below that (this hackathon's actual
scale most of the time), a plain "> OVERLOAD_MEAN_MULTIPLIER x peers' mean load" rule
is used instead and is honestly what small inputs fall back to.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.ensemble import IsolationForest

SEVERITY_LEVELS = ("normal", "urgent")


@dataclass(frozen=True)
class DetectedAnomaly:
    type: str
    """One of: submission_rate, attendance_drop, document_backlog, teacher_overload."""
    entity_type: str
    entity_id: int
    severity: str
    """One of SEVERITY_LEVELS."""
    message: str
    detail: dict


# --- 1. submission_rate: HONEST STUB interface - see module docstring ---


@dataclass(frozen=True)
class SubmissionRateSignal:
    """PLACEHOLDER interface - no backing table exists. Construct this from real data
    once Person B's assignments/submissions tables land."""

    assignment_id: int
    class_id: int
    expected_submissions: int
    actual_submissions: int


LOW_SUBMISSION_RATE_THRESHOLD = 0.5
URGENT_SUBMISSION_RATE_THRESHOLD = 0.25


def detect_low_submission_rates(signals: list[SubmissionRateSignal]) -> list[DetectedAnomaly]:
    anomalies = []
    for s in signals:
        if s.expected_submissions <= 0:
            continue
        rate = s.actual_submissions / s.expected_submissions
        if rate >= LOW_SUBMISSION_RATE_THRESHOLD:
            continue
        anomalies.append(
            DetectedAnomaly(
                type="submission_rate",
                entity_type="classes",
                entity_id=s.class_id,
                severity="urgent" if rate < URGENT_SUBMISSION_RATE_THRESHOLD else "normal",
                message=f"Assignment {s.assignment_id}: only {rate:.0%} of expected submissions received",
                detail={
                    "assignment_id": s.assignment_id,
                    "rate": round(rate, 3),
                    "expected_submissions": s.expected_submissions,
                    "actual_submissions": s.actual_submissions,
                },
            )
        )
    return anomalies


# --- 2. attendance_drop: FULLY REAL ---


@dataclass(frozen=True)
class ClassAttendanceWindow:
    class_id: int
    recent_present_count: int
    recent_total_count: int
    baseline_rate: float
    """The class's typical attendance rate to compare against (e.g. a longer-window
    average). Caller-supplied since "typical" is a lookback-window judgment call this
    pure function shouldn't make on its own."""
    class_name: str | None = None
    """Display name for the generated message. Optional and caller-supplied because
    this module stays ORM-free (see the module docstring) - it can't look a name up
    itself. Defaults to None so existing positional constructions and unit tests keep
    working; the message falls back to "Class {id}" exactly as before when unset."""


ATTENDANCE_DROP_THRESHOLD = 0.15
"""Flag when the recent attendance rate is this many percentage points below baseline."""
URGENT_ATTENDANCE_DROP_THRESHOLD = 0.30


def detect_attendance_drops(windows: list[ClassAttendanceWindow]) -> list[DetectedAnomaly]:
    anomalies = []
    for w in windows:
        if w.recent_total_count <= 0:
            continue
        recent_rate = w.recent_present_count / w.recent_total_count
        drop = w.baseline_rate - recent_rate
        if drop < ATTENDANCE_DROP_THRESHOLD:
            continue
        anomalies.append(
            DetectedAnomaly(
                type="attendance_drop",
                entity_type="classes",
                entity_id=w.class_id,
                severity="urgent" if drop >= URGENT_ATTENDANCE_DROP_THRESHOLD else "normal",
                message=(
                    f"{w.class_name or f'Class {w.class_id}'} attendance dropped to "
                    f"{recent_rate:.0%} (baseline {w.baseline_rate:.0%})"
                ),
                detail={"recent_rate": round(recent_rate, 3), "baseline_rate": round(w.baseline_rate, 3), "drop": round(drop, 3)},
            )
        )
    return anomalies


# --- 3. document_backlog: FULLY REAL ---


@dataclass(frozen=True)
class DocumentBacklogItem:
    document_id: int
    status: str
    hours_since_upload: float


DOCUMENT_BACKLOG_HOURS_THRESHOLD = 24.0
"""OCR processing in this codebase is SYNCHRONOUS (see routers/documents.py) - a
document transitions queued -> processing -> done/failed within a single request.
A document genuinely stuck in queued/processing for any real length of time
therefore indicates the server crashed or was killed mid-request, not a normal
processing delay - this detector exists specifically to catch that failure mode."""
URGENT_DOCUMENT_BACKLOG_HOURS_THRESHOLD = 72.0


def detect_document_backlogs(items: list[DocumentBacklogItem]) -> list[DetectedAnomaly]:
    anomalies = []
    for item in items:
        if item.status not in ("queued", "processing"):
            continue
        if item.hours_since_upload < DOCUMENT_BACKLOG_HOURS_THRESHOLD:
            continue
        anomalies.append(
            DetectedAnomaly(
                type="document_backlog",
                entity_type="documents",
                entity_id=item.document_id,
                severity="urgent" if item.hours_since_upload >= URGENT_DOCUMENT_BACKLOG_HOURS_THRESHOLD else "normal",
                message=f"Document {item.document_id} has been stuck in {item.status!r} for {item.hours_since_upload:.0f}h",
                detail={"status": item.status, "hours_stuck": round(item.hours_since_upload, 1)},
            )
        )
    return anomalies


# --- 4. teacher_overload: FULLY REAL, IsolationForest with a documented fallback ---


@dataclass(frozen=True)
class TeacherLoadObservation:
    teacher_id: int
    periods_per_week: int
    teacher_name: str | None = None
    """Display name for the generated message - same caller-supplied pattern and
    fallback behaviour as ClassAttendanceWindow.class_name above."""


MIN_TEACHERS_FOR_MODEL = 6
"""Below this many teachers, IsolationForest has too few points to mean anything -
falls back to the mean-multiplier rule instead."""
OVERLOAD_MEAN_MULTIPLIER = 1.5
"""Fallback rule: flag a teacher whose load is at least this multiple of the mean of
everyone else's load."""


def _build_overload_anomaly(observation: TeacherLoadObservation, baseline: float) -> DetectedAnomaly:
    return DetectedAnomaly(
        type="teacher_overload",
        entity_type="users",
        entity_id=observation.teacher_id,
        severity="urgent" if baseline > 0 and observation.periods_per_week >= baseline * 2 else "normal",
        message=(
            f"{observation.teacher_name or f'Teacher {observation.teacher_id}'} is teaching "
            f"{observation.periods_per_week} periods/week vs a peer average of ~{baseline:.1f}"
        ),
        detail={"periods_per_week": observation.periods_per_week, "peer_baseline": round(baseline, 1)},
    )


def _detect_via_mean_multiplier(observations: list[TeacherLoadObservation]) -> list[DetectedAnomaly]:
    anomalies = []
    for obs in observations:
        others = [o.periods_per_week for o in observations if o.teacher_id != obs.teacher_id]
        if not others:
            continue
        mean_others = sum(others) / len(others)
        if mean_others <= 0:
            continue
        if obs.periods_per_week >= mean_others * OVERLOAD_MEAN_MULTIPLIER:
            anomalies.append(_build_overload_anomaly(obs, mean_others))
    return anomalies


def _detect_via_isolation_forest(observations: list[TeacherLoadObservation]) -> list[DetectedAnomaly]:
    X = np.array([[o.periods_per_week] for o in observations], dtype=float)
    try:
        labels = IsolationForest(contamination="auto", random_state=42).fit_predict(X)
    except ValueError:
        return _detect_via_mean_multiplier(observations)

    mean_load = sum(o.periods_per_week for o in observations) / len(observations)
    anomalies = []
    for obs, label in zip(observations, labels):
        # Only flag HIGH outliers as overload - a suspiciously *light* load is a
        # different (and not currently modeled) concern, not overload.
        if label == -1 and obs.periods_per_week > mean_load:
            anomalies.append(_build_overload_anomaly(obs, mean_load))
    return anomalies


def detect_teacher_overload(observations: list[TeacherLoadObservation]) -> list[DetectedAnomaly]:
    if len(observations) < 2:
        return []
    if len(observations) >= MIN_TEACHERS_FOR_MODEL:
        return _detect_via_isolation_forest(observations)
    return _detect_via_mean_multiplier(observations)
