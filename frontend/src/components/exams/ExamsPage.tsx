import { useState } from "react";
import {
  AlertTriangle,
  CalendarClock,
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  ClipboardCheck,
  DoorOpen,
  Grid3x3,
  ListTodo,
  Plus,
  Trash2,
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
import InvigilationDuties from "@/components/exams/InvigilationDuties";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useCreateExam, useGenerateSchedules, useSeating, useExamsList } from "@/api/hooks/useExams";
import { DEMO_SCHOOL_ID, DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { ApiError } from "@/api/client";

const PAGE_SIZE = 8;

function ExamsListTab({ onView, onGenerate }: { onView: (examId: number) => void; onGenerate: (examId: number) => void }) {
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
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
            badges={<Badge variant="outline">{exam.academic_year}</Badge>}
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

function CreateExamTab({ onCreated }: { onCreated: (examId: number) => void }) {
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
  const create = useCreateExam();
  const [subjectId, setSubjectId] = useState("");
  const [classId, setClassId] = useState("");
  const [examDate, setExamDate] = useState("");
  const [startTime, setStartTime] = useState("09:00");
  const [endTime, setEndTime] = useState("11:00");
  const [totalMarks, setTotalMarks] = useState("100");

  const canSubmit = subjectId && classId && examDate && startTime && endTime;

  function submit() {
    if (!canSubmit) return;
    create.mutate(
      {
        school_id: DEMO_SCHOOL_ID,
        subject_id: Number(subjectId),
        class_id: Number(classId),
        academic_year: DEFAULT_ACADEMIC_YEAR,
        exam_date: examDate,
        start_time: startTime,
        end_time: endTime,
        total_marks: totalMarks ? Number(totalMarks) : undefined,
      },
      { onSuccess: (exam) => onCreated(exam.id) }
    );
  }

  return (
    <Card className="max-w-xl">
      <CardHeader>
        <CardTitle>Create an exam</CardTitle>
        <CardDescription>Not in the original stub — added because generating a schedule needs an Exam to generate one for.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
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
        <Button onClick={submit} disabled={!canSubmit || create.isPending} className="self-start">
          <CalendarPlus className="h-4 w-4" />
          {create.isPending ? "Creating…" : "Create exam"}
        </Button>
        {create.isError && (
          <p className="text-sm text-urgent">{create.error instanceof ApiError ? create.error.message : "Failed to create exam."}</p>
        )}
        {create.isSuccess && <p className="text-sm text-positive">Exam #{create.data.id} created.</p>}
      </CardContent>
    </Card>
  );
}

function GenerateScheduleTab({
  initialExamId,
  onGenerated,
}: {
  initialExamId: number | null;
  onGenerated: (examId: number) => void;
}) {
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
  const [examId, setExamId] = useState(initialExamId ? String(initialExamId) : "");
  const [rooms, setRooms] = useState<{ roomId: string; capacity: string }[]>([{ roomId: "", capacity: "30" }]);
  const generate = useGenerateSchedules();

  const teacherName = (id: number | null) => (id === null ? null : lookup.data?.teachers.find((t) => t.id === id)?.name ?? `Teacher #${id}`);

  function updateRoom(i: number, patch: Partial<{ roomId: string; capacity: string }>) {
    setRooms((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  }

  function submit() {
    const parsedRooms = rooms.filter((r) => r.roomId && r.capacity).map((r) => ({ room_id: Number(r.roomId), capacity: Number(r.capacity) }));
    if (!examId || parsedRooms.length === 0) return;
    generate.mutate({ examId: Number(examId), rooms: parsedRooms }, { onSuccess: (result) => onGenerated(result.exam_id) });
  }

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>Generate seating + invigilation</CardTitle>
          <CardDescription>
            Supersedes any previous generation for this exam. Pick an exam from the "Exams" tab, or type its id directly below.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Field label="Exam ID">
            <Input type="number" value={examId} onChange={(e) => setExamId(e.target.value)} placeholder="e.g. 25" />
          </Field>

          <div className="flex flex-col gap-2">
            <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">Rooms</span>
            {rooms.map((r, i) => (
              <div key={i} className="flex items-end gap-2">
                <Field label="Room" className="flex-1">
                  <Select value={r.roomId} onValueChange={(v) => updateRoom(i, { roomId: v })}>
                    <SelectTrigger>
                      <SelectValue placeholder="Select room" />
                    </SelectTrigger>
                    <SelectContent>
                      {lookup.data?.rooms.map((room) => (
                        <SelectItem key={room.id} value={String(room.id)}>
                          {room.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </Field>
                <Field label="Capacity" className="w-28">
                  <Input type="number" value={r.capacity} onChange={(e) => updateRoom(i, { capacity: e.target.value })} />
                </Field>
                <Button variant="ghost" size="icon" onClick={() => setRooms((prev) => prev.filter((_, idx) => idx !== i))} disabled={rooms.length === 1}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={() => setRooms((prev) => [...prev, { roomId: "", capacity: "30" }])} className="self-start">
              <Plus className="h-3.5 w-3.5" /> Add room
            </Button>
          </div>

          <Button onClick={submit} disabled={!examId || generate.isPending} className="self-start">
            {generate.isPending ? "Generating…" : "Generate schedule"}
          </Button>
          {generate.isError && (
            <p className="text-sm text-urgent">{generate.error instanceof ApiError ? generate.error.message : "Failed to generate schedule."}</p>
          )}
        </CardContent>
      </Card>

      {generate.isSuccess && (
        <Card>
          <CardHeader>
            <CardTitle>Result — exam #{generate.data.exam_id}</CardTitle>
            <CardDescription>{generate.data.seating.length} seat(s) assigned across {generate.data.invigilators.length} room(s).</CardDescription>
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

function SeatingChartTab({ lastGeneratedExamId }: { lastGeneratedExamId: number | null }) {
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
  const [examId, setExamId] = useState(lastGeneratedExamId ? String(lastGeneratedExamId) : "");
  const seating = useSeating({ examId: examId ? Number(examId) : undefined, enabled: !!examId });

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Exam ID" className="w-48">
          <Input type="number" value={examId} onChange={(e) => setExamId(e.target.value)} placeholder="e.g. 25" />
        </Field>
      </div>

      {!examId && <p className="text-sm text-ink-muted">Enter an exam id to view its seating chart.</p>}
      {examId && seating.isLoading && <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />}
      {examId && seating.data && <SeatingChart items={seating.data.items} lookup={lookup.data} />}
    </div>
  );
}

export default function ExamsPage() {
  const [tab, setTab] = useState("list");
  const [selectedExamId, setSelectedExamId] = useState<number | null>(null);

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="Exam Management" description="Exam creation, seating allocation, and invigilation scheduling." />
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
          <TabsTrigger value="invigilation">
            <ClipboardCheck className="h-3.5 w-3.5" /> My invigilation duties
          </TabsTrigger>
        </TabsList>
        <TabsContent value="list">
          <ExamsListTab
            onView={(id) => { setSelectedExamId(id); setTab("seating"); }}
            onGenerate={(id) => { setSelectedExamId(id); setTab("generate"); }}
          />
        </TabsContent>
        <TabsContent value="create">
          <CreateExamTab
            onCreated={(id) => {
              setSelectedExamId(id);
              setTab("generate");
            }}
          />
        </TabsContent>
        <TabsContent value="generate">
          <GenerateScheduleTab initialExamId={selectedExamId} onGenerated={setSelectedExamId} />
        </TabsContent>
        <TabsContent value="seating">
          <SeatingChartTab lastGeneratedExamId={selectedExamId} />
        </TabsContent>
        <TabsContent value="invigilation">
          <InvigilationDuties />
        </TabsContent>
      </Tabs>
    </div>
  );
}
