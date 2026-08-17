import { useMemo, useState } from "react";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ChevronDown,
  ChevronUp,
  Download,
  TrendingDown,
  UserCheck,
  Users,
  UserX,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import Field from "@/components/ui/field";
import StatTile from "@/components/shared/StatTile";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useAttendanceAnalytics } from "@/api/hooks/useAttendance";
import { ApiError } from "@/api/client";
import { DAY_LABELS } from "@/lib/constants";
import { csvFilename, downloadCsv, toCsv } from "@/lib/csv";
import type { AttendanceBucket, StudentBucket } from "@/api/types";
import { cn } from "@/lib/utils";

/** Below this, attendance is a problem worth surfacing rather than just a number.
 * Also the default for the defaulter list, and user-overridable in the filter row. */
const DEFAULT_THRESHOLD = 75;

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

/** A meter, per the mark spec: 10px track (well under the 24px cap), fill with a
 * 4px rounded data-end and a square baseline, and an unfilled track that is a
 * lighter step of the fill's own hue so state reads across the whole bar.
 *
 * One hue for every bar - the bar's LENGTH already encodes the percentage, so
 * ramping hue by value too would double-encode it. Colour changes only to carry
 * status (below threshold), and never alone: the row also gets a text badge. */
function Meter({
  label,
  sublabel,
  pct,
  bucket,
  belowThreshold,
  threshold,
}: {
  label: string;
  sublabel?: string;
  pct: number;
  bucket: AttendanceBucket;
  belowThreshold: boolean;
  threshold: number;
}) {
  const title = `${label}${sublabel ? ` · ${sublabel}` : ""} — ${pct.toFixed(1)}% present (${bucket.present_count} present, ${bucket.absent_count} absent, ${bucket.late_count} late of ${bucket.total_records})`;
  return (
    <div className="flex items-center gap-3" title={title}>
      <span className="flex w-32 shrink-0 flex-col">
        <span className="truncate text-xs font-medium text-ink">{label}</span>
        {sublabel && <span className="truncate text-[0.6875rem] text-ink-faint">{sublabel}</span>}
      </span>
      <div className={cn("h-2.5 flex-1 rounded-[4px]", belowThreshold ? "bg-urgent/10" : "bg-accent/10")}>
        <div
          className={cn("h-full rounded-r-[4px]", belowThreshold ? "bg-urgent" : "bg-accent")}
          style={{ width: `${Math.max(0, Math.min(100, pct))}%` }}
        />
      </div>
      <span className="w-14 shrink-0 text-right font-mono text-xs tabular-nums text-ink">{pct.toFixed(1)}%</span>
      <span className="w-24 shrink-0">
        {belowThreshold && (
          <Badge variant="urgent" className="gap-1">
            <TrendingDown className="h-3 w-3" /> under {threshold}%
          </Badge>
        )}
      </span>
    </div>
  );
}

function TrendCell({ trend, delta }: { trend: StudentBucket["trend"]; delta: number }) {
  // Icon + signed number, never colour alone.
  const Icon = trend === "rising" ? ArrowUp : trend === "falling" ? ArrowDown : ArrowRight;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 font-mono text-xs tabular-nums",
        trend === "rising" ? "text-positive" : trend === "falling" ? "text-urgent" : "text-ink-faint"
      )}
      title={`${trend} — ${delta > 0 ? "+" : ""}${delta} points, newer half of the range vs the older half`}
    >
      <Icon className="h-3 w-3" />
      {delta > 0 ? "+" : ""}
      {delta}
    </span>
  );
}

type StudentSortKey = keyof Pick<
  StudentBucket,
  "name" | "class_name" | "present_pct" | "present_count" | "absent_count" | "late_count" | "total_records" | "trend_delta"
>;

