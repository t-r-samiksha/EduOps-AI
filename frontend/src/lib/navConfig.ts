import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  Armchair,
  Bot,
  BookOpen,
  BookOpenCheck,
  CalendarClock,
  Calendar as CalendarIcon,
  ClipboardList,
  Compass,
  FileCheck2,
  FileText,
  FolderKanban,
  GraduationCap,
  HelpCircle,
  LayoutGrid,
  Megaphone,
  Library,
  MessageSquare,
  MessagesSquare,
  School,
  ScanText,
  ScanFace,
  TrendingUp,
  Users,
  Wallet,
  User as UserIcon,
} from "lucide-react";
import type { Role } from "@/store/authStore";

/** A live count rendered on a nav item. The Layout resolves the key to a hook -
 * navConfig stays a plain data module with no data-fetching in it.
 *
 * Exists because the fee payment queue became a TAB rather than its own page, and an
 * inbox that parents are waiting on cannot only be visible once you're already on the
 * right screen. */
export type NavBadge = "pending-fee-payment-requests";

export interface NavItem {
  label: string;
  path: string;
  icon: LucideIcon;
  end?: boolean;
  badge?: NavBadge;
}

/** A collapsible section of the sidebar.
 *
 * Deliberately NOT a NavItem with children: a group has no path and is never a
 * navigation target, and modelling it as one invites `item.path` to be read on
 * something that has none. The nav is therefore a list of (NavItem | NavGroup).
 *
 * Groups exist because the menus reached 24 entries and the rail clipped everything
 * below the fold - `overflow-hidden`, so those items were not merely hard to reach but
 * unreachable. Collapsible sections, not hover flyouts: the rail is ALREADY a
 * hover-expand surface, and nesting hover inside hover is fragile on a projector and
 * broken for touch and keyboard. */
export interface NavGroup {
  label: string;
  icon: LucideIcon;
  children: NavItem[];
}

export type NavEntry = NavItem | NavGroup;

export function isNavGroup(entry: NavEntry): entry is NavGroup {
  return (entry as NavGroup).children !== undefined;
}

/** Every NavItem a role can reach, groups flattened.
 *
 * Anything validating a destination MUST use this rather than iterating NAV_ITEMS
 * directly - NotificationBell's routeFor() checks a notification's target against the
 * role's own menu, and once items moved into groups a top-level-only scan would have
 * silently failed every grouped destination. The failure mode is a silent fallback to
 * the dashboard, not an error, so nothing would have surfaced it. */
export function flattenNav(entries: NavEntry[]): NavItem[] {
  return entries.flatMap((e) => (isNavGroup(e) ? e.children : [e]));
}

