from app.services.anomaly_detector import (
    DOCUMENT_BACKLOG_HOURS_THRESHOLD,
    LOW_SUBMISSION_RATE_THRESHOLD,
    URGENT_DOCUMENT_BACKLOG_HOURS_THRESHOLD,
    ClassAttendanceWindow,
    DocumentBacklogItem,
    SubmissionRateSignal,
    TeacherLoadObservation,
    detect_attendance_drops,
    detect_document_backlogs,
    detect_low_submission_rates,
    detect_teacher_overload,
)

# --- submission_rate (honest-stub interface) ---


def test_low_submission_rate_is_flagged_normal():
    signal = SubmissionRateSignal(assignment_id=1, class_id=10, expected_submissions=20, actual_submissions=8)  # rate=0.4
    anomalies = detect_low_submission_rates([signal])
    assert len(anomalies) == 1
    assert anomalies[0].type == "submission_rate"
    assert anomalies[0].entity_id == 10
    assert anomalies[0].severity == "normal"


def test_very_low_submission_rate_is_urgent():
    signal = SubmissionRateSignal(assignment_id=1, class_id=10, expected_submissions=20, actual_submissions=2)  # rate=0.1
    anomalies = detect_low_submission_rates([signal])
    assert anomalies[0].severity == "urgent"


def test_healthy_submission_rate_is_not_flagged():
    signal = SubmissionRateSignal(assignment_id=1, class_id=10, expected_submissions=20, actual_submissions=18)  # rate=0.9
    assert detect_low_submission_rates([signal]) == []


def test_submission_rate_boundary_is_exclusive():
    expected = 20
    actual = int(LOW_SUBMISSION_RATE_THRESHOLD * expected)  # exactly at threshold
    signal = SubmissionRateSignal(assignment_id=1, class_id=10, expected_submissions=expected, actual_submissions=actual)
    assert detect_low_submission_rates([signal]) == []  # at threshold, not below it


def test_zero_expected_submissions_does_not_crash():
    signal = SubmissionRateSignal(assignment_id=1, class_id=10, expected_submissions=0, actual_submissions=0)
    assert detect_low_submission_rates([signal]) == []


# --- attendance_drop (fully real) ---


def test_attendance_drop_flagged_normal():
    window = ClassAttendanceWindow(class_id=5, recent_present_count=70, recent_total_count=100, baseline_rate=0.9)  # recent=0.7, drop=0.2
    anomalies = detect_attendance_drops([window])
    assert len(anomalies) == 1
    assert anomalies[0].type == "attendance_drop"
    assert anomalies[0].entity_id == 5
    assert anomalies[0].severity == "normal"


def test_severe_attendance_drop_is_urgent():
    window = ClassAttendanceWindow(class_id=5, recent_present_count=30, recent_total_count=100, baseline_rate=0.9)  # drop=0.6
    anomalies = detect_attendance_drops([window])
    assert anomalies[0].severity == "urgent"


def test_stable_attendance_is_not_flagged():
    window = ClassAttendanceWindow(class_id=5, recent_present_count=88, recent_total_count=100, baseline_rate=0.9)  # drop=0.02
    assert detect_attendance_drops([window]) == []


def test_attendance_improvement_is_not_flagged():
    window = ClassAttendanceWindow(class_id=5, recent_present_count=95, recent_total_count=100, baseline_rate=0.8)  # negative drop
    assert detect_attendance_drops([window]) == []


def test_zero_recent_records_does_not_crash():
    window = ClassAttendanceWindow(class_id=5, recent_present_count=0, recent_total_count=0, baseline_rate=0.9)
    assert detect_attendance_drops([window]) == []


# --- document_backlog (fully real) ---


def test_stuck_queued_document_is_flagged():
    item = DocumentBacklogItem(document_id=7, status="queued", hours_since_upload=DOCUMENT_BACKLOG_HOURS_THRESHOLD + 1)
    anomalies = detect_document_backlogs([item])
    assert len(anomalies) == 1
    assert anomalies[0].type == "document_backlog"
    assert anomalies[0].entity_id == 7
    assert anomalies[0].severity == "normal"


def test_very_stuck_document_is_urgent():
    item = DocumentBacklogItem(document_id=7, status="processing", hours_since_upload=URGENT_DOCUMENT_BACKLOG_HOURS_THRESHOLD + 1)
    anomalies = detect_document_backlogs([item])
    assert anomalies[0].severity == "urgent"


def test_recently_uploaded_document_is_not_flagged():
    item = DocumentBacklogItem(document_id=7, status="queued", hours_since_upload=1.0)
    assert detect_document_backlogs([item]) == []


def test_done_document_is_never_flagged_regardless_of_age():
    item = DocumentBacklogItem(document_id=7, status="done", hours_since_upload=1000.0)
    assert detect_document_backlogs([item]) == []


def test_failed_document_is_never_flagged_as_backlog():
    # failed documents are their own alert source (document_failed in
    # alert_aggregator.py) - this detector is specifically for stuck-in-progress ones.
    item = DocumentBacklogItem(document_id=7, status="failed", hours_since_upload=1000.0)
    assert detect_document_backlogs([item]) == []


# --- teacher_overload (fully real, hybrid IsolationForest/fallback) ---


def test_single_teacher_is_never_flagged():
    assert detect_teacher_overload([TeacherLoadObservation(teacher_id=1, periods_per_week=40)]) == []


def test_fallback_rule_flags_teacher_far_above_peer_mean():
    # 4 teachers - below MIN_TEACHERS_FOR_MODEL, uses the mean-multiplier fallback.
    observations = [
        TeacherLoadObservation(teacher_id=1, periods_per_week=20),
        TeacherLoadObservation(teacher_id=2, periods_per_week=20),
        TeacherLoadObservation(teacher_id=3, periods_per_week=22),
        TeacherLoadObservation(teacher_id=4, periods_per_week=40),  # ~2x everyone else
    ]
    anomalies = detect_teacher_overload(observations)
    assert len(anomalies) == 1
    assert anomalies[0].entity_id == 4
    assert anomalies[0].type == "teacher_overload"


def test_fallback_rule_does_not_flag_evenly_loaded_teachers():
    observations = [TeacherLoadObservation(teacher_id=i, periods_per_week=20 + i) for i in range(4)]  # 20,21,22,23
    assert detect_teacher_overload(observations) == []


def test_isolation_forest_path_flags_clear_outlier_with_enough_teachers():
    # >= MIN_TEACHERS_FOR_MODEL (6) teachers - engages the IsolationForest path.
    observations = [TeacherLoadObservation(teacher_id=i, periods_per_week=20) for i in range(8)]
    observations.append(TeacherLoadObservation(teacher_id=99, periods_per_week=50))  # clear outlier
    anomalies = detect_teacher_overload(observations)
    assert any(a.entity_id == 99 for a in anomalies)


def test_isolation_forest_path_does_not_flag_uniform_loads():
    observations = [TeacherLoadObservation(teacher_id=i, periods_per_week=20) for i in range(8)]
    assert detect_teacher_overload(observations) == []


def test_isolation_forest_does_not_flag_a_suspiciously_light_load_as_overload():
    observations = [TeacherLoadObservation(teacher_id=i, periods_per_week=20) for i in range(8)]
    observations.append(TeacherLoadObservation(teacher_id=99, periods_per_week=2))  # a low outlier, not overload
    anomalies = detect_teacher_overload(observations)
    assert all(a.entity_id != 99 for a in anomalies)
