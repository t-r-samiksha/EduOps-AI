import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPut, API_BASE_URL, authHeaders } from "@/api/client";
import type {
  Notification,
  NotificationPage,
  NotificationStreamSnapshot,
  UnreadCountResponse,
} from "@/api/types";

export function useNotifications(page = 1, read?: boolean, pageSize = 20) {
  return useQuery({
    queryKey: ["notifications", page, read],
    queryFn: () =>
      apiGet<NotificationPage>("/notifications", {
        page,
        page_size: pageSize,
        read: read === undefined ? undefined : String(read),
      }),
  });
}

export function useUnreadCount() {
  return useQuery({
    queryKey: ["notifications-unread-count"],
    queryFn: () => apiGet<UnreadCountResponse>("/notifications/unread-count"),
  });
}

function useInvalidateNotifications() {
  const queryClient = useQueryClient();
  return () => {
    queryClient.invalidateQueries({ queryKey: ["notifications"] });
    queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
  };
}

export function useMarkNotificationRead() {
  const invalidate = useInvalidateNotifications();
  return useMutation({
    mutationFn: (id: number) => apiPut<Notification>(`/notifications/${id}/read`),
    onSuccess: invalidate,
  });
}

export function useMarkAllNotificationsRead() {
  const invalidate = useInvalidateNotifications();
  return useMutation({
    mutationFn: () => apiPut<{ updated: number }>("/notifications/read-all"),
    onSuccess: invalidate,
  });
}

export function useAcknowledgeNotification() {
  const invalidate = useInvalidateNotifications();
  return useMutation({
    mutationFn: (id: number) => apiPut<Notification>(`/notifications/${id}/acknowledge`),
    onSuccess: invalidate,
  });
}

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30000;

/**
 * GET /notifications/stream is SSE, but the browser's native EventSource can't
 * attach an Authorization header (see api-contract.md's "Auth caveat"). This
 * reads the same text/event-stream response via fetch + a manual ReadableStream
 * reader instead, and writes each pushed snapshot straight into the react-query
 * cache so the bell updates live without client-side polling.
 *
 * Modelled on useAlertsLiveStream in useAlerts.ts, with one deliberate fix: that
 * hook has NO reconnection - it console.warn()s on error and dies silently, and
 * its `done` branch just breaks out of the loop. Either way the feed is gone
 * until the component remounts. A notification bell that silently stops after
 * the first backend restart is worse than no bell, so this one reconnects with
 * exponential backoff (1s -> 2s -> 4s -> 8s, capped at 30s), resets the backoff
 * as soon as a message arrives, and treats a clean server-side close (`done`)
 * as a reconnect trigger too - that's the COMMON case during a dev restart, not
 * an error.
 */
export function useNotificationStream(enabled: boolean) {
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return;

    const controller = new AbortController();
    let cancelled = false;
    let backoff = INITIAL_BACKOFF_MS;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    function scheduleReconnect() {
      if (cancelled) return;
      retryTimer = setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
    }

    async function connect() {
      if (cancelled) return;
      try {
        const headers = await authHeaders();
        const res = await fetch(`${API_BASE_URL}/notifications/stream`, {
          headers,
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          scheduleReconnect();
          return;
        }

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
              const snapshot: NotificationStreamSnapshot = JSON.parse(line.slice("data: ".length));
              // A message arrived, so the connection is healthy again - reset
              // the backoff or a long outage would leave us at 30s intervals
              // forever after recovery.
              backoff = INITIAL_BACKOFF_MS;
              queryClient.setQueryData<UnreadCountResponse>(["notifications-unread-count"], {
                count: snapshot.unread_count,
              });
              queryClient.setQueryData<NotificationPage>(["notifications", 1, undefined], (prev) => ({
                items: snapshot.latest,
                total: prev?.total ?? snapshot.latest.length,
                page: 1,
                page_size: prev?.page_size ?? 20,
              }));
            } catch {
              // skip malformed chunk
            }
          }
        }
        // Fell out of the loop without an exception: the server closed the
        // stream cleanly (a backend restart, a proxy timeout). Reconnect -
        // unless we're unmounting.
        if (!cancelled) scheduleReconnect();
      } catch (err) {
        if (controller.signal.aborted || cancelled) return;
        console.warn("Notification stream disconnected, retrying", err);
        scheduleReconnect();
      }
    }

    connect();
    return () => {
      cancelled = true;
      if (retryTimer !== undefined) clearTimeout(retryTimer);
      controller.abort();
    };
  }, [enabled, queryClient]);
}
