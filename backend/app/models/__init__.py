from app.models.admissions import AdmissionApplication
from app.models.alerts import AlertDismissal
from app.models.attendance import AttendanceReconciliation, AttendanceRecord, FaceEmbedding
from app.models.audit import AuditLogEntry
from app.models.class_ import SchoolClass
from app.models.document import Document, ExtractedEntity, OcrResult
from app.models.enrollment import Enrollment
from app.models.exams import Exam, ExamRoomAssignment, InvigilationAssignment, SeatingAssignment
from app.models.fees import FeeRecord, FeeReminder, FeeSchedule
from app.models.parent_student import ParentStudent
from app.models.risk import Intervention, RemarkStub, RiskFlag
from app.models.role import Role
from app.models.school import School
from app.models.staffing import LeaveRequest, StaffingForecast, Substitution
from app.models.subject import Subject
from app.models.syllabus import AnomalyFlag, SyllabusCheckpoint, SyllabusPlan
from app.models.timetable import (
    ClassSubjectRequirement,
    Room,
    SubjectRoomRequirement,
    TeacherSubject,
    TeacherUnavailability,
    TimetableSlot,
)
from app.models.user import User

__all__ = [
    "AdmissionApplication",
    "AlertDismissal",
    "AnomalyFlag",
    "AttendanceReconciliation",
    "AttendanceRecord",
    "AuditLogEntry",
    "ClassSubjectRequirement",
    "Document",
    "Enrollment",
    "Exam",
    "ExamRoomAssignment",
    "ExtractedEntity",
    "FaceEmbedding",
    "FeeRecord",
    "FeeReminder",
    "FeeSchedule",
    "Intervention",
    "InvigilationAssignment",
    "LeaveRequest",
    "OcrResult",
    "ParentStudent",
    "RemarkStub",
    "RiskFlag",
    "Role",
    "Room",
    "School",
    "SchoolClass",
    "SeatingAssignment",
    "StaffingForecast",
    "Subject",
    "SubjectRoomRequirement",
    "Substitution",
    "SyllabusCheckpoint",
    "SyllabusPlan",
    "TeacherSubject",
    "TeacherUnavailability",
    "TimetableSlot",
    "User",
]
