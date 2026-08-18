import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiGet, apiPost, apiPut } from "@/api/client";

export interface LibraryItem {
  id: number;
  school_id: number;
  title: string;
  author?: string;
  isbn?: string;
  category: string;
  type: string;
  available_copies: number;
  total_copies: number;
  file_url?: string;
  created_at: string;
}

export interface LibraryLoan {
  id: number;
  library_item_id: number;
  item_title?: string;
  student_id: number;
  student_name?: string;
  issued_at: string;
  due_date: string;
  returned_at?: string;
  status: string; // active, returned, overdue
}

export function useLibraryCatalog(category?: string, type?: string, q?: string) {
  return useQuery<LibraryItem[]>({
    queryKey: ["library-catalog", { category, type, q }],
    queryFn: () =>
      apiGet<LibraryItem[]>("/library/catalog", {
        category: category && category !== "all" ? category : undefined,
        type: type && type !== "all" ? type : undefined,
        q: q || undefined,
      }),
  });
}

export function useStudentLoans(studentId?: number) {
  return useQuery<LibraryLoan[]>({
    queryKey: ["student-loans", studentId],
    queryFn: () => apiGet<LibraryLoan[]>(`/library/my-loans/${studentId}`),
    enabled: typeof studentId === "number" && !isNaN(studentId),
  });
}

export function useAllLoans(statusFilter?: string) {
  return useQuery<LibraryLoan[]>({
    queryKey: ["all-library-loans", statusFilter],
    queryFn: () =>
      apiGet<LibraryLoan[]>("/library/loans", {
        status: statusFilter && statusFilter !== "all" ? statusFilter : undefined,
      }),
  });
}

export function useAddLibraryItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      title: string;
      author?: string;
      isbn?: string;
      category: string;
      type: string;
      total_copies: number;
      file_url?: string;
    }) => apiPost<LibraryItem>("/library/items", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library-catalog"] });
    },
  });
}

export function useIssueBook() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: {
      item_id: number;
      student_id: number;
      loan_days?: number;
    }) => apiPost<LibraryLoan>("/library/issue", payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["student-loans"] });
      queryClient.invalidateQueries({ queryKey: ["all-library-loans"] });
    },
  });
}

export function useReturnBook() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (loanId: number) =>
      apiPut<LibraryLoan>(`/library/return/${loanId}`),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["library-catalog"] });
      queryClient.invalidateQueries({ queryKey: ["student-loans"] });
      queryClient.invalidateQueries({ queryKey: ["all-library-loans"] });
    },
  });
}
