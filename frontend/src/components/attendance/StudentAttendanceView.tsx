import { useState } from "react";
import { CalendarDays, CheckCircle2, Clock, Download, ScanFace, UserX } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import Field from "@/components/ui/field";
import StatTile from "@/components/shared/StatTile";
import { useMyAttendanceRecords } from "@/api/hooks/useAttendance";
import { ApiError } from "@/api/client";
import { DAY_LABELS } from "@/lib/constants";
import { csvFilename, downloadCsv, toCsv } from "@/lib/csv";
import type { AttendanceStatus, MyRecordDay } from "@/api/types";
import { cn } from "@/lib/utils";

const RANGE_PRESETS = [7, 30, 90] as const;
const LOW_ATTENDANCE_PCT = 75;

const STATUS_BADGE: Record<AttendanceStatus, "positive" | "urgent" | "warning"> = {
  present: "positive",
  absent: "urgent",
  late: "warning",
};

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function dayTone(day: MyRecordDay): string {
  if (day.present_pct >= 90) return "bg-positive/70";
  if (day.present_pct >= LOW_ATTENDANCE_PCT) return "bg-warning/70";
  if (day.present_pct > 0) return "bg-urgent/50";
  return "bg-urgent/80";
}

/** Read-only period-by-period attendance for one student. Shared by the student
 * portal (reads itself, `studentId` omitted) and the parent portal (passes the
 * selected child's id). Neither role can edit - the backend rejects it too. */
