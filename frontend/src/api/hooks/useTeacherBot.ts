import { useMutation } from "@tanstack/react-query";
import { apiPost } from "@/api/client";
import type { Citation } from "@/api/types";

export const TEACHER_BOT_ENDPOINT = "/bots/teacher/ask";

export interface TeacherAskRequest {
  query: string;
  grade_level?: number;
  subject_id?: number;
  class_id?: number;
  mode?: string;
}

export interface TeacherAskResponse {
  answer: string;
  citations: Citation[];
  mode?: string;
}

/**
 * Ask Teacher Assistant Bot hook.
 *
 * Supports lesson planning, quiz/MCQ generation, performance summaries,
 * and curriculum Q&A grounded in uploaded class notes.
 */
export function useTeacherBot() {
  return useMutation({
    mutationFn: (body: TeacherAskRequest) =>
      apiPost<TeacherAskResponse>(TEACHER_BOT_ENDPOINT, body),
  });
}
