import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { GraduationCap } from "lucide-react";
import { signup, signInWithEmail } from "@/api/auth";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import Field from "@/components/ui/field";

export default function Signup() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [schoolName, setSchoolName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await signup({ full_name: fullName, email, password, school_name: schoolName });
      // Real server-side account creation is done - establish our own
      // client-side Supabase session the same way the login page does, so
      // there's no separate "now log in" step from the user's perspective.
      await signInWithEmail(email, password);
      // Straight into the real onboarding wizard - no dashboard stop first,
      // closing the gap flagged after the previous session's signup proof.
      navigate("/onboarding");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : "Sign up failed");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4 py-8">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-3xl border border-border bg-card p-6 shadow-elevated"
      >
        <div className="mb-5 flex items-center gap-3">
          <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-foreground shadow-sm">
            <GraduationCap className="h-5 w-5" />
          </div>
          <div>
            <span className="font-display text-lg font-bold tracking-tight text-ink">EduOps</span>
            <span className="ml-1 font-mono text-xs tracking-widest text-accent">AI</span>
          </div>
        </div>
        <h1 className="mb-1 font-display text-xl font-bold text-ink">Set up your school</h1>
        <p className="mb-5 text-sm text-ink-muted">
          Creates a real admin account and a new school - no seed data, nothing to configure first.
        </p>
        <div className="flex flex-col gap-3">
          <Field label="Your name">
            <Input id="full_name" type="text" required value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="School name">
            <Input id="school_name" type="text" required value={schoolName} onChange={(e) => setSchoolName(e.target.value)} />
          </Field>
          <Field label="Email">
            <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password" hint="At least 8 characters">
            <Input
              id="password"
              type="password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </Field>
          {error && <p className="text-sm text-urgent">{error}</p>}
          <Button type="submit" className="mt-2 w-full" disabled={isSubmitting}>
            {isSubmitting ? "Creating your school…" : "Create school & sign in"}
          </Button>
          <p className="text-center text-xs text-ink-muted">
            Already have an account?{" "}
            <Link to="/login" className="font-medium text-accent hover:underline">
              Sign in
            </Link>
          </p>
        </div>
      </form>
    </div>
  );
}
