import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost, apiPut } from "@/api/client";

// --- School ------------------------------------------------------------------

export interface SchoolOut {
  id: number;
  name: string;
  address: string | null;
  is_active: boolean;
}

export function useSchool(schoolId: number | undefined) {
  return useQuery({
    queryKey: ["school", schoolId],
    queryFn: () => apiGet<SchoolOut>(`/admin/schools/${schoolId}`),
    enabled: schoolId !== undefined,
  });
}

export function useUpdateSchool() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ schoolId, address }: { schoolId: number; address: string }) =>
      apiPut<SchoolOut>(`/admin/schools/${schoolId}`, { address }),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ["school", variables.schoolId] });
    },
  });
}

// --- Subject -------------------------------------------------------------------

export interface SubjectCreateBody {
  school_id: number;
  name: string;
  code?: string;
  periods_per_week?: number;
  lab_required?: boolean;
}

export interface SubjectOut {
  id: number;
  name: string;
  code: string | null;
  school_id: number;
  is_active: boolean;
  periods_per_week: number;
  lab_required: boolean;
}

/** POST /admin/subjects - real master-data creation (see backend/app/routers/
 * master_data.py), same endpoint the standalone master-data admin UI will use
 * once built. Invalidates reference-lookup so every other real consumer of
 * the subjects list (not just the caller) picks up the new subject too. */
export function useCreateSubject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: SubjectCreateBody) => apiPost<SubjectOut>("/admin/subjects", body),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ["reference-lookup", variables.school_id] });
    },
  });
}

/** Real, ongoing management list - distinct from the onboarding wizard's
 * one-time creation flow. `GET /admin/subjects` (see master_data.py), used by
 * the School Management page's Subjects tab. */
export function useSubjectsAdmin(schoolId: number | undefined, includeInactive = false) {
  return useQuery({
    queryKey: ["admin-subjects", schoolId, includeInactive],
    queryFn: () => apiGet<SubjectOut[]>("/admin/subjects", { school_id: schoolId, include_inactive: includeInactive ? "true" : undefined }),
    enabled: schoolId !== undefined,
  });
}

function _invalidateSubject(queryClient: ReturnType<typeof useQueryClient>, schoolId: number) {
  queryClient.invalidateQueries({ queryKey: ["admin-subjects", schoolId] });
  queryClient.invalidateQueries({ queryKey: ["reference-lookup", schoolId] });
}

export function useUpdateSubject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      subjectId,
      schoolId,
      ...body
    }: {
      subjectId: number;
      schoolId: number;
      name?: string;
      code?: string;
      periods_per_week?: number;
      lab_required?: boolean;
    }) => apiPut<SubjectOut>(`/admin/subjects/${subjectId}`, body),
    onSuccess: (_result, variables) => _invalidateSubject(queryClient, variables.schoolId),
  });
}

export function useDeactivateSubject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ subjectId }: { subjectId: number; schoolId: number }) =>
      apiPut<SubjectOut>(`/admin/subjects/${subjectId}/deactivate`),
    onSuccess: (_result, variables) => _invalidateSubject(queryClient, variables.schoolId),
  });
}

export function useReactivateSubject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ subjectId }: { subjectId: number; schoolId: number }) =>
      apiPut<SubjectOut>(`/admin/subjects/${subjectId}/reactivate`),
    onSuccess: (_result, variables) => _invalidateSubject(queryClient, variables.schoolId),
  });
}

// --- SchoolClass -----------------------------------------------------------------

export interface ClassCreateBody {
  school_id: number;
  name: string;
  academic_year: string;
  grade_level?: number;
  grade_label?: string;
  section?: string;
  class_teacher_id: number;
  home_room_id?: number;
}

export interface ClassOut {
  id: number;
  name: string;
  academic_year: string;
  grade_level: number | null;
  grade_label: string | null;
  section: string | null;
  school_id: number;
  class_teacher_id: number | null;
  home_room_id: number | null;
  is_active: boolean;
}

export function useCreateClass() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: ClassCreateBody) => apiPost<ClassOut>("/admin/classes", body),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ["reference-lookup", variables.school_id] });
    },
  });
}

export interface ClassWithCountsOut extends ClassOut {
  student_count: number;
}

/** Real, ongoing management list - GET /admin/classes, used by the School
 * Management page's Classes tab. Student counts are computed client-side from
 * the same reference-lookup students list already fetched for the page,
 * see SchoolManagementPage.tsx - not a new backend aggregate. */
