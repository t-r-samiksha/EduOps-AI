import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import type { TimetableSlot } from "@/api/types";

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
