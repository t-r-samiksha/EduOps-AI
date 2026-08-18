import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { ChevronDown, GraduationCap, LogOut, Menu, X } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { signOut } from "@/api/auth";
import { queryClient } from "@/api/queryClient";
import { Button } from "@/components/ui/button";
import ThemeToggle from "@/components/ThemeToggle";
import { NotificationBell } from "@/components/notifications/NotificationBell";
import {
  NAV_ITEMS,
  ROLE_LABEL,
  isNavGroup,
  type NavBadge,
  type NavGroup as NavGroupType,
  type NavItem,
} from "@/lib/navConfig";
import { useFeePaymentRequests } from "@/api/hooks/useFeePaymentRequests";
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
          expanded ? "opacity-100" : "opacity-0"
        )}
      >
        <span className="font-display text-lg font-bold tracking-tight text-ink">EduOps</span>
        <span className="ml-1 font-mono text-xs tracking-widest text-accent">AI</span>
      </div>
    </div>
  );
}

/** Resolves a NavItem's badge key to a live count.
 *
 * Kept here rather than in navConfig so that module stays pure data. Renders nothing
 * at zero - a permanent "0" beside a nav label is noise, and the point of a badge is
 * that its presence means something. */
function NavBadgeCount({ badge, expanded }: { badge: NavBadge; expanded: boolean }) {
  // Same query key as the Fees page and the dashboard tile, so all three share one
  // request and update together.
  const queue = useFeePaymentRequests({ live: badge === "pending-fee-payment-requests" });
  const count = queue.data?.pending_count ?? 0;
  if (count === 0) return null;

  return (
    <span
      className={cn(
        "ml-auto shrink-0 rounded-full bg-urgent px-1.5 py-0.5 text-[0.625rem] font-bold tabular-nums text-urgent-foreground transition-opacity duration-300",
        expanded ? "opacity-100" : "opacity-0"
      )}
      title={`${count} fee payment claim${count === 1 ? "" : "s"} awaiting confirmation`}
    >
      {count}
    </span>
  );
}

function NavRow({
  item, expanded, onNavigate, nested = false,
}: { item: NavItem; expanded: boolean; onNavigate?: () => void; nested?: boolean }) {
  return (
    <NavLink
      to={item.path}
      end={item.end}
      onClick={onNavigate}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-3.5 whitespace-nowrap rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
          nested && expanded && "pl-6",
          isActive ? "bg-accent/10 font-semibold text-accent" : "text-ink-muted hover:bg-elevated hover:text-accent"
        )
      }
    >
      <item.icon className="h-5 w-5 shrink-0" />
      <span
        className={cn(
          "overflow-hidden transition-opacity duration-300",
          expanded ? "opacity-100" : "opacity-0"
        )}
      >
        {item.label}
      </span>
      {item.badge && <NavBadgeCount badge={item.badge} expanded={expanded} />}
    </NavLink>
  );
}

/** A collapsible section. Only rendered when the sidebar is EXPANDED - see SidebarNav. */
function NavGroupSection({
  group, expanded, onNavigate,
}: { group: NavGroupType; expanded: boolean; onNavigate?: () => void }) {
  const { pathname } = useLocation();
  const holdsActive = group.children.some((c) => pathname.startsWith(c.path));
  // Open if you are inside it, so the active page is never hidden behind a closed
  // section - otherwise navigating by URL leaves the menu pointing somewhere else.
  const [open, setOpen] = useState(holdsActive);
  useEffect(() => {
    if (holdsActive) setOpen(true);
  }, [holdsActive]);

  return (
    <div>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`${group.label} section, ${open ? "expanded" : "collapsed"}`}
        className={cn(
          "flex w-full items-center gap-3.5 whitespace-nowrap rounded-xl px-3 py-2.5 text-sm font-medium transition-colors",
          holdsActive ? "text-accent" : "text-ink-muted hover:bg-elevated hover:text-accent"
        )}
      >
        <group.icon className="h-5 w-5 shrink-0" />
        <span
          className={cn(
            "flex-1 overflow-hidden text-left transition-opacity duration-300",
            expanded ? "opacity-100" : "opacity-0"
          )}
        >
          {group.label}
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 transition-transform",
            open ? "rotate-180" : "",
            expanded ? "opacity-100" : "opacity-0"
          )}
          aria-hidden="true"
        />
      </button>
      {open && expanded && (
        <div className="mt-0.5 flex flex-col gap-0.5">
          {group.children.map((child) => (
            <NavRow key={child.path} item={child} expanded={expanded} onNavigate={onNavigate} nested />
          ))}
        </div>
      )}
    </div>
  );
}

