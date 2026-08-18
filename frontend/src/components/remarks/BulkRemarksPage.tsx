import { useState } from "react";
import {
  MessageSquare,
  Save,
  Clock,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  useClassGradebook,
} from "@/api/hooks/useGradebook";
import {
  useStudentRemarks,
  useCreateBulkRemarks,
} from "@/api/hooks/useRemarks";
import { useAuthStore } from "@/store/authStore";

export default function BulkRemarksPage() {
  const { user, role } = useAuthStore();
  const isTeacherOrAdmin = role === "teacher" || role === "admin" || role === "principal";

  const targetStudentId = !isTeacherOrAdmin && user?.id ? Number(user.id) || 2 : 2;
  const [selectedSentimentFilter, setSelectedSentimentFilter] = useState<string>("all");

  const { data: studentRemarks = [], isLoading: isRemarksLoading } = useStudentRemarks(
    targetStudentId,
    selectedSentimentFilter
  );

  const { data: classData } = useClassGradebook(isTeacherOrAdmin ? 1 : undefined);
  const bulkRemarksMutation = useCreateBulkRemarks();

  // Bulk remarks entry form state: mapping studentId -> { content, sentiment }
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

  const handleBulkSubmit = async () => {
    const payload = Object.entries(bulkEntries)
      .filter(([_, val]) => val.content.trim().length > 0)
      .map(([sid, val]) => ({
        student_id: Number(sid),
        content: val.content,
        sentiment_tag: val.sentiment_tag,
      }));

    if (payload.length === 0) return;

    await bulkRemarksMutation.mutateAsync({
      class_id: 1,
      remarks: payload,
    });

    setBulkEntries({});
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <MessageSquare className="h-7 w-7 text-primary" />
            Teacher Remarks & Behavioral Observations
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            {isTeacherOrAdmin
              ? "Provide qualitative feedback and sentiment-tagged remarks for students."
              : "Review chronological feedback and teacher observations from your classes."}
          </p>
        </div>

        {isTeacherOrAdmin && (
          <Button
            onClick={handleBulkSubmit}
            disabled={bulkRemarksMutation.isPending || Object.keys(bulkEntries).length === 0}
            className="flex items-center gap-1.5 shadow-sm text-xs font-medium"
          >
            <Save className="h-4 w-4" />
            {bulkRemarksMutation.isPending ? "Saving..." : "Save All Remarks"}
          </Button>
        )}
      </div>

      {/* Teacher View: Bulk Entry Grid */}
      {isTeacherOrAdmin ? (
        <Card className="border shadow-xs overflow-hidden">
          <CardContent className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs border-collapse">
                <thead>
                  <tr className="border-b bg-muted/40 font-semibold text-muted-foreground uppercase tracking-wider">
                    <th className="p-4 w-1/4">Student</th>
                    <th className="p-4 w-1/2">Teacher Remark</th>
                    <th className="p-4 w-1/4">Sentiment Tag</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {!classData?.students || classData.students.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="p-8 text-center text-muted-foreground">
                        No students found in class section.
                      </td>
                    </tr>
                  ) : (
                    classData.students.map((st) => {
                      const entry = bulkEntries[String(st.student_id)] || {
                        content: "",
                        sentiment_tag: "academic",
                      };
                      return (
                        <tr key={st.student_id} className="hover:bg-muted/20 transition-colors">
                          <td className="p-4 font-semibold text-foreground">
                            {st.student_name}
                            <span className="text-[11px] text-muted-foreground block">
                              ID: #{st.student_id}
                            </span>
                          </td>
                          <td className="p-4">
                            <Input
                              placeholder="Enter constructive remark or praise..."
                              value={entry.content}
                              onChange={(e) =>
                                handleRemarkTextChange(st.student_id, e.target.value)
                              }
                              className="text-xs"
                            />
                          </td>
                          <td className="p-4">
                            <div className="flex gap-1.5">
                              {[
                                { key: "academic", label: "Academic", color: "bg-blue-50 text-blue-700 border-blue-200" },
                                { key: "behavioral", label: "Behavioral", color: "bg-amber-50 text-amber-700 border-amber-200" },
                                { key: "appreciation", label: "Appreciation", color: "bg-emerald-50 text-emerald-700 border-emerald-200" },
                              ].map((pill) => {
                                const isSelected = entry.sentiment_tag === pill.key;
                                return (
                                  <button
                                    key={pill.key}
                                    type="button"
                                    onClick={() =>
                                      handleSentimentChange(st.student_id, pill.key)
                                    }
                                    className={`px-2.5 py-1 rounded-md text-[11px] font-semibold border transition-all ${
                                      isSelected
                                        ? `${pill.color} font-bold shadow-xs`
                                        : "bg-background text-muted-foreground border-muted hover:bg-muted/40"
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
      ) : (
        /* Student & Parent Timeline View */
        <div className="space-y-4">
          {/* Sentiment Filter Tabs */}
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            {["all", "academic", "behavioral", "appreciation"].map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setSelectedSentimentFilter(t)}
                className={`px-3 py-1.5 rounded-lg border text-xs font-semibold capitalize whitespace-nowrap transition-all ${
                  selectedSentimentFilter === t
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-muted/30 text-muted-foreground hover:text-foreground"
                }`}
              >
                {t === "all" ? "All Remarks" : t}
              </button>
            ))}
          </div>

          <div className="space-y-3">
            {isRemarksLoading ? (
              <div className="py-16 text-center text-muted-foreground">Loading remarks...</div>
            ) : studentRemarks.length === 0 ? (
              <div className="py-16 text-center border rounded-xl bg-card">
                <MessageSquare className="h-10 w-10 mx-auto text-muted-foreground/50 mb-3" />
                <h3 className="font-semibold text-foreground">No remarks recorded</h3>
                <p className="text-sm text-muted-foreground mt-1">
                  Teacher feedback will appear here as terms progress.
                </p>
              </div>
            ) : (
              studentRemarks.map((r) => (
                <Card key={r.id} className="border shadow-xs hover:shadow-sm transition-shadow">
                  <CardContent className="p-4 space-y-2">
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
                            ? "text-emerald-700 bg-emerald-50 border-emerald-200"
                            : r.sentiment_tag === "behavioral"
                            ? "text-amber-700 bg-amber-50 border-amber-200"
                            : "text-blue-700 bg-blue-50 border-blue-200"
                        }`}
                      >
                        {r.sentiment_tag}
                      </Badge>
                    </div>

                    <p className="text-sm text-foreground italic">"{r.content}"</p>

                    <div className="flex items-center gap-1 text-[11px] text-muted-foreground pt-1 border-t">
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
