import { useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  ClipboardCheck,
  NotebookPen,
  ScanFace,
  Upload,
  UserPlus,
  Video,
  XCircle,
} from "lucide-react";
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
import {
  useEnrollStudent,
  useAttendanceEnrollments,
  useMarkAttendance,
  useAttendanceSummary,
  useReviewAttendanceRecord,
} from "@/api/hooks/useAttendance";
import { useCurrentUser } from "@/api/hooks/useAuth";
import LiveCameraCapture from "@/components/attendance/LiveCameraCapture";
import AttendanceRegister from "@/components/attendance/AttendanceRegister";
import AttendanceAnalytics from "@/components/attendance/AttendanceAnalytics";
import { DEFAULT_ACADEMIC_YEAR, DAY_LABELS } from "@/lib/constants";
import { daysAgoIso, todayIso } from "@/lib/dates";
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

/** Turns the backend's plain-string 422 reason into a clearer, more
 * actionable message for this specific "exactly one face" requirement -
 * the raw message ("Expected exactly one face in the reference photo, found
 * 2") is accurate but easy to misread as a generic failure rather than "you
 * picked a group photo, use single-face photos instead". */
function describeEnrollError(message: string): string {
  const multiMatch = message.match(/found (\d+)/i);
  if (multiMatch) {
    return `This photo has ${multiMatch[1]} faces - enroll each student separately with their own single-face photo.`;
  }
  if (/no face detected/i.test(message)) {
    return "No face was detected in this photo. Try a clearer, well-lit photo showing just this student's face.";
  }
  return message;
}

