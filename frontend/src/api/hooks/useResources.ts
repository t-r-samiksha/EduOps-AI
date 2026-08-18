import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPostForm } from "@/api/client";
import type {
  ResourceFilters,
  ResourceListResponse,
  ResourceUploadResponse,
  UnitsListResponse,
} from "@/api/types";

export function useResources(filters: ResourceFilters = {}) {
  return useQuery({
    queryKey: ["resources", filters],
    queryFn: () =>
      apiGet<ResourceListResponse>("/resources", {
        class_id: filters.class_id,
        grade_level: filters.grade_level,
        subject_id: filters.subject_id,
        unit: filters.unit,
        file_type: filters.file_type,
        q: filters.q,
      }),
  });
}

export function useClassResources(classId?: number, filters: Omit<ResourceFilters, "class_id"> = {}) {
  return useQuery({
    queryKey: ["class-resources", classId, filters],
    queryFn: () =>
      apiGet<ResourceListResponse>(`/resources/${classId}`, {
        subject_id: filters.subject_id,
        unit: filters.unit,
        file_type: filters.file_type,
        q: filters.q,
      }),
    enabled: typeof classId === "number" && !isNaN(classId),
  });
}

export function useResourceUnits(classId?: number, subjectId?: number) {
  return useQuery({
    queryKey: ["resource-units", classId, subjectId],
    queryFn: () =>
      apiGet<UnitsListResponse>("/resources/units", {
        class_id: classId,
        subject_id: subjectId,
      }),
  });
}

export interface UploadResourceInput {
  file: File;
  title: string;
  description?: string;
  unit?: string;
  class_id?: number;
  grade_level?: number;
  subject_id?: number;
}

export function useUploadResource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: UploadResourceInput) => {
      const form = new FormData();
      form.append("file", input.file);
      form.append("title", input.title);
      if (input.description) form.append("description", input.description);
      if (input.unit) form.append("unit", input.unit);
      if (input.class_id) form.append("class_id", String(input.class_id));
      if (input.grade_level) form.append("grade_level", String(input.grade_level));
      if (input.subject_id) form.append("subject_id", String(input.subject_id));

      return apiPostForm<ResourceUploadResponse>("/resources/upload", form);
    },
    onSuccess: (_, input) => {
      queryClient.invalidateQueries({ queryKey: ["resources"] });
      if (input.class_id) {
        queryClient.invalidateQueries({ queryKey: ["class-resources", input.class_id] });
      }
      queryClient.invalidateQueries({ queryKey: ["resource-units"] });
    },
  });
}

export function useDeleteResource() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (resourceId: number) => apiDelete<void>(`/resources/${resourceId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["resources"] });
      queryClient.invalidateQueries({ queryKey: ["class-resources"] });
      queryClient.invalidateQueries({ queryKey: ["resource-units"] });
    },
  });
}
