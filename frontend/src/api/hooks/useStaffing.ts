import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPut } from "@/api/client";
import type {
  ApproveLeaveResponse,
  ConfirmSubstitutionResponse,
  LeaveRequest,
  StaffingForecast,
  SubstituteSuggestionsResponse,
  SuggestSubstitutionsResponse,
} from "@/api/types";

export function useLeaveRequests(params: { status?: string; teacherId?: number } = {}) {
  return useQuery({
    queryKey: ["leave-requests", params.status, params.teacherId],
    queryFn: () => apiGet<LeaveRequest[]>("/staff/leave_requests", { status: params.status, teacher_id: params.teacherId }),
  });
}

export function useRequestLeave() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { teacher_id?: number; start_date: string; end_date: string; reason: string }) =>
      apiPost<LeaveRequest>("/staff/request_leave", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["leave-requests"] }),
  });
}

/** Approves/rejects through the unified approvals endpoint (same underlying
 * decide_leave_request() as PUT /staff/approve_leave), per the playbook's
 * instruction to route staffing decisions through the shared approval pattern. */
export function useDecideLeaveRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      leaveRequestId,
      decision,
      academicYear,
    }: {
      leaveRequestId: number;
      decision: "approve" | "reject";
      academicYear?: string;
    }) =>
      apiPost<{ id: string; status: string }>(`/admin/approvals/leave_request:${leaveRequestId}/decision`, {
        decision,
        academic_year: academicYear,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leave-requests"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
      queryClient.invalidateQueries({ queryKey: ["admin-approvals"] });
    },
  });
}

/** Fallback path used by the "Review substitutes" flow — same server-side
 * logic as the approvals decision above, but its response inlines the created
 * Substitution rows (with real ids) so they're immediately confirmable. */
export function useApproveLeaveDirect() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { leave_request_id: number; decision: "approved" | "rejected"; academic_year?: string }) =>
      apiPut<ApproveLeaveResponse>("/staff/approve_leave", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["leave-requests"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
    },
  });
}

export function useSuggestSubstitutions() {
  return useMutation({
    mutationFn: (body: { leave_request_id: number; academic_year: string }) =>
      apiPost<SuggestSubstitutionsResponse>("/substitution/suggest", body),
  });
}

export function useConfirmSubstitution() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ substitutionId, substituteTeacherId }: { substitutionId: number; substituteTeacherId?: number }) =>
      apiPut<ConfirmSubstitutionResponse>(`/substitution/${substitutionId}/confirm`, {
        substitute_teacher_id: substituteTeacherId,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-alerts"] }),
  });
}

export function useStaffingForecast(params: { schoolId: number; weekStart: string; enabled?: boolean }) {
  return useQuery({
    queryKey: ["staffing-forecast", params.schoolId, params.weekStart],
    queryFn: () => apiGet<StaffingForecast>("/admin/staffing/forecast", { school_id: params.schoolId, week_start: params.weekStart }),
    enabled: params.enabled ?? true,
  });
}

export function useSubstituteSuggestionsPreview() {
  return useMutation({
    mutationFn: (params: { teacherId: number; date: string; academicYear: string }) =>
      apiGet<SubstituteSuggestionsResponse>("/admin/staffing/substitute-suggestions", {
        teacher_id: params.teacherId,
        date: params.date,
        academic_year: params.academicYear,
      }),
  });
}
