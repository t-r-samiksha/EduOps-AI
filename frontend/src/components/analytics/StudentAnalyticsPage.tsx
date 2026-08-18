import { useMemo, useState } from "react";
import {
  TrendingUp,
  Award,
  AlertTriangle,
  CheckCircle2,
  Calendar,
  BookOpen,
  FileCheck,
  HelpCircle,
  Users,
  UserSearch,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useStudentAnalytics } from "@/api/hooks/useStudentAnalytics";
import { useClassGradebook } from "@/api/hooks/useGradebook";
import { useFlaggedStudents } from "@/api/hooks/useRisk";
import { useAuthStore } from "@/store/authStore";
import { useViewedStudent } from "@/hooks/useViewedStudent";
import { useSelectedChild } from "@/hooks/useSelectedChild";
import StudentPicker from "@/components/shared/StudentPicker";

const TERMS = ["Term 1", "Term 2", "Annual"];

/**
 * Class-wide roll-up, shown to staff before they drill into one student.
 *
 * Composed CLIENT-SIDE from GET /gradebook/class/{id} (which already returns each
 * student's term average, GPA and letter grade) and GET /risk/flagged?class_id=. No new
 * aggregate endpoint: everything below is a reduction over data those two already return,
 * so adding one would mean a second implementation of "class average" that could disagree
 * with the gradebook grid's own numbers.
 */
