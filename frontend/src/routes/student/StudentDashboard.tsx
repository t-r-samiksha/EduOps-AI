import { CalendarClock, ScanFace } from "lucide-react";
import PageHeader from "@/components/shared/PageHeader";
import StatTile from "@/components/shared/StatTile";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { useTimetableActive, useReferenceLookup } from "@/api/hooks/useTimetable";
import { useAttendanceSummary } from "@/api/hooks/useAttendance";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { ApiError } from "@/api/client";
import { DEFAULT_ACADEMIC_YEAR, DAY_LABELS } from "@/lib/constants";

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function todayDow(): number {
  return (new Date().getDay() + 6) % 7;
}

export default function StudentDashboard() {
  const lookup = useReferenceLookup(useCurrentUser().data?.school_id);
  // No class enrollment -> the real backend 404s here (see timetable.py's
  // _resolve_student_class_id) rather than returning an empty list. Retry
  // disabled since a 404 for "not enrolled" won't resolve itself on retry.
  const timetable = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR, retry: false });
  const attendance = useAttendanceSummary({ fromDate: daysAgo(30), toDate: daysAgo(0) });

  const dow = todayDow();
  const todaySlots = (timetable.data ?? [])
    .filter((s) => s.day_of_week === dow)
    .sort((a, b) => a.period_number - b.period_number);

  const notEnrolled = timetable.error instanceof ApiError && timetable.error.status === 404;

  // GET /risk/flagged 403s for the student role by design (teacher/admin/principal/
  // parent only) - not shown here rather than faked. See docs/api-contract.md.
  const myAttendance = attendance.data?.items[0];

  const subjectName = (id: number) => lookup.data?.subjects.find((s) => s.id === id)?.name ?? `Subject #${id}`;
  const roomName = (id: number) => lookup.data?.rooms.find((r) => r.id === id)?.name ?? `Rm ${id}`;
  const teacherName = (id: number) => lookup.data?.teachers.find((t) => t.id === id)?.name ?? `Teacher #${id}`;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="Student Dashboard" description={`Today is ${DAY_LABELS[dow] ?? "—"}, ${new Date().toLocaleDateString()}.`} />

      <div className="flex flex-wrap gap-3">
        <StatTile
          label="Attendance (30d)"
          value={attendance.isLoading ? "…" : myAttendance ? `${myAttendance.present_pct.toFixed(1)}%` : "—"}
          caption={!attendance.isLoading && !myAttendance ? "No records in range" : undefined}
          icon={ScanFace}
          tone={myAttendance && myAttendance.present_pct < 85 ? "warning" : "positive"}
        />
        <StatTile
          label="Today's periods"
          value={timetable.isLoading ? "…" : notEnrolled ? "—" : todaySlots.length}
          caption={notEnrolled ? "Not enrolled in a class" : undefined}
          icon={CalendarClock}
          tone="neutral"
        />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Today's schedule</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {timetable.isLoading && <div className="h-16 animate-pulse rounded-lg bg-elevated/60" />}
          {notEnrolled && (
            <p className="text-sm text-ink-muted">
              This account has no primary class enrollment yet, so there's no timetable to show — a real backend state, not a
              loading glitch.
            </p>
          )}
          {!timetable.isLoading && !notEnrolled && todaySlots.length === 0 && (
            <p className="text-sm text-ink-muted">No periods scheduled today.</p>
          )}
          {todaySlots.map((slot) => (
            <div key={slot.id} className="flex items-center justify-between rounded-xl bg-elevated/40 px-3.5 py-2.5 text-sm">
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs tabular-nums text-ink-muted">{slot.start_time.slice(0, 5)}</span>
                <span className="font-medium text-ink">{subjectName(slot.subject_id)}</span>
                <span className="text-ink-muted">{teacherName(slot.teacher_id)}</span>
              </div>
              <span className="font-mono text-xs text-ink-muted">{roomName(slot.room_id)}</span>
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
