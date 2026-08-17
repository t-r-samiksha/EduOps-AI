import { useState, useMemo } from "react";
import { useParams, Link } from "react-router-dom";
import {
  FileCheck,
  Search,
  Plus,
  Download,
  Trash2,
  FileText,
  Clock,
  CheckCircle2,
  AlertCircle,
  XCircle,
  Award,
  UploadCloud,
  Send,
  Sparkles,
  UserCheck,
  MessageSquare,
  X,
} from "lucide-react";
import PageHeader from "@/components/shared/PageHeader";
import ConfirmDialog from "@/components/shared/ConfirmDialog";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import {
  useAssignments,
  useClassAssignments,
  useAssignmentSubmissions,
  useCreateAssignment,
  useSubmitAssignment,
  useGradeSubmission,
  useUploadAssignmentFile,
  useDeleteAssignment,
} from "@/api/hooks/useAssignments";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useAuthStore } from "@/store/authStore";
import { timeAgo } from "@/lib/format";
import type { AssignmentItem, SubmissionItem, SubmissionStatus } from "@/api/types";

function getStatusBadge(status?: SubmissionStatus | string) {
  switch (status) {
    case "graded":
      return { label: "Graded", icon: Award, color: "bg-blue-500/15 text-blue-400 border-blue-500/30" };
    case "submitted":
      return { label: "Submitted", icon: CheckCircle2, color: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30" };
    case "late":
      return { label: "Late Submission", icon: AlertCircle, color: "bg-amber-500/15 text-amber-400 border-amber-500/30" };
    case "missing":
      return { label: "Missing", icon: XCircle, color: "bg-red-500/15 text-red-400 border-red-500/30" };
    default:
      return { label: "Pending", icon: Clock, color: "bg-ink-muted/15 text-ink-muted border-border" };
  }
}

function formatDeadline(iso: string) {
  const d = new Date(iso);
  const now = new Date();
  const diffMs = d.getTime() - now.getTime();
  const diffDays = Math.ceil(diffMs / (1000 * 60 * 60 * 24));

  let relative = "";
  if (diffMs < 0) {
    relative = `Expired ${timeAgo(iso)}`;
  } else if (diffDays === 0) {
    relative = "Due today";
  } else if (diffDays === 1) {
    relative = "Due tomorrow";
  } else {
    relative = `Due in ${diffDays} days`;
  }

  return {
    formatted: d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }),
    relative,
    isPast: diffMs < 0,
  };
}

