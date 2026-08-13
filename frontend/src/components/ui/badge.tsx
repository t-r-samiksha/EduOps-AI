import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        neutral: "bg-elevated text-ink-muted",
        strong: "bg-accent text-accent-foreground",
        accent: "bg-accent/10 text-accent",
        urgent: "bg-urgent/10 text-urgent",
        positive: "bg-positive/10 text-positive",
        warning: "bg-warning/10 text-warning",
        outline: "border border-border bg-transparent text-ink-muted",
      },
    },
    defaultVariants: { variant: "neutral" },
  }
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
