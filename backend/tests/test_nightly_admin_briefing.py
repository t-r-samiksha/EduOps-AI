import uuid
from datetime import datetime, timezone

import pytest

from app.models.risk import RiskFlag
from app.models.role import Role
from app.models.school import School
from app.models.user import User
from scripts.run_nightly_admin_briefing import compile_briefing, send_briefing_email


def _make_user(db_session, role_row, prefix, school):
    email = f"{prefix}-{uuid.uuid4()}@example.com"
    user = User(supabase_id=uuid.uuid4(), email=email, full_name=prefix, role_id=role_row.id, school_id=school.id)
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture()
def seed(db_session):
    school = School(name="Test School")
    db_session.add(school)
    db_session.flush()
    student_role = db_session.query(Role).filter(Role.name == "student").one()
    student = _make_user(db_session, student_role, "student", school)
    db_session.commit()
    return {"school": school, "student": student}


def test_briefing_includes_urgent_alert_with_id_and_message(db_session, seed):
    flag = RiskFlag(student_id=seed["student"].id, risk_level="high", score=0.8, reasons=["attendance below threshold"], status="open")
    db_session.add(flag)
    db_session.commit()

    briefing = compile_briefing(db_session, generated_at=datetime.now(timezone.utc))

    assert "EduOps AI - Admin Briefing" in briefing
    assert "URGENT" in briefing
    assert f"[risk_flag:{flag.id}]" in briefing
    assert "attendance below threshold" in briefing


def test_briefing_header_counts_match_body(db_session, seed):
    flag = RiskFlag(student_id=seed["student"].id, risk_level="high", score=0.8, reasons=["x"], status="open")
    db_session.add(flag)
    db_session.commit()

    briefing = compile_briefing(db_session)
    header_line = next(line for line in briefing.splitlines() if line.startswith("Total open alerts:"))
    total = int(header_line.split(":")[1].strip())

    body_alert_lines = [line for line in briefing.splitlines() if line.startswith("[")]
    assert total == len(body_alert_lines)
    assert total >= 1


def test_briefing_on_a_source_with_no_rows_omits_that_section_gracefully(db_session, seed):
    # A source (e.g. attendance_reconciliation) contributing zero alerts must not
    # produce a dangling "--- URGENT (0) ---" or similar empty section header.
    briefing = compile_briefing(db_session)
    assert "(0)" not in briefing


def test_send_briefing_email_is_a_stub_and_does_not_raise(capsys):
    send_briefing_email(["admin@example.com"], "Test Subject", "body text")
    captured = capsys.readouterr()
    assert "STUB" in captured.out
    assert "admin@example.com" in captured.out
