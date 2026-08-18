import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiDelete, apiGet, apiPost, apiPostForm } from "@/api/client";
import type {
  Classroom,
  CreatePostRequest,
  PostType,
  StreamPost,
  StreamResponse,
  UploadAttachmentResponse,
} from "@/api/types";

export function useMyClassrooms() {
  return useQuery({
    queryKey: ["my-classrooms"],
    queryFn: () => apiGet<Classroom[]>("/classroom/my-classrooms"),
  });
}

export function useClassroom(classroomId?: number) {
  return useQuery({
    queryKey: ["classroom", classroomId],
    queryFn: () => apiGet<Classroom>(`/classroom/${classroomId}`),
    enabled: typeof classroomId === "number" && !isNaN(classroomId),
  });
}

export function useClassroomStream(classroomId?: number, postType?: PostType | "all") {
  return useQuery({
    queryKey: ["classroom-stream", classroomId, postType],
    queryFn: () => {
      const params = postType && postType !== "all" ? { post_type: postType } : undefined;
      return apiGet<StreamResponse>(`/classroom/${classroomId}/stream`, params);
    },
    enabled: typeof classroomId === "number" && !isNaN(classroomId),
  });
}

export function useCreatePost(classroomId?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CreatePostRequest) =>
      apiPost<StreamPost>(`/classroom/${classroomId}/post`, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classroom-stream", classroomId] });
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
    },
  });
}

export function useDeletePost(classroomId?: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (postId: number) =>
      apiDelete<void>(`/classroom/${classroomId}/post/${postId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["classroom-stream", classroomId] });
    },
  });
}

export function useUploadAttachment(classroomId?: number) {
  return useMutation({
    mutationFn: async (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return apiPostForm<UploadAttachmentResponse>(`/classroom/${classroomId}/upload`, formData);
    },
  });
}

export function useCreateClassroom() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { class_id: number; subject_id: number; teacher_id?: number }) =>
      apiPost<Classroom>("/classroom", body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["my-classrooms"] });
    },
  });
}
