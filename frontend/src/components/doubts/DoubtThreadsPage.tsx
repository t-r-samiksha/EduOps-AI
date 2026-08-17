import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  ArrowLeft,
  BadgeCheck,
  Bot,
  Loader2,
  MessageSquare,
  MessageSquarePlus,
  Send,
  Undo2,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import {
  useCreateDoubtThread,
  useDoubtThread,
  useDoubtThreads,
  useReplyToThread,
  useUnverifyReply,
  useVerifyReply,
} from "@/api/hooks/useDoubtThreads";
import { useTimetableActive } from "@/api/hooks/useTimetable";
import { useAuthStore } from "@/store/authStore";
import { ApiError } from "@/api/client";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import type { DoubtThread, ThreadReply } from "@/api/types";
import { cn } from "@/lib/utils";

/**
 * Doubt threads — one component for both /student/doubts and /teacher/doubts.
 *
 * THE POINT OF THIS SCREEN IS THE VERIFY BUTTON. A teacher marking a reply verified
 * ingests it into the bot's knowledge base, so the same question asked of the Doubt Bot
 * afterwards is answered by a human teacher's words instead of a PDF. That causal link
 * is invisible unless the UI says so, which is why the confirmation is an inline panel
 * that stays on screen rather than a toast that vanishes before anyone reads it.
 *
 * Selected thread lives in the URL (`?thread=`), the same convention useSelectedChild
 * set with `?child=` and the fees page with `?tab=` — so a thread is linkable and the
 * back button returns to the list.
 */

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ThreadListRow({ thread, onOpen }: { thread: DoubtThread; onOpen: (id: number) => void }) {
  return (
    <button
      type="button"
      onClick={() => onOpen(thread.id)}
      className={cn(
        "flex w-full flex-col gap-1.5 rounded-2xl border border-l-4 border-border bg-card px-4 py-3 text-left shadow-elevated transition-colors hover:border-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        thread.resolved ? "border-l-positive" : "border-l-warning"
      )}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="min-w-0 font-display text-sm font-semibold text-ink">{thread.title}</span>
        {thread.resolved ? (
          <Badge variant="positive" className="shrink-0">
            <BadgeCheck className="h-3 w-3" aria-hidden="true" /> Answered
          </Badge>
        ) : (
          <Badge variant="warning" className="shrink-0">
            Open
          </Badge>
        )}
      </div>
      <p className="line-clamp-2 text-xs text-ink-muted">{thread.body}</p>
      <div className="flex flex-wrap items-center gap-2 text-[0.6875rem] text-ink-faint">
        <span>{thread.author_name}</span>
        <span aria-hidden="true">·</span>
        <span className="flex items-center gap-1">
          <MessageSquare className="h-3 w-3" aria-hidden="true" />
          {thread.reply_count} {thread.reply_count === 1 ? "reply" : "replies"}
        </span>
        <span aria-hidden="true">·</span>
        <span>{timeLabel(thread.created_at)}</span>
      </div>
    </button>
  );
}

