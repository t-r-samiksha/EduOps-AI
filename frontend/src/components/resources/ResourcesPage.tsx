import { useState, useMemo } from "react";
import { useParams } from "react-router-dom";
import {
  FolderKanban,
  Search,
  Plus,
  Download,
  Trash2,
  FileText,
  FileIcon,
  Image as ImageIcon,
  FileCode,
  FileArchive,
  Layers,
  Sparkles,
  ExternalLink,
  BookOpen,
  Filter,
  X,
  Clock,
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
  useResources,
  useClassResources,
  useResourceUnits,
  useUploadResource,
  useDeleteResource,
} from "@/api/hooks/useResources";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useAuthStore } from "@/store/authStore";
import { timeAgo } from "@/lib/format";
import type { ResourceItem } from "@/api/types";

function getFileCategory(mime: string, filename: string): { label: string; icon: any; color: string } {
  const ext = filename.split(".").pop()?.toLowerCase() || "";
  if (mime.includes("pdf") || ext === "pdf") {
    return { label: "PDF Document", icon: FileText, color: "text-red-400 bg-red-500/10 border-red-500/20" };
  }
  if (mime.includes("word") || ["doc", "docx"].includes(ext)) {
    return { label: "Word Document", icon: FileText, color: "text-blue-400 bg-blue-500/10 border-blue-500/20" };
  }
  if (mime.includes("presentation") || mime.includes("powerpoint") || ["ppt", "pptx"].includes(ext)) {
    return { label: "Slides / Presentation", icon: Layers, color: "text-amber-400 bg-amber-500/10 border-amber-500/20" };
  }
  if (mime.startsWith("image/") || ["png", "jpg", "jpeg", "webp", "gif", "svg"].includes(ext)) {
    return { label: "Image / Diagram", icon: ImageIcon, color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20" };
  }
  if (["zip", "rar", "tar", "gz", "7z"].includes(ext)) {
    return { label: "Archive", icon: FileArchive, color: "text-orange-400 bg-orange-500/10 border-orange-500/20" };
  }
  if (["py", "ts", "js", "html", "css", "json", "java", "cpp"].includes(ext)) {
    return { label: "Code / Data", icon: FileCode, color: "text-cyan-400 bg-cyan-500/10 border-cyan-500/20" };
  }
  return { label: "Notes / Text", icon: FileIcon, color: "text-purple-400 bg-purple-500/10 border-purple-500/20" };
}

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ResourcesPage() {
  const params = useParams<{ classId?: string }>();
  const classIdFromRoute = params.classId ? Number(params.classId) : undefined;

  const { role } = useAuthStore();
  const currentUser = useCurrentUser().data;
  const lookup = useReferenceLookup(currentUser?.school_id);

  // Filter & Search states
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedClassId, setSelectedClassId] = useState<number | undefined>(classIdFromRoute);
  const [selectedSubjectId, setSelectedSubjectId] = useState<number | undefined>(undefined);
  const [selectedUnit, setSelectedUnit] = useState<string | undefined>(undefined);
  const [selectedFormat, setSelectedFormat] = useState<string | "all">("all");

  // Query resources
  const activeFilters = useMemo(() => ({
    class_id: selectedClassId,
    subject_id: selectedSubjectId,
    unit: selectedUnit,
    file_type: selectedFormat !== "all" ? selectedFormat : undefined,
    q: searchQuery.trim() || undefined,
  }), [selectedClassId, selectedSubjectId, selectedUnit, selectedFormat, searchQuery]);

  const resourcesQuery = selectedClassId
    ? useClassResources(selectedClassId, activeFilters)
    : useResources(activeFilters);

  const items: ResourceItem[] = resourcesQuery.data?.items || [];

  // Units list for filter dropdown / pills
  const unitsQuery = useResourceUnits(selectedClassId, selectedSubjectId);
  const availableUnits = unitsQuery.data?.units || [];

  // Upload dialog state (Teacher / Admin)
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadDesc, setUploadDesc] = useState("");
  const [uploadUnit, setUploadUnit] = useState("");
  const [uploadClassId, setUploadClassId] = useState<number | "">("");
  const [uploadSubjectId, setUploadSubjectId] = useState<number | "">("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);

  const uploadMutation = useUploadResource();
  const deleteMutation = useDeleteResource();

  const isTeacherOrAdmin = role === "teacher" || role === "admin" || role === "principal";

  const handleUploadSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!uploadFile || !uploadTitle.trim()) return;

    await uploadMutation.mutateAsync({
      file: uploadFile,
      title: uploadTitle.trim(),
      description: uploadDesc.trim() || undefined,
      unit: uploadUnit.trim() || undefined,
      class_id: uploadClassId ? Number(uploadClassId) : undefined,
      subject_id: uploadSubjectId ? Number(uploadSubjectId) : undefined,
    });

    // Reset & close
    setUploadTitle("");
    setUploadDesc("");
    setUploadUnit("");
    setUploadClassId("");
    setUploadSubjectId("");
    setUploadFile(null);
    setUploadOpen(false);
  };

  const handleClearFilters = () => {
    setSearchQuery("");
    setSelectedSubjectId(undefined);
    setSelectedUnit(undefined);
    setSelectedFormat("all");
  };

  const hasActiveFilters = searchQuery || selectedSubjectId !== undefined || selectedUnit || selectedFormat !== "all";

  return (
    <div className="flex flex-col gap-6">
      {/* Top Header */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <PageHeader
          title="Academic Resources Library"
          description="Subject textbooks, unit notes, worksheets, and lecture materials."
        />

        {isTeacherOrAdmin && (
          <Dialog open={uploadOpen} onOpenChange={setUploadOpen}>
            <DialogTrigger asChild>
              <Button size="sm" className="gap-2 shadow-sm">
                <Plus className="h-4 w-4" />
                Upload Academic Material
              </Button>
            </DialogTrigger>
            <DialogContent className="max-w-lg">
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-accent" />
                  Upload Teaching Resource
                </DialogTitle>
              </DialogHeader>

              <form onSubmit={handleUploadSubmit} className="flex flex-col gap-4 mt-2">
                <div>
                  <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                    Resource Title *
                  </label>
                  <Input
                    placeholder="e.g. Unit 3: Optics Formulas & Practice Sheet"
                    value={uploadTitle}
                    onChange={(e) => setUploadTitle(e.target.value)}
                    required
                  />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                      Class Section
                    </label>
                    <select
                      value={uploadClassId}
                      onChange={(e) => setUploadClassId(e.target.value ? Number(e.target.value) : "")}
                      className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
                    >
                      <option value="">All Sections / Grade-level</option>
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
                      value={uploadSubjectId}
                      onChange={(e) => setUploadSubjectId(e.target.value ? Number(e.target.value) : "")}
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

                <div>
                  <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                    Unit / Topic Tag
                  </label>
                  <Input
                    placeholder="e.g. Unit 2: Chemical Bonding or Chapter 4"
                    value={uploadUnit}
                    onChange={(e) => setUploadUnit(e.target.value)}
                    list="units-datalist"
                  />
                  <datalist id="units-datalist">
                    {availableUnits.map((u) => (
                      <option key={u} value={u} />
                    ))}
                  </datalist>
                </div>

                <div>
                  <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                    Description / Instructions
                  </label>
                  <Textarea
                    placeholder="Brief description or guidance for students..."
                    value={uploadDesc}
                    onChange={(e) => setUploadDesc(e.target.value)}
                    rows={3}
                  />
                </div>

                {/* File Dropzone */}
                <div>
                  <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1">
                    Academic File (PDF, Word, Slides, Text, Images) *
                  </label>
                  <div className="flex flex-col items-center justify-center rounded-xl border-2 border-dashed border-border bg-elevated/30 p-6 text-center hover:border-border-strong transition-colors">
                    <input
                      type="file"
                      id="resource-file-input"
                      onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                      className="hidden"
                      accept=".pdf,.doc,.docx,.ppt,.pptx,.txt,.md,.png,.jpg,.jpeg,.webp,.svg"
                      required
                    />
                    <label
                      htmlFor="resource-file-input"
                      className="cursor-pointer flex flex-col items-center gap-1.5"
                    >
                      <FolderKanban className="h-8 w-8 text-accent" />
                      {uploadFile ? (
                        <div className="mt-1">
                          <p className="text-sm font-semibold text-ink">{uploadFile.name}</p>
                          <p className="text-xs text-ink-muted">{formatBytes(uploadFile.size)} · Click to replace</p>
                        </div>
                      ) : (
                        <div className="mt-1">
                          <p className="text-sm font-medium text-ink">Click or drag file here to upload</p>
                          <p className="text-xs text-ink-muted">PDF, Word, PPT, Markdown, PNG, JPG (up to 25MB)</p>
                        </div>
                      )}
                    </label>
                  </div>
                </div>

                <div className="flex justify-end gap-2 pt-2 border-t border-border">
                  <Button type="button" variant="ghost" onClick={() => setUploadOpen(false)}>
                    Cancel
                  </Button>
                  <Button type="submit" disabled={uploadMutation.isPending || !uploadFile || !uploadTitle.trim()}>
                    {uploadMutation.isPending ? "Uploading..." : "Publish Resource"}
                  </Button>
                </div>
              </form>
            </DialogContent>
          </Dialog>
        )}
      </div>

      {/* Filter and Search Bar Card */}
      <Card className="border-border bg-surface shadow-sm">
        <CardContent className="p-4 flex flex-col gap-4">
          {/* Top Search Line */}
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative flex-1 min-w-[220px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-ink-muted" />
              <Input
                placeholder="Search resources by title, unit topic, or description..."
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

            {/* Class Section Filter */}
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

            {/* Subject Filter */}
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

            {hasActiveFilters && (
              <Button variant="ghost" size="sm" onClick={handleClearFilters} className="text-xs gap-1.5 h-9">
                <X className="h-3.5 w-3.5" />
                Reset
              </Button>
            )}
          </div>

          {/* Unit Pills & Format Filters */}
          <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-border/50 text-xs">
            {/* Unit Topic Filter Pills */}
            <div className="flex items-center gap-1.5 overflow-x-auto pb-1 max-w-full">
              <span className="font-semibold text-ink-muted flex items-center gap-1 mr-1 shrink-0">
                <Filter className="h-3 w-3" /> Unit:
              </span>
              <button
                onClick={() => setSelectedUnit(undefined)}
                className={`px-2.5 py-1 rounded-lg transition-colors shrink-0 ${
                  selectedUnit === undefined
                    ? "bg-accent/20 text-accent font-semibold"
                    : "bg-elevated/60 text-ink-muted hover:text-ink"
                }`}
              >
                All Units
              </button>
              {availableUnits.map((u) => (
                <button
                  key={u}
                  onClick={() => setSelectedUnit(selectedUnit === u ? undefined : u)}
                  className={`px-2.5 py-1 rounded-lg transition-colors shrink-0 ${
                    selectedUnit === u
                      ? "bg-accent text-accent-foreground font-semibold"
                      : "bg-elevated/60 text-ink-muted hover:text-ink"
                  }`}
                >
                  {u}
                </button>
              ))}
            </div>

            {/* Format Pills */}
            <div className="flex items-center gap-1 shrink-0">
              <span className="text-ink-muted mr-1">Type:</span>
              {(["all", "pdf", "word", "presentation", "image"] as const).map((fmt) => (
                <button
                  key={fmt}
                  onClick={() => setSelectedFormat(fmt)}
                  className={`px-2 py-0.5 rounded text-[11px] capitalize transition-colors ${
                    selectedFormat === fmt
                      ? "bg-primary/20 text-primary font-semibold"
                      : "text-ink-muted hover:text-ink"
                  }`}
                >
                  {fmt === "all" ? "All" : fmt}
                </button>
              ))}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Results Header */}
      <div className="flex items-center justify-between text-xs text-ink-muted px-1">
        <span>
          Showing <span className="font-semibold text-ink">{items.length}</span> academic resource
          {items.length === 1 ? "" : "s"}
        </span>
        {currentUser?.school_id && (
          <span className="flex items-center gap-1.5">
            <BookOpen className="h-3.5 w-3.5 text-accent" />
            Knowledge Base Indexed for Doubt Bot
          </span>
        )}
      </div>

      {/* Resources Cards Grid */}
      {resourcesQuery.isLoading ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {[1, 2, 3, 4, 5, 6].map((i) => (
            <div key={i} className="h-44 rounded-2xl bg-elevated/40 animate-pulse" />
          ))}
        </div>
      ) : items.length === 0 ? (
        <Card className="border-dashed border-border p-12 text-center bg-elevated/10">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-elevated text-ink-muted mb-3">
            <FolderKanban className="h-6 w-6" />
          </div>
          <h3 className="text-base font-semibold text-ink">No Academic Resources Found</h3>
          <p className="text-sm text-ink-muted mt-1 max-w-md mx-auto">
            {hasActiveFilters
              ? "No resources match your active search or filter criteria. Try resetting filters."
              : isTeacherOrAdmin
              ? "Upload notes, unit worksheets, slides, or sample questions to get started."
              : "No teaching materials have been uploaded for your class sections yet."}
          </p>
          {hasActiveFilters && (
            <Button variant="outline" size="sm" onClick={handleClearFilters} className="mt-4">
              Clear All Filters
            </Button>
          )}
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {items.map((r) => {
            const category = getFileCategory(r.mime_type, r.file_url);
            const CategoryIcon = category.icon;
            const isAuthor = currentUser?.user_id === r.teacher_id;
            const canDelete = isAuthor || role === "admin" || role === "principal";

            return (
              <Card
                key={r.id}
                className="border-border hover:border-border-strong transition-all flex flex-col justify-between bg-surface group"
              >
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex items-center gap-2.5 min-w-0">
                      <div
                        className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border ${category.color}`}
                      >
                        <CategoryIcon className="h-5 w-5" />
                      </div>
                      <div className="flex flex-col min-w-0">
                        <span className="text-[11px] font-semibold text-accent uppercase tracking-wider truncate">
                          {r.subject_name || "General"}
                        </span>
                        <span className="text-xs text-ink-muted truncate">
                          {r.class_name || `Grade ${r.grade_level}`}
                        </span>
                      </div>
                    </div>

                    {canDelete && (
                      <ConfirmDialog
                        trigger={
                          <button className="text-ink-faint hover:text-urgent p-1 rounded transition-colors opacity-80 group-hover:opacity-100">
                            <Trash2 className="h-4 w-4" />
                          </button>
                        }
                        title="Delete Resource"
                        description="Are you sure you want to delete this resource? It will also be removed from the Doubt Bot knowledge base."
                        confirmLabel="Delete"
                        onConfirm={() => deleteMutation.mutate(r.id)}
                      />
                    )}
                  </div>

                  <CardTitle className="text-sm font-semibold text-ink mt-2.5 leading-snug line-clamp-2">
                    {r.title}
                  </CardTitle>
                </CardHeader>

                <CardContent className="pt-0 flex flex-col gap-3">
                  {r.unit && (
                    <div className="flex items-center gap-1.5">
                      <Badge variant="neutral" className="text-[11px] font-medium py-0 px-2">
                        {r.unit}
                      </Badge>
                    </div>
                  )}

                  {r.description && (
                    <p className="text-xs text-ink-muted line-clamp-2 leading-relaxed">{r.description}</p>
                  )}

                  <div className="flex items-center justify-between text-[11px] text-ink-faint pt-2.5 border-t border-border/50">
                    <div className="flex items-center gap-2">
                      <span>{formatBytes(r.file_size)}</span>
                      <span>·</span>
                      <span className="flex items-center gap-1">
                        <Clock className="h-3 w-3" />
                        {timeAgo(r.created_at)}
                      </span>
                    </div>

                    {r.teacher_name && (
                      <span className="truncate max-w-[100px] text-ink-muted">By {r.teacher_name}</span>
                    )}
                  </div>

                  {/* Preview / Download Button */}
                  <a
                    href={r.file_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center justify-center gap-1.5 rounded-xl border border-border bg-elevated/40 hover:bg-elevated text-ink text-xs font-medium py-2 transition-colors w-full mt-1"
                  >
                    <Download className="h-3.5 w-3.5 text-accent" />
                    <span>Download / Open</span>
                    <ExternalLink className="h-3 w-3 text-ink-faint ml-0.5" />
                  </a>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
