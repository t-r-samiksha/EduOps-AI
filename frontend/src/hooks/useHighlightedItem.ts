import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Reads `?highlight=<id>`, scrolls that item into view, and rings it briefly.
 *
 * Exists so the homework calendar's cards can actually reach the thing they are about.
 * Neither the assignments nor the quizzes screen has a per-item route - they are list pages
 * that filter client-side - so a query param plus a scroll is the honest way to point at one
 * row without inventing routes and detail pages for both.
 *
 * The highlight FADES rather than persisting: it is a "here it is" cue, and a permanent ring
 * on one card would read as selected state that nothing can clear.
 *
 * Callers give each row `data-highlight-id={String(item.id)}` and apply `ringClass` when
 * `highlightedId === item.id`.
 */
export function useHighlightedItem(): {
  highlightedId: number | undefined;
  isFading: boolean;
} {
  const [searchParams] = useSearchParams();
  const raw = searchParams.get("highlight");
  const highlightedId = raw && !Number.isNaN(Number(raw)) ? Number(raw) : undefined;
  const [isFading, setIsFading] = useState(false);

  useEffect(() => {
    if (highlightedId === undefined) return;
    setIsFading(false);

    // The list is rendered from a query that may still be loading on mount, so the element
    // is not guaranteed to exist yet. Retry a few frames rather than scrolling to nothing.
    let attempts = 0;
    const timer = window.setInterval(() => {
      const el = document.querySelector(`[data-highlight-id="${highlightedId}"]`);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        window.clearInterval(timer);
        return;
      }
      if (++attempts > 20) window.clearInterval(timer); // ~4s, then give up quietly
    }, 200);

    const fade = window.setTimeout(() => setIsFading(true), 2600);
    return () => {
      window.clearInterval(timer);
      window.clearTimeout(fade);
    };
  }, [highlightedId]);

  return { highlightedId, isFading };
}

/** Ring applied to the highlighted row. Exported so both list pages look identical. */
export const HIGHLIGHT_RING = "ring-2 ring-primary ring-offset-2 transition-shadow duration-700";
