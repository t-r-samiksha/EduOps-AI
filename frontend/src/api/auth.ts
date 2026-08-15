import { supabase } from "@/api/supabaseClient";
import { apiPost } from "@/api/client";

export async function signInWithEmail(email: string, password: string) {
  const { data, error } = await supabase.auth.signInWithPassword({ email, password });
  if (error) throw error;
  return data;
}

export interface SignupBody {
  full_name: string;
  email: string;
  password: string;
  school_name: string;
}

export interface SignupResult {
  access_token: string;
  user_id: number;
  school_id: number;
  email: string;
  school_name: string;
}

/** POST /auth/signup is public/unauthenticated - creates a real Supabase Auth
 * account + School + User, all server-side. The response's access_token
 * proves a real session was mintable, but the frontend still establishes its
 * OWN client-side Supabase session via a real signInWithEmail call right
 * after (same mechanism the login page uses) - that's what populates
 * supabase.auth.getSession(), which every API call's auth header reads from. */
export async function signup(body: SignupBody): Promise<SignupResult> {
  return apiPost<SignupResult>("/auth/signup", body);
}

export async function signOut() {
  const { error } = await supabase.auth.signOut();
  if (error) throw error;
}
