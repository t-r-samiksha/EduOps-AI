import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import type { MyTopDoubtsResponse } from "@/api/types";

/**
 * The teacher dashboard's Top Doubts feed.
 *
 * Clusters are computed LIVE on each call (no stored cluster table), and the
 * computation includes one Gemini labelling call, so this is deliberately given a
 * longer staleTime than the 30s global default - re-clustering on every dashboard
 * focus would spend tokens to produce the same answer.
 */
export function useTopDoubts(days = 7, limit = 5) {
  return useQuery({
    queryKey: ["top-doubts", days, limit],
    queryFn: () => apiGet<MyTopDoubtsResponse>("/bots/insights/my-top-doubts", { days, limit }),
    staleTime: 5 * 60_000,
  });
}
