import { GraduationCap, Printer } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { ReportCard } from "@/api/hooks/useReportCards";

/**
 * The printable official transcript.
 *
 * Extracted verbatim from ReportCardsPage when the gradebook and report card screens were
 * merged - it is the one thing on the old page that was neither a duplicate of the
 * gradebook nor broken, and it is now reachable from both the class report-card list and a
 * student's own list.
 */
export default function TranscriptDialog({
  card,
  onClose,
}: {
  card: ReportCard | null;
  onClose: () => void;
}) {
  return (
    <Dialog open={!!card} onOpenChange={onClose}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between">
            <span className="flex items-center gap-2">
              <GraduationCap className="h-5 w-5 text-primary" />
              Academic Transcript
            </span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => window.print()}
              className="flex items-center gap-1 text-xs"
            >
              <Printer className="h-3.5 w-3.5" />
              Print / Save PDF
            </Button>
          </DialogTitle>
        </DialogHeader>

        {card && (
          <div className="space-y-6 rounded-xl border bg-card p-6 text-foreground print:border-none">
            {/* Header */}
            <div className="space-y-1 border-b pb-4 text-center">
              <h2 className="text-2xl font-bold uppercase tracking-wide text-primary">
                {card.source_data_snapshot?.school_name || "EduOps AI Academy"}
              </h2>
              <p className="text-xs text-muted-foreground">Official Academic Progress Report</p>
              <div className="flex items-center justify-center gap-4 pt-2 text-xs font-semibold text-muted-foreground">
                <span>Term: {card.term}</span>
                <span>•</span>
                <span>Academic Year: {card.academic_year}</span>
                <span>•</span>
                <span>Date: {card.source_data_snapshot?.generated_date}</span>
              </div>
            </div>

            {/* Student Metadata */}
            <div className="grid grid-cols-2 gap-4 rounded-xl border bg-muted/20 p-4 text-xs sm:grid-cols-4">
              <div>
                <span className="text-muted-foreground">Student Name</span>
                <p className="mt-0.5 font-bold text-foreground">
                  {card.source_data_snapshot?.student_name}
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">Student ID</span>
                <p className="mt-0.5 font-bold text-foreground">#{card.student_id}</p>
              </div>
              <div>
                <span className="text-muted-foreground">Class Section</span>
                <p className="mt-0.5 font-bold text-foreground">
                  {card.source_data_snapshot?.class_name}
                </p>
              </div>
              <div>
                <span className="text-muted-foreground">
                  {card.source_data_snapshot?.attendance?.label ?? "Attendance"}
                </span>
                <p className="mt-0.5 font-bold text-emerald-600">
                  {card.attendance_percentage == null
                    ? "No data"
                    : `${card.attendance_percentage}% Present`}
                </p>
              </div>
            </div>

            {/* Subject Grades Table */}
            <div>
              <h4 className="mb-2 text-xs font-bold uppercase tracking-wider text-muted-foreground">
                Subject Performance
              </h4>
              {/* overflow-x-auto: this was the only wide table in the app without a scroll
                  container, so at 390px it pushed the dialog sideways. */}
              <div className="overflow-x-auto">
                <table className="w-full min-w-[420px] border-collapse text-left text-xs">
                  <thead>
                    <tr className="border-b bg-muted/40 font-semibold text-muted-foreground">
                      <th scope="col" className="p-3">Subject</th>
                      <th scope="col" className="p-3 text-right">Weighted Marks</th>
                      <th scope="col" className="p-3 text-right">Grade Point (GPA)</th>
                      <th scope="col" className="p-3 text-right">Letter Grade</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {card.source_data_snapshot?.subjects?.map((s) => (
                      <tr key={s.subject_id}>
                        <td className="p-3 font-semibold">{s.subject_name}</td>
                        <td className="p-3 text-right font-bold">
                          {s.percentage !== undefined && s.percentage !== null
                            ? `${s.percentage}%`
                            : "—"}
                        </td>
                        <td className="p-3 text-right font-mono">
                          {s.gpa !== undefined && s.gpa !== null ? s.gpa.toFixed(1) : "—"}
                        </td>
                        <td className="p-3 text-right font-bold">{s.letter_grade || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {/* Summary KPIs */}
            <div className="grid grid-cols-2 gap-4 rounded-xl border bg-primary/5 p-4 text-center">
              <div>
                <span className="text-xs text-muted-foreground">Overall Term Average</span>
                <p className="mt-1 text-2xl font-bold text-primary">
                  {card.term_average ? `${card.term_average}%` : "—"}
                </p>
              </div>
              <div>
                <span className="text-xs text-muted-foreground">Cumulative GPA</span>
                <p className="mt-1 text-2xl font-bold text-emerald-600">
                  {card.gpa ? `${card.gpa.toFixed(1)} / 4.0` : "—"}
                </p>
              </div>
            </div>

            {/* Remarks */}
            {card.source_data_snapshot?.teacher_remarks?.length > 0 && (
              <div className="space-y-2 border-t pt-2">
                <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                  Teacher Remarks & Observations
                </h4>
                {card.source_data_snapshot.teacher_remarks.map((r, i) => (
                  <div key={i} className="rounded-lg border bg-muted/20 p-3 text-xs">
                    <p className="italic text-foreground">"{r.content}"</p>
                    <span className="mt-1 block text-[11px] text-muted-foreground">
                      Recorded on {r.date} · Tag: {r.sentiment}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
