import { Link } from "react-router-dom";
import type { LucideIcon } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";

interface QuickLinkCardProps {
  to: string;
  icon: LucideIcon;
  label: string;
  stat: string;
}

/** A navigation entry point into a real screen, with one real stat — not a
 * generic placeholder tile. Composed from Card, not a new primitive. */
export default function QuickLinkCard({ to, icon: Icon, label, stat }: QuickLinkCardProps) {
  return (
    <Link to={to} className="block rounded-2xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
      <Card className="transition-shadow hover:shadow-floating">
        <CardContent className="flex items-center gap-3 p-4">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
            <Icon className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-sm font-semibold text-ink">{label}</div>
            <div className="truncate text-xs text-ink-muted">{stat}</div>
          </div>
        </CardContent>
      </Card>
    </Link>
  );
}
