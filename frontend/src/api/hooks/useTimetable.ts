import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPut } from "@/api/client";
import type { PreflightResult, TimetableGenerateResponse, TimetableSlot, TimetableUpdateResponse } from "@/api/types";

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

/** Real committed-hours-per-teacher count from a school's currently active
 * timetable slots - the single source of truth behind GenerateTimetableForm's
 * "Committed: X/Y hrs/wk" badge. Shared here (not reimplemented) so the
 * School Management page's Teachers tab shows the exact same real number. */
export function computeSlotsByTeacher(slots: TimetableSlot[]): Map<number, number> {
  const map = new Map<number, number>();
  for (const s of slots) map.set(s.teacher_id, (map.get(s.teacher_id) ?? 0) + 1);
  return map;
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

export interface SubjectSelectionBody {
  subject_id: number;
  periods_per_week: number;
  lab_required: boolean;
}

export interface TeacherSelectionBody {
  teacher_id: number;
  included: boolean;
  max_periods_per_week_override?: number | null;
}

/** Matches the backend's real GenerateRequest shape exactly (see
 * backend/app/routers/timetable.py) - built fresh from real teacher/room/subject
 * master data plus this request's own selections every run, never persisted back
 * to master data (a per-run override only ever affects this one generation). */
export interface GenerateTimetableBody {
  school_id: number;
  academic_year: string;
  grade_levels: number[];
  sections_per_grade: number;
  periods_per_day: number;
  days_per_week: number;
  subjects: SubjectSelectionBody[];
  teacher_selections: TeacherSelectionBody[];
  room_ids: number[];
}

/** POST /timetable/generate is a SUPERSEDING run, not additive - it deactivates
 * any previous active slots for the affected class(es)/academic_year before
 * inserting the new ones (real backend behavior, not a UI assumption). */
export function useGenerateTimetable() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: GenerateTimetableBody) => apiPost<TimetableGenerateResponse>("/timetable/generate", body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["timetable-active"] }),
  });
}

/** Read-only: runs the EXACT same pre-flight arithmetic checks POST
 * /timetable/generate itself gates on (Section balance, teacher pool
 * capacity, room/lab concurrency, teacher availability, cross-run
 * collisions) - meant to be called with a debounced body as the admin edits
 * the Generate dialog, so problems surface before Generate is even
 * pressed. Deliberately calls the backend rather than reimplementing this
 * arithmetic in TypeScript, so the live check and the real gate can never
 * drift apart. `body` may be null while the form doesn't yet have enough
 * input to attempt a real request. */
export function usePreflightCheck(body: GenerateTimetableBody | null) {
  return useQuery({
    queryKey: ["timetable-preflight", body],
    queryFn: () => apiPost<PreflightResult>("/timetable/preflight", body),
    enabled: body !== null,
    retry: false,
    staleTime: 0,
  });
}

export interface LookupSubject {
  id: number;
  name: string;
  periods_per_week: number;
  lab_required: boolean;
}

export interface LookupTeacher {
  id: number;
  name: string;
  max_periods_per_week: number | null;
  subject_ids: number[];
}

export interface LookupRoom {
  id: number;
  name: string;
  room_type: string;
}

export interface LookupClass {
  id: number;
  name: string;
  grade_level: number | null;
  grade_label: string | null;
  section: string | null;
  class_teacher_id: number | null;
}

export interface LookupResponse {
  subjects: LookupSubject[];
  teachers: LookupTeacher[];
  students: { id: number; name: string }[];
  rooms: LookupRoom[];
  classes: LookupClass[];
}

export function useReferenceLookup(schoolId?: number | null) {
  return useQuery({
    queryKey: ["reference-lookup", schoolId ?? "current"],
    queryFn: () =>
      apiGet<LookupResponse>("/reference/lookup", schoolId != null ? { school_id: schoolId } : undefined),
    staleTime: 5 * 60_000,
  });
}