export default function StudentAttendanceView({
  studentId,
  heading,
  description,
}: {
  studentId?: number;
  heading?: string;
  description?: string;
}) {
  const [fromDate, setFromDate] = useState(() => daysAgo(30));
  const [toDate, setToDate] = useState(() => daysAgo(0));

  // The parent wrapper doesn't mount this until a child is selected, so no
  // guard is needed here: a student reads themselves with studentId undefined,
  // and the backend ignores the param for that role anyway.
  const records = useMyAttendanceRecords({ fromDate, toDate, studentId });
  const data = records.data;

  function applyPreset(days: number) {
    setFromDate(daysAgo(days));
    setToDate(daysAgo(0));
  }

  function handleExport() {
    if (!data) return;
    const headers = ["Date", "Day", "Period", "Time", "Subject", "Teacher", "Status", "Source"];
    const rows = data.days.flatMap((day) =>
      day.periods.map((p) => [
        day.date,
        DAY_LABELS[day.day_of_week],
        p.period_number ?? "",
        p.start_time ? p.start_time.slice(0, 5) : "",
        p.subject_name ?? "",
        p.teacher_name ?? "",
        p.status,
        p.source,
      ])
    );
    downloadCsv(
      csvFilename("attendance", data.student_name, data.from_date, data.to_date),
      toCsv(headers, rows)
    );
  }

  const summary = data?.summary;
  const isLow = summary ? summary.present_pct < LOW_ATTENDANCE_PCT : false;

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>{heading ?? "My attendance"}</CardTitle>
          <CardDescription>
            {description ??
              "Period by period, as recorded by the class camera or the teacher. Updates as soon as attendance is marked."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <Field label="From">
            <Input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
          </Field>
          <Field label="To">
            <Input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
          </Field>
          <div className="mb-0.5 flex items-center gap-1.5">
            {RANGE_PRESETS.map((days) => (
              <Button key={days} variant="outline" size="sm" onClick={() => applyPreset(days)}>
                <CalendarDays className="h-3.5 w-3.5" /> {days}d
              </Button>
            ))}
          </div>
          {data && data.days.length > 0 && (
            <Button variant="outline" size="sm" className="mb-0.5" onClick={handleExport}>
              <Download className="h-3.5 w-3.5" /> CSV
            </Button>
          )}
        </CardContent>
      </Card>

      {records.isError && (
        <Card>
          <CardContent className="py-6">
            <p className="text-sm text-urgent">
              {records.error instanceof ApiError ? records.error.message : "Could not load attendance."}
            </p>
          </CardContent>
        </Card>
      )}
      {records.isLoading && <div className="h-48 animate-pulse rounded-2xl bg-elevated/60" />}

      {data && summary && (
        <div className={cn("flex flex-col gap-3 transition-opacity", records.isFetching && "opacity-60")}>
          <div className="flex flex-wrap gap-3">
            <StatTile
              label="Present"
              value={`${summary.present_pct.toFixed(1)}%`}
              caption={`${summary.total_records} period${summary.total_records === 1 ? "" : "s"} recorded`}
              icon={ScanFace}
              tone={isLow ? "urgent" : summary.present_pct >= 90 ? "positive" : "warning"}
              emphasize
            />
            <StatTile label="Periods attended" value={summary.present_count} icon={CheckCircle2} tone="positive" />
            <StatTile
              label="Missed"
              value={summary.absent_count}
              caption={`${summary.late_count} late`}
              icon={UserX}
              tone={summary.absent_count > 0 ? "urgent" : "neutral"}
            />
            {data.class_name && <StatTile label="Class" value={data.class_name} />}
          </div>

          {isLow && summary.total_records > 0 && (
            <div className="flex items-start gap-2 rounded-xl border border-urgent/30 bg-urgent/5 px-3.5 py-2.5 text-xs text-urgent">
              <UserX className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                Attendance is below {LOW_ATTENDANCE_PCT}% for this range. Most schools treat this as the point where it
                affects exam eligibility — worth raising with the class teacher.
              </span>
            </div>
          )}

          {data.days.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Day by day</CardTitle>
                <CardDescription>
                  One block per recorded day, newest last. Hover a block for that day's figure — the full list below
                  carries the same numbers.
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1">
                  {[...data.days].reverse().map((day) => (
                    <span
                      key={day.date}
                      title={`${day.date} (${DAY_LABELS[day.day_of_week]}) — ${day.present_count}/${day.total_count} periods present, ${day.present_pct.toFixed(0)}%`}
                      className={cn("h-5 w-5 rounded-[4px]", dayTone(day))}
                    />
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {data.days.length === 0 ? (
            <Card>
              <CardContent className="py-6">
                <p className="text-sm text-ink-muted">
                  No attendance recorded between {data.from_date} and {data.to_date}.
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="flex flex-col gap-3">
              {data.days.map((day) => (
                <Card key={day.date}>
                  <CardHeader>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <CardTitle className="text-base">
                        {DAY_LABELS[day.day_of_week]} · {day.date}
                      </CardTitle>
                      <Badge
                        variant={
                          day.present_pct >= 90 ? "positive" : day.present_pct >= LOW_ATTENDANCE_PCT ? "warning" : "urgent"
                        }
                        className="font-mono tabular-nums"
                      >
                        {day.present_count}/{day.total_count} present
                      </Badge>
                    </div>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-1">
                    {day.periods.map((period, i) => (
                      <div
                        key={`${period.timetable_slot_id ?? "x"}-${i}`}
                        className="flex flex-wrap items-center gap-2 rounded-lg bg-elevated/30 px-2.5 py-1.5 text-sm"
                      >
                        <span className="w-8 shrink-0 font-mono text-xs text-ink-faint">
                          {period.period_number !== null ? `P${period.period_number}` : "—"}
                        </span>
                        {period.start_time && (
                          <span className="flex shrink-0 items-center gap-1 font-mono text-xs tabular-nums text-ink-muted">
                            <Clock className="h-3 w-3" />
                            {period.start_time.slice(0, 5)}
                          </span>
                        )}
                        <span className="min-w-24 flex-1 font-medium text-ink">{period.subject_name ?? "—"}</span>
                        <span className="hidden shrink-0 text-xs text-ink-muted sm:inline">
                          {period.teacher_name ?? ""}
                        </span>
                        <Badge variant={STATUS_BADGE[period.status]}>{period.status}</Badge>
                        <span
                          className="shrink-0 font-mono text-[0.6875rem] text-ink-faint"
                          title={
                            period.source === "cv"
                              ? "Recorded automatically by the classroom camera"
                              : period.source === "manual"
                                ? "Marked by a teacher"
                                : period.source
                          }
                        >
                          {period.source}
                        </span>
                      </div>
                    ))}
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
