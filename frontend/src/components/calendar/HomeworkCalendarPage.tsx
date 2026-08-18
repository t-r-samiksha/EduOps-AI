import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Award,
  Calendar as CalendarIcon,
  Clock,
  FileCheck,
  HelpCircle,
  RotateCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  useHomeworkCalendar,
  useTriggerCalendarSync,
  HomeworkEvent,
} from "@/api/hooks/useHomeworkCalendar";
import { useAuthStore } from "@/store/authStore";
import { useMyUserId, useViewedStudent } from "@/hooks/useViewedStudent";
import { deadlineRoute } from "@/lib/deadlineLinks";
import { ApiError } from "@/api/client";

const TYPE_FILTERS = ["all", "assignment", "quiz", "exam"] as const;

/** Buckets, soonest first. A flat list sorted by date makes you compute urgency yourself;
 *  what a student actually needs to know is "is this today or next week". */
type BucketKey = "overdue" | "today" | "tomorrow" | "this_week" | "later";

const BUCKET_LABEL: Record<BucketKey, string> = {
  overdue: "Overdue",
  today: "Today",
  tomorrow: "Tomorrow",
  this_week: "This week",
  later: "Later",
};

const BUCKET_ORDER: BucketKey[] = ["overdue", "today", "tomorrow", "this_week", "later"];

/** Rail dot + accent per bucket. Overdue is the only one that shouts. */
const BUCKET_TONE: Record<BucketKey, { dot: string; label: string }> = {
  overdue: { dot: "bg-red-500", label: "text-red-600" },
  today: { dot: "bg-amber-500", label: "text-amber-600" },
  tomorrow: { dot: "bg-primary", label: "text-primary" },
  this_week: { dot: "bg-emerald-500", label: "text-emerald-600" },
  later: { dot: "bg-muted-foreground/40", label: "text-muted-foreground" },
};

function startOfDay(d: Date): Date {
  const copy = new Date(d);
  copy.setHours(0, 0, 0, 0);
  return copy;
}

/** Which bucket a deadline falls in, relative to now.
 *
 *  Uses calendar-day boundaries, not elapsed hours: something due at 9am tomorrow is
 *  "Tomorrow" even though it is 14 hours away, because that is how a person reads a
 *  deadline. `status === "completed"` never counts as overdue - a sat exam is done, not late.
 */
function bucketFor(ev: HomeworkEvent, now: Date): BucketKey {
  const due = new Date(ev.end);
  if (due.getTime() < now.getTime() && ev.status !== "completed") return "overdue";

  const today = startOfDay(now);
  const dueDay = startOfDay(due);
  const dayDiff = Math.round((dueDay.getTime() - today.getTime()) / 86_400_000);

  if (dayDiff <= 0) return "today";
  if (dayDiff === 1) return "tomorrow";
  if (dayDiff <= 7) return "this_week";
  return "later";
}

function typeIcon(type: string) {
  switch (type) {
    case "assignment":
      return <FileCheck className="h-4 w-4 text-blue-500" />;
    case "quiz":
      return <HelpCircle className="h-4 w-4 text-purple-500" />;
    case "exam":
      return <Award className="h-4 w-4 text-amber-500" />;
    default:
      return <CalendarIcon className="h-4 w-4 text-primary" />;
  }
}

