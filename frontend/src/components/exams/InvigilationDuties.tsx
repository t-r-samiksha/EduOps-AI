import { ClipboardCheck } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import EntityCard from "@/components/shared/EntityCard";
import { useMyInvigilations } from "@/api/hooks/useExams";
import { ApiError } from "@/api/client";

/** Self-scoped invigilation duty list — GET /admin/exams/invigilations/me always
 * returns only the caller's own duties, so this is safe to reuse verbatim for
 * admin/principal/teacher (the "invigilator self-lookup" playbook item). */
export default function InvigilationDuties() {
  const duties = useMyInvigilations();

  if (duties.isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1].map((i) => (
          <div key={i} className="h-20 animate-pulse rounded-lg bg-elevated/60" />
        ))}
      </div>
    );
  }
  if (duties.error) {
    return (
      <Card>
        <CardContent className="py-6 text-sm text-urgent">
          {duties.error instanceof ApiError ? duties.error.message : "Failed to load invigilation duties."}
        </CardContent>
      </Card>
    );
  }
  const items = duties.data ?? [];
  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-1 py-8 text-center">
          <ClipboardCheck className="h-6 w-6 text-ink-muted" />
          <p className="font-display text-sm font-medium text-ink">No invigilation duties</p>
          <p className="text-xs text-ink-muted">Nothing assigned to you yet.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {items.map((d) => (
        <EntityCard
          key={`${d.exam_id}-${d.room_id}`}
          icon={ClipboardCheck}
          tone="accent"
          title={`${d.subject_name} · ${d.class_name}`}
          badges={<Badge variant="outline">{d.status}</Badge>}
          message={`${d.room_name} · ${d.exam_date} · ${d.start_time.slice(0, 5)}–${d.end_time.slice(0, 5)}`}
          meta={`Exam #${d.exam_id}`}
        />
      ))}
    </div>
  );
}
