import { useState } from "react";
import {
  Compass,
  Plus,
  BookOpen,
  Sparkles,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  useSyllabusSummary,
  useLogCheckpoint,
} from "@/api/hooks/useSyllabus";

export default function TeacherSyllabusPacePage() {
  const { data: summaryData, isLoading } = useSyllabusSummary();
  const logCheckpointMutation = useLogCheckpoint();

  const [activePlanId, setActivePlanId] = useState<number | null>(null);
  const [topicLabel, setTopicLabel] = useState("");
  const [sequenceNumber, setSequenceNumber] = useState("1");

  const handleLogTopic = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activePlanId || !topicLabel.trim()) return;

    await logCheckpointMutation.mutateAsync({
      plan_id: activePlanId,
      topic_label: topicLabel.trim(),
      sequence_number: Number(sequenceNumber) || 1,
    });

    setActivePlanId(null);
    setTopicLabel("");
  };

  const items = summaryData?.items || [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <Compass className="h-7 w-7 text-primary" />
            Teacher Syllabus Pace Tracker
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Monitor curriculum pacing across assigned subjects and stay aligned with expected timelines.
          </p>
        </div>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
        {isLoading ? (
          <div className="col-span-full py-16 text-center text-muted-foreground">
            Loading syllabus pace summaries...
          </div>
        ) : items.length === 0 ? (
          <div className="col-span-full py-16 text-center border rounded-xl bg-card">
            <BookOpen className="h-10 w-10 mx-auto text-muted-foreground/50 mb-3" />
            <h3 className="font-semibold text-foreground">No syllabus plans tracked</h3>
            <p className="text-sm text-muted-foreground mt-1">
              Active curriculum plans will display here with pace status and progress indicators.
            </p>
          </div>
        ) : (
          items.map((item: any) => {
            const expectedPct = Math.round((item.expected_fraction || 0) * 100);
            const actualPct = Math.round((item.actual_fraction || 0) * 100);
            const isBehind = actualPct < expectedPct;

            return (
              <Card key={item.plan_id} className="border shadow-xs hover:shadow-md transition-shadow">
                <CardContent className="p-5 flex flex-col justify-between h-full space-y-4">
                  <div>
                    <div className="flex items-center justify-between">
                      <Badge variant="outline" className="text-xs">
                        {item.class_name || `Class #${item.class_id}`}
                      </Badge>
                      <Badge
                        variant="outline"
                        className={`text-xs font-bold ${
                          isBehind
                            ? "text-red-600 bg-red-50 border-red-200"
                            : "text-emerald-700 bg-emerald-50 border-emerald-200"
                        }`}
                      >
                        {isBehind ? "⚠️ Behind Plan" : "✅ On Track"}
                      </Badge>
                    </div>

                    <h3 className="font-bold text-base text-foreground mt-2">
                      {item.subject_name || `Subject #${item.subject_id}`}
                    </h3>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      Academic Year: {item.academic_year} · {item.total_units} Units Total
                    </p>
                  </div>

                  {/* Progress Bars */}
                  <div className="space-y-3 pt-2 border-t text-xs">
                    <div>
                      <div className="flex justify-between mb-1">
                        <span className="text-muted-foreground">Actual Progress</span>
                        <span className="font-bold text-foreground">{actualPct}%</span>
                      </div>
                      <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
                        <div
                          className={`h-2 rounded-full transition-all ${
                            isBehind ? "bg-amber-500" : "bg-emerald-500"
                          }`}
                          style={{ width: `${actualPct}%` }}
                        />
                      </div>
                    </div>

                    <div>
                      <div className="flex justify-between mb-1">
                        <span className="text-muted-foreground">Expected Target</span>
                        <span className="font-bold text-primary">{expectedPct}%</span>
                      </div>
                      <div className="w-full bg-muted rounded-full h-2 overflow-hidden">
                        <div
                          className="bg-primary/40 h-2 rounded-full transition-all"
                          style={{ width: `${expectedPct}%` }}
                        />
                      </div>
                    </div>
                  </div>

                  <div className="pt-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setActivePlanId(item.plan_id)}
                      className="w-full text-xs flex items-center justify-center gap-1.5"
                    >
                      <Plus className="h-3.5 w-3.5" />
                      Log Topic / Checkpoint
                    </Button>
                  </div>
                </CardContent>
              </Card>
            );
          })
        )}
      </div>

      {/* Log Topic Modal */}
      <Dialog open={!!activePlanId} onOpenChange={() => setActivePlanId(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primary" />
              Log Covered Topic / Unit
            </DialogTitle>
          </DialogHeader>

          <form onSubmit={handleLogTopic} className="space-y-3 mt-2 text-xs">
            <div>
              <label className="font-semibold text-foreground">Topic / Unit Label</label>
              <Input
                required
                placeholder="e.g. Chapter 5: Differential Calculus"
                value={topicLabel}
                onChange={(e) => setTopicLabel(e.target.value)}
                className="mt-1 text-xs"
              />
            </div>
            <div>
              <label className="font-semibold text-foreground">Sequence Number</label>
              <Input
                type="number"
                min={1}
                value={sequenceNumber}
                onChange={(e) => setSequenceNumber(e.target.value)}
                className="mt-1 text-xs"
              />
            </div>

            <div className="flex justify-end gap-2 pt-3 border-t">
              <Button type="button" variant="ghost" onClick={() => setActivePlanId(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={logCheckpointMutation.isPending}>
                {logCheckpointMutation.isPending ? "Logging..." : "Record Checkpoint"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
