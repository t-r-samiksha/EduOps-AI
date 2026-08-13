import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  BookOpenCheck,
  CalendarClock,
  FileCheck2,
  LayoutGrid,
  ScanFace,
  Users,
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
  ],
  principal: [
    { label: "Dashboard", path: "/principal", icon: LayoutGrid, end: true },
    { label: "Timetable", path: "/principal/timetable", icon: CalendarClock },
    { label: "Staffing", path: "/principal/staffing", icon: Users },
    { label: "Early-Warning", path: "/principal/risk", icon: AlertTriangle },
    { label: "Syllabus", path: "/principal/syllabus", icon: BookOpenCheck },
    { label: "Approvals", path: "/principal/approvals", icon: FileCheck2 },
  ],
  teacher: [
    { label: "Dashboard", path: "/teacher", icon: LayoutGrid, end: true },
    { label: "Timetable", path: "/teacher/timetable", icon: CalendarClock },
    { label: "Attendance", path: "/teacher/attendance", icon: ScanFace },
    { label: "Staffing", path: "/teacher/staffing", icon: Users },
    { label: "Early-Warning", path: "/teacher/risk", icon: AlertTriangle },
    { label: "Syllabus", path: "/teacher/syllabus", icon: BookOpenCheck },
  ],
  student: [
    { label: "Dashboard", path: "/student", icon: LayoutGrid, end: true },
    { label: "Timetable", path: "/student/timetable", icon: CalendarClock },
  ],
  parent: [
    { label: "Dashboard", path: "/parent", icon: LayoutGrid, end: true },
    { label: "Timetable", path: "/parent/timetable", icon: CalendarClock },
    { label: "Early-Warning", path: "/parent/risk", icon: AlertTriangle },
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
