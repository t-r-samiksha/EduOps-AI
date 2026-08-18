import { useState, useMemo, useEffect } from "react";
import {
  FolderKanban,
  UploadCloud,
  FileText,
  Search,
  CheckCircle2,
  Clock,
  AlertCircle,
  Trash2,
  Download,
  Info,
} from "lucide-react";
import PageHeader from "@/components/shared/PageHeader";
import FileDropzone from "@/components/shared/FileDropzone";
import ConfirmDialog from "@/components/shared/ConfirmDialog";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { useResources, useUploadResource, useDeleteResource } from "@/hooks/useResources";
import { useTimetableActive, useReferenceLookup } from "@/api/hooks/useTimetable";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useMyUserId } from "@/hooks/useViewedStudent";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { ApiError } from "@/api/client";
import { timeAgo } from "@/lib/format";

function getFileNameWithoutExtension(filename: string): string {
  const lastDot = filename.lastIndexOf(".");
  if (lastDot <= 0) return filename;
  return filename.substring(0, lastDot);
}

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function TeacherResources() {
  const myUserId = useMyUserId();
  const currentUser = useCurrentUser().data;
  const schoolId = currentUser?.school_id;
  const lookup = useReferenceLookup(schoolId);
  const timetable = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR });

  // --- Resolve Teacher Classes, Grades, and Subjects ---
  const teacherSlots = timetable.data ?? [];

  const teacherClasses = useMemo(() => {
    if (!lookup.data?.classes) return [];
    const classIdsTaught = new Set<number>();
    for (const s of teacherSlots) {
      if (s.class_id) classIdsTaught.add(s.class_id);
    }
    // `Number(user.id)` here was ALWAYS NaN - authStore.user is the Supabase auth user and
    // its id is a UUID string - so this comparison never matched and the homeroom classes
    // were silently never added. It failed soft (the code below falls back to a wider list),
    // which is why it went unnoticed. See useMyUserId.
    if (myUserId != null) {
      for (const c of lookup.data.classes) {
        if (c.class_teacher_id === myUserId) {
          classIdsTaught.add(c.id);
        }
      }
    }
    if (classIdsTaught.size > 0) {
      return lookup.data.classes.filter((c) => classIdsTaught.has(c.id));
    }
    return lookup.data.classes;
  }, [lookup.data?.classes, teacherSlots, myUserId]);

  const availableGrades = useMemo(() => {
    const grades = new Set<number>();
    for (const c of teacherClasses) {
      if (c.grade_level != null) grades.add(c.grade_level);
    }
    return Array.from(grades).sort((a, b) => a - b);
  }, [teacherClasses]);

  const availableSubjects = useMemo(() => {
    if (!lookup.data?.subjects) return [];
    const subjectIdsTaught = new Set<number>();
    for (const s of teacherSlots) {
      if (s.subject_id) subjectIdsTaught.add(s.subject_id);
    }
    if (subjectIdsTaught.size > 0) {
      return lookup.data.subjects.filter((s) => subjectIdsTaught.has(s.id));
    }
    return lookup.data.subjects;
  }, [lookup.data?.subjects, teacherSlots]);

  // --- Upload Form State ---
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [selectedGrade, setSelectedGrade] = useState<string>("");
  const [selectedClassId, setSelectedClassId] = useState<string>("");
  const [selectedSubjectId, setSelectedSubjectId] = useState<string>("");
  const [unit, setUnit] = useState("");
  const [description, setDescription] = useState("");

  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccessMessage, setUploadSuccessMessage] = useState<string | null>(null);

  // Set default grade/subject once loaded
  useEffect(() => {
    if (availableGrades.length > 0 && !selectedGrade) {
      setSelectedGrade(String(availableGrades[0]));
    }
  }, [availableGrades, selectedGrade]);

  useEffect(() => {
    if (availableSubjects.length > 0 && !selectedSubjectId) {
      setSelectedSubjectId(String(availableSubjects[0].id));
    }
  }, [availableSubjects, selectedSubjectId]);

  // Handle file selection & auto-fill title
  const handleFileSelected = (file: File | null) => {
    setSelectedFile(file);
    setUploadError(null);
    setUploadSuccessMessage(null);
    if (file) {
      const defaultTitle = getFileNameWithoutExtension(file.name);
      setTitle((prev) => (prev.trim() === "" ? defaultTitle : prev));
    }
  };

  // Filter classes matching selected grade
  const classesForSelectedGrade = useMemo(() => {
    if (!selectedGrade) return teacherClasses;
    const g = Number(selectedGrade);
    return teacherClasses.filter((c) => c.grade_level === g);
  }, [teacherClasses, selectedGrade]);

  // --- Upload Mutation ---
  const uploadMutation = useUploadResource();

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setUploadError(null);
    setUploadSuccessMessage(null);

    if (!selectedFile) {
      setUploadError("Please select a file to upload.");
      return;
    }
    if (!title.trim()) {
      setUploadError("Please enter a title for the resource.");
      return;
    }
    if (!selectedGrade && !selectedClassId) {
      setUploadError("Please select a grade for the resource.");
      return;
    }

    try {
      const res = await uploadMutation.mutateAsync({
        file: selectedFile,
        title: title.trim(),
        description: description.trim() || undefined,
        unit: unit.trim() || undefined,
        grade_level: selectedGrade ? Number(selectedGrade) : undefined,
        class_id: selectedClassId ? Number(selectedClassId) : undefined,
        subject_id: selectedSubjectId ? Number(selectedSubjectId) : undefined,
      });

      setUploadSuccessMessage(`"${res.title}" uploaded successfully! Indexing into Student Bot knowledge base.`);
      // Reset form
      setSelectedFile(null);
      setTitle("");
      setUnit("");
      setDescription("");
      setSelectedClassId("");
    } catch (err: any) {
      if (err instanceof ApiError) {
        if (err.status === 422 || (typeof err.message === "string" && err.message.toLowerCase().includes("text layer"))) {
          setUploadError(
            "This PDF doesn't contain a readable text layer. Please upload a digital/text-based PDF or a clearer copy."
          );
        } else if (err.status === 413) {
          setUploadError("File size exceeds the 25 MB limit. Please select a smaller file.");
        } else if (err.status === 415) {
          setUploadError(
            "File format is not supported. Supported formats: PDF, Word (DOC/DOCX), Slides (PPT/PPTX), Text/Markdown (TXT/MD), and common images."
          );
        } else if (err.status === 403) {
          setUploadError("You do not have authorization to upload resources for this grade or class section.");
        } else {
          setUploadError(err.message || "Failed to upload resource. Please check the inputs and try again.");
        }
      } else {
        setUploadError(err?.message || "An unexpected error occurred during upload.");
      }
    }
  };

  // --- Resource List & Search/Filter State ---
  const [filterSearch, setFilterSearch] = useState("");
  const [filterGrade, setFilterGrade] = useState<string>("all");
  const [filterSubject, setFilterSubject] = useState<string>("all");

  const resourcesQuery = useResources({
    grade_level: filterGrade !== "all" ? Number(filterGrade) : undefined,
    subject_id: filterSubject !== "all" ? Number(filterSubject) : undefined,
    q: filterSearch.trim() || undefined,
  });

  const resourcesList = resourcesQuery.data?.items ?? [];

  // Determine if any resource is still pending indexing
  const hasPendingResources = useMemo(() => {
    return resourcesList.some((r) => r.needs_reindex || r.indexed_at === null);
  }, [resourcesList]);

  // Polling mechanism for pending indexing
  useEffect(() => {
    if (!hasPendingResources) return;
    const interval = setInterval(() => {
      resourcesQuery.refetch();
    }, 2500);

    const timeout = setTimeout(() => {
      clearInterval(interval);
    }, 30000); // 30s timeout

    return () => {
      clearInterval(interval);
      clearTimeout(timeout);
    };
  }, [hasPendingResources, resourcesQuery]);

  // --- Delete Resource Mutation ---
  const deleteMutation = useDeleteResource();

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Teacher Resource Library"
        description="Upload lecture notes, worksheets, and syllabus units. Uploaded materials are indexed for Student Doubt Bot retrieval."
      />

      {/* SECTION A: UPLOAD RESOURCE */}
      <Card className="border shadow-elevated">
        <CardHeader className="pb-3">
          <div className="flex items-center gap-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10 text-accent">
              <UploadCloud className="h-5 w-5" />
            </div>
            <div>
              <CardTitle>Upload Resource</CardTitle>
              <CardDescription>
                Accepted formats: PDF, Word (DOC/DOCX), Slides (PPT/PPTX), Text (TXT/MD), Images • Maximum 25 MB
              </CardDescription>
            </div>
          </div>
        </CardHeader>

        <CardContent className="pt-2">
          <form onSubmit={handleUploadSubmit} className="flex flex-col gap-4">
            {/* File Dropzone */}
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-ink">
                Academic Document File <span className="text-urgent">*</span>
              </label>
              <FileDropzone
                file={selectedFile}
                onFileSelected={handleFileSelected}
                accept=".pdf,.doc,.docx,.ppt,.pptx,.txt,.md,.markdown,.png,.jpg,.jpeg,.webp,.gif,.svg"
                className="py-6"
              />
              <p className="text-xs text-ink-muted flex items-center gap-1 mt-0.5">
                <Info className="h-3.5 w-3.5 text-accent" />
                Text-based PDFs and documents are automatically chunked and embedded into the AI Doubt Bot corpus.
              </p>
            </div>

            {/* Form Fields: Grade, Subject, Class */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 md:grid-cols-3">
              {/* Grade Selector */}
              <div className="flex flex-col gap-1.5">
                <label htmlFor="grade-select" className="text-xs font-semibold text-ink">
                  Grade / Year Level <span className="text-urgent">*</span>
                </label>
                <Select value={selectedGrade} onValueChange={(val) => {
                  setSelectedGrade(val);
                  setSelectedClassId("");
                }}>
                  <SelectTrigger id="grade-select" aria-label="Select Grade Level">
                    <SelectValue placeholder="Select Grade" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableGrades.map((grade) => (
                      <SelectItem key={grade} value={String(grade)}>
                        Grade {grade}
                      </SelectItem>
                    ))}
                    {availableGrades.length === 0 && (
                      <SelectItem value="all" disabled>
                        No grades assigned
                      </SelectItem>
                    )}
                  </SelectContent>
                </Select>
              </div>

              {/* Subject Selector */}
              <div className="flex flex-col gap-1.5">
                <label htmlFor="subject-select" className="text-xs font-semibold text-ink">
                  Subject <span className="text-urgent">*</span>
                </label>
                <Select value={selectedSubjectId} onValueChange={setSelectedSubjectId}>
                  <SelectTrigger id="subject-select" aria-label="Select Subject">
                    <SelectValue placeholder="Select Subject" />
                  </SelectTrigger>
                  <SelectContent>
                    {availableSubjects.map((sub) => (
                      <SelectItem key={sub.id} value={String(sub.id)}>
                        {sub.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {/* Class Section (Optional) */}
              <div className="flex flex-col gap-1.5">
                <label htmlFor="class-select" className="text-xs font-semibold text-ink">
                  Class Section (Optional)
                </label>
                <Select value={selectedClassId} onValueChange={setSelectedClassId}>
                  <SelectTrigger id="class-select" aria-label="Select Class Section">
                    <SelectValue placeholder="All Sections in Grade" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="">All Sections in Grade</SelectItem>
                    {classesForSelectedGrade.map((c) => (
                      <SelectItem key={c.id} value={String(c.id)}>
                        {c.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>

            {/* Title & Unit */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <div className="flex flex-col gap-1.5 sm:col-span-2">
                <label htmlFor="resource-title" className="text-xs font-semibold text-ink">
                  Resource Title <span className="text-urgent">*</span>
                </label>
                <Input
                  id="resource-title"
                  placeholder="e.g. Kinematics & Laws of Motion Notes"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  required
                />
              </div>

              <div className="flex flex-col gap-1.5">
                <label htmlFor="resource-unit" className="text-xs font-semibold text-ink">
                  Unit / Chapter (Optional)
                </label>
                <Input
                  id="resource-unit"
                  placeholder="e.g. Unit 3"
                  value={unit}
                  onChange={(e) => setUnit(e.target.value)}
                />
              </div>
            </div>

            {/* Description (Optional) */}
            <div className="flex flex-col gap-1.5">
              <label htmlFor="resource-desc" className="text-xs font-semibold text-ink">
                Summary / Description (Optional)
              </label>
              <Input
                id="resource-desc"
                placeholder="Brief summary of topics covered in this resource"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>

            {/* Error / Success Feedback */}
            {uploadError && (
              <div
                role="alert"
                className="flex items-center gap-2 rounded-xl border border-urgent/30 bg-urgent/10 p-3 text-xs text-urgent"
              >
                <AlertCircle className="h-4 w-4 shrink-0" />
                <span>{uploadError}</span>
              </div>
            )}

            {uploadSuccessMessage && (
              <div
                role="status"
                aria-live="polite"
                className="flex items-center gap-2 rounded-xl border border-positive/30 bg-positive/10 p-3 text-xs text-positive"
              >
                <CheckCircle2 className="h-4 w-4 shrink-0" />
                <span>{uploadSuccessMessage}</span>
              </div>
            )}

            {/* Submit Button */}
            <div className="flex justify-end pt-1">
              <Button
                type="submit"
                disabled={uploadMutation.isPending}
                className="w-full sm:w-auto"
              >
                {uploadMutation.isPending ? (
                  <>
                    <Clock className="h-4 w-4 animate-spin" />
                    Uploading & Indexing...
                  </>
                ) : (
                  <>
                    <UploadCloud className="h-4 w-4" />
                    Upload Resource
                  </>
                )}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>

      {/* SECTION B: MY RESOURCES */}
      <Card className="border shadow-elevated">
        <CardHeader className="pb-3">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent/10 text-accent">
                <FolderKanban className="h-5 w-5" />
              </div>
              <div>
                <CardTitle>My Resources</CardTitle>
                <CardDescription>
                  View and manage uploaded materials, their indexing status, and student visibility.
                </CardDescription>
              </div>
            </div>

            {hasPendingResources && (
              <div aria-live="polite" className="flex items-center gap-1.5 text-xs text-warning animate-pulse font-medium">
                <Clock className="h-3.5 w-3.5" />
                <span>Auto-refreshing indexing status...</span>
              </div>
            )}
          </div>
        </CardHeader>

        <CardContent className="pt-2 flex flex-col gap-4">
          {/* Filters Bar */}
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            {/* Search Input */}
            <div className="relative">
              <Search className="absolute left-3 top-2.5 h-4 w-4 text-ink-muted" />
              <Input
                placeholder="Search resources by title or unit..."
                value={filterSearch}
                onChange={(e) => setFilterSearch(e.target.value)}
                className="pl-9 text-xs"
              />
            </div>

            {/* Filter by Grade */}
            <Select value={filterGrade} onValueChange={setFilterGrade}>
              <SelectTrigger aria-label="Filter by Grade">
                <SelectValue placeholder="All Grades" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Grades</SelectItem>
                {availableGrades.map((g) => (
                  <SelectItem key={g} value={String(g)}>
                    Grade {g}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {/* Filter by Subject */}
            <Select value={filterSubject} onValueChange={setFilterSubject}>
              <SelectTrigger aria-label="Filter by Subject">
                <SelectValue placeholder="All Subjects" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Subjects</SelectItem>
                {availableSubjects.map((s) => (
                  <SelectItem key={s.id} value={String(s.id)}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Resources Table / Cards */}
          {resourcesQuery.isLoading ? (
            <div className="py-12 text-center text-sm text-ink-muted">
              Loading resources...
            </div>
          ) : resourcesList.length === 0 ? (
            <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border py-12 text-center">
              <FolderKanban className="h-10 w-10 text-ink-muted/50 mb-2" />
              <p className="text-sm font-medium text-ink">No resources found</p>
              <p className="text-xs text-ink-muted mt-1 max-w-sm">
                {filterSearch || filterGrade !== "all" || filterSubject !== "all"
                  ? "No materials match the selected filters. Try clearing your search."
                  : "You have not uploaded any resources yet. Use the upload form above to add your first study material."}
              </p>
            </div>
          ) : (
            <div className="flex flex-col gap-2.5">
              {resourcesList.map((resource) => {
                const isPending = resource.needs_reindex || resource.indexed_at === null;
                const isIndexed = !!resource.indexed_at;

                return (
                  <div
                    key={resource.id}
                    className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 rounded-xl border border-border bg-card p-4 transition-colors hover:border-border-strong hover:bg-elevated/20 shadow-xs"
                  >
                    {/* Left: Icon & Details */}
                    <div className="flex items-start gap-3 min-w-0">
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent">
                        <FileText className="h-5 w-5" />
                      </div>

                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <h4 className="font-semibold text-sm text-ink truncate max-w-md">
                            {resource.title}
                          </h4>
                          {resource.unit && (
                            <Badge variant="outline" className="text-xs">
                              {resource.unit}
                            </Badge>
                          )}
                        </div>

                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-ink-muted mt-1">
                          {resource.subject_name && (
                            <span className="font-medium text-ink">
                              {resource.subject_name}
                            </span>
                          )}
                          <span>
                            Grade {resource.grade_level}
                            {resource.class_name ? ` (${resource.class_name})` : ""}
                          </span>
                          <span>•</span>
                          <span>{formatBytes(resource.file_size)}</span>
                          <span>•</span>
                          <span>{timeAgo(resource.created_at)}</span>
                        </div>

                        {resource.description && (
                          <p className="text-xs text-ink-faint mt-1 line-clamp-1">
                            {resource.description}
                          </p>
                        )}
                      </div>
                    </div>

                    {/* Right: Status & Actions */}
                    <div className="flex items-center justify-between sm:justify-end gap-3 shrink-0 pt-2 sm:pt-0 border-t sm:border-t-0 border-border">
                      {/* Indexing Status Badge */}
                      <div aria-live="polite">
                        {isIndexed ? (
                          <Badge variant="positive" className="gap-1">
                            <CheckCircle2 className="h-3 w-3" />
                            Indexed
                          </Badge>
                        ) : isPending ? (
                          <Badge variant="warning" className="gap-1 animate-pulse">
                            <Clock className="h-3 w-3" />
                            Pending
                          </Badge>
                        ) : (
                          <Badge variant="urgent" className="gap-1">
                            <AlertCircle className="h-3 w-3" />
                            Failed
                          </Badge>
                        )}
                      </div>

                      {/* Download / View Button */}
                      {resource.file_url && resource.file_url !== "pending" && (
                        <a
                          href={resource.file_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex h-8 items-center justify-center rounded-lg border border-border px-2.5 text-xs text-ink hover:border-accent hover:text-accent gap-1"
                          aria-label={`Download ${resource.title}`}
                        >
                          <Download className="h-3.5 w-3.5" />
                          <span className="hidden md:inline">Download</span>
                        </a>
                      )}

                      {/* Delete Button with ConfirmDialog */}
                      <ConfirmDialog
                        trigger={
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-ink-muted hover:text-urgent hover:bg-urgent/10 h-8 px-2"
                            aria-label={`Delete ${resource.title}`}
                          >
                            <Trash2 className="h-3.5 w-3.5 text-urgent" />
                          </Button>
                        }
                        title="Delete Resource"
                        description={`Are you sure you want to delete "${resource.title}"? This will remove the document and its indexing from the Student Doubt Bot.`}
                        confirmLabel="Delete Resource"
                        onConfirm={() => deleteMutation.mutate(resource.id)}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
