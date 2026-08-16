import { useState, type DragEvent } from "react";
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, FileScan, FileWarning, GripVertical, Hourglass, Link2, Paperclip, RotateCcw, ScanText, Search, UserPlus, type LucideIcon } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger } from "@/components/ui/dialog";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import EntityCard from "@/components/shared/EntityCard";
import FileDropzone from "@/components/shared/FileDropzone";
import { useUploadDocument, useDocument, useCorrectEntity, useAddManualEntity, useReextractDocument, useDocumentsList } from "@/api/hooks/useOcr";
import { useSubmitApplication, useAttachDocument } from "@/api/hooks/useAdmissions";
import { GradeLevelSelect } from "@/components/admissions/AdmissionsPage";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/utils";
import type { DocumentRouting, DocumentSummary, DocumentType, ExtractedEntity } from "@/api/types";

const DOCUMENT_TYPES: { value: DocumentType; label: string }[] = [
  { value: "admission_form", label: "Admission form" },
  { value: "marksheet", label: "Marksheet" },
  { value: "id_proof", label: "ID proof" },
  { value: "other", label: "Other" },
];

const STATUS_TONE: Record<string, "urgent" | "positive" | "warning" | "neutral"> = {
  queued: "neutral",
  processing: "warning",
  done: "positive",
  failed: "urgent",
};

/** A document's TYPE, not its processing status, is the more useful thing to
 * color-code once documents are organized into the linked/unlinked board below -
 * it's what tells you at a glance whether you're looking at the form itself, a
 * marksheet, or an ID proof, across every column. */
const DOC_TYPE_TONE: Record<DocumentType, "urgent" | "positive" | "accent" | "warning" | "neutral"> = {
  admission_form: "accent",
  marksheet: "positive",
  id_proof: "warning",
  other: "neutral",
};

const BOARD_PAGE_SIZE = 30;

