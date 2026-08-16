import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPostForm, apiPut } from "@/api/client";
import type { DocumentCreateResult, DocumentDetail, DocumentsListResponse, DocumentType, ExtractedEntity } from "@/api/types";

// Processing is synchronous (see docs/api-contract.md's "Document OCR" section),
// so there is no queued/processing gap to poll across - a document's POST
// response already carries its final status.

// school_id is REQUIRED on every one of these calls now - a reliability-audit
// fix (documents had zero tenant scoping; an admin could see/correct/reextract
// another school's documents, confirmed empirically). See docs/api-contract.md's
// "Document OCR" section. Callers pass the real logged-in admin's own
// school_id (from useCurrentUser()) - it's no longer a hardcoded constant here.

export function useUploadDocument(schoolId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ file, documentType }: { file: File; documentType: DocumentType }) => {
      const form = new FormData();
      form.append("file", file);
      form.append("document_type", documentType);
      form.append("school_id", String(schoolId));
      return apiPostForm<DocumentCreateResult>("/admin/ocr/documents", form);
    },
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["ocr-document", result.id] });
      queryClient.invalidateQueries({ queryKey: ["ocr-documents-list"] });
    },
  });
}

export function useDocumentsList(
  schoolId: number,
  params: { status?: string; documentType?: DocumentType; page?: number; pageSize?: number } = {}
) {
  return useQuery({
    queryKey: ["ocr-documents-list", schoolId, params.status, params.documentType, params.page, params.pageSize],
    queryFn: () =>
      apiGet<DocumentsListResponse>("/admin/ocr/documents", {
        school_id: schoolId,
        status: params.status,
        document_type: params.documentType,
        page: params.page,
        page_size: params.pageSize,
      }),
  });
}

export function useDocument(schoolId: number, documentId: number | undefined) {
  return useQuery({
    queryKey: ["ocr-document", documentId],
    queryFn: () => apiGet<DocumentDetail>(`/admin/ocr/documents/${documentId}`, { school_id: schoolId }),
    enabled: documentId !== undefined,
  });
}

export function useCorrectEntity(schoolId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ documentId, entityId, correctedValue }: { documentId: number; entityId: number; correctedValue: string }) =>
      apiPut<ExtractedEntity>(`/admin/ocr/documents/${documentId}/entities/${entityId}?school_id=${schoolId}`, {
        corrected_value: correctedValue,
      }),
    onSuccess: (_result, { documentId }) => {
      queryClient.invalidateQueries({ queryKey: ["ocr-document", documentId] });
    },
  });
}

/** For a field OCR never found at all (no entity exists yet) - genuinely different
 * from useCorrectEntity, which corrects an EXISTING (if wrong/low-confidence)
 * value. See DocumentDetail.expected_fields' docstring for why a field can go
 * missing entirely, not just low-confidence. */
export function useAddManualEntity(schoolId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ documentId, fieldName, value }: { documentId: number; fieldName: string; value: string }) =>
      apiPost<DocumentDetail>(`/admin/ocr/documents/${documentId}/entities?school_id=${schoolId}`, {
        field_name: fieldName,
        value,
      }),
    onSuccess: (_result, { documentId }) => {
      queryClient.invalidateQueries({ queryKey: ["ocr-document", documentId] });
    },
  });
}

export function useReextractDocument(schoolId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ documentId, documentType }: { documentId: number; documentType?: DocumentType }) =>
      apiPost<DocumentDetail>(
        `/admin/ocr/documents/${documentId}/reextract?school_id=${schoolId}`,
        documentType ? { document_type: documentType } : {}
      ),
    onSuccess: (_result, { documentId }) => {
      queryClient.invalidateQueries({ queryKey: ["ocr-document", documentId] });
      queryClient.invalidateQueries({ queryKey: ["ocr-documents-list"] });
    },
  });
}
