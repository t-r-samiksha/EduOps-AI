import { useEffect, useState } from "react";
import {
  AlertCircle,
  BadgeCheck,
  CheckCircle2,
  Clock,
  FileImage,
  Loader2,
  Receipt,
  Wallet,
  XCircle,
} from "lucide-react";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger } from "@/components/ui/dialog";
import Field from "@/components/ui/field";
import StatTile from "@/components/shared/StatTile";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import {
  useConfirmPaymentRequest,
  useFeePaymentRequests,
  useRejectPaymentRequest,
  paymentProofPath,
} from "@/api/hooks/useFeePaymentRequests";
import { ApiError, apiGetBlob } from "@/api/client";
import type { FeePaymentRequestItem, PaymentRequestStatus } from "@/api/types";
import { cn } from "@/lib/utils";

const TABS: { value: PaymentRequestStatus | "all"; label: string }[] = [
  { value: "pending", label: "Pending" },
  { value: "confirmed", label: "Confirmed" },
  { value: "rejected", label: "Rejected" },
  { value: "all", label: "All" },
];

const STATUS_BADGE: Record<PaymentRequestStatus, "warning" | "positive" | "urgent"> = {
  pending: "warning",
  confirmed: "positive",
  rejected: "urgent",
};

function money(value: number): string {
  return `₹${value.toLocaleString("en-IN")}`;
}

/** The proof lives in a private bucket, so it can't be an <img src> pointing at the
 * API - the request needs the bearer token. Fetched as a blob on open and revoked on
 * close, rather than eagerly for every row in the queue. */
