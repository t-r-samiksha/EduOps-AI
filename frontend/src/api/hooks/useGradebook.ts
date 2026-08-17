import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/api/client";

export interface GradebookEntry {
  id: number;
  student_id: number;
  student_name?: string;
  subject_id: number;
  subject_name?: string;
  class_id: number;
  term: string;
  assessment_type: string;
  assessment_id?: number;
  score: number;
  max_score: number;
  percentage: number;
  weight: number;
}

export interface SubjectSummary {
  subject_id: number;
  subject_name: string;
  percentage?: number;
  gpa?: number;
  letter_grade?: string;
  entries_count: number;
  categories: Record<string, number>;
}

export interface StudentGradebookSummary {
  student_id: number;
  student_name?: string;
  term: string;
  term_average?: number;
  gpa?: number;
  letter_grade?: string;
  subjects: SubjectSummary[];
  total_assessments: number;
}

export function useStudentGradebook(studentId?: number, term: string = "Term 1") {
  return useQuery<StudentGradebookSummary>({
    queryKey: ["gradebook", studentId, term],
    queryFn: () =>
      apiGet<StudentGradebookSummary>(`/gradebook/${studentId}`, { term }),
    enabled: typeof studentId === "number" && !isNaN(studentId),
  });
}

export function useClassGradebook(classId?: number, term: string = "Term 1") {
  return useQuery<{
    class_id: number;
    term: string;
    students: {
      student_id: number;
      student_name: string;
      term_average?: number;
      gpa?: number;
      letter_grade?: string;
      subjects: SubjectSummary[];
    }[];
  }>({
    queryKey: ["class-gradebook", classId, term],
    queryFn: () =>
      apiGet(`/gradebook/class/${classId}`, { term }),
    enabled: typeof classId === "number" && !isNaN(classId),
  });
}

export function useUpsertGradebookEntry() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      student_id: number;
      subject_id: number;
      class_id: number;
      term?: string;
      assessment_type: string;
      assessment_id?: number;
      score: number;
      max_score?: number;
      weight?: number;
    }) => apiPost<GradebookEntry>("/gradebook/entry", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["gradebook"] });
      queryClient.invalidateQueries({ queryKey: ["class-gradebook"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}

export function useBulkGradebook() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      entries: {
        student_id: number;
        subject_id: number;
        class_id: number;
        term: string;
        assessment_type: string;
        assessment_id?: number;
        score: number;
        max_score?: number;
        weight?: number;
      }[];
    }) => apiPost("/gradebook/bulk", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["gradebook"] });
      queryClient.invalidateQueries({ queryKey: ["class-gradebook"] });
      queryClient.invalidateQueries({ queryKey: ["analytics"] });
    },
  });
}