export function useClassesAdmin(schoolId: number | undefined, includeInactive = false) {
  return useQuery({
    queryKey: ["admin-classes", schoolId, includeInactive],
    queryFn: () => apiGet<ClassOut[]>("/admin/classes", { school_id: schoolId, include_inactive: includeInactive ? "true" : undefined }),
    enabled: schoolId !== undefined,
  });
}

function _invalidateClass(queryClient: ReturnType<typeof useQueryClient>, schoolId: number) {
  queryClient.invalidateQueries({ queryKey: ["admin-classes", schoolId] });
  queryClient.invalidateQueries({ queryKey: ["reference-lookup", schoolId] });
}

export function useUpdateClass() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      classId,
      schoolId,
      ...body
    }: {
      classId: number;
      schoolId: number;
      name?: string;
      academic_year?: string;
      grade_level?: number;
      grade_label?: string;
      section?: string;
      class_teacher_id?: number;
      home_room_id?: number;
    }) => apiPut<ClassOut>(`/admin/classes/${classId}`, body),
    onSuccess: (_result, variables) => _invalidateClass(queryClient, variables.schoolId),
  });
}

export function useDeactivateClass() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ classId }: { classId: number; schoolId: number }) => apiPut<ClassOut>(`/admin/classes/${classId}/deactivate`),
    onSuccess: (_result, variables) => _invalidateClass(queryClient, variables.schoolId),
  });
}

export function useReactivateClass() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ classId }: { classId: number; schoolId: number }) => apiPut<ClassOut>(`/admin/classes/${classId}/reactivate`),
    onSuccess: (_result, variables) => _invalidateClass(queryClient, variables.schoolId),
  });
}

// --- Room ------------------------------------------------------------------------

export interface RoomCreateBody {
  school_id: number;
  name: string;
  capacity: number;
  room_type?: string;
}

export interface RoomOut {
  id: number;
  name: string;
  capacity: number;
  room_type: string;
  school_id: number;
  is_active: boolean;
}

export function useCreateRoom() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: RoomCreateBody) => apiPost<RoomOut>("/admin/rooms", body),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ["reference-lookup", variables.school_id] });
    },
  });
}

/** Real, ongoing management list - GET /admin/rooms, used by the School
 * Management page's Rooms tab. */
export function useRoomsAdmin(schoolId: number | undefined, includeInactive = false) {
  return useQuery({
    queryKey: ["admin-rooms", schoolId, includeInactive],
    queryFn: () => apiGet<RoomOut[]>("/admin/rooms", { school_id: schoolId, include_inactive: includeInactive ? "true" : undefined }),
    enabled: schoolId !== undefined,
  });
}

function _invalidateRoom(queryClient: ReturnType<typeof useQueryClient>, schoolId: number) {
  queryClient.invalidateQueries({ queryKey: ["admin-rooms", schoolId] });
  queryClient.invalidateQueries({ queryKey: ["reference-lookup", schoolId] });
}

export function useUpdateRoom() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ roomId, schoolId, ...body }: { roomId: number; schoolId: number; name?: string; capacity?: number; room_type?: string }) =>
      apiPut<RoomOut>(`/admin/rooms/${roomId}`, body),
    onSuccess: (_result, variables) => _invalidateRoom(queryClient, variables.schoolId),
  });
}

export function useDeactivateRoom() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ roomId }: { roomId: number; schoolId: number }) => apiPut<RoomOut>(`/admin/rooms/${roomId}/deactivate`),
    onSuccess: (_result, variables) => _invalidateRoom(queryClient, variables.schoolId),
  });
}

export function useReactivateRoom() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ roomId }: { roomId: number; schoolId: number }) => apiPut<RoomOut>(`/admin/rooms/${roomId}/reactivate`),
    onSuccess: (_result, variables) => _invalidateRoom(queryClient, variables.schoolId),
  });
}

// --- Teacher (compound: real Supabase Auth account + profile + qualifications) -----

export interface TeacherCreateBody {
  school_id: number;
  email: string;
  password: string;
  full_name?: string;
  max_periods_per_week?: number;
  subject_ids?: number[];
}

export interface TeacherUnavailabilityOut {
  id: number;
  day_of_week: number;
  period_number: number;
  academic_year: string;
}

export interface TeacherOut {
  id: number;
  email: string;
  full_name: string | null;
  school_id: number | null;
  is_active: boolean;
  max_periods_per_week: number;
  subject_ids: number[];
  unavailability: TeacherUnavailabilityOut[];
}

