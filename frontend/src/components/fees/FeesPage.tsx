import { useEffect, useState } from "react";
import { BadgeCheck, BellRing, CreditCard, Receipt, RefreshCw, Users, Wallet, X } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger } from "@/components/ui/dialog";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import EntityCard from "@/components/shared/EntityCard";
import StatTile from "@/components/shared/StatTile";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import {
  useFeeSchedules,
  useCreateFeeSchedule,
  useFeeStatus,
  useTriggerReminders,
  useRecordPayment,
  useRunInvoicing,
  useMarkFeePaid,
  useGenerateScheduleRecords,
} from "@/api/hooks/useFees";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useParentChildren } from "@/api/hooks/useParent";
import { useAuthStore } from "@/store/authStore";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { ApiError } from "@/api/client";
import type { FeeSchedule, FeeStatusItem } from "@/api/types";

const AUTO_GENERATE_WINDOW_DAYS = 7;

function daysUntil(dateStr: string): number {
  const ms = new Date(dateStr + "T00:00:00").getTime() - new Date(new Date().toDateString()).getTime();
  return Math.round(ms / (1000 * 60 * 60 * 24));
}

const STATUS_TONE: Record<string, "urgent" | "positive" | "warning" | "neutral"> = {
  overdue: "urgent",
  pending: "warning",
  partial: "warning",
  paid: "positive",
};

const STATUS_FILTERS = ["all", "pending", "partial", "paid", "overdue"] as const;
const ALL_CLASSES = "__all__";

