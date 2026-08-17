import { useState } from "react";
import {
  GraduationCap,
  Award,
  BookOpen,
  Plus,
  Edit2,
  TrendingUp,
  Save,
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
import { useAuthStore } from "@/store/authStore";

export default function GradebookPage() {
  const { user, role } = useAuthStore();
  const isTeacherOrAdmin = role === "teacher" || role === "admin" || role === "principal";

  const [selectedTerm, setSelectedTerm] = useState("Term 1");
  const selectedClassId = 1;

  // Queries
  const { data: classData, isLoading: isClassLoading } = useClassGradebook(
    isTeacherOrAdmin ? selectedClassId : undefined,
    selectedTerm
  );
  const { data: studentData, isLoading: isStudentLoading } = useStudentGradebook(
    !isTeacherOrAdmin && user?.id ? Number(user.id) : undefined,
    selectedTerm
  );

  const upsertMutation = useUpsertGradebookEntry();

  // Grade Entry Modal
  const [isEntryOpen, setIsEntryOpen] = useState(false);
  const [entryStudentId, setEntryStudentId] = useState<number>(1);
  const entrySubjectId = 1;
  const [entryAssessmentType, setEntryAssessmentType] = useState<string>("assignment");
  const [entryScore, setEntryScore] = useState<string>("");
  const [entryMaxScore, setEntryMaxScore] = useState<string>("100");

  const handleSaveEntry = async (e: React.FormEvent) => {
    e.preventDefault();
    await upsertMutation.mutateAsync({
      student_id: entryStudentId,
      subject_id: entrySubjectId,
      class_id: selectedClassId,
      term: selectedTerm,
      assessment_type: entryAssessmentType,
      score: parseFloat(entryScore) || 0,
      max_score: parseFloat(entryMaxScore) || 100,
    });
    setIsEntryOpen(false);
    setEntryScore("");
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <GraduationCap className="h-7 w-7 text-primary" />
            Academic Gradebook & GPA
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {isTeacherOrAdmin
              ? "Record assessment marks, view weighted averages, and evaluate student GPA."
              : "Track your subject-wise academic performance, term averages, and 4.0 scale GPA."}
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Term Selector */}
          <div className="flex rounded-lg border bg-muted/30 p-1">
            {["Term 1", "Term 2", "Annual"].map((term) => (
              <button
                key={term}
                type="button"
                onClick={() => setSelectedTerm(term)}
                className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
                  selectedTerm === term
                    ? "bg-background text-foreground shadow-xs"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {term}
              </button>
            ))}
          </div>

          {isTeacherOrAdmin && (
            <Button
              onClick={() => setIsEntryOpen(true)}
              className="flex items-center gap-1.5 shadow-sm text-xs font-medium"
            >
              <Plus className="h-4 w-4" />
              Record Mark
            </Button>
          )}
        </div>
      </div>

      {/* Teacher View: Matrix Grid */}
      {isTeacherOrAdmin ? (
        <Card className="border shadow-xs overflow-hidden">
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-left border-collapse text-sm">
                <thead>
                  <tr className="border-b bg-muted/40 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    <th className="p-4">Student</th>
                    <th className="p-4">Term Average</th>
                    <th className="p-4">GPA (4.0 Scale)</th>
                    <th className="p-4">Letter Grade</th>
                    <th className="p-4">Subjects Evaluated</th>
                    <th className="p-4 text-right">Actions</th>
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
                      <tr key={st.student_id} className="hover:bg-muted/20 transition-colors">
                        <td className="p-4 font-semibold text-foreground">
                          {st.student_name}
                        </td>
                        <td className="p-4">
                          {st.term_average !== undefined && st.term_average !== null ? (
                            <span className="font-bold text-foreground">
                              {st.term_average}%
                            </span>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </td>
                        <td className="p-4">
                          {st.gpa !== undefined && st.gpa !== null ? (
                            <Badge className="bg-primary/10 text-primary font-mono font-bold">
                              {st.gpa.toFixed(1)} / 4.0
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </td>
                        <td className="p-4">
                          {st.letter_grade ? (
                            <Badge variant="outline" className="font-bold">
                              {st.letter_grade}
                            </Badge>
                          ) : (
                            <span className="text-muted-foreground text-xs">—</span>
                          )}
                        </td>
                        <td className="p-4 text-xs text-muted-foreground">
                          {st.subjects?.length || 0} Subject(s)
                        </td>
                        <td className="p-4 text-right">
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => {
                              setEntryStudentId(st.student_id);
                              setIsEntryOpen(true);
                            }}
                            className="h-8 text-xs flex items-center gap-1 ml-auto"
                          >
                            <Edit2 className="h-3.5 w-3.5" />
                            Enter Marks
                          </Button>
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
        /* Student & Parent Read-Only Summary */
        <div className="space-y-6">
          {/* Top KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <Card className="border shadow-xs">
              <CardContent className="p-5 flex items-center gap-4">
                <div className="h-12 w-12 rounded-xl bg-primary/10 text-primary flex items-center justify-center">
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
              <CardContent className="p-5 flex items-center gap-4">
                <div className="h-12 w-12 rounded-xl bg-emerald-500/10 text-emerald-600 flex items-center justify-center">
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
              <CardContent className="p-5 flex items-center gap-4">
                <div className="h-12 w-12 rounded-xl bg-amber-500/10 text-amber-600 flex items-center justify-center">
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

          {/* Subject Breakdown Table */}
          <Card className="border shadow-xs overflow-hidden">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-left border-collapse text-sm">
                  <thead>
                    <tr className="border-b bg-muted/40 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                      <th className="p-4">Subject</th>
                      <th className="p-4">Assessments Count</th>
                      <th className="p-4">Weighted Score</th>
                      <th className="p-4">Subject GPA</th>
                      <th className="p-4">Grade</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {isStudentLoading ? (
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
                        <tr key={subj.subject_id} className="hover:bg-muted/20 transition-colors">
                          <td className="p-4 font-semibold text-foreground">
                            {subj.subject_name}
                          </td>
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
                              <Badge className="bg-primary/10 text-primary font-mono font-bold">
                                {subj.gpa.toFixed(1)}
                              </Badge>
                            ) : (
                              <span className="text-muted-foreground text-xs">—</span>
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
        </div>
      )}

      {/* Record Mark Modal */}
      <Dialog open={isEntryOpen} onOpenChange={setIsEntryOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Save className="h-5 w-5 text-primary" />
              Record Assessment Mark
            </DialogTitle>
          </DialogHeader>

          <form onSubmit={handleSaveEntry} className="space-y-4 mt-2">
            <div>
              <label className="text-xs font-semibold text-foreground">Assessment Type</label>
              <select
                value={entryAssessmentType}
                onChange={(e) => setEntryAssessmentType(e.target.value)}
                className="w-full mt-1 p-2 rounded-lg border bg-background text-sm"
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

            <div className="flex justify-end gap-2 pt-3 border-t">
              <Button type="button" variant="ghost" onClick={() => setIsEntryOpen(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={upsertMutation.isPending}>
                {upsertMutation.isPending ? "Saving..." : "Save Grade"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
