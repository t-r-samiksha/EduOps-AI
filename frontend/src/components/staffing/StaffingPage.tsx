import { useState } from "react";
import { CalendarClock, CalendarPlus, TrendingUp, Users } from "lucide-react";
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
  useSuggestSubstitutions,
  useConfirmSubstitution,
  useStaffingForecast,
  useSubstituteSuggestionsPreview,
} from "@/api/hooks/useStaffing";
import { DEFAULT_ACADEMIC_YEAR, DEMO_SCHOOL_ID, DAY_LABELS } from "@/lib/constants";
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

function LeaveRequestsTab({ onReviewSubstitutes }: { onReviewSubstitutes: (leaveRequestId: number) => void }) {
  const { role } = useAuthStore();
  const isAdminLike = role === "admin" || role === "principal";
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
  const requests = useLeaveRequests();
  const requestLeave = useRequestLeave();
  const decide = useDecideLeaveRequest();
  const [decidingId, setDecidingId] = useState<string | null>(null);

  const [teacherId, setTeacherId] = useState<string>("");
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [reason, setReason] = useState("");

  function submitRequest() {
    if (!startDate || !endDate || !reason) return;
    requestLeave.mutate(
      { teacher_id: isAdminLike && teacherId ? Number(teacherId) : undefined, start_date: startDate, end_date: endDate, reason },
      { onSuccess: () => { setStartDate(""); setEndDate(""); setReason(""); setTeacherId(""); } }
    );
  }

  function handleDecide(id: number, decision: "approve" | "reject") {
    setDecidingId(String(id));
    decide.mutate(
      { leaveRequestId: id, decision, academicYear: decision === "approve" ? DEFAULT_ACADEMIC_YEAR : undefined },
      { onSettled: () => setDecidingId(null) }
    );
  }

  const teacherName = (id: number) => lookup.data?.teachers.find((t) => t.id === id)?.name ?? `Teacher #${id}`;

  return (
    <div className="grid items-start gap-3 lg:grid-cols-[22rem_1fr]">
      <Card className="h-fit">
        <CardHeader>
          <CardTitle>Request leave</CardTitle>
          <CardDescription>
            {isAdminLike ? "File on behalf of a teacher, or leave blank to file for yourself." : "Submit a leave request for approval."}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {isAdminLike && (
            <Field label="Teacher (optional)">
              <Select value={teacherId} onValueChange={setTeacherId}>
                <SelectTrigger>
                  <SelectValue placeholder="File for myself" />
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
          )}
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
            title={isAdminLike ? teacherName(lr.teacher_id) : `${lr.start_date} → ${lr.end_date}`}
            badges={<Badge variant={lr.status === "pending" ? "warning" : lr.status === "approved" ? "positive" : "urgent"}>{lr.status}</Badge>}
            message={
              <>
                {isAdminLike && (
                  <span className="font-mono text-ink">
                    {lr.start_date} → {lr.end_date}
                  </span>
                )}
                {isAdminLike && " · "}
                {lr.reason}
              </>
            }
            meta={`Requested ${new Date(lr.requested_at).toLocaleDateString()}`}
            actions={
              isAdminLike && lr.status === "pending" ? (
                <div className="flex gap-1.5">
                  <Button size="sm" onClick={() => handleDecide(lr.id, "approve")} disabled={decidingId === String(lr.id)}>
                    Approve
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => handleDecide(lr.id, "reject")} disabled={decidingId === String(lr.id)}>
                    Reject
                  </Button>
                </div>
              ) : isAdminLike && lr.status === "approved" ? (
                <Button variant="outline" size="sm" onClick={() => onReviewSubstitutes(lr.id)}>
                  <Users className="h-3.5 w-3.5" /> Substitutes
                </Button>
              ) : undefined
            }
          />
        ))}
      </div>
    </div>
  );
}

