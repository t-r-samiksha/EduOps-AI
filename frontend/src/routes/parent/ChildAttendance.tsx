import { Card, CardContent } from "@/components/ui/card";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import PageHeader from "@/components/shared/PageHeader";
import StudentAttendanceView from "@/components/attendance/StudentAttendanceView";
import { useSelectedChild } from "@/hooks/useSelectedChild";

/** A linked child's period-by-period attendance.
 *
 * Child selection goes through useSelectedChild (the shared ?child= param), not a
 * hand-typed student id: GET /attendance/my-records 403s a parent who names a
 * child they aren't linked to, and asking a parent to know their child's numeric
 * id was never a real interface. */
export default function ChildAttendance() {
  const { children, selectedChildId, setSelectedChildId, selectedChild, showSelector, isLoading } =
    useSelectedChild();

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Attendance"
        description="Period-by-period attendance for your child, updated as soon as it is marked at school."
      />

      {isLoading && <div className="h-14 animate-pulse rounded-2xl bg-elevated/60" />}

      {!isLoading && children.length === 0 && (
        <Card>
          <CardContent className="py-6">
            <p className="text-sm text-ink-muted">
              No children are linked to your account yet. Ask the school office to link your child's record.
            </p>
          </CardContent>
        </Card>
      )}

      {!isLoading && children.length > 0 && (
        <>
          <Card>
            <CardContent className="flex flex-col gap-2 py-3">
              <label htmlFor="child-select" className="text-xs font-semibold uppercase tracking-wide text-ink-muted">
                Viewing
              </label>
              {showSelector ? (
                <Select value={String(selectedChildId ?? "")} onValueChange={(v) => setSelectedChildId(Number(v))}>
                  <SelectTrigger id="child-select" className="w-full" aria-label="Select which child to view">
                    <SelectValue placeholder="Select child" />
                  </SelectTrigger>
                  <SelectContent>
                    {children.map((child) => (
                      <SelectItem key={child.id} value={String(child.id)}>
                        {child.name}
                        {child.class_name ? ` · ${child.class_name}` : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : (
                <p className="font-display text-lg font-bold text-ink">
                  {selectedChild?.name}
                  {selectedChild?.class_name && (
                    <span className="ml-2 text-sm font-normal text-ink-muted">{selectedChild.class_name}</span>
                  )}
                </p>
              )}
            </CardContent>
          </Card>

          <div aria-live="polite">
            {selectedChildId !== undefined && (
              // Keyed on the child so switching resets the view's own date range
              // state rather than showing one child's range against another's data.
              <StudentAttendanceView
                key={selectedChildId}
                studentId={selectedChildId}
                heading={`${selectedChild?.name ?? "Child"}'s attendance`}
                description="Period by period, as recorded by the class camera or the teacher."
              />
            )}
          </div>
        </>
      )}
    </div>
  );
}