function ComposeThread({ classId, onCreated }: { classId: number; onCreated: (id: number) => void }) {
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const create = useCreateDoubtThread();

  if (!open) {
    return (
      <Button onClick={() => setOpen(true)} className="self-start">
        <MessageSquarePlus className="h-4 w-4" aria-hidden="true" /> Ask a doubt
      </Button>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ask a doubt</CardTitle>
        <CardDescription>Your class and your teacher can see this and reply.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <Field label="What's the question?">
          <Input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={255}
            placeholder="Why does ice float on water?"
          />
        </Field>
        <Field label="Add any detail">
          <Textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={3}
            placeholder="Everything else sinks when it turns solid, so I don't understand why ice doesn't."
          />
        </Field>
        {create.isError && (
          <p className="text-sm text-urgent">
            {create.error instanceof ApiError ? create.error.message : "Could not post this doubt."}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button
            disabled={!title.trim() || !body.trim() || create.isPending}
            onClick={() =>
              create.mutate(
                { class_id: classId, title: title.trim(), body: body.trim() },
                {
                  onSuccess: (thread) => {
                    setTitle("");
                    setBody("");
                    setOpen(false);
                    onCreated(thread.id);
                  },
                }
              )
            }
          >
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Send className="h-4 w-4" aria-hidden="true" />}
            {create.isPending ? "Posting…" : "Post doubt"}
          </Button>
          <Button variant="ghost" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ReplyRow({
  reply,
  canVerify,
  threadId,
  onVerified,
}: {
  reply: ThreadReply;
  canVerify: boolean;
  threadId: number;
  onVerified: (note: string) => void;
}) {
  const verify = useVerifyReply();

  return (
    <div
      className={cn(
        "flex flex-col gap-1.5 rounded-xl px-3.5 py-2.5",
        reply.is_verified
          ? // The verified answer wears --positive, matching how the bot's own citation
            // footnote marks it — one signal, two screens.
            "border-l-2 border-l-positive bg-positive/5"
          : "bg-elevated/40"
      )}
    >
      <div className="flex flex-wrap items-center gap-2">
        {reply.is_verified && (
          <Badge variant="positive">
            <BadgeCheck className="h-3 w-3" aria-hidden="true" /> Verified answer
          </Badge>
        )}
        <span className="text-xs font-semibold text-ink">{reply.author_name}</span>
        <span className="font-mono text-[0.6875rem] text-ink-faint">{timeLabel(reply.created_at)}</span>
      </div>
      <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{reply.body}</p>

      {canVerify && !reply.is_verified && (
        <div className="flex flex-col gap-1">
          <Button
            variant="outline"
            size="sm"
            className="self-start"
            disabled={verify.isPending}
            aria-label={`Mark ${reply.author_name}'s reply as the verified answer and add it to the knowledge base`}
            onClick={() =>
              verify.mutate(
                { threadId, replyId: reply.id },
                { onSuccess: (result) => onVerified(result.kb_note) }
              )
            }
          >
            {verify.isPending ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
            ) : (
              <BadgeCheck className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {/* Says what is happening, not just that something is. The embedding
                round-trip is ~1s of otherwise-dead air, and this is the moment that
                explains the whole feature. */}
            {verify.isPending ? "Adding to knowledge base…" : "Mark verified"}
          </Button>
          {verify.isError && (
            <p className="text-xs text-urgent">
              {verify.error instanceof ApiError ? verify.error.message : "Could not verify this reply."}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

function ThreadDetail({
  threadId,
  canVerify,
  onBack,
}: {
  threadId: number;
  canVerify: boolean;
  onBack: () => void;
}) {
  const thread = useDoubtThread(threadId);
  const reply = useReplyToThread();
  const unverify = useUnverifyReply();
  const [replyBody, setReplyBody] = useState("");
  const [kbNote, setKbNote] = useState<string | null>(null);

  if (thread.isLoading) return <div className="h-64 animate-pulse rounded-2xl bg-elevated/60" />;
  if (thread.isError) {
    return (
      <Card>
        <CardContent className="py-6">
          <p className="text-sm text-urgent">
            {thread.error instanceof ApiError ? thread.error.message : "Could not load this thread."}
          </p>
        </CardContent>
      </Card>
    );
  }
  if (!thread.data) return null;
  const data = thread.data;
  const verified = data.replies.find((r) => r.is_verified);
  const others = data.replies.filter((r) => !r.is_verified);

  return (
    <div className="flex flex-col gap-3">
      <Button variant="ghost" onClick={onBack} className="self-start" aria-label="Back to all doubts">
        <ArrowLeft className="h-4 w-4" aria-hidden="true" /> All doubts
      </Button>

      <Card>
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <CardTitle>{data.title}</CardTitle>
            {data.resolved ? (
              <Badge variant="positive">
                <BadgeCheck className="h-3 w-3" aria-hidden="true" /> Answered
              </Badge>
            ) : (
              <Badge variant="warning">Open</Badge>
            )}
          </div>
          <CardDescription>
            Asked by {data.author_name} · {timeLabel(data.created_at)}
            {data.class_name ? ` · ${data.class_name}` : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-ink">{data.body}</p>
        </CardContent>
      </Card>

      {/* The KB confirmation is a persistent panel, not a toast: it is the causal link
          between verifying and the bot getting smarter, and a reader who missed it has
          missed the feature. aria-live so it is announced, not just seen. */}
      <div aria-live="polite">
        {kbNote && (
          <div className="flex items-start gap-2 rounded-xl border border-positive/40 bg-positive/5 px-3.5 py-3">
            <Bot className="mt-0.5 h-4 w-4 shrink-0 text-positive" aria-hidden="true" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-positive">Answer added to the Doubt Bot</p>
              <p className="text-xs text-ink-muted">{kbNote}</p>
              <p className="mt-1 text-xs text-ink-faint">
                Ask the bot this question now and it will cite this reply instead of a document.
              </p>
            </div>
          </div>
        )}
      </div>

      {verified && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Verified answer</CardTitle>
            <CardDescription>
              Certified by the class teacher, and part of the Doubt Bot's knowledge base.
            </CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-2">
            <ReplyRow reply={verified} canVerify={false} threadId={data.id} onVerified={setKbNote} />
            {canVerify && (
              <div className="flex flex-col gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  className="self-start"
                  disabled={unverify.isPending}
                  aria-label="Retract this verified answer and remove it from the knowledge base"
                  onClick={() =>
                    unverify.mutate(data.id, {
                      onSuccess: (result) =>
                        setKbNote(
                          `Retracted — ${result.chunks_deleted} entry removed from the knowledge base. The bot will no longer cite it.`
                        ),
                    })
                  }
                >
                  <Undo2 className="h-3.5 w-3.5" aria-hidden="true" />
                  {unverify.isPending ? "Removing…" : "Retract verification"}
                </Button>
                {unverify.isError && (
                  <p className="text-xs text-urgent">
                    {unverify.error instanceof ApiError ? unverify.error.message : "Could not retract."}
                  </p>
                )}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">
            {others.length} {others.length === 1 ? "reply" : "replies"}
          </CardTitle>
          {canVerify && others.length > 0 && (
            <CardDescription>
              Marking one verified adds it to the Doubt Bot's knowledge base for the whole grade.
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {others.length === 0 && <p className="text-sm text-ink-muted">No replies yet.</p>}
          {others.map((r) => (
            <ReplyRow key={r.id} reply={r} canVerify={canVerify} threadId={data.id} onVerified={setKbNote} />
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Add a reply</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <Textarea
            value={replyBody}
            onChange={(e) => setReplyBody(e.target.value)}
            rows={3}
            aria-label="Your reply"
            placeholder="Share what you think, or explain the answer."
          />
          {reply.isError && (
            <p className="text-sm text-urgent">
              {reply.error instanceof ApiError ? reply.error.message : "Could not post this reply."}
            </p>
          )}
          <Button
            className="self-start"
            disabled={!replyBody.trim() || reply.isPending}
            onClick={() =>
              reply.mutate(
                { threadId: data.id, body: replyBody.trim() },
                { onSuccess: () => setReplyBody("") }
              )
            }
          >
            {reply.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden="true" /> : <Send className="h-4 w-4" aria-hidden="true" />}
            {reply.isPending ? "Posting…" : "Post reply"}
          </Button>
        </CardContent>
      </Card>
    </div>
  );
}

export default function DoubtThreadsPage() {
  const { role } = useAuthStore();
  const isTeacher = role === "teacher";
  const [searchParams, setSearchParams] = useSearchParams();
  const selected = Number(searchParams.get("thread")) || undefined;

  // class_id is RESOLVED, never typed: any slot the timetable returns is by definition
  // a class the caller belongs to. Same reasoning as StudentDoubtBot.
  const timetable = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR, retry: false });
  const classId = timetable.data?.[0]?.class_id;
  const threads = useDoubtThreads({ classId });

  function openThread(id: number | undefined) {
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      if (id === undefined) next.delete("thread");
      else next.set("thread", String(id));
      return next;
    });
  }

  const items = threads.data?.items ?? [];
  const open = items.filter((t) => !t.resolved).length;

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Doubts"
        description={
          isTeacher
            ? "Your class's questions. Reply, then mark the best answer verified — a verified answer joins the Doubt Bot's knowledge base for the whole grade."
            : "Ask your class and your teacher. Once a teacher verifies an answer, the Doubt Bot can use it too."
        }
      />

      {timetable.isLoading && <div className="h-24 animate-pulse rounded-2xl bg-elevated/60" />}

      {!timetable.isLoading && classId === undefined && (
        <Card>
          <CardContent className="py-6">
            <p className="text-sm text-ink-muted">
              {isTeacher
                ? "You have no scheduled classes yet, so there is no class to show doubts for."
                : "You are not enrolled in a class yet, so there is nowhere to post a doubt."}
            </p>
          </CardContent>
        </Card>
      )}

      {classId !== undefined && selected !== undefined && (
        <ThreadDetail threadId={selected} canVerify={isTeacher} onBack={() => openThread(undefined)} />
      )}

      {classId !== undefined && selected === undefined && (
        <>
          {!isTeacher && <ComposeThread classId={classId} onCreated={openThread} />}

          {threads.isLoading && <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />}
          {threads.isError && (
            <Card>
              <CardContent className="py-6">
                <p className="text-sm text-urgent">
                  {threads.error instanceof ApiError ? threads.error.message : "Could not load doubts."}
                </p>
              </CardContent>
            </Card>
          )}

          {threads.data && (
            <div className={cn("flex flex-col gap-2 transition-opacity", threads.isFetching && "opacity-60")}>
              {items.length > 0 && (
                <p className="text-xs text-ink-muted">
                  {open} open · {items.length - open} answered
                </p>
              )}
              {items.length === 0 ? (
                <Card>
                  <CardContent className="flex flex-col items-center gap-1 py-8 text-center">
                    <MessageSquare className="h-6 w-6 text-ink-muted" aria-hidden="true" />
                    <p className="font-display text-sm font-medium text-ink">No doubts yet</p>
                    <p className="text-xs text-ink-muted">
                      {isTeacher ? "Your students haven't asked anything yet." : "Be the first to ask."}
                    </p>
                  </CardContent>
                </Card>
              ) : (
                items.map((t) => <ThreadListRow key={t.id} thread={t} onOpen={openThread} />)
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
