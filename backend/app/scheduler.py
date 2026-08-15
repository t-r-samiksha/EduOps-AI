"""Real scheduled execution for the 4 previously-manual-only jobs (nightly risk
scoring, nightly syllabus/anomaly scan, nightly admin briefing, monthly fee
invoicing).

A reliability audit confirmed all 4 had ZERO automation anywhere - no Celery,
Dramatiq, Huey, or APScheduler wiring existed, so a risk flag/anomaly flag/fee
invoice never appeared unless a human ran the corresponding
`scripts/run_*.py` by hand from a terminal. This module closes that gap by
wiring APScheduler into the FastAPI app's lifespan (see `app/main.py`), so the
jobs run automatically for real whenever the backend process is up.

WIRING, NOT A REWRITE
------------------------
Every job wrapper below imports and calls the exact same pure function the
manual CLI script already uses (`run_nightly_scoring`, `run_scan`,
`compile_briefing`, `run_monthly_invoicing`) - no business logic is duplicated
here, only the "for every active school/year, call the real function, log
what happened" plumbing the CLI scripts always deferred to a future real
scheduler (see each script's own "SCHEDULING" docstring section). The manual
CLI invocations (`python -m scripts.run_nightly_risk_scoring --school-id ...
--academic-year ...`) still work exactly as before - nothing here removes
that capability, it's purely additive.

WHY "FOR EVERY ACTIVE SCHOOL/ACADEMIC_YEAR", NOT ONE HARDCODED PAIR
------------------------------------------------------------------------
The manual scripts take `--school-id`/`--academic-year` as required CLI args
because a human tester picks one school to check. A real automated job has no
human to ask - it must cover every real school, so each job wrapper queries
every (school_id, academic_year) pair with at least one active class (via
`_active_school_academic_year_pairs`) and runs the underlying function once
per pair. `compile_briefing` is the one exception - it's school-agnostic (the
unified alerts feed it reads has no school scoping of its own), so it runs
once per invocation, not once per school.
"""

from __future__ import annotations

import logging
import os
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.class_ import SchoolClass
from app.models.school import School
from scripts.run_monthly_fee_invoicing import run_monthly_invoicing
from scripts.run_nightly_admin_briefing import BRIEFING_OUTPUT_DIR, compile_briefing
from scripts.run_nightly_risk_scoring import run_nightly_scoring
from scripts.run_nightly_syllabus_anomaly_scan import run_scan

logger = logging.getLogger("eduops.scheduler")
logger.setLevel(logging.INFO)
if not logger.handlers:
    # Deliberately not touching the root logger / logging.basicConfig() - this
    # must not fight with uvicorn's own logging setup. A dedicated handler on
    # this named logger only is enough to make every run visible (the explicit
    # "log clearly so there's a visible record automation actually happened"
    # requirement) without side effects on the rest of the app's logging.
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
    logger.addHandler(_handler)

JOB_ID_RISK_SCORING = "nightly_risk_scoring"
JOB_ID_SYLLABUS_ANOMALY_SCAN = "nightly_syllabus_anomaly_scan"
JOB_ID_ADMIN_BRIEFING = "nightly_admin_briefing"
JOB_ID_FEE_INVOICING = "monthly_fee_invoicing"


def _active_school_academic_year_pairs(session: Session) -> list[tuple[int, str]]:
    rows = (
        session.query(SchoolClass.school_id, SchoolClass.academic_year)
        .join(School, SchoolClass.school_id == School.id)
        .filter(School.is_active.is_(True), SchoolClass.is_active.is_(True))
        .distinct()
        .all()
    )
    return [(r.school_id, r.academic_year) for r in rows]


def run_nightly_risk_scoring_job() -> dict:
    logger.info("nightly risk scoring: starting")
    session = SessionLocal()
    totals = {"school_year_pairs": 0, "students_scored": 0, "flags_created": 0, "flags_updated": 0}
    try:
        pairs = _active_school_academic_year_pairs(session)
        for school_id, academic_year in pairs:
            summary = run_nightly_scoring(session, school_id, academic_year)
            logger.info("nightly risk scoring: school_id=%s academic_year=%s -> %s", school_id, academic_year, summary)
            totals["school_year_pairs"] += 1
            totals["students_scored"] += summary["students_scored"]
            totals["flags_created"] += summary["flags_created"]
            totals["flags_updated"] += summary["flags_updated"]
    except Exception:
        logger.exception("nightly risk scoring: FAILED")
        raise
    finally:
        session.close()
    logger.info("nightly risk scoring: done - %s", totals)
    return totals


