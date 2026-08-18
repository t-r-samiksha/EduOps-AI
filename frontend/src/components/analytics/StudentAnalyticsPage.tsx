import { useState } from "react";
import {
  TrendingUp,
  Award,
  AlertTriangle,
  CheckCircle2,
  Calendar,
  BookOpen,
  FileCheck,
  HelpCircle,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { useStudentAnalytics } from "@/api/hooks/useStudentAnalytics";
import { useAuthStore } from "@/store/authStore";

export default function StudentAnalyticsPage() {
  const { user } = useAuthStore();
  const studentId = user?.id ? Number(user.id) || 2 : 2;

  const [selectedTerm, setSelectedTerm] = useState("Term 1");
  const { data: analytics, isLoading, isError } = useStudentAnalytics(studentId, selectedTerm);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <TrendingUp className="h-7 w-7 text-primary" />
            Student Personal Analytics
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Holistic academic performance, attendance metrics, coursework completion, and risk status.
          </p>
        </div>

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
      </div>

      {isError ? (
        <div className="py-16 text-center border rounded-xl bg-card" role="alert">
          <p className="text-sm font-medium text-[hsl(var(--urgent))]">Could not load analytics for this student.</p>
          <p className="mt-1 text-xs text-muted-foreground">
            Reload the page, or try again in a moment.
          </p>
        </div>
      ) : isLoading ? (
        <div className="py-16 text-center text-muted-foreground">Loading analytics...</div>
      ) : !analytics ? (
        <div className="py-16 text-center text-muted-foreground">No analytics data available.</div>
      ) : (
        <div className="space-y-6">
          {/* Person A Risk Flag Banner */}
          {analytics.risk_status?.is_at_risk ? (
            <div className="p-4 rounded-xl border border-amber-300 bg-amber-500/10 text-amber-900 dark:text-amber-200 flex items-start gap-3 shadow-xs">
              <AlertTriangle className="h-5 w-5 text-amber-600 shrink-0 mt-0.5" />
              <div>
                <h3 className="font-bold text-sm">
                  {analytics.risk_status.banner_message}
                </h3>
                <p className="text-xs mt-1 text-amber-800 dark:text-amber-300">
                  {analytics.risk_status.reasons?.join(" · ") ||
                    "Attendance or subject scores are trending below optimal thresholds. Connect with your class teacher for support."}
                </p>
              </div>
            </div>
          ) : (
            <div className="p-3.5 rounded-xl border border-emerald-300 bg-emerald-500/10 text-emerald-900 dark:text-emerald-200 flex items-center gap-3">
              <CheckCircle2 className="h-5 w-5 text-emerald-600 shrink-0" />
              <span className="text-xs font-semibold">
                Academic standing is in good health with high attendance consistency!
              </span>
            </div>
          )}

          {/* Top Metric Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <Card className="border shadow-xs">
              <CardContent className="p-5 flex items-center gap-4">
                <div className="h-12 w-12 rounded-xl bg-primary/10 text-primary flex items-center justify-center">
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
              <CardContent className="p-5 flex items-center gap-4">
                <div className="h-12 w-12 rounded-xl bg-emerald-500/10 text-emerald-600 flex items-center justify-center">
                  <Calendar className="h-6 w-6" />
                </div>
                <div>
                  {/* Labelled with its window: this is the rolling 30-day figure, the
                      same one the parent portal shows. The report card deliberately
                      shows the academic year instead, so both carry their label. */}
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
              <CardContent className="p-5 flex items-center gap-4">
                <div className="h-12 w-12 rounded-xl bg-blue-500/10 text-blue-600 flex items-center justify-center">
                  <FileCheck className="h-6 w-6" />
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Assignments Done</span>
                  <p className="text-2xl font-bold text-foreground">
                    {analytics.assignments?.submitted_count} /{" "}
                    {analytics.assignments?.total_submissions}
                  </p>
                </div>
              </CardContent>
            </Card>

            <Card className="border shadow-xs">
              <CardContent className="p-5 flex items-center gap-4">
                <div className="h-12 w-12 rounded-xl bg-purple-500/10 text-purple-600 flex items-center justify-center">
                  <HelpCircle className="h-6 w-6" />
                </div>
                <div>
                  <span className="text-xs text-muted-foreground">Quizzes Attempted</span>
                  <p className="text-2xl font-bold text-foreground">
                    {analytics.quizzes?.total_attempts}
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Subject Performance & Progress Trend */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
            {/* Subject Breakdown Card */}
            <Card className="border shadow-xs">
              <CardContent className="p-5 space-y-4">
                <h3 className="font-bold text-sm text-foreground flex items-center gap-2">
                  <BookOpen className="h-4 w-4 text-primary" />
                  Subject Performance Breakdown
                </h3>

                <div className="space-y-3">
                  {analytics.gradebook?.subjects?.length === 0 ? (
                    <p className="text-xs text-muted-foreground py-4 text-center">
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
                        <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
                          <div
                            className="bg-primary h-2 rounded-full transition-all"
                            style={{ width: `${s.percentage || 0}%` }}
                          />
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </CardContent>
            </Card>

            {/* Performance Trend Card */}
            <Card className="border shadow-xs">
              <CardContent className="p-5 space-y-4">
                <h3 className="font-bold text-sm text-foreground flex items-center gap-2">
                  <TrendingUp className="h-4 w-4 text-emerald-600" />
                  Monthly Score & Attendance Trend
                </h3>

                <div className="grid grid-cols-5 gap-2 pt-4">
                  {analytics.trend?.map((t) => (
                    <div key={t.month} className="flex flex-col items-center space-y-2 text-xs">
                      <div className="h-32 w-full bg-muted/40 rounded-lg flex flex-col justify-end p-1.5 items-center relative overflow-hidden">
                        {/* Attendance Bar */}
                        <div
                          className="w-full bg-emerald-500/30 rounded-t mb-1 transition-all"
                          style={{ height: `${t.attendance}%` }}
                          title={`Attendance: ${t.attendance}%`}
                        />
                        {/* Score Bar */}
                        <div
                          className="w-full bg-primary rounded-t transition-all"
                          style={{ height: `${t.score}%` }}
                          title={`Score: ${t.score}%`}
                        />
                      </div>
                      <span className="font-semibold text-foreground">{t.month}</span>
                      <span className="text-[10px] text-muted-foreground">{t.score}%</span>
                    </div>
                  ))}
                </div>

                <div className="flex items-center justify-center gap-4 text-xs text-muted-foreground pt-2 border-t">
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
      )}
    </div>
  );
}
