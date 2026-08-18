import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPut } from "@/api/client";
import type {
  Announcement,
  AnnouncementAckStatus,
  AnnouncementCreateRequest,
  AnnouncementCreateResult,
  AnnouncementFeed,
} from "@/api/types";

/** Posting an announcement dispatches notifications, so the bell is stale too.
 * Announcements are a source that routes through the existing notification path —
 * invalidating only the feed would leave the bell showing a lower count than reality. */
function invalidateAnnouncements(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["announcements-feed"] });
  queryClient.invalidateQueries({ queryKey: ["announcement-ack-status"] });
  queryClient.invalidateQueries({ queryKey: ["notifications"] });
  queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
}

/** The caller's own feed. Deliberately takes no user id — the backend derives the
 * audience from the token, so there is nothing here for a client to widen. */
export function useAnnouncementFeed(params?: { scope?: string }) {
  return useQuery({
    queryKey: ["announcements-feed", params?.scope ?? "all"],
    queryFn: () =>
      apiGet<AnnouncementFeed>("/announcements/feed", {
        scope_filter: params?.scope,
      }),
  });
}

export function useCreateAnnouncement() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AnnouncementCreateRequest) =>
      apiPost<AnnouncementCreateResult>("/announcements", body),
    onSuccess: () => invalidateAnnouncements(queryClient),
  });
}

export function useAcknowledgeAnnouncement() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (announcementId: number) =>
      apiPut<Announcement>(`/announcements/${announcementId}/acknowledge`, {}),
    onSuccess: () => invalidateAnnouncements(queryClient),
  });
}

/** Author / admin / principal only — "who else has read this" is not every
 * recipient's business, and the backend enforces that too. */
export function useAnnouncementAckStatus(announcementId: number | undefined) {
  return useQuery({
    queryKey: ["announcement-ack-status", announcementId],
    queryFn: () => apiGet<AnnouncementAckStatus>(`/announcements/${announcementId}/ack-status`),
    enabled: announcementId != null,
  });
}