function ProofDialog({ request }: { request: FeePaymentRequestItem }) {
  const [open, setOpen] = useState(false);
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    let objectUrl: string | null = null;
    let cancelled = false;
    setError(null);
    apiGetBlob(paymentProofPath(request.id))
      .then((blob) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        setUrl(objectUrl);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof ApiError ? err.message : "Could not load the proof.");
      });
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
      setUrl(null);
    };
  }, [open, request.id]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="ghost" size="sm" className="h-7 px-2">
          <FileImage className="h-3.5 w-3.5" /> View
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Payment proof</DialogTitle>
          <DialogDescription>
            {request.parent_name} · {request.student_name} · {money(request.amount)} ·{" "}
            {request.payment_method} ref {request.payment_reference}
          </DialogDescription>
        </DialogHeader>
        {error && <p className="text-sm text-urgent">{error}</p>}
        {!error && !url && <div className="h-64 animate-pulse rounded-xl bg-elevated/60" />}
        {url && (
          // A PDF proof renders in an <object>; an image in an <img>. Both are
          // constrained so a large receipt doesn't blow the dialog out.
          <object data={url} className="max-h-[70vh] w-full rounded-xl border border-border" aria-label="Payment proof">
            <img src={url} alt="Payment proof" className="max-h-[70vh] w-full rounded-xl object-contain" />
          </object>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ConfirmDialog({ request }: { request: FeePaymentRequestItem }) {
  const [open, setOpen] = useState(false);
  const confirm = useConfirmPaymentRequest();
  const willFullyPay = request.amount >= request.outstanding;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) confirm.reset();
      }}
    >
      <DialogTrigger asChild>
        <Button size="sm" className="h-7 px-2.5">
          <CheckCircle2 className="h-3.5 w-3.5" /> Confirm
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Confirm this payment?</DialogTitle>
          <DialogDescription>
            This writes {money(request.amount)} to {request.student_name}'s fee record. Only do it once you've matched
            reference <span className="font-mono">{request.payment_reference}</span> against the bank statement.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1 rounded-xl border border-border bg-elevated/40 px-3 py-2.5 text-xs">
            <span className="text-ink-muted">
              Parent: <span className="font-medium text-ink">{request.parent_name}</span>
            </span>
            <span className="text-ink-muted">
              {request.fee_type} · outstanding {money(request.outstanding)} · claimed {money(request.amount)}
            </span>
            <span className={cn("font-medium", willFullyPay ? "text-positive" : "text-warning")}>
              {willFullyPay
                ? "The fee will read as fully paid."
                : `The fee will read as partial — ${money(request.outstanding - request.amount)} would remain.`}
            </span>
          </div>
          {confirm.isError && (
            <p className="text-sm text-urgent">
              {confirm.error instanceof ApiError ? confirm.error.message : "Could not confirm this payment."}
            </p>
          )}
          <Button
            onClick={() => confirm.mutate(request.id, { onSuccess: () => setOpen(false) })}
            disabled={confirm.isPending}
            className="self-start"
          >
            {confirm.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <BadgeCheck className="h-4 w-4" />}
            {confirm.isPending ? "Confirming…" : "Confirm payment"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function RejectDialog({ request }: { request: FeePaymentRequestItem }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const reject = useRejectPaymentRequest();

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) {
          setReason("");
          reject.reset();
        }
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="h-7 px-2.5">
          <XCircle className="h-3.5 w-3.5" /> Reject
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reject this payment claim</DialogTitle>
          <DialogDescription>
            The fee stays unpaid and keeps attracting reminders. The reason is shown to {request.parent_name} so they
            can correct it and submit again — so make it specific.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Reason" hint="Required. The parent sees this text verbatim.">
            <Textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder="No matching UPI credit on the 14 Aug statement — please check the reference."
            />
          </Field>
          {reject.isError && (
            <p className="text-sm text-urgent">
              {reject.error instanceof ApiError ? reject.error.message : "Could not reject this claim."}
            </p>
          )}
          <Button
            variant="urgent"
            disabled={!reason.trim() || reject.isPending}
            onClick={() =>
              reject.mutate(
                { requestId: request.id, rejectionReason: reason.trim() },
                { onSuccess: () => setOpen(false) }
              )
            }
            className="self-start"
          >
            {reject.isPending ? "Rejecting…" : "Reject claim"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** The review queue, as a tab inside the Fees page.
 *
 * WHY A TAB AND NOT ITS OWN PAGE: a claim IS a fee record awaiting a decision, so
 * the queue and the Fees → Status list are two views of one row. Kept apart, they
 * drifted - Status showed a plain "overdue" for a fee a parent had already reported
 * paying, and paying a fee from the Status tab left the claim pending forever so the
 * dashboard badge could never reach zero. Both are fixed, and living in one place is
 * what stops them recurring. `/admin/fee-payment-requests` still resolves here via a
 * redirect, so the dashboard badge and notification deep links keep working. */
export function PaymentRequestsTab() {
  const [tab, setTab] = useState<PaymentRequestStatus | "all">("pending");
  // `live` on every tab: the whole point of this screen is that a claim submitted on
  // a parent's phone shows up here without a reload.
  const queue = useFeePaymentRequests({ status: tab === "all" ? undefined : tab, live: true });
  const items = queue.data?.items ?? [];

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-ink-muted">
        Parents report payments made by UPI, bank transfer or cash. Match each against the bank statement, then
        confirm — confirming is what marks the fee paid.
      </p>

      <div className="flex flex-wrap gap-3">
        <StatTile
          label="Awaiting review"
          value={queue.data?.pending_count ?? 0}
          caption={queue.data?.pending_count ? "parents waiting on a decision" : "nothing to review"}
          icon={Clock}
          tone={queue.data?.pending_count ? "warning" : "positive"}
          emphasize={(queue.data?.pending_count ?? 0) > 0}
        />
        <StatTile
          label="Claimed in view"
          value={money(items.reduce((sum, i) => sum + i.amount, 0))}
          caption={`${items.length} request(s)`}
          icon={Wallet}
        />
      </div>

      <div className="inline-flex flex-wrap gap-1 rounded-xl border border-border bg-elevated/40 p-1">
        {TABS.map((t) => (
          <button
            key={t.value}
            type="button"
            onClick={() => setTab(t.value)}
            aria-pressed={tab === t.value}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              tab === t.value ? "bg-accent text-accent-foreground shadow-sm" : "text-ink-muted hover:text-accent"
            )}
          >
            {t.label}
            {t.value === "pending" && (queue.data?.pending_count ?? 0) > 0 && (
              <span className="rounded-full bg-urgent px-1.5 text-[0.625rem] font-bold text-urgent-foreground">
                {queue.data?.pending_count}
              </span>
            )}
          </button>
        ))}
      </div>

      {queue.isError && (
        <Card>
          <CardContent className="py-6">
            <p className="text-sm text-urgent">
              {queue.error instanceof ApiError ? queue.error.message : "Could not load the payment queue."}
            </p>
          </CardContent>
        </Card>
      )}
      {queue.isLoading && <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />}

      {queue.data && (
        <Card className={cn("transition-opacity", queue.isFetching && "opacity-60")}>
          <CardHeader>
            <CardTitle>{TABS.find((t) => t.value === tab)?.label} requests</CardTitle>
            <CardDescription>
              Refreshes on its own — a claim submitted on a parent's phone appears here without a reload.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {items.length === 0 ? (
              <div className="flex flex-col items-center gap-1 py-8 text-center">
                <Receipt className="h-6 w-6 text-ink-muted" />
                <p className="font-display text-sm font-medium text-ink">Nothing here</p>
                <p className="text-xs text-ink-muted">
                  {tab === "pending" ? "No payment claims are waiting for review." : `No ${tab} requests.`}
                </p>
              </div>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Parent</TableHead>
                    <TableHead>Child</TableHead>
                    <TableHead>Fee</TableHead>
                    <TableHead>Claimed</TableHead>
                    <TableHead>Method</TableHead>
                    <TableHead>Reference</TableHead>
                    <TableHead>Proof</TableHead>
                    <TableHead>Submitted</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {items.map((request) => (
                    <TableRow key={request.id}>
                      <TableCell className="font-medium">{request.parent_name}</TableCell>
                      <TableCell>
                        <span className="flex flex-col">
                          <span className="text-ink">{request.student_name}</span>
                          {request.class_name && (
                            <span className="text-xs text-ink-faint">{request.class_name}</span>
                          )}
                        </span>
                      </TableCell>
                      <TableCell className="text-ink-muted">{request.fee_type}</TableCell>
                      <TableCell>
                        <span className="flex flex-col">
                          <span className="font-mono tabular-nums text-ink">{money(request.amount)}</span>
                          <span className="text-xs text-ink-faint">of {money(request.outstanding)} due</span>
                        </span>
                      </TableCell>
                      <TableCell className="text-ink-muted">{request.payment_method}</TableCell>
                      <TableCell className="max-w-40 break-words font-mono text-xs">
                        {request.payment_reference}
                      </TableCell>
                      <TableCell>
                        {request.has_proof ? (
                          <ProofDialog request={request} />
                        ) : (
                          <span className="text-xs text-ink-faint">none</span>
                        )}
                      </TableCell>
                      <TableCell className="font-mono text-xs tabular-nums text-ink-muted">
                        {new Date(request.submitted_at).toLocaleDateString()}
                      </TableCell>
                      <TableCell>
                        <span className="flex flex-col items-start gap-1">
                          <Badge variant={STATUS_BADGE[request.status]}>{request.status}</Badge>
                          {request.reviewed_by_name && (
                            <span className="text-[0.6875rem] text-ink-faint">by {request.reviewed_by_name}</span>
                          )}
                          {request.rejection_reason && (
                            <span className="flex max-w-48 items-start gap-1 text-[0.6875rem] text-urgent">
                              <AlertCircle className="mt-0.5 h-3 w-3 shrink-0" />
                              <span className="break-words">{request.rejection_reason}</span>
                            </span>
                          )}
                        </span>
                      </TableCell>
                      <TableCell>
                        {request.status === "pending" && (
                          <span className="flex flex-wrap items-center gap-1.5">
                            <ConfirmDialog request={request} />
                            <RejectDialog request={request} />
                          </span>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
