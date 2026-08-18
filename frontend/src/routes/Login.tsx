import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import {
  BookOpen,
  Building2,
  GraduationCap,
  Presentation,
  ShieldCheck,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { signInWithEmail } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import Field from "@/components/ui/field";

/** Shared password for every seeded Shikshaa account - see
 * `backend/scripts/seed_shikshaa.py`'s PASSWORD constant. Correct for a throwaway
 * demo school (any role can be signed into on camera without a password manager),
 * and wrong for anything else. */
const DEMO_PASSWORD = "1234567890";

interface DemoAccount {
  role: string;
  name: string;
  email: string;
  icon: LucideIcon;
  /** Why a judge would pick this account over the others in the same role. */
  note: string;
}

/** One account per role, picked so each lands on a fully populated dashboard.
 * The seed creates many more (t1..t8, s1..s30, p1..p6) - all on DEMO_PASSWORD. */
const DEMO_ACCOUNTS: DemoAccount[] = [
  {
    role: "Principal",
    name: "Lakshmi Subramanian",
    email: "principal@shikshaa.in",
    icon: ShieldCheck,
    note: "School-wide analytics, approvals, audit log",
  },
  {
    role: "Office Admin",
    name: "Ravi Shankar",
    email: "admin@shikshaa.in",
    icon: Building2,
    note: "Documents, fees, admissions",
  },
  {
    role: "Teacher",
    name: "Anjali Menon",
    email: "t1@shikshaa.in",
    icon: Presentation,
    note: "Homeroom class, attendance, gradebook",
  },
  {
    role: "Student",
    name: "Aditi Rao",
    email: "s1@shikshaa.in",
    icon: BookOpen,
    note: "Grade 1-A · classroom, doubt bot",
  },
  {
    role: "Parent",
    name: "Prakash Sharma",
    email: "p6@shikshaa.in",
    icon: Users,
    // The one guardian seeded with children in two different grades, which is what
    // makes the child selector and grade-scoped announcements demonstrable.
    note: "Two children, different grades",
  },
];

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  /** Email of the demo account currently signing in, so only its own chip shows
   * the pending state instead of all five. */
  const [pendingDemo, setPendingDemo] = useState<string | null>(null);
  const navigate = useNavigate();

  async function signIn(emailValue: string, passwordValue: string) {
    setError(null);
    setIsSubmitting(true);
    try {
      await signInWithEmail(emailValue, passwordValue);
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setIsSubmitting(false);
      setPendingDemo(null);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    await signIn(email, password);
  }

  /** Fill the visible fields *and* sign in, so a judge gets one click per role -
   * and still sees which credentials were used if it fails. */
  async function handleDemoSignIn(account: DemoAccount) {
    setEmail(account.email);
    setPassword(DEMO_PASSWORD);
    setPendingDemo(account.email);
    await signIn(account.email, DEMO_PASSWORD);
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-paper px-4 py-10">
      <div className="w-full max-w-md">
        <form
          onSubmit={handleSubmit}
          className="rounded-3xl border border-border bg-card p-6 shadow-elevated"
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
          <h1 className="mb-1 font-display text-xl font-bold text-ink">Sign in</h1>
          <p className="mb-5 text-sm text-ink-muted">School operations, unified in one place.</p>
          <div className="flex flex-col gap-3">
            <Field label="Email">
              <Input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Password">
              <Input id="password" type="password" required value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            {error && <p className="text-sm text-urgent">{error}</p>}
            <Button type="submit" className="mt-2 w-full" disabled={isSubmitting}>
              {isSubmitting && !pendingDemo ? "Signing in…" : "Sign in"}
            </Button>
            <p className="text-center text-xs text-ink-muted">
              New school?{" "}
              <Link to="/signup" className="font-medium text-accent hover:underline">
                Sign up
              </Link>
            </p>
          </div>
        </form>

        <section className="mt-4 rounded-3xl border border-dashed border-border bg-panel p-5">
          <div className="mb-1 flex items-baseline justify-between gap-2">
            <h2 className="font-display text-sm font-bold text-ink">Demo accounts</h2>
            <span className="font-mono text-[0.6875rem] uppercase tracking-widest text-accent">
              Shikshaa Public School
            </span>
          </div>
          <p className="mb-4 text-xs text-ink-muted">
            Click any role to sign straight in — every screen is populated with real seeded data.
          </p>

          <ul className="flex flex-col gap-2">
            {DEMO_ACCOUNTS.map((account) => {
              const Icon = account.icon;
              const isPending = pendingDemo === account.email;
              return (
                <li key={account.email}>
                  <button
                    type="button"
                    onClick={() => handleDemoSignIn(account)}
                    disabled={isSubmitting}
                    className="group flex w-full items-center gap-3 rounded-xl border border-border bg-card px-3 py-2.5 text-left transition-colors hover:border-accent disabled:pointer-events-none disabled:opacity-50"
                  >
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
                      <Icon className="h-4 w-4" />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex items-baseline gap-2">
                        <span className="text-sm font-medium text-ink group-hover:text-accent">
                          {account.role}
                        </span>
                        <span className="truncate text-xs text-ink-faint">{account.name}</span>
                      </span>
                      <span className="block truncate text-xs text-ink-muted">{account.note}</span>
                    </span>
                    <span className="shrink-0 font-mono text-[0.6875rem] text-ink-faint">
                      {isPending ? "signing in…" : account.email}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>

          <div className="mt-4 border-t border-border pt-3 text-xs text-ink-muted">
            <p>
              Password for every account:{" "}
              <code className="rounded bg-elevated px-1.5 py-0.5 font-mono text-ink">{DEMO_PASSWORD}</code>
            </p>
            <p className="mt-1.5 text-ink-faint">
              Also seeded: teachers <span className="font-mono">t1–t8</span>, students{" "}
              <span className="font-mono">s1–s30</span>, parents <span className="font-mono">p1–p6</span> —
              all <span className="font-mono">@shikshaa.in</span>.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
