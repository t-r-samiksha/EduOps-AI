import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useParentChildren } from "@/api/hooks/useParent";
import type { LinkedChild } from "@/api/types";

/**
 * The parent's currently-selected child, shared by every parent-facing screen.
 *
 * WHY THIS EXISTS: this exact block was duplicated verbatim in FOUR places -
 * ParentDashboard, TimetablePage, RiskDashboard and FeesPage - each with its own
 * `useState("")` plus the same first-child-defaulting effect. A fifth copy was about to
 * be written for the parent portal. Unlike the backend's per-router scoping helpers
 * (which routers/fees.py documents as a deliberate convention), nothing defended this
 * duplication; it was just copy-paste.
 *
 * SELECTION LIVES IN THE URL (`?child=`), not component state. The four copies all lost
 * the selection on reload and could not be deep-linked - you could not send someone "the
 * page showing Diya". Putting it in a query param also means switching child is a real
 * navigation, so the browser back button does what a parent expects.
 */
export interface UseSelectedChild {
  children: LinkedChild[];
  selectedChildId: number | undefined;
  setSelectedChildId: (id: number) => void;
  selectedChild: LinkedChild | undefined;
  /** True only when there is a real choice to make - one child needs no selector. */
  showSelector: boolean;
  isLoading: boolean;
}

const PARAM = "child";

/** `enabled: false` skips the /parent/children request entirely.
 *
 * Needed because the shared academic pages call useViewedStudent for EVERY role, and
 * GET /parent/children is `require_role("parent")` - so without this a staff user would
 * fire a guaranteed 403 on every one of those pages. `isLoading` reports false when
 * disabled, so a staff caller is never told it is waiting on a request that will not
 * happen. */
export function useSelectedChild(options?: { enabled?: boolean }): UseSelectedChild {
  const enabled = options?.enabled ?? true;
  const query = useParentChildren({ enabled });
  const [searchParams, setSearchParams] = useSearchParams();

  const children = query.data?.items ?? [];
  const fromUrl = Number(searchParams.get(PARAM));

  // Only honour a URL value that names a child this parent is ACTUALLY linked to.
  // Otherwise a hand-edited `?child=99999` would leave every card requesting a student
  // the backend will 403 on, which reads as a broken page rather than a rejected one.
  const valid = children.some((c) => c.id === fromUrl);
  const selectedChildId = valid ? fromUrl : children[0]?.id;

  useEffect(() => {
    // Reflect the effective selection back into the URL so a bare /parent/child (or a
    // stale/invalid ?child=) becomes shareable without the user touching the selector.
    if (selectedChildId === undefined || valid) return;
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set(PARAM, String(selectedChildId));
        return next;
      },
      { replace: true }, // replace, not push - this is a correction, not a navigation
    );
  }, [selectedChildId, valid, setSearchParams]);

  return {
    children,
    selectedChildId,
    setSelectedChildId: (id: number) =>
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.set(PARAM, String(id));
        return next;
      }),
    selectedChild: children.find((c) => c.id === selectedChildId),
    showSelector: children.length > 1,
    isLoading: enabled && query.isLoading,
  };
}
