import { useAuthStore } from "@/store/authStore";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useSelectedChild } from "@/hooks/useSelectedChild";

/**
 * The numeric database id of the logged-in user.
 *
 * USE THIS, NEVER `Number(useAuthStore().user.id)`. `authStore.user` is the Supabase auth
 * user, whose `id` is a UUID STRING - `Number("3fa8…")` is `NaN`, silently. That mistake
 * was live in eight places and had two flavours:
 *
 *   - `Number(user.id) || 2`  - the `|| 2` swallowed the NaN, so Student Analytics, the
 *     Homework Calendar and Bulk Remarks requested STUDENT #2's records for every role,
 *     in every school, in every session. Admins saw a stranger's data or an error, never
 *     their own school's.
 *   - `c.class_teacher_id === Number(user.id)` - NaN equals nothing, so the
 *     "classes I'm homeroom teacher of" branch in the Teacher Assistant Bot and the
 *     teacher Resources page never once matched, and both quietly fell back to a wider
 *     class list.
 *
 * The numeric id only exists server-side (it is not a JWT claim), so it has to come from
 * GET /auth/me. `useCurrentUser` caches it for 5 minutes, so this is not a per-page fetch.
 *
 * Returns `undefined` until /auth/me resolves - callers should leave dependent queries
 * disabled rather than substituting a fallback id.
 */
export function useMyUserId(): number | undefined {
  return useCurrentUser().data?.user_id;
}

export interface ViewedStudent {
  /** The student whose records the page should show, or undefined if not resolved yet
   *  (still loading) or not chosen yet (staff who have not picked anyone). */
  studentId: number | undefined;
  /** True while the identity itself is still being resolved, as distinct from resolved-to-
   *  nothing. A page that cannot tell these apart renders "no data" over a pending fetch. */
  isLoading: boolean;
  /** True when the caller must pick a student before there is anything to show - staff
   *  with no selection. Pages use this to render a "choose a class and student" prompt
   *  instead of an empty table that looks broken. */
  needsSelection: boolean;
}

/**
 * Which student's records the current page is showing, resolved per role.
 *
 * The academic pages (gradebook, report cards, analytics, calendar, remarks, library
 * loans) are each mounted on all five roles, and every one of them had its own broken
 * guess at this. One resolution, one place:
 *
 *   - student: themselves, always.
 *   - parent:  the child selected in the URL (`?child=`), via useSelectedChild.
 *   - staff:   whoever they explicitly picked - `explicitStudentId`. Never a default:
 *              silently defaulting an admin to "some student" is how student #2's
 *              gradebook ended up on an admin's screen.
 */
export function useViewedStudent(explicitStudentId?: number): ViewedStudent {
  const role = useAuthStore((s) => s.role);
  const me = useCurrentUser();
  const child = useSelectedChild({ enabled: role === "parent" });

  if (role === "parent") {
    return {
      studentId: child.selectedChildId,
      isLoading: child.isLoading,
      // A parent with no linked children has nothing to select, which is a different
      // message from "pick one" - pages render their own empty state for that.
      needsSelection: false,
    };
  }

  if (role === "student") {
    return {
      studentId: me.data?.user_id,
      isLoading: me.isLoading,
      needsSelection: false,
    };
  }

  return {
    studentId: explicitStudentId,
    isLoading: false,
    needsSelection: explicitStudentId === undefined,
  };
}
