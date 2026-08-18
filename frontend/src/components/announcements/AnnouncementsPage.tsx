import { useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  Loader2,
  Megaphone,
  Send,
  Users,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import { apiGet } from "@/api/client";
import { useQuery } from "@tanstack/react-query";
import {
  useAcknowledgeAnnouncement,
  useAnnouncementAckStatus,
  useAnnouncementFeed,
  useCreateAnnouncement,
} from "@/api/hooks/useAnnouncements";
import { useAuthStore } from "@/store/authStore";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { ApiError } from "@/api/client";
import type {
  Announcement,
  AnnouncementCategory,
  AnnouncementPriority,
  AnnouncementScope,
} from "@/api/types";
import { cn } from "@/lib/utils";

/**
 * Announcements — one role-aware component for all five roles.
 *
 * THE SCOPE BADGE IS THE POINT OF THIS SCREEN. Three announcements with no badge look
 * like three announcements; with School / Grade 3 / Grade 3 - A on them, the targeting
 * is the thing you can see. Same for a parent's child tag: "Grade 3 · for Aarav, Diya"
 * on one item and no tag on the school-wide one IS the story of scoped delivery. Both
 * come from the server (`scope_label`, `related_children`) rather than being recomputed
 * here, so the badge can never disagree with the audience the backend actually resolved.
 *
 * The composer offers only what the caller may post to, from
 * GET /announcements/postable-scopes — a teacher has no School-wide option at all
 * rather than a disabled one. That is a rendering convenience, not the boundary: the
 * server re-checks every post.
 */

interface PostableScopes {
  can_post: boolean;
  can_post_school: boolean;
  grades: number[];
  classes: { id: number; name: string; grade_level: number | null }[];
}

const CATEGORY_LABEL: Record<AnnouncementCategory, string> = {
  event: "Event",
  academic: "Academic",
  fee: "Fees",
  general: "General",
};

function timeLabel(iso: string): string {
  return new Date(iso).toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** School / Grade 3 / Grade 3 - A. Deliberately high-contrast and never truncated —
 * this is the element that makes targeting legible at a glance. */
function ScopeBadge({ announcement }: { announcement: Announcement }) {
  const tone =
    announcement.scope_type === "school"
      ? "bg-[hsl(var(--chip-5)/0.16)] text-[hsl(var(--chip-5))] border-[hsl(var(--chip-5)/0.35)]"
      : announcement.scope_type === "grade"
        ? "bg-[hsl(var(--chip-1)/0.16)] text-[hsl(var(--chip-1))] border-[hsl(var(--chip-1)/0.35)]"
        : "bg-[hsl(var(--chip-4)/0.16)] text-[hsl(var(--chip-4))] border-[hsl(var(--chip-4)/0.35)]";
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1",
        "text-xs font-semibold tracking-tight",
        tone,
      )}
    >
      <Users className="h-3.5 w-3.5" aria-hidden="true" />
      {announcement.scope_label}
    </span>
  );
}

/** Parents only. "for Aarav, Diya" versus nothing on a school-wide item is exactly the
 * difference between targeted and broadcast, so it sits beside the scope badge rather
 * than buried in the body. */
function ChildTag({ announcement }: { announcement: Announcement }) {
  if (announcement.related_children.length === 0) return null;
  const names = announcement.related_children.map((c) => c.name ?? `#${c.id}`).join(", ");
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1",
        "border border-[hsl(var(--accent)/0.35)] bg-[hsl(var(--accent)/0.12)]",
        "text-xs font-semibold text-[hsl(var(--accent))]",
      )}
    >
      for {names}
    </span>
  );
}

