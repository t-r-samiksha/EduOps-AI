import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  AlertCircle,
  BadgeCheck,
  BellRing,
  Clock,
  CreditCard,
  Receipt,
  RefreshCw,
  Users,
  Wallet,
  X,
} from "lucide-react";
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
import FileDropzone from "@/components/shared/FileDropzone";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import {
  useCreatePaymentRequest,
  useFeePaymentRequests,
  useParentChildFees,
} from "@/api/hooks/useFeePaymentRequests";
import { PaymentRequestsTab } from "@/components/fees/PaymentRequestsTab";
import {
  useFeeSchedules,
  useCreateFeeSchedule,
  useFeeStatus,
  useTriggerReminders,
  useRecordPayment,
  useRemindersPreview,
  useRunInvoicing,
  useMarkFeePaid,
  useGenerateScheduleRecords,
} from "@/api/hooks/useFees";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useSelectedChild } from "@/hooks/useSelectedChild";
import { useAuthStore } from "@/store/authStore";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { ApiError } from "@/api/client";
import { PAYMENT_METHODS } from "@/api/types";
import type { DerivedFeeStatus, FeeSchedule, FeeStatusItem, ParentFeeItem } from "@/api/types";
import { cn } from "@/lib/utils";

const AUTO_GENERATE_WINDOW_DAYS = 7;

/** Mirrors fee_schedules.fee_type String(30) / academic_year String(20). Kept as named
 * constants so the input limit and the hint can't drift apart from each other. */
const FEE_TYPE_MAX = 30;
const ACADEMIC_YEAR_MAX = 20;

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
          {/* maxLength mirrors the DB columns (academic_year String(20), fee_type
              String(30)). Without it a longer paste reached Postgres, raised a
              truncation error, and came back as a bare 500 - the button just sat on
              "Creating…" with nothing to show. The backend now validates too; this
              stops it being reachable at all. */}
          <Field label="Academic year">
            <Input
              value={academicYear}
              onChange={(e) => setAcademicYear(e.target.value)}
              maxLength={ACADEMIC_YEAR_MAX}
            />
          </Field>
          <Field
            label="Fee type"
            hint={`${feeType.length}/${FEE_TYPE_MAX} characters`}
          >
            <Input
              value={feeType}
              onChange={(e) => setFeeType(e.target.value)}
              maxLength={FEE_TYPE_MAX}
              placeholder="e.g. tuition, transport"
            />
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
          <Field
            label="Amount"
            hint={`${money(item.outstanding)} outstanding of ${money(item.amount_due)}${
              item.amount_paid > 0 ? ` · ${money(item.amount_paid)} already received` : ""
            }`}
          >
            {/* Placeholder is THIS fee's outstanding balance, not a hardcoded 5000 -
                that constant sat next to a ₹350 fee inviting a 5000 rupee entry, and
                record_payment has no upper bound to catch it. */}
            <Input
              type="number"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder={String(item.outstanding)}
              max={item.outstanding}
            />
          </Field>
          {Number(amount) > item.outstanding && (
            <p className="text-xs text-warning">
              That is more than the {money(item.outstanding)} outstanding — it will be recorded as an
              overpayment.
            </p>
          )}
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
  requestsHref,
}: {
  item: FeeStatusItem;
  mode: "admin" | "teacher" | "parent" | "student";
  studentName: (id: number) => string;
  /** Where the "Review" link on a pending-claim notice points. */
  requestsHref?: string;
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
          {(mode === "admin" || mode === "teacher") && (
            <ClaimNotice item={item} requestsHref={requestsHref ?? "#"} />
          )}
        </>
      }
      meta={`Fee record #${item.fee_record_id}`}
      actions={mode === "admin" ? <PaymentDialog item={item} /> : mode === "teacher" ? <MarkPaidToggle item={item} /> : undefined}
    />
  );
}