export default function AssignmentsPage() {
  const params = useParams<{ classId?: string }>();
  const classIdFromRoute = params.classId ? Number(params.classId) : undefined;

  const { role } = useAuthStore();
  const currentUser = useCurrentUser().data;
  const lookup = useReferenceLookup(currentUser?.school_id);

  // Filters
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedClassId, setSelectedClassId] = useState<number | undefined>(classIdFromRoute);
  const [selectedSubjectId, setSelectedSubjectId] = useState<number | undefined>(undefined);
  const [statusFilter, setStatusFilter] = useState<string | "all">("all");

  // Query
  const assignmentsQuery = selectedClassId
    ? useClassAssignments(selectedClassId, selectedSubjectId)
    : useAssignments(selectedSubjectId);

  const rawAssignments = assignmentsQuery.data || [];

  // Filter items
  const assignments = useMemo(() => {
    return rawAssignments.filter((a) => {
      if (selectedClassId && a.class_id !== selectedClassId) return false;
      if (selectedSubjectId && a.subject_id !== selectedSubjectId) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matches =
          a.title.toLowerCase().includes(q) ||
          (a.description && a.description.toLowerCase().includes(q)) ||
          (a.subject_name && a.subject_name.toLowerCase().includes(q));
        if (!matches) return false;
      }
      if (statusFilter !== "all") {
        const studentStatus = a.my_submission?.status || "pending";
        if (studentStatus !== statusFilter) return false;
      }
      return true;
    });
  }, [rawAssignments, selectedClassId, selectedSubjectId, searchQuery, statusFilter]);

  // Create Assignment Dialog state (Teacher / Admin)
  const [createOpen, setCreateOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [desc, setDesc] = useState("");
  const [classId, setClassId] = useState<number | "">("");
  const [subjectId, setSubjectId] = useState<number | "">("");
  const [deadline, setDeadline] = useState("");
  const [maxMarks, setMaxMarks] = useState("100");
  const [attachmentFile, setAttachmentFile] = useState<File | null>(null);

  // Submission Queue & Grading Drawer (Teacher)
  const [activeQueueAssignment, setActiveQueueAssignment] = useState<AssignmentItem | null>(null);

  // Submit Homework Dialog (Student)
  const [activeSubmitAssignment, setActiveSubmitAssignment] = useState<AssignmentItem | null>(null);
  const [submissionFile, setSubmissionFile] = useState<File | null>(null);

  // Individual Grading Popover state
  const [gradingSubmission, setGradingSubmission] = useState<SubmissionItem | null>(null);
  const [gradeInput, setGradeInput] = useState("");
  const [feedbackInput, setFeedbackInput] = useState("");

  const createMutation = useCreateAssignment();
  const submitMutation = useSubmitAssignment(activeSubmitAssignment?.id);
  const gradeMutation = useGradeSubmission(activeQueueAssignment?.id);
  const uploadMutation = useUploadAssignmentFile(activeSubmitAssignment?.id || 0);
  const deleteMutation = useDeleteAssignment();

  // Submissions for active queue
  const submissionsQuery = useAssignmentSubmissions(activeQueueAssignment?.id);
  const submissionsList = submissionsQuery.data || [];

  const isTeacherOrAdmin = role === "teacher" || role === "admin" || role === "principal";

  const handleCreateAssignment = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim() || !classId || !deadline) return;

    let uploadedUrl: string | undefined = undefined;
    let uploadedName: string | undefined = undefined;

    if (attachmentFile) {
      const up = await uploadMutation.mutateAsync(attachmentFile);
      uploadedUrl = up.file_url;
      uploadedName = up.file_name;
    }

    await createMutation.mutateAsync({
      title: title.trim(),
      description: desc.trim() || undefined,
      class_id: Number(classId),
      subject_id: subjectId ? Number(subjectId) : undefined,
      deadline: new Date(deadline).toISOString(),
      max_marks: Number(maxMarks) || 100,
      attachment_url: uploadedUrl,
      attachment_name: uploadedName,
    });

    setTitle("");
    setDesc("");
    setClassId("");
    setSubjectId("");
    setDeadline("");
    setMaxMarks("100");
    setAttachmentFile(null);
    setCreateOpen(false);
  };

  const handleStudentSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!submissionFile || !activeSubmitAssignment) return;

    const up = await uploadMutation.mutateAsync(submissionFile);
    await submitMutation.mutateAsync({
      file_url: up.file_url,
      file_name: up.file_name,
      file_size: up.file_size,
    });

    setSubmissionFile(null);
    setActiveSubmitAssignment(null);
  };

  const handleSaveGrade = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!gradingSubmission || !activeQueueAssignment) return;

    const g = parseFloat(gradeInput);
    if (isNaN(g) || g < 0 || g > activeQueueAssignment.max_marks) return;

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

  return (
    <div className="flex flex-col gap-6">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <PageHeader
          title="Assignments & Coursework"
          description="Create problem sets, track student submissions, and record assignment grades."
        />

        {isTeacherOrAdmin && (
          <Dialog open={createOpen} onOpenChange={setCreateOpen}>
            <DialogTrigger asChild>
              <Button size="sm" className="gap-2 shadow-sm">
                <Plus className="h-4 w-4" />
                New Assignment
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-accent" />
                  Create Coursework Assignment
                </DialogTitle>
              </DialogHeader>

              <form onSubmit={handleCreateAssignment} className="flex flex-col gap-4 mt-2">
                <div>
                  <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                    Assignment Title *
                  </label>
                  <Input
                    placeholder="e.g. Problem Set 3: Matrix Transformations"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    required
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                      Class Section *
                    </label>
                    <select
                      value={classId}
                      onChange={(e) => setClassId(e.target.value ? Number(e.target.value) : "")}
                      className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
                      required
                    >
                      <option value="">Select class</option>
                      {lookup.data?.classes.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                      Subject
                    </label>
                    <select
                      value={subjectId}
                      onChange={(e) => setSubjectId(e.target.value ? Number(e.target.value) : "")}
                      className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
                    >
                      <option value="">Select subject</option>
                      {lookup.data?.subjects.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                      Submission Deadline *
                    </label>
                    <Input
                      type="datetime-local"
                      value={deadline}
                      onChange={(e) => setDeadline(e.target.value)}
                      required
                    />
                  </div>

                  <div>
                    <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                      Maximum Marks
                    </label>
                    <Input
                      type="number"
                      min="1"
                      step="1"
                      value={maxMarks}
                      onChange={(e) => setMaxMarks(e.target.value)}
                      required
                    />
                  </div>
                </div>

                <div>
                  <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                    Instructions & Questions
                  </label>
                  <Textarea
                    placeholder="Describe problem statements, formatting instructions, or submission rules..."
                    value={desc}
                    onChange={(e) => setDesc(e.target.value)}
                    rows={3}
                  />
                </div>

                <div>
                  <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                    Attach Problem Sheet / Prompt File
                  </label>
                  <Input
                    type="file"
                    onChange={(e) => setAttachmentFile(e.target.files?.[0] || null)}
                    className="text-xs"
                  />
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-border">
                  <Button type="button" variant="ghost" onClick={() => setCreateOpen(false)}>
                    Cancel
                  </Button>
                  <Button type="submit" disabled={createMutation.isPending || !title.trim() || !classId || !deadline}>
                    {createMutation.isPending ? "Creating..." : "Publish Assignment"}
                  </Button>
                </div>
              </form>
            </DialogContent>
          </Dialog>
        )}
      </div>

      {/* Filter & Search Toolbar */}
      <Card className="border-border bg-surface shadow-sm">
        <CardContent className="p-4 flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-ink-muted" />
              <Input
                placeholder="Search assignments by title or subject..."
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

            {lookup.data?.classes && lookup.data.classes.length > 0 && (
              <select
                value={selectedClassId || ""}
                onChange={(e) => setSelectedClassId(e.target.value ? Number(e.target.value) : undefined)}
                className="rounded-xl border border-border bg-surface px-3 py-2 text-xs font-medium text-ink focus:outline-none focus:ring-2 focus:ring-accent"
              >
                <option value="">All Class Sections</option>
                {lookup.data.classes.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            )}

            {lookup.data?.subjects && (
              <select
                value={selectedSubjectId || ""}
                onChange={(e) => setSelectedSubjectId(e.target.value ? Number(e.target.value) : undefined)}
                className="rounded-xl border border-border bg-surface px-3 py-2 text-xs font-medium text-ink focus:outline-none focus:ring-2 focus:ring-accent"
              >
                <option value="">All Subjects</option>
                {lookup.data.subjects.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            )}
          </div>

          {/* Student Status Filters */}
          {role === "student" && (
            <div className="flex items-center gap-1.5 pt-2 border-t border-border/50 text-xs">
              <span className="font-semibold text-ink-muted mr-1">Status:</span>
              {[
                { id: "all", label: "All" },
                { id: "pending", label: "Pending" },
                { id: "submitted", label: "Submitted" },
                { id: "late", label: "Late" },
                { id: "graded", label: "Graded" },
                { id: "missing", label: "Missing" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setStatusFilter(tab.id)}
                  className={`px-2.5 py-1 rounded-lg transition-colors ${
                    statusFilter === tab.id
                      ? "bg-accent text-accent-foreground font-semibold"
                      : "bg-elevated/60 text-ink-muted hover:text-ink"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Assignment List Grid */}
      {assignmentsQuery.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-48 rounded-2xl bg-elevated/40 animate-pulse" />
          ))}
        </div>
      ) : assignments.length === 0 ? (
        <Card className="border-dashed border-border p-12 text-center bg-elevated/10">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-elevated text-ink-muted mb-3">
            <FileCheck className="h-6 w-6" />
          </div>
          <h3 className="text-base font-semibold text-ink">No Assignments Found</h3>
          <p className="text-sm text-ink-muted mt-1 max-w-md mx-auto">
            {isTeacherOrAdmin
              ? "Create your first assignment to assign homework and track student submissions."
              : "No coursework assignments have been posted for your classes."}
          </p>
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {assignments.map((a) => {
            const dl = formatDeadline(a.deadline);
            const mySub = a.my_submission;
            const statusBadge = getStatusBadge(mySub?.status);
            const StatusIcon = statusBadge.icon;
            const isAuthor = currentUser?.user_id === a.teacher_id;
            const canDelete = isAuthor || role === "admin" || role === "principal";

            return (
              <Card
                key={a.id}
                className="border-border hover:border-border-strong transition-all flex flex-col justify-between bg-surface group shadow-sm"
              >
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex flex-col">
                      <span className="text-[11px] font-semibold text-accent uppercase tracking-wider">
                        {a.subject_name || "General"} · {a.class_name}
                      </span>
                      <CardTitle className="text-base font-semibold text-ink mt-1 leading-snug line-clamp-2">
                        {a.title}
                      </CardTitle>
                    </div>

                    {canDelete && (
                      <ConfirmDialog
                        trigger={
                          <button className="text-ink-faint hover:text-urgent p-1 rounded transition-colors opacity-80 group-hover:opacity-100">
                            <Trash2 className="h-4 w-4" />
                          </button>
                        }
                        title="Delete Assignment"
                        description="Are you sure you want to delete this assignment? All student submissions and grades will also be permanently deleted."
                        confirmLabel="Delete"
                        onConfirm={() => deleteMutation.mutate(a.id)}
                      />
                    )}
                  </div>
                </CardHeader>

                <CardContent className="pt-0 flex flex-col gap-3">
                  {a.description && (
                    <p className="text-xs text-ink-muted line-clamp-2 leading-relaxed">{a.description}</p>
                  )}

                  {/* Deadline & Marks Banner */}
                  <div className="flex items-center justify-between text-xs rounded-xl bg-elevated/40 p-2.5 border border-border/50">
                    <div className="flex items-center gap-1.5 text-ink-muted">
                      <Clock className={`h-3.5 w-3.5 ${dl.isPast ? "text-red-400" : "text-amber-400"}`} />
                      <span className={dl.isPast ? "text-red-400 font-medium" : "text-ink font-medium"}>
                        {dl.relative}
                      </span>
                    </div>
                    <span className="font-semibold text-ink">{a.max_marks} Marks</span>
                  </div>

                  {/* Teacher Stats Bar */}
                  {isTeacherOrAdmin && a.stats && (
                    <div className="flex flex-col gap-1.5 pt-1">
                      <div className="flex items-center justify-between text-xs text-ink-muted">
                        <span>
                          Submissions: <strong className="text-ink">{a.stats.submitted_count}</strong> / {a.stats.enrolled_count}
                        </span>
                        <span>
                          Graded: <strong className="text-ink">{a.stats.graded_count}</strong>
                        </span>
                      </div>
                      <div className="h-1.5 w-full rounded-full bg-elevated overflow-hidden flex">
                        <div
                          className="bg-emerald-500 h-full"
                          style={{
                            width: `${(a.stats.submitted_count / (a.stats.enrolled_count || 1)) * 100}%`,
                          }}
                        />
                      </div>
                    </div>
                  )}

                  {/* Student Status & Grade */}
                  {role === "student" && (
                    <div className="flex items-center justify-between pt-1">
                      <Badge className={`gap-1 text-xs py-0.5 px-2 border ${statusBadge.color}`}>
                        <StatusIcon className="h-3 w-3" />
                        {statusBadge.label}
                      </Badge>

                      {mySub?.grade !== null && mySub?.grade !== undefined && (
                        <div className="flex items-center gap-1 text-xs font-bold text-emerald-400">
                          <Award className="h-3.5 w-3.5" />
                          <span>{mySub.grade} / {a.max_marks}</span>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Action Buttons */}
                  <div className="pt-2 border-t border-border/60 flex items-center gap-2">
                    {/* Attached Prompt Download */}
                    {a.attachment_url && (
                      <a
                        href={a.attachment_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="flex items-center gap-1 rounded-lg bg-elevated/40 hover:bg-elevated text-ink text-xs px-2.5 py-1.5 transition-colors border border-border"
                        title="Download Assignment Sheet"
                      >
                        <FileText className="h-3.5 w-3.5 text-accent" />
                        <span className="truncate max-w-[110px]">{a.attachment_name || "Attachment"}</span>
                        <Download className="h-3 w-3 text-ink-faint" />
                      </a>
                    )}

                    {/* Teacher: View Submissions Tracker */}
                    {isTeacherOrAdmin && (
                      <div className="flex items-center gap-1.5 flex-1">
                        <Link
                          to={`/${role}/assignments/${a.id}/submissions`}
                          className="flex-1 inline-flex items-center justify-center gap-1.5 rounded-xl border border-border bg-surface px-2.5 py-1.5 text-xs font-medium text-ink hover:bg-elevated/60 hover:border-border-strong transition-colors"
                        >
                          <UserCheck className="h-3.5 w-3.5 text-accent" />
                          <span>Track ({a.stats?.submitted_count ?? 0}/{a.stats?.enrolled_count ?? 0})</span>
                        </Link>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setActiveQueueAssignment(a)}
                          className="text-xs h-8 px-2 text-ink-muted hover:text-ink"
                          title="Quick Grading Drawer"
                        >
                          <Award className="h-3.5 w-3.5" />
                        </Button>
                      </div>
                    )}

                    {/* Student: Submit Button */}
                    {role === "student" && (
                      <Button
                        size="sm"
                        onClick={() => setActiveSubmitAssignment(a)}
                        className="flex-1 text-xs gap-1.5"
                      >
                        <UploadCloud className="h-3.5 w-3.5" />
                        {mySub?.status === "submitted" || mySub?.status === "late"
                          ? "Resubmit Homework"
                          : mySub?.status === "graded"
                          ? "View Evaluation"
                          : "Submit Homework"}
                      </Button>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Teacher Submissions Queue & Grading Drawer/Dialog */}
      <Dialog
        open={activeQueueAssignment !== null}
        onOpenChange={(open) => {
          if (!open) {
            setActiveQueueAssignment(null);
            setGradingSubmission(null);
          }
        }}
      >
        <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle className="flex items-center justify-between pr-4">
              <div className="flex items-center gap-2">
                <FileCheck className="h-5 w-5 text-accent" />
                <span>Submissions: {activeQueueAssignment?.title}</span>
              </div>
              <Badge variant="neutral">{activeQueueAssignment?.class_name}</Badge>
            </DialogTitle>
          </DialogHeader>

          {activeQueueAssignment && (
            <div className="flex flex-col gap-4 mt-2">
              {/* Stats overview bar */}
              {activeQueueAssignment.stats && (
                <div className="grid grid-cols-4 gap-2 text-center text-xs bg-elevated/40 p-3 rounded-xl border border-border">
                  <div>
                    <span className="text-ink-muted block">Enrolled</span>
                    <strong className="text-base text-ink">{activeQueueAssignment.stats.enrolled_count}</strong>
                  </div>
                  <div>
                    <span className="text-emerald-400 block">Submitted</span>
                    <strong className="text-base text-ink">{activeQueueAssignment.stats.submitted_count}</strong>
                  </div>
                  <div>
                    <span className="text-red-400 block">Missing</span>
                    <strong className="text-base text-ink">{activeQueueAssignment.stats.missing_count}</strong>
                  </div>
                  <div>
                    <span className="text-blue-400 block">Avg Score</span>
                    <strong className="text-base text-ink">
                      {activeQueueAssignment.stats.average_grade !== null
                        ? `${activeQueueAssignment.stats.average_grade} / ${activeQueueAssignment.max_marks}`
                        : "—"}
                    </strong>
                  </div>
                </div>
              )}

              {/* Submissions List Table */}
              {submissionsQuery.isLoading ? (
                <div className="h-32 bg-elevated/40 rounded-xl animate-pulse" />
              ) : submissionsList.length === 0 ? (
                <div className="p-8 text-center text-ink-muted text-sm border border-dashed border-border rounded-xl">
                  No enrolled students found in this class section.
                </div>
              ) : (
                <div className="flex flex-col gap-2">
                  {submissionsList.map((sub) => {
                    const stBadge = getStatusBadge(sub.status);
                    const StIcon = stBadge.icon;
                    const isGraded = sub.status === "graded" || sub.grade !== null;

                    return (
                      <div
                        key={sub.student_id}
                        className="flex flex-wrap items-center justify-between gap-3 p-3 rounded-xl bg-surface border border-border hover:border-border-strong transition-colors"
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent font-semibold text-xs">
                            {sub.student_name?.slice(0, 2).toUpperCase() || "ST"}
                          </div>
                          <div className="flex flex-col min-w-0">
                            <span className="text-sm font-semibold text-ink truncate">
                              {sub.student_name || "Student"}
                            </span>
                            <span className="text-xs text-ink-muted truncate">{sub.student_email}</span>
                          </div>
                        </div>

                        <div className="flex items-center gap-3">
                          <Badge className={`gap-1 text-[11px] py-0.5 px-2 border ${stBadge.color}`}>
                            <StIcon className="h-3 w-3" />
                            {stBadge.label}
                          </Badge>

                          {/* Submitted File link */}
                          {sub.file_url ? (
                            <a
                              href={sub.file_url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="flex items-center gap-1 text-xs text-accent hover:underline bg-accent/10 px-2 py-1 rounded-lg"
                            >
                              <Download className="h-3 w-3" />
                              <span>{sub.file_name || "File"}</span>
                            </a>
                          ) : (
                            <span className="text-xs text-ink-faint">No file</span>
                          )}

                          {/* Grade display / Grade button */}
                          {isGraded ? (
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-bold text-emerald-400 bg-emerald-500/10 px-2 py-1 rounded-lg border border-emerald-500/20">
                                {sub.grade} / {activeQueueAssignment.max_marks}
                              </span>
                              <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => {
                                  setGradingSubmission(sub);
                                  setGradeInput(sub.grade?.toString() || "");
                                  setFeedbackInput(sub.feedback || "");
                                }}
                                className="text-xs h-8 px-2"
                              >
                                Edit
                              </Button>
                            </div>
                          ) : sub.status in ["submitted", "late"] || sub.file_url ? (
                            <Button
                              size="sm"
                              onClick={() => {
                                setGradingSubmission(sub);
                                setGradeInput("");
                                setFeedbackInput("");
                              }}
                              className="text-xs h-8 gap-1"
                            >
                              <Award className="h-3 w-3" />
                              Grade
                            </Button>
                          ) : (
                            <span className="text-xs text-ink-faint">—</span>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Grading Drawer / Form Modal */}
              {gradingSubmission && (
                <div className="p-4 rounded-xl border border-accent/40 bg-accent/5 flex flex-col gap-3 mt-2">
                  <div className="flex items-center justify-between">
                    <h4 className="text-sm font-semibold text-ink flex items-center gap-1.5">
                      <Award className="h-4 w-4 text-accent" />
                      Grade Submission for {gradingSubmission.student_name}
                    </h4>
                    <button
                      onClick={() => setGradingSubmission(null)}
                      className="text-ink-muted hover:text-ink"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>

                  <form onSubmit={handleSaveGrade} className="flex flex-col gap-3">
                    <div className="flex items-center gap-3">
                      <div className="w-40">
                        <label className="text-xs font-medium text-ink-muted block mb-1">
                          Marks (Max {activeQueueAssignment.max_marks}) *
                        </label>
                        <Input
                          type="number"
                          min="0"
                          max={activeQueueAssignment.max_marks}
                          step="0.5"
                          placeholder="e.g. 85"
                          value={gradeInput}
                          onChange={(e) => setGradeInput(e.target.value)}
                          required
                          className="bg-surface"
                        />
                      </div>

                      <div className="flex-1">
                        <label className="text-xs font-medium text-ink-muted block mb-1">
                          Teacher Feedback / Comments
                        </label>
                        <Input
                          placeholder="Feedback, corrections, or encouraging note..."
                          value={feedbackInput}
                          onChange={(e) => setFeedbackInput(e.target.value)}
                          className="bg-surface"
                        />
                      </div>
                    </div>

                    <div className="flex justify-end gap-2 pt-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => setGradingSubmission(null)}
                      >
                        Cancel
                      </Button>
                      <Button
                        type="submit"
                        size="sm"
                        disabled={gradeMutation.isPending || !gradeInput}
                        className="gap-1"
                      >
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        {gradeMutation.isPending ? "Saving..." : "Save Grade & Notify"}
                      </Button>
                    </div>
                  </form>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* Student Submission Modal */}
      <Dialog
        open={activeSubmitAssignment !== null}
        onOpenChange={(open) => {
          if (!open) {
            setActiveSubmitAssignment(null);
            setSubmissionFile(null);
          }
        }}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FileCheck className="h-5 w-5 text-accent" />
              <span>Submit: {activeSubmitAssignment?.title}</span>
            </DialogTitle>
          </DialogHeader>

          {activeSubmitAssignment && (
            <div className="flex flex-col gap-4 mt-2">
              {/* Instructions Banner */}
              {activeSubmitAssignment.description && (
                <div className="p-3 rounded-xl bg-elevated/40 text-xs text-ink-muted leading-relaxed border border-border">
                  <strong className="text-ink block mb-1">Instructions:</strong>
                  {activeSubmitAssignment.description}
                </div>
              )}

              {/* Deadline reminder */}
              <div className="flex items-center justify-between text-xs bg-surface p-2.5 rounded-xl border border-border">
                <span className="text-ink-muted">Deadline:</span>
                <span className="font-semibold text-ink">
                  {new Date(activeSubmitAssignment.deadline).toLocaleString()}
                </span>
              </div>

              {/* Already Graded View */}
              {activeSubmitAssignment.my_submission?.status === "graded" && (
                <div className="p-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 flex flex-col gap-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase tracking-wider text-emerald-400">
                      Evaluated & Graded
                    </span>
                    <strong className="text-base text-emerald-400">
                      {activeSubmitAssignment.my_submission.grade} / {activeSubmitAssignment.max_marks} Marks
                    </strong>
                  </div>
                  {activeSubmitAssignment.my_submission.feedback && (
                    <p className="text-xs text-ink mt-1 flex items-start gap-1.5">
                      <MessageSquare className="h-4 w-4 text-emerald-400 shrink-0 mt-0.5" />
                      <span>{activeSubmitAssignment.my_submission.feedback}</span>
                    </p>
                  )}
                </div>
              )}

              {/* Submit / Resubmit Form */}
              {activeSubmitAssignment.my_submission?.status !== "graded" && (
                <form onSubmit={handleStudentSubmit} className="flex flex-col gap-4">
                  <div>
                    <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                      Upload Homework File (PDF, DOCX, ZIP, Image) *
                    </label>
                    <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-border bg-elevated/30 p-6 text-center hover:border-border-strong transition-colors">
                      <input
                        type="file"
                        id="submission-file-input"
                        onChange={(e) => setSubmissionFile(e.target.files?.[0] || null)}
                        className="hidden"
                        required
                      />
                      <label
                        htmlFor="submission-file-input"
                        className="cursor-pointer flex flex-col items-center gap-1.5"
                      >
                        <UploadCloud className="h-8 w-8 text-accent" />
                        {submissionFile ? (
                          <div className="mt-1">
                            <p className="text-sm font-semibold text-ink">{submissionFile.name}</p>
                            <p className="text-xs text-ink-muted">
                              {(submissionFile.size / 1024).toFixed(0)} KB · Click to replace
                            </p>
                          </div>
                        ) : (
                          <div className="mt-1">
                            <p className="text-sm font-medium text-ink">Click or drag homework file here</p>
                            <p className="text-xs text-ink-muted">Supports all academic file types up to 25MB</p>
                          </div>
                        )}
                      </label>
                    </div>
                  </div>

                  <div className="flex justify-end gap-2 pt-2 border-t border-border">
                    <Button
                      type="button"
                      variant="ghost"
                      onClick={() => setActiveSubmitAssignment(null)}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="submit"
                      disabled={submitMutation.isPending || !submissionFile}
                      className="gap-1.5"
                    >
                      <Send className="h-3.5 w-3.5" />
                      {submitMutation.isPending ? "Submitting..." : "Turn In Homework"}
                    </Button>
                  </div>
                </form>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
