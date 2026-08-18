import { useState } from "react";
import { MessageSquare, Save, Clock, UserSearch } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { useClassRoster } from "@/api/hooks/useClassRoster";
import { useStudentRemarks, useCreateBulkRemarks, useClassRemarks } from "@/api/hooks/useRemarks";
import { useAuthStore } from "@/store/authStore";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useReferenceLookup } from "@/api/hooks/useTimetable";
import { useViewedStudent } from "@/hooks/useViewedStudent";
import { ClassSelect } from "@/components/shared/StudentPicker";
import { ApiError } from "@/api/client";

const SENTIMENT_PILLS = [
  { key: "academic", label: "Academic", color: "bg-blue-50 text-blue-700 border-blue-200" },
  { key: "behavioral", label: "Behavioral", color: "bg-amber-50 text-amber-700 border-amber-200" },
  {
    key: "appreciation",
    label: "Appreciation",
    color: "bg-emerald-50 text-emerald-700 border-emerald-200",
  },
];

/**
 * Teacher remark authoring (staff) and the remark timeline (student/parent).
 *
 * NO LONGER ON THE ADMIN OR PRINCIPAL MENU. Writing per-student behavioural observations is
 * a classroom act - an admin has no class they observe, so an authoring grid was the wrong
 * surface for them. Admin and principal read remarks where they are actionable instead: on
 * the Early-Warning flag that the remark sentiment helped raise (see RiskDashboard's
 * FlagRemarks). The page still accepts those roles if reached directly, since the backend
 * permits it and the RBAC matrix has not changed.
 */
