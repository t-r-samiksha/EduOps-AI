import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { GraduationCap, LogOut, Menu, X } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { signOut } from "@/api/auth";
import { queryClient } from "@/api/queryClient";
import { Button } from "@/components/ui/button";
import ThemeToggle from "@/components/ThemeToggle";
import { NAV_ITEMS, ROLE_LABEL } from "@/lib/navConfig";
import { cn } from "@/lib/utils";

function Logo({ expanded = true }: { expanded?: boolean }) {
  return (
    <div className="mb-6 flex items-center gap-3 overflow-hidden px-1">
      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-foreground shadow-sm">
        <GraduationCap className="h-5 w-5" />
      </div>
      <div
        className={cn(
          "overflow-hidden whitespace-nowrap transition-opacity duration-300",
          expanded ? "opacity-100" : "opacity-0 group-hover:opacity-100"
        )}
      >
        <span className="font-display text-lg font-bold tracking-tight text-ink">EduOps</span>
        <span className="ml-1 font-mono text-xs tracking-widest text-accent">AI</span>
      </div>
    </div>
  );
}

function SidebarNav({ onNavigate, expanded = true }: { onNavigate?: () => void; expanded?: boolean }) {
  const { role } = useAuthStore();
  const items = role ? NAV_ITEMS[role] : [];

  return (
    <nav className="flex flex-1 flex-col gap-1 overflow-hidden">
      {items.map((item) => (
        <NavLink
          key={item.path}
          to={item.path}
          end={item.end}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3.5 whitespace-nowrap rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
              isActive ? "bg-accent/10 font-semibold text-accent" : "text-ink-muted hover:bg-elevated hover:text-accent"
            )
          }
        >
          <item.icon className="h-5 w-5 shrink-0" />
          <span
            className={cn(
              "overflow-hidden transition-opacity duration-300",
              expanded ? "opacity-100" : "opacity-0 group-hover:opacity-100"
            )}
          >
            {item.label}
          </span>
        </NavLink>
      ))}
    </nav>
  );
}

export default function Layout() {
  const { user, role } = useAuthStore();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);

  async function handleLogout() {
    await signOut();
    // Every cached query (current-user, seating, etc.) is scoped by a fixed key,
    // not by which account fetched it - without this, whoever logs in next on
    // this tab within the staleTime window would see the previous user's
    // cached data (e.g. the wrong user_id, breaking "my seat" highlighting).
    queryClient.clear();
    navigate("/login");
  }

  return (
    <div className="flex min-h-screen bg-paper text-ink">
      {/*
        Desktop hover-expand icon rail — a REAL flex sibling of the content
        column (sticky, not fixed/absolute), so its width change on hover
        reflows the content via normal flexbox layout instead of overlaying
        it. This makes clipping structurally impossible rather than relying
        on two separately-animated properties (sidebar width + content
        margin) staying in sync.
      */}
      <aside className="group sticky top-0 hidden h-screen w-20 shrink-0 flex-col overflow-hidden border-r border-border bg-panel px-3 py-6 shadow-elevated transition-[width] duration-300 ease-in-out hover:w-64 md:flex">
        <Logo expanded={false} />
        <SidebarNav expanded={false} />
      </aside>

      {/* Mobile drawer — a real overlay is the correct pattern here (tap to open/close, not hover) */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-ink/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col border-r border-border bg-panel px-3 py-6 shadow-elevated">
            <Button
              variant="ghost"
              size="icon"
              className="absolute right-2 top-2"
              onClick={() => setMobileOpen(false)}
              aria-label="Close navigation menu"
            >
              <X className="h-4 w-4" />
            </Button>
            <Logo expanded />
            <SidebarNav onNavigate={() => setMobileOpen(false)} expanded />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 shrink-0 items-center justify-between border-b border-border bg-panel/80 px-4 backdrop-blur-md sm:px-6">
          <div className="flex items-center gap-3">
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden"
              onClick={() => setMobileOpen(true)}
              aria-label="Open navigation menu"
            >
              <Menu className="h-5 w-5" />
            </Button>
            {role && (
              <span className="hidden rounded-full bg-accent/10 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-accent sm:inline-block">
                {ROLE_LABEL[role]}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 text-sm">
            <span className="hidden truncate text-ink-muted sm:inline">{user?.email}</span>
            <ThemeToggle />
            <Button variant="outline" size="sm" onClick={handleLogout}>
              <LogOut className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Log out</span>
            </Button>
          </div>
        </header>
        <main className="min-w-0 flex-1 overflow-x-hidden p-4 sm:p-6">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
