import { useEffect } from "react";
import { Routes, Route, Navigate } from "react-router-dom";
import { supabase } from "@/api/supabaseClient";
import { useAuthStore } from "@/store/authStore";
import Layout from "@/components/Layout";
import ProtectedRoute from "@/components/ProtectedRoute";
import Login from "@/routes/Login";
import PrincipalDashboard from "@/routes/principal/PrincipalDashboard";
import AdminDashboard from "@/routes/admin/AdminDashboard";
import TeacherDashboard from "@/routes/teacher/TeacherDashboard";
import StudentDashboard from "@/routes/student/StudentDashboard";
import ParentDashboard from "@/routes/parent/ParentDashboard";

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
      <Route element={<Layout />}>
        <Route path="/" element={<Navigate to={role ? `/${role}` : "/login"} replace />} />
        <Route
          path="/principal"
          element={
            <ProtectedRoute allowedRoles={["principal"]}>
              <PrincipalDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/admin"
          element={
            <ProtectedRoute allowedRoles={["admin"]}>
              <AdminDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/teacher"
          element={
            <ProtectedRoute allowedRoles={["teacher"]}>
              <TeacherDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/student"
          element={
            <ProtectedRoute allowedRoles={["student"]}>
              <StudentDashboard />
            </ProtectedRoute>
          }
        />
        <Route
          path="/parent"
          element={
            <ProtectedRoute allowedRoles={["parent"]}>
              <ParentDashboard />
            </ProtectedRoute>
          }
        />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
