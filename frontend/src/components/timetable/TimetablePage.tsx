import { useEffect, useState } from "react";
import { Users } from "lucide-react";
import { useAuthStore } from "@/store/authStore";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useTimetableActive, useReferenceLookup } from "@/api/hooks/useTimetable";
import { useParentChildren } from "@/api/hooks/useParent";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import PageHeader from "@/components/shared/PageHeader";
import TimetableGrid from "@/components/timetable/TimetableGrid";
import GenerateTimetableForm from "@/components/timetable/GenerateTimetableForm";
import { ApiError } from "@/api/client";

export default function TimetablePage() {
  const { role } = useAuthStore();
  const schoolId = useCurrentUser().data?.school_id;
  const lookup = useReferenceLookup(schoolId);
  const [classId, setClassId] = useState<number | undefined>(undefined);
  const children = useParentChildren();
  const [selectedChildId, setSelectedChildId] = useState<string>("");

  const isAdminLike = role === "admin" || role === "principal";

  useEffect(() => {
    if (role === "parent" && !selectedChildId && children.data?.items.length) {
      setSelectedChildId(String(children.data.items[0].id));
    }
  }, [role, children.data, selectedChildId]);

  const parentStudentId = role === "parent" && selectedChildId ? Number(selectedChildId) : undefined;
  const showChildSelect = role === "parent" && (children.data?.items.length ?? 0) > 1;

  const { data, isLoading, error } = useTimetableActive({
    academicYear: DEFAULT_ACADEMIC_YEAR,
    classId: isAdminLike ? classId : undefined,
    studentId: role === "parent" ? parentStudentId : undefined,
    enabled: role !== "parent" || parentStudentId !== undefined,
  });

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="Timetable"
        description={
          <>
            Academic year <span className="font-mono text-ink">{DEFAULT_ACADEMIC_YEAR}</span>
            {isAdminLike && classId && lookup.data ? (
              <>
                {" "}
                · <span className="font-mono text-ink">{lookup.data.classes.find((c) => c.id === classId)?.name}</span>
              </>
            ) : null}
            {isAdminLike && (
              <>
                {" "}
                · Drag a slot to a new day/period to reschedule it. Red drop zones are a same-teacher/room/class heads-up
                based on what's currently loaded (accurate only for "All classes") — the real check happens on drop.
              </>
            )}
          </>
        }
        actions={
          <>
            {isAdminLike && (
              <Select
                value={classId ? String(classId) : "all"}
                onValueChange={(v) => setClassId(v === "all" ? undefined : Number(v))}
              >
                <SelectTrigger className="w-48">
                  <SelectValue placeholder="All classes" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All classes</SelectItem>
                  {lookup.data?.classes.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}

            {isAdminLike && schoolId != null && <GenerateTimetableForm schoolId={schoolId} />}

            {showChildSelect && (
              <Select value={selectedChildId} onValueChange={setSelectedChildId}>
                <SelectTrigger className="w-56">
                  <SelectValue placeholder="Select child" />
                </SelectTrigger>
                <SelectContent>
                  {children.data?.items.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name} {c.class_name ? `· ${c.class_name}` : ""}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </>
        }
      />

      {role === "parent" && !children.isLoading && (children.data?.items.length ?? 0) === 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2"><Users className="h-4 w-4" /> No linked children</CardTitle>
            <CardDescription>This account has no linked children yet.</CardDescription>
          </CardHeader>
        </Card>
      )}

      {error && (
        <Card className="border-urgent/40">
          <CardContent className="text-sm text-urgent">
            {error instanceof ApiError && error.status === 403
              ? "Not linked to this student."
              : error instanceof ApiError
                ? error.message
                : "Failed to load timetable."}
          </CardContent>
        </Card>
      )}

      {isLoading && (role !== "parent" || parentStudentId !== undefined) ? (
        <div className="h-64 animate-pulse rounded-lg border border-border bg-elevated/60" />
      ) : (
        (role !== "parent" || parentStudentId !== undefined) &&
        !error && (
          <TimetableGrid
            slots={data ?? []}
            lookup={lookup.data}
            showClass={role === "teacher" || (isAdminLike && !classId)}
            editable={isAdminLike}
          />
        )
      )}
    </div>
  );
}