export default function BulkRemarksPage() {
  const { role } = useAuthStore();
  const isTeacherOrAdmin = role === "teacher" || role === "admin" || role === "principal";

  const currentUser = useCurrentUser().data;
  const lookup = useReferenceLookup(currentUser?.school_id);
  const classes = lookup.data?.classes ?? [];

  // THE CLASS WAS HARDCODED TO 1. `useClassGradebook(isTeacherOrAdmin ? 1 : undefined)` and
  // `class_id: 1` on submit - so the grid showed class 1's roster to every teacher in every
  // school (in practice: "No students found in class section", because class 1 is almost
  // never one of yours), and any remark that DID save was filed against the wrong class.
  const [selectedClassId, setSelectedClassId] = useState<number | "">("");
  const roster = useClassRoster(
    isTeacherOrAdmin && selectedClassId ? Number(selectedClassId) : undefined,
  );
  const students = roster.data?.students ?? [];
  // Existing remarks per student, so a teacher can see what is already recorded instead of
  // being shown an empty box and re-entering the same observation every week.
  const existing = useClassRemarks(
    isTeacherOrAdmin && selectedClassId ? Number(selectedClassId) : undefined,
  );

  const [selectedSentimentFilter, setSelectedSentimentFilter] = useState<string>("all");
  const viewed = useViewedStudent();
  const { data: studentRemarks = [], isLoading: isRemarksLoading } = useStudentRemarks(
    isTeacherOrAdmin ? undefined : viewed.studentId,
    selectedSentimentFilter,
  );

  const bulkRemarksMutation = useCreateBulkRemarks();
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savedCount, setSavedCount] = useState<number | null>(null);

  const [bulkEntries, setBulkEntries] = useState<
    Record<string, { content: string; sentiment_tag: string }>
  >({});

  const handleRemarkTextChange = (studentId: number, text: string) => {
    setBulkEntries((prev) => ({
      ...prev,
      [String(studentId)]: {
        content: text,
        sentiment_tag: prev[String(studentId)]?.sentiment_tag || "academic",
      },
    }));
  };

  const handleSentimentChange = (studentId: number, sentiment: string) => {
    setBulkEntries((prev) => ({
      ...prev,
      [String(studentId)]: {
        content: prev[String(studentId)]?.content || "",
        sentiment_tag: sentiment,
      },
    }));
  };

  const pendingCount = Object.values(bulkEntries).filter((v) => v.content.trim().length > 0).length;

  const handleBulkSubmit = async () => {
    if (!selectedClassId) {
      setSaveError("Select a class section first.");
      return;
    }
    const payload = Object.entries(bulkEntries)
      .filter(([, val]) => val.content.trim().length > 0)
      .map(([sid, val]) => ({
        student_id: Number(sid),
        content: val.content.trim(),
        sentiment_tag: val.sentiment_tag,
      }));

    if (payload.length === 0) return;

    setSaveError(null);
    setSavedCount(null);
    try {
      await bulkRemarksMutation.mutateAsync({
        class_id: Number(selectedClassId),
        remarks: payload,
      });
      setBulkEntries({});
      setSavedCount(payload.length);
    } catch (err) {
      // Was unhandled, so a rejected save left the typed remarks on screen with no
      // indication they had not been recorded.
      setSaveError(
        err instanceof ApiError ? err.message : "Could not save these remarks. Please try again.",
      );
    }
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="flex items-center gap-2 text-2xl font-bold tracking-tight text-foreground">
            <MessageSquare className="h-7 w-7 text-primary" />
            Teacher Remarks & Behavioral Observations
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {isTeacherOrAdmin
              ? "Recorded remarks print on the student's report card and feed their early-warning risk score."
              : "Review chronological feedback and teacher observations from your classes."}
          </p>
        </div>

        {isTeacherOrAdmin && (
          <div className="flex flex-wrap items-center gap-2">
            <ClassSelect
              value={selectedClassId}
              onChange={(next) => {
                setSelectedClassId(next);
                // Entries are keyed by student id; carrying them across a class change
                // would post remarks about one section's students under another's class_id.
                setBulkEntries({});
                setSavedCount(null);
                setSaveError(null);
              }}
              classes={classes}
            />
            <Button
              onClick={handleBulkSubmit}
              disabled={bulkRemarksMutation.isPending || pendingCount === 0}
              className="flex items-center gap-1.5 text-xs font-medium shadow-sm"
            >
              <Save className="h-4 w-4" />
              {bulkRemarksMutation.isPending
                ? "Saving..."
                : pendingCount > 0
                ? `Save ${pendingCount} Remark${pendingCount === 1 ? "" : "s"}`
                : "Save All Remarks"}
            </Button>
          </div>
        )}
      </div>

      {saveError && (
        <div
          className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-xs text-red-500"
          role="alert"
        >
          {saveError}
        </div>
      )}
      {savedCount !== null && (
        <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-xs text-emerald-600">
          Saved {savedCount} remark{savedCount === 1 ? "" : "s"}. Sentiment is picked up by the
          next early-warning scoring run.
        </div>
      )}

      {isTeacherOrAdmin ? (
        !selectedClassId ? (
          <div className="rounded-xl border bg-card py-16 text-center">
            <UserSearch className="mx-auto mb-3 h-10 w-10 text-muted-foreground/50" />
            <h3 className="font-semibold text-foreground">Choose a class section</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Pick a section above to record remarks for its students.
            </p>
          </div>
        ) : (
          <Card className="overflow-hidden border shadow-xs">
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full min-w-[640px] border-collapse text-left text-xs">
                  <thead>
                    <tr className="border-b bg-muted/40 font-semibold uppercase tracking-wider text-muted-foreground">
                      <th scope="col" className="w-1/4 p-4">Student</th>
                      <th scope="col" className="w-1/2 p-4">Teacher Remark</th>
                      <th scope="col" className="w-1/4 p-4">Sentiment Tag</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {roster.isLoading ? (
                      <tr>
                        <td colSpan={3} className="p-8 text-center text-muted-foreground">
                          Loading roster…
                        </td>
                      </tr>
                    ) : students.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="p-8 text-center text-muted-foreground">
                          No students enrolled in this section.
                        </td>
                      </tr>
                    ) : (
                      students.map((st) => {
                        const entry = bulkEntries[String(st.id)] || {
                          content: "",
                          sentiment_tag: "academic",
                        };
                        return (
                          <tr key={st.id} className="transition-colors hover:bg-muted/20">
                            <td className="p-4 align-top">
                              <span className="font-semibold text-foreground">{st.name}</span>
                              {(existing.data?.by_student?.[String(st.id)]?.length ?? 0) > 0 && (
                                <ul className="mt-1.5 space-y-1">
                                  {existing.data!.by_student[String(st.id)].map((r) => (
                                    <li key={r.id} className="text-[11px] leading-snug">
                                      <span className="italic text-muted-foreground">
                                        "{r.content}"
                                      </span>
                                      <span className="ml-1 whitespace-nowrap text-muted-foreground/70">
                                        · {r.sentiment_tag} ·{" "}
                                        {new Date(r.created_at).toLocaleDateString()}
                                      </span>
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </td>
                            <td className="p-4 align-top">
                              <Input
                                placeholder="Enter constructive remark or praise..."
                                value={entry.content}
                                onChange={(e) => handleRemarkTextChange(st.id, e.target.value)}
                                className="text-xs"
                              />
                            </td>
                            <td className="p-4 align-top">
                              <div className="flex gap-1.5">
                                {SENTIMENT_PILLS.map((pill) => {
                                  const isSelected = entry.sentiment_tag === pill.key;
                                  return (
                                    <button
                                      key={pill.key}
                                      type="button"
                                      onClick={() => handleSentimentChange(st.id, pill.key)}
                                      className={`rounded-md border px-2.5 py-1 text-[11px] font-semibold transition-all ${
                                        isSelected
                                          ? `${pill.color} font-bold shadow-xs`
                                          : "border-muted bg-background text-muted-foreground hover:bg-muted/40"
                                      }`}
                                    >
                                      {pill.label}
                                    </button>
                                  );
                                })}
                              </div>
                            </td>
                          </tr>
                        );
                      })
                    )}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        )
      ) : (
        /* Student & Parent Timeline View */
        <div className="space-y-4">
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            {["all", "academic", "behavioral", "appreciation"].map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setSelectedSentimentFilter(t)}
                className={`whitespace-nowrap rounded-lg border px-3 py-1.5 text-xs font-semibold capitalize transition-all ${
                  selectedSentimentFilter === t
                    ? "border-primary bg-primary text-primary-foreground"
                    : "bg-muted/30 text-muted-foreground hover:text-foreground"
                }`}
              >
                {t === "all" ? "All Remarks" : t}
              </button>
            ))}
          </div>

          <div className="space-y-3">
            {isRemarksLoading || viewed.isLoading ? (
              <div className="py-16 text-center text-muted-foreground">Loading remarks...</div>
            ) : studentRemarks.length === 0 ? (
              <div className="rounded-xl border bg-card py-16 text-center">
                <MessageSquare className="mx-auto mb-3 h-10 w-10 text-muted-foreground/50" />
                <h3 className="font-semibold text-foreground">No remarks recorded</h3>
                <p className="mt-1 text-sm text-muted-foreground">
                  Teacher feedback will appear here as terms progress.
                </p>
              </div>
            ) : (
              studentRemarks.map((r) => (
                <Card key={r.id} className="border shadow-xs transition-shadow hover:shadow-sm">
                  <CardContent className="space-y-2 p-4">
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-foreground">
                          {r.author_name || "Class Teacher"}
                        </span>
                        {r.subject_name && (
                          <Badge variant="outline" className="text-[11px]">
                            {r.subject_name}
                          </Badge>
                        )}
                      </div>
                      <Badge
                        variant="outline"
                        className={`text-[11px] capitalize ${
                          r.sentiment_tag === "appreciation"
                            ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                            : r.sentiment_tag === "behavioral"
                            ? "border-amber-200 bg-amber-50 text-amber-700"
                            : "border-blue-200 bg-blue-50 text-blue-700"
                        }`}
                      >
                        {r.sentiment_tag}
                      </Badge>
                    </div>

                    <p className="text-sm italic text-foreground">"{r.content}"</p>

                    <div className="flex items-center gap-1 border-t pt-1 text-[11px] text-muted-foreground">
                      <Clock className="h-3 w-3" />
                      {new Date(r.created_at).toLocaleDateString()}
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
