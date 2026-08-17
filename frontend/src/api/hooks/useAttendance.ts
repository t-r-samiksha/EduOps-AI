import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPostForm, apiPut } from "@/api/client";
import type {
  AttendanceAnalyticsResponse,
  AttendanceRecord,
  AttendanceRegisterResponse,
  AttendanceSummaryResponse,
  EnrollmentListItem,
  EnrollResponse,
  ManualMarkEntry,
  ManualMarkResponse,
  MarkAttendanceResponse,
  MyAttendanceRecordsResponse,
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
      queryClient.invalidateQueries({ queryKey: ["attendance-register"] });
      queryClient.invalidateQueries({ queryKey: ["attendance-analytics"] });
    },
  });
}

/** One class's whole day as a period x student grid. */
export function useAttendanceRegister(params: { classId?: number; date: string; enabled?: boolean }) {
  return useQuery({
    queryKey: ["attendance-register", params.classId, params.date],
    queryFn: () =>
      apiGet<AttendanceRegisterResponse>("/attendance/register", {
        class_id: params.classId,
        date: params.date,
      }),
    enabled: (params.enabled ?? true) && params.classId != null,
  });
}

/** Bulk manual marking. One request per Save, however many cells changed -
 * per-keystroke requests would mean hundreds of calls for a full grid. */
export function useMarkManualAttendance() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      classId,
      date,
      entries,
    }: {
      classId: number;
      date: string;
      entries: ManualMarkEntry[];
    }) =>
      apiPost<ManualMarkResponse>("/attendance/manual", {
        class_id: classId,
        date,
        entries,
      }),
    onSuccess: () => {
      // Every downstream view of attendance is now stale: the register itself,
      // the range summary, the analytics slices and any student/parent history.
      queryClient.invalidateQueries({ queryKey: ["attendance-register"] });
      queryClient.invalidateQueries({ queryKey: ["attendance-summary"] });
      queryClient.invalidateQueries({ queryKey: ["attendance-analytics"] });
      queryClient.invalidateQueries({ queryKey: ["attendance-my-records"] });
      queryClient.invalidateQueries({ queryKey: ["child-summary"] });
    },
  });
}

export function useAttendanceAnalytics(params: {
  fromDate: string;
  toDate: string;
  classId?: number;
  gradeLevel?: number;
  section?: string;
  periodNumber?: number;
  subjectId?: number;
  /** Filters the students list down to those below this present_pct. */
  belowPct?: number;
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: [
      "attendance-analytics",
      params.fromDate,
      params.toDate,
      params.classId,
      params.gradeLevel,
      params.section,
      params.periodNumber,
      params.subjectId,
      params.belowPct,
    ],
    queryFn: () =>
      apiGet<AttendanceAnalyticsResponse>("/attendance/analytics", {
        from_date: params.fromDate,
        to_date: params.toDate,
        class_id: params.classId,
        grade_level: params.gradeLevel,
        section: params.section,
        period_number: params.periodNumber,
        subject_id: params.subjectId,
        below_pct: params.belowPct,
      }),
    enabled: params.enabled ?? true,
  });
}

/** One student's period-by-period history. The student/parent portal view -
 * a student always reads themselves and `studentId` is ignored for them; a
 * parent must pass one of their own linked children. */
export function useMyAttendanceRecords(params: {
  fromDate: string;
  toDate: string;
  studentId?: number;
  enabled?: boolean;
}) {
  return useQuery({
    queryKey: ["attendance-my-records", params.fromDate, params.toDate, params.studentId],
    queryFn: () =>
      apiGet<MyAttendanceRecordsResponse>("/attendance/my-records", {
        from_date: params.fromDate,
        to_date: params.toDate,
        student_id: params.studentId,
      }),
    enabled: params.enabled ?? true,
  });
}
