import { useMemo, useRef, useState } from "react";
import { CheckCircle2, ClipboardCheck, ScanFace, Upload, UserPlus, XCircle } from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useTimetableActive } from "@/api/hooks/useTimetable";
import { useEnrollStudent, useMarkAttendance, useAttendanceSummary, useReviewAttendanceRecord } from "@/api/hooks/useAttendance";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { DEFAULT_ACADEMIC_YEAR, DAY_LABELS } from "@/lib/constants";
import { ApiError } from "@/api/client";
import type { TimetableSlot } from "@/api/types";
import { cn } from "@/lib/utils";

function ImagePicker({
  file,
  onChange,
  label,
}: {
  file: File | null;
  onChange: (file: File | null) => void;
  label: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const previewUrl = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);

  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs font-medium text-ink-muted">{label}</span>
      <button
        type="button"
        onClick={() => inputRef.current?.click()}
        className="flex h-40 items-center justify-center overflow-hidden rounded-xl border-2 border-dashed border-border bg-elevated/50 transition-colors hover:border-accent hover:bg-elevated focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        {previewUrl ? (
          <img src={previewUrl} alt="Selected preview" className="h-full w-full object-cover" />
        ) : (
          <span className="flex flex-col items-center gap-1.5 text-ink-muted">
            <Upload className="h-5 w-5" />
            <span className="text-xs">Click to choose a photo</span>
          </span>
        )}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        className="sr-only"
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
      {file && <span className="truncate text-xs font-mono text-ink-muted">{file.name}</span>}
    </div>
  );
}

function ConfidenceBadge({ confidence, needsReview }: { confidence: number; needsReview: boolean }) {
  const pct = (confidence * 100).toFixed(1);
  return (
    <Badge variant={needsReview ? "urgent" : "positive"} className="font-mono tabular-nums">
      {pct}%
    </Badge>
  );
}

