import { useEffect } from "react";
import type { ReactElement } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { supabase } from "@/api/supabaseClient";
import { useAuthStore, type Role } from "@/store/authStore";
import Layout from "@/components/Layout";
import ProtectedRoute from "@/components/ProtectedRoute";
import Login from "@/routes/Login";
import Signup from "@/routes/Signup";
import OnboardingWizard from "@/routes/OnboardingWizard";
import PrincipalDashboard from "@/routes/principal/PrincipalDashboard";
import AdminDashboard from "@/routes/admin/AdminDashboard";
import TeacherDashboard from "@/routes/teacher/TeacherDashboard";
import StudentDashboard from "@/routes/student/StudentDashboard";
import ParentDashboard from "@/routes/parent/ParentDashboard";
import TimetablePage from "@/components/timetable/TimetablePage";
import AttendanceCapture from "@/components/attendance/AttendanceCapture";
import StaffingPage from "@/components/staffing/StaffingPage";
import RiskDashboard from "@/components/risk/RiskDashboard";
import SyllabusPage from "@/components/syllabus/SyllabusPage";
import ApprovalsInbox from "@/components/approvals/ApprovalsInbox";
import OcrPage from "@/components/ocr/OcrPage";
import FeesPage from "@/components/fees/FeesPage";
import AdmissionsPage from "@/components/admissions/AdmissionsPage";
import ExamsPage from "@/components/exams/ExamsPage";
import InvigilationDutiesPage from "@/components/exams/InvigilationDutiesPage";
import StudentSeatLookup from "@/components/exams/StudentSeatLookup";
import SchoolManagementPage from "@/components/admin/SchoolManagementPage";
import StudentDoubtBot from "@/components/bots/StudentDoubtBot";
import DoubtThreadsPage from "@/components/doubts/DoubtThreadsPage";
import ChildSummary from "@/routes/parent/ChildSummary";
import ChildAttendance from "@/routes/parent/ChildAttendance";
import ParentBot from "@/routes/parent/ParentBot";
import StudentAttendance from "@/routes/student/StudentAttendance";
import ClassroomStreamPage from "@/components/classroom/ClassroomStreamPage";
import ResourcesPage from "@/components/resources/ResourcesPage";
import AssignmentsPage from "@/components/assignments/AssignmentsPage";
import SubmissionTrackerPage from "@/components/assignments/SubmissionTrackerPage";
import QuizzesPage from "@/components/quizzes/QuizzesPage";
import GradebookPage from "@/components/gradebook/GradebookPage";
import ReportCardsPage from "@/components/report_cards/ReportCardsPage";
import DigitalLibraryPage from "@/components/library/DigitalLibraryPage";
import HomeworkCalendarPage from "@/components/calendar/HomeworkCalendarPage";
import StudentAnalyticsPage from "@/components/analytics/StudentAnalyticsPage";
import BulkRemarksPage from "@/components/remarks/BulkRemarksPage";
import TeacherSyllabusPacePage from "@/components/syllabus/TeacherSyllabusPacePage";
import TeacherResources from "@/routes/teacher/Resources";
import TeacherAssistantBot from "@/components/bots/TeacherAssistantBot";

interface RouteConfig {
  path: string;
  role: Role;
  element: ReactElement;
}

