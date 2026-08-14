import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost } from "@/api/client";
import type { AdmissionApplication, AdmissionDecisionResult, AdmissionsListResponse, AdmissionStatus } from "@/api/types";

export function useSubmitApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      school_id: number;
      academic_year: string;
      applicant_name: string;
      dob: string;
      guardian_email: string;
      grade_applied: string;
      ocr_document_ids?: number[];
    }) => apiPost<AdmissionApplication>("/admin/admissions/applications", { ocr_document_ids: [], ...body }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admissions-applications"] }),
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

export function useUpdateApplication() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      status,
      decisionJustification,
      studentUserId,
      classId,
    }: {
      id: number;
      status: AdmissionStatus;
      decisionJustification?: string;
      studentUserId?: number;
      classId?: number;
    }) =>
      apiPatch<AdmissionDecisionResult>(`/admin/admissions/applications/${id}`, {
        status,
        decision_justification: decisionJustification ?? null,
        student_user_id: studentUserId ?? null,
        class_id: classId ?? null,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admissions-applications"] });
      queryClient.invalidateQueries({ queryKey: ["admin-approvals"] });
    },
  });
}
