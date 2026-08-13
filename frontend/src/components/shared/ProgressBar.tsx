import { cn } from "@/lib/utils";

interface ProgressBarProps {
  /** 0..1 */
  value: number;
  /** 0..1, rendered as a thin marker line — e.g. "where we should be" */
  target?: number;
  tone?: "urgent" | "positive" | "accent" | "neutral";
  className?: string;
}

const TONE_FILL: Record<string, string> = {
  urgent: "bg-urgent",
  positive: "bg-positive",
  accent: "bg-accent",
  neutral: "bg-ink-muted",
};

export default function ProgressBar({ value, target, tone = "neutral", className }: ProgressBarProps) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className={cn("relative h-2 w-full overflow-hidden rounded-full bg-elevated", className)}>
      <div className={cn("h-full rounded-full transition-all", TONE_FILL[tone])} style={{ width: `${pct}%` }} />
      {target !== undefined && (
        <div
          className="absolute top-0 h-full w-0.5 bg-ink"
          style={{ left: `${Math.max(0, Math.min(1, target)) * 100}%` }}
          aria-hidden="true"
        />
      )}
    </div>
  );
}
