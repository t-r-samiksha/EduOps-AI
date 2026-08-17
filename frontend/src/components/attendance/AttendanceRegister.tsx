import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CalendarDays,
  Check,
  ChevronLeft,
  ChevronRight,
  Download,
  Loader2,
  RotateCcw,
  Save,
  UserCheck,
  UserX,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import Field from "@/components/ui/field";
import StatTile from "@/components/shared/StatTile";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useAttendanceRegister, useMarkManualAttendance } from "@/api/hooks/useAttendance";
import { ApiError } from "@/api/client";
import { DAY_LABELS } from "@/lib/constants";
import { csvFilename, downloadCsv, toCsv } from "@/lib/csv";
import type { AttendanceStatus, RegisterCell, RegisterPeriod, RegisterStudent } from "@/api/types";
import { cn } from "@/lib/utils";

/** Click order for a cell. An unmarked cell also cycles back to unmarked;
 * a cell that already has a saved record cannot be returned to unmarked,
 * because the API has no "delete this record" operation - only a status
 * change. Discarding unsaved edits is what the Discard button is for. */
const CYCLE: AttendanceStatus[] = ["present", "absent", "late"];

const STATUS_LETTER: Record<AttendanceStatus, string> = { present: "P", absent: "A", late: "L" };
const STATUS_LABEL: Record<AttendanceStatus, string> = { present: "Present", absent: "Absent", late: "Late" };
const STATUS_CELL: Record<AttendanceStatus, string> = {
  present: "border-positive/40 bg-positive/15 text-positive",
  absent: "border-urgent/40 bg-urgent/15 text-urgent",
  late: "border-warning/40 bg-warning/15 text-warning",
};
const UNMARKED_CELL = "border-dashed border-border bg-elevated/40 text-ink-faint";

/** Keys that set a status directly, so a teacher can run down a column without
 * ever touching the mouse. */
const KEY_TO_STATUS: Record<string, AttendanceStatus> = { p: "present", a: "absent", l: "late" };

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

