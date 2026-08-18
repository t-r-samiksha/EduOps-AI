import { AlertTriangle, CalendarCheck, MessageSquareQuote, Users, Wallet } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useChildSummary } from "@/api/hooks/useChildSummary";
import { useSelectedChild } from "@/hooks/useSelectedChild";
import type { ChildSummaryRemark } from "@/api/types";
import { cn } from "@/lib/utils";

/**
 * The parent portal - the one screen a parent actually opens, on a phone.
 *
 * BUILT AT 390px FIRST, desktop is the widening. Single column throughout; the only
 * multi-column rule is `sm:grid-cols-3` on the attendance breakdown, which collapses
 * to a stacked row below that. No fixed widths anywhere, every long string wraps, and
 * the fee row is the one place amounts could collide so it stacks rather than
 * flex-rows on narrow screens.
 */

/** Sentiment as VISUAL WEIGHT, not a label chip.
 *
 * The API gives a `compound` score in -1..+1 (real data spans -0.85 to +0.82). A
 * "negative" tag reads identically whether the remark was mildly flat or genuinely
 * worrying; a bar whose length and colour track the magnitude makes Diya's feed feel
 * different from Aarav's at a glance rather than after reading six rows.
 */
function SentimentBar({ compound }: { compound: number }) {
  const magnitude = Math.min(Math.abs(compound), 1);
  const positive = compound > 0.05;
  const negative = compound < -0.05;
  const tone = positive ? "bg-positive" : negative ? "bg-urgent" : "bg-ink-faint";
  // Floor the width so a near-neutral remark still shows a visible sliver rather than
  // looking like a rendering bug.
  const width = `${Math.max(magnitude * 100, 8)}%`;
  const label = positive ? "positive" : negative ? "negative" : "neutral";

  return (
    <div
      className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-elevated"
      role="img"
      aria-label={`Sentiment ${label}, strength ${Math.round(magnitude * 100)} percent`}
    >
      <div className={cn("h-full rounded-full transition-all", tone)} style={{ width }} />
    </div>
  );
}

function RemarkRow({ remark }: { remark: ChildSummaryRemark }) {
  const { compound } = remark.sentiment;
  const accentBorder =
    compound > 0.05 ? "border-l-positive" : compound < -0.05 ? "border-l-urgent" : "border-l-border";

  return (
    <li className={cn("rounded-r-lg border-l-2 bg-elevated/40 py-2 pl-3 pr-3", accentBorder)}>
      <p className="text-sm leading-relaxed text-ink">{remark.remark_text}</p>
      <SentimentBar compound={compound} />
      <p className="mt-1.5 text-xs text-ink-faint">
        {remark.teacher_name ?? "Teacher"} · {new Date(remark.created_at).toLocaleDateString()}
      </p>
    </li>
  );
}

function Skeleton() {
  return (
    <div className="flex flex-col gap-3">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-28 animate-pulse rounded-2xl bg-elevated/60" />
      ))}
    </div>
  );
}

