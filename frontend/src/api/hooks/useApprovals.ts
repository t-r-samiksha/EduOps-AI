import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/api/client";
import type { Approval } from "@/api/types";

export function usePendingApprovals() {
  return useQuery({
    queryKey: ["admin-approvals"],
    queryFn: () => apiGet<{ items: Approval[] }>("/admin/approvals"),
  });
}

export function useDecideApproval() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      id,
      decision,
      comment,
      academicYear,
      studentUserId,
      classId,
    }: {
      id: string;
      decision: "approve" | "reject";
      comment?: string;
      academicYear?: string;
      studentUserId?: number;
      classId?: number;
    }) =>
      apiPost<{ id: string; status: string }>(`/admin/approvals/${id}/decision`, {
        decision,
        comment,
        academic_year: academicYear,
        student_user_id: studentUserId,
        class_id: classId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-approvals"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
      queryClient.invalidateQueries({ queryKey: ["leave-requests"] });
    },
  });
}
