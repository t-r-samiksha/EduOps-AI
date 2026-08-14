import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, CalendarClock, FileCheck2, Inbox, ScanFace } from "lucide-react";
import PageHeader from "@/components/shared/PageHeader";
import StatTile from "@/components/shared/StatTile";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { buttonVariants } from "@/components/ui/button";
import AlertRow from "@/components/alerts/AlertRow";
import { useAlerts, useAlertsSummary, useResolveAlert } from "@/api/hooks/useAlerts";
import { usePendingApprovals } from "@/api/hooks/useApprovals";
import { useTimetableActive } from "@/api/hooks/useTimetable";
import { useAttendanceSummary } from "@/api/hooks/useAttendance";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

export default function PrincipalDashboard() {
  const summary = useAlertsSummary();
  const alerts = useAlerts();
  const approvals = usePendingApprovals();
  const timetable = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR });
  const attendance = useAttendanceSummary({ fromDate: daysAgo(30), toDate: daysAgo(0) });
  const resolve = useResolveAlert();
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  function handleResolve(id: string) {
    setResolvingId(id);
    resolve.mutate(id, { onSettled: () => setResolvingId(null) });
  }

  const activeClasses = new Set((timetable.data ?? []).map((s) => s.class_id)).size;

  const items = attendance.data?.items ?? [];
  const overallAttendance = items.length > 0 ? items.reduce((sum, i) => sum + i.present_pct, 0) / items.length : null;

  const topAlerts = [...(alerts.data?.items ?? [])]
    .sort((a, b) => (a.severity === b.severity ? 0 : a.severity === "urgent" ? -1 : 1))
    .slice(0, 5);

  return (
    <div className="flex flex-col gap-3">
      <PageHeader title="Principal Dashboard" description="A school-wide overview across every operational area." />

      <div className="flex flex-wrap gap-3">
        <StatTile
          label="Urgent alerts"
          value={summary.isLoading ? "…" : (summary.data?.by_severity.urgent ?? 0)}
          icon={Inbox}
          tone="urgent"
        />
        <StatTile
          label="Normal alerts"
          value={summary.isLoading ? "…" : (summary.data?.by_severity.normal ?? 0)}
          icon={Inbox}
          tone="neutral"
        />
        <StatTile
          label="Pending approvals"
          value={approvals.isLoading ? "…" : (approvals.data?.items.length ?? 0)}
          icon={FileCheck2}
          tone="warning"
        />
        <StatTile
          label="Classes with active timetable"
          value={timetable.isLoading ? "…" : activeClasses}
          icon={CalendarClock}
          tone="neutral"
        />
        <StatTile
          label="Attendance rate (30d)"
          value={attendance.isLoading ? "…" : overallAttendance === null ? "—" : `${overallAttendance.toFixed(1)}%`}
          caption={overallAttendance === null ? "No records in range" : undefined}
          icon={ScanFace}
          tone={overallAttendance !== null && overallAttendance < 85 ? "warning" : "positive"}
        />
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle>Highest-priority alerts</CardTitle>
            <CardDescription>Top {topAlerts.length} by severity — the full feed lives in Command Center.</CardDescription>
          </div>
          <Link to="/admin" className={buttonVariants({ variant: "outline", size: "sm" })}>
            View Command Center <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          {alerts.isLoading && <div className="h-16 animate-pulse rounded-lg bg-elevated/60" />}
          {!alerts.isLoading && topAlerts.length === 0 && <p className="text-sm text-ink-muted">All clear — nothing open.</p>}
          {topAlerts.map((alert) => (
            <AlertRow key={alert.id} alert={alert} onResolve={handleResolve} resolving={resolvingId === alert.id} />
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
