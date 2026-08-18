import { useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Bell,
  BookOpen,
  CalendarClock,
  CheckCircle2,
  ClipboardList,
  FileCheck2,
  GraduationCap,
  HelpCircle,
  Megaphone,
  MessageSquare,
  MessagesSquare,
  ScrollText,
  Sparkles,
  Wallet,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  useMarkAllNotificationsRead,
  useMarkNotificationRead,
  useNotificationStream,
  useNotifications,
  useUnreadCount,
} from "@/api/hooks/useNotifications";
import type { Notification } from "@/api/types";
import { NAV_ITEMS, flattenNav } from "@/lib/navConfig";
import { useAuthStore, type Role } from "@/store/authStore";
import { cn } from "@/lib/utils";

/** source_type -> icon. Falls back to the bell for a source_type the backend
 * adds later that this map doesn't know about yet. */
const SOURCE_ICON: Record<string, LucideIcon> = {
  early_warning: AlertTriangle,
  fee_reminder: Wallet,
  fee_payment_request: Wallet,
  fee_payment_confirmed: Wallet,
  fee_payment_rejected: Wallet,
  report_card: ScrollText,
  substitute_assigned: CalendarClock,
  announcement: Megaphone,
  remark_posted: MessageSquare,
  leave_decision: FileCheck2,
  admission_decision: ClipboardList,
  // Academics. These nine were dispatched for months with no entry here, so they
  // rendered with the fallback bell and no click target - see SOURCE_ROUTE below and
  // models/notification.py's SOURCE_TYPES, which is now validated.
  assignment_created: BookOpen,
  assignment_graded: GraduationCap,
  assignment_missing: AlertTriangle,
  assignment_nudge: AlertTriangle,
  assignment_reminder: CalendarClock,
  quiz_published: HelpCircle,
  // Doubt threads and insights.
  doubt_reply: MessagesSquare,
  doubt_answer_verified: CheckCircle2,
  top_doubts: Sparkles,
};

/** Where clicking a notification takes you: source_type -> path segment.
 *
 * The segment is validated against the caller's OWN nav in routeFor() below, so a
 * mapping that is right for a teacher but meaningless for a parent degrades to the
 * dashboard instead of a 404. Anything unmapped does the same. */
const SOURCE_ROUTE: Record<string, string> = {
  early_warning: "risk",
  fee_reminder: "fees",
  fee_payment_request: "fees",
  fee_payment_confirmed: "fees",
  fee_payment_rejected: "fees",
  substitute_assigned: "staffing",
  leave_decision: "staffing",
  admission_decision: "admissions",
  // M-8: `announcement` was missing, so clicking ANY announcement - including the ones
  // the announcement engine dispatches - dead-ended on the dashboard.
  announcement: "announcements",
  // The academics family, none of which had a route.
  report_card: "report-cards",
  remark_posted: "remarks",
  assignment_created: "assignments",
  assignment_graded: "assignments",
  assignment_missing: "assignments",
  assignment_nudge: "assignments",
  assignment_reminder: "assignments",
  quiz_published: "quizzes",
  doubt_reply: "doubts",
  doubt_answer_verified: "doubts",
  top_doubts: "assistant",
};

function routeFor(notification: Notification, role: Role | null): string {
  if (!role) return "/";
  const segment = SOURCE_ROUTE[notification.source_type];
  if (!segment) return `/${role}`;

  // A segment that is right for one role can be absent for another - a parent has no
  // /parent/quizzes, and the Assistant Bot is teacher-only. Navigating there would 404,
  // which is worse than landing on the dashboard. Checked against the role's OWN nav so
  // this stays correct as menus change, rather than duplicating the route table here.
  const path = `/${role}/${segment}`;
  // flattenNav, NOT a top-level scan: most destinations now live inside collapsible
  // groups, and a top-level-only check would silently send every one of them to the
  // dashboard. The fallback is not an error, so nothing would have surfaced it.
  const exists = flattenNav(NAV_ITEMS[role] ?? []).some((item) => item.path === path);
  return exists ? path : `/${role}`;
}

