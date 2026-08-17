import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import type { ChildSummary } from "@/api/types";

/**
 * The parent portal's single call. One round trip fills every card on the page -
 * attendance, risk, remarks, fees - because four sequential requests from a phone on
 * venue wifi is a visibly slow screen.
 *
 * Keyed by student id so switching child is a cache hit on the way back, which makes
 * the selector feel instant after the first look at each child.
 */
export function useChildSummary(studentId: number | undefined) {
  return useQuery({
    queryKey: ["child-summary", studentId],
    queryFn: () => apiGet<ChildSummary>(`/parent/child/${studentId}/summary`),
    enabled: studentId !== undefined,
  });
}
