import { useState } from "react";
import { BadgeCheck, BellRing, CreditCard, Receipt, Wallet } from "lucide-react";
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
import { useFeeSchedules, useCreateFeeSchedule, useFeeStatus, useTriggerReminders, useRecordPayment } from "@/api/hooks/useFees";
import { DEMO_SCHOOL_ID, DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { ApiError } from "@/api/client";
import type { FeeStatusItem } from "@/api/types";

const STATUS_TONE: Record<string, "urgent" | "positive" | "warning" | "neutral"> = {
  overdue: "urgent",
  pending: "warning",
  partial: "warning",
  paid: "positive",
};

const STATUS_FILTERS = ["all", "pending", "partial", "paid", "overdue"] as const;

function SchedulesTab() {
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
  const schedules = useFeeSchedules({ schoolId: DEMO_SCHOOL_ID });
  const create = useCreateFeeSchedule();

  const [classId, setClassId] = useState("");
  const [academicYear, setAcademicYear] = useState(DEFAULT_ACADEMIC_YEAR);
  const [feeType, setFeeType] = useState("");
  const [amount, setAmount] = useState("");
  const [dueDate, setDueDate] = useState("");

  const className = (id: number | null) => (id === null ? "School-wide" : lookup.data?.classes.find((c) => c.id === id)?.name ?? `Class #${id}`);

  function submit() {
    if (!feeType.trim() || !amount || !dueDate) return;
    create.mutate(
      {
        school_id: DEMO_SCHOOL_ID,
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
        {schedules.isLoading && <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />}
        {schedules.data?.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-sm text-ink-muted">No fee schedules yet.</CardContent>
          </Card>
        )}
        {schedules.data?.map((s) => (
          <EntityCard
            key={s.id}
            icon={Receipt}
            tone="neutral"
            title={`${s.fee_type} · ₹${s.amount.toLocaleString()}`}
            badges={<Badge variant="outline">{className(s.class_id)}</Badge>}
            message={`${s.academic_year} · due ${s.due_date}`}
            meta={`Schedule #${s.id}`}
          />
        ))}
      </div>
    </div>
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

function StatusTab() {
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
  const [classId, setClassId] = useState("");
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_FILTERS)[number]>("all");
  const status = useFeeStatus({ classId: classId ? Number(classId) : undefined, status: statusFilter === "all" ? undefined : statusFilter });

  const studentName = (id: number) => lookup.data?.students.find((s) => s.id === id)?.name ?? `Student #${id}`;
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
        <Field label="Class" className="w-56">
          <Select value={classId} onValueChange={setClassId}>
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
          <EntityCard
            key={item.fee_record_id}
            icon={Wallet}
            tone={STATUS_TONE[item.status] ?? "neutral"}
            title={studentName(item.student_id)}
            badges={<Badge variant={item.status === "paid" ? "positive" : item.status === "overdue" ? "urgent" : "warning"}>{item.status}</Badge>}
            message={`Due ₹${item.amount_due.toLocaleString()} · paid ₹${item.amount_paid.toLocaleString()} · due date ${item.due_date}`}
            meta={`Fee record #${item.fee_record_id}`}
            actions={<PaymentDialog item={item} />}
          />
        ))}
      </div>
    </div>
  );
}

function RemindersTab() {
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
  const [classId, setClassId] = useState("");
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
        <Field label="Class (optional)" className="w-56">
          <Select value={classId} onValueChange={setClassId}>
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
          onClick={() => trigger.mutate({ class_id: classId ? Number(classId) : undefined, overdue_only: overdueOnly })}
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

export default function FeesPage() {
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
          <StatusTab />
        </TabsContent>
        <TabsContent value="schedules">
          <SchedulesTab />
        </TabsContent>
        <TabsContent value="reminders">
          <RemindersTab />
        </TabsContent>
      </Tabs>
    </div>
  );
}
