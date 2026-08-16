import { Armchair } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import PageHeader from "@/components/shared/PageHeader";
import SeatingChart from "@/components/exams/SeatingChart";
import { useSeating } from "@/api/hooks/useExams";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { ApiError } from "@/api/client";

/** No exam_id/student_id passed — per the real backend (GET /admin/exams/seating),
 * a student's own id is used regardless of any student_id they might pass, so this
 * is already correctly scoped to "my seats" without a filter UI. The backend
 * returns every seat in each room the student is actually placed in (not just
 * their own row), so the chart shows the real room layout with their own seat
 * highlighted - not an isolated single seat. */
export default function StudentSeatLookup() {
  const currentUser = useCurrentUser();
  const seating = useSeating();
  const lookup = useReferenceLookup(currentUser.data?.school_id);

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="My Exam Seats" description="The full room layout for every exam you've been seated in, with your own seat highlighted." />

      {seating.isLoading && <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />}
      {seating.error && (
        <Card>
          <CardContent className="py-6 text-sm text-urgent">
            {seating.error instanceof ApiError ? seating.error.message : "Failed to load seating."}
          </CardContent>
        </Card>
      )}
      {seating.data && seating.data.items.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center gap-1 py-10 text-center">
            <Armchair className="h-6 w-6 text-ink-muted" />
            <p className="font-display text-sm font-medium text-ink">No seat assigned yet</p>
            <p className="max-w-xs text-xs text-ink-muted">Nothing has been generated for any exam you're enrolled in yet.</p>
          </CardContent>
        </Card>
      )}
      {seating.data && seating.data.items.length > 0 && (
        <SeatingChart items={seating.data.items} lookup={lookup.data} highlightStudentId={currentUser.data?.user_id} />
      )}
    </div>
  );
}
