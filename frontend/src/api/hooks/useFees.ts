import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/api/client";
import type { FeeSchedule, FeeStatusItem, PaymentResult, RemindersResult } from "@/api/types";

export function useFeeSchedules(params: { schoolId?: number; academicYear?: string } = {}) {
  return useQuery({
    queryKey: ["fee-schedules", params.schoolId, params.academicYear],
    queryFn: () => apiGet<FeeSchedule[]>("/admin/fees/schedules", { school_id: params.schoolId, academic_year: params.academicYear }),
    enabled: params.schoolId != null,
  });
}

export function useCreateFeeSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { school_id: number; class_id?: number; academic_year: string; fee_type: string; amount: number; due_date: string }) =>
      apiPost<FeeSchedule>("/admin/fees/schedules", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["fee-schedules"] }),
  });
}

export function useFeeStatus(params: { classId?: number; status?: string } = {}) {
  return useQuery({
    queryKey: ["fee-status", params.classId, params.status],
    queryFn: () => apiGet<{ items: FeeStatusItem[] }>("/admin/fees/status", { class_id: params.classId, status: params.status }),
  });
}

export function useTriggerReminders() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { class_id?: number; overdue_only: boolean }) => apiPost<RemindersResult>("/admin/fees/reminders", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fee-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
    },
  });
}

export function useRecordPayment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ feeRecordId, amount, paidAt }: { feeRecordId: number; amount: number; paidAt?: string }) =>
      apiPost<PaymentResult>(`/admin/fees/records/${feeRecordId}/payment`, { amount, paid_at: paidAt ?? null }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fee-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
    },
  });
}
