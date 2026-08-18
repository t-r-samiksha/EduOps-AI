import { useState } from "react";
import {
  Award,
  BookOpen,
  Edit2,
  FileText,
  GraduationCap,
  Layers,
  Printer,
  Save,
  TrendingUp,
  UserSearch,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  useClassGradebook,
  useStudentGradebook,
  useUpsertGradebookEntry,
} from "@/api/hooks/useGradebook";
import {
  useBulkGenerateReports,
  useClassReportCards,
  useGenerateReportCard,
  useStudentReportCards,
  type ReportCard as ReportCardType,
} from "@/api/hooks/useReportCards";
import { useAuthStore } from "@/store/authStore";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useViewedStudent } from "@/hooks/useViewedStudent";
import { ClassSelect } from "@/components/shared/StudentPicker";
import TranscriptDialog from "@/components/report_cards/TranscriptDialog";
import { ApiError } from "@/api/client";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";

const TERMS = ["Term 1", "Term 2", "Annual"];

type StaffTab = "marks" | "reports";

/**
 * Gradebook and report cards, one page.
 *
 * WHY THEY WERE MERGED. They are not duplicates - the gradebook is the live, editable
 * ledger (`gradebook_entries`: per-assessment scores, weighted term average, per-subject
 * GPA) and a report card is a frozen artifact (a `report_cards` row whose
 * `source_data_snapshot` bundles those grades PLUS attendance, teacher remarks and school
 * metadata as they stood at generation time, for printing). But as SCREENS they were the
 * same audience, the same class and term selectors, and a strictly sequential workflow:
 * enter marks, generate the card, print it. Two pages meant re-selecting the class to
 * cross between the halves of one task.
 *
 * The merge also fixed the report card side, which was broken outright: it resolved its
 * subject as `isTeacherOrAdmin ? undefined : ...` and then called
 * `useStudentReportCards(targetStudentId || 0)`, so staff always fetched student id 0 and
 * saw "No report cards generated yet" no matter how many cards they had just generated.
 * There was no class-listing endpoint to fetch instead; there is now.
 */
