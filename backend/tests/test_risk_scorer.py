from app.services.risk_scorer import (
    LOW_RISK_MAX,
    MEDIUM_RISK_MAX,
    AttendanceSignal,
    GradeSignal,
    RemarkSignal,
    score_student,
)

STUDENT_ID = 1


def _attendance(present: int, absent: int, late: int = 0) -> AttendanceSignal:
    total = present + absent + late
    return AttendanceSignal(student_id=STUDENT_ID, present_count=present, absent_count=absent, late_count=late, total_records=total)


def test_good_attendance_only_is_low_risk():
    result = score_student(_attendance(present=19, absent=1))
    assert result.risk_level == "low"
    assert result.score <= LOW_RISK_MAX
    assert result.missing_signals == ["grades", "remarks"]


def test_poor_attendance_alone_crosses_into_risk():
    # 40% attendance - well below the 90% threshold - even with no other signals.
    result = score_student(_attendance(present=8, absent=12))
    assert result.risk_level in ("medium", "high")
    assert any("attendance rate" in r for r in result.reasons)


def test_combined_bad_signals_produce_high_risk():
    attendance = _attendance(present=5, absent=15)
    grades = GradeSignal(student_id=STUDENT_ID, average_score_pct=20.0, trend="declining")
    remarks = RemarkSignal(
        student_id=STUDENT_ID,
        remark_texts=[
            "Seems withdrawn and disengaged, very worrying behavior.",
            "Missed two more assignments, extremely concerning and disappointing.",
            "Struggling badly, failing to keep up, seems miserable and hopeless.",
        ],
    )
    result = score_student(attendance, grades, remarks)

    assert result.risk_level == "high"
    assert result.score > MEDIUM_RISK_MAX
    assert result.missing_signals == []
    assert any("attendance rate" in r for r in result.reasons)
    assert any("average grade" in r for r in result.reasons)
    assert any("remarks skew negative" in r for r in result.reasons)


def test_all_good_signals_produce_low_risk():
    attendance = _attendance(present=19, absent=1)
    grades = GradeSignal(student_id=STUDENT_ID, average_score_pct=88.0, trend="improving")
    remarks = RemarkSignal(student_id=STUDENT_ID, remark_texts=["Excellent progress, very engaged in class!"])
    result = score_student(attendance, grades, remarks)

    assert result.risk_level == "low"
    assert result.missing_signals == []


def test_missing_grades_and_remarks_are_reported_not_faked():
    result = score_student(_attendance(present=19, absent=1), grades=None, remarks=None)
    assert result.missing_signals == ["grades", "remarks"]


def test_missing_remarks_only():
    grades = GradeSignal(student_id=STUDENT_ID, average_score_pct=90.0)
    result = score_student(_attendance(present=19, absent=1), grades=grades, remarks=None)
    assert result.missing_signals == ["remarks"]


def test_declining_grade_trend_increases_risk_over_flat():
    attendance = _attendance(present=19, absent=1)
    flat = score_student(attendance, GradeSignal(student_id=STUDENT_ID, average_score_pct=50.0, trend="stable"))
    declining = score_student(attendance, GradeSignal(student_id=STUDENT_ID, average_score_pct=50.0, trend="declining"))
    assert declining.score > flat.score


def test_improving_grade_trend_decreases_risk_over_flat():
    attendance = _attendance(present=19, absent=1)
    flat = score_student(attendance, GradeSignal(student_id=STUDENT_ID, average_score_pct=50.0, trend="stable"))
    improving = score_student(attendance, GradeSignal(student_id=STUDENT_ID, average_score_pct=50.0, trend="improving"))
    assert improving.score < flat.score


def test_no_attendance_records_does_not_crash():
    result = score_student(AttendanceSignal(student_id=STUDENT_ID, present_count=0, absent_count=0, late_count=0, total_records=0))
    assert result.risk_level == "low"
    assert result.score == 0.0


def test_score_is_clamped_to_zero_one_range():
    attendance = _attendance(present=0, absent=20)
    grades = GradeSignal(student_id=STUDENT_ID, average_score_pct=0.0, trend="declining")
    remarks = RemarkSignal(student_id=STUDENT_ID, remark_texts=["Absolutely terrible, failing everything, very worrying."])
    result = score_student(attendance, grades, remarks)
    assert 0.0 <= result.score <= 1.0


def test_positive_remarks_do_not_produce_negative_risk():
    # A very positive remark shouldn't let sentiment "cancel out" real attendance risk.
    attendance = _attendance(present=8, absent=12)
    remarks = RemarkSignal(student_id=STUDENT_ID, remark_texts=["Absolutely wonderful, best student ever!"])
    with_remarks = score_student(attendance, remarks=remarks)
    without_remarks = score_student(attendance)
    assert with_remarks.score >= without_remarks.score * 0.5  # positive remarks don't drag score sharply down
