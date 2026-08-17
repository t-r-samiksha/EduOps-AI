import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPut } from "@/api/client";
import type {
  DoubtThread,
  DoubtThreadDetail,
  ThreadReply,
  ThreadVerifyResult,
  ThreadUnverifyResult,
} from "@/api/types";

/** Everything a verify/unverify invalidates. The verified answer is ingested into the
 * bot's knowledge base, so the thread views AND anything reading the KB are stale. */
function invalidateThreads(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["doubt-threads"] });
  queryClient.invalidateQueries({ queryKey: ["doubt-thread"] });
  queryClient.invalidateQueries({ queryKey: ["notifications"] });
  queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
}

export function useDoubtThreads(params: { classId?: number; resolved?: boolean }) {
  return useQuery({
    queryKey: ["doubt-threads", params.classId, params.resolved],
    queryFn: () =>
      apiGet<{ items: DoubtThread[] }>("/threads", {
        class_id: params.classId,
        resolved: params.resolved === undefined ? undefined : String(params.resolved),
      }),
    enabled: params.classId != null,
  });
}

export function useDoubtThread(threadId: number | undefined) {
  return useQuery({
    queryKey: ["doubt-thread", threadId],
    queryFn: () => apiGet<DoubtThreadDetail>(`/threads/${threadId}`),
    enabled: threadId != null,
  });
}

export function useCreateDoubtThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: { class_id: number; subject_id?: number; title: string; body: string }) =>
      apiPost<DoubtThread>("/threads", body),
    onSuccess: () => invalidateThreads(queryClient),
  });
}

export function useReplyToThread() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ threadId, body }: { threadId: number; body: string }) =>
      apiPost<ThreadReply>(`/threads/${threadId}/reply`, { body }),
    onSuccess: () => invalidateThreads(queryClient),
  });
}

/** Certifies a reply AND ingests it into the bot's knowledge base — a ~1s embedding
 * round-trip happens inside this request, which is why the UI needs a real pending
 * state rather than an optimistic flip. */
export function useVerifyReply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ threadId, replyId }: { threadId: number; replyId: number }) =>
      apiPut<ThreadVerifyResult>(`/threads/${threadId}/verify/${replyId}`),
    onSuccess: () => invalidateThreads(queryClient),
  });
}

export function useUnverifyReply() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (threadId: number) => apiPut<ThreadUnverifyResult>(`/threads/${threadId}/unverify`),
    onSuccess: () => invalidateThreads(queryClient),
  });
}