/** Staff-facing claim indicator on a canonical fee row.
 *
 * The fix for the two views disagreeing: `item.status` is the fee record's own
 * status and knows nothing about claims, so an overdue fee a parent had already
 * reported paying read as plainly overdue here - and an admin could send a reminder
 * chasing someone who was waiting on the school. */
function ClaimNotice({ item, requestsHref }: { item: FeeStatusItem; requestsHref: string }) {
  const claim = item.claim;
  if (!claim) return null;

  if (claim.status === "pending") {
    return (
      <div className="mt-2 flex flex-wrap items-center gap-2 rounded-xl border border-warning/30 bg-warning/5 px-3 py-2 text-xs text-warning">
        <Clock className="h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0 break-words">
          Parent reported paying {money(claim.amount)} by {claim.payment_method} · ref{" "}
          <span className="font-mono">{claim.payment_reference}</span> — awaiting your confirmation
        </span>
        <Link
          to={requestsHref}
          className="ml-auto shrink-0 font-semibold underline underline-offset-2 hover:opacity-80"
        >
          Review
        </Link>
      </div>
    );
  }

  if (claim.status === "rejected") {
    return (
      <div className="mt-2 flex flex-wrap items-start gap-2 rounded-xl border border-urgent/30 bg-urgent/5 px-3 py-2 text-xs text-urgent">
        <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <span className="min-w-0 break-words">
          A reported payment of {money(claim.amount)} was rejected
          {claim.rejection_reason ? `: ${claim.rejection_reason}` : ""}
        </span>
      </div>
    );
  }

  return null;
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
  requestsHref,
}: {
  schoolId: number;
  mode: "admin" | "teacher" | "parent" | "student";
  studentId?: number;
  studentLabel?: string;
  requestsHref?: string;
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
          <FeeStatusCard
            key={item.fee_record_id}
            item={item}
            mode={mode}
            studentName={studentName}
            requestsHref={requestsHref}
          />
        ))}
      </div>
    </div>
  );
}

/** Explains what a reminder run would do, and why it might do nothing.
 *
 * WHY: the tab used to report only "0 reminder(s) recorded as due", which is
 * indistinguishable from a broken button - and it genuinely read as one while ten
 * overdue cards sat on the Status tab. `overdue` means the due date has passed;
 * whether a reminder fires is a separate cadence question. This makes both visible. */
