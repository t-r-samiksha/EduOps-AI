import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost } from "@/api/client";
import type {
  AdmissionApplication,
  AdmissionApplicationDetail,
  AdmissionDecisionResult,
  AdmissionsListResponse,
  AdmissionStatus,
  GradeLevelsResponse,
} from "@/api/types";

export function useSubmitApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      school_id: number;
      academic_year: string;
      applicant_name: string;
      dob: string;
      guardian_email: string;
      guardian_name?: string;
      guardian_phone?: string;
      grade_applied: string;
      ocr_document_ids?: number[];
    }) => apiPost<AdmissionApplication>("/admin/admissions/applications", { ocr_document_ids: [], ...body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admissions-applications"] }),
  });
}

/** Corrects the application's OWN declared details after submission - genuinely
 * separate from correcting a linked OCR document's extracted fields
 * (useCorrectEntity), which never flows back into an application already created
 * from it (found live: correcting a document's applicant_name didn't update the
 * application that was created from it, and never will by design - this is the
 * real, explicit way to fix the application's own record instead). Blocked by the
 * backend once the application is accepted. */
export function useUpdateApplicationDetails() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      ...body
    }: {
      id: number;
      applicant_name?: string;
      dob?: string;
      guardian_email?: string;
      guardian_name?: string;
      guardian_phone?: string;
    }) => apiPatch<AdmissionApplicationDetail>(`/admin/admissions/applications/${id}/details`, body),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ["admissions-applications"] });
      queryClient.invalidateQueries({ queryKey: ["admissions-application", variables.id] });
    },
  });
}

export function useApplicationsList(params: { status?: AdmissionStatus; page?: number; pageSize?: number } = {}) {
  return useQuery({
    queryKey: ["admissions-applications", params.status, params.page, params.pageSize],
    queryFn: () =>
      apiGet<AdmissionsListResponse>("/admin/admissions/applications", {
        status: params.status,
        page: params.page,
        page_size: params.pageSize,
      }),
  });
}

/** Single-application detail - backs the real applicant detail view (full info +
 * every linked OCR document's full detail, not just the summary card). */
export function useApplication(applicationId: number | null) {
  return useQuery({
    queryKey: ["admissions-application", applicationId],
    queryFn: () => apiGet<AdmissionApplicationDetail>(`/admin/admissions/applications/${applicationId}`),
    enabled: applicationId !== null,
  });
}

/** Attaches an already-uploaded OCR document (marksheet, id_proof, or another
 * admission_form) to an existing application - the missing link for document
 * types with no routing handler of their own (see ocr_routing.py). Returns the
 * same enriched detail shape as useApplication, so the detail view's cache can
 * be refreshed directly from the mutation response. */
export function useAttachDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ applicationId, documentId }: { applicationId: number; documentId: number }) =>
      apiPost<AdmissionApplicationDetail>(`/admin/admissions/applications/${applicationId}/documents`, {
        document_id: documentId,
      }),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ["admissions-application", variables.applicationId] });
      queryClient.invalidateQueries({ queryKey: ["admissions-applications"] });
      // The OCR Documents board (OcrPage.tsx) reads its own separate query keys
      // for the exact same underlying documents - without these, a drag-and-drop
      // attach looked like it silently did nothing until a manual page refresh
      // (found live): the board kept rendering the now-stale application_id it
      // had cached before the attach.
      queryClient.invalidateQueries({ queryKey: ["ocr-documents-list"] });
      queryClient.invalidateQueries({ queryKey: ["ocr-document", variables.documentId] });
    },
  });
}

/** Real offered grade LEVELS for a school/year (never section names - see
 * AdmissionApplication.grade_applied's docstring) - backs the Submit form's
 * "Grade applied" dropdown so an admin picks from what's actually real. */
export function useOfferedGradeLevels(schoolId: number | undefined, academicYear: string) {
  return useQuery({
    queryKey: ["admissions-grade-levels", schoolId, academicYear],
    queryFn: () => apiGet<GradeLevelsResponse>("/admin/admissions/grade-levels", { school_id: schoolId, academic_year: academicYear }),
    enabled: schoolId !== undefined,
  });
}

export function useUpdateApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      status,
      decisionJustification,
    }: {
      id: number;
      status: AdmissionStatus;
      decisionJustification?: string;
    }) =>
      apiPatch<AdmissionDecisionResult>(`/admin/admissions/applications/${id}`, {
        status,
        decision_justification: decisionJustification ?? null,
      }),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ["admissions-applications"] });
      queryClient.invalidateQueries({ queryKey: ["admissions-application", variables.id] });
      queryClient.invalidateQueries({ queryKey: ["admin-approvals"] });
    },
  });
}
