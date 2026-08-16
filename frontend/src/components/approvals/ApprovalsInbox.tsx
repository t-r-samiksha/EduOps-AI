import { useState } from "react";
import { CalendarClock, FileCheck2 } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger } from "@/components/ui/dialog";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import EntityCard from "@/components/shared/EntityCard";
import { usePendingApprovals, useDecideApproval } from "@/api/hooks/useApprovals";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { gradeLevelDisplay } from "@/lib/format";
import { timeAgo } from "@/lib/format";
import { ApiError } from "@/api/client";
import type { Approval } from "@/api/types";

const TYPE_LABEL: Record<string, string> = {
  leave_request: "Leave request",
  admission_application: "Admission application",
};

function summarizePayload(approval: Approval): string {
  const p = approval.payload;
  if (approval.type === "leave_request") {
    return `${p.start_date} → ${p.end_date} · ${p.reason}`;
  }
  if (approval.type === "admission_application") {
    // grade_applied is a stringified grade LEVEL now (e.g. "3", "-2" for LKG),
    // never a section name - see admissions_rules.py. gradeLevelDisplay handles
    // the LKG/UKG/Nursery labels; this is also where the old "Grade Grade 3 - A"
    // double-label bug lived (grade_applied used to already contain "Grade").
    return `${p.applicant_name} · DOB ${p.dob} · ${gradeLevelDisplay(String(p.grade_applied))} · ${p.guardian_email}`;
  }
  return JSON.stringify(p);
}

function DecisionDialog({ approval, decision }: { approval: Approval; decision: "approve" | "reject" }) {
  const [open, setOpen] = useState(false);
  const [comment, setComment] = useState("");
  const decide = useDecideApproval();

  const isAdmission = approval.type === "admission_application";
  // Real backend requirement (services/admissions_rules.py::check_reject_reason) -
  // rejecting an admission application needs a real reason; other approval types
  // don't have this requirement today.
  const requiresReason = isAdmission && decision === "reject";

  function submit() {
    if (requiresReason && !comment.trim()) return;
    decide.mutate(
      {
        id: approval.id,
        decision,
        comment: comment || undefined,
        academicYear: approval.type === "leave_request" && decision === "approve" ? DEFAULT_ACADEMIC_YEAR : undefined,
      },
      { onSuccess: () => setOpen(false) }
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant={decision === "approve" ? "default" : "outline"} size="sm">
          {decision === "approve" ? "Approve" : "Reject"}
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{decision === "approve" ? "Approve" : "Reject"} {TYPE_LABEL[approval.type] ?? approval.type}</DialogTitle>
          <DialogDescription>
            {summarizePayload(approval)}
            {isAdmission && decision === "approve" && " — a section, student account, and guardian link are all assigned automatically."}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label={requiresReason ? "Reason (required)" : "Comment (optional)"}>
            <Textarea value={comment} onChange={(e) => setComment(e.target.value)} />
          </Field>
          {decide.isError && (
            <p className="text-sm text-urgent">{decide.error instanceof ApiError ? decide.error.message : "Decision failed."}</p>
          )}
          <Button onClick={submit} disabled={decide.isPending || (requiresReason && !comment.trim())} className="self-start">
            {decide.isPending ? "Submitting…" : `Confirm ${decision}`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export default function ApprovalsInbox() {
  const approvals = usePendingApprovals();
  const items = approvals.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Approvals"
        description="Pending decisions gated on someone other than the requester — leave requests and admission applications."
      />

      {approvals.isLoading && (
        <div className="flex flex-col gap-2">
          {[0, 1].map((i) => <div key={i} className="h-20 animate-pulse rounded-lg bg-elevated/60" />)}
        </div>
      )}

      {!approvals.isLoading && items.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-1 py-6 text-center">
            <FileCheck2 className="h-6 w-6 text-positive" />
            <p className="font-display text-sm font-medium text-ink">Inbox zero</p>
            <p className="text-xs text-ink-muted">Nothing pending a decision right now.</p>
          </CardContent>
        </Card>
      )}

      <div className="flex flex-col gap-2">
        {items.map((approval) => (
          <EntityCard
            key={approval.id}
            icon={CalendarClock}
            tone="warning"
            title={TYPE_LABEL[approval.type] ?? approval.type}
            badges={<Badge variant="outline">#{approval.entity_id}</Badge>}
            message={summarizePayload(approval)}
            meta={`Requested by #${approval.requested_by} · ${timeAgo(approval.requested_at)}`}
            actions={
              <div className="flex gap-1.5">
                <DecisionDialog approval={approval} decision="approve" />
                <DecisionDialog approval={approval} decision="reject" />
              </div>
            }
          />
        ))}
      </div>
    </div>
  );
}