function ReminderPreviewPanel({ classId, overdueOnly }: { classId?: number; overdueOnly: boolean }) {
  const preview = useRemindersPreview({ classId, overdueOnly });

  if (preview.isLoading) return <div className="h-24 animate-pulse rounded-xl bg-elevated/60" />;
  if (!preview.data) return null;
  const p = preview.data;

  const rows: { label: string; value: number; tone?: string }[] = [
    { label: "Due a reminder now", value: p.due_now, tone: p.due_now > 0 ? "text-positive" : "text-ink-muted" },
    { label: "Not yet due (due today or later)", value: p.not_yet_due },
    { label: "Waiting to cross the next threshold", value: p.waiting_for_next_tier },
    { label: "Fully escalated — nothing further will fire", value: p.fully_escalated },
  ].filter((r) => r.value > 0 || r.label.startsWith("Due"));

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-xl border px-3.5 py-3",
        p.due_now > 0 ? "border-positive/30 bg-positive/5" : "border-border bg-elevated/40"
      )}
    >
      <p className="text-sm font-semibold text-ink">
        {p.in_scope} fee{p.in_scope === 1 ? "" : "s"} in scope ·{" "}
        <span className={p.due_now > 0 ? "text-positive" : "text-ink-muted"}>
          {p.due_now} due a reminder
        </span>
      </p>

      {p.by_tier.length > 0 && (
        <ul className="flex flex-col gap-1">
          {p.by_tier.map((bucket) => (
            <li key={bucket.cadence_reason} className="flex items-center gap-2 text-xs">
              <Badge variant={bucket.severity === "urgent" ? "urgent" : "warning"}>{bucket.count}</Badge>
              <span className="text-ink-muted">{bucket.cadence_reason}</span>
            </li>
          ))}
        </ul>
      )}

      <dl className="flex flex-col gap-0.5 text-xs">
        {rows.map((row) => (
          <div key={row.label} className="flex flex-wrap justify-between gap-2">
            <dt className="text-ink-muted">{row.label}</dt>
            <dd className={cn("font-mono tabular-nums", row.tone ?? "text-ink")}>{row.value}</dd>
          </div>
        ))}
      </dl>

      {p.next_due_date && (
        <p className="flex items-start gap-1.5 border-t border-border pt-2 text-xs text-ink-muted">
          <Clock className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            Next {p.next_due_count === 1 ? "reminder becomes" : "reminders become"} due on{" "}
            <span className="font-medium text-ink">{p.next_due_date}</span> ({p.next_due_count} record
            {p.next_due_count === 1 ? "" : "s"}).
          </span>
        </p>
      )}
      {p.due_now === 0 && !p.next_due_date && (
        <p className="border-t border-border pt-2 text-xs text-ink-muted">
          Nothing in scope will ever fire a reminder — every record is either fully escalated or already paid.
        </p>
      )}
      {!overdueOnly && p.not_yet_due > 0 && (
        <p className="flex items-start gap-1.5 border-t border-border pt-2 text-xs text-warning">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            {p.not_yet_due} of these aren't past their due date yet, so widening the scope beyond overdue can't
            produce extra reminders today.
          </span>
        </p>
      )}
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
          Runs the 1/7/14/30-day cadence against matching records — a first notice the day a fee goes past due, then
          escalating reminders. Logs a real <span className="font-mono">FeeReminder</span> row per record that's due
          one, and notifies the parents; no email infrastructure exists, so a row means a reminder was determined due,
          not that mail was delivered. Each tier fires at most once per fee.
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
        <ReminderPreviewPanel
          classId={classId !== ALL_CLASSES ? Number(classId) : undefined}
          overdueOnly={overdueOnly}
        />
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

// --- Parent fee view: the claim half of the payment confirmation loop ----------------
//
// There is no payment gateway. The parent pays by UPI/bank transfer/cash through their
// own bank, then records the reference here; an admin confirms it against the
// statement before the canonical fee record moves. So this view's job is to make the
// FOUR derived states unmistakable - especially `rejected`, which is the state that
// proves this is a real review loop and not a rubber stamp, and the one that has to
// offer a way forward rather than a dead end.

const DERIVED_STATUS_LABEL: Record<DerivedFeeStatus, string> = {
  unpaid: "Unpaid",
  // Not "Unpaid": a fee with money already against it read identically to one with
  // nothing paid, which is untrue and discouraging to a parent who has part-paid.
  partially_paid: "Partly paid",
  payment_pending: "Awaiting confirmation",
  paid: "Paid",
  rejected: "Not confirmed",
};

const DERIVED_STATUS_BADGE: Record<DerivedFeeStatus, "urgent" | "warning" | "positive"> = {
  unpaid: "urgent",
  // Amber, not red: still incomplete and still owed, but progress has been made.
  partially_paid: "warning",
  payment_pending: "warning",
  paid: "positive",
  rejected: "urgent",
};

/** Left border carries the state at a glance down a phone-width list, where the
 * badge itself may have wrapped to a second line. */
const DERIVED_STATUS_EDGE: Record<DerivedFeeStatus, string> = {
  unpaid: "border-l-urgent",
  partially_paid: "border-l-warning",
  payment_pending: "border-l-warning",
  paid: "border-l-positive",
  rejected: "border-l-urgent",
};

function money(value: number): string {
  return `₹${value.toLocaleString("en-IN")}`;
}

