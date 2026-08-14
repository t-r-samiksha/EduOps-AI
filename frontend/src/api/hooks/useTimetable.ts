import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPut } from "@/api/client";
import type { TimetableSlot, TimetableUpdateResponse } from "@/api/types";

interface UseTimetableParams {
  academicYear: string;
  classId?: number;
  teacherId?: number;
  studentId?: number;
  enabled?: boolean;
  retry?: boolean | number;
}

export function useTimetableActive({ academicYear, classId, teacherId, studentId, enabled = true, retry }: UseTimetableParams) {
  return useQuery({
    queryKey: ["timetable-active", academicYear, classId, teacherId, studentId],
    queryFn: () =>
      apiGet<TimetableSlot[]>("/timetable/active", {
        academic_year: academicYear,
        class_id: classId,
        teacher_id: teacherId,
        student_id: studentId,
      }),
    enabled,
    ...(retry !== undefined ? { retry } : {}),
  });
}

export interface UpdateTimetableSlotBody {
  slot_id: number;
  day_of_week?: number;
  period_number?: number;
  teacher_id?: number;
  room_id?: number;
  subject_id?: number;
}

/** PUT /timetable/update: on conflict, the backend leaves the slot UNTOUCHED and
 * returns `{ slot: null, conflicts: [...] }` instead of throwing - so a "conflict"
 * is a normal 200 response, not a mutation error. Callers must check `result.slot`
 * rather than relying on isError/isSuccess to know whether anything actually
 * changed. Only a real success (`result.slot` non-null) should invalidate the
 * cached grid; a conflict changed nothing server-side, so nothing to refetch. */
export function useUpdateTimetableSlot() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: UpdateTimetableSlotBody) => apiPut<TimetableUpdateResponse>("/timetable/update", body),
    onSuccess: (result) => {
      if (result.slot) {
        queryClient.invalidateQueries({ queryKey: ["timetable-active"] });
      }
    },
  });
}

export interface LookupResponse {
  subjects: { id: number; name: string }[];
  teachers: { id: number; name: string }[];
  students: { id: number; name: string }[];
  rooms: { id: number; name: string }[];
  classes: { id: number; name: string }[];
}

export function useReferenceLookup(schoolId: number) {
  return useQuery({
    queryKey: ["reference-lookup", schoolId],
    queryFn: () => apiGet<LookupResponse>("/reference/lookup", { school_id: schoolId }),
    staleTime: 5 * 60_000,
  });
}