function UploadCard({ schoolId, onUploaded }: { schoolId: number; onUploaded: (documentId: number) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState<DocumentType>("admission_form");
  const upload = useUploadDocument(schoolId);

  function submit() {
    if (!file) return;
    upload.mutate({ file, documentType }, { onSuccess: (result) => onUploaded(result.id) });
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upload a document</CardTitle>
        <CardDescription>
          OCR + field extraction runs synchronously — the result below is the real final status, not a placeholder.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Field label="Document type">
          <Select value={documentType} onValueChange={(v) => setDocumentType(v as DocumentType)}>
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {DOCUMENT_TYPES.map((t) => (
                <SelectItem key={t.value} value={t.value}>
                  {t.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </Field>
        <FileDropzone file={file} onFileSelected={setFile} />
        <Button onClick={submit} disabled={!file || upload.isPending} className="self-start">
          <FileScan className="h-4 w-4" />
          {upload.isPending ? "Processing…" : "Upload & extract"}
        </Button>
        {upload.isError && (
          <p className="text-sm text-urgent">{upload.error instanceof ApiError ? upload.error.message : "Upload failed."}</p>
        )}
        {upload.isSuccess && (
          <p className="text-sm text-positive">
            Document #{upload.data.id} → status <span className="font-mono">{upload.data.status}</span>.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function EntityRow({ schoolId, documentId, entity }: { schoolId: number; documentId: number; entity: ExtractedEntity }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(entity.corrected_value ?? entity.field_value);
  const correct = useCorrectEntity(schoolId);

  const displayValue = entity.corrected_value ?? entity.field_value;

  function save() {
    if (!value.trim()) return;
    correct.mutate({ documentId, entityId: entity.id, correctedValue: value }, { onSuccess: () => setEditing(false) });
  }

  return (
    <div
      className={cn(
        "rounded-xl border px-3.5 py-2.5",
        entity.is_low_confidence ? "border-warning/40 bg-warning/5" : "border-border bg-elevated/40"
      )}
    >
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs uppercase tracking-wide text-ink-muted">{entity.field_name}</span>
          {entity.is_low_confidence && (
            <Badge variant="warning">
              <AlertTriangle className="h-3 w-3" /> Low confidence
            </Badge>
          )}
          {entity.corrected_value !== null && <Badge variant="positive">Corrected</Badge>}
          <span className="font-mono text-[0.6875rem] text-ink-faint">{(entity.confidence_score * 100).toFixed(0)}%</span>
        </div>
        {editing ? (
          <div className="flex flex-wrap items-center gap-2">
            <Input value={value} onChange={(e) => setValue(e.target.value)} className="max-w-xs" />
            <Button size="sm" onClick={save} disabled={!value.trim() || correct.isPending}>
              {correct.isPending ? "Saving…" : "Save"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setValue(displayValue); }}>
              Cancel
            </Button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-ink">{displayValue}</span>
            <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
              Correct
            </Button>
          </div>
        )}
        {correct.isError && (
          <p className="text-xs text-urgent">{correct.error instanceof ApiError ? correct.error.message : "Correction failed."}</p>
        )}
      </div>
    </div>
  );
}

/** A field OCR never found at all for this document - genuinely different from a
 * low-confidence EntityRow above (which has SOME value, just an uncertain one).
 * Found live: a real marksheet's "Total Marks:" line came back from Tesseract as
 * "otal Mark:", so the field's regex never matched and no entity was ever
 * created - there was nowhere for an admin to even see that gap, let alone fill
 * it in, until now. */
function MissingFieldRow({ schoolId, documentId, fieldName }: { schoolId: number; documentId: number; fieldName: string }) {
  const [value, setValue] = useState("");
  const addManual = useAddManualEntity(schoolId);

  function save() {
    if (!value.trim()) return;
    addManual.mutate({ documentId, fieldName, value });
  }

  return (
    <div className="rounded-xl border border-dashed border-urgent/40 bg-urgent/5 px-3.5 py-2.5">
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-xs uppercase tracking-wide text-ink-muted">{fieldName}</span>
          <Badge variant="urgent">Not found</Badge>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Enter manually" className="max-w-xs" />
          <Button size="sm" onClick={save} disabled={!value.trim() || addManual.isPending}>
            {addManual.isPending ? "Saving…" : "Save"}
          </Button>
        </div>
        {addManual.isError && (
          <p className="text-xs text-urgent">{addManual.error instanceof ApiError ? addManual.error.message : "Failed to save."}</p>
        )}
      </div>
    </div>
  );
}

/** Pre-fills the real POST /admin/admissions/applications submission from
 * routing's suggested_payload - a human still reviews/edits every field and
 * explicitly clicks Submit, matching the product's own "typically entered by
 * office staff, possibly pre-filled via OCR" description (see AdmissionsPage's
 * own "New admission application" form, which this mirrors). academic_year is
 * the one field never in suggested_payload - genuinely not on the physical
 * form, so it starts at DEFAULT_ACADEMIC_YEAR but stays editable. */
function CreateApplicationDialog({ routing }: { routing: DocumentRouting }) {
  const payload = routing.suggested_payload;
  const [open, setOpen] = useState(false);
  const [applicantName, setApplicantName] = useState(payload?.applicant_name ?? "");
  const [dob, setDob] = useState(payload?.dob ?? "");
  const [guardianEmail, setGuardianEmail] = useState(payload?.guardian_email ?? "");
  const [guardianName, setGuardianName] = useState(payload?.guardian_name ?? "");
  const [guardianPhone, setGuardianPhone] = useState(payload?.guardian_phone ?? "");
  const [gradeApplied, setGradeApplied] = useState(payload?.grade_applied ?? "");
  const [academicYear, setAcademicYear] = useState(DEFAULT_ACADEMIC_YEAR);
  const submit = useSubmitApplication();

  if (!payload) return null;

  function handleSubmit() {
    if (!applicantName.trim() || !dob || !guardianEmail.trim() || !gradeApplied || !academicYear.trim()) return;
    submit.mutate({
      school_id: payload!.school_id,
      academic_year: academicYear,
      applicant_name: applicantName,
      dob,
      guardian_email: guardianEmail,
      guardian_name: guardianName.trim() || undefined,
      guardian_phone: guardianPhone.trim() || undefined,
      grade_applied: gradeApplied,
      ocr_document_ids: payload!.ocr_document_ids,
    });
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <UserPlus className="h-3.5 w-3.5" /> Create application from this document
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Create admission application</DialogTitle>
          <DialogDescription>Pre-filled from this document's extracted fields — review before submitting.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Applicant name">
            <Input value={applicantName} onChange={(e) => setApplicantName(e.target.value)} />
          </Field>
          <Field label="Date of birth">
            <Input type="date" value={dob} onChange={(e) => setDob(e.target.value)} />
          </Field>
          <Field label="Guardian email">
            <Input type="email" value={guardianEmail} onChange={(e) => setGuardianEmail(e.target.value)} />
          </Field>
          <Field label="Guardian name" hint="Becomes the real name on the guardian's account once accepted">
            <Input value={guardianName} onChange={(e) => setGuardianName(e.target.value)} />
          </Field>
          <Field label="Guardian phone">
            <Input type="tel" value={guardianPhone} onChange={(e) => setGuardianPhone(e.target.value)} />
          </Field>
          <Field label="Grade applied" hint="Grade level only — the specific section is assigned automatically on acceptance">
            <GradeLevelSelect schoolId={payload.school_id} value={gradeApplied} onChange={setGradeApplied} />
          </Field>
          <Field label="Academic year" hint="Not on the physical form — confirm this is correct">
            <Input value={academicYear} onChange={(e) => setAcademicYear(e.target.value)} />
          </Field>
          {submit.isError && (
            <p className="text-sm text-urgent">{submit.error instanceof ApiError ? submit.error.message : "Submission failed."}</p>
          )}
          {submit.isSuccess && (
            <p className="text-sm text-positive">
              Application #{submit.data.id} submitted — status <span className="font-mono">{submit.data.status}</span>.
            </p>
          )}
          <Button
            onClick={handleSubmit}
            disabled={!applicantName.trim() || !dob || !guardianEmail.trim() || !gradeApplied || !academicYear.trim() || submit.isPending}
            className="self-start"
          >
            {submit.isPending ? "Submitting…" : "Submit application"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ReviewPanel({ schoolId, documentId }: { schoolId: number; documentId: number }) {
  const doc = useDocument(schoolId, documentId);
  const reextract = useReextractDocument(schoolId);
  const [reextractType, setReextractType] = useState<DocumentType | "">("");

  if (doc.isLoading) return <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />;
  if (doc.error) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-urgent">
          {doc.error instanceof ApiError ? doc.error.message : "Failed to load document."}
        </CardContent>
      </Card>
    );
  }
  const d = doc.data;
  if (!d) return null;

  const lowConfidenceCount = d.entities.filter((e) => e.is_low_confidence).length;
  const missingFields = d.expected_fields.filter((f) => !(f in d.extracted_fields));

  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>
            Document #{d.id} · {d.document_type}
          </CardTitle>
          <CardDescription>
            Uploaded {new Date(d.uploaded_at).toLocaleString()}
            {d.processed_at && ` · processed ${new Date(d.processed_at).toLocaleString()}`}
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant={STATUS_TONE[d.status]}>{d.status}</Badge>
          {d.ocr_confidence !== null && <Badge variant="outline">OCR {(d.ocr_confidence * 100).toFixed(0)}%</Badge>}
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {d.error && <p className="text-sm text-urgent">{d.error}</p>}

        {d.expected_fields.length === 0 && !d.error && (
          <p className="text-sm text-ink-muted">No entities extracted for this document type.</p>
        )}

        {d.expected_fields.length > 0 && (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">Extracted fields</span>
              <div className="flex gap-2">
                {lowConfidenceCount > 0 && (
                  <span className="text-xs text-warning">{lowConfidenceCount} field(s) need review</span>
                )}
                {missingFields.length > 0 && (
                  <span className="text-xs text-urgent">{missingFields.length} field(s) not found</span>
                )}
              </div>
            </div>
            {d.entities.map((e) => (
              <EntityRow key={e.id} schoolId={schoolId} documentId={d.id} entity={e} />
            ))}
            {missingFields.map((fieldName) => (
              <MissingFieldRow key={fieldName} schoolId={schoolId} documentId={d.id} fieldName={fieldName} />
            ))}
          </div>
        )}

        {d.routing && (
          <div
            className={cn(
              "flex flex-wrap items-center justify-between gap-2 rounded-xl border px-3.5 py-2.5 text-xs",
              d.routing.routed ? "border-positive/40 bg-positive/5 text-ink" : "border-border bg-elevated/40 text-ink-muted"
            )}
          >
            <span>
              <span className="font-medium text-ink">Routing:</span>{" "}
              {d.routing.routed ? `Ready — target ${d.routing.target_table}` : "Not routed"} — {d.routing.reason}
            </span>
            {d.routing.routed && <CreateApplicationDialog routing={d.routing} />}
          </div>
        )}

        {d.raw_text && (
          <details className="rounded-xl border border-border bg-elevated/40 px-3.5 py-2.5 text-xs">
            <summary className="cursor-pointer font-medium text-ink-muted">Raw OCR text</summary>
            <pre className="mt-2 whitespace-pre-wrap font-mono text-[0.6875rem] text-ink-muted">{d.raw_text}</pre>
          </details>
        )}

        <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
          <Field label="Re-extract as (optional)" className="w-48" hint="Omit to retry with the current document_type">
            <Select value={reextractType} onValueChange={(v) => setReextractType(v as DocumentType)}>
              <SelectTrigger>
                <SelectValue placeholder={d.document_type} />
              </SelectTrigger>
              <SelectContent>
                {DOCUMENT_TYPES.map((t) => (
                  <SelectItem key={t.value} value={t.value}>
                    {t.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Button
            variant="outline"
            onClick={() =>
              reextract.mutate({ documentId: d.id, documentType: reextractType || undefined }, { onSuccess: () => setReextractType("") })
            }
            disabled={reextract.isPending}
          >
            <RotateCcw className="h-4 w-4" />
            {reextract.isPending ? "Re-extracting…" : "Re-extract"}
          </Button>
          {reextract.isError && (
            <p className="text-sm text-urgent">{reextract.error instanceof ApiError ? reextract.error.message : "Re-extract failed."}</p>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

interface DocGroup {
  applicationId: number;
  /** The admission_form document in this group, IF it's on the current page -
   * pagination means it isn't guaranteed to be (e.g. it was uploaded long before
   * a later-attached marksheet). Falls back to a generic "Application #X" header
   * when absent, rather than skipping the group. */
  parent: DocumentSummary | null;
  children: DocumentSummary[];
}

/** Groups the CURRENT PAGE's documents by application_id - a document is either
 * the admission_form "root" of a group, a document already attached to that same
 * application (nested beneath it), or unlinked entirely (ungrouped). Grouping is
 * necessarily page-scoped, not global: fetching every linked document's own
 * detail just to build a cross-page tree isn't worth the round-trips for what's
 * fundamentally a review aid, not a source of truth (GET .../applications/{id}
 * remains the real, complete picture - see AdmissionsPage.tsx). */
/** Splits ungrouped (application_id === null) documents into the two columns'
 * worth of "still needs attention" work: an admission_form waiting to become an
 * application (a real drop target, once one exists) vs. everything else waiting
 * to be linked TO one (a real drag source). */
function groupDocuments(
  items: DocumentSummary[]
): {
  fullyLinkedGroups: DocGroup[];
  awaitingDocumentGroups: DocGroup[];
  unlinkedAdmissionForms: DocumentSummary[];
  unlinkedOther: DocumentSummary[];
} {
  const byApplication = new Map<number, DocumentSummary[]>();
  const unlinkedAdmissionForms: DocumentSummary[] = [];
  const unlinkedOther: DocumentSummary[] = [];
  for (const doc of items) {
    if (doc.application_id == null) {
      (doc.document_type === "admission_form" ? unlinkedAdmissionForms : unlinkedOther).push(doc);
      continue;
    }
    const existing = byApplication.get(doc.application_id);
    if (existing) existing.push(doc);
    else byApplication.set(doc.application_id, [doc]);
  }
  const groups: DocGroup[] = [...byApplication.entries()].map(([applicationId, docs]) => {
    const parent = docs.find((d) => d.document_type === "admission_form") ?? null;
    return { applicationId, parent, children: docs.filter((d) => d !== parent) };
  });
  // An application that exists but has nothing else attached yet (marksheet/
  // id_proof are now a real hard requirement to accept - see admissions.py's
  // REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE) is meaningfully different from one
  // that's genuinely linked - its own column, not just a bare group in "Linked".
  const fullyLinkedGroups = groups.filter((g) => g.children.length > 0);
  const awaitingDocumentGroups = groups.filter((g) => g.children.length === 0);
  return { fullyLinkedGroups, awaitingDocumentGroups, unlinkedAdmissionForms, unlinkedOther };
}

function DocRow({
  doc,
  selectedId,
  onSelect,
  isDropTarget,
  isDragOver,
  draggable,
  onDragStart,
  onDragOver,
  onDragEnter,
  onDragLeave,
  onDrop,
  linkedBadge,
}: {
  doc: DocumentSummary;
  selectedId: number | null;
  onSelect: (id: number) => void;
  isDropTarget?: boolean;
  isDragOver?: boolean;
  draggable?: boolean;
  onDragStart?: (e: DragEvent) => void;
  onDragOver?: (e: DragEvent) => void;
  onDragEnter?: () => void;
  onDragLeave?: () => void;
  onDrop?: (e: DragEvent) => void;
  linkedBadge?: string;
}) {
  const isSelected = doc.id === selectedId;
  return (
    <div
      className={cn(
        "rounded-2xl transition-shadow",
        isDragOver && "ring-2 ring-accent",
        isSelected && !isDragOver && "ring-2 ring-ink/25"
      )}
      draggable={draggable}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragEnter={onDragEnter}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
    >
      <button onClick={() => onSelect(doc.id)} className="flex w-full items-center gap-1 text-left">
        {draggable && <GripVertical className="h-3.5 w-3.5 shrink-0 cursor-grab text-ink-faint" />}
        <div className="min-w-0 flex-1">
          <EntityCard
            icon={ScanText}
            tone={DOC_TYPE_TONE[doc.document_type]}
            title={`#${doc.id} · ${doc.document_type}`}
            badges={
              <>
                <Badge variant="outline">{doc.status}</Badge>
                {isSelected && <Badge variant="accent">Currently viewing</Badge>}
                {linkedBadge && <Badge variant="positive">{linkedBadge}</Badge>}
                {isDropTarget && doc.application_id == null && <Badge variant="neutral">Not yet an application</Badge>}
              </>
            }
            message={doc.application_applicant_name ?? undefined}
            meta={`Uploaded ${new Date(doc.uploaded_at).toLocaleString()}`}
          />
        </div>
      </button>
    </div>
  );
}

function ColumnHeader({
  icon: Icon,
  tone,
  title,
  count,
  description,
}: {
  icon: LucideIcon;
  tone: "positive" | "warning" | "accent" | "urgent";
  title: string;
  count: number;
  description: string;
}) {
  const TONE_STYLE: Record<typeof tone, string> = {
    positive: "bg-positive/10 text-positive",
    warning: "bg-warning/10 text-warning",
    accent: "bg-accent/10 text-accent",
    urgent: "bg-urgent/10 text-urgent",
  };
  return (
    <div className="flex items-start gap-2.5 border-b border-border px-1 pb-3">
      <div className={cn("flex h-8 w-8 shrink-0 items-center justify-center rounded-lg", TONE_STYLE[tone])}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="font-display text-sm font-semibold text-ink">{title}</span>
          <Badge variant="outline">{count}</Badge>
        </div>
        <p className="text-xs text-ink-muted">{description}</p>
      </div>
    </div>
  );
}

function EmptyColumn({ text }: { text: string }) {
  return (
    <div className="flex flex-col items-center gap-1 rounded-xl border border-dashed border-border py-6 text-center">
      <CheckCircle2 className="h-4 w-4 text-ink-faint" />
      <p className="max-w-[16rem] text-xs text-ink-muted">{text}</p>
    </div>
  );
}

function DocumentsBoard({
  schoolId,
  selectedId,
  onSelect,
}: {
  schoolId: number;
  selectedId: number | null;
  onSelect: (id: number) => void;
}) {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [page, setPage] = useState(1);
  const [lookupId, setLookupId] = useState("");
  const [dragOverKey, setDragOverKey] = useState<string | null>(null);
  const [blockedMessage, setBlockedMessage] = useState<string | null>(null);
  const attach = useAttachDocument();

  const list = useDocumentsList(schoolId, {
    status: statusFilter || undefined,
    page,
    pageSize: BOARD_PAGE_SIZE,
  });

  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1;

  function handleLookup() {
    const id = Number(lookupId);
    if (!id) return;
    onSelect(id);
  }

  function handleDrop(e: DragEvent, targetApplicationId: number | null) {
    e.preventDefault();
    setDragOverKey(null);
    const documentId = Number(e.dataTransfer.getData("text/plain"));
    if (!documentId) return;
    if (targetApplicationId == null) {
      setBlockedMessage("Create an application from this admission form first, then drag documents onto it.");
      return;
    }
    setBlockedMessage(null);
    attach.mutate({ applicationId: targetApplicationId, documentId });
  }

  function dropTargetProps(key: string, targetApplicationId: number | null) {
    return {
      onDragOver: (e: DragEvent) => e.preventDefault(),
      onDragEnter: () => setDragOverKey(key),
      onDragLeave: () => setDragOverKey((current) => (current === key ? null : current)),
      onDrop: (e: DragEvent) => handleDrop(e, targetApplicationId),
    };
  }

  function dragSourceProps(doc: DocumentSummary) {
    // admission_form can never be dragged - it's always the root of its own
    // group, never something attached to another document (this session's own
    // explicit decision). Already-linked documents also aren't draggable again -
    // once attached, a document stays where it is rather than becoming a general
    // reordering target.
    if (doc.document_type === "admission_form" || doc.application_id != null) return {};
    return {
      draggable: true,
      onDragStart: (e: DragEvent) => e.dataTransfer.setData("text/plain", String(doc.id)),
    };
  }

  const { fullyLinkedGroups, awaitingDocumentGroups, unlinkedAdmissionForms, unlinkedOther } = list.data
    ? groupDocuments(list.data.items)
    : { fullyLinkedGroups: [], awaitingDocumentGroups: [], unlinkedAdmissionForms: [], unlinkedOther: [] };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Document board</CardTitle>
        <CardDescription>
          Drag a marksheet or ID proof onto an admission form to attach it to that applicant's file — real, paginated data from the backend.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-end gap-2">
          <Field label="Jump to document ID" className="w-56">
            <Input type="number" value={lookupId} onChange={(e) => setLookupId(e.target.value)} placeholder="e.g. 22" />
          </Field>
          <Button variant="outline" size="default" onClick={handleLookup} disabled={!lookupId}>
            <Search className="h-4 w-4" />
          </Button>
          <Field label="Status" className="w-36">
            <Select value={statusFilter} onValueChange={(v) => { setStatusFilter(v); setPage(1); }}>
              <SelectTrigger>
                <SelectValue placeholder="All" />
              </SelectTrigger>
              <SelectContent>
                {["queued", "processing", "done", "failed"].map((s) => (
                  <SelectItem key={s} value={s}>
                    {s}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
        </div>

        {list.isLoading && <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />}
        {list.error && (
          <p className="text-sm text-urgent">{list.error instanceof ApiError ? list.error.message : "Failed to load documents."}</p>
        )}
        {blockedMessage && (
          <div className="flex items-center justify-between gap-2 rounded-xl border border-urgent/40 bg-urgent/5 px-3 py-2 text-xs text-urgent">
            <span>{blockedMessage}</span>
            <button onClick={() => setBlockedMessage(null)} className="font-medium underline">
              Dismiss
            </button>
          </div>
        )}
        {attach.isError && (
          <p className="text-xs text-urgent">{attach.error instanceof ApiError ? attach.error.message : "Failed to attach document."}</p>
        )}

        {list.data && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            {/* Column 1: fully linked - an application with real marksheet/id_proof (etc.) attached */}
            <div className="flex flex-col gap-3">
              <ColumnHeader
                icon={Link2}
                tone="positive"
                title="Linked"
                count={fullyLinkedGroups.length}
                description="Application + supporting documents"
              />
              <div className="flex flex-col gap-3">
                {fullyLinkedGroups.length === 0 && (
                  <EmptyColumn text="Nothing fully linked yet — drag a marksheet or ID proof onto an admission form." />
                )}
                {fullyLinkedGroups.map((group) => {
                  const key = `app-${group.applicationId}`;
                  const drop = dropTargetProps(key, group.applicationId);
                  return (
                    <div key={key} className="flex flex-col gap-2.5 rounded-2xl border border-border bg-elevated/30 p-2.5">
                      {group.parent ? (
                        <DocRow
                          doc={group.parent}
                          selectedId={selectedId}
                          onSelect={onSelect}
                          isDropTarget
                          isDragOver={dragOverKey === key}
                          linkedBadge={`Created Application #${group.applicationId}`}
                          {...drop}
                        />
                      ) : (
                        <div
                          {...drop}
                          className={cn(
                            "rounded-xl border border-dashed border-border px-3 py-2 text-xs text-ink-muted",
                            dragOverKey === key && "ring-2 ring-accent"
                          )}
                        >
                          Application #{group.applicationId}
                        </div>
                      )}
                      <div className="ml-4 flex flex-col gap-2.5 border-l-2 border-dashed border-border/70 pl-4">
                        {group.children.map((child) => (
                          <DocRow
                            key={child.id}
                            doc={child}
                            selectedId={selectedId}
                            onSelect={onSelect}
                            linkedBadge={`→ Application #${group.applicationId}`}
                          />
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Column 2: application exists, but marksheet/id_proof aren't attached yet -
                this application literally CANNOT be accepted until it moves to Column 1
                (REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE). */}
            <div className="flex flex-col gap-3">
              <ColumnHeader
                icon={FileWarning}
                tone="urgent"
                title="Awaiting documents"
                count={awaitingDocumentGroups.length}
                description="Marksheet + ID proof required to accept"
              />
              <div className="flex flex-col gap-3">
                {awaitingDocumentGroups.length === 0 && <EmptyColumn text="No application is missing its required documents." />}
                {awaitingDocumentGroups.map((group) => {
                  const key = `app-${group.applicationId}`;
                  const drop = dropTargetProps(key, group.applicationId);
                  return group.parent ? (
                    <DocRow
                      key={key}
                      doc={group.parent}
                      selectedId={selectedId}
                      onSelect={onSelect}
                      isDropTarget
                      isDragOver={dragOverKey === key}
                      linkedBadge={`Created Application #${group.applicationId}`}
                      {...drop}
                    />
                  ) : null;
                })}
              </div>
            </div>

            {/* Column 3: unlinked marksheet/id_proof/other - these must be linked to someone */}
            <div className="flex flex-col gap-3">
              <ColumnHeader
                icon={Paperclip}
                tone="warning"
                title="Needs linking"
                count={unlinkedOther.length}
                description="Drag onto an admission form"
              />
              <div className="flex flex-col gap-2.5">
                {unlinkedOther.length === 0 && <EmptyColumn text="Nothing waiting to be linked." />}
                {unlinkedOther.map((doc) => (
                  <DocRow key={doc.id} doc={doc} selectedId={selectedId} onSelect={onSelect} {...dragSourceProps(doc)} />
                ))}
              </div>
            </div>

            {/* Column 4: unlinked admission_form documents - real drop targets once an application exists */}
            <div className="flex flex-col gap-3">
              <ColumnHeader
                icon={Hourglass}
                tone="accent"
                title="Pending applications"
                count={unlinkedAdmissionForms.length}
                description="Not yet turned into an application"
              />
              <div className="flex flex-col gap-2.5">
                {unlinkedAdmissionForms.length === 0 && <EmptyColumn text="No admission forms waiting on an application." />}
                {unlinkedAdmissionForms.map((doc) => {
                  const key = `doc-${doc.id}`;
                  return (
                    <DocRow
                      key={doc.id}
                      doc={doc}
                      selectedId={selectedId}
                      onSelect={onSelect}
                      isDropTarget
                      isDragOver={dragOverKey === key}
                      {...dropTargetProps(key, null)}
                    />
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {list.data && list.data.total > list.data.page_size && (
          <div className="flex items-center justify-between border-t border-border pt-3">
            <span className="text-xs text-ink-faint">
              Page {list.data.page} of {totalPages} · {list.data.total} total
            </span>
            <div className="flex gap-1.5">
              <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={page <= 1}>
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="sm" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={page >= totalPages}>
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function OcrPage() {
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const schoolId = useCurrentUser().data?.school_id;

  if (schoolId == null) {
    return <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />;
  }

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Document OCR"
        description="Upload scanned documents for Tesseract-backed OCR + field extraction, then review or correct low-confidence fields."
      />

      <div className="grid items-start gap-3 lg:grid-cols-[22rem_1fr]">
        <UploadCard schoolId={schoolId} onUploaded={setSelectedId} />

        <div>
          {selectedId === null ? (
            <Card>
              <CardContent className="flex flex-col items-center gap-1 py-10 text-center">
                <CheckCircle2 className="h-6 w-6 text-ink-muted" />
                <p className="font-display text-sm font-medium text-ink">No document selected</p>
                <p className="max-w-xs text-xs text-ink-muted">Upload a document or pick one from the board below to review its extracted fields here.</p>
              </CardContent>
            </Card>
          ) : (
            <ReviewPanel schoolId={schoolId} documentId={selectedId} />
          )}
        </div>
      </div>

      <DocumentsBoard schoolId={schoolId} selectedId={selectedId} onSelect={setSelectedId} />
    </div>
  );
}
