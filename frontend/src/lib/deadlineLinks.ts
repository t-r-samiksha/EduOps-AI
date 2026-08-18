import type { Role } from "@/store/authStore";

/** `assignment_12` -> `{ kind: "assignment", id: 12 }`. */
export function parseDeadlineId(
  eventId: string,
): { kind: "assignment" | "quiz" | "exam"; id: number } | null {
  const match = /^(assignment|quiz|exam)_(\d+)$/.exec(eventId);
  if (!match) return null;
  return { kind: match[1] as "assignment" | "quiz" | "exam", id: Number(match[2]) };
}

/**
 * Where a homework-calendar card should take you.
 *
 * The calendar was previously a dead end: clicking a deadline opened a modal repeating the
 * same three facts already on the card, with no way to reach the actual assignment or quiz.
 * A deadline you cannot act on is a reminder, not a task list.
 *
 * `?highlight=` rather than a per-item route, because no per-item route exists for these -
 * both pages are list screens that filter client-side. The destination scrolls the item into
 * view and rings it (see useHighlightedItem).
 *
 * QUIZZES ARE HIGHLIGHTED, NOT OPENED. QuizzesPage starts an attempt in an effect as soon as
 * a quiz id is set - a timed attempt with a server-side `started_at`. Opening one straight
 * from a URL would silently burn a student's single attempt because they tapped a reminder,
 * so the card takes them to the quiz in the list and they press Start themselves.
 *
 * Returns null when there is nowhere useful to go for that role, so the caller can leave the
 * card inert instead of navigating somewhere confusing.
 */
export function deadlineRoute(
  role: Role | null,
  eventId: string,
): string | null {
  if (!role) return null;
  const parsed = parseDeadlineId(eventId);
  if (!parsed) return null;

  const { kind, id } = parsed;

  if (kind === "assignment") {
    // Parents have no assignments page of their own in the nav; they read the child's work
    // through the portal, so there is nothing to link to.
    if (role === "parent") return null;
    return `/${role}/assignments?highlight=${id}`;
  }

  if (kind === "quiz") {
    if (role === "parent") return null;
    return `/${role}/quizzes?highlight=${id}`;
  }

  // Exams. The student-facing screen is a seat lookup rather than an exam list, so there is
  // no per-exam target to highlight - link to the page itself.
  if (role === "student") return "/student/exams";
  if (role === "teacher") return "/teacher/exams";
  if (role === "admin" || role === "principal") return `/${role}/exams`;
  return null;
}
