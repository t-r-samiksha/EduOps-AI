import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost, apiPostForm, apiPut } from "@/api/client";
import type {
  AssignmentItem,
  CreateAssignmentRequest,
  GradeSubmissionRequest,
  SubmissionItem,
  SubmitAssignmentRequest,
  UploadAttachmentResponse,
} from "@/api/types";

export function useAssignments(subjectId?: number) {
  return useQuery({
    queryKey: ["assignments", subjectId],
    queryFn: () =>
      apiGet<AssignmentItem[]>("/assignments", subjectId ? { subject_id: subjectId } : undefined),
  });
}

export function useClassAssignments(classId?: number, subjectId?: number) {
  return useQuery({
    queryKey: ["class-assignments", classId, subjectId],
    queryFn: () =>
      apiGet<AssignmentItem[]>(`/assignments/${classId}`, subjectId ? { subject_id: subjectId } : undefined),
    enabled: typeof classId === "number" && !isNaN(classId),
  });
}

export function useAssignmentDetail(assignmentId?: number) {
  return useQuery({
    queryKey: ["assignment-detail", assignmentId],
    queryFn: () => apiGet<AssignmentItem>(`/assignments/detail/${assignmentId}`),
    enabled: typeof assignmentId === "number" && !isNaN(assignmentId),
  });
}

export function useAssignmentSubmissions(assignmentId?: number) {
  return useQuery({
    queryKey: ["assignment-submissions", assignmentId],
    queryFn: () => apiGet<SubmissionItem[]>(`/assignments/${assignmentId}/submissions`),
    enabled: typeof assignmentId === "number" && !isNaN(assignmentId),
  });
}

export function useCreateAssignment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreateAssignmentRequest) =>
      apiPost<AssignmentItem>("/assignments", body),
    onSuccess: (_, input) => {
      queryClient.invalidateQueries({ queryKey: ["assignments"] });
      queryClient.invalidateQueries({ queryKey: ["class-assignments", input.class_id] });
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
    },
  });
}

export function useSubmitAssignment(assignmentId?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SubmitAssignmentRequest) =>
      apiPost<SubmissionItem>(`/assignments/${assignmentId}/submit`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assignments"] });
      queryClient.invalidateQueries({ queryKey: ["class-assignments"] });
      queryClient.invalidateQueries({ queryKey: ["assignment-detail", assignmentId] });
      queryClient.invalidateQueries({ queryKey: ["assignment-submissions", assignmentId] });
    },
  });
}

export function useGradeSubmission(assignmentId?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ submissionId, data }: { submissionId: number; data: GradeSubmissionRequest }) =>
      apiPut<SubmissionItem>(`/assignments/${assignmentId}/grade/${submissionId}`, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assignments"] });
      queryClient.invalidateQueries({ queryKey: ["class-assignments"] });
      queryClient.invalidateQueries({ queryKey: ["assignment-detail", assignmentId] });
      queryClient.invalidateQueries({ queryKey: ["assignment-submissions", assignmentId] });
    },
  });
}

export function useUploadAssignmentFile(assignmentId?: number) {
  return useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return apiPostForm<UploadAttachmentResponse>(`/assignments/${assignmentId}/upload`, formData);
    },
  });
}

export function useDeleteAssignment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (assignmentId: number) => apiDelete<void>(`/assignments/${assignmentId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assignments"] });
      queryClient.invalidateQueries({ queryKey: ["class-assignments"] });
    },
  });
}

export function useNudgeStudent(assignmentId?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (studentId: number) =>
      apiPost<{ status: string; student_id: number; assignment_id: number }>(
        `/assignments/${assignmentId}/nudge/${studentId}`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assignment-submissions", assignmentId] });
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}

export function useNudgeAllMissing(assignmentId?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () =>
      apiPost<{ status: string; nudged_count: number }>(
        `/assignments/${assignmentId}/nudge-missing`,
        {}
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["assignment-submissions", assignmentId] });
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
    },
  });
}
