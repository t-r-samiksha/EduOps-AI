import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPostForm, apiPut } from "@/api/client";
import type { AttendanceRecord, AttendanceSummaryResponse, EnrollResponse, MarkAttendanceResponse } from "@/api/types";

export function useEnrollStudent() {
  return useMutation({
    mutationFn: ({ studentId, file }: { studentId: number; file: File }) => {
      const form = new FormData();
      form.append("student_id", String(studentId));
      form.append("file", file);
      return apiPostForm<EnrollResponse>("/attendance/enroll", form);
    },
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

export function useAttendanceSummary(params: { fromDate: string; toDate: string; classId?: number; enabled?: boolean }) {
  return useQuery({
    queryKey: ["attendance-summary", params.fromDate, params.toDate, params.classId],
    queryFn: () =>
      apiGet<AttendanceSummaryResponse>("/attendance/summary", {
        from_date: params.fromDate,
        to_date: params.toDate,
        class_id: params.classId,
      }),
    enabled: params.enabled ?? true,
  });
}

export function useReviewAttendanceRecord() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ recordId, status }: { recordId: number; status: "present" | "absent" | "late" }) =>
      apiPut<AttendanceRecord>(`/attendance/${recordId}/review`, { status }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["attendance-summary"] });
    },
  });
}
