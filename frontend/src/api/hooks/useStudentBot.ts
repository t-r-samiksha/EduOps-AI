import { useMutation } from "@tanstack/react-query";
import { apiPost } from "@/api/client";
import type { BotAskRequest, BotAskResponse } from "@/api/types";

/**
 * Ask any RAG bot, by endpoint.
 *
 * Generic from the start because ChatShell is shared: the Parent Bot is a config swap
 * (`/bots/parent/ask` plus a different scope field), not a second component and not a
 * second hook.
 *
 * A mutation, not a query, and deliberately NOT cached: each ask is stateless (the
 * backend carries no conversation context - see api-contract.md's note that
 * `conversation_id` was never built), and the transcript lives in ChatShell's own
 * state. Caching by query key would mean asking the same question twice silently
 * replayed the first answer instead of hitting the bot.
 */
export function useBotAsk(endpoint: string) {
  return useMutation({
    mutationFn: (body: BotAskRequest) => apiPost<BotAskResponse>(endpoint, body),
  });
}

export const STUDENT_BOT_ENDPOINT = "/bots/student/ask";

/** Student Doubt Bot - the endpoint-bound convenience wrapper. */
export function useStudentBot() {
  return useBotAsk(STUDENT_BOT_ENDPOINT);
}
