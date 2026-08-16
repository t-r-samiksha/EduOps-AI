const GRADE_LEVEL_DISPLAY_OVERRIDES: Record<number, string> = { "-3": "Nursery", "-2": "LKG", "-1": "UKG" };
/** Mirrors the backend's services/admissions_rules.py::grade_level_display (and
 * SchoolClass.grade_label's documented convention) - purely cosmetic. Accepts a
 * stringified grade level (e.g. "3", "-2") and returns a friendly label
 * ("Grade 3", "LKG"). Never prefix the result with "Grade " again yourself - that
 * was the exact "Grade Grade 3 - A" double-label bug found live. */
export function gradeLevelDisplay(gradeLevel: string): string {
  const level = Number(gradeLevel);
  if (!Number.isInteger(level)) return gradeLevel;
  return GRADE_LEVEL_DISPLAY_OVERRIDES[level] ?? `Grade ${level}`;
}

export function timeAgo(iso: string): string {
  const diffMs = Date.now() - new Date(iso).getTime();
  const diffSec = Math.round(diffMs / 1000);
  if (diffSec < 5) return "just now";
  if (diffSec < 60) return `${diffSec}s ago`;
  const diffMin = Math.round(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.round(diffHr / 24);
  return `${diffDay}d ago`;
}
