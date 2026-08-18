import { useState } from "react";
import {
  FileText,
  Printer,
  Layers,
  GraduationCap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  useStudentReportCards,
  useBulkGenerateReports,
  ReportCard as ReportCardType,
} from "@/api/hooks/useReportCards";
import { useAuthStore } from "@/store/authStore";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useCurrentUser } from "@/api/hooks/useAuth";

export default function ReportCardsPage() {
  const { user, role } = useAuthStore();
  const isTeacherOrAdmin = role === "teacher" || role === "admin" || role === "principal";

  const currentUser = useCurrentUser().data;
  const lookup = useReferenceLookup(currentUser?.school_id);
  const classes = lookup.data?.classes ?? [];

  const [selectedClassId, setSelectedClassId] = useState<number | "">("");
  
  // Note: the individual report card view still needs a student ID. If the user is a teacher,
  // we could let them select a student, but since we are focusing on bulk generation for teachers,
  // we default to targeting the logged-in student if they are not a teacher.
  const targetStudentId = isTeacherOrAdmin ? undefined : (user?.id ? Number(user.id) : undefined);
  const { data: reportCards = [], isLoading } = useStudentReportCards(targetStudentId || 0);

  const bulkGenerateMutation = useBulkGenerateReports();

  const [previewCard, setPreviewCard] = useState<ReportCardType | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);

  const handleBulkGenerate = async () => {
    if (!selectedClassId) {
      setGenerateError("Please select a class section first.");
      return;
    }
    setGenerateError(null);
    try {
      await bulkGenerateMutation.mutateAsync({
        classId: Number(selectedClassId),
        term: "Term 1",
      });
    } catch (err: any) {
      console.error("Failed to generate report cards:", err);
      setGenerateError(err?.message || "Failed to generate report cards.");
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <FileText className="h-7 w-7 text-primary" />
            Automated Report Cards & Transcripts
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {isTeacherOrAdmin
              ? "Generate verifiable multi-factor academic report cards with attendance and GPA snapshots."
              : "Access and print your official term academic report cards and transcripts."}
          </p>
        </div>

        {isTeacherOrAdmin && (
          <div className="flex items-center gap-2">
            <select
              value={selectedClassId}
              onChange={(e) => {
                setSelectedClassId(e.target.value ? Number(e.target.value) : "");
                setGenerateError(null);
              }}
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="">Select class…</option>
              {classes.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
            <Button
              variant="outline"
              onClick={handleBulkGenerate}
              disabled={bulkGenerateMutation.isPending || !selectedClassId}
              className="flex items-center gap-1.5 text-xs font-medium"
            >
              <Layers className="h-4 w-4" />
              {bulkGenerateMutation.isPending ? "Generating..." : "Bulk Generate"}
            </Button>
          </div>
        )}
      </div>

      {generateError && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-400">
          {generateError}
        </div>
      )}

      {/* Cards List */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {isLoading ? (
          <div className="col-span-full py-16 text-center text-muted-foreground">
            Loading report cards...
          </div>
        ) : reportCards.length === 0 ? (
          <div className="col-span-full py-16 text-center border rounded-xl bg-card">
            <GraduationCap className="h-10 w-10 mx-auto text-muted-foreground/50 mb-3" />
            <h3 className="font-semibold text-foreground">No report cards generated yet</h3>
            <p className="text-sm text-muted-foreground mt-1">
              {isTeacherOrAdmin
                ? "Click 'Generate Report Card' to compile grades and attendance."
                : "Your official report card will appear here once published by the school."}
            </p>
          </div>
        ) : (
          reportCards.map((card) => (
            <Card key={card.id} className="border shadow-xs hover:shadow-md transition-shadow">
              <CardContent className="p-5 space-y-4">
                <div className="flex items-start justify-between">
                  <div>
                    <Badge variant="outline" className="bg-primary/5 text-primary text-xs font-bold">
                      {card.term} · {card.academic_year}
                    </Badge>
                    <h3 className="font-bold text-base text-foreground mt-2">
                      {card.source_data_snapshot?.student_name || `Student #${card.student_id}`}
                    </h3>
                    <p className="text-xs text-muted-foreground">
                      {card.source_data_snapshot?.class_name}
                    </p>
                  </div>
                  <div className="text-right">
                    <span className="text-xs text-muted-foreground">GPA</span>
                    <p className="text-xl font-bold text-primary">
                      {card.gpa ? card.gpa.toFixed(1) : "—"}
                    </p>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 pt-2 border-t text-xs">
                  <div className="p-2 rounded-lg bg-muted/30">
                    <span className="text-muted-foreground">Term Average</span>
                    <p className="font-bold text-foreground mt-0.5">
                      {card.term_average ? `${card.term_average}%` : "—"}
                    </p>
                  </div>
                  <div className="p-2 rounded-lg bg-muted/30">
                    {/* "Attendance - 2026-27": the academic-year figure, labelled so it
                        reads as a different measure from the portal's 30-day one rather
                        than a contradiction. Never falls back to "100%" - no attendance
                        data is not perfect attendance. */}
                    <span className="text-muted-foreground">
                      {card.source_data_snapshot?.attendance?.label ?? "Attendance"}
                    </span>
                    <p className="font-bold text-emerald-600 mt-0.5">
                      {card.attendance_percentage == null
                        ? "No data"
                        : `${card.attendance_percentage}%`}
                    </p>
                  </div>
                </div>

                <div className="pt-2 flex gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setPreviewCard(card)}
                    className="w-full flex items-center justify-center gap-1.5 text-xs"
                  >
                    <Printer className="h-3.5 w-3.5" />
                    Preview & Print
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))
        )}
      </div>

      {/* Official Transcript Preview Modal */}
      <Dialog open={!!previewCard} onOpenChange={() => setPreviewCard(null)}>
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-y-auto">
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

          {previewCard && (
            <div className="p-6 border rounded-xl bg-card space-y-6 text-foreground print:border-none">
              {/* Header */}
              <div className="text-center border-b pb-4 space-y-1">
                <h2 className="text-2xl font-bold text-primary tracking-wide uppercase">
                  {previewCard.source_data_snapshot?.school_name || "EduOps AI Academy"}
                </h2>
                <p className="text-xs text-muted-foreground">Official Academic Progress Report</p>
                <div className="flex items-center justify-center gap-4 text-xs font-semibold text-muted-foreground pt-2">
                  <span>Term: {previewCard.term}</span>
                  <span>•</span>
                  <span>Academic Year: {previewCard.academic_year}</span>
                  <span>•</span>
                  <span>Date: {previewCard.source_data_snapshot?.generated_date}</span>
                </div>
              </div>

              {/* Student Metadata */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 p-4 rounded-xl bg-muted/20 border text-xs">
                <div>
                  <span className="text-muted-foreground">Student Name</span>
                  <p className="font-bold text-foreground mt-0.5">
                    {previewCard.source_data_snapshot?.student_name}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">Student ID</span>
                  <p className="font-bold text-foreground mt-0.5">
                    #{previewCard.student_id}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">Class Section</span>
                  <p className="font-bold text-foreground mt-0.5">
                    {previewCard.source_data_snapshot?.class_name}
                  </p>
                </div>
                <div>
                  <span className="text-muted-foreground">
                    {previewCard.source_data_snapshot?.attendance?.label ?? "Attendance"}
                  </span>
                  <p className="font-bold text-emerald-600 mt-0.5">
                    {previewCard.attendance_percentage == null
                      ? "No data"
                      : `${previewCard.attendance_percentage}% Present`}
                  </p>
                </div>
              </div>

              {/* Subject Grades Table */}
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground mb-2">
                  Subject Performance
                </h4>
                {/* overflow-x-auto: this was the only wide table in the app without a scroll
                    container, so at 390px it pushed the dialog sideways. */}
                <div className="overflow-x-auto">
                <table className="w-full min-w-[420px] text-left text-xs border-collapse">
                  <thead>
                    <tr className="border-b bg-muted/40 font-semibold text-muted-foreground">
                      <th scope="col" className="p-3">Subject</th>
                      <th scope="col" className="p-3 text-right">Weighted Marks</th>
                      <th scope="col" className="p-3 text-right">Grade Point (GPA)</th>
                      <th scope="col" className="p-3 text-right">Letter Grade</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {previewCard.source_data_snapshot?.subjects?.map((s) => (
                      <tr key={s.subject_id}>
                        <td className="p-3 font-semibold">{s.subject_name}</td>
                        <td className="p-3 text-right font-bold">
                          {s.percentage !== undefined && s.percentage !== null ? `${s.percentage}%` : "—"}
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
              <div className="grid grid-cols-2 gap-4 p-4 rounded-xl border bg-primary/5 text-center">
                <div>
                  <span className="text-xs text-muted-foreground">Overall Term Average</span>
                  <p className="text-2xl font-bold text-primary mt-1">
                    {previewCard.term_average ? `${previewCard.term_average}%` : "—"}
                  </p>
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Cumulative GPA</span>
                  <p className="text-2xl font-bold text-emerald-600 mt-1">
                    {previewCard.gpa ? `${previewCard.gpa.toFixed(1)} / 4.0` : "—"}
                  </p>
                </div>
              </div>

              {/* Remarks */}
              {previewCard.source_data_snapshot?.teacher_remarks?.length > 0 && (
                <div className="space-y-2 pt-2 border-t">
                  <h4 className="text-xs font-bold uppercase tracking-wider text-muted-foreground">
                    Teacher Remarks & Observations
                  </h4>
                  {previewCard.source_data_snapshot.teacher_remarks.map((r, i) => (
                    <div key={i} className="p-3 rounded-lg bg-muted/20 border text-xs">
                      <p className="italic text-foreground">"{r.content}"</p>
                      <span className="text-[11px] text-muted-foreground mt-1 block">
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
    </div>
  );
}
