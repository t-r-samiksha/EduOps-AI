import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  Armchair,
  Bot,
  BookOpenCheck,
  CalendarClock,
  ClipboardList,
  FileCheck2,
  LayoutGrid,
  School,
  ScanText,
  ScanFace,
  Users,
  Wallet,
  User as UserIcon,
} from "lucide-react";
import type { Role } from "@/store/authStore";

export interface NavItem {
  label: string;
  path: string;
  icon: LucideIcon;
  end?: boolean;
}

export const NAV_ITEMS: Record<Role, NavItem[]> = {
  admin: [
    { label: "Command Center", path: "/admin", icon: LayoutGrid, end: true },
    { label: "Timetable", path: "/admin/timetable", icon: CalendarClock },
    { label: "Attendance", path: "/admin/attendance", icon: ScanFace },
    { label: "Staffing", path: "/admin/staffing", icon: Users },
    { label: "Early-Warning", path: "/admin/risk", icon: AlertTriangle },
    { label: "Syllabus", path: "/admin/syllabus", icon: BookOpenCheck },
    { label: "Approvals", path: "/admin/approvals", icon: FileCheck2 },
    { label: "Document OCR", path: "/admin/ocr", icon: ScanText },
    { label: "Fees", path: "/admin/fees", icon: Wallet },
    { label: "Admissions", path: "/admin/admissions", icon: ClipboardList },
    { label: "Exams", path: "/admin/exams", icon: Armchair },
    { label: "School Management", path: "/admin/school-management", icon: School },
  ],
  principal: [
    { label: "Dashboard", path: "/principal", icon: LayoutGrid, end: true },
    { label: "Timetable", path: "/principal/timetable", icon: CalendarClock },
    { label: "Staffing", path: "/principal/staffing", icon: Users },
    { label: "Early-Warning", path: "/principal/risk", icon: AlertTriangle },
    { label: "Syllabus", path: "/principal/syllabus", icon: BookOpenCheck },
    { label: "Approvals", path: "/principal/approvals", icon: FileCheck2 },
    { label: "Document OCR", path: "/principal/ocr", icon: ScanText },
    { label: "Fees", path: "/principal/fees", icon: Wallet },
    { label: "Admissions", path: "/principal/admissions", icon: ClipboardList },
    { label: "Exams", path: "/principal/exams", icon: Armchair },
    { label: "School Management", path: "/principal/school-management", icon: School },
  ],
  teacher: [
    { label: "Dashboard", path: "/teacher", icon: LayoutGrid, end: true },
    { label: "Timetable", path: "/teacher/timetable", icon: CalendarClock },
    { label: "Attendance", path: "/teacher/attendance", icon: ScanFace },
    { label: "Staffing", path: "/teacher/staffing", icon: Users },
    { label: "Early-Warning", path: "/teacher/risk", icon: AlertTriangle },
    { label: "Syllabus", path: "/teacher/syllabus", icon: BookOpenCheck },
    { label: "Fees", path: "/teacher/fees", icon: Wallet },
    { label: "Exam Duties", path: "/teacher/exams", icon: Armchair },
  ],
  student: [
    { label: "Dashboard", path: "/student", icon: LayoutGrid, end: true },
    { label: "Doubt Bot", path: "/student/doubt-bot", icon: Bot },
    { label: "Timetable", path: "/student/timetable", icon: CalendarClock },
    { label: "Fees", path: "/student/fees", icon: Wallet },
    { label: "Exam Seats", path: "/student/exams", icon: Armchair },
  ],
  parent: [
    { label: "Dashboard", path: "/parent", icon: LayoutGrid, end: true },
    { label: "My Child", path: "/parent/child", icon: UserIcon },
    { label: "Ask", path: "/parent/bot", icon: Bot },
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
