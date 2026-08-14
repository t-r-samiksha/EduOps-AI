import { useMemo, useState } from "react";
import type { DragEvent } from "react";
import { AlertTriangle, GripVertical, Loader2, Undo2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { TimetableSlot, TimetableUpdateConflict } from "@/api/types";
import type { LookupResponse } from "@/api/hooks/useTimetable";
import { useUpdateTimetableSlot } from "@/api/hooks/useTimetable";
import { DAY_LABELS } from "@/lib/constants";
import { subjectChipVar } from "@/lib/subjectColor";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/utils";

interface TimetableGridProps {
  slots: TimetableSlot[];
  lookup?: LookupResponse;
  /** Show the class name on each chip — useful for an unfiltered "all classes" admin view. */
  showClass?: boolean;
  /** Enables real drag-and-drop editing via PUT /timetable/update. Gate this on
   * role at the call site (admin/principal) — the backend independently 403s
   * every other role regardless of what this prop is set to, so a wrong value
   * here is a UX annoyance, not a security hole. */
  editable?: boolean;
}

function toMinutes(time: string): number {
  const [h, m] = time.split(":").map(Number);
  return h * 60 + m;
}

interface ConflictState {
  slotId: number;
  label: string;
  targetDay: number;
  targetPeriod: number;
  conflicts: TimetableUpdateConflict[];
}

interface UndoState {
  slotId: number;
  label: string;
  fromDay: number;
  fromPeriod: number;
  toDay: number;
  toPeriod: number;
}

interface MoveErrorState {
  slotId: number;
  label: string;
  message: string;
}

export default function TimetableGrid({ slots, lookup, showClass, editable = false }: TimetableGridProps) {
  const subjectNames = useMemo(() => new Map(lookup?.subjects.map((s) => [s.id, s.name])), [lookup]);
  const teacherNames = useMemo(() => new Map(lookup?.teachers.map((t) => [t.id, t.name])), [lookup]);
  const roomNames = useMemo(() => new Map(lookup?.rooms.map((r) => [r.id, r.name])), [lookup]);
  const classNames = useMemo(() => new Map(lookup?.classes.map((c) => [c.id, c.name])), [lookup]);

  const days = useMemo(() => {
    const present = new Set(slots.map((s) => s.day_of_week));
    const range = present.size ? Math.max(...present, 4) : 4;
    return Array.from({ length: Math.min(range + 1, 6) }, (_, i) => i);
  }, [slots]);

  const periods = useMemo(() => {
    const byNumber = new Map<number, { start: string; end: string }>();
    for (const s of slots) {
      if (!byNumber.has(s.period_number)) byNumber.set(s.period_number, { start: s.start_time, end: s.end_time });
    }
    return Array.from(byNumber.entries())
      .sort(([a], [b]) => a - b)
      .map(([number, times]) => ({ number, ...times }));
  }, [slots]);

  const now = new Date();
  const todayDow = (now.getDay() + 6) % 7; // convert JS Sunday=0 to Monday=0 convention
  const nowMinutes = now.getHours() * 60 + now.getMinutes();

  const updateSlot = useUpdateTimetableSlot();
  const [draggedSlot, setDraggedSlot] = useState<TimetableSlot | null>(null);
  const [dragOverCell, setDragOverCell] = useState<{ day: number; period: number } | null>(null);
  const [pendingSlotId, setPendingSlotId] = useState<number | null>(null);
  const [conflictState, setConflictState] = useState<ConflictState | null>(null);
  const [undoState, setUndoState] = useState<UndoState | null>(null);
  const [moveErrorState, setMoveErrorState] = useState<MoveErrorState | null>(null);

  const slotLabel = (slot: { subject_id: number; class_id: number }) =>
    `${subjectNames.get(slot.subject_id) ?? `Subject #${slot.subject_id}`} · ${classNames.get(slot.class_id) ?? `Class #${slot.class_id}`}`;

  const dayPeriodLabel = (day: number, period: number) => `${DAY_LABELS[day] ?? `Day ${day}`} · Period ${period + 1}`;

  /** Client-side-only pre-check using the currently-loaded slot list, purely for
   * a responsive drop-zone warning WHILE dragging. This is NOT the real conflict
   * check — the server re-checks authoritatively on drop (see PUT /timetable/update's
   * real behavior below) and is the only source of truth for whether a move
   * actually succeeds. This pre-check can also under-report: if the grid is
   * currently filtered to one class, slots for other classes aren't loaded
   * client-side, so a teacher/room conflict against a class outside the current
   * filter won't show a warning here even though the server would still catch it. */
  function liveConflicts(dragged: TimetableSlot, day: number, period: number): TimetableSlot[] {
    return slots.filter(
      (s) =>
        s.id !== dragged.id &&
        s.day_of_week === day &&
        s.period_number === period &&
        (s.teacher_id === dragged.teacher_id || s.room_id === dragged.room_id || s.class_id === dragged.class_id)
    );
  }

  function findSlot(id: number): TimetableSlot | undefined {
    return slots.find((s) => s.id === id);
  }

  function describeConflictingSlot(id: number): string {
    const s = findSlot(id);
    if (!s) return `slot #${id}`;
    return `${slotLabel(s)} (${dayPeriodLabel(s.day_of_week, s.period_number)})`;
  }

  function handleDragStart(e: DragEvent<HTMLDivElement>, slot: TimetableSlot) {
    if (!editable || pendingSlotId !== null) return;
    setDraggedSlot(slot);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(slot.id));
  }

  function handleDragEnd() {
    setDraggedSlot(null);
    setDragOverCell(null);
  }

  function handleCellDragOver(e: DragEvent<HTMLTableCellElement>, day: number, period: number) {
    if (!editable || !draggedSlot) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (dragOverCell?.day !== day || dragOverCell?.period !== period) {
      setDragOverCell({ day, period });
    }
  }

  function handleCellDrop(e: DragEvent<HTMLTableCellElement>, day: number, period: number) {
    if (!editable || !draggedSlot) return;
    e.preventDefault();
    const slot = draggedSlot;
    setDraggedSlot(null);
    setDragOverCell(null);

    if (day === slot.day_of_week && period === slot.period_number) return; // dropped back on itself - no-op

    setConflictState(null);
    setMoveErrorState(null);
    setUndoState(null);
    setPendingSlotId(slot.id);

    updateSlot.mutate(
      { slot_id: slot.id, day_of_week: day, period_number: period },
      {
        onSuccess: (result) => {
          setPendingSlotId(null);
          if (result.slot) {
            setUndoState({
              slotId: slot.id,
              label: slotLabel(slot),
              fromDay: slot.day_of_week,
              fromPeriod: slot.period_number,
              toDay: day,
              toPeriod: period,
            });
          } else {
            setConflictState({ slotId: slot.id, label: slotLabel(slot), targetDay: day, targetPeriod: period, conflicts: result.conflicts });
          }
        },
        onError: (err) => {
          setPendingSlotId(null);
          setMoveErrorState({ slotId: slot.id, label: slotLabel(slot), message: err instanceof ApiError ? err.message : "Failed to move slot." });
        },
      }
    );
  }

  function handleUndo() {
    if (!undoState) return;
    const { slotId, fromDay, fromPeriod, label } = undoState;
    setConflictState(null);
    setMoveErrorState(null);
    setPendingSlotId(slotId);

    updateSlot.mutate(
      { slot_id: slotId, day_of_week: fromDay, period_number: fromPeriod },
      {
        onSuccess: (result) => {
          setPendingSlotId(null);
          setUndoState(null);
          if (!result.slot) {
            // Moving back to the vacated spot conflicted for real (e.g. something
            // else was scheduled into it in the meantime) - surface it honestly
            // rather than pretending the undo worked.
            setConflictState({ slotId, label, targetDay: fromDay, targetPeriod: fromPeriod, conflicts: result.conflicts });
          }
        },
        onError: (err) => {
          setPendingSlotId(null);
          setUndoState(null);
          setMoveErrorState({ slotId, label, message: err instanceof ApiError ? err.message : "Failed to undo move." });
        },
      }
    );
  }

  if (periods.length === 0) {
    return (
      <div className="flex flex-col items-center gap-1 rounded-2xl border border-dashed border-border px-6 py-8 text-center">
        <p className="font-display text-sm font-medium text-ink">No active timetable slots</p>
        <p className="max-w-xs text-xs text-ink-muted">
          Nothing has been generated for this scope yet — run <code className="font-mono">POST /timetable/generate</code> for this class/academic year.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {conflictState && (
        <div className="flex items-start gap-2.5 rounded-2xl border border-urgent/30 bg-urgent/5 px-4 py-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-urgent" />
          <div className="min-w-0 flex-1">
            <p className="font-medium text-ink">
              Couldn't move <span className="font-semibold">{conflictState.label}</span> to {dayPeriodLabel(conflictState.targetDay, conflictState.targetPeriod)} — left untouched.
            </p>
            <ul className="mt-1.5 flex flex-col gap-1">
              {conflictState.conflicts.map((c, i) => (
                <li key={i} className="flex flex-wrap items-center gap-1.5 text-ink-muted">
                  <Badge variant="urgent">{c.type}</Badge>
                  <span>{c.message} — clashes with {describeConflictingSlot(c.conflicting_slot_id)}.</span>
                </li>
              ))}
            </ul>
          </div>
          <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => setConflictState(null)} aria-label="Dismiss">
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      {moveErrorState && (
        <div className="flex items-start gap-2.5 rounded-2xl border border-urgent/30 bg-urgent/5 px-4 py-3 text-sm">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-urgent" />
          <div className="min-w-0 flex-1">
            <p className="font-medium text-ink">
              Couldn't move <span className="font-semibold">{moveErrorState.label}</span>: {moveErrorState.message}
            </p>
          </div>
          <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => setMoveErrorState(null)} aria-label="Dismiss">
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      {undoState && (
        <div className="flex items-center gap-2.5 rounded-2xl border border-positive/30 bg-positive/5 px-4 py-3 text-sm">
          <span className="min-w-0 flex-1 text-ink">
            Moved <span className="font-semibold">{undoState.label}</span> from {dayPeriodLabel(undoState.fromDay, undoState.fromPeriod)} to{" "}
            {dayPeriodLabel(undoState.toDay, undoState.toPeriod)}.
          </span>
          <Button variant="outline" size="sm" onClick={handleUndo} disabled={pendingSlotId !== null}>
            <Undo2 className="h-3.5 w-3.5" /> Undo
          </Button>
          <Button variant="ghost" size="icon" className="h-7 w-7 shrink-0" onClick={() => setUndoState(null)} aria-label="Dismiss">
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}

      <div className="overflow-x-auto rounded-2xl border border-border bg-card shadow-elevated">
        <table className="w-full min-w-[640px] border-collapse text-sm">
          <thead>
            <tr className="bg-panel">
              <th className="w-24 border-b border-r border-border px-3 py-2 text-left font-mono text-[0.6875rem] font-medium uppercase tracking-wide text-ink-muted">
                Period
              </th>
              {days.map((d) => (
                <th
                  key={d}
                  className={cn(
                    "border-b border-border px-3 py-2 text-left font-display text-xs font-semibold uppercase tracking-wide text-ink-muted",
                    d === todayDow && "text-accent"
                  )}
                >
                  {DAY_LABELS[d]}
                  {d === todayDow && <span className="ml-1 font-mono text-[0.625rem] text-accent">· today</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {periods.map((period) => {
              const isNowRow = todayDow < days.length && nowMinutes >= toMinutes(period.start) && nowMinutes < toMinutes(period.end);
              return (
                <tr key={period.number} className={cn("border-b border-border last:border-b-0", isNowRow && "bg-accent/10")}>
                  <td className="border-r border-border px-3 py-2 align-top font-mono text-xs tabular-nums text-ink-muted">
                    {period.start.slice(0, 5)}
                    <br />
                    {period.end.slice(0, 5)}
                  </td>
                  {days.map((day) => {
                    const cellSlots = slots.filter((s) => s.day_of_week === day && s.period_number === period.number);
                    const isNowCell = isNowRow && day === todayDow;
                    const isDragOver = editable && dragOverCell?.day === day && dragOverCell?.period === period.number;
                    const isOwnCell = draggedSlot?.day_of_week === day && draggedSlot?.period_number === period.number;
                    const cellHasLiveConflict = isDragOver && draggedSlot && !isOwnCell ? liveConflicts(draggedSlot, day, period.number).length > 0 : false;

                    return (
                      <td
                        key={day}
                        onDragOver={editable ? (e) => handleCellDragOver(e, day, period.number) : undefined}
                        onDrop={editable ? (e) => handleCellDrop(e, day, period.number) : undefined}
                        className={cn(
                          "min-w-[9rem] border-l border-border px-1.5 py-1.5 align-top first:border-l-0 transition-colors",
                          isNowCell && "relative",
                          isDragOver && !isOwnCell && !cellHasLiveConflict && "bg-accent/10 ring-2 ring-inset ring-accent",
                          isDragOver && !isOwnCell && cellHasLiveConflict && "bg-urgent/10 ring-2 ring-inset ring-urgent"
                        )}
                      >
                        {isNowCell && <div className="absolute inset-x-0 top-0 h-0.5 bg-accent" aria-hidden="true" />}
                        {isDragOver && !isOwnCell && cellHasLiveConflict && (
                          <div className="mb-1 flex items-center gap-1 font-mono text-[0.625rem] font-medium text-urgent">
                            <AlertTriangle className="h-3 w-3" /> Likely conflict
                          </div>
                        )}
                        <div className="flex flex-col gap-1">
                          {cellSlots.map((slot) => {
                            const isPending = pendingSlotId === slot.id;
                            const isBeingDragged = draggedSlot?.id === slot.id;
                            return (
                              <div
                                key={slot.id}
                                draggable={editable && pendingSlotId === null}
                                onDragStart={editable ? (e) => handleDragStart(e, slot) : undefined}
                                onDragEnd={editable ? handleDragEnd : undefined}
                                className={cn(
                                  "group relative rounded-lg border-l-4 bg-elevated/60 px-2.5 py-1.5 transition-opacity",
                                  editable && pendingSlotId === null && "cursor-grab active:cursor-grabbing",
                                  isBeingDragged && "opacity-40",
                                  isPending && "opacity-70"
                                )}
                                style={{ borderLeftColor: subjectChipVar(slot.subject_id) }}
                              >
                                {editable && pendingSlotId === null && (
                                  <GripVertical className="pointer-events-none absolute right-1 top-1 h-3 w-3 text-ink-faint opacity-0 transition-opacity group-hover:opacity-100" />
                                )}
                                <div className="truncate text-xs font-semibold text-ink">
                                  {subjectNames.get(slot.subject_id) ?? `Subject #${slot.subject_id}`}
                                </div>
                                <div className="truncate font-mono text-[0.6875rem] text-ink-muted">
                                  {roomNames.get(slot.room_id) ?? `Rm ${slot.room_id}`} · {teacherNames.get(slot.teacher_id) ?? `T-${slot.teacher_id}`}
                                </div>
                                {showClass && (
                                  <div className="truncate font-mono text-[0.625rem] text-ink-muted/80">
                                    {classNames.get(slot.class_id) ?? `Class #${slot.class_id}`}
                                  </div>
                                )}
                                {isPending && (
                                  <div className="absolute inset-0 flex items-center justify-center gap-1.5 rounded-lg bg-card/90 font-mono text-[0.625rem] font-medium text-ink-muted">
                                    <Loader2 className="h-3 w-3 animate-spin" /> Saving…
                                  </div>
                                )}
                              </div>
                            );
                          })}
                        </div>
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
