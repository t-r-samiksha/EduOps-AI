import { useState } from "react";
import { AlertOctagon, Inbox, ShieldCheck } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import AlertRow from "@/components/alerts/AlertRow";
import PageHeader from "@/components/shared/PageHeader";
import StatTile from "@/components/shared/StatTile";
import { useAlerts, useAlertsSummary, useAlertsLiveStream, useResolveAlert } from "@/api/hooks/useAlerts";
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
