import { Fragment, useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, ChevronDown, ChevronRight as ChevronRightIcon, Pencil, Plus, Power, PowerOff } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Card, CardContent } from "@/components/ui/card";
import { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogTrigger } from "@/components/ui/dialog";
import Field from "@/components/ui/field";
import PageHeader from "@/components/shared/PageHeader";
import ConfirmDialog from "@/components/shared/ConfirmDialog";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useReferenceLookup, useTimetableActive, computeSlotsByTeacher } from "@/api/hooks/useTimetable";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { ApiError } from "@/api/client";
import {
  useClassesAdmin, useCreateClass, useUpdateClass, useDeactivateClass, useReactivateClass, type ClassOut,
  useSubjectsAdmin, useCreateSubject, useUpdateSubject, useDeactivateSubject, useReactivateSubject, type SubjectOut,
  useRoomsAdmin, useCreateRoom, useUpdateRoom, useDeactivateRoom, useReactivateRoom, type RoomOut,
  useTeachersAdmin, useUpdateTeacher, useDeactivateTeacher, useReactivateTeacher,
  useAddTeacherSubject, useRemoveTeacherSubject, useAddTeacherUnavailability, useRemoveTeacherUnavailability, type TeacherOut,
  useStudentsAdmin, useUpdateStudent, useDeactivateStudent, useReactivateStudent, type StudentOut,
  useParentsAdmin, useUpdateParent, useDeactivateParent, useReactivateParent,
  useAddParentChild, useRemoveParentChild, type ParentOut,
} from "@/api/hooks/useMasterData";

const PAGE_SIZE = 10;
const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

// --- Shared bits ---------------------------------------------------------------

function StatusBadge({ isActive }: { isActive: boolean }) {
  return <Badge variant={isActive ? "positive" : "outline"}>{isActive ? "Active" : "Deactivated"}</Badge>;
}

function EmptyState({ label }: { label: string }) {
  return (
    <Card>
      <CardContent className="flex flex-col items-center gap-2 py-10 text-center">
        <p className="font-display text-sm font-medium text-ink">Nothing here yet</p>
        <p className="max-w-sm text-xs text-ink-muted">
          No {label} exist for this school yet. Add the first one below, or use the onboarding wizard if you're setting
          several up at once.
        </p>
        <a href="/onboarding" className="text-xs font-medium text-accent hover:underline">
          Go to onboarding wizard
        </a>
      </CardContent>
    </Card>
  );
}

function Pagination({ page, setPage, total }: { page: number; setPage: (p: number) => void; total: number }) {
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  if (totalPages <= 1) return null;
  return (
    <div className="flex items-center justify-between pt-1">
      <span className="text-xs text-ink-faint">
        Page {page} of {totalPages} · {total} total
      </span>
      <div className="flex gap-1.5">
        <Button variant="outline" size="sm" onClick={() => setPage(Math.max(1, page - 1))} disabled={page <= 1}>
          <ChevronLeft className="h-3.5 w-3.5" />
        </Button>
        <Button variant="outline" size="sm" onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page >= totalPages}>
          <ChevronRight className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

function IncludeInactiveToggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className="flex items-center gap-1.5 text-xs font-medium text-ink-muted">
      <input type="checkbox" checked={value} onChange={(e) => onChange(e.target.checked)} className="h-3.5 w-3.5 rounded border-border accent-accent" />
      Show deactivated
    </label>
  );
}

function usePaged<T>(items: T[] | undefined, page: number) {
  const all = items ?? [];
  const start = (page - 1) * PAGE_SIZE;
  return { rows: all.slice(start, start + PAGE_SIZE), total: all.length };
}

// --- Classes ---------------------------------------------------------------------