function PaymentClaimDialog({
  studentId,
  item,
  resubmit,
}: {
  studentId: number;
  item: ParentFeeItem;
  resubmit?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [method, setMethod] = useState<string>("UPI");
  const [reference, setReference] = useState("");
  const [amount, setAmount] = useState(String(item.outstanding));
  const [proof, setProof] = useState<File | null>(null);
  const create = useCreatePaymentRequest();

  function submit() {
    if (!reference.trim() || !amount) return;
    create.mutate(
      {
        studentId,
        feeRecordId: item.fee_record_id,
        paymentMethod: method,
        paymentReference: reference.trim(),
        amount: Number(amount),
        proofFile: proof,
      },
      {
        onSuccess: () => {
          setOpen(false);
          setReference("");
          setProof(null);
          create.reset();
        },
      }
    );
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        // Re-prefill from the CURRENT balance each time it opens - a part payment
        // confirmed since last time changes what's left to claim.
        if (next) {
          setAmount(String(item.outstanding));
          create.reset();
        }
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" variant={resubmit ? "outline" : "default"} className="w-full sm:w-auto">
          <CreditCard className="h-3.5 w-3.5" />
          {resubmit ? "Submit again" : "I've paid"}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{resubmit ? "Submit a corrected payment" : "Tell the school you've paid"}</DialogTitle>
          <DialogDescription>
            {item.fee_type} · {money(item.outstanding)} outstanding. The school checks this against their bank
            statement before the fee is marked paid — it isn't automatic.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="How did you pay?">
            <Select value={method} onValueChange={setMethod}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PAYMENT_METHODS.map((m) => (
                  <SelectItem key={m} value={m}>
                    {m}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field
            label="Transaction reference"
            hint="The UPI transaction id, bank reference, or the receipt number from the office"
          >
            <Input
              value={reference}
              onChange={(e) => setReference(e.target.value)}
              placeholder="UPI/428817263541"
            />
          </Field>
          <Field label="Amount paid" hint={`Cannot be more than the ${money(item.outstanding)} outstanding`}>
            <Input type="number" value={amount} onChange={(e) => setAmount(e.target.value)} />
          </Field>
          <Field label="Proof (optional)" hint="A screenshot or photo of the receipt helps the school match it faster">
            <FileDropzone file={proof} onFileSelected={setProof} accept="image/*,application/pdf" />
          </Field>
          {create.isError && (
            <p className="text-sm text-urgent">
              {create.error instanceof ApiError ? create.error.message : "Could not submit this payment."}
            </p>
          )}
          <Button
            onClick={submit}
            disabled={!reference.trim() || !amount || create.isPending}
            className="w-full sm:w-auto sm:self-start"
          >
            {create.isPending ? "Submitting…" : "Submit for confirmation"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ParentFeeRow({ studentId, item }: { studentId: number; item: ParentFeeItem }) {
  const derived = item.derived_status;
  const request = item.request;

  return (
    <Card className={cn("border-l-4", DERIVED_STATUS_EDGE[derived])}>
      <CardContent className="flex flex-col gap-3 py-4">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="font-display text-sm font-semibold text-ink">{item.fee_type}</p>
            <p className="text-xs text-ink-muted">
              {money(item.amount_due)} due by {item.due_date}
              {item.amount_paid > 0 && ` · ${money(item.amount_paid)} paid so far`}
            </p>
          </div>
          <Badge variant={DERIVED_STATUS_BADGE[derived]}>{DERIVED_STATUS_LABEL[derived]}</Badge>
        </div>

        {derived !== "paid" && (
          <p className="text-sm font-medium text-ink">
            {money(item.outstanding)} still to pay
            {item.amount_paid > 0 && (
              <span className="font-normal text-ink-muted">
                {" "}
                — {money(item.amount_paid)} of {money(item.amount_due)} received
              </span>
            )}
          </p>
        )}

        {/* AWAITING CONFIRMATION - the reference is shown back so the parent can see
            exactly what they claimed, and chase it with the office if it stalls. */}
        {derived === "payment_pending" && request && (
          <div className="flex flex-col gap-1 rounded-xl border border-warning/30 bg-warning/5 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-warning">
              <Clock className="h-3.5 w-3.5 shrink-0" />
              Waiting for the school to confirm
            </p>
            <p className="break-words text-xs text-ink-muted">
              You reported {money(request.amount)} by {request.payment_method}, reference{" "}
              <span className="font-mono text-ink">{request.payment_reference}</span>
            </p>
            <p className="text-xs text-ink-faint">
              Submitted {new Date(request.submitted_at).toLocaleString()}
              {request.has_proof && " · proof attached"}
            </p>
          </div>
        )}

        {/* NOT CONFIRMED - the reason is the whole point. Without it a parent has no
            idea what to fix, and "rejected" reads as the school being arbitrary. */}
        {derived === "rejected" && request && (
          <div className="flex flex-col gap-1 rounded-xl border border-urgent/30 bg-urgent/5 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-urgent">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              The school could not confirm this payment
            </p>
            {request.rejection_reason && (
              <p className="break-words text-sm text-ink">{request.rejection_reason}</p>
            )}
            <p className="break-words text-xs text-ink-muted">
              You reported {money(request.amount)} by {request.payment_method}, reference{" "}
              <span className="font-mono">{request.payment_reference}</span>
              {request.reviewed_at && ` · reviewed ${new Date(request.reviewed_at).toLocaleDateString()}`}
            </p>
          </div>
        )}

        {derived === "paid" && (
          <p className="flex items-center gap-1.5 text-xs font-medium text-positive">
            <BadgeCheck className="h-3.5 w-3.5 shrink-0" />
            Confirmed by the school — nothing further to pay
          </p>
        )}

        {/* partially_paid gets the button too - the remaining balance is exactly the
            thing a parent still needs to report paying. */}
        {(derived === "unpaid" || derived === "partially_paid" || derived === "rejected") && (
          <PaymentClaimDialog studentId={studentId} item={item} resubmit={derived === "rejected"} />
        )}
      </CardContent>
    </Card>
  );
}

function ParentFeeList({ studentId }: { studentId: number }) {
  const fees = useParentChildFees(studentId);
  const items = fees.data?.items ?? [];

  const counts = { outstanding: 0, pendingReview: 0, paid: 0 };
  let owed = 0;
  for (const item of items) {
    if (item.derived_status === "paid") counts.paid += 1;
    else if (item.derived_status === "payment_pending") counts.pendingReview += 1;
    else counts.outstanding += 1;
    if (item.derived_status !== "paid") owed += item.outstanding;
  }

  if (fees.isLoading) return <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />;
  if (fees.isError) {
    return (
      <Card>
        <CardContent className="py-6">
          <p className="text-sm text-urgent">
            {fees.error instanceof ApiError ? fees.error.message : "Could not load fees."}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className={cn("flex flex-col gap-3 transition-opacity", fees.isFetching && "opacity-60")}>
      <div className="flex flex-wrap gap-3">
        <StatTile
          label="Still to pay"
          value={money(owed)}
          caption={counts.outstanding > 0 ? `${counts.outstanding} fee(s) outstanding` : "nothing outstanding"}
          icon={Wallet}
          tone={owed > 0 ? "urgent" : "positive"}
          emphasize={owed > 0}
        />
        <StatTile
          label="Awaiting confirmation"
          value={counts.pendingReview}
          caption={counts.pendingReview > 0 ? "reported, not yet confirmed" : undefined}
          icon={Clock}
          tone={counts.pendingReview > 0 ? "warning" : "neutral"}
        />
        <StatTile label="Paid" value={counts.paid} icon={BadgeCheck} tone="positive" />
      </div>

      {items.length === 0 ? (
        <Card>
          <CardContent className="py-8 text-center text-sm text-ink-muted">No fees recorded yet.</CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-2">
          {items.map((item) => (
            <ParentFeeRow key={item.fee_record_id} studentId={studentId} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function ParentFeesView() {
  const { children, selectedChildId, setSelectedChildId, selectedChild, isLoading: childrenLoading } =
    useSelectedChild();

  if (childrenLoading) return <div className="h-16 animate-pulse rounded-2xl bg-elevated/60" />;

  if (children.length === 0) {
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
      {children.length > 1 && (
        <Select value={String(selectedChildId ?? "")} onValueChange={(v) => setSelectedChildId(Number(v))}>
          {/* Full width below sm: a fixed w-56 selector next to a wrapping label is
              the classic 390px overflow. */}
          <SelectTrigger className="w-full sm:w-56">
            <SelectValue placeholder="Select child" />
          </SelectTrigger>
          <SelectContent>
            {children.map((c) => (
              <SelectItem key={c.id} value={String(c.id)}>
                {c.name} {c.class_name ? `· ${c.class_name}` : ""}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {selectedChild && <ParentFeeList key={selectedChild.id} studentId={selectedChild.id} />}
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
        <PageHeader
          title="Fees"
          description="What your child owes, what's already paid, and anything you've reported that the school hasn't confirmed yet."
        />
        <ParentFeesView />
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

  return <StaffFeesView schoolId={schoolId} role={role ?? "admin"} />;
}

const FEE_TABS = ["status", "requests", "schedules", "reminders"] as const;
type FeeTab = (typeof FEE_TABS)[number];

/** Admin/principal fees hub. Everything that was on the separate Payment Requests
 * page lives here as a tab, with no feature dropped.
 *
 * TAB STATE LIVES IN THE URL (`?tab=`), the same convention useSelectedChild
 * established with `?child=`. That's what lets the dashboard badge, the sidebar and
 * the `fee_payment_request` notifications deep-link straight to the queue - a tab
 * reachable only by clicking would have buried an inbox that parents are actively
 * waiting on. */
function StaffFeesView({ schoolId, role }: { schoolId: number; role: string }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get("tab");
  const tab: FeeTab = (FEE_TABS as readonly string[]).includes(requested ?? "")
    ? (requested as FeeTab)
    : "status";

  // Shared with the sidebar badge, so opening the page doesn't fire a second
  // request for the same count.
  const queue = useFeePaymentRequests({ live: true });
  const pending = queue.data?.pending_count ?? 0;
  const requestsHref = `/${role}/fees?tab=requests`;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Fees"
        description="Schedules, per-student status, reminders, and the payment claims parents have reported for confirmation."
      />
      <Tabs
        value={tab}
        onValueChange={(next) =>
          setSearchParams(
            (prev) => {
              const params = new URLSearchParams(prev);
              // `status` is the default, so keep the bare URL clean.
              if (next === "status") params.delete("tab");
              else params.set("tab", next);
              return params;
            },
            // A tab change is a navigation - back should return to the previous tab.
            { replace: false }
          )
        }
      >
        <TabsList>
          <TabsTrigger value="status">Status</TabsTrigger>
          <TabsTrigger value="requests">
            <Receipt className="mr-1 h-3.5 w-3.5" />
            Payment Requests
            {pending > 0 && (
              <span className="ml-1.5 rounded-full bg-urgent px-1.5 text-[0.625rem] font-bold text-urgent-foreground">
                {pending}
              </span>
            )}
          </TabsTrigger>
          <TabsTrigger value="schedules">Schedules</TabsTrigger>
          <TabsTrigger value="reminders">Reminders</TabsTrigger>
        </TabsList>
        <TabsContent value="status">
          <StatusTab schoolId={schoolId} mode="admin" requestsHref={requestsHref} />
        </TabsContent>
        <TabsContent value="requests">
          <PaymentRequestsTab />
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
