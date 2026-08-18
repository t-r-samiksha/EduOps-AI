import { useMemo, useState } from "react";
import { Search, Users } from "lucide-react";
import { Input } from "@/components/ui/input";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useReferenceLookup, type LookupClass } from "@/api/hooks/useTimetable";
import { useClassRoster } from "@/api/hooks/useClassRoster";
import { gradeLevelDisplay } from "@/lib/format";

/** "Grade 3 - B", or the class's own name when it carries no grade level. */
export function classLabel(c: LookupClass): string {
  if (c.grade_level == null) return c.name;
  const grade = c.grade_label ?? gradeLevelDisplay(String(c.grade_level));
  return c.section ? `${grade} - ${c.section}` : grade;
}

/** Classes sorted the way a human reads a school: youngest grade first, then section. */
export function sortClasses(classes: LookupClass[]): LookupClass[] {
  return [...classes].sort((a, b) => {
    const ga = a.grade_level ?? Number.MAX_SAFE_INTEGER;
    const gb = b.grade_level ?? Number.MAX_SAFE_INTEGER;
    if (ga !== gb) return ga - gb;
    return (a.section ?? "").localeCompare(b.section ?? "");
  });
}

/** Just the class half of the picker, for pages that select a whole section rather than
 *  one student (bulk remarks, the gradebook grid, report card generation). */
export function ClassSelect({
  value,
  onChange,
  classes,
  placeholder = "Select class…",
  className = "",
  includeAllOption = false,
}: {
  value: number | "";
  onChange: (classId: number | "") => void;
  classes: LookupClass[];
  placeholder?: string;
  className?: string;
  includeAllOption?: boolean;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : "")}
      className={`rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-primary ${className}`}
    >
      <option value="">{includeAllOption ? "All classes" : placeholder}</option>
      {sortClasses(classes).map((c) => (
        <option key={c.id} value={c.id}>
          {classLabel(c)}
        </option>
      ))}
    </select>
  );
}

/**
 * Pick a student by CLASS then NAME - never by typing a database id.
 *
 * WHY. The library's issue-book dialog asked staff to type a numeric "Student ID" into a
 * number input, prefilled with `2`. Nobody in a school office knows a student's database
 * id, so the realistic outcomes were issuing a book to whichever student happens to be
 * row 2 or giving up. (There is no roll-number column in this schema either, so name
 * within a section is the only identity a human actually has.) The same "which student?"
 * problem shows up on Student Analytics and the remarks grid, so the control is shared.
 *
 * Two steps, because a school-wide flat list of every student is unusable past a few
 * dozen: choose the section, then filter that roster by name. The search box only appears
 * once a class is chosen and its roster is big enough to need it.
 */
export default function StudentPicker({
  classId,
  studentId,
  onClassChange,
  onStudentChange,
  classes: classesProp,
  label,
}: {
  classId: number | "";
  studentId: number | "";
  onClassChange: (classId: number | "") => void;
  onStudentChange: (studentId: number | "") => void;
  /** Restrict selectable classes (e.g. only the ones a teacher teaches). Defaults to
   *  every class in the caller's school. */
  classes?: LookupClass[];
  label?: string;
}) {
  const schoolId = useCurrentUser().data?.school_id;
  const lookup = useReferenceLookup(schoolId);
  const classes = classesProp ?? lookup.data?.classes ?? [];

  const roster = useClassRoster(typeof classId === "number" ? classId : undefined);
  const [search, setSearch] = useState("");

  const students = roster.data?.students ?? [];
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return students;
    return students.filter((s) => s.name.toLowerCase().includes(q));
  }, [students, search]);

  return (
    <div className="flex flex-col gap-2">
      {label && <span className="text-xs font-semibold text-foreground">{label}</span>}

      <ClassSelect
        value={classId}
        onChange={(next) => {
          onClassChange(next);
          // The previously-picked student is almost certainly not in the new section, and
          // silently keeping them would issue/record against the wrong class.
          onStudentChange("");
          setSearch("");
        }}
        classes={classes}
        className="w-full"
      />

      {typeof classId === "number" && (
        <>
          {students.length > 8 && (
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search by name…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8 text-xs"
              />
            </div>
          )}

          {roster.isLoading ? (
            <p className="py-2 text-xs text-muted-foreground">Loading students…</p>
          ) : students.length === 0 ? (
            <p className="flex items-center gap-1.5 py-2 text-xs text-muted-foreground">
              <Users className="h-3.5 w-3.5" />
              No students enrolled in this section.
            </p>
          ) : (
            <select
              value={studentId}
              onChange={(e) => onStudentChange(e.target.value ? Number(e.target.value) : "")}
              className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="">
                {filtered.length === 0 ? "No match for that name" : "Select student…"}
              </option>
              {filtered.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.name}
                  {s.is_primary ? "" : " (elective)"}
                </option>
              ))}
            </select>
          )}
        </>
      )}
    </div>
  );
}
