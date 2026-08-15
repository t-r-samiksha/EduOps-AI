import { useQuery } from "@tanstack/react-query";
import { apiGet } from "@/api/client";

export interface CurrentUserInfo {
  sub: string;
  email: string | null;
  role: string | null;
  user_id: number;
  school_id: number | null;
}

/** GET /auth/me - the only real way to know which school the logged-in admin
 * manages (school_id isn't derivable client-side from the Supabase JWT, which
 * only carries the role claim). Used by the onboarding wizard right after
 * signup, and by anything else that needs "my own school_id" going forward. */
export function useCurrentUser() {
  return useQuery({
    queryKey: ["current-user"],
    queryFn: () => apiGet<CurrentUserInfo>("/auth/me"),
    staleTime: 5 * 60_000,
  });
}