function EnrollTab({ schoolId }: { schoolId: number }) {
  const lookup = useReferenceLookup(schoolId);
  const [studentId, setStudentId] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const enroll = useEnrollStudent();

  function handleSubmit() {
    if (!studentId || !file) return;
    enroll.mutate({ studentId: Number(studentId), file });
  }

  return (
    <div className="grid items-start gap-3 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Enroll a reference photo</CardTitle>
          <CardDescription>One clear photo containing exactly one face. Stored as a face embedding for future recognition.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Field label="Student">
            <Select value={studentId} onValueChange={setStudentId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a student" />
              </SelectTrigger>
              <SelectContent>
                {lookup.data?.students.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    {s.name} <span className="text-ink-muted">· #{s.id}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <ImagePicker file={file} onChange={setFile} label="Reference photo" />
          <Button onClick={handleSubmit} disabled={!studentId || !file || enroll.isPending} className="self-start">
            <UserPlus className="h-4 w-4" />
            {enroll.isPending ? "Enrolling…" : "Enroll student"}
          </Button>
          {enroll.isError && (
            <p className="text-sm text-urgent">
              {enroll.error instanceof ApiError ? enroll.error.message : "Enrollment failed."}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Result</CardTitle>
        </CardHeader>
        <CardContent>
          {enroll.isSuccess ? (
            <div className="flex flex-col gap-1 text-sm">
              <Badge variant="positive" className="w-fit">
                Enrolled
              </Badge>
              <p className="text-ink-muted">
                Embedding <span className="font-mono text-ink">#{enroll.data.id}</span> stored for student{" "}
                <span className="font-mono text-ink">#{enroll.data.student_id}</span>
              </p>
              <p className="font-mono text-xs text-ink-muted">{new Date(enroll.data.enrolled_at).toLocaleString()}</p>
            </div>
          ) : (
            <p className="text-sm text-ink-muted">Nothing enrolled yet this session.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function MarkTab({ schoolId }: { schoolId: number }) {
  const timetable = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR });
  const lookup = useReferenceLookup(schoolId);
  const [slotId, setSlotId] = useState<string>("");
  const [date, setDate] = useState<string>(() => new Date().toISOString().slice(0, 10));
  const [file, setFile] = useState<File | null>(null);
  const mark = useMarkAttendance();
  const review = useReviewAttendanceRecord();
  const [reviewedIds, setReviewedIds] = useState<Set<number>>(new Set());

  const slotLabel = (s: TimetableSlot) => {
    const subject = lookup.data?.subjects.find((x) => x.id === s.subject_id)?.name ?? `Subject #${s.subject_id}`;
    const cls = lookup.data?.classes.find((x) => x.id === s.class_id)?.name ?? `Class #${s.class_id}`;
    return `${DAY_LABELS[s.day_of_week]} ${s.start_time.slice(0, 5)} · ${subject} · ${cls}`;
  };

  function handleSubmit() {
    if (!slotId || !file) return;
    setReviewedIds(new Set());
    mark.mutate({ timetableSlotId: Number(slotId), file, date });
  }

  function handleReview(recordId: number, status: "present" | "absent") {
    review.mutate(
      { recordId, status },
      { onSuccess: () => setReviewedIds((prev) => new Set(prev).add(recordId)) }
    );
  }

  const studentName = (id: number) => lookup.data?.students.find((s) => s.id === id)?.name ?? `Student #${id}`;

  return (
    <div className="grid items-start gap-3 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Run recognition on a classroom photo</CardTitle>
          <CardDescription>Matches every enrolled face in the slot's class against the photo.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Field label="Timetable slot">
            <Select value={slotId} onValueChange={setSlotId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a period" />
              </SelectTrigger>
              <SelectContent>
                {timetable.data?.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    {slotLabel(s)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Date">
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <ImagePicker file={file} onChange={setFile} label="Classroom photo" />
          <Button onClick={handleSubmit} disabled={!slotId || !file || mark.isPending} className="self-start">
            <ScanFace className="h-4 w-4" />
            {mark.isPending ? "Running recognition…" : "Mark attendance"}
          </Button>
          {mark.isError && (
            <p className="text-sm text-urgent">{mark.error instanceof ApiError ? mark.error.message : "Recognition failed."}</p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Match results</CardTitle>
          {mark.isSuccess && (
            <CardDescription>
              {mark.data.records_created} new record{mark.data.records_created === 1 ? "" : "s"} · {mark.data.matches.length} matched ·{" "}
              {mark.data.unmatched_faces.length} unmatched face{mark.data.unmatched_faces.length === 1 ? "" : "s"}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {!mark.isSuccess && <p className="text-sm text-ink-muted">No photo processed yet this session.</p>}
          {mark.isSuccess && mark.data.matches.length > 0 && (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Student</TableHead>
                  <TableHead>Confidence</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mark.data.matches.map((m) => {
                  const wasReviewed = reviewedIds.has(m.record_id);
                  return (
                    <TableRow key={m.record_id}>
                      <TableCell className="font-medium">{studentName(m.student_id)}</TableCell>
                      <TableCell>
                        <ConfidenceBadge confidence={m.confidence} needsReview={m.needs_review} />
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <span className={cn("text-xs", m.already_marked ? "text-ink-muted" : "text-positive")}>
                            {m.already_marked ? "already marked" : "newly marked"}
                          </span>
                          {m.needs_review && !wasReviewed && (
                            <>
                              <Badge variant="urgent">needs review</Badge>
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-6 px-2 text-[0.6875rem]"
                                disabled={review.isPending}
                                onClick={() => handleReview(m.record_id, "present")}
                              >
                                <CheckCircle2 className="h-3 w-3" /> Confirm
                              </Button>
                              <Button
                                variant="outline"
                                size="sm"
                                className="h-6 px-2 text-[0.6875rem]"
                                disabled={review.isPending}
                                onClick={() => handleReview(m.record_id, "absent")}
                              >
                                <XCircle className="h-3 w-3" /> Not present
                              </Button>
                            </>
                          )}
                          {m.needs_review && wasReviewed && <Badge variant="positive">reviewed</Badge>}
                        </div>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
          {mark.isSuccess && mark.data.unmatched_faces.length > 0 && (
            <div className="flex flex-col gap-1.5 border-t border-border pt-3">
              <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">Unmatched faces</span>
              {mark.data.unmatched_faces.map((f, i) => (
                <div key={i} className="flex items-center justify-between text-sm">
                  <span className="text-ink-muted">Face {i + 1}</span>
                  <span className="font-mono text-xs tabular-nums text-ink-muted">
                    best confidence {(f.best_confidence * 100).toFixed(1)}%
                  </span>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function SummaryTab({ schoolId }: { schoolId: number }) {
  const lookup = useReferenceLookup(schoolId);
  const [fromDate, setFromDate] = useState(() => daysAgo(7));
  const [toDate, setToDate] = useState(() => daysAgo(0));
  const [classId, setClassId] = useState<string>("all");

  const summary = useAttendanceSummary({
    fromDate,
    toDate,
    classId: classId === "all" ? undefined : Number(classId),
  });

  const studentName = (id: number) => lookup.data?.students.find((s) => s.id === id)?.name ?? `Student #${id}`;
  const className = (id: number) => lookup.data?.classes.find((c) => c.id === id)?.name ?? `Class #${id}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Attendance summary</CardTitle>
        <CardDescription>Real per-student stats from recorded attendance, over a date range.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="From">
            <Input type="date" value={fromDate} onChange={(e) => setFromDate(e.target.value)} />
          </Field>
          <Field label="To">
            <Input type="date" value={toDate} onChange={(e) => setToDate(e.target.value)} />
          </Field>
          <Field label="Class">
            <Select value={classId} onValueChange={setClassId}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All classes</SelectItem>
                {lookup.data?.classes.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        </div>

        {summary.isLoading && <div className="h-32 animate-pulse rounded-lg bg-elevated/60" />}
        {summary.data && summary.data.items.length === 0 && (
          <p className="text-sm text-ink-muted">No attendance records in this range.</p>
        )}
        {summary.data && summary.data.items.length > 0 && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Student</TableHead>
                <TableHead>Class</TableHead>
                <TableHead>Present</TableHead>
                <TableHead>Absent</TableHead>
                <TableHead>Late</TableHead>
                <TableHead>Present %</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {summary.data.items.map((item) => (
                <TableRow key={item.student_id}>
                  <TableCell className="font-medium">{studentName(item.student_id)}</TableCell>
                  <TableCell className="text-ink-muted">{className(item.class_id)}</TableCell>
                  <TableCell className="font-mono tabular-nums">{item.present_count}</TableCell>
                  <TableCell className="font-mono tabular-nums">{item.absent_count}</TableCell>
                  <TableCell className="font-mono tabular-nums">{item.late_count}</TableCell>
                  <TableCell>
                    <Badge variant={item.present_pct >= 90 ? "positive" : item.present_pct >= 75 ? "neutral" : "urgent"} className="font-mono tabular-nums">
                      {item.present_pct.toFixed(1)}%
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export default function AttendanceCapture() {
  const schoolId = useCurrentUser().data?.school_id;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Attendance"
        description="CV-based face recognition — enroll reference photos, mark attendance from a classroom photo, review low-confidence matches, and track summary stats."
      />
      {schoolId == null ? (
        <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />
      ) : (
        <Tabs defaultValue="mark">
          <TabsList>
            <TabsTrigger value="mark">Mark attendance</TabsTrigger>
            <TabsTrigger value="enroll">Enroll student</TabsTrigger>
            <TabsTrigger value="summary">
              <ClipboardCheck className="mr-1 h-3.5 w-3.5" /> Summary
            </TabsTrigger>
          </TabsList>
          <TabsContent value="mark">
            <MarkTab schoolId={schoolId} />
          </TabsContent>
          <TabsContent value="enroll">
            <EnrollTab schoolId={schoolId} />
          </TabsContent>
          <TabsContent value="summary">
            <SummaryTab schoolId={schoolId} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
