import { useState, useMemo } from "react";
import {
  Calendar as CalendarIcon,
  Clock,
  RotateCw,
  FileCheck,
  HelpCircle,
  Award,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  useHomeworkCalendar,
  useTriggerCalendarSync,
  HomeworkEvent,
} from "@/api/hooks/useHomeworkCalendar";
import { useAuthStore } from "@/store/authStore";
import { useMyUserId, useViewedStudent } from "@/hooks/useViewedStudent";
import { ApiError } from "@/api/client";

export default function HomeworkCalendarPage() {
  const { role } = useAuthStore();
  const isStaff = role === "admin" || role === "principal" || role === "teacher";

  // THIS PAGE WAS ALWAYS EMPTY, FOR EVERYONE. It resolved the subject of the calendar as
  // `Number(user.id) || 2` - and user.id is a Supabase UUID string, so Number() is NaN and
  // the `|| 2` turned every single request, in every role and every school, into "show me
  // student #2's deadlines". An admin got either a stranger's calendar or, far more often
  // (student 2 not existing in their school), an empty one.
  //
  // GET /calendar/homework/{id} already returns SCHOOL-WIDE deadlines when the id belongs
  // to a staff member, and the caller's own classes for a teacher - so the endpoint could
  // always have populated this page. It just was never asked about the right person.
  const myUserId = useMyUserId();
  const viewed = useViewedStudent();
  const calendarSubjectId = isStaff ? myUserId : viewed.studentId;

  const { data: events = [], isLoading, isError } = useHomeworkCalendar(calendarSubjectId);
  const syncMutation = useTriggerCalendarSync();

  const [selectedType, setSelectedType] = useState<string>("all");
  const [selectedSubject, setSelectedSubject] = useState<string>("all");
  const [selectedEvent, setSelectedEvent] = useState<HomeworkEvent | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);

  /** Subjects present in the returned deadlines. Staff see the whole school here, which is
   *  a lot of cards, and subject is the axis that actually narrows it - the class is not
   *  carried on a HomeworkEventOut, so filtering by class would need a backend change. */
  const subjects = useMemo(
    () => Array.from(new Set(events.map((e) => e.subject).filter(Boolean))).sort(),
    [events],
  );

  const filteredEvents = useMemo(() => {
    return events
      .filter((e) => selectedType === "all" || e.type.toLowerCase() === selectedType.toLowerCase())
      .filter((e) => selectedSubject === "all" || e.subject === selectedSubject)
      // Soonest deadline first. The endpoint concatenates assignments, then quizzes, then
      // exams, so unsorted output interleaved next week's exam above tomorrow's homework.
      .sort((a, b) => new Date(a.end).getTime() - new Date(b.end).getTime());
  }, [events, selectedType, selectedSubject]);

  const handleSync = async () => {
    setSyncError(null);
    try {
      await syncMutation.mutateAsync();
    } catch (err) {
      setSyncError(
        err instanceof ApiError ? err.message : "Could not sync the schedule. Please try again."
      );
    }
  };

  const getTypeIcon = (type: string) => {
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
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <CalendarIcon className="h-7 w-7 text-primary" />
            Homework & Assessment Calendar
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {isStaff
              ? "Every assignment deadline, quiz window, and examination date across your school."
              : "Stay on top of upcoming assignment deadlines, online quizzes, and examination dates."}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={handleSync}
            disabled={syncMutation.isPending}
            className="flex items-center gap-1.5 text-xs font-medium"
          >
            <RotateCw className={`h-3.5 w-3.5 ${syncMutation.isPending ? "animate-spin" : ""}`} />
            {syncMutation.isPending ? "Syncing..." : "Sync Schedule"}
          </Button>
        </div>
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
          {["all", "assignment", "quiz", "exam"].map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setSelectedType(t)}
              className={`px-3 py-1.5 rounded-lg border text-xs font-semibold capitalize whitespace-nowrap transition-all ${
                selectedType === t
                  ? "bg-primary text-primary-foreground border-primary"
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
              {filteredEvents.length} of {events.length}
            </span>
          )}
        </div>
      </div>

      {/* Events Timeline / Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {isError ? (
          <div className="col-span-full py-16 text-center border rounded-xl bg-card" role="alert">
            <p className="text-sm font-medium text-[hsl(var(--urgent))]">Could not load the academic calendar.</p>
            <p className="mt-1 text-xs text-muted-foreground">
              Reload the page, or try again in a moment.
            </p>
          </div>
        ) : isLoading ? (
          <div className="col-span-full py-16 text-center text-muted-foreground">
            Loading academic calendar...
          </div>
        ) : filteredEvents.length === 0 ? (
          <div className="col-span-full py-16 text-center border rounded-xl bg-card">
            <CalendarIcon className="h-10 w-10 mx-auto text-muted-foreground/50 mb-3" />
            <h3 className="font-semibold text-foreground">
              {events.length > 0 ? "Nothing matches these filters" : "No deadlines scheduled"}
            </h3>
            <p className="text-sm text-muted-foreground mt-1">
              {events.length > 0
                ? "Clear the type or subject filter to see the rest."
                : isStaff
                ? "Assignment deadlines, quiz windows, and exam dates appear here as staff create them."
                : "You are all caught up on assignments, quizzes, and exams!"}
            </p>
          </div>
        ) : (
          filteredEvents.map((ev) => {
            const isOverdue = ev.status === "overdue";
            return (
              <Card
                key={ev.id}
                onClick={() => setSelectedEvent(ev)}
                className={`border shadow-xs hover:shadow-md transition-all cursor-pointer ${
                  isOverdue ? "border-red-200/80 bg-red-500/5" : ""
                }`}
              >
                <CardContent className="p-4 flex flex-col justify-between h-full space-y-3">
                  <div>
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        {getTypeIcon(ev.type)}
                        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          {ev.type}
                        </span>
                      </div>
                      <Badge
                        variant="outline"
                        className={`text-[11px] font-bold ${
                          isOverdue
                            ? "text-red-600 bg-red-50 border-red-200"
                            : "text-emerald-700 bg-emerald-50 border-emerald-200"
                        }`}
                      >
                        {ev.status}
                      </Badge>
                    </div>

                    <h3 className="font-bold text-sm text-foreground mt-2 line-clamp-2">
                      {ev.title}
                    </h3>
                    <p className="text-xs text-primary font-medium mt-0.5">{ev.subject}</p>
                  </div>

                  <div className="border-t pt-2.5 flex items-center justify-between text-xs text-muted-foreground">
                    <div className="flex items-center gap-1">
                      <Clock className="h-3.5 w-3.5" />
                      Due: {new Date(ev.end).toLocaleDateString()}{" "}
                      {new Date(ev.end).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })
        )}
      </div>

      {/* Event Detail Modal */}
      <Dialog open={!!selectedEvent} onOpenChange={() => setSelectedEvent(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {selectedEvent && getTypeIcon(selectedEvent.type)}
              Deadline Details
            </DialogTitle>
          </DialogHeader>

          {selectedEvent && (
            <div className="space-y-4 mt-2 text-xs">
              <div>
                <Badge variant="outline" className="capitalize">
                  {selectedEvent.type}
                </Badge>
                <h3 className="text-base font-bold text-foreground mt-1">
                  {selectedEvent.title}
                </h3>
                <p className="text-primary font-semibold mt-0.5">{selectedEvent.subject}</p>
              </div>

              <div className="p-3 rounded-lg bg-muted/20 border space-y-1.5">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Due Time:</span>
                  <span className="font-semibold text-foreground">
                    {new Date(selectedEvent.end).toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Status:</span>
                  <Badge
                    variant="outline"
                    className={
                      selectedEvent.status === "overdue"
                        ? "text-red-600 bg-red-50"
                        : "text-emerald-700 bg-emerald-50"
                    }
                  >
                    {selectedEvent.status}
                  </Badge>
                </div>
                {selectedEvent.max_marks && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Max Marks:</span>
                    <span className="font-semibold text-foreground">
                      {selectedEvent.max_marks}
                    </span>
                  </div>
                )}
              </div>

              {selectedEvent.details && (
                <div>
                  <span className="font-bold text-muted-foreground uppercase text-[10px]">
                    Description / Notes
                  </span>
                  <p className="text-muted-foreground mt-1 bg-muted/10 p-2.5 rounded-md border">
                    {selectedEvent.details}
                  </p>
                </div>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