export function useCreateTeacher() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: TeacherCreateBody) => apiPost<TeacherOut>("/admin/teachers", body),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ["reference-lookup", variables.school_id] });
    },
  });
}

/** Real, ongoing management list - GET /admin/teachers (see teachers.py, which
 * already had the full create/list/get/update/deactivate/reactivate +
 * subject/unavailability sub-resource shape before this page was built).
 * Used by the School Management page's Teachers tab. */
export function useTeachersAdmin(schoolId: number | undefined, includeInactive = false) {
  return useQuery({
    queryKey: ["admin-teachers", schoolId, includeInactive],
    queryFn: () => apiGet<TeacherOut[]>("/admin/teachers", { school_id: schoolId, include_inactive: includeInactive ? "true" : undefined }),
    enabled: schoolId !== undefined,
  });
}

function _invalidateTeacher(queryClient: ReturnType<typeof useQueryClient>, schoolId: number) {
  queryClient.invalidateQueries({ queryKey: ["admin-teachers", schoolId] });
  queryClient.invalidateQueries({ queryKey: ["reference-lookup", schoolId] });
}

export function useUpdateTeacher() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ teacherId, schoolId, ...body }: { teacherId: number; schoolId: number; full_name?: string; max_periods_per_week?: number }) =>
      apiPut<TeacherOut>(`/admin/teachers/${teacherId}`, body),
    onSuccess: (_result, variables) => _invalidateTeacher(queryClient, variables.schoolId),
  });
}

export function useDeactivateTeacher() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ teacherId }: { teacherId: number; schoolId: number }) => apiPut<TeacherOut>(`/admin/teachers/${teacherId}/deactivate`),
    onSuccess: (_result, variables) => _invalidateTeacher(queryClient, variables.schoolId),
  });
}

export function useReactivateTeacher() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ teacherId }: { teacherId: number; schoolId: number }) => apiPut<TeacherOut>(`/admin/teachers/${teacherId}/reactivate`),
    onSuccess: (_result, variables) => _invalidateTeacher(queryClient, variables.schoolId),
  });
}

export function useAddTeacherSubject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ teacherId, subjectId }: { teacherId: number; subjectId: number; schoolId: number }) =>
      apiPost<TeacherOut>(`/admin/teachers/${teacherId}/subjects?subject_id=${subjectId}`),
    onSuccess: (_result, variables) => _invalidateTeacher(queryClient, variables.schoolId),
  });
}

export function useRemoveTeacherSubject() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ teacherId, subjectId }: { teacherId: number; subjectId: number; schoolId: number }) =>
      apiDelete<TeacherOut>(`/admin/teachers/${teacherId}/subjects/${subjectId}`),
    onSuccess: (_result, variables) => _invalidateTeacher(queryClient, variables.schoolId),
  });
}

export function useAddTeacherUnavailability() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      teacherId,
      schoolId: _schoolId,
      ...body
    }: {
      teacherId: number;
      schoolId: number;
      day_of_week: number;
      period_number: number;
      academic_year: string;
    }) => apiPost<TeacherOut>(`/admin/teachers/${teacherId}/unavailability`, body),
    onSuccess: (_result, variables) => _invalidateTeacher(queryClient, variables.schoolId),
  });
}

export function useRemoveTeacherUnavailability() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ teacherId, unavailabilityId }: { teacherId: number; unavailabilityId: number; schoolId: number }) =>
      apiDelete<TeacherOut>(`/admin/teachers/${teacherId}/unavailability/${unavailabilityId}`),
    onSuccess: (_result, variables) => _invalidateTeacher(queryClient, variables.schoolId),
  });
}

// --- Student (compound: real Supabase Auth account + optional immediate enrollment) -

export interface StudentCreateBody {
  school_id: number;
  email: string;
  password: string;
  full_name?: string;
  class_id?: number;
}

export interface StudentOut {
  id: number;
  email: string;
  full_name: string | null;
  school_id: number | null;
  is_active: boolean;
  class_id: number | null;
}

export function useCreateStudent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: StudentCreateBody) => apiPost<StudentOut>("/admin/students", body),
    onSuccess: (_result, variables) => {
      queryClient.invalidateQueries({ queryKey: ["reference-lookup", variables.school_id] });
    },
  });
}