export default function AcademicRecordsPage() {
  const { role } = useAuthStore();
  const isStaff = role === "teacher" || role === "admin" || role === "principal";

  const currentUser = useCurrentUser().data;
  const lookup = useReferenceLookup(currentUser?.school_id);
  const classes = lookup.data?.classes ?? [];
  const subjects = lookup.data?.subjects ?? [];

  const [selectedTerm, setSelectedTerm] = useState("Term 1");
  const [selectedClassId, setSelectedClassId] = useState<number | "">("");
  const [activeTab, setActiveTab] = useState<StaffTab>("marks");

  // --- Staff data ---------------------------------------------------------------------
  const { data: classData, isLoading: isClassLoading } = useClassGradebook(
    isStaff && selectedClassId ? selectedClassId : undefined,
    selectedTerm,
  );
  const classCards = useClassReportCards(
    isStaff && selectedClassId && activeTab === "reports" ? Number(selectedClassId) : undefined,
    selectedTerm,
    DEFAULT_ACADEMIC_YEAR,
  );

  // --- Student / parent data ----------------------------------------------------------
  // Was `Number(user.id)` - NaN, because authStore.user.id is a Supabase UUID.
  const viewed = useViewedStudent();
  const { data: studentData, isLoading: isStudentLoading } = useStudentGradebook(
    isStaff ? undefined : viewed.studentId,
    selectedTerm,
  );
  const ownCards = useStudentReportCards(isStaff ? undefined : viewed.studentId);

  const upsertMutation = useUpsertGradebookEntry();
  const bulkGenerateMutation = useBulkGenerateReports();
  const generateOneMutation = useGenerateReportCard();

  const [previewCard, setPreviewCard] = useState<ReportCardType | null>(null);
  const [generateError, setGenerateError] = useState<string | null>(null);

  // --- Mark entry dialog --------------------------------------------------------------
  const [isEntryOpen, setIsEntryOpen] = useState(false);
  const [entryStudentId, setEntryStudentId] = useState<number | "">("");
  const [entryStudentName, setEntryStudentName] = useState<string>("");
  const [entrySubjectId, setEntrySubjectId] = useState<number | "">("");
  const [entryAssessmentType, setEntryAssessmentType] = useState<string>("assignment");
  const [entryScore, setEntryScore] = useState<string>("");
  const [entryMaxScore, setEntryMaxScore] = useState<string>("100");
  const [entryError, setEntryError] = useState<string | null>(null);

  const openEntryDialog = (studentId: number, studentName: string) => {
    setEntryStudentId(studentId);
    setEntryStudentName(studentName);
    setEntryError(null);
    setEntryScore("");
    setIsEntryOpen(true);
  };

  const handleSaveEntry = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!entrySubjectId || !entryStudentId || !selectedClassId) return;
    setEntryError(null);
    try {
      await upsertMutation.mutateAsync({
        student_id: Number(entryStudentId),
        subject_id: Number(entrySubjectId),
        // The class comes from the page's own selector rather than a second dropdown
        // inside the dialog. The old form asked for the class again and defaulted it
        // empty, so it was possible to file a mark against a different class than the
        // grid you opened it from.
        class_id: Number(selectedClassId),
        term: selectedTerm,
        assessment_type: entryAssessmentType,
        score: parseFloat(entryScore) || 0,
        max_score: parseFloat(entryMaxScore) || 100,
      });
      setIsEntryOpen(false);
      setEntryScore("");
    } catch (err) {
      setEntryError(
        err instanceof ApiError ? err.message : "Failed to save grade. Please check your inputs.",
      );
    }
  };

  const handleBulkGenerate = async () => {
    if (!selectedClassId) {
      setGenerateError("Please select a class section first.");
      return;
    }
    setGenerateError(null);
    try {
      await bulkGenerateMutation.mutateAsync({
        classId: Number(selectedClassId),
        term: selectedTerm,
        academicYear: DEFAULT_ACADEMIC_YEAR,
      });
      setActiveTab("reports");
    } catch (err) {
      setGenerateError(
        err instanceof ApiError ? err.message : "Failed to generate report cards.",
      );
    }
  };

  const handleGenerateOne = async (studentId: number) => {
    setGenerateError(null);
    try {
      await generateOneMutation.mutateAsync({
        studentId,
        term: selectedTerm,
        academicYear: DEFAULT_ACADEMIC_YEAR,
      });
      setActiveTab("reports");
    } catch (err) {
      setGenerateError(
        err instanceof ApiError ? err.message : "Failed to generate this report card.",
      );
    }
  };

  const cards = isStaff ? classCards.data ?? [] : ownCards.data ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-foreground">
            <GraduationCap className="h-7 w-7 text-primary" />
            {isStaff ? "Gradebook & Report Cards" : "My Grades & Report Cards"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {isStaff
              ? "Record assessment marks, then generate and print official report cards from the same roster."
              : "Track your subject-wise performance and GPA, and print your official term report cards."}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="flex rounded-lg border bg-muted/30 p-1">
            {TERMS.map((term) => (
              <button
                key={term}
                type="button"
                onClick={() => setSelectedTerm(term)}
                className={`rounded-md px-3 py-1.5 text-xs font-semibold transition-all ${
                  selectedTerm === term
                    ? "bg-background text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {term}
              </button>
            ))}
          </div>

          {isStaff && (
            <ClassSelect
              value={selectedClassId}
              onChange={setSelectedClassId}
              classes={classes}
            />
          )}
        </div>
      </div>

      {generateError && (
        <div
          className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-500"
          role="alert"
        >
          {generateError}
        </div>
      )}

      {isStaff ? (
        <>
          {/* Marks / Report Cards tabs. One class + term selection above serves both, which
              is the whole point of the merge. */}
          <div className="flex items-center justify-between gap-3 border-b">
            <div className="flex gap-1">
              {(
                [
                  { key: "marks", label: "Marks", icon: Edit2 },
                  { key: "reports", label: "Report Cards", icon: FileText },
                ] as const
              ).map((tab) => (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => setActiveTab(tab.key)}
                  className={`-mb-px flex items-center gap-1.5 border-b-2 px-4 py-2 text-xs font-semibold transition-colors ${
                    activeTab === tab.key
                      ? "border-primary text-primary"
                      : "border-transparent text-muted-foreground hover:text-foreground"
                  }`}
                >
                  <tab.icon className="h-3.5 w-3.5" />
                  {tab.label}
                  {tab.key === "reports" && cards.length > 0 && (
                    <span className="ml-1 rounded-full bg-primary/10 px-1.5 text-[10px] font-bold text-primary">
                      {cards.length}
                    </span>
                  )}
                </button>
              ))}
            </div>

            {activeTab === "reports" && (
              <Button
                variant="outline"
                onClick={handleBulkGenerate}
                disabled={bulkGenerateMutation.isPending || !selectedClassId}
                className="mb-1.5 flex items-center gap-1.5 text-xs font-medium"
              >
                <Layers className="h-4 w-4" />
                {bulkGenerateMutation.isPending
                  ? "Generating..."
                  : `Generate all · ${selectedTerm}`}
              </Button>
            )}
          </div>

          {!selectedClassId ? (
            <div className="rounded-xl border bg-card py-16 text-center">
              <UserSearch className="mx-auto mb-3 h-10 w-10 text-muted-foreground/50" />
              <h3 className="font-semibold text-foreground">Choose a class section</h3>
              <p className="mt-1 text-sm text-muted-foreground">
                Pick a section above to record marks or generate its report cards.
              </p>
            </div>
          ) : activeTab === "marks" ? (
            /* --- Marks grid ------------------------------------------------------- */
            <Card className="overflow-hidden border shadow-xs">
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[640px] border-collapse text-left text-sm">
                    <thead>
                      <tr className="border-b bg-muted/40 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                        <th scope="col" className="p-4">Student</th>
                        <th scope="col" className="p-4">Term Average</th>
                        <th scope="col" className="p-4">GPA (4.0 Scale)</th>
                        <th scope="col" className="p-4">Letter Grade</th>
                        <th scope="col" className="p-4">Subjects Evaluated</th>
                        <th scope="col" className="p-4 text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {isClassLoading ? (
                        <tr>
                          <td colSpan={6} className="p-8 text-center text-muted-foreground">
                            Loading gradebook...
                          </td>
                        </tr>
                      ) : !classData?.students || classData.students.length === 0 ? (
                        <tr>
                          <td colSpan={6} className="p-8 text-center text-muted-foreground">
                            No students enrolled in this section.
                          </td>
                        </tr>
                      ) : (
                        classData.students.map((st) => (
                          <tr key={st.student_id} className="transition-colors hover:bg-muted/20">
                            <td className="p-4 font-semibold text-foreground">{st.student_name}</td>
                            <td className="p-4">
                              {st.term_average !== undefined && st.term_average !== null ? (
                                <span className="font-bold text-foreground">{st.term_average}%</span>
                              ) : (
                                <span className="text-xs text-muted-foreground">—</span>
                              )}
                            </td>
                            <td className="p-4">
                              {st.gpa !== undefined && st.gpa !== null ? (
                                <Badge className="bg-primary/10 font-mono font-bold text-primary">
                                  {st.gpa.toFixed(1)} / 4.0
                                </Badge>
                              ) : (
                                <span className="text-xs text-muted-foreground">—</span>
                              )}
                            </td>
                            <td className="p-4">
                              {st.letter_grade ? (
                                <Badge variant="outline" className="font-bold">
                                  {st.letter_grade}
                                </Badge>
                              ) : (
                                <span className="text-xs text-muted-foreground">—</span>
                              )}
                            </td>
                            <td className="p-4 text-xs text-muted-foreground">
                              {st.subjects?.length || 0} Subject(s)
                            </td>
                            <td className="p-4">
                              {/* Both halves of the workflow on the row itself - enter a
                                  mark, or publish this student's card - which is what two
                                  separate pages could not offer. */}
                              <div className="ml-auto flex items-center justify-end gap-1">
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => openEntryDialog(st.student_id, st.student_name)}
                                  className="flex h-8 items-center gap-1 text-xs"
                                >
                                  <Edit2 className="h-3.5 w-3.5" />
                                  Enter Marks
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  onClick={() => handleGenerateOne(st.student_id)}
                                  disabled={generateOneMutation.isPending}
                                  className="flex h-8 items-center gap-1 text-xs"
                                >
                                  <FileText className="h-3.5 w-3.5" />
                                  Card
                                </Button>
                              </div>
                            </td>
                          </tr>
                        ))
                      )}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          ) : (
            /* --- Report cards for this class -------------------------------------- */
            <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
              {classCards.isLoading ? (
                <div className="col-span-full py-16 text-center text-muted-foreground">
                  Loading report cards...
                </div>
              ) : cards.length === 0 ? (
                <div className="col-span-full rounded-xl border bg-card py-16 text-center">
                  <GraduationCap className="mx-auto mb-3 h-10 w-10 text-muted-foreground/50" />
                  <h3 className="font-semibold text-foreground">
                    No report cards for {selectedTerm} yet
                  </h3>
                  <p className="mt-1 text-sm text-muted-foreground">
                    Use "Generate all" above to compile grades, attendance and remarks for
                    this section.
                  </p>
                </div>
              ) : (
                cards.map((card) => (
                  <ReportCardTile
                    key={card.id}
                    card={card}
                    onPreview={() => setPreviewCard(card)}
                  />
                ))
              )}
            </div>
          )}
        </>
      ) : (
        /* ================= Student / parent read-only view ======================= */
        <div className="space-y-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <Card className="border shadow-xs">
              <CardContent className="flex items-center gap-4 p-5">
                <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
                  <Award className="h-6 w-6" />
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Cumulative GPA</span>
                  <p className="text-2xl font-bold text-foreground">
                    {studentData?.gpa !== undefined && studentData?.gpa !== null
                      ? `${studentData.gpa.toFixed(1)} / 4.0`
                      : "—"}
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card className="border shadow-xs">
              <CardContent className="flex items-center gap-4 p-5">
                <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600">
                  <TrendingUp className="h-6 w-6" />
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Term Average</span>
                  <p className="text-2xl font-bold text-foreground">
                    {studentData?.term_average !== undefined && studentData?.term_average !== null
                      ? `${studentData.term_average}%`
                      : "—"}
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card className="border shadow-xs">
              <CardContent className="flex items-center gap-4 p-5">
                <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-amber-500/10 text-amber-600">
                  <BookOpen className="h-6 w-6" />
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Letter Grade</span>
                  <p className="text-2xl font-bold text-foreground">
                    {studentData?.letter_grade || "—"}
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Subject breakdown */}
          <Card className="overflow-hidden border shadow-xs">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] border-collapse text-left text-sm">
                  <thead>
                    <tr className="border-b bg-muted/40 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                      <th scope="col" className="p-4">Subject</th>
                      <th scope="col" className="p-4">Assessments Count</th>
                      <th scope="col" className="p-4">Weighted Score</th>
                      <th scope="col" className="p-4">Subject GPA</th>
                      <th scope="col" className="p-4">Grade</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {isStudentLoading || viewed.isLoading ? (
                      <tr>
                        <td colSpan={5} className="p-8 text-center text-muted-foreground">
                          Loading grade summary...
                        </td>
                      </tr>
                    ) : !studentData?.subjects || studentData.subjects.length === 0 ? (
                      <tr>
                        <td colSpan={5} className="p-8 text-center text-muted-foreground">
                          No assessment grades posted for this term yet.
                        </td>
                      </tr>
                    ) : (
                      studentData.subjects.map((subj) => (
                        <tr key={subj.subject_id} className="transition-colors hover:bg-muted/20">
                          <td className="p-4 font-semibold text-foreground">{subj.subject_name}</td>
                          <td className="p-4 text-muted-foreground">
                            {subj.entries_count} Entries
                          </td>
                          <td className="p-4 font-bold text-foreground">
                            {subj.percentage !== undefined && subj.percentage !== null
                              ? `${subj.percentage}%`
                              : "—"}
                          </td>
                          <td className="p-4">
                            {subj.gpa !== undefined && subj.gpa !== null ? (
                              <Badge className="bg-primary/10 font-mono font-bold text-primary">
                                {subj.gpa.toFixed(1)}
                              </Badge>
                            ) : (
                              <span className="text-xs text-muted-foreground">—</span>
                            )}
                          </td>
                          <td className="p-4">
                            <Badge variant="outline">{subj.letter_grade || "—"}</Badge>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {/* Own report cards, same page - the student no longer needs a second menu item
              to print the term's card. */}
          <div className="space-y-3">
            <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
              <FileText className="h-4 w-4 text-primary" />
              Official Report Cards
            </h3>
            {ownCards.isLoading ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                Loading report cards...
              </p>
            ) : cards.length === 0 ? (
              <div className="rounded-xl border bg-card py-10 text-center">
                <p className="text-sm text-muted-foreground">
                  Your official report card will appear here once published by the school.
                </p>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-5 md:grid-cols-2 lg:grid-cols-3">
                {cards.map((card) => (
                  <ReportCardTile
                    key={card.id}
                    card={card}
                    onPreview={() => setPreviewCard(card)}
                  />
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      <TranscriptDialog card={previewCard} onClose={() => setPreviewCard(null)} />

      {/* Record Mark Modal */}
      <Dialog open={isEntryOpen} onOpenChange={setIsEntryOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Save className="h-5 w-5 text-primary" />
              Record Assessment Mark
            </DialogTitle>
          </DialogHeader>

          <form onSubmit={handleSaveEntry} className="mt-2 space-y-4">
            <div className="rounded-lg border bg-muted/20 p-3 text-xs">
              <span className="text-muted-foreground">Recording for</span>
              <p className="font-bold text-foreground">{entryStudentName}</p>
              <p className="mt-0.5 text-muted-foreground">
                {classes.find((c) => c.id === selectedClassId)?.name} · {selectedTerm}
              </p>
            </div>

            <div>
              <label className="text-xs font-semibold text-foreground">Subject *</label>
              <select
                required
                value={entrySubjectId}
                onChange={(e) => setEntrySubjectId(e.target.value ? Number(e.target.value) : "")}
                className="mt-1 w-full rounded-lg border bg-background p-2 text-sm"
              >
                <option value="">Select subject…</option>
                {subjects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>

            <div>
              <label className="text-xs font-semibold text-foreground">Assessment Type</label>
              <select
                value={entryAssessmentType}
                onChange={(e) => setEntryAssessmentType(e.target.value)}
                className="mt-1 w-full rounded-lg border bg-background p-2 text-sm"
              >
                <option value="assignment">Assignment (20%)</option>
                <option value="quiz">Quiz (20%)</option>
                <option value="midterm">Midterm Exam (20%)</option>
                <option value="final">Final Exam (40%)</option>
                <option value="other">Other Assessment</option>
              </select>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-semibold text-foreground">Score Obtained</label>
                <Input
                  type="number"
                  required
                  min={0}
                  step={0.5}
                  placeholder="e.g. 85"
                  value={entryScore}
                  onChange={(e) => setEntryScore(e.target.value)}
                  className="mt-1"
                />
              </div>
              <div>
                <label className="text-xs font-semibold text-foreground">Max Marks</label>
                <Input
                  type="number"
                  required
                  min={1}
                  placeholder="e.g. 100"
                  value={entryMaxScore}
                  onChange={(e) => setEntryMaxScore(e.target.value)}
                  className="mt-1"
                />
              </div>
            </div>

            {entryError && (
              <div
                className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-500"
                role="alert"
              >
                {entryError}
              </div>
            )}

            <div className="flex justify-end gap-2 border-t pt-3">
              <Button type="button" variant="ghost" onClick={() => setIsEntryOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={upsertMutation.isPending || !entrySubjectId}>
                {upsertMutation.isPending ? "Saving..." : "Save Grade"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}

/** One report card summary tile. Shared by the staff class list and a student's own list. */
function ReportCardTile({
  card,
  onPreview,
}: {
  card: ReportCardType;
  onPreview: () => void;
}) {
  return (
    <Card className="border shadow-xs transition-shadow hover:shadow-md">
      <CardContent className="space-y-4 p-5">
        <div className="flex items-start justify-between">
          <div>
            <Badge variant="outline" className="bg-primary/5 text-xs font-bold text-primary">
              {card.term} · {card.academic_year}
            </Badge>
            <h3 className="mt-2 text-base font-bold text-foreground">
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

        <div className="grid grid-cols-2 gap-2 border-t pt-2 text-xs">
          <div className="rounded-lg bg-muted/30 p-2">
            <span className="text-muted-foreground">Term Average</span>
            <p className="mt-0.5 font-bold text-foreground">
              {card.term_average ? `${card.term_average}%` : "—"}
            </p>
          </div>
          <div className="rounded-lg bg-muted/30 p-2">
            {/* "Attendance - 2026-27": the academic-year figure, labelled so it reads as a
                different measure from the portal's 30-day one rather than a contradiction.
                Never falls back to "100%" - no attendance data is not perfect attendance. */}
            <span className="text-muted-foreground">
              {card.source_data_snapshot?.attendance?.label ?? "Attendance"}
            </span>
            <p className="mt-0.5 font-bold text-emerald-600">
              {card.attendance_percentage == null ? "No data" : `${card.attendance_percentage}%`}
            </p>
          </div>
        </div>

        <div className="flex gap-2 pt-2">
          <Button
            variant="outline"
            size="sm"
            onClick={onPreview}
            className="flex w-full items-center justify-center gap-1.5 text-xs"
          >
            <Printer className="h-3.5 w-3.5" />
            Preview & Print
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
