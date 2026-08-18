import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";

export interface StudentAnalytics {
  student_id: number;
  student_name: string;
  term: string;
  attendance: {
    /** null when the student has no attendance records - NOT 0 and NOT 100. */
    percentage: number | null;
    total_days: number;
    present_days: number;
    absent_days: number;
    late_days: number;
    /** Which window the percentage covers ("Last 30 days"), so the UI labels it
     *  instead of showing a bare number that looks like it disagrees with the
     *  report card's academic-year figure. */
    window_label: string;
  };
  gradebook: {
    student_id: number;
    term: string;
    term_average?: number;
    gpa?: number;
    letter_grade?: string;
    subjects: {
      subject_id: number;
      subject_name: string;
      percentage?: number;
      gpa?: number;
      letter_grade?: string;
      entries_count: number;
      categories: Record<string, number>;
    }[];
    total_assessments: number;
  };
  assignments: {
    total_submissions: number;
    submitted_count: number;
    late_count: number;
    missing_count: number;
    average_score?: number;
  };
  quizzes: {
    total_attempts: number;
    average_score?: number;
  };
  risk_status: {
    is_at_risk: boolean;
    flags_count: number;
    reasons: string[];
    banner_message: string;
  };
  trend: {
    month: string;
    score: number;
    attendance: number;
  }[];
}

export function useStudentAnalytics(studentId?: number, term: string = "Term 1") {
  return useQuery<StudentAnalytics>({
    queryKey: ["student-analytics", studentId, term],
    queryFn: () =>
      apiGet<StudentAnalytics>(`/analytics/student/${studentId}`, { term }),
    enabled: typeof studentId === "number" && !isNaN(studentId),
  });
}