export default function ChildSummary() {
  const { children, selectedChildId, setSelectedChildId, selectedChild, showSelector, isLoading } =
    useSelectedChild();
  const summary = useChildSummary(selectedChildId);

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <div className="h-14 animate-pulse rounded-2xl bg-elevated/60" />
        <Skeleton />
      </div>
    );
  }

  if (children.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
          <Users className="h-7 w-7 text-ink-muted" aria-hidden="true" />
          <p className="font-display text-base font-semibold text-ink">No children linked yet</p>
          <p className="max-w-xs text-sm text-ink-muted">
            Your account isn't linked to a student. Ask the school office to link your child so their attendance,
            remarks and fees appear here.
          </p>
        </CardContent>
      </Card>
    );
  }

  const data = summary.data;

  return (
    <div className="flex flex-col gap-3">
      {/* 1. CHILD SELECTOR - the thing you touch on stage, so it gets its own card at
             the top rather than being tucked into a header corner. */}
      <Card>
        <CardContent className="flex flex-col gap-2 py-3">
          <label htmlFor="child-select" className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
            Viewing
          </label>
          {showSelector ? (
            <Select value={String(selectedChildId ?? "")} onValueChange={(v) => setSelectedChildId(Number(v))}>
              <SelectTrigger id="child-select" className="w-full" aria-label="Select which child to view">
                <SelectValue placeholder="Select child" />
              </SelectTrigger>
              <SelectContent>
                {children.map((child) => (
                  <SelectItem key={child.id} value={String(child.id)}>
                    {child.name}
                    {child.class_name ? ` · ${child.class_name}` : ""}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          ) : (
            <p className="font-display text-lg font-bold text-ink">
              {selectedChild?.name}
              {selectedChild?.class_name && (
                <span className="ml-2 text-sm font-normal text-ink-muted">{selectedChild.class_name}</span>
              )}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Everything below changes when the child changes, so the whole region is one
          polite live region - a screen reader user hears that the page updated. */}
      <div className="flex flex-col gap-3" aria-live="polite" aria-busy={summary.isFetching}>
        {summary.isLoading && <Skeleton />}

        {summary.isError && (
          <Card>
            <CardContent className="py-6 text-center text-sm text-urgent">
              Couldn't load {selectedChild?.name ?? "this child"}'s details. Pull down to retry.
            </CardContent>
          </Card>
        )}

        {data && (
          <>
            {/* 2. AT-RISK BANNER - only when flagged. The reasons come straight from the
                   nightly scorer and are already human-readable, so they are rendered
                   verbatim: "why" is far more convincing than a severity label. */}
            {data.risk && (
              <div className="rounded-2xl border border-urgent/40 bg-urgent/10 p-4">
                <div className="flex items-start gap-2.5">
                  <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-urgent" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="font-display text-sm font-bold text-ink">
                      Flagged as {data.risk.level} risk
                    </p>
                    <ul className="mt-1.5 flex flex-col gap-1">
                      {data.risk.reasons.map((reason, index) => (
                        <li key={index} className="text-sm leading-relaxed text-ink-muted">
                          • {reason}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-2 text-xs text-ink-faint">
                      The school has been notified. Talk to {data.student.class_name ?? "the class"}'s teacher if
                      you'd like to discuss it.
                    </p>
                  </div>
                </div>
              </div>
            )}

            {/* 3. ATTENDANCE - percentage as the hero, breakdown beneath. */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <CalendarCheck className="h-4 w-4 text-accent" aria-hidden="true" />
                  Attendance
                </CardTitle>
              </CardHeader>
              <CardContent>
                {data.attendance.present_count + data.attendance.absent_count + data.attendance.late_count === 0 ? (
                  <p className="py-2 text-sm text-ink-muted">
                    No attendance recorded in the last {data.attendance.days} days yet.
                  </p>
                ) : (
                  <>
                    <div className="flex items-baseline gap-2">
                      <span
                        className={cn(
                          "font-display text-4xl font-bold tabular-nums",
                          data.attendance.present_pct < 75
                            ? "text-urgent"
                            : data.attendance.present_pct < 90
                              ? "text-warning"
                              : "text-positive",
                        )}
                      >
                        {data.attendance.present_pct.toFixed(0)}%
                      </span>
                      <span className="text-sm text-ink-muted">present</span>
                    </div>
                    <p className="mt-0.5 text-xs text-ink-faint">
                      {data.attendance.window_label ?? `last ${data.attendance.days} days`}
                    </p>

                    <div className="mt-3 grid grid-cols-3 gap-2">
                      {[
                        { label: "Present", value: data.attendance.present_count, tone: "text-positive" },
                        { label: "Absent", value: data.attendance.absent_count, tone: "text-urgent" },
                        { label: "Late", value: data.attendance.late_count, tone: "text-warning" },
                      ].map((cell) => (
                        <div key={cell.label} className="rounded-xl bg-elevated/50 px-2 py-2 text-center">
                          <p className={cn("font-display text-lg font-bold tabular-nums", cell.tone)}>{cell.value}</p>
                          <p className="text-xs text-ink-muted">{cell.label}</p>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </CardContent>
            </Card>

            {/* 4. TEACHER REMARKS */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <MessageSquareQuote className="h-4 w-4 text-accent" aria-hidden="true" />
                  Teacher remarks
                </CardTitle>
              </CardHeader>
              <CardContent>
                {data.remarks.length === 0 ? (
                  <p className="py-2 text-sm text-ink-muted">
                    No remarks yet this term. Teachers add these after class activities and assessments.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {data.remarks.map((remark) => (
                      <RemarkRow key={remark.id} remark={remark} />
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>

            {/* 5. FEES - read-only. Stacks on narrow screens so the amount never
                   collides with the fee name. */}
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Wallet className="h-4 w-4 text-accent" aria-hidden="true" />
                  Fees
                </CardTitle>
              </CardHeader>
              <CardContent>
                {data.fees.length === 0 ? (
                  <p className="py-2 text-sm text-ink-muted">
                    Nothing due right now. Fee notices will appear here when the school raises them.
                  </p>
                ) : (
                  <ul className="flex flex-col gap-2">
                    {data.fees.map((fee) => {
                      const paid = fee.status === "paid";
                      return (
                        <li
                          key={fee.fee_record_id}
                          className="flex flex-col gap-1.5 rounded-xl bg-elevated/40 px-3 py-2.5 sm:flex-row sm:items-center sm:justify-between"
                        >
                          <div className="min-w-0">
                            <p className="text-sm font-medium text-ink">{fee.fee_type}</p>
                            <p className="text-xs text-ink-faint">
                              due {new Date(fee.due_date).toLocaleDateString()}
                            </p>
                          </div>
                          <div className="flex items-center gap-2">
                            <span className="font-mono text-sm tabular-nums text-ink">
                              ₹{(paid ? fee.amount_paid : fee.amount_due - fee.amount_paid).toLocaleString()}
                            </span>
                            <Badge variant={paid ? "positive" : "urgent"}>{paid ? "Paid" : fee.status}</Badge>
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </CardContent>
            </Card>
          </>
        )}
      </div>
    </div>
  );
}
