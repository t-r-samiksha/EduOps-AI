import { useState } from "react";
import { CheckCircle2, ClipboardList, FileScan, Pencil, Send, UserPlus } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import EntityCard from "@/components/shared/EntityCard";
import FileDropzone from "@/components/shared/FileDropzone";
import {
  useSubmitApplication,
  useApplicationsList,
  useApplication,
  useOfferedGradeLevels,
  useUpdateApplication,
  useUpdateApplicationDetails,
  useAttachDocument,
} from "@/api/hooks/useAdmissions";
import { useUploadDocument } from "@/api/hooks/useOcr";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { gradeLevelDisplay } from "@/lib/format";
import { ApiError } from "@/api/client";
import type { AdmissionApplication, AdmissionStatus, DocumentDetail, DocumentType } from "@/api/types";

const DOCUMENT_TYPE_LABEL: Record<DocumentType, string> = {
  admission_form: "Admission Form",
  marksheet: "Marksheet",
  id_proof: "ID Proof",
  other: "Other",
};

// A real intake process typically involves these three document types -
// admission_form is expected but not a hard gate here (it's how the application
// itself came to exist in the routed-upload flow, but one submitted via the
// Submit tab below has no document at all yet). marksheet/id_proof ARE a real,
// backend-enforced hard requirement to accept - see
// REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE below (this used to be purely
// informational; that decision was overridden - compulsory now).
const EXPECTED_DOCUMENT_TYPES: DocumentType[] = ["admission_form", "marksheet", "id_proof"];

// Mirrors admissions.py's REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE exactly - the
// backend is the real, authoritative enforcement (accept 400s without these
// regardless of what this UI does), but disabling Accept client-side here saves
// an admin the round-trip of clicking it just to learn that.
const REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE: DocumentType[] = ["marksheet", "id_proof"];

const STATUS_TONE: Record<AdmissionStatus, "urgent" | "positive" | "warning" | "neutral"> = {
  submitted: "neutral",
  under_review: "warning",
  accepted: "positive",
  rejected: "urgent",
};

// The real state machine (services/admissions_rules.py) — mirrored here only to
// decide which action buttons to offer. The backend re-checks this itself and
// 400s with a clear reason on an illegal transition either way (see the error
// display in ApplicationDetailDialog below), so this is a UX nicety, not the real guard.
const LEGAL_NEXT: Record<AdmissionStatus, AdmissionStatus[]> = {
  submitted: ["under_review", "rejected"],
  under_review: ["accepted", "rejected"],
  accepted: [],
  rejected: [],
};

const STATUS_TABS: (AdmissionStatus | "all")[] = ["all", "submitted", "under_review", "accepted", "rejected"];