// Dashboards stay per-role stubs for anything not yet built this session
// (Person B/C territory). Every other entry is a real, live-data screen.
const ROUTE_TABLE: RouteConfig[] = [
  { path: "/principal", role: "principal", element: <PrincipalDashboard /> },
  { path: "/principal/classroom", role: "principal", element: <ClassroomStreamPage /> },
  { path: "/principal/classroom/:id", role: "principal", element: <ClassroomStreamPage /> },
  { path: "/principal/resources", role: "principal", element: <ResourcesPage /> },
  { path: "/principal/resources/:classId", role: "principal", element: <ResourcesPage /> },
  { path: "/principal/assignments", role: "principal", element: <AssignmentsPage /> },
  { path: "/principal/assignments/:classId", role: "principal", element: <AssignmentsPage /> },
  { path: "/principal/assignments/:id/submissions", role: "principal", element: <SubmissionTrackerPage /> },
  { path: "/principal/quizzes", role: "principal", element: <QuizzesPage /> },
  { path: "/principal/gradebook", role: "principal", element: <GradebookPage /> },
  { path: "/principal/report-cards", role: "principal", element: <ReportCardsPage /> },
  { path: "/principal/library", role: "principal", element: <DigitalLibraryPage /> },
  { path: "/principal/calendar", role: "principal", element: <HomeworkCalendarPage /> },
  { path: "/principal/analytics", role: "principal", element: <StudentAnalyticsPage /> },
  { path: "/principal/remarks", role: "principal", element: <BulkRemarksPage /> },
  { path: "/principal/syllabus-pace", role: "principal", element: <TeacherSyllabusPacePage /> },
  { path: "/principal/timetable", role: "principal", element: <TimetablePage /> },
  { path: "/principal/attendance", role: "principal", element: <AttendanceCapture /> },
  { path: "/principal/staffing", role: "principal", element: <StaffingPage /> },
  { path: "/principal/risk", role: "principal", element: <RiskDashboard /> },
  { path: "/principal/syllabus", role: "principal", element: <SyllabusPage /> },
  { path: "/principal/approvals", role: "principal", element: <ApprovalsInbox /> },
  { path: "/principal/ocr", role: "principal", element: <OcrPage /> },
  { path: "/principal/fees", role: "principal", element: <FeesPage /> },
  // The payment-request queue is a tab on the Fees page now, not its own screen.
  // Kept as a redirect rather than deleted: the dashboard badge, the sidebar and the
  // `fee_payment_request` notifications all point at this path.
  {
    path: "/principal/fee-payment-requests",
    role: "principal",
    element: <Navigate to="/principal/fees?tab=requests" replace />,
  },
  { path: "/principal/admissions", role: "principal", element: <AdmissionsPage /> },
  { path: "/principal/exams", role: "principal", element: <ExamsPage /> },
  { path: "/principal/school-management", role: "principal", element: <SchoolManagementPage /> },
  { path: "/principal/assistant", role: "principal", element: <TeacherAssistantBot /> },

  { path: "/admin", role: "admin", element: <AdminDashboard /> },
  { path: "/admin/classroom", role: "admin", element: <ClassroomStreamPage /> },
  { path: "/admin/classroom/:id", role: "admin", element: <ClassroomStreamPage /> },
  { path: "/admin/resources", role: "admin", element: <ResourcesPage /> },
  { path: "/admin/resources/:classId", role: "admin", element: <ResourcesPage /> },
  { path: "/admin/assignments", role: "admin", element: <AssignmentsPage /> },
  { path: "/admin/assignments/:classId", role: "admin", element: <AssignmentsPage /> },
  { path: "/admin/assignments/:id/submissions", role: "admin", element: <SubmissionTrackerPage /> },
  { path: "/admin/quizzes", role: "admin", element: <QuizzesPage /> },
  { path: "/admin/gradebook", role: "admin", element: <GradebookPage /> },
  { path: "/admin/report-cards", role: "admin", element: <ReportCardsPage /> },
  { path: "/admin/library", role: "admin", element: <DigitalLibraryPage /> },
  { path: "/admin/calendar", role: "admin", element: <HomeworkCalendarPage /> },
  { path: "/admin/analytics", role: "admin", element: <StudentAnalyticsPage /> },
  { path: "/admin/remarks", role: "admin", element: <BulkRemarksPage /> },
  { path: "/admin/syllabus-pace", role: "admin", element: <TeacherSyllabusPacePage /> },
  { path: "/admin/timetable", role: "admin", element: <TimetablePage /> },
  { path: "/admin/attendance", role: "admin", element: <AttendanceCapture /> },
  { path: "/admin/staffing", role: "admin", element: <StaffingPage /> },
  { path: "/admin/risk", role: "admin", element: <RiskDashboard /> },
  { path: "/admin/syllabus", role: "admin", element: <SyllabusPage /> },
  { path: "/admin/approvals", role: "admin", element: <ApprovalsInbox /> },
  { path: "/admin/ocr", role: "admin", element: <OcrPage /> },
  { path: "/admin/fees", role: "admin", element: <FeesPage /> },
  { path: "/admin/fee-payment-requests", role: "admin", element: <Navigate to="/admin/fees?tab=requests" replace /> },
  { path: "/admin/admissions", role: "admin", element: <AdmissionsPage /> },
  { path: "/admin/exams", role: "admin", element: <ExamsPage /> },
  { path: "/admin/school-management", role: "admin", element: <SchoolManagementPage /> },
  { path: "/admin/assistant", role: "admin", element: <TeacherAssistantBot /> },

  { path: "/teacher", role: "teacher", element: <TeacherDashboard /> },
  { path: "/teacher/classroom", role: "teacher", element: <ClassroomStreamPage /> },
  { path: "/teacher/classroom/:id", role: "teacher", element: <ClassroomStreamPage /> },
  { path: "/teacher/resources", role: "teacher", element: <TeacherResources /> },
  { path: "/teacher/resources/:classId", role: "teacher", element: <TeacherResources /> },
  { path: "/teacher/assignments", role: "teacher", element: <AssignmentsPage /> },
  { path: "/teacher/assignments/:classId", role: "teacher", element: <AssignmentsPage /> },
  { path: "/teacher/assignments/:id/submissions", role: "teacher", element: <SubmissionTrackerPage /> },
  { path: "/teacher/quizzes", role: "teacher", element: <QuizzesPage /> },
  { path: "/teacher/gradebook", role: "teacher", element: <GradebookPage /> },
  { path: "/teacher/report-cards", role: "teacher", element: <ReportCardsPage /> },
  { path: "/teacher/library", role: "teacher", element: <DigitalLibraryPage /> },
  { path: "/teacher/calendar", role: "teacher", element: <HomeworkCalendarPage /> },
  { path: "/teacher/analytics", role: "teacher", element: <StudentAnalyticsPage /> },
  { path: "/teacher/remarks", role: "teacher", element: <BulkRemarksPage /> },
  { path: "/teacher/syllabus-pace", role: "teacher", element: <TeacherSyllabusPacePage /> },
  { path: "/teacher/timetable", role: "teacher", element: <TimetablePage /> },
  { path: "/teacher/attendance", role: "teacher", element: <AttendanceCapture /> },
  { path: "/teacher/staffing", role: "teacher", element: <StaffingPage /> },
  { path: "/teacher/risk", role: "teacher", element: <RiskDashboard /> },
  { path: "/teacher/syllabus", role: "teacher", element: <SyllabusPage /> },
  { path: "/teacher/fees", role: "teacher", element: <FeesPage /> },
  { path: "/teacher/exams", role: "teacher", element: <InvigilationDutiesPage /> },
  { path: "/teacher/doubts", role: "teacher", element: <DoubtThreadsPage /> },
  { path: "/teacher/assistant", role: "teacher", element: <TeacherAssistantBot /> },

  { path: "/student", role: "student", element: <StudentDashboard /> },
  { path: "/student/attendance", role: "student", element: <StudentAttendance /> },
  { path: "/student/timetable", role: "student", element: <TimetablePage /> },
  { path: "/student/fees", role: "student", element: <FeesPage /> },
  { path: "/student/exams", role: "student", element: <StudentSeatLookup /> },
  { path: "/student/doubt-bot", role: "student", element: <StudentDoubtBot /> },
  { path: "/student/doubts", role: "student", element: <DoubtThreadsPage /> },
  { path: "/student/classroom", role: "student", element: <ClassroomStreamPage /> },
  { path: "/student/classroom/:id", role: "student", element: <ClassroomStreamPage /> },
  { path: "/student/resources", role: "student", element: <ResourcesPage /> },
  { path: "/student/resources/:classId", role: "student", element: <ResourcesPage /> },
  { path: "/student/assignments", role: "student", element: <AssignmentsPage /> },
  { path: "/student/assignments/:classId", role: "student", element: <AssignmentsPage /> },
  { path: "/student/quizzes", role: "student", element: <QuizzesPage /> },
  { path: "/student/gradebook", role: "student", element: <GradebookPage /> },
  { path: "/student/report-cards", role: "student", element: <ReportCardsPage /> },
  { path: "/student/library", role: "student", element: <DigitalLibraryPage /> },
  { path: "/student/calendar", role: "student", element: <HomeworkCalendarPage /> },
  { path: "/student/analytics", role: "student", element: <StudentAnalyticsPage /> },
  { path: "/student/remarks", role: "student", element: <BulkRemarksPage /> },

  { path: "/parent", role: "parent", element: <ParentDashboard /> },
  { path: "/parent/child", role: "parent", element: <ChildSummary /> },
  { path: "/parent/attendance", role: "parent", element: <ChildAttendance /> },
  { path: "/parent/bot", role: "parent", element: <ParentBot /> },
  { path: "/parent/classroom", role: "parent", element: <ClassroomStreamPage /> },
  { path: "/parent/classroom/:id", role: "parent", element: <ClassroomStreamPage /> },
  { path: "/parent/resources", role: "parent", element: <ResourcesPage /> },
  { path: "/parent/resources/:classId", role: "parent", element: <ResourcesPage /> },
  { path: "/parent/assignments", role: "parent", element: <AssignmentsPage /> },
  { path: "/parent/assignments/:classId", role: "parent", element: <AssignmentsPage /> },
  { path: "/parent/gradebook", role: "parent", element: <GradebookPage /> },
  { path: "/parent/report-cards", role: "parent", element: <ReportCardsPage /> },
  { path: "/parent/library", role: "parent", element: <DigitalLibraryPage /> },
  { path: "/parent/calendar", role: "parent", element: <HomeworkCalendarPage /> },
  { path: "/parent/analytics", role: "parent", element: <StudentAnalyticsPage /> },
  { path: "/parent/remarks", role: "parent", element: <BulkRemarksPage /> },
  { path: "/parent/timetable", role: "parent", element: <TimetablePage /> },
  { path: "/parent/risk", role: "parent", element: <RiskDashboard /> },
  { path: "/parent/fees", role: "parent", element: <FeesPage /> },
];

export default function App() {
  const { setSession, setLoading, role } = useAuthStore();

  useEffect(() => {
    supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setLoading(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange((_event, session) => {
      setSession(session);
    });

    return () => listener.subscription.unsubscribe();
  }, [setSession, setLoading]);

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/signup" element={<Signup />} />
      <Route
        path="/onboarding"
        element={
          <ProtectedRoute allowedRoles={["admin", "principal"]}>
            <OnboardingWizard />
          </ProtectedRoute>
        }
      />
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to={role ? `/${role}` : "/login"} replace />} />
        {ROUTE_TABLE.map(({ path, role: routeRole, element }) => (
          <Route
            key={path}
            path={path}
            element={<ProtectedRoute allowedRoles={[routeRole]}>{element}</ProtectedRoute>}
          />
        ))}
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
