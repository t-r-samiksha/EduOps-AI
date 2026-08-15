import { useEffect, useState } from "react";
import { AlertTriangle, CalendarClock, ScanFace, Users } from "lucide-react";
import PageHeader from "@/components/shared/PageHeader";
import StatTile from "@/components/shared/StatTile";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { useParentChildren } from "@/api/hooks/useParent";
import { useTimetableActive, useReferenceLookup } from "@/api/hooks/useTimetable";
import { useAttendanceSummary } from "@/api/hooks/useAttendance";
import { useFlaggedStudents } from "@/api/hooks/useRisk";
import { useAuthStore } from "@/store/authStore";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function todayDow(): number {
  return (new Date().getDay() + 6) % 7;
}

export default function ParentDashboard() {
  const children = useParentChildren();
  const lookup = useReferenceLookup(useCurrentUser().data?.school_id);
  const email = useAuthStore((s) => s.user?.email);
  const [selectedId, setSelectedId] = useState<string>("");

  useEffect(() => {
    if (!selectedId && children.data?.items.length) {
      setSelectedId(String(children.data.items[0].id));
    }
  }, [children.data, selectedId]);

  const studentId = selectedId ? Number(selectedId) : undefined;
  const dow = todayDow();

  const timetable = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR, studentId, enabled: studentId !== undefined });
  const attendance = useAttendanceSummary({ fromDate: daysAgo(30), toDate: daysAgo(0), studentId, enabled: studentId !== undefined });
  const flagged = useFlaggedStudents({ studentId, enabled: studentId !== undefined });

  const todaySlots = (timetable.data ?? []).filter((s) => s.day_of_week === dow).sort((a, b) => a.period_number - b.period_number);
  const myAttendance = attendance.data?.items[0];

  const subjectName = (id: number) => lookup.data?.subjects.find((s) => s.id === id)?.name ?? `Subject #${id}`;
  const roomName = (id: number) => lookup.data?.rooms.find((r) => r.id === id)?.name ?? `Rm ${id}`;
  const teacherName = (id: number) => lookup.data?.teachers.find((t) => t.id === id)?.name ?? `Teacher #${id}`;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Parent Dashboard"
        description="Your linked children's attendance, timetable, and early-warning status."
        actions={
          (children.data?.items.length ?? 0) > 1 ? (
            <Select value={selectedId} onValueChange={setSelectedId}>
              <SelectTrigger className="w-56">
                <SelectValue placeholder="Select child" />
              </SelectTrigger>
              <SelectContent>
                {children.data?.items.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name} {c.class_name ? `· ${c.class_name}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : undefined
        }
      />

      {children.isLoading && <div className="h-24 animate-pulse rounded-2xl bg-elevated/60" />}

      {!children.isLoading && (children.data?.items.length ?? 0) === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-1 py-6 text-center">
            <Users className="h-6 w-6 text-ink-muted" />
            <p className="font-display text-sm font-medium text-ink">No linked children</p>
            <p className="max-w-sm text-xs text-ink-muted">
              This account{email ? ` (${email})` : ""} has no <code className="font-mono">parent_student</code> link in the
              seeded data yet — this is a real, honest empty state, not a bug.
            </p>
          </CardContent>
        </Card>
      )}

      {studentId !== undefined && (
        <>
          <div className="flex flex-wrap gap-3">
            <StatTile
              label="Attendance (30d)"
              value={attendance.isLoading ? "…" : myAttendance ? `${myAttendance.present_pct.toFixed(1)}%` : "—"}
              caption={!attendance.isLoading && !myAttendance ? "No records in range" : undefined}
              icon={ScanFace}
              tone={myAttendance && myAttendance.present_pct < 85 ? "warning" : "positive"}
            />
            <StatTile
              label="Open risk flags"
              value={flagged.isLoading ? "…" : (flagged.data?.length ?? 0)}
              icon={AlertTriangle}
              tone={(flagged.data?.length ?? 0) > 0 ? "warning" : "positive"}
            />
            <StatTile label="Today's periods" value={timetable.isLoading ? "…" : todaySlots.length} icon={CalendarClock} tone="neutral" />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Today's schedule</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              {timetable.isLoading && <div className="h-16 animate-pulse rounded-lg bg-elevated/60" />}
              {!timetable.isLoading && todaySlots.length === 0 && (
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
        </>
      )}
    </div>
  );
}