export default function HomeworkCalendarPage() {
  const { role } = useAuthStore();
  const navigate = useNavigate();
  const isStaff = role === "admin" || role === "principal" || role === "teacher";

  // THIS PAGE WAS ALWAYS EMPTY, FOR EVERYONE. It resolved its subject as
  // `Number(user.id) || 2` - user.id is a Supabase UUID, so Number() is NaN and the `|| 2`
  // turned every request, in every role and school, into "show me student #2's deadlines".
  // GET /calendar/homework/{id} already returns a teacher's own taught-class deadlines and an
  // admin's school-wide ones; it was simply never asked about the right person.
  const myUserId = useMyUserId();
  const viewed = useViewedStudent();
  const calendarSubjectId = isStaff ? myUserId : viewed.studentId;

  const { data: events = [], isLoading, isError } = useHomeworkCalendar(calendarSubjectId);
  const syncMutation = useTriggerCalendarSync();

  const [selectedType, setSelectedType] = useState<string>("all");
  const [selectedSubject, setSelectedSubject] = useState<string>("all");
  const [syncError, setSyncError] = useState<string | null>(null);

  const subjects = useMemo(
    () => Array.from(new Set(events.map((e) => e.subject).filter(Boolean))).sort(),
    [events],
  );

  const filtered = useMemo(
    () =>
      events
        .filter(
          (e) => selectedType === "all" || e.type.toLowerCase() === selectedType.toLowerCase(),
        )
        .filter((e) => selectedSubject === "all" || e.subject === selectedSubject),
    [events, selectedType, selectedSubject],
  );

  /** Grouped and ordered by deadline. The endpoint concatenates assignments, then quizzes,
   *  then exams, so its raw order interleaved next week's exam above tomorrow's homework. */
  const groups = useMemo(() => {
    const now = new Date();
    const byBucket = new Map<BucketKey, HomeworkEvent[]>();
    for (const ev of filtered) {
      const key = bucketFor(ev, now);
      const list = byBucket.get(key);
      if (list) list.push(ev);
      else byBucket.set(key, [ev]);
    }
    for (const list of byBucket.values()) {
      list.sort((a, b) => new Date(a.end).getTime() - new Date(b.end).getTime());
    }
    // Overdue reads most-recent-first: the thing you missed yesterday is more actionable
    // than the one you missed last month.
    byBucket.get("overdue")?.reverse();

    return BUCKET_ORDER.filter((k) => byBucket.has(k)).map((k) => ({
      key: k,
      items: byBucket.get(k)!,
    }));
  }, [filtered]);

  const handleSync = async () => {
    setSyncError(null);
    try {
      await syncMutation.mutateAsync();
    } catch (err) {
      setSyncError(
        err instanceof ApiError ? err.message : "Could not sync the schedule. Please try again.",
      );
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-foreground">
            <CalendarIcon className="h-7 w-7 text-primary" />
            Homework & Assessment Calendar
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {isStaff
              ? "Every assignment deadline, quiz window, and examination date across your school, soonest first."
              : "Your deadlines in order — overdue first, then what's due today and this week."}
          </p>
        </div>

        <Button
          variant="outline"
          onClick={handleSync}
          disabled={syncMutation.isPending}
          className="flex shrink-0 items-center gap-1.5 text-xs font-medium"
        >
          <RotateCw className={`h-3.5 w-3.5 ${syncMutation.isPending ? "animate-spin" : ""}`} />
          {syncMutation.isPending ? "Syncing..." : "Sync Schedule"}
        </Button>
      </div>

      {syncError && (
        <div
          className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-500"
          role="alert"
        >
          {syncError}
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2 overflow-x-auto pb-1">
          {TYPE_FILTERS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setSelectedType(t)}
              className={`whitespace-nowrap rounded-lg border px-3 py-1.5 text-xs font-semibold capitalize transition-all ${
                selectedType === t
                  ? "border-primary bg-primary text-primary-foreground"
                  : "bg-muted/30 text-muted-foreground hover:text-foreground"
              }`}
            >
              {t === "all" ? "All Deadlines" : `${t}s`}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-3">
          {subjects.length > 1 && (
            <select
              value={selectedSubject}
              onChange={(e) => setSelectedSubject(e.target.value)}
              className="rounded-lg border border-border bg-background px-3 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-primary"
            >
              <option value="all">All subjects</option>
              {subjects.map((sub) => (
                <option key={sub} value={sub}>
                  {sub}
                </option>
              ))}
            </select>
          )}
          {events.length > 0 && (
            <span className="whitespace-nowrap text-xs text-muted-foreground">
              {filtered.length} of {events.length}
            </span>
          )}
        </div>
      </div>

      {/* Timeline */}
      {isError ? (
        <div className="rounded-xl border bg-card py-16 text-center" role="alert">
          <p className="text-sm font-medium text-[hsl(var(--urgent))]">
            Could not load the academic calendar.
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            Reload the page, or try again in a moment.
          </p>
        </div>
      ) : isLoading || viewed.isLoading ? (
        <div className="py-16 text-center text-muted-foreground">Loading academic calendar...</div>
      ) : groups.length === 0 ? (
        <div className="rounded-xl border bg-card py-16 text-center">
          <CalendarIcon className="mx-auto mb-3 h-10 w-10 text-muted-foreground/50" />
          <h3 className="font-semibold text-foreground">
            {events.length > 0 ? "Nothing matches these filters" : "No deadlines scheduled"}
          </h3>
          <p className="mt-1 text-sm text-muted-foreground">
            {events.length > 0
              ? "Clear the type or subject filter to see the rest."
              : isStaff
              ? "Assignment deadlines, quiz windows, and exam dates appear here as staff create them."
              : "You are all caught up on assignments, quizzes, and exams!"}
          </p>
        </div>
      ) : (
        <div className="space-y-8">
          {groups.map((group) => {
            const tone = BUCKET_TONE[group.key];
            return (
              <section key={group.key}>
                <div className="mb-3 flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${tone.dot}`} aria-hidden="true" />
                  <h2 className={`text-xs font-bold uppercase tracking-wider ${tone.label}`}>
                    {BUCKET_LABEL[group.key]}
                  </h2>
                  <span className="text-xs text-muted-foreground">({group.items.length})</span>
                </div>

                {/* The rail. A left border on the list plus a dot per row - cheaper and more
                    legible at 390px than an absolutely-positioned spine, and it wraps
                    correctly when a title runs long. */}
                <ol className="ml-1 space-y-2 border-l border-border pl-4">
                  {group.items.map((ev) => {
                    const target = deadlineRoute(role, ev.id);
                    const due = new Date(ev.end);
                    return (
                      <li key={ev.id} className="relative">
                        <span
                          className={`absolute -left-[21px] top-4 h-2 w-2 rounded-full ring-2 ring-background ${tone.dot}`}
                          aria-hidden="true"
                        />
                        {/* CARDS NOW GO SOMEWHERE. They used to open a modal repeating the
                            same facts already on the card, with no route to the actual
                            assignment or quiz - a reminder you could not act on. */}
                        <div
                          {...(target
                            ? {
                                role: "link",
                                tabIndex: 0,
                                onClick: () => navigate(target),
                                onKeyDown: (e: React.KeyboardEvent) => {
                                  if (e.key === "Enter" || e.key === " ") {
                                    e.preventDefault();
                                    navigate(target);
                                  }
                                },
                              }
                            : {})}
                          className={`flex flex-col gap-2 rounded-xl border bg-card p-3.5 shadow-xs transition-all sm:flex-row sm:items-center sm:justify-between ${
                            target ? "cursor-pointer hover:border-primary/40 hover:shadow-md" : ""
                          } ${group.key === "overdue" ? "border-red-200/80 bg-red-500/5" : ""}`}
                        >
                          <div className="min-w-0">
                            <div className="flex items-center gap-1.5">
                              {typeIcon(ev.type)}
                              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                                {ev.type}
                              </span>
                              <Badge
                                variant="outline"
                                className={`text-[10px] font-bold ${
                                  group.key === "overdue"
                                    ? "border-red-200 bg-red-50 text-red-600"
                                    : ev.status === "completed"
                                    ? "text-muted-foreground"
                                    : "border-emerald-200 bg-emerald-50 text-emerald-700"
                                }`}
                              >
                                {ev.status}
                              </Badge>
                            </div>
                            <h3 className="mt-1 truncate text-sm font-bold text-foreground">
                              {ev.title}
                            </h3>
                            <p className="text-xs font-medium text-primary">{ev.subject}</p>
                          </div>

                          <div className="flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
                            <span className="flex items-center gap-1">
                              <Clock className="h-3.5 w-3.5" />
                              {due.toLocaleDateString()}{" "}
                              {due.toLocaleTimeString([], {
                                hour: "2-digit",
                                minute: "2-digit",
                              })}
                            </span>
                            {ev.max_marks != null && (
                              <span className="whitespace-nowrap">{ev.max_marks} marks</span>
                            )}
                            {target && (
                              <span className="flex items-center gap-0.5 font-medium text-primary">
                                Open
                                <ArrowRight className="h-3 w-3" />
                              </span>
                            )}
                          </div>
                        </div>
                      </li>
                    );
                  })}
                </ol>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