function SchedulesTab({ schoolId }: { schoolId: number }) {
  const lookup = useReferenceLookup(schoolId);
  const schedules = useFeeSchedules({ schoolId });
  const create = useCreateFeeSchedule();

  const [classId, setClassId] = useState("");
  const [academicYear, setAcademicYear] = useState(DEFAULT_ACADEMIC_YEAR);
  const [feeType, setFeeType] = useState("");
  const [amount, setAmount] = useState("");
  const [dueDate, setDueDate] = useState("");
  const runInvoicing = useRunInvoicing();

  const className = (id: number | null) => (id === null ? "School-wide" : lookup.data?.classes.find((c) => c.id === id)?.name ?? `Class #${id}`);

  function submit() {
    if (!feeType.trim() || !amount || !dueDate) return;
    create.mutate(
      {
        school_id: schoolId,
        class_id: classId ? Number(classId) : undefined,
        academic_year: academicYear,
        fee_type: feeType,
        amount: Number(amount),
        due_date: dueDate,
      },
      { onSuccess: () => { setFeeType(""); setAmount(""); setDueDate(""); setClassId(""); } }
    );
  }

  return (
    <div className="grid items-start gap-3 lg:grid-cols-[22rem_1fr]">
      <Card className="h-fit">
        <CardHeader>
          <CardTitle>New fee schedule</CardTitle>
          <CardDescription>Class-specific (e.g. tuition) or school-wide (e.g. transport, leave class blank).</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Field label="Class (optional — blank = school-wide)">
            <Select value={classId} onValueChange={setClassId}>
              <SelectTrigger>
                <SelectValue placeholder="School-wide" />
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
          <Field label="Academic year">
            <Input value={academicYear} onChange={(e) => setAcademicYear(e.target.value)} />
          </Field>
          <Field label="Fee type">
            <Input value={feeType} onChange={(e) => setFeeType(e.target.value)} placeholder="e.g. tuition, transport" />
          </Field>
          <Field label="Amount">
            <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="15000" />
          </Field>
          <Field label="Due date">
            <Input type="date" value={dueDate} onChange={(e) => setDueDate(e.target.value)} />
          </Field>
          <Button onClick={submit} disabled={!feeType.trim() || !amount || !dueDate || create.isPending} className="self-start">
            {create.isPending ? "Creating…" : "Create schedule"}
          </Button>
          {create.isError && (
            <p className="text-sm text-urgent">{create.error instanceof ApiError ? create.error.message : "Failed to create schedule."}</p>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-2">
        <Card>
          <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
            <div>
              <p className="text-sm font-medium">Generate every {academicYear} schedule's records now</p>
              <p className="text-sm text-ink-muted">
                Each schedule below auto-generates its own records once its due date is within {AUTO_GENERATE_WINDOW_DAYS} days (or use
                its own "Generate now" button to do it early). This does all of them at once, regardless of due date — mainly useful for
                backfilling students enrolled after a schedule already existed.
              </p>
            </div>
            <Button
              variant="outline"
              onClick={() => runInvoicing.mutate({ academic_year: academicYear })}
              disabled={runInvoicing.isPending}
              className="shrink-0"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              {runInvoicing.isPending ? "Generating…" : "Generate all now"}
            </Button>
          </CardContent>
          {runInvoicing.isError && (
            <CardContent className="pt-0">
              <p className="text-sm text-urgent">
                {runInvoicing.error instanceof ApiError ? runInvoicing.error.message : "Failed to generate fee records."}
              </p>
            </CardContent>
          )}
          {runInvoicing.isSuccess && (
            <CardContent className="pt-0">
              <p className="text-sm text-positive">
                {runInvoicing.data.records_created} record(s) created · {runInvoicing.data.overdue_marked} marked overdue ·{" "}
                {runInvoicing.data.reminders_sent} reminder(s) logged.
              </p>
            </CardContent>
          )}
        </Card>
        {schedules.isLoading && <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />}
        {schedules.data?.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-sm text-ink-muted">No fee schedules yet.</CardContent>
          </Card>
        )}
        {schedules.data?.map((s) => (
          <ScheduleCard key={s.id} schedule={s} classLabel={className(s.class_id)} />
        ))}
      </div>
    </div>
  );
}

function ScheduleCard({ schedule, classLabel }: { schedule: FeeSchedule; classLabel: string }) {
  const generate = useGenerateScheduleRecords();
  const daysLeft = daysUntil(schedule.due_date);
  const withinWindow = daysLeft <= AUTO_GENERATE_WINDOW_DAYS;

  return (
    <EntityCard
      icon={Receipt}
      tone="neutral"
      title={`${schedule.fee_type} · ₹${schedule.amount.toLocaleString()}`}
      badges={
        <>
          <Badge variant="outline">{classLabel}</Badge>
          {schedule.records_generated ? (
            <Badge variant="positive">
              <BadgeCheck className="h-3 w-3" /> Records generated
            </Badge>
          ) : withinWindow ? (
            <Badge variant="warning">Generating tonight</Badge>
          ) : (
            <Badge variant="outline">Auto-generates in {daysLeft - AUTO_GENERATE_WINDOW_DAYS} day(s)</Badge>
          )}
        </>
      }
      message={
        <>
          {`${schedule.academic_year} · due ${schedule.due_date}`}
          {generate.isError && (
            <span className="mt-1 block text-urgent">
              {generate.error instanceof ApiError ? generate.error.message : "Failed to generate records."}
            </span>
          )}
        </>
      }
      meta={`Schedule #${schedule.id}`}
      actions={
        !schedule.records_generated ? (
          <Button variant="outline" size="sm" onClick={() => generate.mutate(schedule.id)} disabled={generate.isPending}>
            <RefreshCw className="h-3.5 w-3.5" />
            {generate.isPending ? "Generating…" : "Generate now"}
          </Button>
        ) : undefined
      }
    />
  );
}

function PaymentDialog({ item }: { item: FeeStatusItem }) {
  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const record = useRecordPayment();

  function submit() {
    if (!amount) return;
    record.mutate({ feeRecordId: item.fee_record_id, amount: Number(amount) }, { onSuccess: () => { setOpen(false); setAmount(""); } });
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm" disabled={item.status === "paid"}>
          <CreditCard className="h-3.5 w-3.5" /> Record payment
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Record a payment</DialogTitle>
          <DialogDescription>
            Fee record #{item.fee_record_id} · student #{item.student_id} · due ₹{item.amount_due.toLocaleString()}, paid so far ₹
            {item.amount_paid.toLocaleString()}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Amount">
            <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} placeholder="5000" />
          </Field>
          {record.isError && (
            <p className="text-sm text-urgent">{record.error instanceof ApiError ? record.error.message : "Failed to record payment."}</p>
          )}
          {record.isSuccess && (
            <p className="text-sm text-positive">
              Recorded. New status: <span className="font-mono">{record.data.status}</span> (₹{record.data.amount_paid.toLocaleString()} / ₹
              {record.data.amount_due.toLocaleString()})
            </p>
          )}
          <Button onClick={submit} disabled={!amount || record.isPending} className="self-start">
            {record.isPending ? "Recording…" : "Record payment"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const PROGRESS_FILL: Record<string, string> = {
  urgent: "bg-urgent",
  positive: "bg-positive",
  warning: "bg-warning",
  neutral: "bg-ink-faint",
};

function FeeProgressBar({ percent, tone }: { percent: number; tone: "urgent" | "positive" | "warning" | "neutral" }) {
  return (
    <div className="mt-1.5 h-1.5 w-full max-w-xs overflow-hidden rounded-full bg-elevated" aria-hidden>
      <div className={`h-full rounded-full ${PROGRESS_FILL[tone]}`} style={{ width: `${percent}%` }} />
    </div>
  );
}

function FeeStatusCard({
  item,
  mode,
  studentName,
}: {
  item: FeeStatusItem;
  mode: "admin" | "teacher" | "parent" | "student";
  studentName: (id: number) => string;
}) {
  const percentPaid = item.amount_due > 0 ? Math.min(100, Math.round((item.amount_paid / item.amount_due) * 100)) : 0;
  const isComplete = item.status === "paid";
  const tone = isComplete ? "neutral" : (STATUS_TONE[item.status] ?? "neutral");

  return (
    <EntityCard
      icon={Wallet}
      tone={tone}
      muted={isComplete}
      title={mode === "admin" || mode === "teacher" ? studentName(item.student_id) : item.fee_type}
      badges={
        <>
          {isComplete ? (
            <Badge variant="outline">
              <BadgeCheck className="h-3 w-3" /> Complete
            </Badge>
          ) : (
            <Badge variant={item.status === "overdue" ? "urgent" : "warning"}>
              {item.status} · {percentPaid}% paid
            </Badge>
          )}
          {(mode === "admin" || mode === "teacher") && <Badge variant="outline">{item.fee_type}</Badge>}
        </>
      }
      message={
        <>
          {`Due ₹${item.amount_due.toLocaleString()} · paid ₹${item.amount_paid.toLocaleString()} · due date ${item.due_date}`}
          {!isComplete && <FeeProgressBar percent={percentPaid} tone={tone} />}
        </>
      }
      meta={`Fee record #${item.fee_record_id}`}
      actions={mode === "admin" ? <PaymentDialog item={item} /> : mode === "teacher" ? <MarkPaidToggle item={item} /> : undefined}
    />
  );
}

function MarkPaidToggle({ item }: { item: FeeStatusItem }) {
  const mark = useMarkFeePaid();
  const isPaid = item.status === "paid";

  return (
    <div className="flex flex-col items-end gap-1">
      <Button
        size="sm"
        variant={isPaid ? "outline" : "default"}
        onClick={() => mark.mutate({ feeRecordId: item.fee_record_id, paid: !isPaid })}
        disabled={mark.isPending}
      >
        {isPaid ? (
          <>
            <X className="h-3.5 w-3.5" /> Mark unpaid
          </>
        ) : (
          <>
            <BadgeCheck className="h-3.5 w-3.5" /> Mark paid
          </>
        )}
      </Button>
      {mark.isError && (
        <p className="text-xs text-urgent">{mark.error instanceof ApiError ? mark.error.message : "Failed to update."}</p>
      )}
    </div>
  );
}

/** Shared across admin/principal (full control), teacher (own class, paid/unpaid
 * toggle instead of amount entry), parent (one child, read-only), and student (self,
 * read-only) - same "one component branches on role" pattern as RiskDashboard. */
function StatusTab({
  schoolId,
  mode,
  studentId,
  studentLabel,
}: {
  schoolId: number;
  mode: "admin" | "teacher" | "parent" | "student";
  studentId?: number;
  studentLabel?: string;
}) {
  const lookup = useReferenceLookup(schoolId);
  const [classId, setClassId] = useState(ALL_CLASSES);
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>("all");
  const status = useFeeStatus({
    classId: mode === "admin" && classId !== ALL_CLASSES ? Number(classId) : undefined,
    studentId: mode === "parent" ? studentId : undefined,
    status: statusFilter === "all" ? undefined : statusFilter,
    enabled: mode !== "parent" || studentId !== undefined,
  });

  const studentName = (id: number) => studentLabel ?? lookup.data?.students.find((s) => s.id === id)?.name ?? `Student #${id}`;
  const items = status.data?.items ?? [];
  const counts = { overdue: 0, pending: 0, partial: 0, paid: 0 };
  for (const i of items) if (i.status in counts) counts[i.status as keyof typeof counts]++;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-3">
        <StatTile label="Overdue" value={counts.overdue} icon={Wallet} tone="urgent" />
        <StatTile label="Pending" value={counts.pending} icon={Wallet} tone="warning" />
        <StatTile label="Partial" value={counts.partial} icon={Wallet} tone="warning" />
        <StatTile label="Paid" value={counts.paid} icon={BadgeCheck} tone="positive" />
      </div>

      <div className="flex flex-wrap items-end gap-3">
        {mode === "admin" && (
          <Field label="Class" className="w-56">
            <Select value={classId} onValueChange={setClassId}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL_CLASSES}>All classes</SelectItem>
                {lookup.data?.classes.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        )}
        <Field label="Status" className="w-40">
          <Select value={statusFilter} onValueChange={(v) => setStatusFilter(v as typeof statusFilter)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {STATUS_FILTERS.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
      </div>

      {status.isLoading && <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />}
      {!status.isLoading && items.length === 0 && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-ink-muted">No fee records match this filter.</CardContent>
        </Card>
      )}
      <div className="flex flex-col gap-2">
        {items.map((item) => (
          <FeeStatusCard key={item.fee_record_id} item={item} mode={mode} studentName={studentName} />
        ))}
      </div>
    </div>
  );
}

function RemindersTab({ schoolId }: { schoolId: number }) {
  const lookup = useReferenceLookup(schoolId);
  const [classId, setClassId] = useState(ALL_CLASSES);
  const [overdueOnly, setOverdueOnly] = useState(true);
  const trigger = useTriggerReminders();

  return (
    <Card>
      <CardHeader>
        <CardTitle>Send fee reminders</CardTitle>
        <CardDescription>
          Runs the 7/14/30-day cadence heuristic against matching records. Logs a real <span className="font-mono">FeeReminder</span> row
          per record that's due one — no email infrastructure exists, so this records that a reminder was determined due, not that mail
          was sent.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Field label="Class" className="w-56">
          <Select value={classId} onValueChange={setClassId}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_CLASSES}>All classes</SelectItem>
              {lookup.data?.classes.map((c) => (
                <SelectItem key={c.id} value={String(c.id)}>
                  {c.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <Field label="Scope">
          <Select value={overdueOnly ? "overdue" : "all"} onValueChange={(v) => setOverdueOnly(v === "overdue")}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="overdue">Overdue only</SelectItem>
              <SelectItem value="all">Overdue, pending, and partial</SelectItem>
            </SelectContent>
          </Select>
        </Field>
        <Button
          onClick={() => trigger.mutate({ class_id: classId !== ALL_CLASSES ? Number(classId) : undefined, overdue_only: overdueOnly })}
          disabled={trigger.isPending}
          className="self-start"
        >
          <BellRing className="h-4 w-4" />
          {trigger.isPending ? "Sending…" : "Trigger reminders"}
        </Button>
        {trigger.isError && (
          <p className="text-sm text-urgent">{trigger.error instanceof ApiError ? trigger.error.message : "Failed to trigger reminders."}</p>
        )}
        {trigger.isSuccess && <p className="text-sm text-positive">{trigger.data.sent_count} reminder(s) recorded as due.</p>}
      </CardContent>
    </Card>
  );
}

function TeacherFeesView({ schoolId }: { schoolId: number }) {
  const currentUser = useCurrentUser();
  const lookup = useReferenceLookup(schoolId);
  const myClasses = (lookup.data?.classes ?? []).filter((c) => c.class_teacher_id === currentUser.data?.user_id);
  const label = myClasses.length > 0 ? myClasses.map((c) => c.name).join(", ") : "-";

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-ink-muted">
        Class teacher: <span className="font-medium text-ink">{label}</span>
      </p>
      {lookup.isLoading ? (
        <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />
      ) : myClasses.length === 0 ? (
        <Card>
          <CardContent className="flex flex-col items-center gap-1 py-8 text-center">
            <Users className="h-6 w-6 text-ink-muted" />
            <p className="font-display text-sm font-medium text-ink">You're not a class teacher</p>
            <p className="text-xs text-ink-muted">This page tracks fees for a class teacher's own class - you aren't one yet.</p>
          </CardContent>
        </Card>
      ) : (
        <StatusTab schoolId={schoolId} mode="teacher" />
      )}
    </div>
  );
}

function ParentFeesView({ schoolId }: { schoolId: number }) {
  const children = useParentChildren();
  const [selectedChildId, setSelectedChildId] = useState("");

  useEffect(() => {
    if (!selectedChildId && children.data?.items.length) {
      setSelectedChildId(String(children.data.items[0].id));
    }
  }, [children.data, selectedChildId]);

  const selectedChild = children.data?.items.find((c) => String(c.id) === selectedChildId);

  if (children.isLoading) return <div className="h-16 animate-pulse rounded-2xl bg-elevated/60" />;

  if ((children.data?.items.length ?? 0) === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-1 py-6 text-center">
          <Users className="h-6 w-6 text-ink-muted" />
          <p className="font-display text-sm font-medium text-ink">No linked children</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {(children.data?.items.length ?? 0) > 1 && (
        <Select value={selectedChildId} onValueChange={setSelectedChildId}>
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
      )}
      {selectedChild && (
        <StatusTab schoolId={schoolId} mode="parent" studentId={selectedChild.id} studentLabel={selectedChild.name} />
      )}
    </div>
  );
}

export default function FeesPage() {
  const schoolId = useCurrentUser().data?.school_id;
  const { role } = useAuthStore();

  if (schoolId == null) {
    return (
      <div className="flex flex-col gap-3">
        <PageHeader title="Fees" description="Fee schedules, per-student status, reminders, and payment reconciliation." />
        <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />
      </div>
    );
  }

  if (role === "teacher") {
    return (
      <div className="flex flex-col gap-3">
        <PageHeader title="Fees" description="Who in your class has paid, and who still owes — mark it as it happens." />
        <TeacherFeesView schoolId={schoolId} />
      </div>
    );
  }

  if (role === "parent") {
    return (
      <div className="flex flex-col gap-3">
        <PageHeader title="Fees" description="What your child owes and what's already paid." />
        <ParentFeesView schoolId={schoolId} />
      </div>
    );
  }

  if (role === "student") {
    return (
      <div className="flex flex-col gap-3">
        <PageHeader title="Fees" description="What you owe and what's already paid." />
        <StatusTab schoolId={schoolId} mode="student" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="Fees" description="Fee schedules, per-student status, reminders, and payment reconciliation." />
      <Tabs defaultValue="status">
        <TabsList>
          <TabsTrigger value="status">Status</TabsTrigger>
          <TabsTrigger value="schedules">Schedules</TabsTrigger>
          <TabsTrigger value="reminders">Reminders</TabsTrigger>
        </TabsList>
        <TabsContent value="status">
          <StatusTab schoolId={schoolId} mode="admin" />
        </TabsContent>
        <TabsContent value="schedules">
          <SchedulesTab schoolId={schoolId} />
        </TabsContent>
        <TabsContent value="reminders">
          <RemindersTab schoolId={schoolId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
