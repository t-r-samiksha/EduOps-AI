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

export default function HomeworkCalendarPage() {
  const { user } = useAuthStore();
  const studentId = user?.id ? Number(user.id) || 2 : 2;

  const { data: events = [], isLoading, isError } = useHomeworkCalendar(studentId);
  const syncMutation = useTriggerCalendarSync();

  const [selectedType, setSelectedType] = useState<string>("all");
  const [selectedEvent, setSelectedEvent] = useState<HomeworkEvent | null>(null);

  const filteredEvents = useMemo(() => {
    if (selectedType === "all") return events;
    return events.filter((e) => e.type.toLowerCase() === selectedType.toLowerCase());
  }, [events, selectedType]);

  const handleSync = async () => {
    await syncMutation.mutateAsync();
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
            Stay on top of upcoming assignment deadlines, online quizzes, and examination dates.
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

      {/* Filter Tabs */}
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
            <h3 className="font-semibold text-foreground">No upcoming deadlines found</h3>
            <p className="text-sm text-muted-foreground mt-1">
              You are all caught up on assignments, quizzes, and exams!
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
