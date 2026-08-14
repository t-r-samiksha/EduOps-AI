import { useState } from "react";
import { useAuthStore } from "@/store/authStore";
import { useTimetableActive, useReferenceLookup } from "@/api/hooks/useTimetable";
import { DEFAULT_ACADEMIC_YEAR, DEMO_SCHOOL_ID } from "@/lib/constants";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import TimetableGrid from "@/components/timetable/TimetableGrid";
import { ApiError } from "@/api/client";

export default function TimetablePage() {
  const { role } = useAuthStore();
  const lookup = useReferenceLookup(DEMO_SCHOOL_ID);
  const [classId, setClassId] = useState<number | undefined>(undefined);
  const [studentId, setStudentId] = useState<string>("");

  const isAdminLike = role === "admin" || role === "principal";
  const parentStudentId = role === "parent" && studentId.trim() ? Number(studentId) : undefined;

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

            {role === "parent" && (
              <Field label="" className="w-40">
                <Input
                  type="number"
                  value={studentId}
                  onChange={(e) => setStudentId(e.target.value)}
                  placeholder="Child's student ID"
                />
              </Field>
            )}
          </>
        }
      />

      {role === "parent" && parentStudentId === undefined && (
        <Card>
          <CardHeader>
            <CardTitle>Enter a student ID</CardTitle>
            <CardDescription>
              There's no "my linked children" lookup endpoint yet — enter your child's numeric student ID above to view
              their timetable. This is a known gap, not a bug.
            </CardDescription>
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
        !error && <TimetableGrid slots={data ?? []} lookup={lookup.data} showClass={isAdminLike && !classId} editable={isAdminLike} />
      )}
    </div>
  );
}
