import { useState } from "react";
import { ChevronDown, Lightbulb, Users } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useTopDoubts } from "@/api/hooks/useTopDoubts";
import type { DoubtCluster } from "@/api/types";
import { cn } from "@/lib/utils";

/**
 * Top Doubts - what this teacher's students are collectively stuck on.
 *
 * The section badges are the point of the whole feature: two section names on one row
 * means the same confusion showed up in two different rooms, which is one thing to
 * re-teach rather than two unrelated question logs. Rendered prominently for that
 * reason, not as decoration.
 */

function ClusterRow({ cluster, rank }: { cluster: DoubtCluster; rank: number }) {
  const [open, setOpen] = useState(false);
  const panelId = `doubt-cluster-${rank}`;
  const crossSection = cluster.sections.length > 1;
  // Degraded mode (or a failed labelling call) leaves label null - fall back to the
  // first real question rather than rendering an empty heading.
  const heading = cluster.label ?? cluster.sample_questions[0] ?? "Recent question";

  return (
    <div className="rounded-xl border border-border bg-panel px-3.5 py-2.5">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={`${open ? "Hide" : "Show"} example questions for ${heading}`}
        className="flex w-full items-start gap-3 rounded text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-accent/10 font-mono text-xs font-semibold text-accent">
          {rank}
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className="font-display text-sm font-semibold text-ink">{heading}</span>
            {cluster.sections.map((section) => (
              <Badge key={section} variant={crossSection ? "accent" : "outline"}>
                {section}
              </Badge>
            ))}
          </span>
          {cluster.description && <span className="mt-1 block text-xs text-ink-muted">{cluster.description}</span>}
          <span className="mt-1 block text-xs text-ink-faint">
            {cluster.question_count} question{cluster.question_count === 1 ? "" : "s"} ·{" "}
            {cluster.distinct_student_count} student{cluster.distinct_student_count === 1 ? "" : "s"}
            {crossSection && " · asked in both sections"}
          </span>
        </span>
        <ChevronDown
          className={cn("mt-1 h-4 w-4 shrink-0 text-ink-faint transition-transform", open && "rotate-180")}
          aria-hidden="true"
        />
      </button>

      {open && (
        <ul id={panelId} className="mt-2 flex flex-col gap-1.5 border-t border-border pt-2">
          {cluster.sample_questions.map((question, index) => (
            <li key={index} className="text-xs italic leading-relaxed text-ink-muted">
              “{question}”
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function TopDoubtsWidget() {
  const { data, isLoading } = useTopDoubts();

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Top doubts this week</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-24 animate-pulse rounded-xl bg-elevated/60" />
        </CardContent>
      </Card>
    );
  }

  const groups = data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Lightbulb className="h-4 w-4 text-accent" aria-hidden="true" />
          Top doubts this week
        </CardTitle>
        <CardDescription>
          What your students are asking the Doubt Bot, grouped by concept across every section you teach.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {groups.length === 0 && (
          // Useful, not "No data" - it says what would make the panel fill up.
          <div className="flex flex-col items-center gap-1 py-6 text-center">
            <Users className="h-6 w-6 text-ink-muted" aria-hidden="true" />
            <p className="font-display text-sm font-medium text-ink">No questions from your classes yet</p>
            <p className="max-w-md text-xs text-ink-muted">
              This fills up once your students use the Doubt Bot. Upload notes for your class first — the bot only
              answers from material you've uploaded.
            </p>
          </div>
        )}

        {groups.map((group) => (
          <div key={`${group.grade_level}-${group.subject_id}`} className="flex flex-col gap-2">
            <p className="font-display text-xs font-semibold uppercase tracking-wide text-ink-muted">
              Grade {group.grade_level} · {group.subject_name}
            </p>
            {group.clusters.map((cluster, index) => (
              <ClusterRow key={index} cluster={cluster} rank={index + 1} />
            ))}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