function ClassOverview({ classId, term }: { classId: number; term: string }) {
  const { data: classData, isLoading, isError } = useClassGradebook(classId, term);
  const flagged = useFlaggedStudents({ classId, status: "open" });

  const students = classData?.students ?? [];

  const stats = useMemo(() => {
    const scored = students.filter(
      (s) => s.term_average !== undefined && s.term_average !== null,
    );
    const averages = scored.map((s) => s.term_average as number);
    const gpas = students
      .map((s) => s.gpa)
      .filter((g): g is number => g !== undefined && g !== null);

    return {
      enrolled: students.length,
      // Distinguishing "evaluated" from "enrolled" matters: a class average computed over
      // only the graded half of a roster is not the class's average, and showing the two
      // counts side by side is what stops it being read as one.
      evaluated: scored.length,
      classAverage: averages.length
        ? Math.round((averages.reduce((a, b) => a + b, 0) / averages.length) * 10) / 10
        : null,
      averageGpa: gpas.length
        ? Math.round((gpas.reduce((a, b) => a + b, 0) / gpas.length) * 10) / 10
        : null,
    };
  }, [students]);

  const openFlags = flagged.data ?? [];

  if (isError) {
    return (
      <div className="rounded-xl border bg-card py-12 text-center" role="alert">
        <p className="text-sm font-medium text-[hsl(var(--urgent))]">
          Could not load this class section.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">Reload the page, or try again in a moment.</p>
      </div>
    );
  }

  if (isLoading) {
    return <div className="py-12 text-center text-muted-foreground">Loading class overview…</div>;
  }

  if (students.length === 0) {
    return (
      <div className="rounded-xl border bg-card py-12 text-center">
        <Users className="mx-auto mb-3 h-10 w-10 text-muted-foreground/50" />
        <h3 className="font-semibold text-foreground">No students enrolled in this section</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Enrol students from School Management to see analytics here.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="border shadow-xs">
          <CardContent className="flex items-center gap-4 p-5">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <TrendingUp className="h-6 w-6" />
            </div>
            <div>
              <span className="text-xs text-muted-foreground">Class average ({term})</span>
              <p className="text-2xl font-bold text-foreground">
                {stats.classAverage == null ? "—" : `${stats.classAverage}%`}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="border shadow-xs">
          <CardContent className="flex items-center gap-4 p-5">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600">
              <Award className="h-6 w-6" />
            </div>
            <div>
              <span className="text-xs text-muted-foreground">Average GPA</span>
              <p className="text-2xl font-bold text-foreground">
                {stats.averageGpa == null ? "—" : `${stats.averageGpa} / 4.0`}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="border shadow-xs">
          <CardContent className="flex items-center gap-4 p-5">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600">
              <Users className="h-6 w-6" />
            </div>
            <div>
              <span className="text-xs text-muted-foreground">Students evaluated</span>
              <p className="text-2xl font-bold text-foreground">
                {stats.evaluated}
                <span className="text-base font-medium text-muted-foreground"> / {stats.enrolled}</span>
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="border shadow-xs">
          <CardContent className="flex items-center gap-4 p-5">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-amber-500/10 text-amber-600">
              <AlertTriangle className="h-6 w-6" />
            </div>
            <div>
              <span className="text-xs text-muted-foreground">Open risk flags</span>
              <p className="text-2xl font-bold text-foreground">{openFlags.length}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="border shadow-xs overflow-hidden">
        <CardContent className="p-0">
          <div className="border-b bg-muted/20 p-4">
            <h3 className="text-sm font-bold text-foreground">
              Roster performance · {classData?.class_id ? `${students.length} students` : ""}
            </h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Pick a student above to see their full analytics.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] border-collapse text-left text-sm">
              <thead>
                <tr className="border-b bg-muted/40 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <th scope="col" className="p-4">Student</th>
                  <th scope="col" className="p-4">Term average</th>
                  <th scope="col" className="p-4">GPA</th>
                  <th scope="col" className="p-4">Grade</th>
                  <th scope="col" className="p-4">Subjects</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {students.map((st) => {
                  const flag = openFlags.find((f) => f.student_id === st.student_id);
                  return (
                    <tr key={st.student_id} className="transition-colors hover:bg-muted/20">
                      <td className="p-4 font-semibold text-foreground">
                        <div className="flex items-center gap-2">
                          {st.student_name}
                          {flag && (
                            <Badge
                              variant="outline"
                              className="border-amber-200 bg-amber-50 text-[11px] text-amber-700"
                            >
                              {flag.risk_level} risk
                            </Badge>
                          )}
                        </div>
                      </td>
                      <td className="p-4">
                        {st.term_average !== undefined && st.term_average !== null ? (
                          <span className="font-bold text-foreground">{st.term_average}%</span>
                        ) : (
                          <span className="text-xs text-muted-foreground">Not evaluated</span>
                        )}
                      </td>
                      <td className="p-4">
                        {st.gpa !== undefined && st.gpa !== null ? (
                          <Badge className="bg-primary/10 font-mono font-bold text-primary">
                            {st.gpa.toFixed(1)}
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
                        {st.subjects?.length || 0}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

/** The single-student view - unchanged in substance, just no longer asked about the
 *  wrong student. */
function StudentDetail({ studentId, term }: { studentId: number; term: string }) {
  const { data: analytics, isLoading, isError } = useStudentAnalytics(studentId, term);

  if (isError) {
    return (
      <div className="rounded-xl border bg-card py-16 text-center" role="alert">
        <p className="text-sm font-medium text-[hsl(var(--urgent))]">
          Could not load analytics for this student.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">Reload the page, or try again in a moment.</p>
      </div>
    );
  }
  if (isLoading) {
    return <div className="py-16 text-center text-muted-foreground">Loading analytics...</div>;
  }
  if (!analytics) {
    return <div className="py-16 text-center text-muted-foreground">No analytics data available.</div>;
  }

  return (
    <div className="space-y-6">
      {analytics.risk_status?.is_at_risk ? (
        <div className="flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-500/10 p-4 text-amber-900 shadow-xs dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
          <div>
            <h3 className="text-sm font-bold">{analytics.risk_status.banner_message}</h3>
            <p className="mt-1 text-xs text-amber-800 dark:text-amber-300">
              {analytics.risk_status.reasons?.join(" · ") ||
                "Attendance or subject scores are trending below optimal thresholds. Connect with your class teacher for support."}
            </p>
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-3 rounded-xl border border-emerald-300 bg-emerald-500/10 p-3.5 text-emerald-900 dark:text-emerald-200">
          <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-600" />
          <span className="text-xs font-semibold">
            Academic standing is in good health with high attendance consistency!
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card className="border shadow-xs">
          <CardContent className="flex items-center gap-4 p-5">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
              <Award className="h-6 w-6" />
            </div>
            <div>
              <span className="text-xs text-muted-foreground">Cumulative GPA</span>
              <p className="text-2xl font-bold text-foreground">
                {analytics.gradebook?.gpa !== undefined && analytics.gradebook?.gpa !== null
                  ? `${analytics.gradebook.gpa.toFixed(1)} / 4.0`
                  : "—"}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="border shadow-xs">
          <CardContent className="flex items-center gap-4 p-5">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-600">
              <Calendar className="h-6 w-6" />
            </div>
            <div>
              {/* Labelled with its window: this is the rolling 30-day figure, the same one
                  the parent portal shows. The report card deliberately shows the academic
                  year instead, so both carry their label. */}
              <span className="text-xs text-muted-foreground">
                {analytics.attendance?.window_label ?? "Attendance Rate"}
              </span>
              <p className="text-2xl font-bold text-emerald-600">
                {analytics.attendance?.percentage == null
                  ? "—"
                  : `${analytics.attendance.percentage}%`}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="border shadow-xs">
          <CardContent className="flex items-center gap-4 p-5">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-500/10 text-blue-600">
              <FileCheck className="h-6 w-6" />
            </div>
            <div>
              <span className="text-xs text-muted-foreground">Assignments Done</span>
              <p className="text-2xl font-bold text-foreground">
                {analytics.assignments?.submitted_count} / {analytics.assignments?.total_submissions}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="border shadow-xs">
          <CardContent className="flex items-center gap-4 p-5">
            <div className="flex h-12 w-12 items-center justify-center rounded-xl bg-purple-500/10 text-purple-600">
              <HelpCircle className="h-6 w-6" />
            </div>
            <div>
              <span className="text-xs text-muted-foreground">Quizzes Attempted</span>
              <p className="text-2xl font-bold text-foreground">{analytics.quizzes?.total_attempts}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card className="border shadow-xs">
          <CardContent className="space-y-4 p-5">
            <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
              <BookOpen className="h-4 w-4 text-primary" />
              Subject Performance Breakdown
            </h3>

            <div className="space-y-3">
              {analytics.gradebook?.subjects?.length === 0 ? (
                <p className="py-4 text-center text-xs text-muted-foreground">
                  No subject evaluations available.
                </p>
              ) : (
                analytics.gradebook?.subjects?.map((s) => (
                  <div key={s.subject_id} className="space-y-1.5">
                    <div className="flex items-center justify-between text-xs">
                      <span className="font-semibold text-foreground">{s.subject_name}</span>
                      <span className="font-bold text-primary">
                        {s.percentage !== undefined && s.percentage !== null
                          ? `${s.percentage}% (GPA ${s.gpa?.toFixed(1)})`
                          : "—"}
                      </span>
                    </div>
                    <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-2 rounded-full bg-primary transition-all"
                        style={{ width: `${s.percentage || 0}%` }}
                      />
                    </div>
                  </div>
                ))
              )}
            </div>
          </CardContent>
        </Card>

        <Card className="border shadow-xs">
          <CardContent className="space-y-4 p-5">
            <h3 className="flex items-center gap-2 text-sm font-bold text-foreground">
              <TrendingUp className="h-4 w-4 text-emerald-600" />
              Monthly Score & Attendance Trend
            </h3>

            <div className="grid grid-cols-5 gap-2 pt-4">
              {analytics.trend?.map((t) => (
                <div key={t.month} className="flex flex-col items-center space-y-2 text-xs">
                  <div className="relative flex h-32 w-full flex-col items-center justify-end overflow-hidden rounded-lg bg-muted/40 p-1.5">
                    <div
                      className="mb-1 w-full rounded-t bg-emerald-500/30 transition-all"
                      style={{ height: `${t.attendance}%` }}
                      title={`Attendance: ${t.attendance}%`}
                    />
                    <div
                      className="w-full rounded-t bg-primary transition-all"
                      style={{ height: `${t.score}%` }}
                      title={`Score: ${t.score}%`}
                    />
                  </div>
                  <span className="font-semibold text-foreground">{t.month}</span>
                  <span className="text-[10px] text-muted-foreground">{t.score}%</span>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-center gap-4 border-t pt-2 text-xs text-muted-foreground">
              <div className="flex items-center gap-1.5">
                <div className="h-2.5 w-2.5 rounded-full bg-primary" />
                <span>Academic Score</span>
              </div>
              <div className="flex items-center gap-1.5">
                <div className="h-2.5 w-2.5 rounded-full bg-emerald-500/40" />
                <span>Attendance %</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default function StudentAnalyticsPage() {
  const { role } = useAuthStore();
  const isStaff = role === "admin" || role === "principal" || role === "teacher";

  const [selectedTerm, setSelectedTerm] = useState("Term 1");
  // Staff drill down class -> student. Students and parents never see these controls;
  // useViewedStudent resolves them from their own identity / selected child.
  const [pickedClassId, setPickedClassId] = useState<number | "">("");
  const [pickedStudentId, setPickedStudentId] = useState<number | "">("");

  const viewed = useViewedStudent(
    typeof pickedStudentId === "number" ? pickedStudentId : undefined,
  );
  const parentChildren = useSelectedChild({ enabled: role === "parent" });

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-foreground">
            <TrendingUp className="h-7 w-7 text-primary" />
            {isStaff ? "Academic Analytics" : "Student Personal Analytics"}
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {isStaff
              ? "Class-wide performance roll-ups, and per-student academic, attendance and risk detail."
              : "Holistic academic performance, attendance metrics, coursework completion, and risk status."}
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
        </div>
      </div>

      {/* Staff: class then student. Laid out across the top rather than inside a dialog so
          the current scope is always visible beside the numbers it produced. */}
      {isStaff && (
        <Card className="border shadow-xs">
          <CardContent className="p-4">
            <div className="max-w-md">
              <StudentPicker
                label="Choose a class section, then a student (optional)"
                classId={pickedClassId}
                studentId={pickedStudentId}
                onClassChange={setPickedClassId}
                onStudentChange={setPickedStudentId}
              />
            </div>
          </CardContent>
        </Card>
      )}

      {/* Parent with several children keeps the existing child selector. */}
      {role === "parent" && parentChildren.showSelector && (
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold text-muted-foreground">Child</span>
          <select
            value={String(parentChildren.selectedChildId ?? "")}
            onChange={(e) => parentChildren.setSelectedChildId(Number(e.target.value))}
            className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium"
          >
            {parentChildren.children.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
                {c.class_name ? ` · ${c.class_name}` : ""}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* One student chosen (or resolved) wins; otherwise staff get the class roll-up.
          THE OLD PAGE HAD NEITHER: it requested analytics for `Number(user.id) || 2`, so an
          admin always saw "Could not load analytics for this student" and had no control to
          pick anybody. */}
      {viewed.studentId !== undefined ? (
        <StudentDetail studentId={viewed.studentId} term={selectedTerm} />
      ) : typeof pickedClassId === "number" ? (
        <ClassOverview classId={pickedClassId} term={selectedTerm} />
      ) : viewed.isLoading ? (
        <div className="py-16 text-center text-muted-foreground">Loading…</div>
      ) : role === "parent" && parentChildren.children.length === 0 ? (
        <div className="rounded-xl border bg-card py-16 text-center">
          <Users className="mx-auto mb-3 h-10 w-10 text-muted-foreground/50" />
          <h3 className="font-semibold text-foreground">No linked children</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Ask the school office to link your account to your child's record.
          </p>
        </div>
      ) : (
        <div className="rounded-xl border bg-card py-16 text-center">
          <UserSearch className="mx-auto mb-3 h-10 w-10 text-muted-foreground/50" />
          <h3 className="font-semibold text-foreground">Choose a class section to begin</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            You'll see the whole section's performance, then can drill into any student.
          </p>
        </div>
      )}
    </div>
  );
}