/** Minimal relative-time formatter. This project has no date library and adding
 * one for a single timestamp column isn't worth the dependency. */
function relativeTime(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(iso).toLocaleDateString();
}

function NotificationRow({
  notification,
  onSelect,
}: {
  notification: Notification;
  onSelect: (notification: Notification) => void;
}) {
  const Icon = SOURCE_ICON[notification.source_type] ?? Bell;
  const unread = notification.read_at === null;

  return (
    <button
      type="button"
      onClick={() => onSelect(notification)}
      className={cn(
        "flex w-full gap-3 border-b border-border px-4 py-3 text-left transition-colors last:border-b-0",
        "hover:bg-elevated focus-visible:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
        unread && "bg-accent/5"
      )}
    >
      <Icon
        className={cn(
          "mt-0.5 h-4 w-4 shrink-0",
          notification.priority === "urgent" ? "text-urgent" : "text-ink-muted"
        )}
        aria-hidden="true"
      />
      <span className="min-w-0 flex-1">
        <span className="flex items-start justify-between gap-2">
          <span className={cn("truncate text-sm", unread ? "font-semibold text-ink" : "text-ink-muted")}>
            {notification.title}
          </span>
          {unread && <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-accent" aria-hidden="true" />}
        </span>
        {notification.body && (
          <span className="mt-0.5 line-clamp-2 block text-xs text-ink-muted">{notification.body}</span>
        )}
        <span className="mt-1 block text-xs text-ink-faint">{relativeTime(notification.created_at)}</span>
      </span>
    </button>
  );
}

export function NotificationBell() {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const role = useAuthStore((s) => s.role);

  // Stream stays connected whether or not the dropdown is open - the badge is
  // the point, and it lives in the header on every page.
  useNotificationStream(true);

  const { data: unread } = useUnreadCount();
  const { data: page } = useNotifications(1, undefined, 10);
  const markRead = useMarkNotificationRead();
  const markAllRead = useMarkAllNotificationsRead();

  const count = unread?.count ?? 0;
  const items = page?.items ?? [];

  function handleSelect(notification: Notification) {
    if (notification.read_at === null) markRead.mutate(notification.id);
    setOpen(false);
    navigate(routeFor(notification, role));
  }

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="relative"
          aria-label={count > 0 ? `Notifications, ${count} unread` : "Notifications"}
        >
          <Bell className="h-5 w-5" aria-hidden="true" />
          {count > 0 && (
            <span
              className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-urgent px-1 text-[10px] font-semibold leading-none text-urgent-foreground"
              aria-hidden="true"
            >
              {count > 9 ? "9+" : count}
            </span>
          )}
        </Button>
      </PopoverTrigger>

      {/* The only aria-live region in this codebase so far. Screen readers
          announce the count changing (the stream pushes it) without the user
          having to open the dropdown to find out. Visually hidden because the
          badge above already conveys it sighted. */}
      <span aria-live="polite" className="sr-only">
        {count > 0 ? `${count} unread notifications` : "No unread notifications"}
      </span>

      <PopoverContent className="w-80 p-0 sm:w-96">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="font-display text-sm font-semibold tracking-tight">Notifications</h2>
          {count > 0 && (
            <button
              type="button"
              onClick={() => markAllRead.mutate()}
              disabled={markAllRead.isPending}
              className="rounded-lg px-1 text-xs font-medium text-accent transition-colors hover:text-accent-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
            >
              Mark all read
            </button>
          )}
        </div>

        <div className="max-h-96 overflow-y-auto">
          {items.length === 0 ? (
            <p className="px-4 py-8 text-center text-sm text-ink-muted">You&rsquo;re all caught up.</p>
          ) : (
            items.map((notification) => (
              <NotificationRow key={notification.id} notification={notification} onSelect={handleSelect} />
            ))
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
