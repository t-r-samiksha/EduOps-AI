import time
import uuid

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.database import SessionLocal
from app.models.class_ import SchoolClass
from app.models.school import School
from app.scheduler import (
    JOB_ID_ADMIN_BRIEFING,
    JOB_ID_FEE_INVOICING,
    JOB_ID_RESOURCE_REINDEX,
    JOB_ID_RISK_SCORING,
    JOB_ID_SYLLABUS_ANOMALY_SCAN,
    JOB_ID_WEEKLY_TOP_DOUBTS,
    _active_school_academic_year_pairs,
    JOB_ID_ASSIGNMENT_DEADLINES,
    build_scheduler,
    get_scheduler,
    run_nightly_admin_briefing_job,
    shutdown_scheduler,
    start_scheduler,
)


def test_build_scheduler_registers_all_jobs():
    """Was "all_4_jobs" - the RAG work added two more (nightly resource reindex,
    weekly top doubts) and S-H added the assignment-deadline job, so the count moved
    4 -> 6 -> 7. Asserting the exact id SET rather than a count is what made this a
    one-line update instead of a silent gap."""
    scheduler = build_scheduler()
    job_ids = {j.id for j in scheduler.get_jobs()}
    assert job_ids == {
        JOB_ID_RISK_SCORING,
        JOB_ID_SYLLABUS_ANOMALY_SCAN,
        JOB_ID_ADMIN_BRIEFING,
        JOB_ID_FEE_INVOICING,
        JOB_ID_RESOURCE_REINDEX,
        JOB_ID_WEEKLY_TOP_DOUBTS,
        JOB_ID_ASSIGNMENT_DEADLINES,
    }


def test_start_scheduler_is_idempotent():
    """Calling start_scheduler() twice (e.g. --reload triggering a second
    startup) must not create a second running scheduler or duplicate jobs."""
    try:
        first = start_scheduler()
        second = start_scheduler()
        assert first is second
        # 7: the RAG work added resource-reindex and weekly-top-doubts, and S-H added
        # the nightly assignment-deadline job.
        assert len(first.get_jobs()) == 7
    finally:
        shutdown_scheduler()


def test_shutdown_scheduler_clears_the_singleton():
    start_scheduler()
    assert get_scheduler() is not None
    shutdown_scheduler()
    assert get_scheduler() is None


def test_scheduler_actually_fires_a_job():
    """The literal "confirm the scheduler actually fires" acceptance check -
    a real BackgroundScheduler (not the app's shared one, to avoid interfering
    with other tests) with a very short interval trigger, proving APScheduler
    genuinely executes registered work rather than just holding config."""
    fired = []
    scheduler = BackgroundScheduler()
    scheduler.add_job(lambda: fired.append(True), IntervalTrigger(seconds=1), id="test-fire")
    scheduler.start()
    try:
        deadline = time.time() + 5
        while not fired and time.time() < deadline:
            time.sleep(0.2)
    finally:
        scheduler.shutdown(wait=False)
    assert fired, "job never fired within 5 seconds"


def _fresh_school_with_class(db_session, academic_year: str):
    school = School(name=f"Scheduler Test School {uuid.uuid4()}")
    db_session.add(school)
    db_session.flush()
    school_class = SchoolClass(name="Grade 5 - A", academic_year=academic_year, grade_level=5, section="A", school_id=school.id)
    db_session.add(school_class)
    db_session.commit()
    db_session.refresh(school)
    db_session.refresh(school_class)
    return school, school_class


def test_active_school_academic_year_pairs_includes_real_active_school(db_session):
    school, school_class = _fresh_school_with_class(db_session, "2099-00")
    pairs = _active_school_academic_year_pairs(db_session)
    assert (school.id, "2099-00") in pairs


def test_active_school_academic_year_pairs_excludes_deactivated_school(db_session):
    school, school_class = _fresh_school_with_class(db_session, "2099-01")
    school.is_active = False
    db_session.commit()
    pairs = _active_school_academic_year_pairs(db_session)
    assert (school.id, "2099-01") not in pairs


def test_active_school_academic_year_pairs_excludes_deactivated_class(db_session):
    school, school_class = _fresh_school_with_class(db_session, "2099-02")
    school_class.is_active = False
    db_session.commit()
    pairs = _active_school_academic_year_pairs(db_session)
    assert (school.id, "2099-02") not in pairs


def test_nightly_admin_briefing_job_writes_a_real_file_using_a_real_session():
    """Wiring correctness, not re-testing compile_briefing()'s own content logic
    (that's covered by test_nightly_admin_briefing.py) - confirms the job
    wrapper calls the real function against a real DB session and produces a
    real output file, using SessionLocal exactly like the manual CLI script."""
    result = run_nightly_admin_briefing_job()
    assert result["chars"] > 0
    with open(result["output_path"], encoding="utf-8") as f:
        content = f.read()
    assert "EduOps AI - Admin Briefing" in content


def test_job_wrappers_use_the_same_functions_as_the_manual_cli_scripts():
    """A cheap but real check against duplication: import both the job
    wrapper's module and each manual script, confirm the wrapper actually
    imported the CLI script's real function object (not a re-implementation)."""
    import app.scheduler as scheduler_module
    from scripts.run_monthly_fee_invoicing import run_monthly_invoicing
    from scripts.run_nightly_risk_scoring import run_nightly_scoring
    from scripts.run_nightly_syllabus_anomaly_scan import run_scan

    assert scheduler_module.run_nightly_scoring is run_nightly_scoring
    assert scheduler_module.run_scan is run_scan
    assert scheduler_module.run_monthly_invoicing is run_monthly_invoicing
