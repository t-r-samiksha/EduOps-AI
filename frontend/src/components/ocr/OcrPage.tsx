import { useState } from "react";
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, FileScan, RotateCcw, ScanText, Search } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import EntityCard from "@/components/shared/EntityCard";
import FileDropzone from "@/components/shared/FileDropzone";
import { useUploadDocument, useDocument, useCorrectEntity, useReextractDocument, useDocumentsList } from "@/api/hooks/useOcr";
import { ApiError } from "@/api/client";
import { cn } from "@/lib/utils";
import type { DocumentType, ExtractedEntity } from "@/api/types";

const PAGE_SIZE = 8;

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

function UploadCard({ onUploaded }: { onUploaded: (documentId: number) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [documentType, setDocumentType] = useState<DocumentType>("admission_form");
  const upload = useUploadDocument();

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

function EntityRow({ documentId, entity }: { documentId: number; entity: ExtractedEntity }) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(entity.corrected_value ?? entity.field_value);
  const correct = useCorrectEntity();

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

function ReviewPanel({ documentId }: { documentId: number }) {
  const doc = useDocument(documentId);
  const reextract = useReextractDocument();
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

        {d.entities.length === 0 && !d.error && (
          <p className="text-sm text-ink-muted">No entities extracted for this document type.</p>
        )}

        {d.entities.length > 0 && (
          <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium uppercase tracking-wide text-ink-muted">Extracted fields</span>
              {lowConfidenceCount > 0 && (
                <span className="text-xs text-warning">{lowConfidenceCount} field(s) need review</span>
              )}
            </div>
            {d.entities.map((e) => (
              <EntityRow key={e.id} documentId={d.id} entity={e} />
            ))}
          </div>
        )}

        {d.routing && (
          <div className="rounded-xl border border-border bg-elevated/40 px-3.5 py-2.5 text-xs text-ink-muted">
            <span className="font-medium text-ink">Routing:</span> {d.routing.routed ? `Routed to ${d.routing.target_table}` : "Not routed"} — {d.routing.reason}
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

function DocumentsListCard({ selectedId, onSelect }: { selectedId: number | null; onSelect: (id: number) => void }) {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [typeFilter, setTypeFilter] = useState<DocumentType | "">("");
  const [page, setPage] = useState(1);
  const [lookupId, setLookupId] = useState("");

  const list = useDocumentsList({
    status: statusFilter || undefined,
    documentType: typeFilter || undefined,
    page,
    pageSize: PAGE_SIZE,
  });

  const totalPages = list.data ? Math.max(1, Math.ceil(list.data.total / list.data.page_size)) : 1;

  function handleLookup() {
    const id = Number(lookupId);
    if (!id) return;
    onSelect(id);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Documents</CardTitle>
        <CardDescription>Real, paginated list from the backend — survives a page refresh.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="flex items-end gap-2">
          <Field label="Jump to document ID" className="flex-1">
            <Input type="number" value={lookupId} onChange={(e) => setLookupId(e.target.value)} placeholder="e.g. 22" />
          </Field>
          <Button variant="outline" size="default" onClick={handleLookup} disabled={!lookupId}>
            <Search className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex flex-wrap gap-2">
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
          <Field label="Type" className="w-40">
            <Select value={typeFilter} onValueChange={(v) => { setTypeFilter(v as DocumentType); setPage(1); }}>
              <SelectTrigger>
                <SelectValue placeholder="All" />
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
        </div>

        {list.isLoading && <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />}
        {list.error && (
          <p className="text-sm text-urgent">{list.error instanceof ApiError ? list.error.message : "Failed to load documents."}</p>
        )}
        {list.data && list.data.items.length === 0 && (
          <p className="text-xs text-ink-muted">No documents match this filter.</p>
        )}

        <div className="flex flex-col gap-2">
          {list.data?.items.map((doc) => (
            <button key={doc.id} onClick={() => onSelect(doc.id)} className="text-left">
              <EntityCard
                icon={ScanText}
                tone={doc.id === selectedId ? "accent" : STATUS_TONE[doc.status]}
                title={`Document #${doc.id} · ${doc.document_type}`}
                badges={<Badge variant="outline">{doc.status}</Badge>}
                message={doc.id === selectedId ? "Currently viewing" : undefined}
                meta={`Uploaded ${new Date(doc.uploaded_at).toLocaleString()}`}
              />
            </button>
          ))}
        </div>

        {list.data && list.data.total > list.data.page_size && (
          <div className="flex items-center justify-between pt-1">
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

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Document OCR"
        description="Upload scanned documents for Tesseract-backed OCR + field extraction, then review or correct low-confidence fields."
      />

      <div className="grid items-start gap-3 lg:grid-cols-[22rem_1fr]">
        <div className="flex flex-col gap-3">
          <UploadCard onUploaded={setSelectedId} />
          <DocumentsListCard selectedId={selectedId} onSelect={setSelectedId} />
        </div>

        <div>
          {selectedId === null ? (
            <Card>
              <CardContent className="flex flex-col items-center gap-1 py-10 text-center">
                <CheckCircle2 className="h-6 w-6 text-ink-muted" />
                <p className="font-display text-sm font-medium text-ink">No document selected</p>
                <p className="max-w-xs text-xs text-ink-muted">Upload a document or pick one from the list to review its extracted fields here.</p>
              </CardContent>
            </Card>
          ) : (
            <ReviewPanel documentId={selectedId} />
          )}
        </div>
      </div>
    </div>
  );
}
