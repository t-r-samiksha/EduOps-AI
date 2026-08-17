import { useState } from "react";
import { Link } from "react-router-dom";
import { AlertOctagon, Inbox, Receipt, ShieldCheck } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import AlertRow from "@/components/alerts/AlertRow";
import PageHeader from "@/components/shared/PageHeader";
import StatTile from "@/components/shared/StatTile";
import { useAlerts, useAlertsSummary, useAlertsLiveStream, useResolveAlert } from "@/api/hooks/useAlerts";
import { useFeePaymentRequests } from "@/api/hooks/useFeePaymentRequests";
import type { Severity } from "@/api/types";

function AlertFeed({ severity }: { severity?: Severity }) {
  const { data, isLoading } = useAlerts(severity);
  const resolve = useResolveAlert();
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  function handleResolve(id: string) {
    setResolvingId(id);
    resolve.mutate(id, { onSettled: () => setResolvingId(null) });
  }

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-16 animate-pulse rounded-2xl border border-border bg-elevated/60" />
        ))}
      </div>
    );
  }

  const items = data?.items ?? [];

  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center gap-1 py-6 text-center">
          <p className="font-display text-sm font-medium text-ink">All clear</p>
          <p className="text-xs text-ink-muted">Nothing needs attention right now.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {items.map((alert) => (
        <AlertRow key={alert.id} alert={alert} onResolve={handleResolve} resolving={resolvingId === alert.id} />
      ))}
    </div>
  );
}

/** Pending fee payment claims, as a live link into the review queue.
 *
 * A parent submits on their phone and this number changes here without a reload -
 * that is the whole reason it polls and refetches on window focus (see
 * useFeePaymentRequests' `live`) rather than fetching once on mount. A badge that
 * only updates on navigation makes the loop look dead exactly when it should look
 * alive. Hidden entirely at zero: an always-present "0" is noise on a dashboard
 * whose job is surfacing what needs attention. */
function PaymentRequestsBadge() {
  const queue = useFeePaymentRequests({ live: true });
  const pending = queue.data?.pending_count ?? 0;
  if (pending === 0) return null;

  return (
    <Link
      to="/admin/fees?tab=requests"
      className="flex flex-1 items-start justify-between gap-3 rounded-2xl border border-transparent bg-warning px-4 py-3.5 text-warning-foreground shadow-floating transition-opacity hover:opacity-90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-paper"
    >
      <span className="flex flex-col gap-0.5">
        <span className="text-xs font-medium uppercase tracking-wide opacity-80">Payment claims</span>
        <span className="font-display text-2xl font-bold">{pending}</span>
        <span className="text-xs opacity-80">
          {pending === 1 ? "parent waiting on confirmation" : "parents waiting on confirmation"} · review now
        </span>
      </span>
      <span className="relative flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-warning-foreground/10">
        <Receipt className="h-4 w-4" />
        <span className="absolute -right-1 -top-1 flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-urgent opacity-75" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-urgent" />
        </span>
      </span>
    </Link>
  );
}

export default function AdminDashboard() {
  const summary = useAlertsSummary();
  useAlertsLiveStream(true);

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Command Center"
        description="Every alert source in one feed — risk flags, leave requests, substitutions, fees, OCR, syllabus drift, teacher overload — updated live."
        actions={
          <span className="flex items-center gap-1.5 rounded-full bg-positive/10 px-3.5 py-1.5 text-xs font-semibold uppercase tracking-wide text-positive">
            <span className="relative flex h-2 w-2">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-positive opacity-60" />
              <span className="relative inline-flex h-2 w-2 rounded-full bg-positive" />
            </span>
            Live
          </span>
        }
      />

      <div className="flex flex-wrap gap-3">
        <PaymentRequestsBadge />
        <StatTile label="Total open" value={summary.data?.total ?? 0} icon={Inbox} tone="neutral" />
        <StatTile label="Urgent" value={summary.data?.by_severity.urgent ?? 0} icon={AlertOctagon} tone="urgent" emphasize />
        <StatTile label="Normal" value={summary.data?.by_severity.normal ?? 0} icon={ShieldCheck} tone="positive" />
      </div>

      <Tabs defaultValue="all">
        <TabsList>
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="urgent">Urgent</TabsTrigger>
          <TabsTrigger value="normal">Normal</TabsTrigger>
        </TabsList>
        <TabsContent value="all">
          <AlertFeed />
        </TabsContent>
        <TabsContent value="urgent">
          <AlertFeed severity="urgent" />
        </TabsContent>
        <TabsContent value="normal">
          <AlertFeed severity="normal" />
        </TabsContent>
      </Tabs>
    </div>
  );
}
