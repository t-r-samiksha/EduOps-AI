import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPostForm, apiPut } from "@/api/client";
import type {
  ConfirmPaymentRequestResult,
  FeePaymentRequestItem,
  FeePaymentRequestQueue,
  FeePaymentRequestSummary,
  ParentFeesResponse,
  PaymentRequestStatus,
} from "@/api/types";

/** How often the admin queue and its dashboard badge re-check for new claims.
 *
 * The demo gesture this exists for: a parent submits on a phone, and the number on
 * the admin screen changes without anyone reloading. Mount-only fetching would make
 * the loop look dead exactly when it should look alive. 20s is well inside the
 * global 30s staleTime, so this query opts out of that below. */
const QUEUE_POLL_MS = 20_000;

/** Everything a confirm/reject invalidates. The claim and the canonical fee record
 * are separate tables read by separate screens, so a stale one is a visible lie:
 * the queue would still show pending, or the fee list would still show overdue. */
function invalidateLoop(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["fee-payment-requests"] });
  queryClient.invalidateQueries({ queryKey: ["parent-child-fees"] });
  queryClient.invalidateQueries({ queryKey: ["fee-status"] });
  queryClient.invalidateQueries({ queryKey: ["admin-alerts"] });
  queryClient.invalidateQueries({ queryKey: ["notifications"] });
  queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
  queryClient.invalidateQueries({ queryKey: ["child-summary"] });
}

/** The admin review queue. `live` turns on polling + refetch-on-focus, which the
 * dashboard badge and the queue page both want; nothing else does. */
export function useFeePaymentRequests(params: { status?: PaymentRequestStatus; live?: boolean } = {}) {
  return useQuery({
    queryKey: ["fee-payment-requests", params.status],
    queryFn: () =>
      apiGet<FeePaymentRequestQueue>("/admin/fee-payment-requests", { status: params.status }),
    ...(params.live
      ? {
          refetchInterval: QUEUE_POLL_MS,
          // Switching back to the admin window IS the demo gesture - refetch on
          // focus, and treat the data as immediately stale so the switch actually
          // triggers a fetch rather than being swallowed by the global staleTime.
          refetchOnWindowFocus: true,
          staleTime: 0,
        }
      : {}),
  });
}

/** One child's fees with the derived status. Parent-facing. */
export function useParentChildFees(studentId: number | undefined) {
  return useQuery({
    queryKey: ["parent-child-fees", studentId],
    queryFn: () => apiGet<ParentFeesResponse>(`/parent/child/${studentId}/fees`),
    enabled: studentId != null,
  });
}

export function useCreatePaymentRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      studentId,
      feeRecordId,
      paymentMethod,
      paymentReference,
      amount,
      proofFile,
    }: {
      studentId: number;
      feeRecordId: number;
      paymentMethod: string;
      paymentReference: string;
      amount: number;
      proofFile?: File | null;
    }) => {
      const form = new FormData();
      form.append("payment_method", paymentMethod);
      form.append("payment_reference", paymentReference);
      form.append("amount", String(amount));
      if (proofFile) form.append("proof_file", proofFile);
      return apiPostForm<FeePaymentRequestSummary>(
        `/parent/child/${studentId}/fees/${feeRecordId}/payment-request`,
        form
      );
    },
    onSuccess: () => invalidateLoop(queryClient),
  });
}

export function useConfirmPaymentRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (requestId: number) =>
      apiPut<ConfirmPaymentRequestResult>(`/admin/fee-payment-requests/${requestId}/confirm`),
    onSuccess: () => invalidateLoop(queryClient),
  });
}

export function useRejectPaymentRequest() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ requestId, rejectionReason }: { requestId: number; rejectionReason: string }) =>
      apiPut<FeePaymentRequestItem>(`/admin/fee-payment-requests/${requestId}/reject`, {
        rejection_reason: rejectionReason,
      }),
    onSuccess: () => invalidateLoop(queryClient),
  });
}

/** The proof image lives in a private bucket, so the <img> src is an authenticated
 * fetch turned into an object URL rather than a plain URL. */
export function paymentProofPath(requestId: number): string {
  return `/admin/fee-payment-requests/${requestId}/proof`;
}
