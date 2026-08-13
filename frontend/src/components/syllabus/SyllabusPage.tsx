import { useState } from "react";
import { BookOpenCheck, ClipboardList, FilePlus2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger } from "@/components/ui/dialog";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import ProgressBar from "@/components/shared/ProgressBar";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useSyllabusSummary, useCreateSyllabusPlan, useLogCheckpoint } from "@/api/hooks/useSyllabus";
import { DEFAULT_ACADEMIC_YEAR, DEMO_SCHOOL_ID } from "@/lib/constants";
import { ApiError } from "@/api/client";

const STATUS_VARIANT: Record<string, "urgent" | "positive" | "accent"> = {
  behind: "urgent",
  on_pace: "positive",
  ahead: "accent",
};

function NewPlanDialog() {
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
  const create = useCreateSyllabusPlan();
  const [open, setOpen] = useState(false);
  const [classId, setClassId] = useState("");
  const [subjectId, setSubjectId] = useState("");
  const [totalUnits, setTotalUnits] = useState("10");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");

  function submit() {
    if (!classId || !subjectId || !totalUnits || !start || !end) return;
    create.mutate(
      {
        class_id: Number(classId),
        subject_id: Number(subjectId),
        academic_year: DEFAULT_ACADEMIC_YEAR,
        total_units: Number(totalUnits),
        term_start_date: start,
        term_end_date: end,
      },
      { onSuccess: () => setOpen(false) }
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <FilePlus2 className="h-4 w-4" /> New plan
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New syllabus plan</DialogTitle>
          <DialogDescription>A flat unit count across a term — no week-by-week breakdown.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Class">
            <Select value={classId} onValueChange={setClassId}>
              <SelectTrigger><SelectValue placeholder="Select class" /></SelectTrigger>
              <SelectContent>
                {lookup.data?.classes.map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Subject">
            <Select value={subjectId} onValueChange={setSubjectId}>
              <SelectTrigger><SelectValue placeholder="Select subject" /></SelectTrigger>
              <SelectContent>
                {lookup.data?.subjects.map((s) => <SelectItem key={s.id} value={String(s.id)}>{s.name}</SelectItem>)}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Total units">
            <Input type="number" value={totalUnits} onChange={(e) => setTotalUnits(e.target.value)} />
          </Field>
          <Field label="Term start">
            <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Field label="Term end">
            <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
          </Field>
          {create.isError && (
            <p className="text-sm text-urgent">{create.error instanceof ApiError ? create.error.message : "Failed to create plan."}</p>
          )}
          <Button onClick={submit} disabled={create.isPending} className="self-start">
            {create.isPending ? "Creating…" : "Create plan"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function LogCheckpointDialog({ plans }: { plans: { plan_id: number; class_name: string; subject_name: string; checkpoints_logged: number }[] }) {
  const log = useLogCheckpoint();
  const [open, setOpen] = useState(false);
  const [planId, setPlanId] = useState("");
  const [topic, setTopic] = useState("");

  const selectedPlan = plans.find((p) => String(p.plan_id) === planId);

  function submit() {
    if (!planId || !topic.trim()) return;
    log.mutate(
      { plan_id: Number(planId), topic_label: topic, sequence_number: (selectedPlan?.checkpoints_logged ?? 0) + 1 },
      { onSuccess: () => { setOpen(false); setTopic(""); } }
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <ClipboardList className="h-4 w-4" /> Log checkpoint
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Log a checkpoint</DialogTitle>
          <DialogDescription>One unit of actual progress.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Plan">
            <Select value={planId} onValueChange={setPlanId}>
              <SelectTrigger><SelectValue placeholder="Select plan" /></SelectTrigger>
              <SelectContent>
                {plans.map((p) => (
                  <SelectItem key={p.plan_id} value={String(p.plan_id)}>
                    {p.class_name} · {p.subject_name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Topic" hint="e.g. Algebra basics">
            <Input value={topic} onChange={(e) => setTopic(e.target.value)} />
          </Field>
          {log.isError && <p className="text-sm text-urgent">{log.error instanceof ApiError ? log.error.message : "Failed to log checkpoint."}</p>}
          <Button onClick={submit} disabled={!planId || !topic.trim() || log.isPending} className="self-start">
            {log.isPending ? "Logging…" : "Log checkpoint"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function SyllabusPage() {
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
  const [classId, setClassId] = useState("all");
  const summary = useSyllabusSummary({ classId: classId === "all" ? undefined : Number(classId), academicYear: DEFAULT_ACADEMIC_YEAR });

  const items = summary.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Syllabus Tracking"
        description="Expected vs. actual pace per class/subject."
        actions={
          <>
            <NewPlanDialog />
            <LogCheckpointDialog plans={items} />
          </>
        }
      />

      <Field label="Filter by class" className="w-56">
        <Select value={classId} onValueChange={setClassId}>
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All classes</SelectItem>
            {lookup.data?.classes.map((c) => <SelectItem key={c.id} value={String(c.id)}>{c.name}</SelectItem>)}
          </SelectContent>
        </Select>
      </Field>

      {summary.isLoading && <div className="h-32 animate-pulse rounded-lg bg-elevated/60" />}
      {items.length === 0 && !summary.isLoading && (
        <Card>
          <CardContent className="flex flex-col items-center gap-1 py-6 text-center">
            <BookOpenCheck className="h-6 w-6 text-ink-muted" />
            <p className="font-display text-sm font-medium text-ink">No syllabus plans yet</p>
            <p className="text-xs text-ink-muted">Create one to start tracking pace.</p>
          </CardContent>
        </Card>
      )}
      {items.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Class</TableHead>
              <TableHead>Subject</TableHead>
              <TableHead>Progress</TableHead>
              <TableHead>Checkpoints</TableHead>
              <TableHead>Drift</TableHead>
              <TableHead>Status</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((item) => (
              <TableRow key={item.plan_id}>
                <TableCell className="font-medium">{item.class_name}</TableCell>
                <TableCell className="text-ink-muted">{item.subject_name}</TableCell>
                <TableCell className="w-48">
                  <ProgressBar
                    value={item.actual_fraction}
                    target={item.expected_fraction}
                    tone={item.status === "behind" ? "urgent" : item.status === "ahead" ? "accent" : "positive"}
                  />
                </TableCell>
                <TableCell className="font-mono tabular-nums text-ink-muted">
                  {item.checkpoints_logged}/{item.total_units}
                </TableCell>
                <TableCell className="font-mono tabular-nums">{(item.drift * 100).toFixed(0)}%</TableCell>
                <TableCell>
                  <Badge variant={STATUS_VARIANT[item.status]}>{item.status.replace("_", " ")}</Badge>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
