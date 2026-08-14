import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";
import type { LinkedChild } from "@/api/types";

export function useParentChildren() {
  return useQuery({
    queryKey: ["parent-children"],
    queryFn: () => apiGet<{ items: LinkedChild[] }>("/parent/children"),
  });
}
