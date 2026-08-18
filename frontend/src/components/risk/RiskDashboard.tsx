import { useState } from "react";
import { AlertTriangle, ChevronDown, ClipboardList, MessageSquare, MessageSquarePlus, ShieldAlert, UserCheck, UserPlus, Users } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger, DialogClose } from "@/components/ui/dialog";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import EntityCard from "@/components/shared/EntityCard";
import StatTile from "@/components/shared/StatTile";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useStudentRemarks } from "@/api/hooks/useRemarks";
import { useFlaggedStudents, useCreateRiskFlag, useAcknowledgeFlag, useResolveFlag, useLogIntervention, useFlagInterventions } from "@/api/hooks/useRisk";
import { useSelectedChild } from "@/hooks/useSelectedChild";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { timeAgo } from "@/lib/format";
import { ApiError } from "@/api/client";
import type { RiskFlag } from "@/api/types";

const LEVEL_TONE: Record<string, "urgent" | "warning" | "neutral"> = { high: "urgent", medium: "warning", low: "neutral" };

function FlagStudentDialog({ schoolId }: { schoolId: number }) {
  const lookup = useReferenceLookup(schoolId);
  const create = useCreateRiskFlag();
  const [open, setOpen] = useState(false);
  const [studentId, setStudentId] = useState("");
  const [riskLevel, setRiskLevel] = useState("medium");
  const [reasons, setReasons] = useState("");

  function submit() {
    if (!studentId || !reasons.trim()) return;
    create.mutate(
      { student_id: Number(studentId), risk_level: riskLevel, reasons: reasons.split("\n").map((r) => r.trim()).filter(Boolean) },
      { onSuccess: () => { setOpen(false); setStudentId(""); setReasons(""); } }
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button>
          <UserPlus className="h-4 w-4" /> Flag student
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Flag a student</DialogTitle>
          <DialogDescription>A human judgment call — not an algorithmic score.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Student">
            <Select value={studentId} onValueChange={setStudentId}>
              <SelectTrigger>
                <SelectValue placeholder="Select a student" />
              </SelectTrigger>
              <SelectContent>
                {lookup.data?.students.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    {s.name} · #{s.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field label="Risk level">
            <Select value={riskLevel} onValueChange={setRiskLevel}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="low">Low</SelectItem>
                <SelectItem value="medium">Medium</SelectItem>
                <SelectItem value="high">High</SelectItem>
              </SelectContent>
            </Select>
          </Field>
          <Field label="Reasons" hint="One per line">
            <Textarea value={reasons} onChange={(e) => setReasons(e.target.value)} placeholder={"Seems withdrawn in class\nMissed 3 assignments"} />
          </Field>
          {create.isError && (
            <p className="text-sm text-urgent">{create.error instanceof ApiError ? create.error.message : "Failed to flag student."}</p>
          )}
          <Button onClick={submit} disabled={!studentId || !reasons.trim() || create.isPending} className="self-start">
            {create.isPending ? "Flagging…" : "Flag student"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function InterventionDialog({ flagId }: { flagId: number }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [actionTaken, setActionTaken] = useState("");
  const log = useLogIntervention();

  function submit() {
    if (!note.trim() || !actionTaken.trim()) return;
    log.mutate({ flagId, note, actionTaken }, { onSuccess: () => { setOpen(false); setNote(""); setActionTaken(""); } });
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <MessageSquarePlus className="h-3.5 w-3.5" /> Intervention
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Log an intervention</DialogTitle>
          <DialogDescription>What staff actually did, independent of the flag's status.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Action taken" hint='e.g. "called parent", "counselor referral"'>
            <Input value={actionTaken} onChange={(e) => setActionTaken(e.target.value)} />
          </Field>
          <Field label="Note">
            <Textarea value={note} onChange={(e) => setNote(e.target.value)} />
          </Field>
          {/* This dialog rendered NO error state, so a rejected save (403 on someone else's
              student, 400 on empty text) closed nothing and changed nothing on screen - the
              button simply appeared not to work. */}
          {log.isError && (
            <p className="text-sm text-urgent" role="alert">
              {log.error instanceof ApiError ? log.error.message : "Failed to log the intervention."}
            </p>
          )}
          <Button onClick={submit} disabled={!note.trim() || !actionTaken.trim() || log.isPending} className="self-start">
            {log.isPending ? "Logging…" : "Log intervention"}
          </Button>
          <DialogClose asChild>
            <Button variant="ghost" size="sm" className="self-start">Close</Button>
          </DialogClose>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * What staff have already DONE about this flag.
 *
 * The counterpart to InterventionDialog, which had none - POST /risk/{id}/intervention
 * saved a row that nothing in the app ever displayed. So logging an intervention looked
 * identical to the button being broken, and the next teacher to open the flag had no way to
 * know a parent had already been called. An intervention log nobody can read is not a log.
 *
 * Collapsed and fetched on demand, same as FlagRemarks - a dashboard can list dozens of
 * flags and this would otherwise be one request per flag on every render.
 */
function FlagInterventions({ flagId }: { flagId: number }) {
  const [open, setOpen] = useState(false);
  const interventions = useFlagInterventions(open ? flagId : undefined);
  const items = interventions.data?.items ?? [];

  return (
    <div className="flex flex-col gap-1.5">
      <Button variant="ghost" size="sm" onClick={() => setOpen((o) => !o)} className="self-start">
        <ClipboardList className="h-3.5 w-3.5" />
        {open ? "Hide actions taken" : "Actions taken"}
        <ChevronDown className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </Button>

      {open && (
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-elevated/30 p-2.5">
          {interventions.isLoading ? (
            <p className="text-xs text-ink-muted">Loading…</p>
          ) : interventions.error ? (
            <p className="text-xs text-urgent">
              {interventions.error instanceof ApiError
                ? interventions.error.message
                : "Could not load the intervention history."}
            </p>
          ) : items.length === 0 ? (
            <p className="text-xs text-ink-muted">
              No interventions logged yet. Use "Intervention" above to record an outreach.
            </p>
          ) : (
            items.map((i) => (
              <div key={i.id} className="text-xs">
                <p className="font-medium text-ink">{i.action_taken}</p>
                <p className="text-ink-muted">{i.note}</p>
                <span className="text-[11px] text-ink-faint">
                  {i.created_by_name || `Staff #${i.created_by}`} · {timeAgo(i.created_at)}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}


/**
 * The teacher remarks behind a flag, expandable on the flag itself.
 *
 * WHY REMARKS LIVE HERE RATHER THAN ON THEIR OWN ADMIN PAGE. Remarks and early-warning are
 * not the same feature - one is an observation, the other a triage lifecycle with
 * acknowledge/intervene/resolve - but they are causally linked: remark sentiment is 15% of
 * the risk score (services/risk_scorer.py DEFAULT_WEIGHTS). So the useful place for an
 * admin to READ remarks is next to the flag they contributed to, where the reasons string
 * says sentiment skewed negative and this says which remarks did it. Authoring stays with
 * teachers, who have a class to observe.
 *
 * Fetched only when opened: a dashboard can list dozens of flags and this would otherwise
 * be one request per flag on every render of the page.
 */
function FlagRemarks({ studentId }: { studentId: number }) {
  const [open, setOpen] = useState(false);
  const remarks = useStudentRemarks(open ? studentId : undefined);
  const items = remarks.data ?? [];

  return (
    <div className="flex flex-col gap-1.5">
      <Button variant="ghost" size="sm" onClick={() => setOpen((o) => !o)} className="self-start">
        <MessageSquare className="h-3.5 w-3.5" />
        {open ? "Hide remarks" : "Teacher remarks"}
        <ChevronDown className={`h-3 w-3 transition-transform ${open ? "rotate-180" : ""}`} />
      </Button>

      {open && (
        <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-elevated/30 p-2.5">
          {remarks.isLoading ? (
            <p className="text-xs text-ink-muted">Loading remarks…</p>
          ) : remarks.error ? (
            <p className="text-xs text-urgent">
              {remarks.error instanceof ApiError ? remarks.error.message : "Could not load remarks."}
            </p>
          ) : items.length === 0 ? (
            <p className="text-xs text-ink-muted">
              No teacher remarks recorded for this student yet.
            </p>
          ) : (
            items.slice(0, 5).map((r) => (
              <div key={r.id} className="text-xs">
                <p className="italic text-ink">"{r.content}"</p>
                <span className="text-[11px] text-ink-faint">
                  {r.author_name || "Teacher"} · {r.sentiment_tag} ·{" "}
                  {new Date(r.created_at).toLocaleDateString()}
                </span>
              </div>
            ))
          )}
          {items.length > 5 && (
            <span className="text-[11px] text-ink-faint">
              Showing the 5 most recent of {items.length}.
            </span>
          )}
        </div>
      )}
    </div>
  );
}


function FlagRow({ flag }: { flag: RiskFlag }) {
  const { role } = useAuthStore();
  const isAdminLike = role === "admin" || role === "principal";
  const canAct = role === "teacher" || isAdminLike;
  const acknowledge = useAcknowledgeFlag();
  const resolve = useResolveFlag();

  return (
    <EntityCard
      icon={AlertTriangle}
      tone={flag.status === "resolved" ? "positive" : LEVEL_TONE[flag.risk_level]}
      title={flag.student_name ?? `Student #${flag.student_id}`}
      badges={
        <>
          <Badge variant={flag.risk_level === "high" ? "urgent" : flag.risk_level === "medium" ? "warning" : "neutral"}>{flag.risk_level}</Badge>
          <Badge variant="outline">{flag.status}</Badge>
          {flag.class_name && <Badge variant="outline">{flag.class_name}</Badge>}
        </>
      }
      message={
        <ul className="list-disc space-y-0.5 pl-4">
          {flag.reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      }
      meta={`Score ${flag.score.toFixed(2)} · ${timeAgo(flag.flagged_at)}`}
      actions={
        canAct ? (
          <div className="flex flex-col gap-1.5">
            <div className="flex flex-wrap gap-1.5">
              {flag.status === "open" && (
                <Button variant="outline" size="sm" onClick={() => acknowledge.mutate(flag.id)} disabled={acknowledge.isPending}>
                  <UserCheck className="h-3.5 w-3.5" /> Acknowledge
                </Button>
              )}
              <InterventionDialog flagId={flag.id} />
              {isAdminLike && flag.status !== "resolved" && (
                <Button size="sm" onClick={() => resolve.mutate(flag.id)} disabled={resolve.isPending}>
                  Resolve
                </Button>
              )}
            </div>
            {(acknowledge.isError || resolve.isError) && (
              <p className="text-xs text-urgent" role="alert">
                {(acknowledge.error ?? resolve.error) instanceof ApiError
                  ? (acknowledge.error ?? resolve.error)!.message
                  : "That action could not be completed."}
              </p>
            )}
            <FlagInterventions flagId={flag.id} />
            <FlagRemarks studentId={flag.student_id} />
          </div>
        ) : undefined
      }
    />
  );
}

function FlagFeed({ riskLevel, studentId }: { riskLevel?: string; studentId?: number }) {
  const flagged = useFlaggedStudents({ riskLevel, studentId });

  if (flagged.isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1].map((i) => <div key={i} className="h-20 animate-pulse rounded-lg bg-elevated/60" />)}
      </div>
    );
  }
  if (flagged.error) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-urgent">
          {flagged.error instanceof ApiError ? flagged.error.message : "Failed to load flagged students."}
        </CardContent>
      </Card>
    );
  }
  const items = flagged.data ?? [];
  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-1 py-6 text-center">
          <ShieldAlert className="h-6 w-6 text-positive" />
          <p className="font-display text-sm font-medium text-ink">No flagged students</p>
        </CardContent>
      </Card>
    );
  }
  return (
    <div className="flex flex-col gap-2">
      {items.map((f) => <FlagRow key={f.id} flag={f} />)}
    </div>
  );
}

export default function RiskDashboard() {
  const { role } = useAuthStore();
  const schoolId = useCurrentUser().data?.school_id;
  // enabled: parent only - GET /parent/children is require_role("parent"), so calling it
  // unconditionally on a page all five roles reach meant a guaranteed 403 per staff visit.
  const { children, selectedChildId, setSelectedChildId, showSelector, isLoading: childrenLoading } =
    useSelectedChild({ enabled: role === "parent" });
  const canFlag = role === "teacher" || role === "admin" || role === "principal";

  const parentStudentId = role === "parent" ? selectedChildId : undefined;
  const showChildSelect = role === "parent" && showSelector;

  const allFlagged = useFlaggedStudents(
    role === "parent" ? { studentId: parentStudentId, enabled: parentStudentId !== undefined } : {}
  );
  const counts = { high: 0, medium: 0, low: 0 };
  for (const f of allFlagged.data ?? []) counts[f.risk_level as keyof typeof counts]++;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Early-Warning & Risk"
        description="Attendance, remark sentiment, and manual flags — students who may need support."
        actions={
          canFlag && schoolId != null ? (
            <FlagStudentDialog schoolId={schoolId} />
          ) : showChildSelect ? (
            <Select value={String(selectedChildId ?? "")} onValueChange={(v) => setSelectedChildId(Number(v))}>
              <SelectTrigger className="w-56">
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
          ) : undefined
        }
      />

      {role === "parent" && childrenLoading && <div className="h-16 animate-pulse rounded-2xl bg-elevated/60" />}

      {role === "parent" && !childrenLoading && children.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-1 py-6 text-center">
            <Users className="h-6 w-6 text-ink-muted" />
            <p className="font-display text-sm font-medium text-ink">No linked children</p>
          </CardContent>
        </Card>
      )}

      {(role !== "parent" || parentStudentId !== undefined) && (
        <>
          <div className="flex flex-wrap gap-3">
            <StatTile label="High risk" value={counts.high} icon={AlertTriangle} tone="urgent" />
            <StatTile label="Medium risk" value={counts.medium} icon={AlertTriangle} tone="warning" />
            <StatTile label="Low risk" value={counts.low} icon={ShieldAlert} tone="neutral" />
          </div>

          <Tabs defaultValue="all">
            <TabsList>
              <TabsTrigger value="all">All</TabsTrigger>
              <TabsTrigger value="high">High</TabsTrigger>
              <TabsTrigger value="medium">Medium</TabsTrigger>
              <TabsTrigger value="low">Low</TabsTrigger>
            </TabsList>
            <TabsContent value="all"><FlagFeed studentId={parentStudentId} /></TabsContent>
            <TabsContent value="high"><FlagFeed riskLevel="high" studentId={parentStudentId} /></TabsContent>
            <TabsContent value="medium"><FlagFeed riskLevel="medium" studentId={parentStudentId} /></TabsContent>
            <TabsContent value="low"><FlagFeed riskLevel="low" studentId={parentStudentId} /></TabsContent>
          </Tabs>
        </>
      )}
    </div>
  );
}