function SidebarNav({ onNavigate, expanded = true }: { onNavigate?: () => void; expanded?: boolean }) {
  const { role } = useAuthStore();
  const entries = role ? NAV_ITEMS[role] : [];

  // COLLAPSED RAIL SHOWS TOP-LEVEL ONLY - flat items plus one icon per group.
  //
  // Flattening instead put 24 unlabelled icons in a w-20 column, which overflows an
  // 800px viewport (16 fit) and a 900px one (18 fit) and turns the rail into a
  // scrolling strip of anonymous glyphs. Top-level is 8-9 icons for every role, which
  // fits at both heights with room to spare. Nothing becomes unreachable: the rail
  // expands on hover or keyboard focus, and the groups open there.
  const rows = entries;

  return (
    // overflow-y-auto, not overflow-hidden: at 24 entries the rail CLIPPED everything
    // below the fold, so those items were unreachable rather than merely low.
    <nav className="flex flex-1 flex-col gap-1 overflow-y-auto overflow-x-hidden">
      {rows.map((entry) =>
        isNavGroup(entry) ? (
          <NavGroupSection key={entry.label} group={entry} expanded={expanded} onNavigate={onNavigate} />
        ) : (
          <NavRow key={entry.path} item={entry} expanded={expanded} onNavigate={onNavigate} />
        )
      )}
    </nav>
  );
}

export default function Layout() {
  const { user, role } = useAuthStore();
  const navigate = useNavigate();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);

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
      {/* The width change is CSS (hover:w-64), but REACT has to know too: the menu
          renders collapsible groups only when `expanded`, and with a CSS-only hover the
          component stayed in its collapsed branch forever - so a desktop user saw a flat
          list on hover and the groups never appeared at all. onFocus/onBlur are included
          so keyboard tabbing into the rail opens it the same way. */}
      <aside
        className={cn(
          "group sticky top-0 hidden h-screen shrink-0 flex-col overflow-hidden border-r border-border bg-panel px-3 py-6 shadow-elevated transition-[width] duration-300 ease-in-out md:flex",
          // ONE source of truth. This used to be CSS `hover:w-64` while the menu shape
          // came from React state - two mechanisms tracking one thing, which desync when
          // a pointer leaves fast or re-enters via a child: you get a wide rail rendering
          // collapsed content, or a narrow rail with labels clipped out of view.
          railOpen ? "w-64" : "w-20"
        )}
        onMouseEnter={() => setRailOpen(true)}
        onMouseLeave={() => setRailOpen(false)}
        onFocusCapture={() => setRailOpen(true)}
        onBlurCapture={(e) => {
          if (!e.currentTarget.contains(e.relatedTarget as Node)) setRailOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") {
            setRailOpen(false);
            (e.target as HTMLElement).blur();
          }
        }}
      >
        <Logo expanded={railOpen} />
        {/* NOT a constant. This was hardcoded `expanded={false}` while the rail widened
            via CSS hover, so React never left its collapsed branch and the collapsible
            groups were invisible on desktop entirely - they rendered only in the mobile
            drawer, which is the one place nobody demos. */}
        <SidebarNav expanded={railOpen} />
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
            <NotificationBell />
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