function SubstitutionCard({ sub, onConfirmed }: { sub: Substitution; onConfirmed: () => void }) {
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
  const confirm = useConfirmSubstitution();
  const [pickedTeacher, setPickedTeacher] = useState<string>(
    sub.substitute_teacher_id ? String(sub.substitute_teacher_id) : sub.candidates[0] ? String(sub.candidates[0].teacher_id) : ""
  );

  const subjectName = lookup.data?.subjects.find((s) => s.id === sub.subject_id)?.name ?? `Subject #${sub.subject_id}`;
  const className = lookup.data?.classes.find((c) => c.id === sub.class_id)?.name ?? `Class #${sub.class_id}`;
  const teacherName = (id: number) => lookup.data?.teachers.find((t) => t.id === id)?.name ?? `Teacher #${id}`;

  const isConfirmed = sub.status === "confirmed";

  function handleConfirm() {
    if (!sub.id || !pickedTeacher) return;
    confirm.mutate({ substitutionId: sub.id, substituteTeacherId: Number(pickedTeacher) }, { onSuccess: () => onConfirmed() });
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
          {sub.candidates.length === 0 && <p className="text-xs text-ink-faint">No candidates returned by the solver.</p>}
          {sub.candidates.map((c) => (
            <div key={c.teacher_id} className="flex items-center justify-between rounded-xl bg-elevated/60 px-3.5 py-2 text-sm">
              <span className="text-ink">{teacherName(c.teacher_id)}</span>
              <span className="font-mono text-xs tabular-nums text-ink-muted">{(c.score * 100).toFixed(0)}% · {c.reason}</span>
            </div>
          ))}
        </div>

        {!isConfirmed && sub.id && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Confirm substitute" className="min-w-[12rem] flex-1">
              <Select value={pickedTeacher} onValueChange={setPickedTeacher}>
                <SelectTrigger>
                  <SelectValue placeholder="Select teacher" />
                </SelectTrigger>
                <SelectContent>
                  {sub.candidates.map((c) => (
                    <SelectItem key={c.teacher_id} value={String(c.teacher_id)}>
                      {teacherName(c.teacher_id)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
            <Button size="sm" onClick={handleConfirm} disabled={!pickedTeacher || confirm.isPending}>
              {confirm.isPending ? "Confirming…" : "Confirm"}
            </Button>
          </div>
        )}
        {isConfirmed && sub.substitute_teacher_id && (
          <p className="text-sm text-positive">Confirmed: {teacherName(sub.substitute_teacher_id)}</p>
        )}
        {confirm.data?.conflicts && confirm.data.conflicts.length > 0 && (
          <p className="text-sm text-urgent">{confirm.data.conflicts.map((c) => c.message).join("; ")}</p>
        )}
      </CardContent>
    </Card>
  );
}

function SubstitutionsTab({ initialLeaveRequestId }: { initialLeaveRequestId: number | null }) {
  const [leaveRequestId, setLeaveRequestId] = useState<string>(initialLeaveRequestId ? String(initialLeaveRequestId) : "");
  const suggest = useSuggestSubstitutions();
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);

  const preview = useSubstituteSuggestionsPreview();
  const [previewTeacher, setPreviewTeacher] = useState("");
  const [previewDate, setPreviewDate] = useState(() => new Date().toISOString().slice(0, 10));

  function loadSubstitutions() {
    if (!leaveRequestId) return;
    suggest.mutate({ leave_request_id: Number(leaveRequestId), academic_year: DEFAULT_ACADEMIC_YEAR });
  }

  return (
    <div className="flex flex-col gap-3">
      <Card>
        <CardHeader>
          <CardTitle>Review substitutes for a leave request</CardTitle>
          <CardDescription>
            Pulls the persisted substitution rows auto-created on approval (one per affected timetable slot) so they can be confirmed.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end gap-3">
          <Field label="Leave request ID" className="w-48">
            <Input type="number" value={leaveRequestId} onChange={(e) => setLeaveRequestId(e.target.value)} placeholder="e.g. 12" />
          </Field>
          <Button onClick={loadSubstitutions} disabled={!leaveRequestId || suggest.isPending}>
            {suggest.isPending ? "Loading…" : "Load substitutions"}
          </Button>
        </CardContent>
      </Card>

      {suggest.isSuccess && suggest.data.substitutions.length === 0 && (
        <p className="text-sm text-ink-muted">No affected timetable slots for this leave request.</p>
      )}
      {suggest.isSuccess && (
        <div className="grid gap-3 md:grid-cols-2">
          {suggest.data.substitutions.map((sub) => (
            <SubstitutionCard key={sub.id ?? `${sub.timetable_slot_id}`} sub={sub} onConfirmed={loadSubstitutions} />
          ))}
        </div>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Preview coverage for a teacher/date</CardTitle>
          <CardDescription>Read-only exploration — nothing persisted, no leave request needed.</CardDescription>
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
    </div>
  );
}

function ForecastTab() {
  const [weekStart, setWeekStart] = useState(mondayOfThisWeek());
  const forecast = useStaffingForecast({ schoolId: DEMO_SCHOOL_ID, weekStart });

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
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {forecast.data?.forecast.map((day) => (
            <StatTile
              key={day.date}
              label={new Date(day.date).toLocaleDateString(undefined, { weekday: "short", day: "numeric" })}
              value={day.predicted_absences.toFixed(1)}
              caption={day.risk_level}
              icon={TrendingUp}
              tone={day.risk_level === "high" ? "urgent" : day.risk_level === "medium" ? "warning" : "positive"}
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
  const [reviewLeaveId, setReviewLeaveId] = useState<number | null>(null);
  const [tab, setTab] = useState("requests");

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="Staffing & Substitutes" description="Leave requests, approvals, and AI-suggested substitute coverage." />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList>
          <TabsTrigger value="requests">Leave Requests</TabsTrigger>
          {isAdminLike && <TabsTrigger value="substitutions">Substitutions</TabsTrigger>}
          {isAdminLike && <TabsTrigger value="forecast">Forecast</TabsTrigger>}
        </TabsList>
        <TabsContent value="requests">
          <LeaveRequestsTab
            onReviewSubstitutes={(id) => {
              setReviewLeaveId(id);
              setTab("substitutions");
            }}
          />
        </TabsContent>
        {isAdminLike && (
          <TabsContent value="substitutions">
            <SubstitutionsTab initialLeaveRequestId={reviewLeaveId} />
          </TabsContent>
        )}
        {isAdminLike && (
          <TabsContent value="forecast">
            <ForecastTab />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
