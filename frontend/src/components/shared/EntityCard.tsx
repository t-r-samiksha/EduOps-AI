import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type Tone = "urgent" | "positive" | "accent" | "warning" | "neutral";

const TONE_BORDER: Record<Tone, string> = {
  urgent: "border-urgent",
  positive: "border-positive",
  accent: "border-accent",
  warning: "border-warning",
  neutral: "border-border",
};

const TONE_CHIP: Record<Tone, string> = {
  urgent: "bg-urgent/10 text-urgent",
  positive: "bg-positive/10 text-positive",
  accent: "bg-accent/10 text-accent",
  warning: "bg-warning/10 text-warning",
  neutral: "bg-elevated text-ink-muted",
};

interface EntityCardProps {
  icon: LucideIcon;
  tone?: Tone;
  title: ReactNode;
  badges?: ReactNode;
  message?: ReactNode;
  meta?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}

/** The shared alert/approval/risk-flag row shape — one visual language reused
 * across the Command Center, Approvals inbox, and Risk dashboard. */
export default function EntityCard({ icon: Icon, tone = "neutral", title, badges, message, meta, actions, children }: EntityCardProps) {
  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-2xl border-l-4 border-y border-r border-border bg-card px-4 py-3 shadow-elevated transition-shadow hover:shadow-floating",
        TONE_BORDER[tone]
      )}
    >
      <div className={cn("mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", TONE_CHIP[tone])}>
        <Icon className="h-4 w-4" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-sm font-semibold text-ink">{title}</span>
          {badges}
        </div>
        {message && <div className="mt-0.5 text-sm text-ink-muted">{message}</div>}
        {meta && <p className="mt-1 font-mono text-[0.6875rem] text-ink-faint">{meta}</p>}
        {children}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}
