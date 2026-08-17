import { useState, useMemo } from "react";
import { useParams, useNavigate } from "react-router-dom";
import {
  BookOpen,
  Megaphone,
  FileText,
  Paperclip,
  Trash2,
  Send,
  Plus,
  Download,
  FileIcon,
  Image as ImageIcon,
  FileCode,
  FileArchive,
  Clock,
  Sparkles,
  School,
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
  useMyClassrooms,
  useClassroomStream,
  useCreatePost,
  useDeletePost,
  useUploadAttachment,
  useCreateClassroom,
} from "@/api/hooks/useClassroom";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useAuthStore } from "@/store/authStore";
import { timeAgo } from "@/lib/format";
import type { PostType, CreateAttachmentInput } from "@/api/types";

function getFileIcon(fileName: string, mimeType: string) {
  const ext = fileName.split(".").pop()?.toLowerCase() || "";
  if (["png", "jpg", "jpeg", "webp", "gif", "svg"].includes(ext) || mimeType.startsWith("image/")) {
    return ImageIcon;
  }
  if (["zip", "rar", "tar", "gz", "7z"].includes(ext)) {
    return FileArchive;
  }
  if (["py", "ts", "js", "html", "css", "json", "cpp", "java"].includes(ext)) {
    return FileCode;
  }
  if (["pdf", "doc", "docx", "txt", "md"].includes(ext)) {
    return FileText;
  }
  return FileIcon;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function ClassroomStreamPage() {
  const params = useParams<{ id?: string }>();
  const navigate = useNavigate();
  const { role } = useAuthStore();
  const currentUser = useCurrentUser().data;
  const lookup = useReferenceLookup(currentUser?.school_id);

  const myClassroomsQuery = useMyClassrooms();
  const classrooms = myClassroomsQuery.data || [];

  // Determine active classroom ID
  const activeClassroomId = useMemo(() => {
    if (params.id && !isNaN(Number(params.id))) {
      return Number(params.id);
    }
    return classrooms.length > 0 ? classrooms[0].id : undefined;
  }, [params.id, classrooms]);

  const [activeFilter, setActiveFilter] = useState<PostType | "all">("all");

  // Stream data
  const streamQuery = useClassroomStream(activeClassroomId, activeFilter);
  const streamData = streamQuery.data;
  const activeClassroom = streamData?.classroom || classrooms.find((c) => c.id === activeClassroomId);

  // Post composer state
  const [postType, setPostType] = useState<PostType>("note");
  const [postTitle, setPostTitle] = useState("");
  const [postContent, setPostContent] = useState("");
  const [stagedAttachments, setStagedAttachments] = useState<CreateAttachmentInput[]>([]);
  const [isUploading, setIsUploading] = useState(false);

  // Create classroom modal state (for teachers/admins)
  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newClassId, setNewClassId] = useState<number | "">("");
  const [newSubjectId, setNewSubjectId] = useState<number | "">("");

  const createPostMutation = useCreatePost(activeClassroomId);
  const deletePostMutation = useDeletePost(activeClassroomId);
  const uploadMutation = useUploadAttachment(activeClassroomId);
  const createClassroomMutation = useCreateClassroom();

  const isTeacherOrAdmin = role === "teacher" || role === "admin" || role === "principal";

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !activeClassroomId) return;

    setIsUploading(true);
    try {
      for (const file of Array.from(files)) {
        const uploaded = await uploadMutation.mutateAsync(file);
        setStagedAttachments((prev) => [
          ...prev,
          {
            file_name: uploaded.file_name,
            file_url: uploaded.file_url,
            file_type: uploaded.file_type,
            file_size: uploaded.file_size,
          },
        ]);
      }
    } catch (err) {
      console.error("Failed to upload attachment", err);
    } finally {
      setIsUploading(false);
      e.target.value = "";
    }
  };

  const handleRemoveStagedAttachment = (index: number) => {
    setStagedAttachments((prev) => prev.filter((_, i) => i !== index));
  };

  const handleSubmitPost = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!postTitle.trim() || !postContent.trim() || !activeClassroomId) return;

    await createPostMutation.mutateAsync({
      post_type: postType,
      title: postTitle.trim(),
      content: postContent.trim(),
      attachments: stagedAttachments,
    });

    setPostTitle("");
    setPostContent("");
    setStagedAttachments([]);
  };

  const handleCreateClassroom = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newClassId || !newSubjectId) return;

    const created = await createClassroomMutation.mutateAsync({
      class_id: Number(newClassId),
      subject_id: Number(newSubjectId),
    });

    setCreateDialogOpen(false);
    navigate(`/${role}/classroom/${created.id}`);
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <PageHeader
          title="Classroom Stream"
          description="Classroom notes, official announcements, and learning materials."
        />

        {isTeacherOrAdmin && (
          <Dialog open={createDialogOpen} onOpenChange={setCreateDialogOpen}>
            <DialogTrigger asChild>
              <Button size="sm" className="gap-2">
                <Plus className="h-4 w-4" />
                New Classroom Space
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Create Classroom Space</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleCreateClassroom} className="flex flex-col gap-4 mt-2">
                <div>
                  <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1.5">
                    Class Section
                  </label>
                  <select
                    value={newClassId}
                    onChange={(e) => setNewClassId(e.target.value ? Number(e.target.value) : "")}
                    className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
                    required
                  >
                    <option value="">Select a class</option>
                    {lookup.data?.classes.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="text-xs font-semibold text-ink-muted uppercase tracking-wider block mb-1.5">
                    Subject
                  </label>
                  <select
                    value={newSubjectId}
                    onChange={(e) => setNewSubjectId(e.target.value ? Number(e.target.value) : "")}
                    className="w-full rounded-xl border border-border bg-surface px-3 py-2 text-sm text-ink focus:outline-none focus:ring-2 focus:ring-accent"
                    required
                  >
                    <option value="">Select a subject</option>
                    {lookup.data?.subjects.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="flex justify-end gap-2 pt-2">
                  <Button type="button" variant="ghost" onClick={() => setCreateDialogOpen(false)}>
                    Cancel
                  </Button>
                  <Button type="submit" disabled={createClassroomMutation.isPending}>
                    {createClassroomMutation.isPending ? "Creating..." : "Create Space"}
                  </Button>
                </div>
              </form>
            </DialogContent>
          </Dialog>
        )}
      </div>

      {/* Classroom Selection Tabs */}
      {myClassroomsQuery.isLoading ? (
        <div className="flex gap-2 animate-pulse">
          <div className="h-10 w-32 rounded-xl bg-elevated/60" />
          <div className="h-10 w-32 rounded-xl bg-elevated/60" />
        </div>
      ) : classrooms.length === 0 ? (
        <Card className="border-dashed border-border p-8 text-center bg-elevated/20">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10 text-accent mb-3">
            <School className="h-6 w-6" />
          </div>
          <h3 className="text-base font-semibold text-ink">No Classroom Spaces Found</h3>
          <p className="text-sm text-ink-muted mt-1 max-w-md mx-auto">
            {role === "student"
              ? "You are not currently enrolled in any active class streams."
              : "Create your first classroom stream space to share notes and materials with your students."}
          </p>
        </Card>
      ) : (
        <div className="flex flex-col gap-4">
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            {classrooms.map((c) => {
              const isActive = c.id === activeClassroomId;
              return (
                <button
                  key={c.id}
                  onClick={() => navigate(`/${role}/classroom/${c.id}`)}
                  className={`flex items-center gap-2.5 rounded-xl px-4 py-2.5 text-sm font-medium transition-all whitespace-nowrap border ${
                    isActive
                      ? "bg-accent text-accent-foreground border-accent shadow-sm"
                      : "bg-surface text-ink-muted border-border hover:bg-elevated hover:text-ink"
                  }`}
                >
                  <span className="font-semibold">{c.class_name}</span>
                  {c.subject_name && (
                    <span className={`text-xs opacity-90 ${isActive ? "text-accent-foreground/80" : "text-ink-faint"}`}>
                      · {c.subject_name}
                    </span>
                  )}
                </button>
              );
            })}
          </div>

          {activeClassroom && (
            <div className="grid gap-6 lg:grid-cols-3">
              {/* Left Column: Classroom Info & Post Composer (for Teachers) */}
              <div className="flex flex-col gap-6 lg:col-span-1">
                {/* Classroom Overview Card */}
                <Card className="bg-gradient-to-br from-surface to-elevated/40 border-border">
                  <CardHeader className="pb-3">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold uppercase tracking-wider text-accent">
                        {activeClassroom.subject_name || "General Stream"}
                      </span>
                      <Badge variant="neutral">{activeClassroom.class_name}</Badge>
                    </div>
                    <CardTitle className="text-lg text-ink mt-1">
                      {activeClassroom.class_name} — {activeClassroom.subject_name || "Academic Stream"}
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="flex flex-col gap-3 text-xs text-ink-muted border-t border-border/50 pt-3">
                    {activeClassroom.teacher_name && (
                      <div className="flex items-center justify-between">
                        <span>Instructor:</span>
                        <span className="font-medium text-ink">{activeClassroom.teacher_name}</span>
                      </div>
                    )}
                    <div className="flex items-center justify-between">
                      <span>Stream Posts:</span>
                      <span className="font-medium text-ink">{streamData?.items.length ?? 0}</span>
                    </div>
                  </CardContent>
                </Card>

                {/* Teacher Post Composer */}
                {isTeacherOrAdmin && (
                  <Card className="border-border shadow-sm">
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm font-semibold flex items-center gap-2">
                        <Sparkles className="h-4 w-4 text-accent" />
                        Publish to Stream
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <form onSubmit={handleSubmitPost} className="flex flex-col gap-3.5">
                        {/* Post Type Selector */}
                        <div className="grid grid-cols-3 gap-1.5 bg-elevated/60 p-1 rounded-xl">
                          <button
                            type="button"
                            onClick={() => setPostType("note")}
                            className={`flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                              postType === "note"
                                ? "bg-sky-500/20 text-sky-400 border border-sky-500/30"
                                : "text-ink-muted hover:text-ink"
                            }`}
                          >
                            <FileText className="h-3.5 w-3.5" />
                            Note
                          </button>
                          <button
                            type="button"
                            onClick={() => setPostType("announcement")}
                            className={`flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                              postType === "announcement"
                                ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                                : "text-ink-muted hover:text-ink"
                            }`}
                          >
                            <Megaphone className="h-3.5 w-3.5" />
                            Alert
                          </button>
                          <button
                            type="button"
                            onClick={() => setPostType("material")}
                            className={`flex items-center justify-center gap-1.5 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                              postType === "material"
                                ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                                : "text-ink-muted hover:text-ink"
                            }`}
                          >
                            <BookOpen className="h-3.5 w-3.5" />
                            Material
                          </button>
                        </div>

                        <div>
                          <Input
                            placeholder="Post title (e.g. Chapter 4 Practice Notes)"
                            value={postTitle}
                            onChange={(e) => setPostTitle(e.target.value)}
                            required
                            className="text-sm bg-surface"
                          />
                        </div>

                        <div>
                          <Textarea
                            placeholder="Write message, instructions, or notes for your students..."
                            value={postContent}
                            onChange={(e) => setPostContent(e.target.value)}
                            rows={4}
                            required
                            className="text-sm bg-surface resize-none"
                          />
                        </div>

                        {/* Staged Attachments Preview */}
                        {stagedAttachments.length > 0 && (
                          <div className="flex flex-col gap-1.5">
                            <span className="text-[11px] font-medium text-ink-muted">Attachments:</span>
                            <div className="flex flex-wrap gap-2">
                              {stagedAttachments.map((att, idx) => (
                                <div
                                  key={idx}
                                  className="flex items-center gap-2 rounded-lg bg-elevated px-2.5 py-1 text-xs text-ink border border-border"
                                >
                                  <Paperclip className="h-3 w-3 text-accent" />
                                  <span className="max-w-[140px] truncate">{att.file_name}</span>
                                  <button
                                    type="button"
                                    onClick={() => handleRemoveStagedAttachment(idx)}
                                    className="text-ink-faint hover:text-urgent"
                                  >
                                    ×
                                  </button>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}

                        <div className="flex items-center justify-between pt-2 border-t border-border">
                          <label className="flex items-center gap-1.5 text-xs text-ink-muted hover:text-accent cursor-pointer">
                            <Paperclip className="h-4 w-4" />
                            <span>{isUploading ? "Uploading..." : "Attach File"}</span>
                            <input
                              type="file"
                              multiple
                              onChange={handleFileUpload}
                              disabled={isUploading}
                              className="hidden"
                            />
                          </label>

                          <Button
                            type="submit"
                            size="sm"
                            disabled={createPostMutation.isPending || isUploading || !postTitle.trim()}
                            className="gap-1.5"
                          >
                            <Send className="h-3.5 w-3.5" />
                            {createPostMutation.isPending ? "Posting..." : "Publish"}
                          </Button>
                        </div>
                      </form>
                    </CardContent>
                  </Card>
                )}
              </div>

              {/* Right Column: Stream Posts Feed */}
              <div className="flex flex-col gap-4 lg:col-span-2">
                {/* Filter Tabs */}
                <div className="flex items-center justify-between border-b border-border pb-3">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setActiveFilter("all")}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                        activeFilter === "all"
                          ? "bg-accent/15 text-accent font-semibold"
                          : "text-ink-muted hover:text-ink"
                      }`}
                    >
                      All Posts
                    </button>
                    <button
                      onClick={() => setActiveFilter("note")}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                        activeFilter === "note"
                          ? "bg-sky-500/20 text-sky-400 font-semibold"
                          : "text-ink-muted hover:text-ink"
                      }`}
                    >
                      Notes
                    </button>
                    <button
                      onClick={() => setActiveFilter("announcement")}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                        activeFilter === "announcement"
                          ? "bg-amber-500/20 text-amber-400 font-semibold"
                          : "text-ink-muted hover:text-ink"
                      }`}
                    >
                      Announcements
                    </button>
                    <button
                      onClick={() => setActiveFilter("material")}
                      className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
                        activeFilter === "material"
                          ? "bg-emerald-500/20 text-emerald-400 font-semibold"
                          : "text-ink-muted hover:text-ink"
                      }`}
                    >
                      Materials
                    </button>
                  </div>

                  <span className="text-xs text-ink-muted">
                    {streamData?.items.length ?? 0} item{streamData?.items.length === 1 ? "" : "s"}
                  </span>
                </div>

                {/* Posts List */}
                {streamQuery.isLoading ? (
                  <div className="flex flex-col gap-3">
                    <div className="h-32 rounded-xl bg-elevated/60 animate-pulse" />
                    <div className="h-32 rounded-xl bg-elevated/60 animate-pulse" />
                  </div>
                ) : streamData?.items.length === 0 ? (
                  <Card className="border-dashed border-border p-12 text-center bg-elevated/10">
                    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-elevated text-ink-muted mb-3">
                      <FileText className="h-6 w-6" />
                    </div>
                    <h3 className="text-base font-semibold text-ink">Stream is Empty</h3>
                    <p className="text-sm text-ink-muted mt-1">
                      No {activeFilter === "all" ? "" : activeFilter} posts have been published to this classroom yet.
                    </p>
                  </Card>
                ) : (
                  <div className="flex flex-col gap-4">
                    {streamData?.items.map((post) => {
                      const isAuthor = currentUser?.user_id === post.author_id;
                      const canDelete = isAuthor || role === "admin" || role === "principal";

                      let badgeTone = "neutral";
                      let badgeIcon = FileText;
                      if (post.post_type === "announcement") {
                        badgeTone = "warning";
                        badgeIcon = Megaphone;
                      } else if (post.post_type === "material") {
                        badgeTone = "positive";
                        badgeIcon = BookOpen;
                      }

                      const BadgeIcon = badgeIcon;

                      return (
                        <Card key={post.id} className="border-border hover:border-border-strong transition-all bg-surface">
                          <CardHeader className="pb-2 flex flex-row items-start justify-between gap-4">
                            <div className="flex items-start gap-3">
                              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-accent/10 text-accent font-semibold text-sm">
                                {post.author?.full_name?.slice(0, 2).toUpperCase() || "T"}
                              </div>
                              <div className="flex flex-col">
                                <div className="flex items-center gap-2">
                                  <span className="text-sm font-semibold text-ink">
                                    {post.author?.full_name || "Teacher"}
                                  </span>
                                  <Badge variant={badgeTone as any} className="gap-1 text-[11px] py-0">
                                    <BadgeIcon className="h-3 w-3" />
                                    {post.post_type.toUpperCase()}
                                  </Badge>
                                </div>
                                <div className="flex items-center gap-2 text-xs text-ink-muted mt-0.5">
                                  <Clock className="h-3 w-3" />
                                  <span>{timeAgo(post.created_at)}</span>
                                  <span>·</span>
                                  <span>{new Date(post.created_at).toLocaleDateString()}</span>
                                </div>
                              </div>
                            </div>

                            {canDelete && (
                              <ConfirmDialog
                                trigger={
                                  <button className="text-ink-faint hover:text-urgent p-1 rounded-md transition-colors">
                                    <Trash2 className="h-4 w-4" />
                                  </button>
                                }
                                title="Delete Stream Post"
                                description="Are you sure you want to delete this post? All linked attachments will also be removed."
                                confirmLabel="Delete"
                                onConfirm={() => deletePostMutation.mutate(post.id)}
                              />
                            )}
                          </CardHeader>

                          <CardContent className="pt-2 flex flex-col gap-3">
                            <h4 className="text-base font-semibold text-ink leading-snug">{post.title}</h4>
                            <div className="text-sm text-ink-muted whitespace-pre-wrap leading-relaxed">
                              {post.content}
                            </div>

                            {/* Attachments Display */}
                            {post.attachments && post.attachments.length > 0 && (
                              <div className="mt-2 flex flex-col gap-2 pt-3 border-t border-border/60">
                                <span className="text-xs font-semibold text-ink-muted uppercase tracking-wider">
                                  Attachments ({post.attachments.length})
                                </span>
                                <div className="grid gap-2 sm:grid-cols-2">
                                  {post.attachments.map((att) => {
                                    const AttIcon = getFileIcon(att.file_name, att.file_type);
                                    return (
                                      <a
                                        key={att.id}
                                        href={att.file_url}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        className="flex items-center justify-between gap-3 rounded-xl border border-border bg-elevated/30 p-2.5 hover:bg-elevated/70 transition-colors group"
                                      >
                                        <div className="flex items-center gap-2.5 min-w-0">
                                          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent/10 text-accent">
                                            <AttIcon className="h-4 w-4" />
                                          </div>
                                          <div className="flex flex-col min-w-0">
                                            <span className="text-xs font-medium text-ink truncate group-hover:text-accent">
                                              {att.file_name}
                                            </span>
                                            <span className="text-[11px] text-ink-faint">
                                              {formatBytes(att.file_size)}
                                            </span>
                                          </div>
                                        </div>
                                        <Download className="h-4 w-4 text-ink-faint group-hover:text-accent shrink-0" />
                                      </a>
                                    );
                                  })}
                                </div>
                              </div>
                            )}
                          </CardContent>
                        </Card>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
