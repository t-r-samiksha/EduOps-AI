import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

interface FieldProps {
  label: string;
  children: ReactNode;
  className?: string;
  hint?: string;
}

/** Consistent label+control wrapper reused across every form in the app. */
export default function Field({ label, children, className, hint }: FieldProps) {
  return (
    <label className={cn("flex flex-col gap-1.5 text-xs font-medium text-ink-muted", className)}>
      {label}
      {children}
      {hint && <span className="text-[0.6875rem] font-normal text-ink-faint">{hint}</span>}
    </label>
  );
}
