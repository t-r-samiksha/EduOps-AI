import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPatch, apiPost } from "@/api/client";
import type { FeeSchedule, FeeStatusItem, InvoicingRunResult, PaymentResult, RemindersResult } from "@/api/types";

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fee-schedules"] });
      // Records are generated immediately on creation now (see backend), so
      // Status must refresh too, not just Schedules.
      queryClient.invalidateQueries({ queryKey: ["fee-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
    },
  });
}

export function useGenerateScheduleRecords() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (scheduleId: number) => apiPost<FeeSchedule>(`/admin/fees/schedules/${scheduleId}/generate`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fee-schedules"] });
      queryClient.invalidateQueries({ queryKey: ["fee-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
    },
  });
}

export function useRunInvoicing() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { academic_year: string }) => apiPost<InvoicingRunResult>("/admin/fees/invoicing/run", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fee-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
    },
  });
}

export function useFeeStatus(params: { classId?: number; studentId?: number; status?: string; enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["fee-status", params.classId, params.studentId, params.status],
    queryFn: () =>
      apiGet<{ items: FeeStatusItem[] }>("/admin/fees/status", {
        class_id: params.classId,
        student_id: params.studentId,
        status: params.status,
      }),
    enabled: params.enabled ?? true,
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

export function useMarkFeePaid() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ feeRecordId, paid }: { feeRecordId: number; paid: boolean }) =>
      apiPatch<PaymentResult>(`/admin/fees/records/${feeRecordId}/mark-paid`, { paid }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["fee-status"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
    },
  });
}