function EnrollTab({ schoolId }: { schoolId: number }) {
  const lookup = useReferenceLookup(schoolId);
  const [studentId, setStudentId] = useState<string>("");
  const [file, setFile] = useState<File | null>(null);
  const enroll = useEnrollStudent();
  // The real, persisted list - refetched on mount and after each successful
  // enrollment, so it survives a full page reload or logout/login, unlike an
  // in-memory session list.
  const enrollments = useAttendanceEnrollments(schoolId);

  function handleSubmit() {
    if (!studentId || !file) return;
    enroll.mutate(
      { studentId: Number(studentId), file },
      {
        onSuccess: () => {
          // Reset so the form is ready for the next student in the same session.
          setStudentId("");
          setFile(null);
        },
      }
    );
  }

  return (
    <div className="grid items-start gap-3 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Enroll a reference photo</CardTitle>
          <CardDescription>One clear photo containing exactly one face. Stored as a face embedding for future recognition.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/5 px-3.5 py-2.5 text-xs text-warning">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              The photo must contain exactly one face. A group photo (e.g. two students together) will be rejected -
              enroll each student separately with their own photo.
            </span>
          </div>
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
              {enroll.error instanceof ApiError ? describeEnrollError(enroll.error.message) : "Enrollment failed."}
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Enrolled students</CardTitle>
          <CardDescription>Real, persisted enrollments for this school - stays here across page reloads and logins, not just this session.</CardDescription>
        </CardHeader>
        <CardContent>
          {enrollments.isLoading && <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />}
          {enrollments.isSuccess && enrollments.data.length === 0 && (
            <p className="text-sm text-ink-muted">No students enrolled yet.</p>
          )}
          {enrollments.isSuccess && enrollments.data.length > 0 && (
            <div className="flex flex-col gap-2">
              {enrollments.data.map((result) => (
                <div
                  key={result.id}
                  className="flex flex-col gap-1 rounded-xl border border-border bg-elevated/40 px-3.5 py-2.5 text-sm"
                >
                  <div className="flex items-center gap-2">
                    <Badge variant="positive">Enrolled</Badge>
                    <span className="font-medium text-ink">{result.student_name}</span>
                  </div>
                  <p className="text-xs text-ink-muted">
                    Embedding <span className="font-mono text-ink">#{result.id}</span> stored for student{" "}
                    <span className="font-mono text-ink">#{result.student_id}</span>
                  </p>
                  <p className="font-mono text-xs text-ink-muted">{new Date(result.enrolled_at).toLocaleString()}</p>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

type CaptureMode = "upload" | "live";

/** Upload works everywhere; live camera needs a permitted camera on a secure
 * origin - so both stay available rather than replacing one with the other. */
function ModeToggle({ mode, onChange }: { mode: CaptureMode; onChange: (mode: CaptureMode) => void }) {
  const options: { value: CaptureMode; label: string; icon: typeof Upload }[] = [
    { value: "upload", label: "Upload Photo", icon: Upload },
    { value: "live", label: "Live Camera", icon: Video },
  ];
  return (
    <div className="inline-flex self-start rounded-xl border border-border bg-elevated/40 p-1">
      {options.map((option) => {
        const Icon = option.icon;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            aria-pressed={mode === option.value}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              mode === option.value
                ? "bg-accent text-accent-foreground shadow-sm"
                : "text-ink-muted hover:text-accent"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function MarkTab({ schoolId }: { schoolId: number }) {
  const timetable = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR });
  const lookup = useReferenceLookup(schoolId);
  const [mode, setMode] = useState<CaptureMode>("upload");
  const [slotId, setSlotId] = useState<string>("");
  const [date, setDate] = useState<string>(todayIso);
  const [file, setFile] = useState<File | null>(null);
  const mark = useMarkAttendance();
  const review = useReviewAttendanceRecord();
  const [reviewedIds, setReviewedIds] = useState<Set<number>>(new Set());
  // Only populated once an admin picks a DIFFERENT student than the one the
  // CV pipeline originally matched for a needs_review row - "the system
  // detected this face as X, but it's actually Y".
  const [reassignments, setReassignments] = useState<Record<number, number>>({});

  const slotLabel = (s: TimetableSlot) => {
    const subject = lookup.data?.subjects.find((x) => x.id === s.subject_id)?.name ?? `Subject #${s.subject_id}`;
    const cls = lookup.data?.classes.find((x) => x.id === s.class_id)?.name ?? `Class #${s.class_id}`;
    return `${DAY_LABELS[s.day_of_week]} ${s.start_time.slice(0, 5)} · ${subject} · ${cls}`;
  };

  function handleSubmit() {
    if (!slotId || !file) return;
    setReviewedIds(new Set());
    setReassignments({});
    mark.mutate({ timetableSlotId: Number(slotId), file, date });
  }

  function handleReview(recordId: number, originalStudentId: number, status: "present" | "absent") {
    const reassignedTo = reassignments[recordId];
    const studentId = reassignedTo !== undefined && reassignedTo !== originalStudentId ? reassignedTo : undefined;
    review.mutate(
      { recordId, status, studentId },
      { onSuccess: () => setReviewedIds((prev) => new Set(prev).add(recordId)) }
    );
  }

  const studentName = (id: number) => lookup.data?.students.find((s) => s.id === id)?.name ?? `Student #${id}`;

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>Mark attendance</CardTitle>
          <CardDescription>
            Pick the period and date, then either upload a classroom photo or run the live camera. Either way, every
            enrolled face in the slot's class is matched against the frame.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Timetable slot" className="min-w-64 flex-1">
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
          </div>
          <ModeToggle mode={mode} onChange={setMode} />
        </CardContent>
      </Card>

      {mode === "live" ? (
        slotId ? (
          <LiveCameraCapture timetableSlotId={Number(slotId)} date={date} />
        ) : (
          <Card>
            <CardContent className="py-6">
              <p className="text-sm text-ink-muted">Select a timetable slot above to start the live camera.</p>
            </CardContent>
          </Card>
        )
      ) : (
        <div className="grid items-start gap-3 lg:grid-cols-2">
          <Card>
            <CardHeader>
              <CardTitle>Run recognition on a classroom photo</CardTitle>
              <CardDescription>One-shot recognition on a single uploaded photo.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
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
                      const editable = m.needs_review && !wasReviewed;
                      const selectedStudentId = reassignments[m.record_id] ?? m.student_id;
                      return (
                        <TableRow key={m.record_id}>
                          <TableCell className="font-medium">
                            {editable ? (
                              <Select
                                value={String(selectedStudentId)}
                                onValueChange={(v) => setReassignments((prev) => ({ ...prev, [m.record_id]: Number(v) }))}
                              >
                                <SelectTrigger className="h-8 w-40">
                                  <SelectValue />
                                </SelectTrigger>
                                <SelectContent>
                                  {mark.data.class_roster.map((s) => (
                                    <SelectItem key={s.student_id} value={String(s.student_id)}>
                                      {s.name}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            ) : (
                              // After a reassignment is confirmed, show the corrected
                              // student - not the original (wrong) detected one.
                              studentName(selectedStudentId)
                            )}
                          </TableCell>
                          <TableCell>
                            <ConfidenceBadge confidence={m.confidence} needsReview={m.needs_review} />
                          </TableCell>
                          <TableCell>
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span className={cn("text-xs", m.already_marked ? "text-ink-muted" : "text-positive")}>
                                {m.already_marked ? "already marked" : "newly marked"}
                              </span>
                              {editable && (
                                <>
                                  <Badge variant="urgent">needs review</Badge>
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-6 px-2 text-[0.6875rem]"
                                    disabled={review.isPending}
                                    onClick={() => handleReview(m.record_id, m.student_id, "present")}
                                  >
                                    <CheckCircle2 className="h-3 w-3" /> Confirm
                                  </Button>
                                  <Button
                                    variant="outline"
                                    size="sm"
                                    className="h-6 px-2 text-[0.6875rem]"
                                    disabled={review.isPending}
                                    onClick={() => handleReview(m.record_id, m.student_id, "absent")}
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
      )}
    </div>
  );
}

const daysAgo = daysAgoIso;

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
  const user = useCurrentUser().data;
  const schoolId = user?.school_id;
  // POST /attendance/mark and /enroll are admin+teacher only - a principal can
  // read every register, correct it and analyse it, but doesn't run the camera.
  // Showing those tabs to a principal would only produce a 403 on submit.
  const canCapture = user?.role === "admin" || user?.role === "teacher";

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Attendance"
        description="Mark attendance from the classroom camera or by hand, read any day's register back, correct low-confidence matches, and analyse trends by period, class and student."
      />
      {schoolId == null ? (
        <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />
      ) : (
        <Tabs defaultValue={canCapture ? "mark" : "register"}>
          <TabsList>
            {canCapture && <TabsTrigger value="mark">Mark attendance</TabsTrigger>}
            <TabsTrigger value="register">
              <NotebookPen className="mr-1 h-3.5 w-3.5" /> Day register
            </TabsTrigger>
            <TabsTrigger value="analytics">
              <BarChart3 className="mr-1 h-3.5 w-3.5" /> Analytics
            </TabsTrigger>
            {canCapture && <TabsTrigger value="enroll">Enroll student</TabsTrigger>}
            <TabsTrigger value="summary">
              <ClipboardCheck className="mr-1 h-3.5 w-3.5" /> Summary
            </TabsTrigger>
          </TabsList>
          {canCapture && (
            <TabsContent value="mark">
              <MarkTab schoolId={schoolId} />
            </TabsContent>
          )}
          <TabsContent value="register">
            <AttendanceRegister schoolId={schoolId} />
          </TabsContent>
          <TabsContent value="analytics">
            <AttendanceAnalytics schoolId={schoolId} />
          </TabsContent>
          {canCapture && (
            <TabsContent value="enroll">
              <EnrollTab schoolId={schoolId} />
            </TabsContent>
          )}
          <TabsContent value="summary">
            <SummaryTab schoolId={schoolId} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
