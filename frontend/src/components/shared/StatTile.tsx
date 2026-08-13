import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";

type Tone = "urgent" | "positive" | "accent" | "warning" | "neutral";

const TONE_TEXT: Record<Tone, string> = {
  urgent: "text-urgent",
  positive: "text-positive",
  accent: "text-accent",
  warning: "text-warning",
  neutral: "text-ink",
};

const TONE_CHIP: Record<Tone, string> = {
  urgent: "bg-urgent/10 text-urgent",
  positive: "bg-positive/10 text-positive",
  accent: "bg-accent/10 text-accent",
  warning: "bg-warning/10 text-warning",
  neutral: "bg-elevated text-ink-muted",
};

const TONE_SOLID: Record<Tone, string> = {
  urgent: "bg-urgent text-urgent-foreground",
  positive: "bg-positive text-positive-foreground",
  accent: "bg-accent text-accent-foreground",
  warning: "bg-warning text-warning-foreground",
  neutral: "bg-elevated text-ink",
};

interface StatTileProps {
  label: string;
  value: string | number;
  caption?: string;
  icon?: LucideIcon;
  tone?: Tone;
  /** Solid-fill "highlighted" treatment for the one stat that most needs attention. */
  emphasize?: boolean;
}

export default function StatTile({ label, value, caption, icon: Icon, tone = "neutral", emphasize = false }: StatTileProps) {
  return (
    <div
      className={cn(
        "relative flex flex-1 items-start justify-between gap-3 overflow-hidden rounded-2xl border px-4 py-3.5",
        emphasize ? cn(TONE_SOLID[tone], "border-transparent shadow-floating") : "border-border bg-card shadow-elevated"
      )}
    >
      {Icon && emphasize && (
        <Icon className="pointer-events-none absolute -bottom-3 -right-3 h-20 w-20 opacity-15" aria-hidden="true" />
      )}
      <div className="relative flex flex-col gap-0.5">
        <span className={cn("text-xs font-medium uppercase tracking-wide", emphasize ? "opacity-80" : "text-ink-muted")}>
          {label}
        </span>
        <span className={cn("font-display text-2xl font-bold tabular-nums", !emphasize && TONE_TEXT[tone])}>{value}</span>
        {caption && <span className={cn("text-xs", emphasize ? "opacity-80" : "text-ink-muted")}>{caption}</span>}
      </div>
      {Icon && !emphasize && (
        <div className={cn("relative flex h-9 w-9 shrink-0 items-center justify-center rounded-lg", TONE_CHIP[tone])}>
          <Icon className="h-4 w-4" />
        </div>
      )}
    </div>
  );
}