export default function AttendanceAnalytics({ schoolId }: { schoolId: number }) {
  const lookup = useReferenceLookup(schoolId);
  const [fromDate, setFromDate] = useState(() => daysAgo(30));
  const [toDate, setToDate] = useState(() => daysAgo(0));
  const [classId, setClassId] = useState("all");
  const [section, setSection] = useState("all");
  const [periodNumber, setPeriodNumber] = useState("all");
  const [subjectId, setSubjectId] = useState("all");
  const [threshold, setThreshold] = useState(DEFAULT_THRESHOLD);
  const [onlyDefaulters, setOnlyDefaulters] = useState(false);
  const [sort, setSort] = useState<{ key: StudentSortKey; dir: "asc" | "desc" }>({
    key: "present_pct",
    dir: "asc",
  });

  const analytics = useAttendanceAnalytics({
    fromDate,
    toDate,
    classId: classId === "all" ? undefined : Number(classId),
    section: section === "all" ? undefined : section,
    periodNumber: periodNumber === "all" ? undefined : Number(periodNumber),
    subjectId: subjectId === "all" ? undefined : Number(subjectId),
    belowPct: onlyDefaulters ? threshold : undefined,
  });

  const data = analytics.data;
  const sections = useMemo(() => {
    const values = new Set(
      (lookup.data?.classes ?? []).map((c) => c.name.split("-").pop()?.trim()).filter((s): s is string => !!s && s.length <= 3)
    );
    return [...values].sort();
  }, [lookup.data]);
  const periodNumbers = useMemo(() => {
    const values = new Set((data?.by_period ?? []).map((p) => p.period_number));
    return [...values].sort((a, b) => a - b);
  }, [data]);

  const sortedStudents = useMemo(() => {
    const rows = [...(data?.students ?? [])];
    rows.sort((a, b) => {
      const av = a[sort.key];
      const bv = b[sort.key];
      const cmp =
        typeof av === "string" && typeof bv === "string"
          ? av.localeCompare(bv)
          : Number(av) - Number(bv);
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [data, sort]);

  const defaulters = useMemo(
    () => (data?.students ?? []).filter((s) => s.present_pct < threshold),
    [data, threshold]
  );

  function toggleSort(key: StudentSortKey) {
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === "asc" ? "desc" : "asc" } : { key, dir: "asc" }));
  }

  function exportStudents() {
    if (!data) return;
    const headers = ["Student", "Class", "Section", "Present %", "Present", "Absent", "Late", "Records", "Trend"];
    const rows = sortedStudents.map((s) => [
      s.name,
      s.class_name,
      s.section,
      s.present_pct,
      s.present_count,
      s.absent_count,
      s.late_count,
      s.total_records,
      `${s.trend} (${s.trend_delta > 0 ? "+" : ""}${s.trend_delta})`,
    ]);
    downloadCsv(csvFilename("attendance-analytics", data.from_date, data.to_date), toCsv(headers, rows));
  }

  function exportBreakdown() {
    if (!data) return;
    const headers = ["Grouping", "Key", "Present %", "Present", "Absent", "Late", "Records"];
    const rows = [
      ...data.by_class.map((c) => ["Class", `${c.class_name}`, c.present_pct, c.present_count, c.absent_count, c.late_count, c.total_records]),
      ...data.by_period.map((p) => ["Period", `P${p.period_number}`, p.present_pct, p.present_count, p.absent_count, p.late_count, p.total_records]),
      ...data.by_subject.map((s) => ["Subject", s.subject_name, s.present_pct, s.present_count, s.absent_count, s.late_count, s.total_records]),
      ...data.by_day.map((d) => ["Day", d.date, d.present_pct, d.present_count, d.absent_count, d.late_count, d.total_records]),
    ];
    downloadCsv(csvFilename("attendance-breakdown", data.from_date, data.to_date), toCsv(headers, rows));
  }

  const SortHead = ({ label, sortKey, className }: { label: string; sortKey: StudentSortKey; className?: string }) => (
    <TableHead className={className}>
      <button
        type="button"
        onClick={() => toggleSort(sortKey)}
        className="inline-flex items-center gap-1 uppercase tracking-wide hover:text-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {label}
        {sort.key === sortKey &&
          (sort.dir === "asc" ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />)}
      </button>
    </TableHead>
  );

  return (
    <div className="flex flex-col gap-3">
      {/* One filter row above everything it scopes - not per-card filters. */}
      <Card>
        <CardHeader>
          <CardTitle>Attendance analytics</CardTitle>
          <CardDescription>
            Every slice below is scoped by these filters. Percentages are of records actually marked in the range.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <Field label="From">
            <Input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
          </Field>
          <Field label="To">
            <Input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
          </Field>
          <Field label="Class">
            <Select value={classId} onValueChange={setClassId}>
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All classes</SelectItem>
                {(lookup.data?.classes ?? []).map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {sections.length > 0 && (
            <Field label="Section">
              <Select value={section} onValueChange={setSection}>
                <SelectTrigger className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All</SelectItem>
                  {sections.map((s) => (
                    <SelectItem key={s} value={s}>
                      {s}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          )}
          <Field label="Period">
            <Select value={periodNumber} onValueChange={setPeriodNumber}>
              <SelectTrigger className="w-28">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All</SelectItem>
                {periodNumbers.map((p) => (
                  <SelectItem key={p} value={String(p)}>
                    P{p}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Subject">
            <Select value={subjectId} onValueChange={setSubjectId}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All subjects</SelectItem>
                {(lookup.data?.subjects ?? []).map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Threshold %" hint="flags students and periods below this">
            <Input
              type="number"
              min={0}
              max={100}
              value={threshold}
              onChange={(e) => setThreshold(Number(e.target.value))}
              className="w-24"
            />
          </Field>
          <Button
            variant={onlyDefaulters ? "default" : "outline"}
            size="sm"
            className="mb-0.5"
            onClick={() => setOnlyDefaulters((v) => !v)}
          >
            <UserX className="h-3.5 w-3.5" />
            {onlyDefaulters ? "Showing only defaulters" : "Only defaulters"}
          </Button>
        </CardContent>
      </Card>

      {analytics.isError && (
        <Card>
          <CardContent className="py-6">
            <p className="text-sm text-urgent">
              {analytics.error instanceof ApiError ? analytics.error.message : "Could not load analytics."}
            </p>
          </CardContent>
        </Card>
      )}
      {analytics.isLoading && <div className="h-64 animate-pulse rounded-2xl bg-elevated/60" />}

      {data && (
        // Hold the previous render at reduced opacity while refetching rather
        // than flashing a skeleton and jumping the layout.
        <div className={cn("flex flex-col gap-3 transition-opacity", analytics.isFetching && "opacity-60")}>
          <div className="flex flex-wrap gap-3">
            <StatTile
              label="Overall present"
              value={`${data.overall.present_pct.toFixed(1)}%`}
              caption={`${data.overall.total_records} records · ${data.from_date} to ${data.to_date}`}
              icon={UserCheck}
              tone={
                data.overall.present_pct >= 90 ? "positive" : data.overall.present_pct >= threshold ? "warning" : "urgent"
              }
              emphasize
            />
            <StatTile label="Students on roll" value={data.roster_size} caption="in the filtered classes" icon={Users} />
            <StatTile
              label={`Below ${threshold}%`}
              value={defaulters.length}
              caption={onlyDefaulters ? "list filtered to these" : "students needing follow-up"}
              icon={UserX}
              tone={defaulters.length > 0 ? "urgent" : "positive"}
            />
            <StatTile
              label="Absences"
              value={data.overall.absent_count}
              caption={`${data.overall.late_count} late`}
              tone={data.overall.absent_count > 0 ? "warning" : "neutral"}
            />
          </div>

          <div className="grid items-start gap-3 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>By period</CardTitle>
                <CardDescription>
                  Which periods bleed attendance. Only covers records attached to a timetable period.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {data.by_period.length === 0 && <p className="text-sm text-ink-muted">No records in this range.</p>}
                {data.by_period.map((p) => (
                  <Meter
                    key={p.period_number}
                    label={`Period ${p.period_number}`}
                    sublabel={`${p.total_records} records`}
                    pct={p.present_pct}
                    bucket={p}
                    belowThreshold={p.present_pct < threshold}
                    threshold={threshold}
                  />
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>By class &amp; section</CardTitle>
                <CardDescription>Worst first.</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {data.by_class.length === 0 && <p className="text-sm text-ink-muted">No records in this range.</p>}
                {data.by_class.map((c) => (
                  <Meter
                    key={c.class_id}
                    label={c.class_name}
                    sublabel={c.section ? `Section ${c.section}` : undefined}
                    pct={c.present_pct}
                    bucket={c}
                    belowThreshold={c.present_pct < threshold}
                    threshold={threshold}
                  />
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>By subject</CardTitle>
              </CardHeader>
              <CardContent className="flex flex-col gap-2">
                {data.by_subject.length === 0 && <p className="text-sm text-ink-muted">No records in this range.</p>}
                {data.by_subject.map((s) => (
                  <Meter
                    key={s.subject_id}
                    label={s.subject_name}
                    sublabel={`${s.total_records} records`}
                    pct={s.present_pct}
                    bucket={s}
                    belowThreshold={s.present_pct < threshold}
                    threshold={threshold}
                  />
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between gap-2">
                  <CardTitle>Day by day</CardTitle>
                  <Button variant="outline" size="sm" onClick={exportBreakdown}>
                    <Download className="h-3.5 w-3.5" /> CSV
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="flex max-h-72 flex-col gap-2 overflow-y-auto">
                {data.by_day.length === 0 && <p className="text-sm text-ink-muted">No records in this range.</p>}
                {data.by_day.map((d) => (
                  <Meter
                    key={d.date}
                    label={d.date}
                    sublabel={DAY_LABELS[d.day_of_week]}
                    pct={d.present_pct}
                    bucket={d}
                    belowThreshold={d.present_pct < threshold}
                    threshold={threshold}
                  />
                ))}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <CardTitle>Per student</CardTitle>
                  <CardDescription>
                    Click any column to sort. {sortedStudents.length} student
                    {sortedStudents.length === 1 ? "" : "s"} with records in this range.
                  </CardDescription>
                </div>
                <Button variant="outline" size="sm" onClick={exportStudents}>
                  <Download className="h-3.5 w-3.5" /> CSV
                </Button>
              </div>
            </CardHeader>
            <CardContent>
              {sortedStudents.length === 0 ? (
                <p className="text-sm text-ink-muted">No attendance records match these filters.</p>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      <SortHead label="Student" sortKey="name" />
                      <SortHead label="Class" sortKey="class_name" />
                      <SortHead label="Present %" sortKey="present_pct" />
                      <SortHead label="Present" sortKey="present_count" />
                      <SortHead label="Absent" sortKey="absent_count" />
                      <SortHead label="Late" sortKey="late_count" />
                      <SortHead label="Records" sortKey="total_records" />
                      <SortHead label="Trend" sortKey="trend_delta" />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {sortedStudents.map((s) => {
                      const below = s.present_pct < threshold;
                      return (
                        <TableRow key={s.student_id} className={cn(below && "bg-urgent/5")}>
                          <TableCell className="font-medium">
                            <span className="flex items-center gap-2">
                              {below && <UserX className="h-3.5 w-3.5 shrink-0 text-urgent" />}
                              {s.name}
                            </span>
                          </TableCell>
                          <TableCell className="text-ink-muted">{s.class_name}</TableCell>
                          <TableCell>
                            <Badge
                              variant={s.present_pct >= 90 ? "positive" : below ? "urgent" : "neutral"}
                              className="font-mono tabular-nums"
                            >
                              {s.present_pct.toFixed(1)}%
                            </Badge>
                          </TableCell>
                          <TableCell className="font-mono tabular-nums">{s.present_count}</TableCell>
                          <TableCell className="font-mono tabular-nums">{s.absent_count}</TableCell>
                          <TableCell className="font-mono tabular-nums">{s.late_count}</TableCell>
                          <TableCell className="font-mono tabular-nums text-ink-muted">{s.total_records}</TableCell>
                          <TableCell>
                            <TrendCell trend={s.trend} delta={s.trend_delta} />
                          </TableCell>
                        </TableRow>
                      );
                    })}
                  </TableBody>
                </Table>
              )}
            </CardContent>
          </Card>
        </div>
      )}
    </div>
  );
}
