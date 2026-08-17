import { CalendarClock, AlertTriangle, ScanFace, Users, BookOpenCheck, FolderKanban } from "lucide-react";
import PageHeader from "@/components/shared/PageHeader";
import StatTile from "@/components/shared/StatTile";
import QuickLinkCard from "@/components/shared/QuickLinkCard";
import TopDoubtsWidget from "@/components/bots/TopDoubtsWidget";
import { Badge } from "@/components/ui/badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { useTimetableActive, useReferenceLookup } from "@/api/hooks/useTimetable";
import { useFlaggedStudents } from "@/api/hooks/useRisk";
import { useLeaveRequests, useMySubstituteDuties } from "@/api/hooks/useStaffing";
import { useSyllabusSummary } from "@/api/hooks/useSyllabus";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { DEFAULT_ACADEMIC_YEAR, DAY_LABELS } from "@/lib/constants";

function todayDow(): number {
  return (new Date().getDay() + 6) % 7;
}

export default function TeacherDashboard() {
  const lookup = useReferenceLookup(useCurrentUser().data?.school_id);
  const timetable = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR });
  const flagged = useFlaggedStudents({});
  const pendingLeave = useLeaveRequests({ status: "pending" });
  const syllabus = useSyllabusSummary({ academicYear: DEFAULT_ACADEMIC_YEAR });
  const substituteDuties = useMySubstituteDuties();

  const dow = todayDow();
  const todaySlots = (timetable.data ?? [])
    .filter((s) => s.day_of_week === dow)
    .sort((a, b) => a.period_number - b.period_number);

  const behindCount = (syllabus.data?.items ?? []).filter((i) => i.status === "behind").length;

  const subjectName = (id: number) => lookup.data?.subjects.find((s) => s.id === id)?.name ?? `Subject #${id}`;
  const roomName = (id: number) => lookup.data?.rooms.find((r) => r.id === id)?.name ?? `Rm ${id}`;
  const className = (id: number) => lookup.data?.classes.find((c) => c.id === id)?.name ?? `Class #${id}`;
  const teacherName = (id: number) => lookup.data?.teachers.find((t) => t.id === id)?.name ?? `Teacher #${id}`;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="Teacher Dashboard" description={`Today is ${DAY_LABELS[dow] ?? "—"}, ${new Date().toLocaleDateString()}.`} />

      <div className="flex flex-wrap gap-3">
        <StatTile
          label="Today's periods"
          value={timetable.isLoading ? "…" : todaySlots.length}
          icon={CalendarClock}
          tone="neutral"
        />
        <StatTile
          label="Open risk flags"
          value={flagged.isLoading ? "…" : (flagged.data?.length ?? 0)}
          icon={AlertTriangle}
          tone={(flagged.data?.length ?? 0) > 0 ? "warning" : "positive"}
        />
        <StatTile
          label="My pending leave"
          value={pendingLeave.isLoading ? "…" : (pendingLeave.data?.length ?? 0)}
          icon={Users}
          tone="neutral"
        />
        <StatTile
          label="Substitute duties"
          value={substituteDuties.isLoading ? "…" : (substituteDuties.data?.length ?? 0)}
          icon={Users}
          tone={(substituteDuties.data?.length ?? 0) > 0 ? "warning" : "positive"}
        />
        <StatTile
          label="Syllabus behind pace"
          value={syllabus.isLoading ? "…" : behindCount}
          icon={BookOpenCheck}
          tone={behindCount > 0 ? "urgent" : "positive"}
        />
      </div>

      {/* Above the schedule deliberately: this is the one panel that tells a teacher
          something they could not already work out from their own timetable. */}
      <TopDoubtsWidget />

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
                <span className="text-ink-muted">{className(slot.class_id)}</span>
              </div>
              <span className="font-mono text-xs text-ink-muted">{roomName(slot.room_id)}</span>
            </div>
          ))}
        </CardContent>
      </Card>

      {(substituteDuties.data?.length ?? 0) > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Your substitute duties</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {substituteDuties.data!.map((duty) => (
              <div
                key={duty.substitution_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-elevated/40 px-3.5 py-2.5 text-sm"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-medium text-ink">{subjectName(duty.subject_id)}</span>
                  <span className="text-ink-muted">{className(duty.class_id)}</span>
                  <span className="font-mono text-xs text-ink-muted">
                    {DAY_LABELS[duty.day_of_week]} · Period {duty.period_number + 1}
                  </span>
                  <span className="text-xs text-ink-muted">
                    covering for {teacherName(duty.original_teacher_id)} ({duty.leave_start_date} → {duty.leave_end_date})
                  </span>
                </div>
                <Badge variant={duty.status === "confirmed" ? "positive" : "accent"}>{duty.status}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <QuickLinkCard
          to="/teacher/classroom"
          icon={BookOpenCheck}
          label="Classroom Stream"
          stat="Post notes, alerts & learning materials"
        />
        <QuickLinkCard
          to="/teacher/resources"
          icon={FolderKanban}
          label="Resources Library"
          stat="Upload & organize notes, slides and sheets"
        />
        <QuickLinkCard
          to="/teacher/timetable"
          icon={CalendarClock}
          label="Timetable"
          stat={`${timetable.data?.length ?? 0} active slots this year`}
        />
        <QuickLinkCard to="/teacher/attendance" icon={ScanFace} label="Attendance" stat="Mark attendance from a classroom photo" />
        <QuickLinkCard
          to="/teacher/staffing"
          icon={Users}
          label="Staffing"
          stat={`${pendingLeave.data?.length ?? 0} of your requests pending`}
        />
        <QuickLinkCard
          to="/teacher/risk"
          icon={AlertTriangle}
          label="Early-Warning"
          stat={`${flagged.data?.length ?? 0} students flagged in your classes`}
        />
        <QuickLinkCard
          to="/teacher/syllabus"
          icon={BookOpenCheck}
          label="Syllabus"
          stat={`${behindCount} plan${behindCount === 1 ? "" : "s"} behind pace`}
        />
      </div>
    </div>
  );
}
