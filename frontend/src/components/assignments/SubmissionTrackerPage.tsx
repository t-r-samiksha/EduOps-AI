import { useState, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import {
  FileCheck,
  Search,
  ArrowLeft,
  Download,
  Award,
  BellRing,
  CheckCircle2,
  AlertCircle,
  XCircle,
  Clock,
  X,
  FileText,
  Users,
  Check,
  ArrowUpDown,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  useAssignmentDetail,
  useAssignmentSubmissions,
  useGradeSubmission,
  useNudgeStudent,
  useNudgeAllMissing,
} from "@/api/hooks/useAssignments";
import { useAuthStore } from "@/store/authStore";
import { timeAgo } from "@/lib/format";
import type { SubmissionItem, SubmissionStatus } from "@/api/types";

function getStatusBadge(status?: SubmissionStatus | string) {
  switch (status) {
    case "graded":
      return { label: "Graded", icon: Award, color: "bg-blue-500/15 text-blue-400 border-blue-500/30" };
    case "submitted":
      return { label: "Submitted", icon: CheckCircle2, color: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" };
    case "late":
      return { label: "Late", icon: AlertCircle, color: "bg-amber-500/15 text-amber-400 border-amber-500/30" };
    case "missing":
      return { label: "Missing", icon: XCircle, color: "bg-red-500/15 text-red-400 border-red-500/30" };
    default:
      return { label: "Pending", icon: Clock, color: "bg-ink-muted/15 text-ink-muted border-border" };
  }
}

type SortField = "name" | "status" | "submitted_at" | "grade";
type SortOrder = "asc" | "desc";

export default function SubmissionTrackerPage() {
  const { id } = useParams<{ id: string }>();
  const assignmentId = id ? Number(id) : undefined;
  const { role } = useAuthStore();

  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState<string | "all">("all");
  const [sortField, setSortField] = useState<SortField>("name");
  const [sortOrder, setSortOrder] = useState<SortOrder>("asc");

  // Grading Modal state
  const [gradingSubmission, setGradingSubmission] = useState<SubmissionItem | null>(null);
  const [gradeInput, setGradeInput] = useState("");
  const [feedbackInput, setFeedbackInput] = useState("");

  // Nudge Feedback Tracker
  const [nudgedStudents, setNudgedStudents] = useState<Set<number>>(new Set());
  const [bulkNudgeSuccess, setBulkNudgeSuccess] = useState(false);

  // Queries & Mutations
  const assignmentQuery = useAssignmentDetail(assignmentId);
  const submissionsQuery = useAssignmentSubmissions(assignmentId);
  const gradeMutation = useGradeSubmission(assignmentId);
  const nudgeMutation = useNudgeStudent(assignmentId);
  const bulkNudgeMutation = useNudgeAllMissing(assignmentId);

  const assignment = assignmentQuery.data;
  const rawSubmissions = submissionsQuery.data || [];

  // Filter & Sort Submissions
  const submissions = useMemo(() => {
    return rawSubmissions
      .filter((s) => {
        if (searchQuery.trim()) {
          const q = searchQuery.toLowerCase();
          const matches =
            (s.student_name && s.student_name.toLowerCase().includes(q)) ||
            (s.student_email && s.student_email.toLowerCase().includes(q));
          if (!matches) return false;
        }
        if (statusFilter !== "all") {
          if (s.status !== statusFilter) return false;
        }
        return true;
      })
      .sort((a, b) => {
        let cmp = 0;
        if (sortField === "name") {
          cmp = (a.student_name || "").localeCompare(b.student_name || "");
        } else if (sortField === "status") {
          cmp = a.status.localeCompare(b.status);
        } else if (sortField === "submitted_at") {
          const tA = a.submitted_at ? new Date(a.submitted_at).getTime() : 0;
          const tB = b.submitted_at ? new Date(b.submitted_at).getTime() : 0;
          cmp = tA - tB;
        } else if (sortField === "grade") {
          const gA = a.grade ?? -1;
          const gB = b.grade ?? -1;
          cmp = gA - gB;
        }
        return sortOrder === "asc" ? cmp : -cmp;
      });
  }, [rawSubmissions, searchQuery, statusFilter, sortField, sortOrder]);

  const stats = useMemo(() => {
    const total = rawSubmissions.length;
    const submitted = rawSubmissions.filter((s) => s.status === "submitted" || s.status === "graded").length;
    const late = rawSubmissions.filter((s) => s.status === "late").length;
    const missing = rawSubmissions.filter((s) => s.status === "missing" || s.status === "pending").length;
    const graded = rawSubmissions.filter((s) => s.status === "graded" || s.grade !== null).length;

    const grades = rawSubmissions.map((s) => s.grade).filter((g): g is number => g !== null && g !== undefined);
    const avg = grades.length > 0 ? (grades.reduce((a, b) => a + b, 0) / grades.length).toFixed(1) : null;

    return { total, submitted, late, missing, graded, avg };
  }, [rawSubmissions]);

  const handleSaveGrade = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!gradingSubmission || !assignment) return;

    const g = parseFloat(gradeInput);
    if (isNaN(g) || g < 0 || g > assignment.max_marks) return;

    await gradeMutation.mutateAsync({
      submissionId: gradingSubmission.id,
      data: {
        grade: g,
        feedback: feedbackInput.trim() || undefined,
      },
    });

    setGradingSubmission(null);
    setGradeInput("");
    setFeedbackInput("");
  };

  const handleNudgeStudent = async (studentId: number) => {
    await nudgeMutation.mutateAsync(studentId);
    setNudgedStudents((prev) => new Set(prev).add(studentId));
  };

  const handleBulkNudge = async () => {
    await bulkNudgeMutation.mutateAsync();
    setBulkNudgeSuccess(true);
    setTimeout(() => setBulkNudgeSuccess(false), 4000);
  };

  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortOrder((prev) => (prev === "asc" ? "desc" : "asc"));
    } else {
      setSortField(field);
      setSortOrder("asc");
    }
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Back Link & Navigation */}
      <div className="flex items-center justify-between gap-4">
        <Link
          to={`/${role}/assignments`}
          className="inline-flex items-center gap-1.5 text-xs font-medium text-ink-muted hover:text-ink transition-colors"
        >
          <ArrowLeft className="h-4 w-4" />
          <span>Back to Assignments</span>
        </Link>
      </div>

      {/* Main Page Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <Badge variant="neutral" className="text-xs">
              {assignment?.class_name || "Class Section"}
            </Badge>
            {assignment?.subject_name && (
              <Badge variant="outline" className="text-xs">
                {assignment.subject_name}
              </Badge>
            )}
            <Badge variant="outline" className="text-xs font-semibold text-accent border-accent/30">
              Max {assignment?.max_marks || 100} Marks
            </Badge>
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-ink">
            {assignment?.title || "Submission Tracker"}
          </h1>
          {assignment?.deadline && (
            <p className="text-xs text-ink-muted mt-1 flex items-center gap-1.5">
              <Clock className="h-3.5 w-3.5 text-amber-400" />
              <span>Due {new Date(assignment.deadline).toLocaleString()}</span>
            </p>
          )}
        </div>

        {/* Header Action Buttons */}
        <div className="flex items-center gap-2">
          {stats.missing > 0 && (
            <Button
              size="sm"
              variant="outline"
              onClick={handleBulkNudge}
              disabled={bulkNudgeMutation.isPending || bulkNudgeSuccess}
              className="gap-1.5 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
            >
              {bulkNudgeSuccess ? (
                <>
                  <Check className="h-4 w-4 text-emerald-400" />
                  Nudges Dispatched!
                </>
              ) : (
                <>
                  <BellRing className="h-4 w-4" />
                  Nudge Missing ({stats.missing})
                </>
              )}
            </Button>
          )}
        </div>
      </div>

      {/* Metric Summary Cards */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
        <Card className="bg-surface border-border p-4 flex flex-col justify-between">
          <span className="text-xs text-ink-muted flex items-center gap-1">
            <Users className="h-3.5 w-3.5" /> Enrolled
          </span>
          <strong className="text-2xl font-bold text-ink mt-1">{stats.total}</strong>
          <span className="text-[11px] text-ink-muted">Total students</span>
        </Card>

        <Card className="bg-surface border-border p-4 flex flex-col justify-between">
          <span className="text-xs text-emerald-400 flex items-center gap-1">
            <CheckCircle2 className="h-3.5 w-3.5" /> Submitted
          </span>
          <strong className="text-2xl font-bold text-emerald-400 mt-1">{stats.submitted}</strong>
          <span className="text-[11px] text-ink-muted">
            {stats.total > 0 ? Math.round((stats.submitted / stats.total) * 100) : 0}% turn-in rate
          </span>
        </Card>

        <Card className="bg-surface border-border p-4 flex flex-col justify-between">
          <span className="text-xs text-amber-400 flex items-center gap-1">
            <AlertCircle className="h-3.5 w-3.5" /> Late
          </span>
          <strong className="text-2xl font-bold text-amber-400 mt-1">{stats.late}</strong>
          <span className="text-[11px] text-ink-muted">Past deadline</span>
        </Card>

        <Card className="bg-surface border-border p-4 flex flex-col justify-between">
          <span className="text-xs text-red-400 flex items-center gap-1">
            <XCircle className="h-3.5 w-3.5" /> Missing
          </span>
          <strong className="text-2xl font-bold text-red-400 mt-1">{stats.missing}</strong>
          <span className="text-[11px] text-ink-muted">Awaiting submission</span>
        </Card>

        <Card className="bg-surface border-border p-4 flex flex-col justify-between col-span-2 sm:col-span-1">
          <span className="text-xs text-blue-400 flex items-center gap-1">
            <Award className="h-3.5 w-3.5" /> Graded Avg
          </span>
          <strong className="text-2xl font-bold text-blue-400 mt-1">
            {stats.avg !== null ? `${stats.avg} / ${assignment?.max_marks || 100}` : "—"}
          </strong>
          <span className="text-[11px] text-ink-muted">{stats.graded} of {stats.submitted} evaluated</span>
        </Card>
      </div>

      {/* Filter and Search Toolbar */}
      <Card className="border-border bg-surface">
        <CardContent className="p-4 flex flex-col gap-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="relative flex-1 min-w-[220px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-ink-muted" />
              <Input
                placeholder="Search student by name or email..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-9 pr-8 text-sm"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              )}
            </div>

            {/* Status Filters */}
            <div className="flex items-center gap-1 text-xs">
              {[
                { id: "all", label: "All" },
                { id: "submitted", label: "Submitted" },
                { id: "late", label: "Late" },
                { id: "missing", label: "Missing" },
                { id: "graded", label: "Graded" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setStatusFilter(tab.id)}
                  className={`px-3 py-1.5 rounded-lg transition-colors ${
                    statusFilter === tab.id
                      ? "bg-accent text-accent-foreground font-semibold"
                      : "bg-elevated/60 text-ink-muted hover:text-ink"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Submissions Tracker Table */}
      <Card className="border-border bg-surface shadow-sm overflow-hidden">
        {submissionsQuery.isError ? (
          <div className="p-6 text-center" role="alert">
            <p className="text-sm font-medium text-[hsl(var(--urgent))]">Could not load submissions for this assignment.</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Reload the page, or try again in a moment.
            </p>
          </div>
        ) : submissionsQuery.isLoading ? (
          <div className="p-6 flex flex-col gap-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-12 bg-elevated/40 rounded-xl animate-pulse" />
            ))}
          </div>
        ) : submissions.length === 0 ? (
          <div className="p-12 text-center text-ink-muted text-sm">
            <FileCheck className="h-8 w-8 mx-auto text-ink-faint mb-2" />
            <p className="font-semibold text-ink">No matching students found</p>
            <p className="text-xs mt-1">Try adjusting your search query or status filter.</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-elevated/40 text-xs font-semibold text-ink-muted border-b border-border">
                <tr>
                  <th scope="col"
                    className="p-3.5 cursor-pointer hover:text-ink transition-colors"
                    onClick={() => toggleSort("name")}
                  >
                    <div className="flex items-center gap-1.5">
                      <span>Student</span>
                      <ArrowUpDown className="h-3 w-3" />
                    </div>
                  </th>
                  <th scope="col"
                    className="p-3.5 cursor-pointer hover:text-ink transition-colors"
                    onClick={() => toggleSort("status")}
                  >
                    <div className="flex items-center gap-1.5">
                      <span>Status</span>
                      <ArrowUpDown className="h-3 w-3" />
                    </div>
                  </th>
                  <th scope="col"
                    className="p-3.5 cursor-pointer hover:text-ink transition-colors"
                    onClick={() => toggleSort("submitted_at")}
                  >
                    <div className="flex items-center gap-1.5">
                      <span>Submitted At</span>
                      <ArrowUpDown className="h-3 w-3" />
                    </div>
                  </th>
                  <th scope="col"
                    className="p-3.5 cursor-pointer hover:text-ink transition-colors"
                    onClick={() => toggleSort("grade")}
                  >
                    <div className="flex items-center gap-1.5">
                      <span>Grade</span>
                      <ArrowUpDown className="h-3 w-3" />
                    </div>
                  </th>
                  <th scope="col" className="p-3.5 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {submissions.map((s) => {
                  const statusBadge = getStatusBadge(s.status);
                  const StatusIcon = statusBadge.icon;
                  const isNudged = nudgedStudents.has(s.student_id);
                  const hasSubmission = s.status === "submitted" || s.status === "late" || s.status === "graded";

                  return (
                    <tr key={s.student_id} className="hover:bg-elevated/20 transition-colors">
                      {/* Student Info */}
                      <td className="p-3.5">
                        <div className="flex items-center gap-3">
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent font-semibold text-xs">
                            {s.student_name ? s.student_name.slice(0, 2).toUpperCase() : "ST"}
                          </div>
                          <div className="flex flex-col min-w-0">
                            <span className="font-semibold text-ink truncate">
                              {s.student_name || "Student"}
                            </span>
                            <span className="text-xs text-ink-muted truncate">{s.student_email}</span>
                          </div>
                        </div>
                      </td>

                      {/* Status */}
                      <td className="p-3.5">
                        <Badge className={`gap-1 text-xs py-0.5 px-2 border ${statusBadge.color}`}>
                          <StatusIcon className="h-3 w-3" />
                          {statusBadge.label}
                        </Badge>
                      </td>

                      {/* Submitted At */}
                      <td className="p-3.5 text-xs text-ink-muted">
                        {s.submitted_at ? (
                          <div className="flex flex-col">
                            <span className="text-ink font-medium">
                              {new Date(s.submitted_at).toLocaleDateString(undefined, {
                                month: "short",
                                day: "numeric",
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </span>
                            <span className="text-[11px] text-ink-faint">{timeAgo(s.submitted_at)}</span>
                          </div>
                        ) : (
                          <span className="text-ink-faint">Not submitted</span>
                        )}
                      </td>

                      {/* Grade */}
                      <td className="p-3.5">
                        {s.grade !== null && s.grade !== undefined ? (
                          <div className="flex items-center gap-1.5 text-xs">
                            <span className="font-bold text-emerald-400 bg-emerald-500/10 px-2 py-0.5 rounded-lg border border-emerald-500/20">
                              {s.grade} / {assignment?.max_marks || 100}
                            </span>
                            <span className="text-[11px] text-ink-muted">
                              ({Math.round((s.grade / (assignment?.max_marks || 100)) * 100)}%)
                            </span>
                          </div>
                        ) : hasSubmission ? (
                          <span className="text-xs text-amber-400 font-medium bg-amber-500/10 px-2 py-0.5 rounded-lg border border-amber-500/20">
                            Ungraded
                          </span>
                        ) : (
                          <span className="text-xs text-ink-faint">—</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="p-3.5 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {/* View / Download Submission File */}
                          {s.file_url ? (
                            <a
                              href={s.file_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg bg-elevated hover:bg-elevated/80 text-ink border border-border transition-colors"
                              title="Download student submission"
                            >
                              <Download className="h-3.5 w-3.5 text-accent" />
                              <span>View File</span>
                            </a>
                          ) : null}

                          {/* Grade Button */}
                          {hasSubmission && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => {
                                setGradingSubmission(s);
                                setGradeInput(s.grade?.toString() || "");
                                setFeedbackInput(s.feedback || "");
                              }}
                              className="text-xs h-8 gap-1"
                            >
                              <Award className="h-3.5 w-3.5 text-accent" />
                              {s.grade !== null ? "Edit Grade" : "Grade"}
                            </Button>
                          )}

                          {/* Nudge Button (for unsubmitted / missing students) */}
                          {!hasSubmission && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleNudgeStudent(s.student_id)}
                              disabled={nudgeMutation.isPending || isNudged}
                              className="text-xs h-8 gap-1 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
                            >
                              {isNudged ? (
                                <>
                                  <Check className="h-3.5 w-3.5 text-emerald-400" />
                                  Nudged
                                </>
                              ) : (
                                <>
                                  <BellRing className="h-3.5 w-3.5" />
                                  Nudge
                                </>
                              )}
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {/* Grading Dialog */}
      <Dialog
        open={gradingSubmission !== null}
        onOpenChange={(open) => {
          if (!open) setGradingSubmission(null);
        }}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Award className="h-5 w-5 text-accent" />
              <span>Grade Submission: {gradingSubmission?.student_name}</span>
            </DialogTitle>
          </DialogHeader>

          {gradingSubmission && assignment && (
            <form onSubmit={handleSaveGrade} className="flex flex-col gap-4 mt-2">
              {gradingSubmission.file_url && (
                <div className="flex items-center justify-between p-3 rounded-xl bg-elevated/40 border border-border text-xs">
                  <div className="flex items-center gap-2 truncate">
                    <FileText className="h-4 w-4 text-accent shrink-0" />
                    <span className="truncate">{gradingSubmission.file_name || "Submission File"}</span>
                  </div>
                  <a
                    href={gradingSubmission.file_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-accent hover:underline flex items-center gap-1 shrink-0"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Download
                  </a>
                </div>
              )}

              <div>
                <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                  Marks Obtained (Max {assignment.max_marks}) *
                </label>
                <Input
                  type="number"
                  min="0"
                  max={assignment.max_marks}
                  step="0.5"
                  placeholder="e.g. 85"
                  value={gradeInput}
                  onChange={(e) => setGradeInput(e.target.value)}
                  required
                  autoFocus
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                  Teacher Feedback / Assessment Remarks
                </label>
                <Input
                  placeholder="e.g. Great clarity in proofs. Review question 4 calculation."
                  value={feedbackInput}
                  onChange={(e) => setFeedbackInput(e.target.value)}
                />
              </div>

              <div className="flex justify-end gap-2 pt-2 border-t border-border">
                <Button type="button" variant="ghost" onClick={() => setGradingSubmission(null)}>
                  Cancel
                </Button>
                <Button type="submit" disabled={gradeMutation.isPending || !gradeInput} className="gap-1.5">
                  <CheckCircle2 className="h-4 w-4" />
                  {gradeMutation.isPending ? "Saving..." : "Save Grade & Notify"}
                </Button>
              </div>
            </form>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
