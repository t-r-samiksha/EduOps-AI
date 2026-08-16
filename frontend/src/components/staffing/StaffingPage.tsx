import { useState } from "react";
import { AlertTriangle, CalendarClock, CalendarPlus, ChevronDown, ChevronRight, TrendingUp } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import EntityCard from "@/components/shared/EntityCard";
import StatTile from "@/components/shared/StatTile";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import {
  useLeaveRequests,
  useRequestLeave,
  useDecideLeaveRequest,
  useLeaveRequestSubstitutions,
  useConfirmSubstitution,
  useMySubstituteDuties,
  useStaffingForecast,
  useSubstituteSuggestionsPreview,
} from "@/api/hooks/useStaffing";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { DEFAULT_ACADEMIC_YEAR, DAY_LABELS } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { ApiError } from "@/api/client";
import type { LeaveRequest, Substitution } from "@/api/types";

const STATUS_TONE: Record<string, "urgent" | "positive" | "warning" | "neutral"> = {
  pending: "warning",
  approved: "positive",
  rejected: "urgent",
};

function mondayOfThisWeek(): string {
  const d = new Date();
  const day = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - day);
  return d.toISOString().slice(0, 10);
}

// --- Substitution card (used both standalone in the preview tool's results ---
// --- and inline, expanded from a leave request card) ------------------------

