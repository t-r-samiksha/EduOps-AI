import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import type { LinkedChild } from "@/api/types";

export function useParentChildren(options?: { enabled?: boolean }) {
  return useQuery({
    queryKey: ["parent-children"],
    queryFn: () => apiGet<{ items: LinkedChild[] }>("/parent/children"),
    // The endpoint is require_role("parent"), so callers on shared multi-role pages pass
    // `enabled: role === "parent"` rather than firing a certain 403. Defaults to true so
    // the parent-only screens that already call this are unaffected.
    enabled: options?.enabled ?? true,
  });
}