export function GradeLevelSelect({
  schoolId,
  value,
  onChange,
}: {
  schoolId: number;
  value: string;
  onChange: (value: string) => void;
}) {
  const gradeLevels = useOfferedGradeLevels(schoolId, DEFAULT_ACADEMIC_YEAR);
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger>
        <SelectValue placeholder={gradeLevels.isLoading ? "Loading…" : "Select grade"} />
      </SelectTrigger>
      <SelectContent>
        {gradeLevels.data?.items.map((g) => (
          <SelectItem key={g.grade_level} value={String(g.grade_level)}>
            {g.display}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function SubmitTab({ schoolId }: { schoolId: number }) {
  const submit = useSubmitApplication();
  const [applicantName, setApplicantName] = useState("");
  const [dob, setDob] = useState("");
  const [guardianEmail, setGuardianEmail] = useState("");
  const [guardianName, setGuardianName] = useState("");
  const [guardianPhone, setGuardianPhone] = useState("");
  const [gradeApplied, setGradeApplied] = useState("");

  function handleSubmit() {
    if (!applicantName.trim() || !dob || !guardianEmail.trim() || !gradeApplied) return;
    submit.mutate(
      {
        school_id: schoolId,
        academic_year: DEFAULT_ACADEMIC_YEAR,
        applicant_name: applicantName,
        dob,
        guardian_email: guardianEmail,
        guardian_name: guardianName.trim() || undefined,
        guardian_phone: guardianPhone.trim() || undefined,
        grade_applied: gradeApplied,
      },
      {
        onSuccess: () => {
          setApplicantName("");
          setDob("");
          setGuardianEmail("");
          setGuardianName("");
          setGuardianPhone("");
          setGradeApplied("");
        },
      }
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
        <Field label="Guardian name" hint="Optional, but becomes the real name on the guardian's account once accepted">
          <Input value={guardianName} onChange={(e) => setGuardianName(e.target.value)} placeholder="Rajesh Sharma" />
        </Field>
        <Field label="Guardian phone" hint="Optional">
          <Input type="tel" value={guardianPhone} onChange={(e) => setGuardianPhone(e.target.value)} placeholder="9876543210" />
        </Field>
        <Field label="Grade applied" hint="Grade level only — the specific section is assigned automatically on acceptance">
          <GradeLevelSelect schoolId={schoolId} value={gradeApplied} onChange={setGradeApplied} />
        </Field>
        <Button
          onClick={handleSubmit}
          disabled={!applicantName.trim() || !dob || !guardianEmail.trim() || !gradeApplied || submit.isPending}
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
            Application #{submit.data.id} submitted — status <span className="font-mono">{submit.data.status}</span>. Attach a
            marksheet and ID proof to it (Document OCR page) before it can be accepted.
          </p>
        )}
        <p className="text-xs text-ink-muted">
          Note: a marksheet and ID proof must be linked to this application (via the Document OCR page) before it can be
          accepted — this form only captures the applicant's declared details.
        </p>
      </CardContent>
    </Card>
  );
}

/** Read-only rendering of one linked document's extracted fields - the document
 * is now embedded directly in the application detail response (see
 * AdmissionApplicationDetail), not fetched separately per id - no more N extra
 * round-trips for N linked documents. Flags low-confidence fields the same way
 * OcrPage.tsx's EntityRow does, since a marksheet/ID proof's OCR quality matters
 * just as much here as it does on the main OCR review screen. */
function LinkedDocumentPanel({ doc }: { doc: DocumentDetail }) {
  const lowConfidenceFields = new Set(doc.entities.filter((e) => e.is_low_confidence).map((e) => e.field_name));
  const fields = Object.entries(doc.extracted_fields);

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">
          {DOCUMENT_TYPE_LABEL[doc.document_type]} · Document #{doc.id}
        </CardTitle>
        <CardDescription>Uploaded {new Date(doc.uploaded_at).toLocaleString()}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-1.5">
        {fields.length === 0 && <p className="text-xs text-ink-muted">No fields extracted from this document.</p>}
        {fields.map(([field, value]) => (
          <div key={field} className="flex items-center justify-between rounded-lg bg-elevated/40 px-3 py-1.5 text-xs">
            <span className="font-mono uppercase tracking-wide text-ink-muted">{field}</span>
            <span className="flex items-center gap-1.5">
              {lowConfidenceFields.has(field) && <Badge variant="warning">Low confidence</Badge>}
              <span className="font-medium text-ink">{value}</span>
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

/** Coverage of the three document types a real admission intake typically
 * involves. marksheet/id_proof are a REAL hard requirement to accept (see
 * REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE and the disabled-Accept-button logic in
 * ApplicationDetailDialog below) - their badges say "required" when missing, not
 * just "not yet linked", so the coverage row itself explains why Accept is
 * blocked. admission_form has no such gate (an application submitted via the
 * Submit tab genuinely has no document at all yet). */
function DocumentCoverage({ documents }: { documents: DocumentDetail[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {EXPECTED_DOCUMENT_TYPES.map((type) => {
        const present = documents.some((d) => d.document_type === type);
        const required = REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE.includes(type);
        return (
          <Badge key={type} variant={present ? "positive" : required ? "urgent" : "outline"}>
            {DOCUMENT_TYPE_LABEL[type]} {present ? "✓" : required ? "· required" : "· not yet linked"}
          </Badge>
        );
      })}
    </div>
  );
}

/** Upload a new document and attach it to this application in one step - the
 * chosen path of the two options considered (upload-in-place vs. pick from an
 * existing list/search of the school's documents): a real intake moment is a
 * parent handing over a physical marksheet/ID proof right now, which this
 * mirrors directly, and avoids building a second parallel document-browsing UI
 * for what's ultimately the same "upload it" action the very first linked
 * document (the admission_form) already went through via OCR routing. */
function AttachDocumentPanel({ schoolId, applicationId }: { schoolId: number; applicationId: number }) {
  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState<DocumentType>("marksheet");
  const upload = useUploadDocument(schoolId);
  const attach = useAttachDocument();

  function submit() {
    if (!file) return;
    upload.mutate(
      { file, documentType },
      { onSuccess: (result) => attach.mutate({ applicationId, documentId: result.id }, { onSuccess: () => setFile(null) }) }
    );
  }

  const pending = upload.isPending || attach.isPending;

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-elevated/40 p-3">
      <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">Attach another document</span>
      <div className="flex flex-wrap items-end gap-2">
        <Field label="Type" className="w-36">
          <Select value={documentType} onValueChange={(v) => setDocumentType(v as DocumentType)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(["marksheet", "id_proof", "admission_form", "other"] as DocumentType[]).map((t) => (
                <SelectItem key={t} value={t}>
                  {DOCUMENT_TYPE_LABEL[t]}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <FileDropzone file={file} onFileSelected={setFile} className="flex-1 py-4" />
        <Button size="sm" onClick={submit} disabled={!file || pending}>
          <FileScan className="h-3.5 w-3.5" />
          {pending ? "Attaching…" : "Upload & attach"}
        </Button>
      </div>
      {(upload.isError || attach.isError) && (
        <p className="text-xs text-urgent">
          {(upload.error instanceof ApiError && upload.error.message) ||
            (attach.error instanceof ApiError && attach.error.message) ||
            "Failed to attach document."}
        </p>
      )}
    </div>
  );
}

/** Full applicant detail view - opened from a card click, not just a summary row.
 * Accept/Reject now live HERE instead of on the card's inline quick-actions (the
 * card previously duplicated a shrunk version of this same decision - one real
 * place to decide, with the full context: linked document(s) + extracted fields,
 * so an admin doesn't have to navigate away to see what the application was
 * actually based on). */
function ApplicationDetailDialog({
  applicationId,
  schoolId,
  open,
  onOpenChange,
}: {
  applicationId: number;
  schoolId: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const detail = useApplication(open ? applicationId : null);
  const lookup = useReferenceLookup(schoolId);
  const update = useUpdateApplication();
  const updateDetails = useUpdateApplicationDetails();
  const [justification, setJustification] = useState("");
  const [editing, setEditing] = useState(false);
  const [editApplicantName, setEditApplicantName] = useState("");
  const [editDob, setEditDob] = useState("");
  const [editGuardianEmail, setEditGuardianEmail] = useState("");
  const [editGuardianName, setEditGuardianName] = useState("");
  const [editGuardianPhone, setEditGuardianPhone] = useState("");

  const application = detail.data;
  const nextStates = application ? LEGAL_NEXT[application.status] : [];
  const needsReasonFor = (target: AdmissionStatus) => target === "rejected";
  const missingRequiredTypes = application
    ? REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE.filter((t) => !application.documents.some((d) => d.document_type === t))
    : [];

  function decide(target: AdmissionStatus) {
    if (!application) return;
    if (needsReasonFor(target) && !justification.trim()) return;
    update.mutate(
      { id: application.id, status: target, decisionJustification: justification || undefined },
      { onSuccess: () => setJustification("") }
    );
  }

  function startEditing() {
    if (!application) return;
    setEditApplicantName(application.applicant_name);
    setEditDob(application.dob);
    setEditGuardianEmail(application.guardian_email);
    setEditGuardianName(application.guardian_name ?? "");
    setEditGuardianPhone(application.guardian_phone ?? "");
    setEditing(true);
  }

  function saveDetails() {
    if (!application || !editApplicantName.trim() || !editDob || !editGuardianEmail.trim()) return;
    updateDetails.mutate(
      {
        id: application.id,
        applicant_name: editApplicantName,
        dob: editDob,
        guardian_email: editGuardianEmail,
        guardian_name: editGuardianName,
        guardian_phone: editGuardianPhone,
      },
      { onSuccess: () => setEditing(false) }
    );
  }

  const assignedClassName = update.data?.assigned_class_id
    ? lookup.data?.classes.find((c) => c.id === update.data!.assigned_class_id)?.name ?? `Class #${update.data.assigned_class_id}`
    : null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        {detail.isLoading && <div className="h-40 animate-pulse rounded-lg bg-elevated/60" />}
        {detail.error && (
          <p className="text-sm text-urgent">{detail.error instanceof ApiError ? detail.error.message : "Failed to load application."}</p>
        )}
        {application && (
          <>
            <DialogHeader>
              <DialogTitle>{application.applicant_name}</DialogTitle>
              <DialogDescription>
                Application #{application.id} · {gradeLevelDisplay(application.grade_applied)} · {application.academic_year}
              </DialogDescription>
            </DialogHeader>

            <div className="flex flex-col gap-3">
              {editing ? (
                <div className="flex flex-col gap-2 rounded-xl border border-border bg-elevated/30 p-3">
                  <Field label="Applicant name">
                    <Input value={editApplicantName} onChange={(e) => setEditApplicantName(e.target.value)} />
                  </Field>
                  <Field label="Date of birth">
                    <Input type="date" value={editDob} onChange={(e) => setEditDob(e.target.value)} />
                  </Field>
                  <Field label="Guardian email">
                    <Input type="email" value={editGuardianEmail} onChange={(e) => setEditGuardianEmail(e.target.value)} />
                  </Field>
                  <Field label="Guardian name">
                    <Input value={editGuardianName} onChange={(e) => setEditGuardianName(e.target.value)} placeholder="Rajesh Sharma" />
                  </Field>
                  <Field label="Guardian phone">
                    <Input type="tel" value={editGuardianPhone} onChange={(e) => setEditGuardianPhone(e.target.value)} placeholder="9876543210" />
                  </Field>
                  {updateDetails.isError && (
                    <p className="text-xs text-urgent">
                      {updateDetails.error instanceof ApiError ? updateDetails.error.message : "Failed to save."}
                    </p>
                  )}
                  <div className="flex gap-1.5">
                    <Button
                      size="sm"
                      onClick={saveDetails}
                      disabled={updateDetails.isPending || !editApplicantName.trim() || !editDob || !editGuardianEmail.trim()}
                    >
                      {updateDetails.isPending ? "Saving…" : "Save"}
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>
                      Cancel
                    </Button>
                  </div>
                </div>
              ) : (
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div>
                    <span className="text-xs uppercase tracking-wide text-ink-muted">Date of birth</span>
                    <p className="font-medium text-ink">{application.dob}</p>
                  </div>
                  <div>
                    <span className="text-xs uppercase tracking-wide text-ink-muted">Guardian email</span>
                    <p className="font-medium text-ink">{application.guardian_email}</p>
                  </div>
                  <div>
                    <span className="text-xs uppercase tracking-wide text-ink-muted">Guardian name</span>
                    <p className="font-medium text-ink">{application.guardian_name ?? <span className="text-ink-faint">Not provided</span>}</p>
                  </div>
                  <div>
                    <span className="text-xs uppercase tracking-wide text-ink-muted">Guardian phone</span>
                    <p className="font-medium text-ink">{application.guardian_phone ?? <span className="text-ink-faint">Not provided</span>}</p>
                  </div>
                  <div>
                    <span className="text-xs uppercase tracking-wide text-ink-muted">Status</span>
                    <p><Badge variant={application.status === "accepted" ? "positive" : application.status === "rejected" ? "urgent" : "outline"}>{application.status}</Badge></p>
                  </div>
                  <div>
                    <span className="text-xs uppercase tracking-wide text-ink-muted">Submitted</span>
                    <p className="font-medium text-ink">{new Date(application.submitted_at).toLocaleString()}</p>
                  </div>
                  <div className="col-span-2">
                    {application.status === "accepted" ? (
                      <p className="text-xs text-ink-faint">
                        Details are locked — a real student/parent account already exists from these values.
                      </p>
                    ) : (
                      <Button size="sm" variant="outline" onClick={startEditing}>
                        <Pencil className="h-3.5 w-3.5" /> Edit details
                      </Button>
                    )}
                  </div>
                </div>
              )}

              {application.enrolled_student_id && (
                <p className="text-sm text-positive">Enrolled as student #{application.enrolled_student_id}.</p>
              )}
              {application.decision_justification && (
                <p className="text-sm text-ink-muted">Reason on file: {application.decision_justification}</p>
              )}

              <div className="flex flex-col gap-2">
                <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">Linked document(s)</span>
                <DocumentCoverage documents={application.documents} />
                {application.documents.length === 0 && (
                  <p className="text-xs text-ink-muted">No document linked to this application.</p>
                )}
                {application.documents.map((doc) => (
                  <LinkedDocumentPanel key={doc.id} doc={doc} />
                ))}
                <AttachDocumentPanel schoolId={schoolId} applicationId={application.id} />
              </div>

              {nextStates.length > 0 && (
                <div className="flex flex-col gap-2 border-t border-border pt-3">
                  {nextStates.includes("rejected") && (
                    <Field label="Reason" hint="Required to reject — optional otherwise">
                      <Textarea value={justification} onChange={(e) => setJustification(e.target.value)} />
                    </Field>
                  )}
                  {nextStates.includes("accepted") && (
                    <p className="text-xs text-ink-muted">
                      Accepting will automatically assign the least-filled real section at{" "}
                      {gradeLevelDisplay(application.grade_applied)}, create a real student account, and link (or create) a
                      real guardian account for {application.guardian_email}.
                    </p>
                  )}
                  {nextStates.includes("accepted") && missingRequiredTypes.length > 0 && (
                    <p className="text-xs text-urgent">
                      Cannot accept yet — missing {missingRequiredTypes.map((t) => DOCUMENT_TYPE_LABEL[t]).join(" and ")}. Attach{" "}
                      {missingRequiredTypes.length > 1 ? "them" : "it"} above first.
                    </p>
                  )}
                  {update.isError && (
                    <p className="text-sm text-urgent">{update.error instanceof ApiError ? update.error.message : "Decision failed."}</p>
                  )}
                  {update.isSuccess && update.data && (
                    <p className="text-sm text-positive">
                      Now <span className="font-mono">{update.data.status}</span>.
                      {update.data.status === "accepted" &&
                        ` Assigned to ${assignedClassName}, student #${update.data.enrolled_student_id}, guardian ${
                          update.data.parent_account_created ? "account newly created" : "linked to existing account"
                        }.`}
                    </p>
                  )}
                  <div className="flex flex-wrap gap-1.5">
                    {nextStates.map((target) => (
                      <Button
                        key={target}
                        variant={target === "rejected" ? "outline" : "default"}
                        onClick={() => decide(target)}
                        disabled={
                          update.isPending ||
                          (needsReasonFor(target) && !justification.trim()) ||
                          (target === "accepted" && missingRequiredTypes.length > 0)
                        }
                      >
                        {target === "under_review" ? "Move to review" : target === "accepted" ? "Accept" : "Reject"}
                      </Button>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ApplicationRow({ application, onOpenDetail }: { application: AdmissionApplication; onOpenDetail: () => void }) {
  const isTerminal = LEGAL_NEXT[application.status].length === 0;
  return (
    <button type="button" onClick={onOpenDetail} className="w-full text-left">
      <EntityCard
        icon={ClipboardList}
        tone={STATUS_TONE[application.status]}
        title={application.applicant_name}
        badges={
          <>
            <Badge variant={application.status === "accepted" ? "positive" : application.status === "rejected" ? "urgent" : "outline"}>
              {application.status}
            </Badge>
            <Badge variant="outline">{gradeLevelDisplay(application.grade_applied)}</Badge>
          </>
        }
        message={`DOB ${application.dob} · ${application.guardian_email}`}
        meta={`Application #${application.id} · submitted ${new Date(application.submitted_at).toLocaleDateString()}${
          application.enrolled_student_id ? ` · enrolled as student #${application.enrolled_student_id}` : ""
        }`}
        actions={isTerminal ? <Badge variant="neutral">Terminal</Badge> : <Badge variant="warning">Needs decision</Badge>}
      />
    </button>
  );
}

function ReviewQueueTab({ schoolId }: { schoolId: number }) {
  const [statusFilter, setStatusFilter] = useState<(typeof STATUS_TABS)[number]>("all");
  const [openId, setOpenId] = useState<number | null>(null);
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
          <ApplicationRow key={a.id} application={a} onOpenDetail={() => setOpenId(a.id)} />
        ))}
      </div>
      {list.data && list.data.total > items.length && (
        <p className="text-xs text-ink-faint">Showing {items.length} of {list.data.total}.</p>
      )}

      {openId !== null && (
        <ApplicationDetailDialog
          applicationId={openId}
          schoolId={schoolId}
          open={openId !== null}
          onOpenChange={(next) => { if (!next) setOpenId(null); }}
        />
      )}
    </div>
  );
}

export default function AdmissionsPage() {
  const { role } = useAuthStore();
  const schoolId = useCurrentUser().data?.school_id;
  // POST /admin/admissions/applications is admin-only on the real backend
  // (principal is not in that route's require_role list) - the Submit tab is
  // hidden for principal rather than shown-then-403ing.
  const canSubmit = role === "admin";

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="Admissions" description="Application intake and the submitted → under_review → accepted/rejected review queue." />
      {schoolId == null ? (
        <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />
      ) : (
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
            <ReviewQueueTab schoolId={schoolId} />
          </TabsContent>
          {canSubmit && (
            <TabsContent value="submit">
              <SubmitTab schoolId={schoolId} />
            </TabsContent>
          )}
        </Tabs>
      )}
    </div>
  );
}
