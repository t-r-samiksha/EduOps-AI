import { useEffect, useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, API_BASE_URL, authHeaders } from "@/api/client";
import type { Alert, AlertsSummary } from "@/api/types";

export function useAlerts(severity?: "normal" | "urgent") {
  return useQuery({
    queryKey: ["admin-alerts", severity],
    queryFn: () => apiGet<{ items: Alert[] }>("/admin/alerts", { severity }),
  });
}

export function useAlertsSummary() {
  return useQuery({
    queryKey: ["admin-alerts-summary"],
    queryFn: () => apiGet<AlertsSummary>("/admin/alerts/summary"),
  });
}

export function useResolveAlert() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (alertId: string) => apiPost<{ id: string; resolved: boolean }>(`/admin/alerts/${alertId}/resolve`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
      queryClient.invalidateQueries({ queryKey: ["admin-alerts-summary"] });
    },
  });
}

/**
 * GET /admin/alerts/stream is SSE, but the browser's native EventSource can't attach
 * an Authorization header (see api-contract.md's "Auth caveat"). This reads the same
 * text/event-stream response via fetch + a manual ReadableStream reader instead, and
 * writes each pushed snapshot straight into the react-query cache so the feed and
 * summary widgets update live without polling from the client side.
 */
export function useAlertsLiveStream(enabled: boolean) {
  const queryClient = useQueryClient();
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    const controller = new AbortController();
    controllerRef.current = controller;

    async function connect() {
      const headers = await authHeaders();
      try {
        const res = await fetch(`${API_BASE_URL}/admin/alerts/stream`, {
          headers,
          signal: controller.signal,
        });
        if (!res.body) return;
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        while (!cancelled) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split("\n\n");
          buffer = events.pop() ?? "";
          for (const evt of events) {
            const line = evt.split("\n").find((l) => l.startsWith("data: "));
            if (!line) continue;
            try {
              const items: Alert[] = JSON.parse(line.slice("data: ".length));
              queryClient.setQueryData(["admin-alerts", undefined], { items });
              queryClient.setQueryData(["admin-alerts", "urgent"], {
                items: items.filter((a) => a.severity === "urgent"),
              });
              queryClient.setQueryData(["admin-alerts", "normal"], {
                items: items.filter((a) => a.severity === "normal"),
              });
              queryClient.setQueryData(["admin-alerts-summary"], {
                total: items.length,
                by_severity: items.reduce<Record<string, number>>((acc, a) => {
                  acc[a.severity] = (acc[a.severity] ?? 0) + 1;
                  return acc;
                }, {}),
                by_source: items.reduce<Record<string, number>>((acc, a) => {
                  acc[a.source] = (acc[a.source] ?? 0) + 1;
                  return acc;
                }, {}),
              });
            } catch {
              // skip malformed chunk
            }
          }
        }
      } catch (err) {
        if (!controller.signal.aborted) console.warn("Alert stream disconnected", err);
      }
    }

    connect();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [enabled, queryClient]);
}
