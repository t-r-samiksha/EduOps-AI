import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/api/client";
import type { SyllabusCheckpoint, SyllabusPlan, SyllabusSummaryItem } from "@/api/types";

export function useSyllabusSummary(params: { classId?: number; subjectId?: number; academicYear?: string } = {}) {
  return useQuery({
    queryKey: ["syllabus-summary", params.classId, params.subjectId, params.academicYear],
    queryFn: () =>
      apiGet<{ items: SyllabusSummaryItem[] }>("/syllabus/summary", {
        class_id: params.classId,
        subject_id: params.subjectId,
        academic_year: params.academicYear,
      }),
  });
}

export function useCreateSyllabusPlan() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      class_id: number;
      subject_id: number;
      academic_year: string;
      total_units: number;
      term_start_date: string;
      term_end_date: string;
    }) => apiPost<SyllabusPlan>("/syllabus/plan", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["syllabus-summary"] }),
  });
}

export function useLogCheckpoint() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { plan_id: number; topic_label: string; sequence_number: number }) =>
      apiPost<SyllabusCheckpoint>("/syllabus/checkpoint", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["syllabus-summary"] }),
  });
}
