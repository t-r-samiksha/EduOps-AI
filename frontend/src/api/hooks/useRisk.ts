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

export function useLogIntervention() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ flagId, note, actionTaken }: { flagId: number; note: string; actionTaken: string }) =>
      apiPost<Intervention>(`/risk/${flagId}/intervention`, { note, action_taken: actionTaken }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["risk-flagged"] }),
  });
}