/** Real, ongoing management list - GET /admin/students, new this session
 * (students.py previously only had CREATE). Used by the School Management
 * page's Students tab. */
export function useStudentsAdmin(schoolId: number | undefined, includeInactive = false) {
  return useQuery({
    queryKey: ["admin-students", schoolId, includeInactive],
    queryFn: () => apiGet<StudentOut[]>("/admin/students", { school_id: schoolId, include_inactive: includeInactive ? "true" : undefined }),
    enabled: schoolId !== undefined,
  });
}

function _invalidateStudent(queryClient: ReturnType<typeof useQueryClient>, schoolId: number) {
  queryClient.invalidateQueries({ queryKey: ["admin-students", schoolId] });
  queryClient.invalidateQueries({ queryKey: ["reference-lookup", schoolId] });
}

export function useUpdateStudent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ studentId, schoolId, ...body }: { studentId: number; schoolId: number; full_name?: string; class_id?: number }) =>
      apiPut<StudentOut>(`/admin/students/${studentId}`, body),
    onSuccess: (_result, variables) => _invalidateStudent(queryClient, variables.schoolId),
  });
}

export function useDeactivateStudent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ studentId }: { studentId: number; schoolId: number }) => apiPut<StudentOut>(`/admin/students/${studentId}/deactivate`),
    onSuccess: (_result, variables) => _invalidateStudent(queryClient, variables.schoolId),
  });
}

export function useReactivateStudent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ studentId }: { studentId: number; schoolId: number }) => apiPut<StudentOut>(`/admin/students/${studentId}/reactivate`),
    onSuccess: (_result, variables) => _invalidateStudent(queryClient, variables.schoolId),
  });
}

// --- Parent (compound: real Supabase Auth account + ParentStudent links) -----------

export interface ParentCreateBody {
  school_id: number;
  email: string;
  password: string;
  full_name?: string;
  phone?: string;
  student_ids?: number[];
}

export interface ParentOut {
  id: number;
  email: string;
  full_name: string | null;
  phone: string | null;
  school_id: number | null;
  is_active: boolean;
  student_ids: number[];
}

export function useCreateParent() {
  return useMutation({
    mutationFn: (body: ParentCreateBody) => apiPost<ParentOut>("/admin/parents", body),
  });
}

/** Real, ongoing management list - GET /admin/parents, new this session
 * (parents.py previously only had CREATE). Used by the School Management
 * page's Parents tab. */
export function useParentsAdmin(schoolId: number | undefined, includeInactive = false) {
  return useQuery({
    queryKey: ["admin-parents", schoolId, includeInactive],
    queryFn: () => apiGet<ParentOut[]>("/admin/parents", { school_id: schoolId, include_inactive: includeInactive ? "true" : undefined }),
    enabled: schoolId !== undefined,
  });
}

function _invalidateParent(queryClient: ReturnType<typeof useQueryClient>, schoolId: number) {
  queryClient.invalidateQueries({ queryKey: ["admin-parents", schoolId] });
}

export function useUpdateParent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ parentId, schoolId, ...body }: { parentId: number; schoolId: number; full_name?: string; phone?: string }) =>
      apiPut<ParentOut>(`/admin/parents/${parentId}`, body),
    onSuccess: (_result, variables) => _invalidateParent(queryClient, variables.schoolId),
  });
}

export function useDeactivateParent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ parentId }: { parentId: number; schoolId: number }) => apiPut<ParentOut>(`/admin/parents/${parentId}/deactivate`),
    onSuccess: (_result, variables) => _invalidateParent(queryClient, variables.schoolId),
  });
}

export function useReactivateParent() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ parentId }: { parentId: number; schoolId: number }) => apiPut<ParentOut>(`/admin/parents/${parentId}/reactivate`),
    onSuccess: (_result, variables) => _invalidateParent(queryClient, variables.schoolId),
  });
}

export function useAddParentChild() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ parentId, studentId }: { parentId: number; studentId: number; schoolId: number }) =>
      apiPost<ParentOut>(`/admin/parents/${parentId}/children?student_id=${studentId}`),
    onSuccess: (_result, variables) => _invalidateParent(queryClient, variables.schoolId),
  });
}

export function useRemoveParentChild() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ parentId, studentId }: { parentId: number; studentId: number; schoolId: number }) =>
      apiDelete<ParentOut>(`/admin/parents/${parentId}/children/${studentId}`),
    onSuccess: (_result, variables) => _invalidateParent(queryClient, variables.schoolId),
  });
}