function AddClassForm({
  schoolId,
  onCancel,
  teacherOptions,
}: {
  schoolId: number;
  onCancel: () => void;
  teacherOptions: { id: number; name: string; classCount: number }[];
}) {
  const [gradeLevel, setGradeLevel] = useState("");
  const [gradeLabel, setGradeLabel] = useState("");
  const [section, setSection] = useState("");
  const [academicYear, setAcademicYear] = useState(DEFAULT_ACADEMIC_YEAR);
  // Pre-selects the least-loaded qualified teacher (teacherOptions is already
  // sorted ascending by classCount) as a suggestion - still just a default,
  // freely overridable via the same dropdown.
  const [classTeacherId, setClassTeacherId] = useState(() => (teacherOptions[0] ? String(teacherOptions[0].id) : ""));
  const create = useCreateClass();

  function handleSave() {
    const level = Number(gradeLevel);
    if (!level && level !== 0) return;
    if (!classTeacherId) return;
    const label = gradeLabel.trim() || undefined;
    const name = `${label || `Grade ${level}`}${section ? ` - ${section}` : ""}`;
    create.mutate(
      {
        school_id: schoolId, name, academic_year: academicYear, grade_level: level, grade_label: label,
        section: section || undefined, class_teacher_id: Number(classTeacherId),
      },
      { onSuccess: onCancel }
    );
  }

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-xl border border-accent/30 bg-accent/5 px-3.5 py-3">
      <Field label="Grade level (number)" className="w-32" hint="Nursery=-3, LKG=-2, UKG=-1...">
        <Input type="number" value={gradeLevel} onChange={(e) => setGradeLevel(e.target.value)} autoFocus />
      </Field>
      <Field label="Label (optional)" className="w-24">
        <Input value={gradeLabel} onChange={(e) => setGradeLabel(e.target.value)} placeholder="e.g. LKG" />
      </Field>
      <Field label="Section" className="w-20">
        <Input value={section} onChange={(e) => setSection(e.target.value)} placeholder="A" />
      </Field>
      <Field label="Academic year" className="w-28">
        <Input value={academicYear} onChange={(e) => setAcademicYear(e.target.value)} />
      </Field>
      <Field label="Class teacher (required)" className="w-56" hint="Pre-filled with the least-loaded teacher - change it if you'd rather pick someone else.">
        <Select value={classTeacherId} onValueChange={setClassTeacherId}>
          <SelectTrigger>
            <SelectValue placeholder="Select a teacher" />
          </SelectTrigger>
          <SelectContent>
            {teacherOptions.map((t) => (
              <SelectItem key={t.id} value={String(t.id)}>
                {t.name} · {t.classCount} class{t.classCount === 1 ? "" : "es"}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </Field>
      <Button size="sm" onClick={handleSave} disabled={!gradeLevel || !classTeacherId || create.isPending}>
        {create.isPending ? "Adding…" : "Add class"}
      </Button>
      <Button variant="ghost" size="sm" onClick={onCancel}>
        Cancel
      </Button>
      {create.isError && (
        <p className="w-full text-xs text-urgent">{create.error instanceof ApiError ? create.error.message : "Failed to create class."}</p>
      )}
    </div>
  );
}

function EditClassDialog({
  schoolId,
  cls,
  teacherOptions,
  roomOptions,
}: {
  schoolId: number;
  cls: ClassOut;
  teacherOptions: { id: number; name: string }[];
  roomOptions: { id: number; name: string; room_type: string }[];
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(cls.name);
  const [academicYear, setAcademicYear] = useState(cls.academic_year);
  const [gradeLevel, setGradeLevel] = useState(cls.grade_level != null ? String(cls.grade_level) : "");
  const [gradeLabel, setGradeLabel] = useState(cls.grade_label ?? "");
  const [section, setSection] = useState(cls.section ?? "");
  const [classTeacherId, setClassTeacherId] = useState(cls.class_teacher_id != null ? String(cls.class_teacher_id) : "");
  const [homeRoomId, setHomeRoomId] = useState(cls.home_room_id != null ? String(cls.home_room_id) : "");
  const update = useUpdateClass();

  function handleSave() {
    update.mutate(
      {
        classId: cls.id, schoolId, name, academic_year: academicYear,
        grade_level: gradeLevel ? Number(gradeLevel) : undefined,
        grade_label: gradeLabel || undefined, section: section || undefined,
        class_teacher_id: classTeacherId ? Number(classTeacherId) : undefined,
        home_room_id: homeRoomId ? Number(homeRoomId) : undefined,
      },
      { onSuccess: () => setOpen(false) }
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Pencil className="h-3.5 w-3.5" /> Edit
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit class</DialogTitle>
          <DialogDescription>Changes apply immediately, real update - no separate save step elsewhere.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <div className="grid grid-cols-3 gap-3">
            <Field label="Grade level">
              <Input type="number" value={gradeLevel} onChange={(e) => setGradeLevel(e.target.value)} />
            </Field>
            <Field label="Label">
              <Input value={gradeLabel} onChange={(e) => setGradeLabel(e.target.value)} placeholder="e.g. LKG" />
            </Field>
            <Field label="Section">
              <Input value={section} onChange={(e) => setSection(e.target.value)} />
            </Field>
          </div>
          <Field label="Academic year">
            <Input value={academicYear} onChange={(e) => setAcademicYear(e.target.value)} />
          </Field>
          <Field label="Class teacher">
            <Select value={classTeacherId} onValueChange={setClassTeacherId}>
              <SelectTrigger>
                <SelectValue placeholder="None assigned" />
              </SelectTrigger>
              <SelectContent>
                {teacherOptions.map((t) => (
                  <SelectItem key={t.id} value={String(t.id)}>
                    {t.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          <Field
            label="Home room"
            hint="Every non-lab period for this class is pinned to this room during timetable generation - a real class doesn't hop between arbitrary rooms all day. Two active classes may never share one."
          >
            <Select value={homeRoomId} onValueChange={setHomeRoomId}>
              <SelectTrigger>
                <SelectValue placeholder="Not configured" />
              </SelectTrigger>
              <SelectContent>
                {roomOptions.map((r) => (
                  <SelectItem key={r.id} value={String(r.id)}>
                    {r.name} ({r.room_type})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {update.isError && (
            <p className="text-sm text-urgent">{update.error instanceof ApiError ? update.error.message : "Failed to update class."}</p>
          )}
          <Button onClick={handleSave} disabled={update.isPending} className="self-start">
            {update.isPending ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ClassesTab({ schoolId }: { schoolId: number }) {
  const [page, setPage] = useState(1);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const classes = useClassesAdmin(schoolId, includeInactive);
  const lookup = useReferenceLookup(schoolId);
  const students = useStudentsAdmin(schoolId);
  const deactivate = useDeactivateClass();
  const reactivate = useReactivateClass();

  const studentCountByClass = useMemo(() => {
    const map = new Map<number, number>();
    for (const s of students.data ?? []) {
      if (s.class_id == null) continue;
      map.set(s.class_id, (map.get(s.class_id) ?? 0) + 1);
    }
    return map;
  }, [students.data]);

  const teacherName = (id: number | null) => (id == null ? "—" : lookup.data?.teachers.find((t) => t.id === id)?.name ?? `Teacher #${id}`);
  // Load = how many active classes this teacher is already the class teacher of -
  // sorted ascending so the least-loaded teacher is both the first option shown
  // and the one AddClassForm pre-selects (a suggestion, not a silent auto-pick;
  // the admin can still choose anyone else from the same list).
  const classTeacherLoad = useMemo(() => {
    const map = new Map<number, number>();
    for (const c of classes.data ?? []) {
      if (c.class_teacher_id != null && c.is_active) map.set(c.class_teacher_id, (map.get(c.class_teacher_id) ?? 0) + 1);
    }
    return map;
  }, [classes.data]);
  const teacherOptions = (lookup.data?.teachers ?? [])
    .map((t) => ({ id: t.id, name: t.name, classCount: classTeacherLoad.get(t.id) ?? 0 }))
    .sort((a, b) => a.classCount - b.classCount);
  const roomName = (id: number | null) => (id == null ? "Not configured" : lookup.data?.rooms.find((r) => r.id === id)?.name ?? `Room #${id}`);
  const roomOptions = lookup.data?.rooms.map((r) => ({ id: r.id, name: r.name, room_type: r.room_type })) ?? [];

  const sorted = useMemo(
    () => [...(classes.data ?? [])].sort((a, b) => (a.grade_level ?? 0) - (b.grade_level ?? 0) || (a.section ?? "").localeCompare(b.section ?? "")),
    [classes.data]
  );
  const { rows, total } = usePaged(sorted, page);
  const missingTeacherCount = (classes.data ?? []).filter((c) => c.is_active && c.class_teacher_id == null).length;

  return (
    <div className="flex flex-col gap-3">
      {missingTeacherCount > 0 && (
        <Card className="border-warning/40 bg-warning/5">
          <CardContent className="py-3 text-sm text-warning">
            {missingTeacherCount} active class{missingTeacherCount === 1 ? "" : "es"} {missingTeacherCount === 1 ? "has" : "have"} no class
            teacher assigned. Timetable generation is blocked for any class without one — assign one below.
          </CardContent>
        </Card>
      )}
      <div className="flex items-center justify-between">
        <IncludeInactiveToggle value={includeInactive} onChange={setIncludeInactive} />
        {!showAdd && (
          <Button variant="outline" size="sm" onClick={() => setShowAdd(true)}>
            <Plus className="h-3.5 w-3.5" /> Add class
          </Button>
        )}
      </div>
      {showAdd && <AddClassForm schoolId={schoolId} onCancel={() => setShowAdd(false)} teacherOptions={teacherOptions} />}

      {classes.isLoading && <div className="h-32 animate-pulse rounded-2xl bg-elevated/60" />}
      {!classes.isLoading && total === 0 && <EmptyState label="classes" />}

      {total > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Grade / Section</TableHead>
              <TableHead>Academic year</TableHead>
              <TableHead>Students</TableHead>
              <TableHead>Class teacher</TableHead>
              <TableHead>Home room</TableHead>
              <TableHead>Status</TableHead>
              <TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="font-medium text-ink">
                  {c.grade_label ?? `Grade ${c.grade_level ?? "?"}`}
                  {c.section ? ` - ${c.section}` : ""}
                </TableCell>
                <TableCell className="text-ink-muted">{c.academic_year}</TableCell>
                <TableCell className="font-mono tabular-nums">{studentCountByClass.get(c.id) ?? 0}</TableCell>
                <TableCell className={c.class_teacher_id == null ? "text-warning" : "text-ink-muted"}>{teacherName(c.class_teacher_id)}</TableCell>
                <TableCell className={c.home_room_id == null ? "text-warning" : "text-ink-muted"}>{roomName(c.home_room_id)}</TableCell>
                <TableCell>
                  <StatusBadge isActive={c.is_active} />
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1.5">
                    <EditClassDialog schoolId={schoolId} cls={c} teacherOptions={teacherOptions} roomOptions={roomOptions} />
                    {c.is_active ? (
                      <ConfirmDialog
                        trigger={
                          <DialogTrigger asChild>
                            <Button variant="outline" size="sm">
                              <PowerOff className="h-3.5 w-3.5" /> Deactivate
                            </Button>
                          </DialogTrigger>
                        }
                        title={`Deactivate ${c.name}?`}
                        description="Reversible - you can reactivate this class anytime. It will stop appearing in class pickers elsewhere in the app while deactivated."
                        confirmLabel="Deactivate"
                        onConfirm={() => deactivate.mutate({ classId: c.id, schoolId })}
                      />
                    ) : (
                      <Button variant="outline" size="sm" onClick={() => reactivate.mutate({ classId: c.id, schoolId })} disabled={reactivate.isPending}>
                        <Power className="h-3.5 w-3.5" /> Reactivate
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Pagination page={page} setPage={setPage} total={total} />
    </div>
  );
}

// --- Subjects --------------------------------------------------------------------

function AddSubjectRow({ schoolId, onCancel }: { schoolId: number; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [periodsPerWeek, setPeriodsPerWeek] = useState("3");
  const [labRequired, setLabRequired] = useState(false);
  const create = useCreateSubject();

  function handleSave() {
    if (!name.trim()) return;
    create.mutate(
      { school_id: schoolId, name: name.trim(), code: code || undefined, periods_per_week: Number(periodsPerWeek) || 3, lab_required: labRequired },
      { onSuccess: onCancel }
    );
  }

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-xl border border-accent/30 bg-accent/5 px-3.5 py-3">
      <Field label="Name" className="w-40">
        <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </Field>
      <Field label="Code (optional)" className="w-24">
        <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="MTH" />
      </Field>
      <Field label="Periods/wk" className="w-24">
        <Input type="number" min={1} value={periodsPerWeek} onChange={(e) => setPeriodsPerWeek(e.target.value)} />
      </Field>
      <label className="flex items-center gap-1.5 pb-2 text-xs font-medium text-ink-muted">
        <input type="checkbox" checked={labRequired} onChange={(e) => setLabRequired(e.target.checked)} className="h-3.5 w-3.5 rounded border-border accent-accent" />
        Lab required
      </label>
      <Button size="sm" onClick={handleSave} disabled={!name.trim() || create.isPending}>
        {create.isPending ? "Adding…" : "Add subject"}
      </Button>
      <Button variant="ghost" size="sm" onClick={onCancel}>
        Cancel
      </Button>
      {create.isError && (
        <p className="w-full text-xs text-urgent">{create.error instanceof ApiError ? create.error.message : "Failed to create subject."}</p>
      )}
    </div>
  );
}

function EditSubjectDialog({ schoolId, subject }: { schoolId: number; subject: SubjectOut }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(subject.name);
  const [code, setCode] = useState(subject.code ?? "");
  const [periodsPerWeek, setPeriodsPerWeek] = useState(String(subject.periods_per_week));
  const [labRequired, setLabRequired] = useState(subject.lab_required);
  const update = useUpdateSubject();

  function handleSave() {
    update.mutate(
      { subjectId: subject.id, schoolId, name, code: code || undefined, periods_per_week: Number(periodsPerWeek) || 1, lab_required: labRequired },
      { onSuccess: () => setOpen(false) }
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Pencil className="h-3.5 w-3.5" /> Edit
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit subject</DialogTitle>
          <DialogDescription>
            Periods/week and lab requirement are real defaults - a generation run can still override either for that
            one run only.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Code (optional)">
            <Input value={code} onChange={(e) => setCode(e.target.value)} />
          </Field>
          <Field label="Periods/week (default)">
            <Input type="number" min={1} value={periodsPerWeek} onChange={(e) => setPeriodsPerWeek(e.target.value)} className="max-w-28" />
          </Field>
          <label className="flex items-center gap-1.5 text-xs font-medium text-ink-muted">
            <input type="checkbox" checked={labRequired} onChange={(e) => setLabRequired(e.target.checked)} className="h-3.5 w-3.5 rounded border-border accent-accent" />
            Lab required (default)
          </label>
          {update.isError && (
            <p className="text-sm text-urgent">{update.error instanceof ApiError ? update.error.message : "Failed to update subject."}</p>
          )}
          <Button onClick={handleSave} disabled={update.isPending} className="self-start">
            {update.isPending ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function SubjectsTab({ schoolId }: { schoolId: number }) {
  const [page, setPage] = useState(1);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const subjects = useSubjectsAdmin(schoolId, includeInactive);
  const deactivate = useDeactivateSubject();
  const reactivate = useReactivateSubject();

  const sorted = useMemo(() => [...(subjects.data ?? [])].sort((a, b) => a.name.localeCompare(b.name)), [subjects.data]);
  const { rows, total } = usePaged(sorted, page);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <IncludeInactiveToggle value={includeInactive} onChange={setIncludeInactive} />
        {!showAdd && (
          <Button variant="outline" size="sm" onClick={() => setShowAdd(true)}>
            <Plus className="h-3.5 w-3.5" /> Add subject
          </Button>
        )}
      </div>
      {showAdd && <AddSubjectRow schoolId={schoolId} onCancel={() => setShowAdd(false)} />}

      {subjects.isLoading && <div className="h-32 animate-pulse rounded-2xl bg-elevated/60" />}
      {!subjects.isLoading && total === 0 && <EmptyState label="subjects" />}

      {total > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Code</TableHead>
              <TableHead>Periods/wk</TableHead>
              <TableHead>Lab required</TableHead>
              <TableHead>Status</TableHead>
              <TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="font-medium text-ink">{s.name}</TableCell>
                <TableCell className="text-ink-muted">{s.code ?? "—"}</TableCell>
                <TableCell className="font-mono tabular-nums">{s.periods_per_week}</TableCell>
                <TableCell>{s.lab_required ? <Badge variant="accent">Yes</Badge> : <span className="text-ink-muted">No</span>}</TableCell>
                <TableCell>
                  <StatusBadge isActive={s.is_active} />
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1.5">
                    <EditSubjectDialog schoolId={schoolId} subject={s} />
                    {s.is_active ? (
                      <ConfirmDialog
                        trigger={
                          <DialogTrigger asChild>
                            <Button variant="outline" size="sm">
                              <PowerOff className="h-3.5 w-3.5" /> Deactivate
                            </Button>
                          </DialogTrigger>
                        }
                        title={`Deactivate ${s.name}?`}
                        description="Reversible - you can reactivate this subject anytime. It will stop appearing in the subject picker for new timetable generation runs while deactivated."
                        confirmLabel="Deactivate"
                        onConfirm={() => deactivate.mutate({ subjectId: s.id, schoolId })}
                      />
                    ) : (
                      <Button variant="outline" size="sm" onClick={() => reactivate.mutate({ subjectId: s.id, schoolId })} disabled={reactivate.isPending}>
                        <Power className="h-3.5 w-3.5" /> Reactivate
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Pagination page={page} setPage={setPage} total={total} />
    </div>
  );
}

// --- Rooms -----------------------------------------------------------------------

const ROOM_TYPES = ["classroom", "lab", "auditorium"];

function AddRoomRow({ schoolId, onCancel }: { schoolId: number; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [capacity, setCapacity] = useState("30");
  const [roomType, setRoomType] = useState("classroom");
  const create = useCreateRoom();

  function handleSave() {
    if (!name.trim()) return;
    create.mutate(
      { school_id: schoolId, name: name.trim(), capacity: Number(capacity) || 30, room_type: roomType },
      { onSuccess: onCancel }
    );
  }

  return (
    <div className="flex flex-wrap items-end gap-3 rounded-xl border border-accent/30 bg-accent/5 px-3.5 py-3">
      <Field label="Name" className="w-40">
        <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Room 101" autoFocus />
      </Field>
      <Field label="Capacity" className="w-24">
        <Input type="number" min={1} value={capacity} onChange={(e) => setCapacity(e.target.value)} />
      </Field>
      <Field label="Type" className="w-36">
        <select
          value={roomType}
          onChange={(e) => setRoomType(e.target.value)}
          className="flex h-10 w-full items-center rounded-xl border border-border bg-card px-3.5 text-sm text-ink shadow-sm"
        >
          {ROOM_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
      </Field>
      <Button size="sm" onClick={handleSave} disabled={!name.trim() || create.isPending}>
        {create.isPending ? "Adding…" : "Add room"}
      </Button>
      <Button variant="ghost" size="sm" onClick={onCancel}>
        Cancel
      </Button>
      {create.isError && (
        <p className="w-full text-xs text-urgent">{create.error instanceof ApiError ? create.error.message : "Failed to create room."}</p>
      )}
    </div>
  );
}

function EditRoomDialog({ schoolId, room }: { schoolId: number; room: RoomOut }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState(room.name);
  const [capacity, setCapacity] = useState(String(room.capacity));
  const [roomType, setRoomType] = useState(room.room_type);
  const update = useUpdateRoom();

  function handleSave() {
    update.mutate(
      { roomId: room.id, schoolId, name, capacity: Number(capacity) || 1, room_type: roomType },
      { onSuccess: () => setOpen(false) }
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Pencil className="h-3.5 w-3.5" /> Edit
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit room</DialogTitle>
          <DialogDescription>Changes apply immediately.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Name">
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          <Field label="Capacity">
            <Input type="number" min={1} value={capacity} onChange={(e) => setCapacity(e.target.value)} className="max-w-28" />
          </Field>
          <Field label="Type">
            <select
              value={roomType}
              onChange={(e) => setRoomType(e.target.value)}
              className="flex h-10 w-full max-w-40 items-center rounded-xl border border-border bg-card px-3.5 text-sm text-ink shadow-sm"
            >
              {ROOM_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
          </Field>
          {update.isError && (
            <p className="text-sm text-urgent">{update.error instanceof ApiError ? update.error.message : "Failed to update room."}</p>
          )}
          <Button onClick={handleSave} disabled={update.isPending} className="self-start">
            {update.isPending ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function RoomsTab({ schoolId }: { schoolId: number }) {
  const [page, setPage] = useState(1);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [showAdd, setShowAdd] = useState(false);
  const rooms = useRoomsAdmin(schoolId, includeInactive);
  const deactivate = useDeactivateRoom();
  const reactivate = useReactivateRoom();

  const sorted = useMemo(() => [...(rooms.data ?? [])].sort((a, b) => a.name.localeCompare(b.name)), [rooms.data]);
  const { rows, total } = usePaged(sorted, page);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <IncludeInactiveToggle value={includeInactive} onChange={setIncludeInactive} />
        {!showAdd && (
          <Button variant="outline" size="sm" onClick={() => setShowAdd(true)}>
            <Plus className="h-3.5 w-3.5" /> Add room
          </Button>
        )}
      </div>
      {showAdd && <AddRoomRow schoolId={schoolId} onCancel={() => setShowAdd(false)} />}

      {rooms.isLoading && <div className="h-32 animate-pulse rounded-2xl bg-elevated/60" />}
      {!rooms.isLoading && total === 0 && <EmptyState label="rooms" />}

      {total > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Capacity</TableHead>
              <TableHead>Status</TableHead>
              <TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="font-medium text-ink">{r.name}</TableCell>
                <TableCell>
                  <Badge variant="outline">{r.room_type}</Badge>
                </TableCell>
                <TableCell className="font-mono tabular-nums">{r.capacity}</TableCell>
                <TableCell>
                  <StatusBadge isActive={r.is_active} />
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1.5">
                    <EditRoomDialog schoolId={schoolId} room={r} />
                    {r.is_active ? (
                      <ConfirmDialog
                        trigger={
                          <DialogTrigger asChild>
                            <Button variant="outline" size="sm">
                              <PowerOff className="h-3.5 w-3.5" /> Deactivate
                            </Button>
                          </DialogTrigger>
                        }
                        title={`Deactivate ${r.name}?`}
                        description="Reversible - you can reactivate this room anytime. It will stop being offered as a valid room for new timetable generation runs while deactivated."
                        confirmLabel="Deactivate"
                        onConfirm={() => deactivate.mutate({ roomId: r.id, schoolId })}
                      />
                    ) : (
                      <Button variant="outline" size="sm" onClick={() => reactivate.mutate({ roomId: r.id, schoolId })} disabled={reactivate.isPending}>
                        <Power className="h-3.5 w-3.5" /> Reactivate
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Pagination page={page} setPage={setPage} total={total} />
    </div>
  );
}

// --- Teachers --------------------------------------------------------------------

function EditTeacherDialog({ schoolId, teacher }: { schoolId: number; teacher: TeacherOut }) {
  const [open, setOpen] = useState(false);
  const [fullName, setFullName] = useState(teacher.full_name ?? "");
  const [maxPeriods, setMaxPeriods] = useState(String(teacher.max_periods_per_week));
  const update = useUpdateTeacher();

  function handleSave() {
    update.mutate(
      { teacherId: teacher.id, schoolId, full_name: fullName, max_periods_per_week: Number(maxPeriods) || 1 },
      { onSuccess: () => setOpen(false) }
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Pencil className="h-3.5 w-3.5" /> Edit
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit teacher</DialogTitle>
          <DialogDescription>
            Qualified subjects and unavailability are managed inline in the table row (expand it) - real add/remove,
            not replaced by this form.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Full name">
            <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Max periods/week">
            <Input type="number" min={1} value={maxPeriods} onChange={(e) => setMaxPeriods(e.target.value)} className="max-w-28" />
          </Field>
          {update.isError && (
            <p className="text-sm text-urgent">{update.error instanceof ApiError ? update.error.message : "Failed to update teacher."}</p>
          )}
          <Button onClick={handleSave} disabled={update.isPending} className="self-start">
            {update.isPending ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function TeacherExpandedPanel({
  schoolId,
  teacher,
  subjectOptions,
}: {
  schoolId: number;
  teacher: TeacherOut;
  subjectOptions: { id: number; name: string }[];
}) {
  const addSubject = useAddTeacherSubject();
  const removeSubject = useRemoveTeacherSubject();
  const addUnavail = useAddTeacherUnavailability();
  const removeUnavail = useRemoveTeacherUnavailability();
  const [day, setDay] = useState("0");
  const [period, setPeriod] = useState("0");
  const [academicYear, setAcademicYear] = useState(DEFAULT_ACADEMIC_YEAR);

  function toggleSubject(subjectId: number) {
    if (teacher.subject_ids.includes(subjectId)) {
      removeSubject.mutate({ teacherId: teacher.id, subjectId, schoolId });
    } else {
      addSubject.mutate({ teacherId: teacher.id, subjectId, schoolId });
    }
  }

  return (
    <div className="flex flex-col gap-4 rounded-xl bg-elevated/40 p-4">
      <div>
        <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-ink-muted">Qualified subjects</span>
        <div className="flex flex-wrap gap-1.5">
          {subjectOptions.length === 0 && <p className="text-xs text-ink-muted">No subjects seeded for this school yet.</p>}
          {subjectOptions.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => toggleSubject(s.id)}
              className={`rounded-full border px-3 py-1 text-xs font-medium transition-colors ${
                teacher.subject_ids.includes(s.id)
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border bg-card text-ink-muted hover:border-border-strong"
              }`}
            >
              {s.name}
            </button>
          ))}
        </div>
      </div>

      <div>
        <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-ink-muted">Unavailability</span>
        <div className="flex flex-col gap-1.5">
          {teacher.unavailability.length === 0 && <p className="text-xs text-ink-muted">No unavailability exceptions - available every period.</p>}
          {teacher.unavailability.map((u) => (
            <div key={u.id} className="flex items-center justify-between rounded-lg bg-card px-3 py-1.5 text-xs">
              <span className="text-ink">
                {DAY_LABELS[u.day_of_week]} · Period {u.period_number} · {u.academic_year}
              </span>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2 text-[0.6875rem]"
                onClick={() => removeUnavail.mutate({ teacherId: teacher.id, unavailabilityId: u.id, schoolId })}
              >
                Remove
              </Button>
            </div>
          ))}
        </div>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <Field label="Day" className="w-28">
            <select
              value={day}
              onChange={(e) => setDay(e.target.value)}
              className="flex h-9 w-full items-center rounded-lg border border-border bg-card px-2.5 text-xs text-ink"
            >
              {DAY_LABELS.map((d, i) => (
                <option key={d} value={i}>
                  {d}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Period" className="w-20">
            <Input type="number" min={0} value={period} onChange={(e) => setPeriod(e.target.value)} className="h-9 text-xs" />
          </Field>
          <Field label="Academic year" className="w-28">
            <Input value={academicYear} onChange={(e) => setAcademicYear(e.target.value)} className="h-9 text-xs" />
          </Field>
          <Button
            size="sm"
            className="h-9"
            onClick={() =>
              addUnavail.mutate({ teacherId: teacher.id, schoolId, day_of_week: Number(day), period_number: Number(period), academic_year: academicYear })
            }
            disabled={addUnavail.isPending}
          >
            <Plus className="h-3.5 w-3.5" /> Add
          </Button>
        </div>
      </div>
    </div>
  );
}

function TeachersTab({ schoolId }: { schoolId: number }) {
  const [page, setPage] = useState(1);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const teachers = useTeachersAdmin(schoolId, includeInactive);
  const lookup = useReferenceLookup(schoolId);
  const allActive = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR });
  const deactivate = useDeactivateTeacher();
  const reactivate = useReactivateTeacher();

  const slotsByTeacher = useMemo(() => computeSlotsByTeacher(allActive.data ?? []), [allActive.data]);
  const subjectOptions = lookup.data?.subjects.map((s) => ({ id: s.id, name: s.name })) ?? [];
  const subjectName = (id: number) => lookup.data?.subjects.find((s) => s.id === id)?.name ?? `Subject #${id}`;

  const sorted = useMemo(
    () => [...(teachers.data ?? [])].sort((a, b) => (a.full_name ?? a.email).localeCompare(b.full_name ?? b.email)),
    [teachers.data]
  );
  const { rows, total } = usePaged(sorted, page);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <IncludeInactiveToggle value={includeInactive} onChange={setIncludeInactive} />
        <p className="text-xs text-ink-muted">New teachers are added via the onboarding wizard (real Supabase Auth account required).</p>
      </div>

      {teachers.isLoading && <div className="h-32 animate-pulse rounded-2xl bg-elevated/60" />}
      {!teachers.isLoading && total === 0 && <EmptyState label="teachers" />}

      {total > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead></TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Qualified subjects</TableHead>
              <TableHead>Hours</TableHead>
              <TableHead>Status</TableHead>
              <TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((t) => {
              const committed = slotsByTeacher.get(t.id) ?? 0;
              const overCap = committed > t.max_periods_per_week;
              const isExpanded = expandedId === t.id;
              return (
                <Fragment key={t.id}>
                  <TableRow>
                    <TableCell>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setExpandedId(isExpanded ? null : t.id)}>
                        {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRightIcon className="h-4 w-4" />}
                      </Button>
                    </TableCell>
                    <TableCell className="font-medium text-ink">{t.full_name ?? "—"}</TableCell>
                    <TableCell className="text-ink-muted">{t.email}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {t.subject_ids.length === 0 && <span className="text-xs text-ink-muted">None</span>}
                        {t.subject_ids.map((sid) => (
                          <Badge key={sid} variant="outline">
                            {subjectName(sid)}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={overCap ? "urgent" : "outline"}>
                        Committed: {committed}/{t.max_periods_per_week} hrs/wk
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <StatusBadge isActive={t.is_active} />
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1.5">
                        <EditTeacherDialog schoolId={schoolId} teacher={t} />
                        {t.is_active ? (
                          <ConfirmDialog
                            trigger={
                              <DialogTrigger asChild>
                                <Button variant="outline" size="sm">
                                  <PowerOff className="h-3.5 w-3.5" /> Deactivate
                                </Button>
                              </DialogTrigger>
                            }
                            title={`Deactivate ${t.full_name ?? t.email}?`}
                            description="Reversible - you can reactivate this teacher anytime. They will stop appearing as an eligible teacher in new timetable generation runs while deactivated."
                            confirmLabel="Deactivate"
                            onConfirm={() => deactivate.mutate({ teacherId: t.id, schoolId })}
                          />
                        ) : (
                          <Button variant="outline" size="sm" onClick={() => reactivate.mutate({ teacherId: t.id, schoolId })} disabled={reactivate.isPending}>
                            <Power className="h-3.5 w-3.5" /> Reactivate
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                  {isExpanded && (
                    <TableRow>
                      <TableCell colSpan={7} className="bg-elevated/20">
                        <TeacherExpandedPanel schoolId={schoolId} teacher={t} subjectOptions={subjectOptions} />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      )}
      <Pagination page={page} setPage={setPage} total={total} />
    </div>
  );
}

// --- Students --------------------------------------------------------------------

function EditStudentDialog({
  schoolId,
  student,
  classOptions,
}: {
  schoolId: number;
  student: StudentOut;
  classOptions: { id: number; label: string }[];
}) {
  const [open, setOpen] = useState(false);
  const [fullName, setFullName] = useState(student.full_name ?? "");
  const [classId, setClassId] = useState(student.class_id != null ? String(student.class_id) : "");
  const update = useUpdateStudent();

  function handleSave() {
    update.mutate(
      { studentId: student.id, schoolId, full_name: fullName, class_id: classId ? Number(classId) : undefined },
      { onSuccess: () => setOpen(false) }
    );
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Pencil className="h-3.5 w-3.5" /> Edit
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit student</DialogTitle>
          <DialogDescription>Changing class REPLACES the current enrollment - real, immediate.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Full name">
            <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Class">
            <Select value={classId} onValueChange={setClassId}>
              <SelectTrigger>
                <SelectValue placeholder="Not enrolled" />
              </SelectTrigger>
              <SelectContent>
                {classOptions.map((c) => (
                  <SelectItem key={c.id} value={String(c.id)}>
                    {c.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {update.isError && (
            <p className="text-sm text-urgent">{update.error instanceof ApiError ? update.error.message : "Failed to update student."}</p>
          )}
          <Button onClick={handleSave} disabled={update.isPending} className="self-start">
            {update.isPending ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function StudentsTab({ schoolId }: { schoolId: number }) {
  const [page, setPage] = useState(1);
  const [includeInactive, setIncludeInactive] = useState(false);
  const students = useStudentsAdmin(schoolId, includeInactive);
  const lookup = useReferenceLookup(schoolId);
  const deactivate = useDeactivateStudent();
  const reactivate = useReactivateStudent();

  const className = (id: number | null) => {
    if (id == null) return "Not enrolled";
    const c = lookup.data?.classes.find((x) => x.id === id);
    if (!c) return `Class #${id}`;
    return `${c.grade_label ?? `Grade ${c.grade_level ?? "?"}`}${c.section ? ` - ${c.section}` : ""}`;
  };
  const classOptions = (lookup.data?.classes ?? []).map((c) => ({
    id: c.id,
    label: `${c.grade_label ?? `Grade ${c.grade_level ?? "?"}`}${c.section ? ` - ${c.section}` : ""}`,
  }));

  const sorted = useMemo(
    () => [...(students.data ?? [])].sort((a, b) => (a.full_name ?? a.email).localeCompare(b.full_name ?? b.email)),
    [students.data]
  );
  const { rows, total } = usePaged(sorted, page);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <IncludeInactiveToggle value={includeInactive} onChange={setIncludeInactive} />
        <p className="text-xs text-ink-muted">New students are added via the onboarding wizard (real Supabase Auth account required).</p>
      </div>

      {students.isLoading && <div className="h-32 animate-pulse rounded-2xl bg-elevated/60" />}
      {!students.isLoading && total === 0 && <EmptyState label="students" />}

      {total > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Class</TableHead>
              <TableHead>Status</TableHead>
              <TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((s) => (
              <TableRow key={s.id}>
                <TableCell className="font-medium text-ink">{s.full_name ?? "—"}</TableCell>
                <TableCell className="text-ink-muted">{s.email}</TableCell>
                <TableCell className="text-ink-muted">{className(s.class_id)}</TableCell>
                <TableCell>
                  <StatusBadge isActive={s.is_active} />
                </TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1.5">
                    <EditStudentDialog schoolId={schoolId} student={s} classOptions={classOptions} />
                    {s.is_active ? (
                      <ConfirmDialog
                        trigger={
                          <DialogTrigger asChild>
                            <Button variant="outline" size="sm">
                              <PowerOff className="h-3.5 w-3.5" /> Deactivate
                            </Button>
                          </DialogTrigger>
                        }
                        title={`Deactivate ${s.full_name ?? s.email}?`}
                        description="Reversible - you can reactivate this student anytime."
                        confirmLabel="Deactivate"
                        onConfirm={() => deactivate.mutate({ studentId: s.id, schoolId })}
                      />
                    ) : (
                      <Button variant="outline" size="sm" onClick={() => reactivate.mutate({ studentId: s.id, schoolId })} disabled={reactivate.isPending}>
                        <Power className="h-3.5 w-3.5" /> Reactivate
                      </Button>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      <Pagination page={page} setPage={setPage} total={total} />
    </div>
  );
}

// --- Parents ---------------------------------------------------------------------

function EditParentDialog({ schoolId, parent }: { schoolId: number; parent: ParentOut }) {
  const [open, setOpen] = useState(false);
  const [fullName, setFullName] = useState(parent.full_name ?? "");
  const [phone, setPhone] = useState(parent.phone ?? "");
  const update = useUpdateParent();

  function handleSave() {
    update.mutate({ parentId: parent.id, schoolId, full_name: fullName, phone }, { onSuccess: () => setOpen(false) });
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          <Pencil className="h-3.5 w-3.5" /> Edit details
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit parent</DialogTitle>
          <DialogDescription>Linked children are managed inline in the table row (expand it).</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <Field label="Full name">
            <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Phone number">
            <Input type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="9876543210" />
          </Field>
          {update.isError && (
            <p className="text-sm text-urgent">{update.error instanceof ApiError ? update.error.message : "Failed to update parent."}</p>
          )}
          <Button onClick={handleSave} disabled={update.isPending} className="self-start">
            {update.isPending ? "Saving…" : "Save changes"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function ParentExpandedPanel({
  schoolId,
  parent,
  studentOptions,
}: {
  schoolId: number;
  parent: ParentOut;
  studentOptions: { id: number; name: string }[];
}) {
  const addChild = useAddParentChild();
  const removeChild = useRemoveParentChild();
  const unlinked = studentOptions.filter((s) => !parent.student_ids.includes(s.id));

  return (
    <div className="flex flex-col gap-3 rounded-xl bg-elevated/40 p-4">
      <div>
        <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-ink-muted">Linked children</span>
        <div className="flex flex-wrap gap-1.5">
          {parent.student_ids.length === 0 && <p className="text-xs text-ink-muted">No children linked yet.</p>}
          {parent.student_ids.map((sid) => (
            <span key={sid} className="flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1 text-xs text-ink">
              {studentOptions.find((s) => s.id === sid)?.name ?? `Student #${sid}`}
              <button
                type="button"
                onClick={() => removeChild.mutate({ parentId: parent.id, studentId: sid, schoolId })}
                className="text-ink-faint hover:text-urgent"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      </div>
      {unlinked.length > 0 && (
        <div>
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-ink-muted">Add a child</span>
          <div className="flex flex-wrap gap-1.5">
            {unlinked.map((s) => (
              <button
                key={s.id}
                type="button"
                onClick={() => addChild.mutate({ parentId: parent.id, studentId: s.id, schoolId })}
                className="rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-ink-muted transition-colors hover:border-accent hover:text-accent"
              >
                <Plus className="mr-1 inline h-3 w-3" />
                {s.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ParentsTab({ schoolId }: { schoolId: number }) {
  const [page, setPage] = useState(1);
  const [includeInactive, setIncludeInactive] = useState(false);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const parents = useParentsAdmin(schoolId, includeInactive);
  const students = useStudentsAdmin(schoolId);
  const deactivate = useDeactivateParent();
  const reactivate = useReactivateParent();

  const studentOptions = (students.data ?? []).map((s) => ({ id: s.id, name: s.full_name ?? s.email }));
  const studentName = (id: number) => studentOptions.find((s) => s.id === id)?.name ?? `Student #${id}`;

  const sorted = useMemo(
    () => [...(parents.data ?? [])].sort((a, b) => (a.full_name ?? a.email).localeCompare(b.full_name ?? b.email)),
    [parents.data]
  );
  const { rows, total } = usePaged(sorted, page);

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <IncludeInactiveToggle value={includeInactive} onChange={setIncludeInactive} />
        <p className="text-xs text-ink-muted">New parents are added via the onboarding wizard (real Supabase Auth account required).</p>
      </div>

      {parents.isLoading && <div className="h-32 animate-pulse rounded-2xl bg-elevated/60" />}
      {!parents.isLoading && total === 0 && <EmptyState label="parents" />}

      {total > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead></TableHead>
              <TableHead>Name</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Phone number</TableHead>
              <TableHead>Linked children</TableHead>
              <TableHead>Status</TableHead>
              <TableHead></TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((p) => {
              const isExpanded = expandedId === p.id;
              return (
                <Fragment key={p.id}>
                  <TableRow>
                    <TableCell>
                      <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => setExpandedId(isExpanded ? null : p.id)}>
                        {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRightIcon className="h-4 w-4" />}
                      </Button>
                    </TableCell>
                    <TableCell className="font-medium text-ink">{p.full_name ?? "—"}</TableCell>
                    <TableCell className="text-ink-muted">{p.email}</TableCell>
                    <TableCell className="text-ink-muted">{p.phone ?? "—"}</TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {p.student_ids.length === 0 && <span className="text-xs text-ink-muted">None</span>}
                        {p.student_ids.map((sid) => (
                          <Badge key={sid} variant="outline">
                            {studentName(sid)}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge isActive={p.is_active} />
                    </TableCell>
                    <TableCell>
                      <div className="flex justify-end gap-1.5">
                        <EditParentDialog schoolId={schoolId} parent={p} />
                        {p.is_active ? (
                          <ConfirmDialog
                            trigger={
                              <DialogTrigger asChild>
                                <Button variant="outline" size="sm">
                                  <PowerOff className="h-3.5 w-3.5" /> Deactivate
                                </Button>
                              </DialogTrigger>
                            }
                            title={`Deactivate ${p.full_name ?? p.email}?`}
                            description="Reversible - you can reactivate this parent anytime."
                            confirmLabel="Deactivate"
                            onConfirm={() => deactivate.mutate({ parentId: p.id, schoolId })}
                          />
                        ) : (
                          <Button variant="outline" size="sm" onClick={() => reactivate.mutate({ parentId: p.id, schoolId })} disabled={reactivate.isPending}>
                            <Power className="h-3.5 w-3.5" /> Reactivate
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                  {isExpanded && (
                    <TableRow>
                      <TableCell colSpan={7} className="bg-elevated/20">
                        <ParentExpandedPanel schoolId={schoolId} parent={p} studentOptions={studentOptions} />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
          </TableBody>
        </Table>
      )}
      <Pagination page={page} setPage={setPage} total={total} />
    </div>
  );
}

// --- Top-level page ----------------------------------------------------------------

export default function SchoolManagementPage() {
  const schoolId = useCurrentUser().data?.school_id;

  if (schoolId == null) {
    return <div className="h-40 animate-pulse rounded-2xl bg-elevated/60" />;
  }

  return (
    <div className="flex flex-col gap-3">
      <PageHeader
        title="School Management"
        description="Ongoing, day-to-day master-data management - view, edit, and deactivate what's already real in your school. For first-time setup, see the onboarding wizard instead."
      />
      <Tabs defaultValue="classes">
        <TabsList>
          <TabsTrigger value="classes">Classes</TabsTrigger>
          <TabsTrigger value="subjects">Subjects</TabsTrigger>
          <TabsTrigger value="rooms">Rooms</TabsTrigger>
          <TabsTrigger value="teachers">Teachers</TabsTrigger>
          <TabsTrigger value="students">Students</TabsTrigger>
          <TabsTrigger value="parents">Parents</TabsTrigger>
        </TabsList>
        <TabsContent value="classes">
          <ClassesTab schoolId={schoolId} />
        </TabsContent>
        <TabsContent value="subjects">
          <SubjectsTab schoolId={schoolId} />
        </TabsContent>
        <TabsContent value="rooms">
          <RoomsTab schoolId={schoolId} />
        </TabsContent>
        <TabsContent value="teachers">
          <TeachersTab schoolId={schoolId} />
        </TabsContent>
        <TabsContent value="students">
          <StudentsTab schoolId={schoolId} />
        </TabsContent>
        <TabsContent value="parents">
          <ParentsTab schoolId={schoolId} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
