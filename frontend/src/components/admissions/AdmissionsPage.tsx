import { useState } from "react";
import { CheckCircle2, ClipboardList, Send, UserPlus } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger } from "@/components/ui/dialog";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import EntityCard from "@/components/shared/EntityCard";
import { useSubmitApplication, useApplicationsList, useUpdateApplication } from "@/api/hooks/useAdmissions";
import { DEMO_SCHOOL_ID, DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { ApiError } from "@/api/client";
import type { AdmissionApplication, AdmissionStatus } from "@/api/types";

const STATUS_TONE: Record<AdmissionStatus, "urgent" | "positive" | "warning" | "neutral"> = {
  submitted: "neutral",
  under_review: "warning",
  accepted: "positive",
  rejected: "urgent",
};

// The real state machine (services/admissions_rules.py) — mirrored here only to
// decide which action buttons to offer. The backend re-checks this itself and
// 400s with a clear reason on an illegal transition either way (see the error
// display in DecisionDialog below), so this is a UX nicety, not the real guard.
const LEGAL_NEXT: Record<AdmissionStatus, AdmissionStatus[]> = {
  submitted: ["under_review", "rejected"],
  under_review: ["accepted", "rejected"],
  accepted: [],
  rejected: [],
};

const STATUS_TABS: (AdmissionStatus | "all")[] = ["all", "submitted", "under_review", "accepted", "rejected"];

function SubmitTab() {
  const submit = useSubmitApplication();
  const [applicantName, setApplicantName] = useState("");
  const [dob, setDob] = useState("");
  const [guardianEmail, setGuardianEmail] = useState("");
  const [gradeApplied, setGradeApplied] = useState("");

  function handleSubmit() {
    if (!applicantName.trim() || !dob || !guardianEmail.trim() || !gradeApplied.trim()) return;
    submit.mutate(
      {
        school_id: DEMO_SCHOOL_ID,
        academic_year: DEFAULT_ACADEMIC_YEAR,
        applicant_name: applicantName,
        dob,
        guardian_email: guardianEmail,
        grade_applied: gradeApplied,
      },
      { onSuccess: () => { setApplicantName(""); setDob(""); setGuardianEmail(""); setGradeApplied(""); } }
    );
  }

  return (
    <Card className="max-w-xl">
      <CardHeader>
        <CardTitle>New admission application</CardTitle>
        <CardDescription>Typically entered by office staff, possibly pre-filled via OCR of an admission form.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Field label="Applicant name">
          <Input value={applicantName} onChange={(e) => setApplicantName(e.target.value)} placeholder="Jane Doe" />
        </Field>
        <Field label="Date of birth">
          <Input type="date" value={dob} onChange={(e) => setDob(e.target.value)} />
        </Field>
        <Field label="Guardian email">
          <Input type="email" value={guardianEmail} onChange={(e) => setGuardianEmail(e.target.value)} placeholder="guardian@example.com" />
        </Field>
        <Field label="Grade applied" hint="Must match an offered class name for this school/academic year">
          <Input value={gradeApplied} onChange={(e) => setGradeApplied(e.target.value)} placeholder="Class 8A" />
        </Field>
        <Button
          onClick={handleSubmit}
          disabled={!applicantName.trim() || !dob || !guardianEmail.trim() || !gradeApplied.trim() || submit.isPending}
          className="self-start"
        >
          <Send className="h-4 w-4" />
          {submit.isPending ? "Submitting…" : "Submit application"}
        </Button>
        {submit.isError && (
          <p className="text-sm text-urgent">{submit.error instanceof ApiError ? submit.error.message : "Submission failed."}</p>
        )}
        {submit.isSuccess && (
          <p className="text-sm text-positive">
            Application #{submit.data.id} submitted — status <span className="font-mono">{submit.data.status}</span>.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function DecisionDialog({ application, target }: { application: AdmissionApplication; target: AdmissionStatus }) {
  const [open, setOpen] = useState(false);
  const [justification, setJustification] = useState("");
  const [studentUserId, setStudentUserId] = useState("");
  const [classId, setClassId] = useState("");
  const update = useUpdateApplication();

  const isAccept = target === "accepted";

  function submit() {
    update.mutate(
      {
        id: application.id,
        status: target,
        decisionJustification: justification || undefined,
        studentUserId: isAccept && studentUserId ? Number(studentUserId) : undefined,
        classId: isAccept && classId ? Number(classId) : undefined,
      },
      { onSuccess: () => setOpen(false) }
    );
  }

  const label = target === "under_review" ? "Move to review" : target === "accepted" ? "Accept" : "Reject";

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant={target === "rejected" ? "outline" : "default"} size="sm">
          {label}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{label}: {application.applicant_name}</DialogTitle>
          <DialogDescription>
            {application.status} → {target}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          {isAccept && (
            <>
              <Field
                label="Student user ID"
                hint="Optional — an ALREADY-EXISTING user id. Required together with class ID to create a real Enrollment; account creation itself is out of scope (no signup flow exists)."
              >
                <Input type="number" value={studentUserId} onChange={(e) => setStudentUserId(e.target.value)} />
              </Field>
              <Field label="Class ID" hint="Optional, required alongside student user ID">
                <Input type="number" value={classId} onChange={(e) => setClassId(e.target.value)} />
              </Field>
            </>
          )}
          <Field label="Justification (optional)">
            <Textarea value={justification} onChange={(e) => setJustification(e.target.value)} />
          </Field>
          {update.isError && (
            <p className="text-sm text-urgent">
              {update.error instanceof ApiError ? update.error.message : "Decision failed."}
            </p>
          )}
          {update.isSuccess && (
            <p className="text-sm text-positive">
              Status now <span className="font-mono">{update.data.status}</span>.{" "}
              {update.data.enrollment_created ? "A real Enrollment was created." : "No Enrollment was created."}
            </p>
          )}
          <Button onClick={submit} disabled={update.isPending} className="self-start">
            {update.isPending ? "Submitting…" : `Confirm ${label.toLowerCase()}`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ApplicationRow({ application }: { application: AdmissionApplication }) {
  const nextStates = LEGAL_NEXT[application.status];
  return (
    <EntityCard
      icon={ClipboardList}
      tone={STATUS_TONE[application.status]}
      title={application.applicant_name}
      badges={
        <>
          <Badge variant={application.status === "accepted" ? "positive" : application.status === "rejected" ? "urgent" : "outline"}>
            {application.status}
          </Badge>
          <Badge variant="outline">Grade {application.grade_applied}</Badge>
        </>
      }
      message={`DOB ${application.dob} · ${application.guardian_email}`}
      meta={`Application #${application.id} · submitted ${new Date(application.submitted_at).toLocaleDateString()}${
        application.enrolled_student_id ? ` · enrolled as student #${application.enrolled_student_id}` : ""
      }`}
      actions={
        nextStates.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {nextStates.map((target) => (
              <DecisionDialog key={target} application={application} target={target} />
            ))}
          </div>
        ) : (
          <Badge variant="neutral">Terminal</Badge>
        )
      }
    />
  );
}

function ReviewQueueTab() {
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_TABS)[number]>("all");
  const list = useApplicationsList({ status: statusFilter === "all" ? undefined : statusFilter, pageSize: 50 });
  const items = list.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3">
      <Tabs value={statusFilter} onValueChange={(v) => setStatusFilter(v as typeof statusFilter)}>
        <TabsList>
          {STATUS_TABS.map((s) => (
            <TabsTrigger key={s} value={s}>
              {s === "all" ? "All" : s}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>

      {list.isLoading && <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />}
      {list.error && (
        <p className="text-sm text-urgent">{list.error instanceof ApiError ? list.error.message : "Failed to load applications."}</p>
      )}
      {!list.isLoading && items.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-1 py-8 text-center">
            <CheckCircle2 className="h-6 w-6 text-ink-muted" />
            <p className="text-sm text-ink-muted">No applications match this filter.</p>
          </CardContent>
        </Card>
      )}
      <div className="flex flex-col gap-2">
        {items.map((a) => (
          <ApplicationRow key={a.id} application={a} />
        ))}
      </div>
      {list.data && list.data.total > items.length && (
        <p className="text-xs text-ink-faint">Showing {items.length} of {list.data.total}.</p>
      )}
    </div>
  );
}

export default function AdmissionsPage() {
  const { role } = useAuthStore();
  // POST /admin/admissions/applications is admin-only on the real backend
  // (principal is not in that route's require_role list) - the Submit tab is
  // hidden for principal rather than shown-then-403ing.
  const canSubmit = role === "admin";

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="Admissions" description="Application intake and the submitted → under_review → accepted/rejected review queue." />
      <Tabs defaultValue="queue">
        <TabsList>
          <TabsTrigger value="queue">
            <ClipboardList className="h-3.5 w-3.5" /> Review queue
          </TabsTrigger>
          {canSubmit && (
            <TabsTrigger value="submit">
              <UserPlus className="h-3.5 w-3.5" /> Submit
            </TabsTrigger>
          )}
        </TabsList>
        <TabsContent value="queue">
          <ReviewQueueTab />
        </TabsContent>
        {canSubmit && (
          <TabsContent value="submit">
            <SubmitTab />
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
