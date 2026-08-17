import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/api/client";

export interface RemarkRecord {
  id: number;
  student_id: number;
  student_name?: string;
  author_id: number;
  author_name?: string;
  class_id: number;
  subject_id?: number;
  subject_name?: string;
  content: string;
  sentiment_tag: string; // academic, behavioral, appreciation
  created_at: string;
}

export function useStudentRemarks(studentId?: number, sentimentTag?: string) {
  return useQuery<RemarkRecord[]>({
    queryKey: ["remarks", studentId, sentimentTag],
    queryFn: () =>
      apiGet<RemarkRecord[]>(`/remarks/${studentId}`, {
        sentiment_tag: sentimentTag && sentimentTag !== "all" ? sentimentTag : undefined,
      }),
    enabled: typeof studentId === "number" && !isNaN(studentId),
  });
}

export function useCreateRemark() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      student_id: number;
      class_id: number;
      subject_id?: number;
      content: string;
      sentiment_tag: string;
    }) => apiPost<RemarkRecord>("/remarks", payload),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["remarks", variables.student_id] });
      queryClient.invalidateQueries({ queryKey: ["report-cards"] });
    },
  });
}

export function useCreateBulkRemarks() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      class_id: number;
      subject_id?: number;
      remarks: {
        student_id: number;
        content: string;
        sentiment_tag: string;
      }[];
    }) => apiPost("/remarks/bulk", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["remarks"] });
      queryClient.invalidateQueries({ queryKey: ["report-cards"] });
    },
  });
}
