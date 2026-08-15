import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPut } from "@/api/client";
import type {
  ApproveLeaveResponse,
  ConfirmSubstitutionResponse,
  LeaveRequest,
  MySubstituteDuty,
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

/** Real duties assigned TO the calling teacher as someone else's substitute
 * (upcoming/ongoing only - already-ended leave is excluded server-side) -
 * previously there was no way for a substitute to discover this anywhere in
 * their own UI, only the leave-taker and admin/principal could see it. */
export function useMySubstituteDuties(enabled = true) {
  return useQuery({
    queryKey: ["my-substitute-duties"],
    queryFn: () => apiGet<MySubstituteDuty[]>("/staff/my-substitute-duties"),
    enabled,
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

/** Read-only, auto-fetching version of the leave_request_id mode behind the
 * old "Load substitutions" lookup - shows the real, persisted Substitution
 * rows for a leave request INLINE on its card (both roles - the backend
 * allows the owning teacher to read their own leave request's substitutions
 * too, not just admin/principal), instead of requiring a manual ID lookup
 * in a separate tab. Reuses the exact same POST /substitution/suggest
 * endpoint/logic as before - not a duplicated read path - just via useQuery
 * so it fires automatically once a card's substitutes section is expanded. */
export function useLeaveRequestSubstitutions(params: { leaveRequestId: number; academicYear: string; enabled: boolean }) {
  return useQuery({
    queryKey: ["leave-request-substitutions", params.leaveRequestId, params.academicYear],
    queryFn: () =>
      apiPost<SuggestSubstitutionsResponse>("/substitution/suggest", {
        leave_request_id: params.leaveRequestId,
        academic_year: params.academicYear,
      }),
    enabled: params.enabled,
  });
}

export function useConfirmSubstitution() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ substitutionId, substituteTeacherId }: { substitutionId: number; substituteTeacherId?: number }) =>
      apiPut<ConfirmSubstitutionResponse>(`/substitution/${substitutionId}/confirm`, {
        substitute_teacher_id: substituteTeacherId,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
      queryClient.invalidateQueries({ queryKey: ["leave-request-substitutions"] });
    },
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
