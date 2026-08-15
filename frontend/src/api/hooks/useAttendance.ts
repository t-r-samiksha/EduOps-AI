import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPostForm, apiPut } from "@/api/client";
import type {
  AttendanceRecord,
  AttendanceSummaryResponse,
  EnrollmentListItem,
  EnrollResponse,
  MarkAttendanceResponse,
} from "@/api/types";

export function useEnrollStudent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ studentId, file }: { studentId: number; file: File }) => {
      const form = new FormData();
      form.append("student_id", String(studentId));
      form.append("file", file);
      return apiPostForm<EnrollResponse>("/attendance/enroll", form);
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["attendance-enrollments"] }),
  });
}

/** Real, persisted enrollment state for a school - not client session memory.
 * Refetching this (on mount, and after each successful enrollment) is what
 * makes the Enroll tab's list survive a full page reload/logout-login: it
 * reads the actual DB truth fresh every time, rather than remembering what
 * happened earlier in an in-memory list that resets when the component
 * unmounts. */
export function useAttendanceEnrollments(schoolId: number) {
  return useQuery({
    queryKey: ["attendance-enrollments", schoolId],
    queryFn: () => apiGet<EnrollmentListItem[]>("/attendance/enrollments", { school_id: schoolId }),
  });
}

export function useMarkAttendance() {
  return useMutation({
    mutationFn: ({ timetableSlotId, file, date }: { timetableSlotId: number; file: File; date?: string }) => {
      const form = new FormData();
      form.append("timetable_slot_id", String(timetableSlotId));
      form.append("file", file);
      if (date) form.append("date", date);
      return apiPostForm<MarkAttendanceResponse>("/attendance/mark", form);
    },
  });
}

export function useAttendanceSummary(params: {
  fromDate: string;
  toDate: string;
  classId?: number;
  studentId?: number;
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: ["attendance-summary", params.fromDate, params.toDate, params.classId, params.studentId],
    queryFn: () =>
      apiGet<AttendanceSummaryResponse>("/attendance/summary", {
        from_date: params.fromDate,
        to_date: params.toDate,
        class_id: params.classId,
        student_id: params.studentId,
      }),
    enabled: params.enabled ?? true,
  });
}

export function useReviewAttendanceRecord() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      recordId,
      status,
      studentId,
    }: {
      recordId: number;
      status: "present" | "absent" | "late";
      /** Corrects a needs_review match's identity - "this was actually
       * <studentId>", not the student the CV pipeline originally matched. */
      studentId?: number;
    }) => apiPut<AttendanceRecord>(`/attendance/${recordId}/review`, { status, student_id: studentId }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["attendance-summary"] });
    },
  });
}
