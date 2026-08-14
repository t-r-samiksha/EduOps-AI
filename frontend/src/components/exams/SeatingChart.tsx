import { useMemo } from "react";
import { DoorOpen } from "lucide-react";
import type { SeatingItem } from "@/api/types";
import type { LookupResponse } from "@/api/hooks/useTimetable";
import { cn } from "@/lib/utils";

interface SeatingChartProps {
  items: SeatingItem[];
  lookup?: LookupResponse;
  /** Highlight one student's own seat — used by the student's self-lookup view. */
  highlightStudentId?: number;
}

const SEATS_PER_ROW = 6;

/** A genuine room-by-room seat map (not a flat table) — each room renders as its own
 * card with seats laid out in real rows, echoing the same "grid = the subject matter
 * itself" idea as TimetableGrid. Seat cells fill in row-major order by seat_no. */
export default function SeatingChart({ items, lookup, highlightStudentId }: SeatingChartProps) {
  const studentNames = useMemo(() => new Map(lookup?.students.map((s) => [s.id, s.name])), [lookup]);

  // Keyed by exam_id+room_id, not room_id alone: seat_no is only unique per
  // exam/room, and the student self-lookup view (no exam_id filter) can return
  // seats across multiple exams that happen to share a room.
  const byRoom = useMemo(() => {
    const map = new Map<string, { examId: number; roomName: string; seats: SeatingItem[] }>();
    for (const item of items) {
      const key = `${item.exam_id}-${item.room_id}`;
      if (!map.has(key)) map.set(key, { examId: item.exam_id, roomName: item.room_name, seats: [] });
      map.get(key)!.seats.push(item);
    }
    for (const room of map.values()) room.seats.sort((a, b) => a.seat_no - b.seat_no);
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b));
  }, [items]);

  if (byRoom.length === 0) {
    return (
      <div className="flex flex-col items-center gap-1 rounded-2xl border border-dashed border-border px-6 py-8 text-center">
        <p className="font-display text-sm font-medium text-ink">No seating found</p>
        <p className="max-w-xs text-xs text-ink-muted">
          Nothing has been generated for this scope yet, or no seat is assigned here.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {byRoom.map(([key, room]) => {
        const maxSeat = Math.max(...room.seats.map((s) => s.seat_no));
        const cols = Math.min(SEATS_PER_ROW, maxSeat);
        return (
          <div key={key} className="overflow-hidden rounded-2xl border border-border bg-card shadow-elevated">
            <div className="flex items-center gap-2 border-b border-border bg-panel px-4 py-2.5">
              <DoorOpen className="h-4 w-4 text-ink-muted" />
              <span className="font-display text-sm font-semibold text-ink">{room.roomName}</span>
              <span className="font-mono text-xs text-ink-muted">· Exam #{room.examId} · {room.seats.length} seat(s)</span>
            </div>
            <div className="p-4">
              <div
                className="grid gap-2"
                style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
              >
                {room.seats.map((seat) => {
                  const isMine = highlightStudentId !== undefined && seat.student_id === highlightStudentId;
                  return (
                    <div
                      key={seat.seat_no}
                      className={cn(
                        "flex flex-col items-center gap-0.5 rounded-xl border-2 px-2 py-2.5 text-center transition-colors",
                        isMine ? "border-accent bg-accent/10" : "border-border bg-elevated/40"
                      )}
                    >
                      <span className="font-mono text-[0.625rem] text-ink-faint">#{seat.seat_no}</span>
                      <span className="truncate text-[0.6875rem] font-medium leading-tight text-ink" title={studentNames.get(seat.student_id) ?? `Student #${seat.student_id}`}>
                        {studentNames.get(seat.student_id) ?? `#${seat.student_id}`}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