function AnnouncementCard({
  announcement,
  onAcknowledge,
  acknowledging,
  canSeeAckStatus,
  onOpenAckStatus,
}: {
  announcement: Announcement;
  onAcknowledge: (id: number) => void;
  acknowledging: boolean;
  canSeeAckStatus: boolean;
  onOpenAckStatus: (id: number) => void;
}) {
  const urgent = announcement.priority === "urgent";
  const important = announcement.priority === "important";

  return (
    <Card
      className={cn(
        "overflow-hidden transition-colors",
        urgent && "border-[hsl(var(--urgent)/0.55)] bg-[hsl(var(--urgent)/0.06)]",
        important && !urgent && "border-[hsl(var(--warning)/0.5)] bg-[hsl(var(--warning)/0.05)]",
      )}
    >
      <CardContent className="space-y-3 p-4 sm:p-5">
        {urgent && (
          <p className="flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-[hsl(var(--urgent))]">
            <AlertTriangle className="h-4 w-4" aria-hidden="true" />
            Urgent
          </p>
        )}

        {/* Badges wrap above the title on a phone so neither is ever truncated. */}
        <div className="flex flex-wrap items-center gap-2">
          <ScopeBadge announcement={announcement} />
          <ChildTag announcement={announcement} />
          <span className="rounded-full border border-[hsl(var(--border))] px-2.5 py-1 text-xs font-medium text-[hsl(var(--ink-muted))]">
            {CATEGORY_LABEL[announcement.category] ?? announcement.category}
          </span>
        </div>

        <div className="space-y-1.5">
          <h3 className="text-base font-semibold leading-snug text-[hsl(var(--ink))] sm:text-lg">
            {announcement.title}
          </h3>
          <p className="whitespace-pre-line text-sm leading-relaxed text-[hsl(var(--ink-muted))]">
            {announcement.body}
          </p>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
          <p className="text-xs text-[hsl(var(--ink-faint))]">
            {announcement.author_name ?? "School"} · {timeLabel(announcement.created_at)}
          </p>

          <div className="flex items-center gap-2">
            {canSeeAckStatus && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => onOpenAckStatus(announcement.id)}
                aria-label={`See who has read "${announcement.title}"`}
              >
                Who has read this
              </Button>
            )}
            {announcement.acknowledged ? (
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-[hsl(var(--positive))]">
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                Acknowledged
              </span>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={acknowledging}
                onClick={() => onAcknowledge(announcement.id)}
                aria-label={`Acknowledge "${announcement.title}"`}
              >
                {acknowledging ? (
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                ) : (
                  <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
                )}
                Acknowledge
              </Button>
            )}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function Composer({ scopes }: { scopes: PostableScopes }) {
  const create = useCreateAnnouncement();
  const [scopeType, setScopeType] = useState<AnnouncementScope>(
    scopes.can_post_school ? "school" : scopes.grades.length ? "grade" : "class",
  );
  const [grade, setGrade] = useState<number | "">(scopes.grades[0] ?? "");
  const [classId, setClassId] = useState<number | "">(scopes.classes[0]?.id ?? "");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [category, setCategory] = useState<AnnouncementCategory>("general");
  const [priority, setPriority] = useState<AnnouncementPriority>("normal");
  const [sent, setSent] = useState<number | null>(null);

  // Only the options this caller may actually use. A teacher gets no School-wide entry
  // at all rather than a disabled one — an option you can see but not use reads as a
  // broken UI, not a permission.
  const scopeOptions: { value: AnnouncementScope; label: string }[] = [
    ...(scopes.can_post_school ? [{ value: "school" as const, label: "School-wide" }] : []),
    ...(scopes.grades.length ? [{ value: "grade" as const, label: "A whole grade" }] : []),
    ...(scopes.classes.length ? [{ value: "class" as const, label: "One class" }] : []),
  ];

  function submit(e: React.FormEvent) {
    e.preventDefault();
    setSent(null);
    create.mutate(
      {
        scope_type: scopeType,
        scope_grade_level: scopeType === "grade" ? Number(grade) : null,
        scope_class_id: scopeType === "class" ? Number(classId) : null,
        title: title.trim(),
        body: body.trim(),
        category,
        priority,
      },
      {
        onSuccess: (res) => {
          setSent(res.recipients);
          setTitle("");
          setBody("");
        },
      },
    );
  }

  const error = create.error instanceof ApiError ? create.error.message : null;

  return (
    <Card>
      <CardContent className="p-4 sm:p-5">
        <h2 className="mb-4 flex items-center gap-2 text-sm font-semibold text-[hsl(var(--ink))]">
          <Megaphone className="h-4 w-4" aria-hidden="true" />
          New announcement
        </h2>

        <form onSubmit={submit} className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Send to">
              <select
                value={scopeType}
                onChange={(e) => setScopeType(e.target.value as AnnouncementScope)}
                aria-label="Announcement scope"
                className="h-10 w-full rounded-[var(--radius)] border border-[hsl(var(--border))] bg-[hsl(var(--paper))] px-3 text-sm text-[hsl(var(--ink))]"
              >
                {scopeOptions.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </Field>

            {scopeType === "grade" && (
              <Field label="Grade">
                <select
                  value={grade}
                  onChange={(e) => setGrade(Number(e.target.value))}
                  aria-label="Target grade"
                  className="h-10 w-full rounded-[var(--radius)] border border-[hsl(var(--border))] bg-[hsl(var(--paper))] px-3 text-sm text-[hsl(var(--ink))]"
                >
                  {scopes.grades.map((g) => (
                    <option key={g} value={g}>
                      Grade {g}
                    </option>
                  ))}
                </select>
              </Field>
            )}

            {scopeType === "class" && (
              <Field label="Class">
                <select
                  value={classId}
                  onChange={(e) => setClassId(Number(e.target.value))}
                  aria-label="Target class"
                  className="h-10 w-full rounded-[var(--radius)] border border-[hsl(var(--border))] bg-[hsl(var(--paper))] px-3 text-sm text-[hsl(var(--ink))]"
                >
                  {scopes.classes.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </div>

          <Field label="Title">
            <Input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Science fair on the 28th"
              maxLength={255}
              required
            />
          </Field>

          <Field label="Message">
            <Textarea
              value={body}
              onChange={(e) => setBody(e.target.value)}
              placeholder="What do they need to know, and by when?"
              rows={4}
              required
            />
          </Field>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Category">
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value as AnnouncementCategory)}
                aria-label="Category"
                className="h-10 w-full rounded-[var(--radius)] border border-[hsl(var(--border))] bg-[hsl(var(--paper))] px-3 text-sm text-[hsl(var(--ink))]"
              >
                {(["general", "event", "academic", "fee"] as const).map((c) => (
                  <option key={c} value={c}>
                    {CATEGORY_LABEL[c]}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Priority">
              <select
                value={priority}
                onChange={(e) => setPriority(e.target.value as AnnouncementPriority)}
                aria-label="Priority"
                className="h-10 w-full rounded-[var(--radius)] border border-[hsl(var(--border))] bg-[hsl(var(--paper))] px-3 text-sm text-[hsl(var(--ink))]"
              >
                <option value="normal">Normal</option>
                <option value="important">Important</option>
                <option value="urgent">Urgent — pinned to the top</option>
              </select>
            </Field>
          </div>

          {error && (
            <p role="alert" className="text-sm font-medium text-[hsl(var(--urgent))]">
              {error}
            </p>
          )}
          {sent !== null && (
            <p
              role="status"
              className="text-sm font-medium text-[hsl(var(--positive))]"
            >
              Sent to {sent} {sent === 1 ? "person" : "people"} — it is in their notifications now.
            </p>
          )}

          <Button type="submit" disabled={create.isPending || !title.trim() || !body.trim()}>
            {create.isPending ? (
              <Loader2 className="mr-2 h-4 w-4 animate-spin" aria-hidden="true" />
            ) : (
              <Send className="mr-2 h-4 w-4" aria-hidden="true" />
            )}
            Post announcement
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function AckStatusPanel({ announcementId, onClose }: { announcementId: number; onClose: () => void }) {
  const { data, isLoading } = useAnnouncementAckStatus(announcementId);
  return (
    <Card>
      <CardContent className="space-y-3 p-4 sm:p-5">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold text-[hsl(var(--ink))]">Who has read this</h2>
          <Button type="button" variant="ghost" size="sm" onClick={onClose} aria-label="Close read receipts">
            Close
          </Button>
        </div>
        {isLoading || !data ? (
          <p className="text-sm text-[hsl(var(--ink-muted))]">Loading…</p>
        ) : (
          <>
            <p className="text-sm text-[hsl(var(--ink-muted))]">
              <span className="font-semibold text-[hsl(var(--ink))]">
                {data.acknowledged_count} of {data.audience_size}
              </span>{" "}
              have acknowledged ({data.acknowledged_pct}%)
            </p>
            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--positive))]">
                  Acknowledged
                </p>
                <ul className="space-y-1 text-sm text-[hsl(var(--ink-muted))]">
                  {data.acknowledged.length === 0 && <li>Nobody yet</li>}
                  {data.acknowledged.map((p) => (
                    <li key={p.user_id}>
                      {p.name ?? `#${p.user_id}`}{" "}
                      <span className="text-[hsl(var(--ink-faint))]">({p.role})</span>
                    </li>
                  ))}
                </ul>
              </div>
              <div>
                <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-[hsl(var(--ink-faint))]">
                  Outstanding
                </p>
                <ul className="space-y-1 text-sm text-[hsl(var(--ink-muted))]">
                  {data.outstanding.length === 0 && <li>Everyone has read it</li>}
                  {data.outstanding.slice(0, 12).map((p) => (
                    <li key={p.user_id}>
                      {p.name ?? `#${p.user_id}`}{" "}
                      <span className="text-[hsl(var(--ink-faint))]">({p.role})</span>
                    </li>
                  ))}
                  {data.outstanding.length > 12 && (
                    <li className="text-[hsl(var(--ink-faint))]">
                      and {data.outstanding.length - 12} more
                    </li>
                  )}
                </ul>
              </div>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function AnnouncementsPage() {
  const role = useAuthStore((s) => s.role);
  // Needed for the ack-status button: the Supabase session carries only a role claim,
  // not the app's numeric user id, so "did I write this?" needs /auth/me.
  const me = useCurrentUser();
  const feed = useAnnouncementFeed();
  const acknowledge = useAcknowledgeAnnouncement();
  const [ackStatusId, setAckStatusId] = useState<number | null>(null);

  const canCompose = role === "admin" || role === "principal" || role === "teacher";
  const scopes = useQuery({
    queryKey: ["announcement-postable-scopes"],
    queryFn: () => apiGet<PostableScopes>("/announcements/postable-scopes"),
    enabled: canCompose,
  });

  const items = feed.data?.items ?? [];
  const unread = feed.data?.unacknowledged_count ?? 0;
  const subtitle = useMemo(() => {
    if (feed.isLoading) return "Loading…";
    if (items.length === 0) return "Nothing for you right now.";
    return `${items.length} for you · ${unread} not yet acknowledged`;
  }, [feed.isLoading, items.length, unread]);

  return (
    <div className="space-y-5">
      <PageHeader title="Announcements" description={subtitle} />

      {canCompose && scopes.data?.can_post && <Composer scopes={scopes.data} />}

      {ackStatusId !== null && (
        <AckStatusPanel announcementId={ackStatusId} onClose={() => setAckStatusId(null)} />
      )}

      {/* aria-live so an acknowledgement or a new post is announced, not just repainted. */}
      <section aria-live="polite" aria-label="Announcements for you" className="space-y-3">
        {feed.isLoading && (
          <p className="text-sm text-[hsl(var(--ink-muted))]">Loading announcements…</p>
        )}

        {!feed.isLoading && items.length === 0 && (
          <Card>
            <CardContent className="p-6 text-center">
              <Megaphone
                className="mx-auto mb-2 h-6 w-6 text-[hsl(var(--ink-faint))]"
                aria-hidden="true"
              />
              <p className="text-sm text-[hsl(var(--ink-muted))]">
                No announcements for you yet.
              </p>
            </CardContent>
          </Card>
        )}

        {items.map((a) => (
          <AnnouncementCard
            key={a.id}
            announcement={a}
            onAcknowledge={(id) => acknowledge.mutate(id)}
            acknowledging={acknowledge.isPending && acknowledge.variables === a.id}
            // Author, admin or principal only - the backend enforces the same rule, so
            // showing it to anyone else would just render a button that 403s.
            canSeeAckStatus={
              role === "admin" || role === "principal" || a.author_id === me.data?.user_id
            }
            onOpenAckStatus={setAckStatusId}
          />
        ))}
      </section>
    </div>
  );
}
