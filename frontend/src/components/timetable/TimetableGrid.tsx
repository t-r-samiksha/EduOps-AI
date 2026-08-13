import { useMemo } from "react";
import type { TimetableSlot } from "@/api/types";
import type { LookupResponse } from "@/api/hooks/useTimetable";
import { DAY_LABELS } from "@/lib/constants";
import { subjectChipVar } from "@/lib/subjectColor";
import { cn } from "@/lib/utils";

interface TimetableGridProps {
  slots: TimetableSlot[];
  lookup?: LookupResponse;
  /** Show the class name on each chip — useful for an unfiltered "all classes" admin view. */
  showClass?: boolean;
}

function toMinutes(time: string): number {
  const [h, m] = time.split(":").map(Number);
  return h * 60 + m;
}

export default function TimetableGrid({ slots, lookup, showClass }: TimetableGridProps) {
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
                  return (
                    <td
                      key={day}
                      className={cn(
                        "min-w-[9rem] border-l border-border px-1.5 py-1.5 align-top first:border-l-0",
                        isNowCell && "relative"
                      )}
                    >
                      {isNowCell && (
                        <div className="absolute inset-x-0 top-0 h-0.5 bg-accent" aria-hidden="true" />
                      )}
                      <div className="flex flex-col gap-1">
                        {cellSlots.map((slot) => (
                          <div
                            key={slot.id}
                            className="rounded-lg border-l-4 bg-elevated/60 px-2.5 py-1.5"
                            style={{ borderLeftColor: subjectChipVar(slot.subject_id) }}
                          >
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
                          </div>
                        ))}
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
  );
}