function shiftIso(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00`);
  d.setDate(d.getDate() + days);
  return d.toISOString().slice(0, 10);
}

function cellKey(studentId: number, slotId: number): string {
  return `${studentId}:${slotId}`;
}

function periodLabel(period: RegisterPeriod): string {
  return `P${period.period_number} ${period.subject_name}`;
}

/** Grid-shaped table rather than the shared <Table>: this one needs a sticky
 * header row AND a sticky student-name column inside a height-capped scroll
 * container, which the shared component (x-scroll only, no max height) can't
 * express. Cell classes are kept in step with it so the two look identical. */
const TH = "h-9 px-3 text-left align-middle font-mono text-[0.6875rem] font-medium uppercase tracking-wide text-ink-muted";

export default function AttendanceRegister({ schoolId }: { schoolId: number }) {
  const lookup = useReferenceLookup(schoolId);
  const [classId, setClassId] = useState<string>("");
  const [date, setDate] = useState<string>(todayIso);
  const register = useAttendanceRegister({ classId: classId ? Number(classId) : undefined, date });
  const save = useMarkManualAttendance();

  /** Local, unsaved status overrides keyed `studentId:slotId`. A key present
   * here always differs from the saved value - setCell drops the key when an
   * edit lands back on what the server already has, so the dirty count never
   * over-reports. */
  const [edits, setEdits] = useState<Record<string, AttendanceStatus>>({});
  const [focus, setFocus] = useState<{ r: number; c: number } | null>(null);
  const cellRefs = useRef<Map<string, HTMLButtonElement | null>>(new Map());

  const classes = useMemo(
    () => [...(lookup.data?.classes ?? [])].sort((a, b) => a.name.localeCompare(b.name)),
    [lookup.data]
  );

  // Land on a real class straight away rather than an empty screen.
  useEffect(() => {
    if (!classId && classes.length > 0) setClassId(String(classes[0].id));
  }, [classId, classes]);

  // Switching class or day invalidates every pending edit - they were keyed to
  // the previous grid's slots.
  useEffect(() => {
    setEdits({});
    setFocus(null);
  }, [classId, date]);

  const data = register.data;
  const periods = data?.periods ?? [];
  const students = data?.students ?? [];
  const dirtyCount = Object.keys(edits).length;

  const effectiveStatus = useCallback(
    (studentId: number, cell: RegisterCell): AttendanceStatus | null =>
      edits[cellKey(studentId, cell.timetable_slot_id)] ?? cell.status,
    [edits]
  );

  const setCell = useCallback((studentId: number, cell: RegisterCell, next: AttendanceStatus | null) => {
    setEdits((prev) => {
      const key = cellKey(studentId, cell.timetable_slot_id);
      const copy = { ...prev };
      if (next === null || next === cell.status) delete copy[key];
      else copy[key] = next;
      return copy;
    });
  }, []);

  const cycleCell = useCallback(
    (student: RegisterStudent, cell: RegisterCell) => {
      const current = effectiveStatus(student.student_id, cell);
      if (current === null) return setCell(student.student_id, cell, CYCLE[0]);
      const idx = CYCLE.indexOf(current);
      const atEnd = idx === CYCLE.length - 1;
      // Only a cell with no saved record can cycle back to unmarked.
      const next = atEnd ? (cell.status === null ? null : CYCLE[0]) : CYCLE[idx + 1];
      setCell(student.student_id, cell, next);
    },
    [effectiveStatus, setCell]
  );

  const moveFocus = useCallback(
    (r: number, c: number) => {
      const row = Math.max(0, Math.min(students.length - 1, r));
      const col = Math.max(0, Math.min(periods.length - 1, c));
      setFocus({ r: row, c: col });
      cellRefs.current.get(`${row}-${col}`)?.focus();
    },
    [periods.length, students.length]
  );

  function handleCellKeyDown(event: React.KeyboardEvent, r: number, c: number) {
    const student = students[r];
    const cell = student?.cells[c];
    if (!student || !cell) return;
    const key = event.key.toLowerCase();

    if (key in KEY_TO_STATUS) {
      event.preventDefault();
      setCell(student.student_id, cell, KEY_TO_STATUS[key]);
      // Auto-advance down the column: marking a class is a vertical sweep.
      moveFocus(r + 1, c);
      return;
    }
    switch (event.key) {
      case "ArrowDown":
      case "ArrowUp":
      case "ArrowLeft":
      case "ArrowRight":
        event.preventDefault();
        moveFocus(
          r + (event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0),
          c + (event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0)
        );
        return;
      case "Enter":
      case " ":
        event.preventDefault();
        cycleCell(student, cell);
        return;
      case "Backspace":
      case "Delete":
        event.preventDefault();
        setCell(student.student_id, cell, null);
        return;
      default:
    }
  }

  /** Bulk fill. `onlyUnmarked` is the one that matters after a camera run: the
   * students the CV never saw are exactly the absentees. */
  function fill(status: AttendanceStatus, opts: { onlyUnmarked?: boolean; slotId?: number } = {}) {
    setEdits((prev) => {
      const copy = { ...prev };
      for (const student of students) {
        for (const cell of student.cells) {
          if (opts.slotId !== undefined && cell.timetable_slot_id !== opts.slotId) continue;
          const current = copy[cellKey(student.student_id, cell.timetable_slot_id)] ?? cell.status;
          if (opts.onlyUnmarked && current !== null) continue;
          const key = cellKey(student.student_id, cell.timetable_slot_id);
          if (status === cell.status) delete copy[key];
          else copy[key] = status;
        }
      }
      return copy;
    });
  }

  function handleSave() {
    if (!classId || dirtyCount === 0) return;
    const entries = Object.entries(edits).map(([key, status]) => {
      const [studentId, slotId] = key.split(":").map(Number);
      return { student_id: studentId, timetable_slot_id: slotId, status };
    });
    save.mutate({ classId: Number(classId), date, entries }, { onSuccess: () => setEdits({}) });
  }

  // A teacher who marked 30 students and navigated away without saving would
  // lose the lot silently.
  useEffect(() => {
    if (dirtyCount === 0) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirtyCount]);

  function handleExport() {
    if (!data) return;
    const headers = ["Student", ...periods.map(periodLabel), "Present", "Absent", "Late", "Unmarked", "Present %"];
    const rows = data.students.map((student) => [
      student.name,
      ...student.cells.map((cell) => {
        const status = effectiveStatus(student.student_id, cell);
        return status ? STATUS_LABEL[status] : "";
      }),
      student.present_count,
      student.absent_count,
      student.late_count,
      student.unmarked_count,
      student.present_pct,
    ]);
    downloadCsv(
      csvFilename("attendance", data.class_name, data.date),
      toCsv(headers, rows)
    );
  }

  const unmarkedPeriods = periods.filter((p) => !p.is_marked);
  const isToday = date === todayIso();

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>Day register</CardTitle>
          <CardDescription>
            Every period of one class on one day. Click a cell to cycle it, or focus the grid and press{" "}
            <kbd className="rounded border border-border bg-elevated px-1 font-mono text-[0.6875rem]">P</kbd>{" "}
            <kbd className="rounded border border-border bg-elevated px-1 font-mono text-[0.6875rem]">A</kbd>{" "}
            <kbd className="rounded border border-border bg-elevated px-1 font-mono text-[0.6875rem]">L</kbd> to mark
            and jump to the next student. Nothing is sent until you press Save.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Class" className="min-w-56">
              <Select value={classId} onValueChange={setClassId}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a class" />
                </SelectTrigger>
                <SelectContent>
                  {classes.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Field label="Date">
              <div className="flex items-center gap-1.5">
                <Button
                  variant="outline"
                  size="icon"
                  className="h-10 w-9 shrink-0"
                  aria-label="Previous day"
                  onClick={() => setDate((d) => shiftIso(d, -1))}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="w-40" />
                <Button
                  variant="outline"
                  size="icon"
                  className="h-10 w-9 shrink-0"
                  aria-label="Next day"
                  onClick={() => setDate((d) => shiftIso(d, 1))}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="sm" disabled={isToday} onClick={() => setDate(todayIso())}>
                  <CalendarDays className="h-3.5 w-3.5" /> Today
                </Button>
              </div>
            </Field>
            {data && (
              <span className="pb-2.5 text-xs text-ink-muted">
                {DAY_LABELS[data.day_of_week]} · {data.class_name}
                {data.section ? ` · Section ${data.section}` : ""}
              </span>
            )}
          </div>

          {data && (
            <div className="flex flex-wrap gap-3">
              <StatTile
                label="Present"
                value={`${data.totals.present_pct.toFixed(1)}%`}
                caption={`${data.totals.present_cells} of ${data.totals.present_cells + data.totals.absent_cells + data.totals.late_cells} marked cells`}
                icon={UserCheck}
                tone={data.totals.present_pct >= 90 ? "positive" : data.totals.present_pct >= 75 ? "warning" : "urgent"}
              />
              <StatTile label="Students" value={data.totals.roster_size} caption="on the roster" />
              <StatTile
                label="Absences"
                value={data.totals.absent_cells}
                caption={`${data.totals.late_cells} late`}
                icon={UserX}
                tone={data.totals.absent_cells > 0 ? "urgent" : "neutral"}
              />
              <StatTile
                label="Periods marked"
                value={`${data.totals.marked_periods}/${data.totals.period_count}`}
                caption={data.totals.unmarked_periods > 0 ? `${data.totals.unmarked_periods} not marked yet` : "all done"}
                icon={AlertTriangle}
                tone={data.totals.unmarked_periods > 0 ? "warning" : "positive"}
                emphasize={data.totals.unmarked_periods > 0}
              />
            </div>
          )}

          {unmarkedPeriods.length > 0 && (
            <div className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/5 px-3.5 py-2.5 text-xs text-warning">
              <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                No attendance recorded at all for{" "}
                <span className="font-medium">
                  {unmarkedPeriods.map((p) => `P${p.period_number} ${p.subject_name}`).join(", ")}
                </span>
                . An unmarked period is not the same as everyone being absent — mark it so the numbers mean something.
              </span>
            </div>
          )}
        </CardContent>
      </Card>

      {register.isError && (
        <Card>
          <CardContent className="py-6">
            <p className="text-sm text-urgent">
              {register.error instanceof ApiError ? register.error.message : "Could not load the register."}
            </p>
          </CardContent>
        </Card>
      )}
      {register.isLoading && <div className="h-64 animate-pulse rounded-2xl bg-elevated/60" />}

      {data && periods.length === 0 && (
        <Card>
          <CardContent className="py-6">
            <p className="text-sm text-ink-muted">
              No periods are scheduled for {data.class_name} on {DAY_LABELS[data.day_of_week]}, {data.date}. Pick
              another date, or generate a timetable for this class first.
            </p>
          </CardContent>
        </Card>
      )}

      {data && periods.length > 0 && (
        <Card>
          <CardHeader className="gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <CardTitle>
                {data.class_name} · {data.date}
              </CardTitle>
              <div className="flex flex-wrap items-center gap-1.5">
                <Button variant="outline" size="sm" onClick={() => fill("present")}>
                  <Check className="h-3.5 w-3.5" /> All present
                </Button>
                <Button variant="outline" size="sm" onClick={() => fill("absent", { onlyUnmarked: true })}>
                  <UserX className="h-3.5 w-3.5" /> Unmarked → absent
                </Button>
                <Button variant="ghost" size="sm" disabled={dirtyCount === 0} onClick={() => setEdits({})}>
                  <RotateCcw className="h-3.5 w-3.5" /> Discard
                </Button>
                <Button variant="outline" size="sm" onClick={handleExport}>
                  <Download className="h-3.5 w-3.5" /> CSV
                </Button>
              </div>
            </div>
            <CardDescription className="flex flex-wrap items-center gap-2">
              <span className="flex items-center gap-1.5">
                <span className={cn("flex h-5 w-5 items-center justify-center rounded border text-[0.625rem] font-bold", STATUS_CELL.present)}>P</span>
                present
              </span>
              <span className="flex items-center gap-1.5">
                <span className={cn("flex h-5 w-5 items-center justify-center rounded border text-[0.625rem] font-bold", STATUS_CELL.absent)}>A</span>
                absent
              </span>
              <span className="flex items-center gap-1.5">
                <span className={cn("flex h-5 w-5 items-center justify-center rounded border text-[0.625rem] font-bold", STATUS_CELL.late)}>L</span>
                late
              </span>
              <span className="flex items-center gap-1.5">
                <span className={cn("flex h-5 w-5 items-center justify-center rounded border text-[0.625rem]", UNMARKED_CELL)}>·</span>
                not marked
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-urgent" /> low-confidence camera match, unreviewed
              </span>
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            <div className="max-h-[65vh] overflow-auto rounded-2xl border border-border">
              <table className="w-full caption-bottom border-separate border-spacing-0 text-sm">
                <thead>
                  <tr>
                    <th className={cn(TH, "sticky left-0 top-0 z-30 min-w-44 border-b border-border bg-elevated")}>
                      Student
                    </th>
                    {periods.map((period) => (
                      <th
                        key={period.timetable_slot_id}
                        className={cn(TH, "sticky top-0 z-20 border-b border-border bg-elevated text-center")}
                      >
                        <div className="flex flex-col items-center gap-0.5 py-1">
                          <span className="text-xs font-semibold normal-case tracking-normal text-ink">
                            P{period.period_number}
                          </span>
                          <span className="max-w-24 truncate normal-case tracking-normal" title={`${period.subject_name} · ${period.teacher_name}`}>
                            {period.subject_name}
                          </span>
                          <span className="tabular-nums">{period.start_time.slice(0, 5)}</span>
                          {!period.is_marked && <Badge variant="warning">unmarked</Badge>}
                          <span className="flex items-center gap-0.5">
                            <button
                              type="button"
                              title={`Mark every student present in P${period.period_number}`}
                              onClick={() => fill("present", { slotId: period.timetable_slot_id })}
                              className="rounded p-0.5 text-positive hover:bg-positive/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              <UserCheck className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              title={`Mark unmarked students absent in P${period.period_number}`}
                              onClick={() => fill("absent", { slotId: period.timetable_slot_id, onlyUnmarked: true })}
                              className="rounded p-0.5 text-urgent hover:bg-urgent/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                            >
                              <UserX className="h-3.5 w-3.5" />
                            </button>
                          </span>
                        </div>
                      </th>
                    ))}
                    <th className={cn(TH, "sticky top-0 z-20 border-b border-border bg-elevated text-center")}>%</th>
                  </tr>
                </thead>
                <tbody>
                  {students.map((student, r) => {
                    const marked = student.cells
                      .map((cell) => effectiveStatus(student.student_id, cell))
                      .filter((s): s is AttendanceStatus => s !== null);
                    const presentNow = marked.filter((s) => s === "present").length;
                    const pctNow = marked.length ? (100 * presentNow) / marked.length : 0;
                    return (
                      <tr key={student.student_id} className="hover:bg-elevated/40">
                        <td className="sticky left-0 z-10 border-b border-border bg-card px-3 py-1.5 font-medium">
                          <span className="flex items-center gap-2">
                            <span className="w-5 text-right font-mono text-[0.6875rem] text-ink-faint">{r + 1}</span>
                            <span className="truncate">{student.name}</span>
                          </span>
                        </td>
                        {student.cells.map((cell, c) => {
                          const status = effectiveStatus(student.student_id, cell);
                          const key = cellKey(student.student_id, cell.timetable_slot_id);
                          const isDirty = edits[key] !== undefined;
                          const isTabStop = focus ? focus.r === r && focus.c === c : r === 0 && c === 0;
                          const period = periods[c];
                          const title = [
                            `${student.name} · P${period.period_number} ${period.subject_name}`,
                            status ? STATUS_LABEL[status] : "Not marked",
                            cell.source ? `source: ${cell.source}` : null,
                            cell.confidence_score !== null
                              ? `confidence ${(cell.confidence_score * 100).toFixed(1)}%`
                              : null,
                            cell.reviewed_by_name ? `reviewed by ${cell.reviewed_by_name}` : null,
                            isDirty ? "unsaved change" : null,
                          ]
                            .filter(Boolean)
                            .join(" · ");
                          return (
                            <td key={cell.timetable_slot_id} className="border-b border-border p-1 text-center">
                              <button
                                type="button"
                                ref={(node) => cellRefs.current.set(`${r}-${c}`, node)}
                                tabIndex={isTabStop ? 0 : -1}
                                title={title}
                                aria-label={title}
                                onFocus={() => setFocus({ r, c })}
                                onClick={() => cycleCell(student, cell)}
                                onKeyDown={(e) => handleCellKeyDown(e, r, c)}
                                className={cn(
                                  "relative h-8 w-9 rounded-lg border text-xs font-bold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                                  status ? STATUS_CELL[status] : UNMARKED_CELL,
                                  isDirty && "ring-2 ring-accent ring-offset-1 ring-offset-card"
                                )}
                              >
                                {status ? STATUS_LETTER[status] : "·"}
                                {cell.needs_review && (
                                  <span className="absolute right-0.5 top-0.5 h-1.5 w-1.5 rounded-full bg-urgent" />
                                )}
                              </button>
                            </td>
                          );
                        })}
                        <td className="border-b border-border px-3 py-1.5 text-center">
                          <Badge
                            variant={pctNow >= 90 ? "positive" : pctNow >= 75 ? "neutral" : "urgent"}
                            className="font-mono tabular-nums"
                          >
                            {marked.length ? `${pctNow.toFixed(0)}%` : "—"}
                          </Badge>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
                <tfoot>
                  <tr>
                    <td className={cn(TH, "sticky left-0 z-10 bg-elevated")}>Present</td>
                    {periods.map((period, c) => {
                      const present = students.filter(
                        (s) => effectiveStatus(s.student_id, s.cells[c]) === "present"
                      ).length;
                      return (
                        <td
                          key={period.timetable_slot_id}
                          className="bg-elevated px-1 py-2 text-center font-mono text-[0.6875rem] tabular-nums text-ink-muted"
                        >
                          {present}/{students.length}
                        </td>
                      );
                    })}
                    <td className="bg-elevated" />
                  </tr>
                </tfoot>
              </table>
            </div>

            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs text-ink-muted">
                {dirtyCount === 0 ? (
                  "No unsaved changes."
                ) : (
                  <span className="font-medium text-accent">
                    {dirtyCount} unsaved change{dirtyCount === 1 ? "" : "s"}
                  </span>
                )}
                {save.isSuccess && dirtyCount === 0 && (
                  <span className="ml-2 text-positive">
                    Saved · {save.data.created} created, {save.data.updated} updated
                    {save.data.unchanged > 0 ? `, ${save.data.unchanged} already correct` : ""}
                  </span>
                )}
              </span>
              <Button onClick={handleSave} disabled={dirtyCount === 0 || save.isPending}>
                {save.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
                {save.isPending ? "Saving…" : `Save ${dirtyCount || ""}`.trim()}
              </Button>
            </div>
            {save.isError && (
              <p className="text-sm text-urgent">
                {save.error instanceof ApiError ? save.error.message : "Could not save attendance."}
              </p>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
