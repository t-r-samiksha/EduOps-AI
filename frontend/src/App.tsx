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
import ChildSummary from "@/routes/parent/ChildSummary";
import ParentBot from "@/routes/parent/ParentBot";

interface RouteConfig {
  path: string;
  role: Role;
  element: ReactElement;
}

// Dashboards stay per-role stubs for anything not yet built this session
// (Person B/C territory). Every other entry is a real, live-data screen.
const ROUTE_TABLE: RouteConfig[] = [
  { path: "/principal", role: "principal", element: <PrincipalDashboard /> },
  { path: "/principal/timetable", role: "principal", element: <TimetablePage /> },
  { path: "/principal/staffing", role: "principal", element: <StaffingPage /> },
  { path: "/principal/risk", role: "principal", element: <RiskDashboard /> },
  { path: "/principal/syllabus", role: "principal", element: <SyllabusPage /> },
  { path: "/principal/approvals", role: "principal", element: <ApprovalsInbox /> },
  { path: "/principal/ocr", role: "principal", element: <OcrPage /> },
  { path: "/principal/fees", role: "principal", element: <FeesPage /> },
  { path: "/principal/admissions", role: "principal", element: <AdmissionsPage /> },
  { path: "/principal/exams", role: "principal", element: <ExamsPage /> },
  { path: "/principal/school-management", role: "principal", element: <SchoolManagementPage /> },

  { path: "/admin", role: "admin", element: <AdminDashboard /> },
  { path: "/admin/timetable", role: "admin", element: <TimetablePage /> },
  { path: "/admin/attendance", role: "admin", element: <AttendanceCapture /> },
  { path: "/admin/staffing", role: "admin", element: <StaffingPage /> },
  { path: "/admin/risk", role: "admin", element: <RiskDashboard /> },
  { path: "/admin/syllabus", role: "admin", element: <SyllabusPage /> },
  { path: "/admin/approvals", role: "admin", element: <ApprovalsInbox /> },
  { path: "/admin/ocr", role: "admin", element: <OcrPage /> },
  { path: "/admin/fees", role: "admin", element: <FeesPage /> },
  { path: "/admin/admissions", role: "admin", element: <AdmissionsPage /> },
  { path: "/admin/exams", role: "admin", element: <ExamsPage /> },
  { path: "/admin/school-management", role: "admin", element: <SchoolManagementPage /> },

  { path: "/teacher", role: "teacher", element: <TeacherDashboard /> },
  { path: "/teacher/timetable", role: "teacher", element: <TimetablePage /> },
  { path: "/teacher/attendance", role: "teacher", element: <AttendanceCapture /> },
  { path: "/teacher/staffing", role: "teacher", element: <StaffingPage /> },
  { path: "/teacher/risk", role: "teacher", element: <RiskDashboard /> },
  { path: "/teacher/syllabus", role: "teacher", element: <SyllabusPage /> },
  { path: "/teacher/fees", role: "teacher", element: <FeesPage /> },
  { path: "/teacher/exams", role: "teacher", element: <InvigilationDutiesPage /> },

  { path: "/student", role: "student", element: <StudentDashboard /> },
  { path: "/student/timetable", role: "student", element: <TimetablePage /> },
  { path: "/student/fees", role: "student", element: <FeesPage /> },
  { path: "/student/exams", role: "student", element: <StudentSeatLookup /> },
  { path: "/student/doubt-bot", role: "student", element: <StudentDoubtBot /> },

  { path: "/parent", role: "parent", element: <ParentDashboard /> },
  { path: "/parent/child", role: "parent", element: <ChildSummary /> },
  { path: "/parent/bot", role: "parent", element: <ParentBot /> },
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
