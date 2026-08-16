import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CalendarClock,
  CalendarPlus,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  DoorOpen,
  Grid3x3,
  ListTodo,
} from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import EntityCard from "@/components/shared/EntityCard";
import SeatingChart from "@/components/exams/SeatingChart";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import {
  useCreateExam,
  useCreateExamsForGrade,
  useGenerateSchedules,
  useRoomSuggestions,
  useSeating,
  useExamsList,
} from "@/api/hooks/useExams";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { ApiError } from "@/api/client";
import type { ExamType } from "@/api/types";

const PAGE_SIZE = 8;

const EXAM_TYPES: { value: ExamType; label: string }[] = [
  { value: "class_test", label: "Class test" },
  { value: "unit_test", label: "Unit test" },
  { value: "mid_term", label: "Mid term" },
  { value: "end_term", label: "End term" },
];

const examTypeLabel = (type: ExamType | null) => EXAM_TYPES.find((t) => t.value === type)?.label ?? null;

function ExamsListTab({
  schoolId,
  onView,
  onGenerate,
}: {
  schoolId: number;
  onView: (examId: number) => void;
  onGenerate: (examId: number) => void;
}) {
  const lookup = useReferenceLookup(schoolId);
  const [classId, setClassId] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [page, setPage] = useState(1);

  const list = useExamsList({
    classId: classId ? Number(classId) : undefined,
    subjectId: subjectId ? Number(subjectId) : undefined,
    page,
    pageSize: PAGE_SIZE,
  });

  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1;
  const subjectName = (id: number) => lookup.data?.subjects.find((s) => s.id === id)?.name ?? `Subject #${id}`;
  const className = (id: number) => lookup.data?.classes.find((c) => c.id === id)?.name ?? `Class #${id}`;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Class" className="w-48">
          <Select value={classId} onValueChange={(v) => { setClassId(v); setPage(1); }}>
            <SelectTrigger>
              <SelectValue placeholder="All classes" />
            </SelectTrigger>
            <SelectContent>
              {lookup.data?.classes.map((c) => (
                <SelectItem key={c.id} value={String(c.id)}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Subject" className="w-48">
          <Select value={subjectId} onValueChange={(v) => { setSubjectId(v); setPage(1); }}>
            <SelectTrigger>
              <SelectValue placeholder="All subjects" />
            </SelectTrigger>
            <SelectContent>
              {lookup.data?.subjects.map((s) => (
                <SelectItem key={s.id} value={String(s.id)}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>

      {list.isLoading && <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />}
      {list.error && (
        <p className="text-sm text-urgent">{list.error instanceof ApiError ? list.error.message : "Failed to load exams."}</p>
      )}
      {list.data && list.data.items.length === 0 && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-ink-muted">No exams match this filter.</CardContent>
        </Card>
      )}

      <div className="flex flex-col gap-2">
        {list.data?.items.map((exam) => (
          <EntityCard
            key={exam.id}
            icon={CalendarClock}
            tone="neutral"
            title={`${subjectName(exam.subject_id)} · ${className(exam.class_id)}`}
            badges={
              <>
                <Badge variant="outline">{exam.academic_year}</Badge>
                {examTypeLabel(exam.exam_type) && <Badge variant="outline">{examTypeLabel(exam.exam_type)}</Badge>}
              </>
            }
            message={`${exam.exam_date} · ${exam.start_time.slice(0, 5)}–${exam.end_time.slice(0, 5)}`}
            meta={`Exam #${exam.id}`}
            actions={
              <div className="flex gap-1.5">
                <Button variant="outline" size="sm" onClick={() => onView(exam.id)}>
                  Seating
                </Button>
                <Button size="sm" onClick={() => onGenerate(exam.id)}>
                  Generate
                </Button>
              </div>
            }
          />
        ))}
      </div>

      {list.data && list.data.total > list.data.page_size && (
        <div className="flex items-center justify-between pt-1">
          <span className="text-xs text-ink-faint">
            Page {list.data.page} of {totalPages} · {list.data.total} total
          </span>
          <div className="flex gap-1.5">
            <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

function CreateExamTab({ schoolId, onCreated }: { schoolId: number; onCreated: (examId: number) => void }) {
  const lookup = useReferenceLookup(schoolId);
  const create = useCreateExam();
  const createForGrade = useCreateExamsForGrade();
  const [scope, setScope] = useState<"section" | "grade">("section");
  const [subjectId, setSubjectId] = useState("");
  const [classId, setClassId] = useState("");
  const [gradeLevel, setGradeLevel] = useState("");
  const [examType, setExamType] = useState<ExamType | "">("");
  const [examDate, setExamDate] = useState("");
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("11:00");
  const [totalMarks, setTotalMarks] = useState("100");

  const gradeOptions = useMemo(() => {
    const seen = new Map<number, string>();
    for (const c of lookup.data?.classes ?? []) {
      if (c.grade_level == null) continue;
      seen.set(c.grade_level, c.grade_label ?? `Grade ${c.grade_level}`);
    }
    return [...seen.entries()].sort((a, b) => a[0] - b[0]);
  }, [lookup.data?.classes]);

  const target = scope === "section" ? classId : gradeLevel;
  const canSubmit = subjectId && target && examDate && startTime && endTime;

  function submit() {
    if (!canSubmit) return;
    const shared = {
      school_id: schoolId,
      subject_id: Number(subjectId),
      academic_year: DEFAULT_ACADEMIC_YEAR,
      exam_type: examType || undefined,
      exam_date: examDate,
      start_time: startTime,
      end_time: endTime,
      total_marks: totalMarks ? Number(totalMarks) : undefined,
    };
    if (scope === "section") {
      create.mutate({ ...shared, class_id: Number(classId) }, { onSuccess: (exam) => onCreated(exam.id) });
    } else {
      createForGrade.mutate(
        { ...shared, grade_level: Number(gradeLevel) },
        { onSuccess: (result) => onCreated(result.created[0].id) }
      );
    }
  }

  const isPending = create.isPending || createForGrade.isPending;
  const error = create.error ?? createForGrade.error;

  return (
    <Card className="max-w-xl">
      <CardHeader>
        <CardTitle>Create an exam</CardTitle>
        <CardDescription>Not in the original stub — added because generating a schedule needs an Exam to generate one for.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Field label="Scope">
          <Select value={scope} onValueChange={(v) => setScope(v as typeof scope)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="section">One class/section</SelectItem>
              <SelectItem value="grade">Whole grade (every active section)</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Field label="Subject">
          <Select value={subjectId} onValueChange={setSubjectId}>
            <SelectTrigger>
              <SelectValue placeholder="Select a subject" />
            </SelectTrigger>
            <SelectContent>
              {lookup.data?.subjects.map((s) => (
                <SelectItem key={s.id} value={String(s.id)}>
                  {s.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        {scope === "section" ? (
          <Field label="Class">
            <Select value={classId} onValueChange={setClassId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a class" />
              </SelectTrigger>
              <SelectContent>
                {lookup.data?.classes.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        ) : (
          <Field label="Grade" hint="Creates one exam per active section in this grade, all with the same subject/date/time.">
            <Select value={gradeLevel} onValueChange={setGradeLevel}>
              <SelectTrigger>
                <SelectValue placeholder="Select a grade" />
              </SelectTrigger>
              <SelectContent>
                {gradeOptions.map(([level, label]) => (
                  <SelectItem key={level} value={String(level)}>
                    {label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        )}
        <Field label="Exam type (optional)">
          <Select value={examType} onValueChange={(v) => setExamType(v as ExamType)}>
            <SelectTrigger>
              <SelectValue placeholder="Not set" />
            </SelectTrigger>
            <SelectContent>
              {EXAM_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Exam date">
          <Input type="date" value={examDate} onChange={(e) => setExamDate(e.target.value)} />
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Start time">
            <Input type="time" value={startTime} onChange={(e) => setStartTime(e.target.value)} />
          </Field>
          <Field label="End time">
            <Input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
          </Field>
        </div>
        <Field label="Total marks (optional)">
          <Input type="number" value={totalMarks} onChange={(e) => setTotalMarks(e.target.value)} />
        </Field>
        <Button onClick={submit} disabled={!canSubmit || isPending} className="self-start">
          <CalendarPlus className="h-4 w-4" />
          {isPending ? "Creating…" : scope === "grade" ? "Create exams" : "Create exam"}
        </Button>
        {error && <p className="text-sm text-urgent">{error instanceof ApiError ? error.message : "Failed to create exam."}</p>}
        {create.isSuccess && <p className="text-sm text-positive">Exam #{create.data.id} created.</p>}
        {createForGrade.isSuccess && (
          <p className="text-sm text-positive">{createForGrade.data.created.length} exam(s) created, one per section.</p>
        )}
      </CardContent>
    </Card>
  );
}

function GenerateScheduleTab({
  schoolId,
  initialExamId,
  onGenerated,
}: {
  schoolId: number;
  initialExamId: number | null;
  onGenerated: (examId: number) => void;
}) {
  const lookup = useReferenceLookup(schoolId);
  const examsList = useExamsList({ pageSize: 100 });
  const [examId, setExamId] = useState(initialExamId ? String(initialExamId) : "");
  const suggestions = useRoomSuggestions(examId ? Number(examId) : undefined);
  const [selectedRoomIds, setSelectedRoomIds] = useState<Set<number>>(new Set());
  const [phase, setPhase] = useState<"idle" | "previewed" | "confirmed">("idle");
  const generate = useGenerateSchedules();

  // A newly picked exam's suggestions load async - default-select whatever's
  // suggested (still just a default; every available room is shown, toggleable).
  useEffect(() => {
    if (suggestions.data) {
      setSelectedRoomIds(new Set(suggestions.data.suggested_room_ids));
      setPhase("idle");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [suggestions.data?.exam_id]);

  const teacherName = (id: number | null) => (id === null ? null : lookup.data?.teachers.find((t) => t.id === id)?.name ?? `Teacher #${id}`);
  const examLabel = (id: number) => {
    const e = examsList.data?.items.find((x) => x.id === id);
    if (!e) return `Exam #${id}`;
    const subj = lookup.data?.subjects.find((s) => s.id === e.subject_id)?.name ?? `Subject #${e.subject_id}`;
    const cls = lookup.data?.classes.find((c) => c.id === e.class_id)?.name ?? `Class #${e.class_id}`;
    return `${subj} · ${cls} · ${e.exam_date}`;
  };

  function toggleRoom(roomId: number) {
    setSelectedRoomIds((prev) => {
      const next = new Set(prev);
      if (next.has(roomId)) next.delete(roomId);
      else next.add(roomId);
      return next;
    });
    setPhase("idle");
  }

  const rooms = (suggestions.data?.available_rooms ?? [])
    .filter((r) => selectedRoomIds.has(r.room_id))
    .map((r) => ({ room_id: r.room_id, capacity: r.capacity }));

  function preview() {
    if (!examId || rooms.length === 0) return;
    generate.mutate({ examId: Number(examId), rooms, dryRun: true }, { onSuccess: () => setPhase("previewed") });
  }

  function confirm() {
    if (!examId || rooms.length === 0) return;
    generate.mutate(
      { examId: Number(examId), rooms, dryRun: false },
      { onSuccess: (result) => { setPhase("confirmed"); onGenerated(result.exam_id); } }
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>Generate seating + invigilation</CardTitle>
          <CardDescription>Preview first - nothing is saved until you confirm. Confirming supersedes any previous generation for this exam.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Field label="Exam">
            <Select value={examId} onValueChange={(v) => { setExamId(v); setPhase("idle"); }}>
              <SelectTrigger>
                <SelectValue placeholder="Select an exam" />
              </SelectTrigger>
              <SelectContent>
                {examsList.data?.items.map((e) => (
                  <SelectItem key={e.id} value={String(e.id)}>
                    {examLabel(e.id)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>

          {examId && (
            <div className="flex flex-col gap-2">
              <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">
                Rooms{suggestions.data ? ` · ${suggestions.data.headcount} student(s) to seat` : ""}
              </span>
              {suggestions.isLoading && <div className="h-16 animate-pulse rounded-lg bg-elevated/60" />}
              {suggestions.data?.available_rooms.length === 0 && (
                <p className="text-sm text-urgent">No rooms are available for this exam's date/time — every room is booked by another exam.</p>
              )}
              {suggestions.data?.available_rooms.map((r) => (
                <label
                  key={r.room_id}
                  className="flex cursor-pointer items-center justify-between rounded-xl border border-border bg-card px-3.5 py-2 text-sm"
                >
                  <span className="flex items-center gap-2 text-ink">
                    <input type="checkbox" checked={selectedRoomIds.has(r.room_id)} onChange={() => toggleRoom(r.room_id)} />
                    {r.room_name} · {r.capacity} seats
                  </span>
                  {suggestions.data!.suggested_room_ids.includes(r.room_id) && <Badge variant="positive">Suggested</Badge>}
                </label>
              ))}
            </div>
          )}

          <div className="flex gap-2">
            <Button variant="outline" onClick={preview} disabled={!examId || rooms.length === 0 || generate.isPending} className="self-start">
              {generate.isPending && phase !== "previewed" ? "Checking…" : "Preview"}
            </Button>
            {phase === "previewed" && (
              <Button onClick={confirm} disabled={generate.isPending} className="self-start">
                {generate.isPending ? "Saving…" : "Confirm & save"}
              </Button>
            )}
          </div>
          {generate.isError && (
            <p className="text-sm text-urgent">{generate.error instanceof ApiError ? generate.error.message : "Failed to generate schedule."}</p>
          )}
        </CardContent>
      </Card>

      {generate.isSuccess && (phase === "previewed" || phase === "confirmed") && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {phase === "confirmed" ? (
                <>
                  <CheckCircle2 className="h-4 w-4 text-positive" /> Saved — {examLabel(generate.data.exam_id)}
                </>
              ) : (
                `Preview — ${examLabel(generate.data.exam_id)}`
              )}
            </CardTitle>
            <CardDescription>
              {phase === "previewed" ? "Nothing saved yet - review, then confirm. " : ""}
              {generate.data.seating.length} seat(s) assigned across {generate.data.invigilators.length} room(s).
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3">
            {generate.data.unassigned_rooms.length > 0 && (
              <div className="flex items-start gap-2 rounded-xl border border-urgent/30 bg-urgent/5 px-3.5 py-2.5 text-sm text-urgent">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  No eligible invigilator was found for room(s) {generate.data.unassigned_rooms.join(", ")} — an honest gap, not silently
                  hidden. Assign a teacher manually for these rooms.
                </span>
              </div>
            )}
            <div className="flex flex-col gap-1.5">
              <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">Invigilators</span>
              {generate.data.invigilators.map((inv) => (
                <div key={inv.room_id} className="flex items-center justify-between rounded-xl bg-elevated/60 px-3.5 py-2 text-sm">
                  <span className="flex items-center gap-1.5 text-ink">
                    <DoorOpen className="h-3.5 w-3.5 text-ink-muted" /> Room #{inv.room_id}
                  </span>
                  {teacherName(inv.teacher_id) ? (
                    <span className="text-ink-muted">{teacherName(inv.teacher_id)}</span>
                  ) : (
                    <Badge variant="urgent">Unassigned</Badge>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

function SeatingChartTab({ schoolId, lastGeneratedExamId }: { schoolId: number; lastGeneratedExamId: number | null }) {
  const lookup = useReferenceLookup(schoolId);
  const examsList = useExamsList({ pageSize: 100 });
  const [examId, setExamId] = useState(lastGeneratedExamId ? String(lastGeneratedExamId) : "");
  const seating = useSeating({ examId: examId ? Number(examId) : undefined, enabled: !!examId });

  const examLabel = (id: number) => {
    const e = examsList.data?.items.find((x) => x.id === id);
    if (!e) return `Exam #${id}`;
    const subj = lookup.data?.subjects.find((s) => s.id === e.subject_id)?.name ?? `Subject #${e.subject_id}`;
    const cls = lookup.data?.classes.find((c) => c.id === e.class_id)?.name ?? `Class #${e.class_id}`;
    return `${subj} · ${cls} · ${e.exam_date}`;
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Exam" className="w-72">
          <Select value={examId} onValueChange={setExamId}>
            <SelectTrigger>
              <SelectValue placeholder="Select an exam" />
            </SelectTrigger>
            <SelectContent>
              {examsList.data?.items.map((e) => (
                <SelectItem key={e.id} value={String(e.id)}>
                  {examLabel(e.id)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>

      {!examId && <p className="text-sm text-ink-muted">Select an exam to view its seating chart.</p>}
      {examId && seating.isLoading && <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />}
      {examId && seating.data && <SeatingChart items={seating.data.items} lookup={lookup.data} />}
    </div>
  );
}

export default function ExamsPage() {
  const [tab, setTab] = useState("list");
  const [selectedExamId, setSelectedExamId] = useState<number | null>(null);
  const schoolId = useCurrentUser().data?.school_id;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="Exam Management" description="Exam creation, seating allocation, and invigilation scheduling." />
      {schoolId == null ? (
        <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />
      ) : (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="list">
              <ListTodo className="h-3.5 w-3.5" /> Exams
            </TabsTrigger>
            <TabsTrigger value="create">
              <CalendarPlus className="h-3.5 w-3.5" /> Create exam
            </TabsTrigger>
            <TabsTrigger value="generate">
              <Grid3x3 className="h-3.5 w-3.5" /> Generate schedule
            </TabsTrigger>
            <TabsTrigger value="seating">
              <DoorOpen className="h-3.5 w-3.5" /> Seating chart
            </TabsTrigger>
          </TabsList>
          <TabsContent value="list">
            <ExamsListTab
              schoolId={schoolId}
              onView={(id) => { setSelectedExamId(id); setTab("seating"); }}
              onGenerate={(id) => { setSelectedExamId(id); setTab("generate"); }}
            />
          </TabsContent>
          <TabsContent value="create">
            <CreateExamTab
              schoolId={schoolId}
              onCreated={(id) => {
                setSelectedExamId(id);
                setTab("generate");
              }}
            />
          </TabsContent>
          <TabsContent value="generate">
            <GenerateScheduleTab schoolId={schoolId} initialExamId={selectedExamId} onGenerated={setSelectedExamId} />
          </TabsContent>
          <TabsContent value="seating">
            <SeatingChartTab schoolId={schoolId} lastGeneratedExamId={selectedExamId} />
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
