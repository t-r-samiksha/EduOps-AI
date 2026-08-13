import {
  Activity,
  AlertTriangle,
  Bell,
  CalendarX,
  FileQuestion,
  FileWarning,
  IndianRupee,
  ScanFace,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import EntityCard from "@/components/shared/EntityCard";
import type { Alert } from "@/api/types";
import { timeAgo } from "@/lib/format";

const SOURCE_ICON: Record<string, LucideIcon> = {
  risk_flag: AlertTriangle,
  leave_request: CalendarX,
  substitution: Users,
  document_failed: FileWarning,
  document_low_confidence: FileQuestion,
  attendance_reconciliation: ScanFace,
  anomaly_flag: Activity,
  fee_overdue: IndianRupee,
};

const SOURCE_LABEL: Record<string, string> = {
  risk_flag: "Early warning",
  leave_request: "Leave request",
  substitution: "Substitution",
  document_failed: "OCR failure",
  document_low_confidence: "OCR review",
  attendance_reconciliation: "Attendance",
  anomaly_flag: "Anomaly",
  fee_overdue: "Fees",
};

interface AlertRowProps {
  alert: Alert;
  onResolve: (id: string) => void;
  resolving: boolean;
}

export default function AlertRow({ alert, onResolve, resolving }: AlertRowProps) {
  return (
    <EntityCard
      icon={SOURCE_ICON[alert.source] ?? Bell}
      tone={alert.severity === "urgent" ? "urgent" : "neutral"}
      title={alert.title}
      badges={
        <>
          <Badge variant={alert.severity === "urgent" ? "urgent" : "neutral"}>{alert.severity}</Badge>
          <Badge variant="outline">{SOURCE_LABEL[alert.source] ?? alert.source}</Badge>
        </>
      }
      message={alert.message}
      meta={timeAgo(alert.created_at)}
      actions={
        <Button variant="outline" size="sm" onClick={() => onResolve(alert.id)} disabled={resolving}>
          {resolving ? "…" : "Resolve"}
        </Button>
      }
    />
  );
}
