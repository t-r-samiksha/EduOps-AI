import { useMutation } from "@tanstack/react-query";
import { apiPost } from "@/api/client";
import type { BotAskResponse, ParentBotAskRequest, StudentBotAskRequest } from "@/api/types";

/**
 * Ask a RAG bot, by endpoint.
 *
 * GENERIC IN THE REQUEST TYPE, not just the endpoint. `useBotAsk<StudentBotAskRequest>`
 * and `useBotAsk<ParentBotAskRequest>` are separately type-checked, which is what
 * removed the `as never` cast ChatShell previously needed - that cast silently
 * disabled type-checking on the request body for BOTH bots.
 *
 * A mutation, not a query, and deliberately NOT cached: each ask is stateless (the
 * backend carries no conversation context - see api-contract.md's note that
 * `conversation_id` was never built), and the transcript lives in ChatShell's own
 * state. Caching by query key would mean asking the same question twice silently
 * replayed the first answer instead of hitting the bot.
 */
export function useBotAsk<TRequest extends { query: string }>(endpoint: string) {
  return useMutation({
    mutationFn: (body: TRequest) => apiPost<BotAskResponse>(endpoint, body),
  });
}

export const STUDENT_BOT_ENDPOINT = "/bots/student/ask";
export const PARENT_BOT_ENDPOINT = "/bots/parent/ask";

/** Student Doubt Bot - endpoint- and type-bound. */
export function useStudentBot() {
  return useBotAsk<StudentBotAskRequest>(STUDENT_BOT_ENDPOINT);
}

/** Parent Assistant Bot - same shell, different scope field. */
export function useParentBot() {
  return useBotAsk<ParentBotAskRequest>(PARENT_BOT_ENDPOINT);
}
