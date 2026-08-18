import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost } from "@/api/client";

export interface ReportCard {
  id: number;
  school_id: number;
  student_id: number;
  class_id: number;
  term: string;
  academic_year: string;
  pdf_url?: string;
  gpa?: number;
  term_average?: number;
  attendance_percentage?: number;
  source_data_snapshot: {
    school_name: string;
    student_name: string;
    student_id: number;
    class_name: string;
    academic_year: string;
    term: string;
    generated_date: string;
    subjects: {
      subject_id: number;
      subject_name: string;
      percentage?: number;
      gpa?: number;
      letter_grade?: string;
      categories?: Record<string, number>;
    }[];
    term_average?: number;
    gpa?: number;
    letter_grade?: string;
    attendance: {
      total_days: number;
      absent_days?: number;
      late_days?: number;
      /** "Attendance — 2026-27". Rendered beside the number on screen and in the PDF. */
      label?: string;
      present_days: number;
      percentage: number;
    };
    teacher_remarks: {
      content: string;
      sentiment: string;
      date: string;
    }[];
  };
  generated_at: string;
}

export function useStudentReportCards(studentId?: number) {
  return useQuery<ReportCard[]>({
    queryKey: ["report-cards", studentId],
    queryFn: () => apiGet<ReportCard[]>(`/report_cards/${studentId}`),
    enabled: typeof studentId === "number" && !isNaN(studentId),
  });
}

/** Report cards already generated for a class section.
 *
 * The read side of `useBulkGenerateReports`, which had none: staff could generate a whole
 * class's cards and then had no way to see them, because the only listing endpoint was
 * per-student. The page fell back to requesting student id 0 and showed a permanent
 * "No report cards generated yet" even immediately after a successful bulk run. */
export function useClassReportCards(
  classId?: number,
  term?: string,
  academicYear?: string,
) {
  return useQuery<ReportCard[]>({
    queryKey: ["class-report-cards", classId, term, academicYear],
    queryFn: () =>
      apiGet<ReportCard[]>(`/report_cards/class/${classId}`, {
        term,
        academic_year: academicYear,
      }),
    enabled: typeof classId === "number" && !Number.isNaN(classId),
  });
}

export function useReportCardDetail(reportCardId?: number) {
  return useQuery<ReportCard>({
    queryKey: ["report-card-detail", reportCardId],
    queryFn: () => apiGet<ReportCard>(`/report_cards/detail/${reportCardId}`),
    enabled: typeof reportCardId === "number" && !isNaN(reportCardId),
  });
}

export function useGenerateReportCard() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      studentId,
      term = "Term 1",
      academicYear = "2026-27",
    }: {
      studentId: number;
      term?: string;
      academicYear?: string;
    }) =>
      apiPost<ReportCard>(
        `/report_cards/generate/${studentId}?term=${encodeURIComponent(
          term
        )}&academic_year=${encodeURIComponent(academicYear)}`
      ),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["report-cards", variables.studentId] });
      queryClient.invalidateQueries({ queryKey: ["class-report-cards"] });
    },
  });
}

export function useBulkGenerateReports() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      classId,
      term = "Term 1",
      academicYear = "2026-27",
    }: {
      classId: number;
      term?: string;
      academicYear?: string;
    }) =>
      apiPost(
        `/report_cards/bulk-generate/${classId}?term=${encodeURIComponent(
          term
        )}&academic_year=${encodeURIComponent(academicYear)}`
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["report-cards"] });
      // Without this the class listing kept showing the pre-generation result.
      queryClient.invalidateQueries({ queryKey: ["class-report-cards"] });
    },
  });
}
