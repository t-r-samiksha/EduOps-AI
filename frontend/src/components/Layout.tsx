import { Outlet, useNavigate } from "react-router-dom";
import { useAuthStore } from "@/store/authStore";
import { signOut } from "@/api/auth";
import { Button } from "@/components/ui/button";

export default function Layout() {
  const { user, role } = useAuthStore();
  const navigate = useNavigate();

  async function handleLogout() {
    await signOut();
    navigate("/login");
  }

  return (
    <div className="min-h-screen flex flex-col">
      <header className="border-b border-border">
        <div className="container flex h-14 items-center justify-between">
          <span className="font-semibold">EduOps AI</span>
          <div className="flex items-center gap-4 text-sm">
            <span className="text-muted-foreground">
              {user?.email} ({role})
            </span>
            <Button variant="outline" size="sm" onClick={handleLogout}>
              Log out
            </Button>
          </div>
        </div>
      </header>
      <main className="container flex-1 py-6">
        <Outlet />
      </main>
    </div>
  );
}
