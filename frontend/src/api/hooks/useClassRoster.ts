import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";

export interface ClassRosterStudent {
  id: number;
  name: string;
  /** False for a secondary/elective enrollment rather than the student's home section. */
  is_primary: boolean;
}

export interface ClassRoster {
  class_id: number;
  class_name: string;
  students: ClassRosterStudent[];
}

/**
 * The roster of one class section - names only, no gradebook computation.
 *
 * Deliberately not `useClassGradebook`, which several pages were using purely to get a
 * list of student names: that endpoint computes a full weighted term average and GPA for
 * every student on the roster, which is a lot of work to fill a dropdown.
 */
export function useClassRoster(classId?: number) {
  return useQuery<ClassRoster>({
    queryKey: ["class-roster", classId],
    queryFn: () => apiGet<ClassRoster>(`/reference/class/${classId}/students`),
    enabled: typeof classId === "number" && !Number.isNaN(classId),
  });
}
