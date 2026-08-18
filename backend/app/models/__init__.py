from app.models.admissions import AdmissionApplication
from app.models.alerts import AlertDismissal
from app.models.announcement import Announcement, AnnouncementAcknowledgment
from app.models.assignment import Assignment, AssignmentSubmission
from app.models.attendance import AttendanceReconciliation, AttendanceRecord, FaceEmbedding
from app.models.audit import AuditLogEntry
from app.models.calendar import CalendarEvent
from app.models.class_ import SchoolClass
from app.models.classroom import Classroom, PostAttachment, StreamPost
from app.models.document import Document, ExtractedEntity, OcrResult
from app.models.doubt import DoubtThread, ThreadReply
from app.models.enrollment import Enrollment
from app.models.exams import Exam, ExamRoomAssignment, InvigilationAssignment, SeatingAssignment
from app.models.fees import FeePaymentRequest, FeeRecord, FeeReminder, FeeSchedule
from app.models.gradebook import GradebookEntry, GradebookWeight
from app.models.knowledge import ChatbotLog, KbChunk
from app.models.library import LibraryItem, LibraryLoan
from app.models.notification import Notification
from app.models.parent_student import ParentStudent
from app.models.quiz import Quiz, QuizAttempt, QuizQuestion
from app.models.remark import Remark
from app.models.report_card import ReportCard
from app.models.resource import Resource
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
    TeacherProfile,
    TeacherSubject,
    TeacherUnavailability,
    TimetableSlot,
)
from app.models.user import User

__all__ = [
    "AdmissionApplication",
    "AlertDismissal",
    "Announcement",
    "AnnouncementAcknowledgment",
    "AnomalyFlag",
    "Assignment",
    "AssignmentSubmission",
    "AttendanceReconciliation",
    "AttendanceRecord",
    "AuditLogEntry",
    "CalendarEvent",
    "ChatbotLog",
    "ClassSubjectRequirement",
    "Classroom",
    "Document",
    "DoubtThread",
    "Enrollment",
    "Exam",
    "ExamRoomAssignment",
    "ExtractedEntity",
    "FaceEmbedding",
    "FeePaymentRequest",
    "FeeRecord",
    "FeeReminder",
    "FeeSchedule",
    "GradebookEntry",
    "GradebookWeight",
    "Intervention",
    "InvigilationAssignment",
    "KbChunk",
    "LeaveRequest",
    "LibraryItem",
    "LibraryLoan",
    "Notification",
    "OcrResult",
    "ParentStudent",
    "PostAttachment",
    "Quiz",
    "QuizAttempt",
    "QuizQuestion",
    "Remark",
    "RemarkStub",
    "ReportCard",
    "Resource",
    "RiskFlag",
    "Role",
    "Room",
    "School",
    "SchoolClass",
    "SeatingAssignment",
    "StaffingForecast",
    "StreamPost",
    "Subject",
    "SubjectRoomRequirement",
    "Substitution",
    "SyllabusCheckpoint",
    "SyllabusPlan",
    "TeacherProfile",
    "TeacherSubject",
    "TeacherUnavailability",
    "ThreadReply",
    "TimetableSlot",
    "User",
]