export const NAV_ITEMS: Record<Role, NavEntry[]> = {
  admin: [
    { label: "Command Center", path: "/admin", icon: LayoutGrid, end: true },
    { label: "Announcements", path: "/admin/announcements", icon: Megaphone },
    { label: "Fees", path: "/admin/fees", icon: Wallet, badge: "pending-fee-payment-requests" },
    { label: "Attendance", path: "/admin/attendance", icon: ScanFace },
    { label: "Timetable", path: "/admin/timetable", icon: CalendarClock },
    {
      label: "Academics",
      icon: GraduationCap,
      children: [
        { label: "Classroom", path: "/admin/classroom", icon: BookOpen },
        { label: "Resources", path: "/admin/resources", icon: FolderKanban },
        { label: "Assignments", path: "/admin/assignments", icon: ClipboardList },
        { label: "Quizzes", path: "/admin/quizzes", icon: HelpCircle },
        { label: "Gradebook", path: "/admin/gradebook", icon: GraduationCap },
        { label: "Report Cards", path: "/admin/report-cards", icon: FileText },
        { label: "Digital Library", path: "/admin/library", icon: Library },
        { label: "Homework Calendar", path: "/admin/calendar", icon: CalendarIcon },
        { label: "Student Analytics", path: "/admin/analytics", icon: TrendingUp },
        { label: "Remarks", path: "/admin/remarks", icon: MessageSquare },
        { label: "Syllabus Pace", path: "/admin/syllabus-pace", icon: Compass },
      ],
    },
    {
      label: "People",
      icon: Users,
      children: [
        { label: "Staffing", path: "/admin/staffing", icon: Users },
        { label: "Admissions", path: "/admin/admissions", icon: ClipboardList },
        { label: "Early-Warning", path: "/admin/risk", icon: AlertTriangle },
      ],
    },
    {
      label: "Operations",
      icon: Compass,
      children: [
        { label: "Syllabus", path: "/admin/syllabus", icon: BookOpenCheck },
        { label: "Approvals", path: "/admin/approvals", icon: FileCheck2 },
        { label: "Document OCR", path: "/admin/ocr", icon: ScanText },
        { label: "Exams", path: "/admin/exams", icon: Armchair },
        { label: "School Management", path: "/admin/school-management", icon: School },
      ],
    },
  ],
  principal: [
    { label: "Dashboard", path: "/principal", icon: LayoutGrid, end: true },
    { label: "Announcements", path: "/principal/announcements", icon: Megaphone },
    { label: "Fees", path: "/principal/fees", icon: Wallet, badge: "pending-fee-payment-requests" },
    { label: "Attendance", path: "/principal/attendance", icon: ScanFace },
    { label: "Timetable", path: "/principal/timetable", icon: CalendarClock },
    {
      label: "Academics",
      icon: GraduationCap,
      children: [
        { label: "Classroom", path: "/principal/classroom", icon: BookOpen },
        { label: "Resources", path: "/principal/resources", icon: FolderKanban },
        { label: "Assignments", path: "/principal/assignments", icon: ClipboardList },
        { label: "Quizzes", path: "/principal/quizzes", icon: HelpCircle },
        { label: "Gradebook", path: "/principal/gradebook", icon: GraduationCap },
        { label: "Report Cards", path: "/principal/report-cards", icon: FileText },
        { label: "Digital Library", path: "/principal/library", icon: Library },
        { label: "Homework Calendar", path: "/principal/calendar", icon: CalendarIcon },
        { label: "Student Analytics", path: "/principal/analytics", icon: TrendingUp },
        { label: "Remarks", path: "/principal/remarks", icon: MessageSquare },
        { label: "Syllabus Pace", path: "/principal/syllabus-pace", icon: Compass },
      ],
    },
    {
      label: "People",
      icon: Users,
      children: [
        { label: "Staffing", path: "/principal/staffing", icon: Users },
        { label: "Admissions", path: "/principal/admissions", icon: ClipboardList },
        { label: "Early-Warning", path: "/principal/risk", icon: AlertTriangle },
      ],
    },
    {
      label: "Operations",
      icon: Compass,
      children: [
        { label: "Syllabus", path: "/principal/syllabus", icon: BookOpenCheck },
        { label: "Approvals", path: "/principal/approvals", icon: FileCheck2 },
        { label: "Document OCR", path: "/principal/ocr", icon: ScanText },
        { label: "Exams", path: "/principal/exams", icon: Armchair },
        { label: "School Management", path: "/principal/school-management", icon: School },
      ],
    },
  ],
  teacher: [
    { label: "Dashboard", path: "/teacher", icon: LayoutGrid, end: true },
    { label: "Announcements", path: "/teacher/announcements", icon: Megaphone },
    { label: "Attendance", path: "/teacher/attendance", icon: ScanFace },
    { label: "Timetable", path: "/teacher/timetable", icon: CalendarClock },
    { label: "Doubts", path: "/teacher/doubts", icon: MessagesSquare },
    { label: "Assistant Bot", path: "/teacher/assistant", icon: Bot },
    {
      label: "Teaching",
      icon: BookOpen,
      children: [
        { label: "Classroom", path: "/teacher/classroom", icon: BookOpen },
        { label: "Resources", path: "/teacher/resources", icon: FolderKanban },
        { label: "Digital Library", path: "/teacher/library", icon: Library },
        { label: "Homework Calendar", path: "/teacher/calendar", icon: CalendarIcon },
      ],
    },
    {
      label: "Assessment",
      icon: GraduationCap,
      children: [
        { label: "Assignments", path: "/teacher/assignments", icon: ClipboardList },
        { label: "Quizzes", path: "/teacher/quizzes", icon: HelpCircle },
        { label: "Gradebook", path: "/teacher/gradebook", icon: GraduationCap },
        { label: "Report Cards", path: "/teacher/report-cards", icon: FileText },
        { label: "Bulk Remarks", path: "/teacher/remarks", icon: MessageSquare },
        { label: "Student Analytics", path: "/teacher/analytics", icon: TrendingUp },
      ],
    },
    {
      label: "School Ops",
      icon: Users,
      children: [
        { label: "Staffing", path: "/teacher/staffing", icon: Users },
        { label: "Syllabus", path: "/teacher/syllabus", icon: BookOpenCheck },
        { label: "Syllabus Pace", path: "/teacher/syllabus-pace", icon: Compass },
        { label: "Exam Duties", path: "/teacher/exams", icon: Armchair },
        { label: "Early-Warning", path: "/teacher/risk", icon: AlertTriangle },
        { label: "Fees", path: "/teacher/fees", icon: Wallet },
      ],
    },
  ],
  student: [
    { label: "Dashboard", path: "/student", icon: LayoutGrid, end: true },
    { label: "Announcements", path: "/student/announcements", icon: Megaphone },
    { label: "Doubt Bot", path: "/student/doubt-bot", icon: Bot },
    { label: "Doubts", path: "/student/doubts", icon: MessagesSquare },
    { label: "Assignments", path: "/student/assignments", icon: ClipboardList },
    { label: "Timetable", path: "/student/timetable", icon: CalendarClock },
    {
      label: "Learning",
      icon: BookOpen,
      children: [
        { label: "Classroom", path: "/student/classroom", icon: BookOpen },
        { label: "Resources", path: "/student/resources", icon: FolderKanban },
        { label: "Quizzes", path: "/student/quizzes", icon: HelpCircle },
        { label: "Digital Library", path: "/student/library", icon: Library },
        { label: "Homework Calendar", path: "/student/calendar", icon: CalendarIcon },
      ],
    },
    {
      label: "My Progress",
      icon: TrendingUp,
      children: [
        { label: "Gradebook", path: "/student/gradebook", icon: GraduationCap },
        { label: "Report Cards", path: "/student/report-cards", icon: FileText },
        { label: "My Analytics", path: "/student/analytics", icon: TrendingUp },
        { label: "Attendance", path: "/student/attendance", icon: ScanFace },
        { label: "Teacher Remarks", path: "/student/remarks", icon: MessageSquare },
        { label: "Exam Seats", path: "/student/exams", icon: Armchair },
      ],
    },
    { label: "Fees", path: "/student/fees", icon: Wallet },
  ],
  parent: [
    { label: "Dashboard", path: "/parent", icon: LayoutGrid, end: true },
    { label: "Announcements", path: "/parent/announcements", icon: Megaphone },
    { label: "My Child", path: "/parent/child", icon: UserIcon },
    { label: "Attendance", path: "/parent/attendance", icon: ScanFace },
    { label: "Ask", path: "/parent/bot", icon: Bot },
    { label: "Resources", path: "/parent/resources", icon: FolderKanban },
    { label: "Assignments", path: "/parent/assignments", icon: ClipboardList },
    { label: "Gradebook", path: "/parent/gradebook", icon: GraduationCap },
    { label: "Report Cards", path: "/parent/report-cards", icon: FileText },
    { label: "Homework Calendar", path: "/parent/calendar", icon: CalendarIcon },
    { label: "Child Analytics", path: "/parent/analytics", icon: TrendingUp },
    { label: "Teacher Remarks", path: "/parent/remarks", icon: MessageSquare },
    { label: "Timetable", path: "/parent/timetable", icon: CalendarClock },
    { label: "Early-Warning", path: "/parent/risk", icon: AlertTriangle },
    { label: "Fees", path: "/parent/fees", icon: Wallet },
  ],
};

export const ROLE_LABEL: Record<Role, string> = {
  admin: "Admin",
  principal: "Principal",
  teacher: "Teacher",
  student: "Student",
  parent: "Parent",
};

export { UserIcon };