function SubstitutionCard({
  schoolId,
  sub,
  onConfirmed,
  readOnly = false,
}: {
  schoolId: number;
  sub: Substitution;
  onConfirmed: () => void;
  readOnly?: boolean;
}) {
  const lookup = useReferenceLookup(schoolId);
  const confirm = useConfirmSubstitution();
  const [pickedTeacher, setPickedTeacher] = useState<string>(
    sub.substitute_teacher_id ? String(sub.substitute_teacher_id) : sub.candidates[0] ? String(sub.candidates[0].teacher_id) : ""
  );
  const [overrideQualification, setOverrideQualification] = useState(false);

  const subjectName = lookup.data?.subjects.find((s) => s.id === sub.subject_id)?.name ?? `Subject #${sub.subject_id}`;
  const className = lookup.data?.classes.find((c) => c.id === sub.class_id)?.name ?? `Class #${sub.class_id}`;
  const teacherName = (id: number) => lookup.data?.teachers.find((t) => t.id === id)?.name ?? `Teacher #${id}`;

  const isConfirmed = sub.status === "confirmed";
  const hasNoSolverCandidates = sub.candidates.length === 0;
  // Manual-override fallback for when the solver found nobody: PUT /substitution/
  // {id}/confirm already accepts any substitute_teacher_id and independently
  // re-checks qualification/availability/conflicts server-side regardless of what
  // this list offers - so surfacing the full roster here is safe, just not
  // solver-recommended (an admin picking someone genuinely unqualified/busy still
  // gets a real conflict back, same as any other pick).
  const manualOverrideOptions = hasNoSolverCandidates
    ? (lookup.data?.teachers ?? []).filter((t) => t.id !== sub.original_teacher_id)
    : [];

  const conflicts = confirm.data?.conflicts ?? [];
  const hasHardConflict = conflicts.some((c) => !c.overridable);
  // Only the not_qualified conflict is left - real-world escalation when there's
  // genuinely no qualified substitute (supervision-only cover). Every other
  // conflict (already busy/substituting/unavailable/on_leave/is_original_teacher)
  // is a real impossibility and can never reach this state.
  const needsQualificationAck = conflicts.length > 0 && !hasHardConflict;

  function handlePick(value: string) {
    setPickedTeacher(value);
    setOverrideQualification(false);
  }

  function handleConfirm() {
    if (!sub.id || !pickedTeacher) return;
    confirm.mutate(
      { substitutionId: sub.id, substituteTeacherId: Number(pickedTeacher), overrideQualification },
      { onSuccess: () => onConfirmed() }
    );
  }

  return (
    <Card>
      <CardContent className="flex flex-col gap-3 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <span className="font-display text-sm font-semibold text-ink">
              {subjectName} · {className}
            </span>
            <p className="font-mono text-xs text-ink-muted">
              {DAY_LABELS[sub.day_of_week]} · Period {sub.period_number + 1}
            </p>
          </div>
          <Badge variant={isConfirmed ? "positive" : "accent"}>{sub.status ?? "suggested"}</Badge>
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">Candidates</span>
          {hasNoSolverCandidates && (
            <p className="text-xs text-ink-faint">
              No candidates returned by the solver - nobody is even free at this day/period, qualified or not. You can
              still confirm any teacher manually below; the same conflict checks still apply.
            </p>
          )}
          {sub.candidates.map((c) => (
            <div
              key={c.teacher_id}
              className={cn(
                "flex items-center justify-between rounded-xl px-3.5 py-2 text-sm",
                c.qualified ? "bg-elevated/60" : "border border-warning/40 bg-warning/10"
              )}
            >
              <span className="flex items-center gap-1.5 text-ink">
                {!c.qualified && <AlertTriangle className="h-3.5 w-3.5 text-warning" />}
                {teacherName(c.teacher_id)}
              </span>
              <span className="font-mono text-xs tabular-nums text-ink-muted">{(c.score * 100).toFixed(0)}% · {c.reason}</span>
            </div>
          ))}
        </div>

        {!readOnly && !isConfirmed && sub.id && (
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-end gap-2">
              <Field
                label="Confirm substitute"
                className="min-w-[12rem] flex-1"
                hint={hasNoSolverCandidates ? "No solver-recommended candidate - choose any teacher manually" : undefined}
              >
                <Select value={pickedTeacher} onValueChange={handlePick}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select teacher" />
                  </SelectTrigger>
                  <SelectContent>
                    {sub.candidates.map((c) => (
                      <SelectItem key={c.teacher_id} value={String(c.teacher_id)}>
                        {teacherName(c.teacher_id)}
                        {!c.qualified && " (not qualified)"}
                      </SelectItem>
                    ))}
                    {manualOverrideOptions.map((t) => (
                      <SelectItem key={t.id} value={String(t.id)}>
                        {t.name} (manual override)
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Button
                size="sm"
                onClick={handleConfirm}
                disabled={!pickedTeacher || confirm.isPending || (needsQualificationAck && !overrideQualification)}
              >
                {confirm.isPending ? "Confirming…" : "Confirm"}
              </Button>
            </div>
            {needsQualificationAck && (
              <label className="flex items-start gap-2 text-xs text-ink-muted">
                <input
                  type="checkbox"
                  checked={overrideQualification}
                  onChange={(e) => setOverrideQualification(e.target.checked)}
                  className="mt-0.5 h-3.5 w-3.5 rounded border-border accent-accent"
                />
                <span>I understand this teacher isn't qualified for this subject - confirm anyway (supervision only)</span>
              </label>
            )}
          </div>
        )}
        {isConfirmed && sub.substitute_teacher_id && (
          <p className="text-sm text-positive">Confirmed: {teacherName(sub.substitute_teacher_id)}</p>
        )}
        {!isConfirmed && readOnly && sub.substitute_teacher_id && (
          <p className="text-sm text-ink-muted">Suggested (not yet confirmed): {teacherName(sub.substitute_teacher_id)}</p>
        )}
        {conflicts.length > 0 && <p className="text-sm text-urgent">{conflicts.map((c) => c.message).join("; ")}</p>}
      </CardContent>
    </Card>
  );
}

/** Coverage summary for one leave request's real Substitution rows - separate
 * from (and shown alongside, never merged into) the leave-approval status
 * badge: "approved" answers "is the LEAVE decided", this answers "is the
 * COVERAGE resolved", and those are two independently-true-or-false real
 * states. Reuses the exact same query as InlineSubstitutions below (same
 * queryKey via useLeaveRequestSubstitutions) rather than a second fetch path -
 * expanding "Show substitutes" on the same card is a cache hit, not a refetch.
 * Zero-confirmed is rendered as the most attention-grabbing (urgent) of the
 * three real states since it's the actual risk: leave approved, nobody
 * covering it yet. */
function CoverageBadge({ leaveRequestId }: { leaveRequestId: number }) {
  const subs = useLeaveRequestSubstitutions({ leaveRequestId, academicYear: DEFAULT_ACADEMIC_YEAR, enabled: true });

  if (subs.isError) return null;
  if (!subs.data) return <Badge variant="neutral">Coverage: …</Badge>;

  const total = subs.data.substitutions.length;
  if (total === 0) return <Badge variant="neutral">No substitutes needed</Badge>;

  const confirmed = subs.data.substitutions.filter((s) => s.status === "confirmed").length;
  const variant = confirmed === total ? "positive" : confirmed === 0 ? "urgent" : "warning";

  return <Badge variant={variant}>Coverage: {confirmed}/{total} confirmed</Badge>;
}

/** Shows the real, persisted Substitution rows for a leave request directly
 * on its card - both roles (the backend allows the owning teacher to read
 * their own leave request's substitutions, not just admin/principal) - so
 * neither role has to copy an id into a separate lookup to see coverage.
 * Collapsed by default (a leave request may have many slots); the query
 * only fires once expanded. */
function InlineSubstitutions({
  schoolId,
  leaveRequestId,
  readOnly,
}: {
  schoolId: number;
  leaveRequestId: number;
  readOnly: boolean;
}) {
  const [expanded, setExpanded] = useState(false);
  const subs = useLeaveRequestSubstitutions({ leaveRequestId, academicYear: DEFAULT_ACADEMIC_YEAR, enabled: expanded });

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setExpanded((e) => !e)}
        className="flex items-center gap-1 text-xs font-medium text-accent hover:underline"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        {expanded ? "Hide substitutes" : "Show substitutes"}
      </button>
      {expanded && (
        <div className="mt-2 flex flex-col gap-2">
          {subs.isLoading && <div className="h-16 animate-pulse rounded-lg bg-elevated/60" />}
          {subs.isError && (
            <p className="text-xs text-urgent">
              {subs.error instanceof ApiError ? subs.error.message : "Failed to load substitutes."}
            </p>
          )}
          {subs.isSuccess && subs.data.substitutions.length === 0 && (
            <p className="text-xs text-ink-muted">No affected timetable slots for this leave request.</p>
          )}
          {subs.isSuccess &&
            subs.data.substitutions.map((sub) => (
              <SubstitutionCard
                key={sub.id ?? `${sub.timetable_slot_id}`}
                schoolId={schoolId}
                sub={sub}
                onConfirmed={() => subs.refetch()}
                readOnly={readOnly}
              />
            ))}
        </div>
      )}
    </div>
  );
}

// --- Teacher's own view: request form (unchanged) + own history -------------

function TeacherLeaveView({ schoolId }: { schoolId: number }) {
  const requests = useLeaveRequests();
  const requestLeave = useRequestLeave();
  const duties = useMySubstituteDuties();
  const lookup = useReferenceLookup(schoolId);
  const subjectName = (id: number) => lookup.data?.subjects.find((s) => s.id === id)?.name ?? `Subject #${id}`;
  const className = (id: number) => lookup.data?.classes.find((c) => c.id === id)?.name ?? `Class #${id}`;
  const teacherName = (id: number) => lookup.data?.teachers.find((t) => t.id === id)?.name ?? `Teacher #${id}`;

  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState("");

  function submitRequest() {
    if (!startDate || !endDate || !reason) return;
    requestLeave.mutate(
      { start_date: startDate, end_date: endDate, reason },
      { onSuccess: () => { setStartDate(""); setEndDate(""); setReason(""); } }
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {(duties.data?.length ?? 0) > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Your substitute duties</CardTitle>
            <CardDescription>Classes you're covering for another teacher's approved leave.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            {duties.data!.map((duty) => (
              <div
                key={duty.substitution_id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-xl bg-elevated/40 px-3.5 py-2.5 text-sm"
              >
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="font-medium text-ink">{subjectName(duty.subject_id)}</span>
                  <span className="text-ink-muted">{className(duty.class_id)}</span>
                  <span className="font-mono text-xs text-ink-muted">
                    {DAY_LABELS[duty.day_of_week]} · Period {duty.period_number + 1}
                  </span>
                  <span className="text-xs text-ink-muted">
                    covering for {teacherName(duty.original_teacher_id)} ({duty.leave_start_date} → {duty.leave_end_date})
                  </span>
                </div>
                <Badge variant={duty.status === "confirmed" ? "positive" : "accent"}>{duty.status}</Badge>
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="grid items-start gap-3 lg:grid-cols-[22rem_1fr]">
      <Card className="h-fit">
        <CardHeader>
          <CardTitle>Request leave</CardTitle>
          <CardDescription>Submit a leave request for approval.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <Field label="Start date">
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </Field>
          <Field label="End date">
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </Field>
          <Field label="Reason">
            <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Feeling unwell" />
          </Field>
          <Button onClick={submitRequest} disabled={!startDate || !endDate || !reason || requestLeave.isPending} className="self-start">
            <CalendarPlus className="h-4 w-4" />
            {requestLeave.isPending ? "Submitting…" : "Submit request"}
          </Button>
          {requestLeave.isError && (
            <p className="text-sm text-urgent">{requestLeave.error instanceof ApiError ? requestLeave.error.message : "Request failed."}</p>
          )}
        </CardContent>
      </Card>

      <div className="flex flex-col gap-2">
        {requests.isLoading && <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />}
        {requests.data?.length === 0 && (
          <Card>
            <CardContent className="py-8 text-center text-sm text-ink-muted">No leave requests yet.</CardContent>
          </Card>
        )}
        {requests.data?.map((lr: LeaveRequest) => (
          <EntityCard
            key={lr.id}
            icon={CalendarClock}
            tone={STATUS_TONE[lr.status]}
            title={`${lr.start_date} → ${lr.end_date}`}
            badges={
              <>
                <Badge variant={lr.status === "pending" ? "warning" : lr.status === "approved" ? "positive" : "urgent"}>{lr.status}</Badge>
                {lr.status === "approved" && <CoverageBadge leaveRequestId={lr.id} />}
              </>
            }
            message={lr.reason}
            meta={`Requested ${new Date(lr.requested_at).toLocaleDateString()}`}
          >
            {lr.status === "approved" && <InlineSubstitutions schoolId={schoolId} leaveRequestId={lr.id} readOnly />}
          </EntityCard>
        ))}
      </div>
      </div>
    </div>
  );
}

// --- Admin/principal view: approval queue is the primary content ------------

/** Secondary action, collapsed by default - filing on behalf of a teacher is
 * real but deliberately not the page's main content for this role, and a
 * teacher selection is REQUIRED (no blank/"file for myself" state is ever
 * reachable - submit stays disabled until a real teacher is chosen), so the
 * old "admin submits with nothing selected" 400 is now structurally
 * unreachable from this UI, not just hidden. */
function FileOnBehalfForm({ schoolId }: { schoolId: number }) {
  const [open, setOpen] = useState(false);
  const lookup = useReferenceLookup(schoolId);
  const requestLeave = useRequestLeave();
  const [teacherId, setTeacherId] = useState("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState("");

  const canSubmit = !!teacherId && !!startDate && !!endDate && !!reason;

  function submit() {
    if (!canSubmit) return;
    requestLeave.mutate(
      { teacher_id: Number(teacherId), start_date: startDate, end_date: endDate, reason },
      {
        onSuccess: () => {
          setTeacherId("");
          setStartDate("");
          setEndDate("");
          setReason("");
          setOpen(false);
        },
      }
    );
  }

  if (!open) {
    return (
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        <CalendarPlus className="h-3.5 w-3.5" /> File leave on behalf of a teacher
      </Button>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">File leave on behalf of a teacher</CardTitle>
        <CardDescription>A specific teacher must be selected - this always files for a real teacher, never for yourself.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Teacher" className="w-56">
            <Select value={teacherId} onValueChange={setTeacherId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a teacher" />
              </SelectTrigger>
              <SelectContent>
                {lookup.data?.teachers.map((t) => (
                  <SelectItem key={t.id} value={String(t.id)}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Start date" className="w-40">
            <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </Field>
          <Field label="End date" className="w-40">
            <Input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </Field>
          <Field label="Reason" className="w-56">
            <Input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Feeling unwell" />
          </Field>
          <Button size="sm" onClick={submit} disabled={!canSubmit || requestLeave.isPending}>
            {requestLeave.isPending ? "Submitting…" : "Submit"}
          </Button>
          <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
        {requestLeave.isError && (
          <p className="text-sm text-urgent">{requestLeave.error instanceof ApiError ? requestLeave.error.message : "Request failed."}</p>
        )}
      </CardContent>
    </Card>
  );
}

function AdminLeaveApprovalView({ schoolId }: { schoolId: number }) {
  const lookup = useReferenceLookup(schoolId);
  const requests = useLeaveRequests();
  const decide = useDecideLeaveRequest();
  const [decidingId, setDecidingId] = useState<string | null>(null);

  function handleDecide(id: number, decision: "approve" | "reject") {
    setDecidingId(String(id));
    decide.mutate(
      { leaveRequestId: id, decision, academicYear: decision === "approve" ? DEFAULT_ACADEMIC_YEAR : undefined },
      { onSettled: () => setDecidingId(null) }
    );
  }

  const teacherName = (id: number) => lookup.data?.teachers.find((t) => t.id === id)?.name ?? `Teacher #${id}`;

  const pending = requests.data?.filter((r) => r.status === "pending") ?? [];
  const decided = requests.data?.filter((r) => r.status !== "pending") ?? [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-display text-sm font-semibold text-ink">Pending approval ({pending.length})</h3>
        <FileOnBehalfForm schoolId={schoolId} />
      </div>

      {requests.isLoading && <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />}
      {!requests.isLoading && pending.length === 0 && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-ink-muted">No pending leave requests.</CardContent>
        </Card>
      )}
      <div className="flex flex-col gap-2">
        {pending.map((lr) => (
          <EntityCard
            key={lr.id}
            icon={CalendarClock}
            tone="warning"
            title={teacherName(lr.teacher_id)}
            badges={<Badge variant="warning">pending</Badge>}
            message={
              <>
                <span className="font-mono text-ink">
                  {lr.start_date} → {lr.end_date}
                </span>{" "}
                · {lr.reason}
              </>
            }
            meta={`Requested ${new Date(lr.requested_at).toLocaleDateString()}`}
            actions={
              <div className="flex gap-1.5">
                <Button size="sm" onClick={() => handleDecide(lr.id, "approve")} disabled={decidingId === String(lr.id)}>
                  Approve
                </Button>
                <Button variant="outline" size="sm" onClick={() => handleDecide(lr.id, "reject")} disabled={decidingId === String(lr.id)}>
                  Reject
                </Button>
              </div>
            }
          />
        ))}
      </div>

      <div className="mt-2 flex flex-col gap-2">
        <h3 className="font-display text-sm font-semibold text-ink-muted">Decided ({decided.length})</h3>
        {decided.length === 0 && <p className="text-sm text-ink-faint">No decided requests yet.</p>}
        {decided.map((lr) => (
          <EntityCard
            key={lr.id}
            icon={CalendarClock}
            tone={STATUS_TONE[lr.status]}
            title={teacherName(lr.teacher_id)}
            badges={
              <>
                <Badge variant={lr.status === "approved" ? "positive" : "urgent"}>{lr.status}</Badge>
                {lr.status === "approved" && <CoverageBadge leaveRequestId={lr.id} />}
              </>
            }
            message={
              <>
                <span className="font-mono text-ink">
                  {lr.start_date} → {lr.end_date}
                </span>{" "}
                · {lr.reason}
              </>
            }
            meta={`Requested ${new Date(lr.requested_at).toLocaleDateString()}`}
          >
            {lr.status === "approved" && <InlineSubstitutions schoolId={schoolId} leaveRequestId={lr.id} readOnly={false} />}
          </EntityCard>
        ))}
      </div>
    </div>
  );
}

function LeaveRequestsTab({ schoolId }: { schoolId: number }) {
  const { role } = useAuthStore();
  const isAdminLike = role === "admin" || role === "principal";
  return isAdminLike ? <AdminLeaveApprovalView schoolId={schoolId} /> : <TeacherLeaveView schoolId={schoolId} />;
}

// --- Coverage preview (read-only, hypothetical teacher/date exploration) ----

function CoveragePreviewTab({ schoolId }: { schoolId: number }) {
  const lookup = useReferenceLookup(schoolId);
  const preview = useSubstituteSuggestionsPreview();
  const [previewTeacher, setPreviewTeacher] = useState("");
  const [previewDate, setPreviewDate] = useState(() => new Date().toISOString().slice(0, 10));

  return (
    <Card>
      <CardHeader>
        <CardTitle>Preview coverage for a teacher/date</CardTitle>
        <CardDescription>
          Read-only exploration — nothing persisted, no leave request needed. For a real leave request's actual
          substitutes, expand "Show substitutes" on its card in Leave Requests instead.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Teacher" className="w-56">
            <Select value={previewTeacher} onValueChange={setPreviewTeacher}>
              <SelectTrigger>
                <SelectValue placeholder="Select teacher" />
              </SelectTrigger>
              <SelectContent>
                {lookup.data?.teachers.map((t) => (
                  <SelectItem key={t.id} value={String(t.id)}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Date" className="w-40">
            <Input type="date" value={previewDate} onChange={(e) => setPreviewDate(e.target.value)} />
          </Field>
          <Button
            variant="outline"
            onClick={() => previewTeacher && preview.mutate({ teacherId: Number(previewTeacher), date: previewDate, academicYear: DEFAULT_ACADEMIC_YEAR })}
            disabled={!previewTeacher || preview.isPending}
          >
            {preview.isPending ? "Loading…" : "Preview"}
          </Button>
        </div>
        {preview.isSuccess && preview.data.slots.length === 0 && <p className="text-xs text-ink-muted">No slots for that teacher/date.</p>}
        {preview.isSuccess &&
          preview.data.slots.map((slot) => (
            <div key={slot.timetable_slot_id} className="rounded-xl border border-border bg-elevated/40 p-3.5 text-sm">
              <span className="font-medium text-ink">Period {slot.period_number + 1}</span>
              <div className="mt-1 flex flex-col gap-1">
                {slot.suggestions.map((c) => (
                  <span key={c.teacher_id} className="font-mono text-xs text-ink-muted">
                    {lookup.data?.teachers.find((t) => t.id === c.teacher_id)?.name ?? `Teacher #${c.teacher_id}`} — {(c.score * 100).toFixed(0)}%
                  </span>
                ))}
              </div>
            </div>
          ))}
      </CardContent>
    </Card>
  );
}

// --- Forecast -----------------------------------------------------------------

function ForecastTab({ schoolId }: { schoolId: number }) {
  const [weekStart, setWeekStart] = useState(mondayOfThisWeek());
  const forecast = useStaffingForecast({ schoolId, weekStart });
  const insufficientData = forecast.data?.data_sufficient === false;

  return (
    <Card>
      <CardHeader>
        <CardTitle>Predicted absence forecast</CardTitle>
        <CardDescription>Recomputed from historical approved leave requests.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Field label="Week starting" className="w-48">
          <Input type="date" value={weekStart} onChange={(e) => setWeekStart(e.target.value)} />
        </Field>
        {forecast.isLoading && <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />}
        {insufficientData && (
          <div className="flex items-start gap-2 rounded-xl border border-border bg-elevated/40 px-3.5 py-2.5 text-sm text-ink-muted">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-ink-faint" />
            <span>
              Insufficient historical data for a confident forecast — only a handful of approved leave requests exist
              for this school so far. The numbers below are shown for reference only, not as a reliable prediction.
            </span>
          </div>
        )}
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {forecast.data?.forecast.map((day) => (
            <StatTile
              key={day.date}
              label={new Date(day.date).toLocaleDateString(undefined, { weekday: "short", day: "numeric" })}
              value={day.predicted_absences.toFixed(1)}
              caption={insufficientData ? "insufficient data" : day.risk_level}
              icon={TrendingUp}
              tone={insufficientData ? "neutral" : day.risk_level === "high" ? "urgent" : day.risk_level === "medium" ? "warning" : "positive"}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

export default function StaffingPage() {
  const { role } = useAuthStore();
  const isAdminLike = role === "admin" || role === "principal";
  const [tab, setTab] = useState("requests");
  const schoolId = useCurrentUser().data?.school_id;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="Staffing & Substitutes" description="Leave requests, approvals, and AI-suggested substitute coverage." />
      {schoolId == null ? (
        <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />
      ) : (
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList>
            <TabsTrigger value="requests">Leave Requests</TabsTrigger>
            {isAdminLike && <TabsTrigger value="preview">Coverage Preview</TabsTrigger>}
            {isAdminLike && <TabsTrigger value="forecast">Forecast</TabsTrigger>}
          </TabsList>
          <TabsContent value="requests">
            <LeaveRequestsTab schoolId={schoolId} />
          </TabsContent>
          {isAdminLike && (
            <TabsContent value="preview">
              <CoveragePreviewTab schoolId={schoolId} />
            </TabsContent>
          )}
          {isAdminLike && (
            <TabsContent value="forecast">
              <ForecastTab schoolId={schoolId} />
            </TabsContent>
          )}
        </Tabs>
      )}
    </div>
  );
}