def run_nightly_syllabus_anomaly_scan_job() -> dict:
    logger.info("nightly syllabus/anomaly scan: starting")
    session = SessionLocal()
    totals = {"school_year_pairs": 0, "anomalies_found": 0, "flags_created": 0, "flags_updated": 0}
    try:
        pairs = _active_school_academic_year_pairs(session)
        for school_id, academic_year in pairs:
            summary = run_scan(session, school_id, academic_year)
            logger.info("nightly syllabus/anomaly scan: school_id=%s academic_year=%s -> %s", school_id, academic_year, summary)
            totals["school_year_pairs"] += 1
            totals["anomalies_found"] += summary["anomalies_found"]
            totals["flags_created"] += summary["flags_created"]
            totals["flags_updated"] += summary["flags_updated"]
    except Exception:
        logger.exception("nightly syllabus/anomaly scan: FAILED")
        raise
    finally:
        session.close()
    logger.info("nightly syllabus/anomaly scan: done - %s", totals)
    return totals


def run_nightly_admin_briefing_job() -> dict:
    logger.info("nightly admin briefing: starting")
    session = SessionLocal()
    try:
        briefing = compile_briefing(session)
    except Exception:
        logger.exception("nightly admin briefing: FAILED")
        raise
    finally:
        session.close()

    os.makedirs(BRIEFING_OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(BRIEFING_OUTPUT_DIR, f"{date.today().isoformat()}.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(briefing)
    logger.info("nightly admin briefing: done - written to %s (%d chars)", output_path, len(briefing))
    return {"output_path": output_path, "chars": len(briefing)}


def run_monthly_fee_invoicing_job() -> dict:
    logger.info("monthly fee invoicing: starting")
    session = SessionLocal()
    totals = {"school_year_pairs": 0, "records_created": 0, "overdue_marked": 0, "reminders_sent": 0}
    try:
        pairs = _active_school_academic_year_pairs(session)
        for school_id, academic_year in pairs:
            summary = run_monthly_invoicing(session, school_id, academic_year)
            logger.info("monthly fee invoicing: school_id=%s academic_year=%s -> %s", school_id, academic_year, summary)
            totals["school_year_pairs"] += 1
            totals["records_created"] += summary["records_created"]
            totals["overdue_marked"] += summary["overdue_marked"]
            totals["reminders_sent"] += summary["reminders_sent"]
    except Exception:
        logger.exception("monthly fee invoicing: FAILED")
        raise
    finally:
        session.close()
    logger.info("monthly fee invoicing: done - %s", totals)
    return totals


_scheduler: BackgroundScheduler | None = None


def build_scheduler() -> BackgroundScheduler:
    """Builds (without starting) a scheduler with all 4 jobs registered. Kept
    separate from `start_scheduler()` so tests can build one without touching
    the module-level singleton or actually starting a background thread."""
    scheduler = BackgroundScheduler(timezone="UTC")
    # Staggered nightly times so the 3 nightly jobs don't contend for the same
    # DB connections/CPU at the exact same instant.
    scheduler.add_job(run_nightly_risk_scoring_job, CronTrigger(hour=2, minute=0), id=JOB_ID_RISK_SCORING, replace_existing=True)
    scheduler.add_job(
        run_nightly_syllabus_anomaly_scan_job, CronTrigger(hour=2, minute=15), id=JOB_ID_SYLLABUS_ANOMALY_SCAN, replace_existing=True
    )
    scheduler.add_job(run_nightly_admin_briefing_job, CronTrigger(hour=2, minute=30), id=JOB_ID_ADMIN_BRIEFING, replace_existing=True)
    # Monthly, 1st of the month, off-peak.
    scheduler.add_job(run_monthly_fee_invoicing_job, CronTrigger(day=1, hour=3, minute=0), id=JOB_ID_FEE_INVOICING, replace_existing=True)
    return scheduler


def start_scheduler() -> BackgroundScheduler:
    """Idempotent - calling this more than once (e.g. --reload triggering a
    second app startup) returns the already-running scheduler rather than
    starting a second one."""
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        return _scheduler
    _scheduler = build_scheduler()
    _scheduler.start()
    logger.info(
        "scheduler started with %d jobs: %s", len(_scheduler.get_jobs()), [j.id for j in _scheduler.get_jobs()]
    )
    return _scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        logger.info("scheduler shut down")
        _scheduler = None


def get_scheduler() -> BackgroundScheduler | None:
    return _scheduler
