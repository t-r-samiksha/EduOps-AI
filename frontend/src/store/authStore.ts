import { create } from "zustand";
import type { Session, User } from "@supabase/supabase-js";

export const ROLES = ["principal", "admin", "teacher", "student", "parent"] as const;
export type Role = (typeof ROLES)[number];

interface AuthState {
  session: Session | null;
  user: User | null;
  role: Role | null;
  isLoading: boolean;
  setSession: (session: Session | null) => void;
  setLoading: (isLoading: boolean) => void;
  clear: () => void;
}

function roleFromUser(user: User | null): Role | null {
  const claim = (user?.app_metadata?.role ?? user?.user_metadata?.role) as
    | Role
    | undefined;
  return claim && ROLES.includes(claim) ? claim : null;
}

export const useAuthStore = create<AuthState>((set) => ({
  session: null,
  user: null,
  role: null,
  isLoading: true,
  setSession: (session) =>
    set({
      session,
      user: session?.user ?? null,
      role: roleFromUser(session?.user ?? null),
    }),
  setLoading: (isLoading) => set({ isLoading }),
  clear: () => set({ session: null, user: null, role: null }),
}));
