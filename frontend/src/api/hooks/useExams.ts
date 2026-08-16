import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/api/client";
import type {
  Exam,
  ExamType,
  ExamsListResponse,
  GenerateSchedulesResult,
  InvigilationDuty,
  RoomSuggestionsResult,
  SeatingResponse,
} from "@/api/types";

export function useCreateExam() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      school_id: number;
      subject_id: number;
      class_id: number;
      academic_year: string;
      exam_type?: ExamType;
      exam_date: string;
      start_time: string;
      end_time: string;
      total_marks?: number;
    }) => apiPost<Exam>("/admin/exams", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["exams-list"] }),
  });
}

export function useCreateExamsForGrade() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: {
      school_id: number;
      subject_id: number;
      grade_level: number;
      academic_year: string;
      exam_type?: ExamType;
      exam_date: string;
      start_time: string;
      end_time: string;
      total_marks?: number;
    }) => apiPost<{ created: Exam[] }>("/admin/exams/bulk-by-grade", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["exams-list"] }),
  });
}

export function useRoomSuggestions(examId?: number) {
  return useQuery({
    queryKey: ["exam-room-suggestions", examId],
    queryFn: () => apiGet<RoomSuggestionsResult>(`/admin/exams/${examId}/room-suggestions`),
    enabled: examId != null,
  });
}

export function useExamsList(params: { classId?: number; subjectId?: number; academicYear?: string; page?: number; pageSize?: number } = {}) {
  return useQuery({
    queryKey: ["exams-list", params.classId, params.subjectId, params.academicYear, params.page, params.pageSize],
    queryFn: () =>
      apiGet<ExamsListResponse>("/admin/exams", {
        class_id: params.classId,
        subject_id: params.subjectId,
        academic_year: params.academicYear,
        page: params.page,
        page_size: params.pageSize,
      }),
  });
}

export function useGenerateSchedules() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      examId,
      rooms,
      dryRun,
    }: {
      examId: number;
      rooms: { room_id: number; capacity: number }[];
      dryRun: boolean;
    }) => apiPost<GenerateSchedulesResult>(`/admin/exams/${examId}/schedules`, { rooms, dry_run: dryRun }),
    onSuccess: (result, { examId, dryRun }) => {
      // Only a real (non-preview) generation actually changed anything worth
      // refetching - a dry-run preview persisted nothing.
      if (!dryRun && result.status === "generated") {
        queryClient.invalidateQueries({ queryKey: ["exam-seating", examId] });
      }
    },
  });
}

export function useSeating(params: { examId?: number; studentId?: number; enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["exam-seating", params.examId, params.studentId],
    queryFn: () => apiGet<SeatingResponse>("/admin/exams/seating", { exam_id: params.examId, student_id: params.studentId }),
    enabled: params.enabled ?? true,
  });
}

export function useMyInvigilations() {
  return useQuery({
    queryKey: ["my-invigilations"],
    queryFn: () => apiGet<InvigilationDuty[]>("/admin/exams/invigilations/me"),
  });
}
