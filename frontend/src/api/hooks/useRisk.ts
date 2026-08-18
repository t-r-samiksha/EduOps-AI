import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPut } from "@/api/client";
import type { Intervention, RiskFlag } from "@/api/types";

export function useFlaggedStudents(
  params: { riskLevel?: string; classId?: number; studentId?: number; status?: string; enabled?: boolean } = {}
) {
  return useQuery({
    queryKey: ["risk-flagged", params.riskLevel, params.classId, params.studentId, params.status],
    queryFn: () =>
      apiGet<RiskFlag[]>("/risk/flagged", {
        risk_level: params.riskLevel,
        class_id: params.classId,
        student_id: params.studentId,
        status: params.status,
      }),
    enabled: params.enabled ?? true,
  });
}

export function useCreateRiskFlag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { student_id: number; risk_level: string; reasons: string[]; score?: number }) =>
      apiPost<RiskFlag>("/risk/flag", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["risk-flagged"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
    },
  });
}

export function useAcknowledgeFlag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (flagId: number) => apiPut<RiskFlag>(`/risk/${flagId}/acknowledge`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["risk-flagged"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
    },
  });
}

export function useResolveFlag() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (flagId: number) => apiPut<RiskFlag>(`/risk/${flagId}/resolve`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["risk-flagged"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
    },
  });
}

/** The outreach history for one flag, newest first.
 *
 * Interventions used to be WRITE-ONLY: POST /risk/{id}/intervention saved a row and nothing
 * in the app ever displayed it, so logging one was indistinguishable from the button not
 * working, and the next teacher could not tell an outreach had already been made. */
export function useFlagInterventions(flagId?: number) {
  return useQuery<{ items: Intervention[] }>({
    queryKey: ["risk-interventions", flagId],
    queryFn: () => apiGet<{ items: Intervention[] }>(`/risk/${flagId}/interventions`),
    enabled: typeof flagId === "number" && !Number.isNaN(flagId),
  });
}

export function useLogIntervention() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ flagId, note, actionTaken }: { flagId: number; note: string; actionTaken: string }) =>
      apiPost<Intervention>(`/risk/${flagId}/intervention`, { note, action_taken: actionTaken }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["risk-flagged"] });
      // Without this the intervention list still showed the pre-log result, which looked
      // exactly like the save having failed.
      queryClient.invalidateQueries({ queryKey: ["risk-interventions", variables.flagId] });
    },
  });
}
