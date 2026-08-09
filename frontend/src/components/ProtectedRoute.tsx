import { Navigate } from "react-router-dom";
import { useAuthStore, type Role } from "@/store/authStore";

interface ProtectedRouteProps {
  allowedRoles: Role[];
  children: React.ReactNode;
}

export default function ProtectedRoute({ allowedRoles, children }: ProtectedRouteProps) {
  const { session, role, isLoading } = useAuthStore();

  if (isLoading) return null;
  if (!session) return <Navigate to="/login" replace />;
  if (!role || !allowedRoles.includes(role)) return <Navigate to="/login" replace />;

  return <>{children}</>;
}
