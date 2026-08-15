import { useEffect, useMemo, useRef, useState } from "react";
import { AlertTriangle, CalendarPlus, ChevronDown, ChevronRight, Loader2, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import Field from "@/components/ui/field";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
  DialogClose,
} from "@/components/ui/dialog";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  useReferenceLookup,
  useGenerateTimetable,
  usePreflightCheck,
  useTimetableActive,
  computeSlotsByTeacher,
  type LookupResponse,
  type GenerateTimetableBody,
} from "@/api/hooks/useTimetable";
import { useCreateSubject } from "@/api/hooks/useMasterData";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { ApiError } from "@/api/client";
import type { Finding, PreflightResult } from "@/api/types";
import TimetableGrid from "@/components/timetable/TimetableGrid";
import { cn } from "@/lib/utils";
import { useDebouncedValue } from "@/lib/useDebouncedValue";

/** Small reusable enable/disable pill - this app has no dedicated Switch
 * primitive yet, and three call sites (subjects/teachers/rooms include toggles)
 * didn't justify adding one to components/ui for a single form. */
function Toggle({ on, onClick, label }: { on: boolean; onClick: () => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={on}
      onClick={onClick}
      className={cn(
        "inline-flex h-6 w-11 shrink-0 items-center rounded-full border p-0.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        on ? "border-accent bg-accent" : "border-border bg-elevated"
      )}
      aria-label={label}
    >
      <span
        className={cn(
          "h-5 w-5 rounded-full bg-card shadow-sm transition-transform",
          on ? "translate-x-5" : "translate-x-0"
        )}
      />
    </button>
  );
}

interface SubjectRow {
  included: boolean;
  periodsPerWeek: string;
  labRequired: boolean;
}

interface TeacherRow {
  included: boolean;
  overrideText: string;
}

interface CoreParams {
  academicYear: string;
  gradeLevels: number[];
  sectionsPerGrade: string;
  periodsPerDay: string;
  daysPerWeek: string;
}

function CoreParamsTab({
  core,
  setCore,
  availableGrades,
  sectionCountByGrade,
  gradeLabelByGrade,
}: {
  core: CoreParams;
  setCore: (patch: Partial<CoreParams>) => void;
  availableGrades: number[];
  sectionCountByGrade: Map<number, number>;
  gradeLabelByGrade: Map<number, string>;
}) {
  // One grade per generation run - sections_per_grade is a single number applied
  // to whichever grade is selected, so mixing grades with different seeded
  // section counts in one run would be ambiguous. Selecting a grade also
  // pre-fills the real seeded section count for it (still editable, e.g. to
  // generate for fewer than all of a grade's sections).
  function selectGrade(g: number) {
    if (core.gradeLevels.includes(g)) {
      setCore({ gradeLevels: [], sectionsPerGrade: "1" });
    } else {
      setCore({ gradeLevels: [g], sectionsPerGrade: String(sectionCountByGrade.get(g) ?? 1) });
    }
  }

  const selectedSections = core.gradeLevels.length ? sectionCountByGrade.get(core.gradeLevels[0]) : undefined;

  return (
    <div className="flex flex-col gap-4">
      <Field label="Academic year">
        <Input value={core.academicYear} onChange={(e) => setCore({ academicYear: e.target.value })} className="max-w-40" />
      </Field>

      <Field
        label="Grade level (one at a time)"
        hint={
          availableGrades.length === 0
            ? "No seeded classes have a resolvable grade level yet."
            : "Generate one grade per run - pick a different grade to switch."
        }
      >
        <div className="flex flex-wrap gap-1.5">
          {availableGrades.map((g) => (
            <button
              key={g}
              type="button"
              onClick={() => selectGrade(g)}
              className={cn(
                "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                core.gradeLevels.includes(g)
                  ? "border-accent bg-accent/10 text-accent"
                  : "border-border bg-card text-ink-muted hover:border-border-strong"
              )}
            >
              {gradeLabelByGrade.get(g) ?? `Grade ${g}`} <span className="text-ink-faint">({sectionCountByGrade.get(g) ?? 0} sec.)</span>
            </button>
          ))}
        </div>
      </Field>

      <Field
        label="Sections required (must already exist — create missing sections first)"
        hint={
          selectedSections !== undefined
            ? `Pre-filled from this grade's ${selectedSections} seeded section(s) - lower it to generate for fewer. Requesting more returns a 400 and never creates new sections.`
            : "Select a grade level first."
        }
      >
        <Input
          type="number"
          min={1}
          value={core.sectionsPerGrade}
          onChange={(e) => setCore({ sectionsPerGrade: e.target.value })}
          className="max-w-28"
        />
      </Field>

      <div className="grid grid-cols-2 gap-3 max-w-sm">
        <Field label="Periods per day">
          <Input type="number" min={1} value={core.periodsPerDay} onChange={(e) => setCore({ periodsPerDay: e.target.value })} />
        </Field>
        <Field label="Days per week">
          <Input type="number" min={1} max={7} value={core.daysPerWeek} onChange={(e) => setCore({ daysPerWeek: e.target.value })} />
        </Field>
      </div>
    </div>
  );
}

function AddSubjectForm({
  schoolId,
  onCreated,
  onCancel,
}: {
  schoolId: number;
  onCreated: (subject: { id: number }, periodsPerWeek: string, labRequired: boolean) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [periodsPerWeek, setPeriodsPerWeek] = useState("3");
  const [labRequired, setLabRequired] = useState(false);
  const createSubject = useCreateSubject();

  function handleSave() {
    if (!name.trim()) return;
    createSubject.mutate(
      { school_id: schoolId, name: name.trim(), periods_per_week: Number(periodsPerWeek) || 3, lab_required: labRequired },
      { onSuccess: (subject) => onCreated(subject, periodsPerWeek, labRequired) }
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-accent/30 bg-accent/5 px-3.5 py-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold uppercase tracking-wide text-accent">New subject</span>
        <Button variant="ghost" size="icon" className="h-6 w-6" onClick={onCancel}>
          <X className="h-3.5 w-3.5" />
        </Button>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Name" className="w-40">
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Sanskrit" autoFocus />
        </Field>
        <Field label="Periods/wk" className="w-24">
          <Input type="number" min={1} value={periodsPerWeek} onChange={(e) => setPeriodsPerWeek(e.target.value)} />
        </Field>
        <label className="flex items-center gap-1.5 pb-2 text-xs font-medium text-ink-muted">
          <input
            type="checkbox"
            checked={labRequired}
            onChange={(e) => setLabRequired(e.target.checked)}
            className="h-3.5 w-3.5 rounded border-border accent-accent"
          />
          Lab required
        </label>
        <Button size="sm" onClick={handleSave} disabled={!name.trim() || createSubject.isPending}>
          {createSubject.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Create subject"}
        </Button>
      </div>
      {createSubject.isError && (
        <p className="text-xs text-urgent">
          {createSubject.error instanceof ApiError ? createSubject.error.message : "Failed to create subject."}
        </p>
      )}
    </div>
  );
}

function SubjectsTab({
  schoolId,
  lookup,
  subjects,
  setSubject,
}: {
  schoolId: number;
  lookup: LookupResponse;
  subjects: Record<number, SubjectRow>;
  setSubject: (id: number, patch: Partial<SubjectRow>) => void;
}) {
  const [showAdd, setShowAdd] = useState(false);

  return (
    <div className="flex flex-col gap-2">
      {showAdd ? (
        <AddSubjectForm
          schoolId={schoolId}
          onCancel={() => setShowAdd(false)}
          onCreated={(subject, periodsPerWeek, labRequired) => {
            setSubject(subject.id, { included: true, periodsPerWeek, labRequired });
            setShowAdd(false);
          }}
        />
      ) : (
        <Button variant="outline" size="sm" className="self-start" onClick={() => setShowAdd(true)}>
          <Plus className="h-3.5 w-3.5" /> Add new subject
        </Button>
      )}

      {lookup.subjects.length === 0 && !showAdd && (
        <p className="text-sm text-ink-muted">No subjects seeded for this school.</p>
      )}

      {lookup.subjects.map((s) => {
        const row = subjects[s.id] ?? { included: false, periodsPerWeek: "3", labRequired: false };
        return (
          <div key={s.id} className="flex items-center gap-3 rounded-xl border border-border bg-elevated/40 px-3.5 py-2.5">
            <Toggle on={row.included} onClick={() => setSubject(s.id, { included: !row.included })} label={`Include ${s.name}`} />
            <span className="w-32 shrink-0 truncate text-sm font-medium text-ink">{s.name}</span>
            {row.included && (
              <>
                <Field label="Periods/wk" className="w-24">
                  <Input
                    type="number"
                    min={1}
                    value={row.periodsPerWeek}
                    onChange={(e) => setSubject(s.id, { periodsPerWeek: e.target.value })}
                  />
                </Field>
                <label className="flex items-center gap-1.5 text-xs font-medium text-ink-muted">
                  <input
                    type="checkbox"
                    checked={row.labRequired}
                    onChange={(e) => setSubject(s.id, { labRequired: e.target.checked })}
                    className="h-3.5 w-3.5 rounded border-border accent-accent"
                  />
                  Lab required
                </label>
              </>
            )}
          </div>
        );
      })}
    </div>
  );
}

function TeachersTab({
  lookup,
  teachers,
  setTeacher,
  slotsByTeacher,
  uncappedFallback,
}: {
  lookup: LookupResponse;
  teachers: Record<number, TeacherRow>;
  setTeacher: (id: number, patch: Partial<TeacherRow>) => void;
  slotsByTeacher: Map<number, number>;
  uncappedFallback: number;
}) {
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const expandedSlots = useTimetableActive({
    academicYear: DEFAULT_ACADEMIC_YEAR,
    teacherId: expandedId ?? undefined,
    enabled: expandedId !== null,
  });

  if (lookup.teachers.length === 0) {
    return <p className="text-sm text-ink-muted">No teachers seeded for this school.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      {lookup.teachers.map((t) => {
        const row = teachers[t.id] ?? { included: false, overrideText: "" };
        const committed = slotsByTeacher.get(t.id) ?? 0;
        const cap = row.overrideText ? Number(row.overrideText) : t.max_periods_per_week ?? uncappedFallback;
        const isExpanded = expandedId === t.id;
        const overCap = committed > cap;

        return (
          <div key={t.id} className="rounded-xl border border-border bg-elevated/40">
            <div className="flex items-center gap-3 px-3.5 py-2.5">
              <Toggle on={row.included} onClick={() => setTeacher(t.id, { included: !row.included })} label={`Include ${t.name}`} />
              <button
                type="button"
                onClick={() => setExpandedId(isExpanded ? null : t.id)}
                className="flex flex-1 items-center gap-1.5 text-left text-sm font-medium text-ink hover:text-accent"
              >
                {isExpanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
                {t.name}
              </button>
              <Badge variant={overCap ? "urgent" : "outline"}>
                Committed: {committed}/{cap} hrs/wk
              </Badge>
              <Field label="Cap override" className="w-28">
                <Input
                  type="number"
                  min={0}
                  placeholder={t.max_periods_per_week != null ? String(t.max_periods_per_week) : "uncapped"}
                  value={row.overrideText}
                  onChange={(e) => setTeacher(t.id, { overrideText: e.target.value })}
                />
              </Field>
            </div>
            {isExpanded && (
              <div className="border-t border-border px-3.5 py-3">
                <p className="mb-2 text-xs text-ink-muted">
                  {t.name}'s real current active schedule for {DEFAULT_ACADEMIC_YEAR} (read-only here).
                </p>
                {expandedSlots.isLoading ? (
                  <div className="h-24 animate-pulse rounded-lg bg-elevated/60" />
                ) : (
                  <TimetableGrid slots={expandedSlots.data ?? []} lookup={lookup} showClass editable={false} />
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

function RoomsTab({
  lookup,
  roomIds,
  toggleRoom,
  anyLabRequired,
}: {
  lookup: LookupResponse;
  roomIds: Set<number>;
  toggleRoom: (id: number) => void;
  anyLabRequired: boolean;
}) {
  const labSelected = lookup.rooms.some((r) => roomIds.has(r.id) && r.room_type === "lab");

  if (lookup.rooms.length === 0) {
    return <p className="text-sm text-ink-muted">No rooms seeded for this school.</p>;
  }

  return (
    <div className="flex flex-col gap-2">
      {anyLabRequired && !labSelected && (
        <div className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/5 px-3.5 py-2.5 text-sm text-warning">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <span>A selected subject requires a lab, but no lab room is selected below - this run would return a 422.</span>
        </div>
      )}
      {lookup.rooms.map((r) => (
        <div key={r.id} className="flex items-center gap-3 rounded-xl border border-border bg-elevated/40 px-3.5 py-2.5">
          <Toggle on={roomIds.has(r.id)} onClick={() => toggleRoom(r.id)} label={`Include ${r.name}`} />
          <span className="flex-1 text-sm font-medium text-ink">{r.name}</span>
          <Badge variant={r.room_type === "lab" ? "accent" : "outline"}>{r.room_type}</Badge>
        </div>
      ))}
    </div>
  );
}

/** Renders pre-flight/solve findings - errors red, warnings amber, each with
 * its numbers and remedies. Reused for the live pre-flight panel, a failed
 * Generate's structured error, and a successful Generate's warning-severity
 * findings, so the three cases render identically. */
function FindingsList({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) return null;
  return (
    <div className="flex flex-col gap-2">
      {findings.map((f, i) => {
        const isError = f.severity === "error";
        return (
          <div
            key={i}
            className={cn(
              "flex flex-col gap-1 rounded-xl border px-3.5 py-2.5",
              isError ? "border-urgent/30 bg-urgent/5" : "border-warning/30 bg-warning/5"
            )}
          >
            <p className={cn("text-sm font-medium", isError ? "text-urgent" : "text-warning")}>{f.message}</p>
            {Object.keys(f.numbers).length > 0 && (
              <p className="font-mono text-[0.6875rem] text-ink-faint">
                {Object.entries(f.numbers)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(" · ")}
              </p>
            )}
            {f.remedies.length > 0 && (
              <ul className="ml-4 list-disc text-xs text-ink-muted">
                {f.remedies.map((r, j) => (
                  <li key={j}>{r.detail}</li>
                ))}
              </ul>
            )}
          </div>
        );
      })}
    </div>
  );
}

/** Parses a failed Generate's structured 422 body (PreflightResult-shaped)
 * out of an ApiError, falling back to null for any other error shape (e.g. a
 * plain-string 400/403) - those still render via the plain message path. */
function preflightResultFromError(error: unknown): PreflightResult | null {
  if (!(error instanceof ApiError) || typeof error.body !== "object" || error.body === null) return null;
  const detail = (error.body as { detail?: unknown }).detail;
  if (typeof detail !== "object" || detail === null || !("findings" in detail)) return null;
  return detail as PreflightResult;
}

export default function GenerateTimetableForm({ schoolId }: { schoolId: number }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState("core");
  const lookup = useReferenceLookup(schoolId);
  const allActive = useTimetableActive({ academicYear: DEFAULT_ACADEMIC_YEAR, enabled: open });
  const generate = useGenerateTimetable();
  const seededRef = useRef(false);

  const [core, setCoreState] = useState<CoreParams>({
    academicYear: DEFAULT_ACADEMIC_YEAR,
    gradeLevels: [],
    sectionsPerGrade: "1",
    periodsPerDay: "6",
    daysPerWeek: "5",
  });
  const [subjects, setSubjects] = useState<Record<number, SubjectRow>>({});
  const [teachers, setTeachers] = useState<Record<number, TeacherRow>>({});
  const [roomIds, setRoomIds] = useState<Set<number>>(new Set());

  function setCore(patch: Partial<CoreParams>) {
    setCoreState((prev) => ({ ...prev, ...patch }));
  }
  function setSubject(id: number, patch: Partial<SubjectRow>) {
    setSubjects((prev) => ({ ...prev, [id]: { ...(prev[id] ?? { included: false, periodsPerWeek: "3", labRequired: false }), ...patch } }));
  }
  function setTeacher(id: number, patch: Partial<TeacherRow>) {
    setTeachers((prev) => ({ ...prev, [id]: { ...(prev[id] ?? { included: false, overrideText: "" }), ...patch } }));
  }
  function toggleRoom(id: number) {
    setRoomIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  // Seed sensible one-time defaults once lookup data arrives: no subjects
  // pre-included (an admin must deliberately pick what this run schedules),
  // but a teacher qualified for at least one already-included subject defaults
  // to included - this only runs once per dialog open, further toggles are
  // never overwritten by it.
  useEffect(() => {
    if (!lookup.data || seededRef.current) return;
    seededRef.current = true;
    setTeachers(
      Object.fromEntries(lookup.data.teachers.map((t) => [t.id, { included: false, overrideText: "" }]))
    );
    // periodsPerWeek/labRequired default from each subject's real, persisted
    // master-data value (School Management's Subjects tab) instead of an
    // arbitrary hardcoded "3"/false - still fully editable per run below.
    setSubjects(
      Object.fromEntries(
        lookup.data.subjects.map((s) => [
          s.id,
          { included: false, periodsPerWeek: String(s.periods_per_week), labRequired: s.lab_required },
        ])
      )
    );
    setRoomIds(new Set());
  }, [lookup.data]);

  useEffect(() => {
    if (!open) {
      seededRef.current = false;
      setTab("core");
      generate.reset();
    }
  }, [open]); // eslint-disable-line react-hooks/exhaustive-deps

  const availableGrades = useMemo(() => {
    const set = new Set<number>();
    for (const c of lookup.data?.classes ?? []) if (c.grade_level != null) set.add(c.grade_level);
    return Array.from(set).sort((a, b) => a - b);
  }, [lookup.data]);

  const sectionCountByGrade = useMemo(() => {
    const map = new Map<number, number>();
    for (const c of lookup.data?.classes ?? []) {
      if (c.grade_level == null) continue;
      map.set(c.grade_level, (map.get(c.grade_level) ?? 0) + 1);
    }
    return map;
  }, [lookup.data]);

  const gradeLabelByGrade = useMemo(() => {
    const map = new Map<number, string>();
    for (const c of lookup.data?.classes ?? []) {
      if (c.grade_level == null || !c.grade_label || map.has(c.grade_level)) continue;
      map.set(c.grade_level, c.grade_label);
    }
    return map;
  }, [lookup.data]);

  const slotsByTeacher = useMemo(() => computeSlotsByTeacher(allActive.data ?? []), [allActive.data]);

  const includedSubjects = Object.entries(subjects)
    .filter(([, r]) => r.included)
    .map(([id, r]) => ({ id: Number(id), periodsPerWeek: Number(r.periodsPerWeek) || 0, labRequired: r.labRequired }));
  const includedTeachers = Object.entries(teachers).filter(([, r]) => r.included);
  const anyLabRequired = includedSubjects.some((s) => s.labRequired);

  const daysPerWeek = Number(core.daysPerWeek) || 5;
  const periodsPerDay = Number(core.periodsPerDay) || 6;
  const uncappedFallback = daysPerWeek * periodsPerDay;
  const sectionsPerGrade = Number(core.sectionsPerGrade) || 0;

  const estimatedClassCount = core.gradeLevels.length * sectionsPerGrade;
  const requiredPeriods = estimatedClassCount * includedSubjects.reduce((sum, s) => sum + s.periodsPerWeek, 0);
  const availableCapacity = includedTeachers.reduce((sum, [id]) => {
    const t = lookup.data?.teachers.find((x) => x.id === Number(id));
    const row = teachers[Number(id)];
    const cap = row?.overrideText ? Number(row.overrideText) : t?.max_periods_per_week ?? uncappedFallback;
    const committed = slotsByTeacher.get(Number(id)) ?? 0;
    return sum + Math.max(0, cap - committed);
  }, 0);

  const canSubmit =
    core.gradeLevels.length > 0 &&
    sectionsPerGrade >= 1 &&
    includedSubjects.length > 0 &&
    includedSubjects.every((s) => s.periodsPerWeek >= 1) &&
    includedTeachers.length > 0 &&
    roomIds.size > 0;

  // Built whenever the form is well-formed enough for the backend to accept
  // it (same prerequisites as canSubmit) - shared by the live pre-flight
  // check below and the real Generate submit, so they can never disagree
  // about what the request actually is.
  const requestBody: GenerateTimetableBody | null = canSubmit
    ? {
        school_id: schoolId,
        academic_year: core.academicYear,
        grade_levels: core.gradeLevels,
        sections_per_grade: sectionsPerGrade,
        periods_per_day: periodsPerDay,
        days_per_week: daysPerWeek,
        subjects: includedSubjects.map((s) => ({
          subject_id: s.id,
          periods_per_week: s.periodsPerWeek,
          lab_required: s.labRequired,
        })),
        teacher_selections: includedTeachers.map(([id]) => {
          const row = teachers[Number(id)];
          return {
            teacher_id: Number(id),
            included: true,
            max_periods_per_week_override: row.overrideText ? Number(row.overrideText) : null,
          };
        }),
        room_ids: Array.from(roomIds),
      }
    : null;

  const debouncedBody = useDebouncedValue(requestBody, 500);
  const preflight = usePreflightCheck(open ? debouncedBody : null);
  const preflightBlocked = preflight.data?.feasible === false;

  function handleSubmit() {
    if (!requestBody) return;
    generate.mutate(requestBody);
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <CalendarPlus className="h-4 w-4" /> Generate timetable
        </Button>
      </DialogTrigger>
      <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Generate timetable</DialogTitle>
          <DialogDescription>
            Real input for one generation run - built fresh from real teacher/room/subject master data plus your selections
            below. This is a superseding run: existing active slots for the resolved classes/academic year are replaced, not
            stacked on top of.
          </DialogDescription>
        </DialogHeader>

        {lookup.isLoading ? (
          <div className="h-64 animate-pulse rounded-lg bg-elevated/60" />
        ) : (
          <>
            <Tabs value={tab} onValueChange={setTab}>
              <TabsList>
                <TabsTrigger value="core">Core Params</TabsTrigger>
                <TabsTrigger value="subjects">
                  Subjects{includedSubjects.length > 0 && <Badge variant="accent" className="ml-1.5">{includedSubjects.length}</Badge>}
                </TabsTrigger>
                <TabsTrigger value="teachers">
                  Teachers{includedTeachers.length > 0 && <Badge variant="accent" className="ml-1.5">{includedTeachers.length}</Badge>}
                </TabsTrigger>
                <TabsTrigger value="rooms">
                  Rooms{roomIds.size > 0 && <Badge variant="accent" className="ml-1.5">{roomIds.size}</Badge>}
                </TabsTrigger>
              </TabsList>

              <TabsContent value="core">
                <CoreParamsTab
                  core={core}
                  setCore={setCore}
                  availableGrades={availableGrades}
                  sectionCountByGrade={sectionCountByGrade}
                  gradeLabelByGrade={gradeLabelByGrade}
                />
              </TabsContent>
              <TabsContent value="subjects">
                {lookup.data && <SubjectsTab schoolId={schoolId} lookup={lookup.data} subjects={subjects} setSubject={setSubject} />}
              </TabsContent>
              <TabsContent value="teachers">
                {lookup.data && (
                  <TeachersTab
                    lookup={lookup.data}
                    teachers={teachers}
                    setTeacher={setTeacher}
                    slotsByTeacher={slotsByTeacher}
                    uncappedFallback={uncappedFallback}
                  />
                )}
              </TabsContent>
              <TabsContent value="rooms">
                {lookup.data && <RoomsTab lookup={lookup.data} roomIds={roomIds} toggleRoom={toggleRoom} anyLabRequired={anyLabRequired} />}
              </TabsContent>
            </Tabs>

            <div className="mt-4 flex flex-col gap-3 border-t border-border pt-3">
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink-muted">
                <span>
                  ~<span className="font-mono text-ink">{estimatedClassCount}</span> class(es) resolved (estimate)
                </span>
                <span>
                  Required periods: <span className="font-mono text-ink">{requiredPeriods}</span>
                </span>
                <span>
                  Selected teachers' capacity: <span className="font-mono text-ink">{availableCapacity}</span>
                </span>
                {canSubmit && (
                  <Badge
                    variant={preflight.isFetching ? "outline" : preflight.data?.feasible ? "positive" : "urgent"}
                  >
                    {preflight.isFetching
                      ? "Checking…"
                      : preflight.data?.feasible
                        ? "Pre-flight checks passed"
                        : preflight.data
                          ? "Pre-flight checks failed"
                          : "Checking…"}
                  </Badge>
                )}
              </div>

              {canSubmit && preflight.data && preflight.data.findings.length > 0 && (
                <FindingsList findings={preflight.data.findings} />
              )}

              {generate.isError &&
                (() => {
                  const structured = preflightResultFromError(generate.error);
                  return structured ? (
                    <FindingsList findings={structured.findings} />
                  ) : (
                    <p className="text-sm text-urgent">
                      {generate.error instanceof ApiError ? generate.error.message : "Failed to generate timetable."}
                    </p>
                  );
                })()}
              {generate.isSuccess && (
                <div className="flex flex-col gap-1.5">
                  <p className="text-sm text-positive">
                    Done - {generate.data.slots_created} slot(s) created for {generate.data.academic_year}.
                  </p>
                  {generate.data.warnings.length > 0 && (
                    <div className="flex flex-col gap-1 rounded-xl border border-warning/30 bg-warning/5 px-3.5 py-2.5">
                      {generate.data.warnings.map((w, i) => (
                        <p key={i} className="text-xs text-warning">
                          {w}
                        </p>
                      ))}
                    </div>
                  )}
                  {generate.data.findings.length > 0 && <FindingsList findings={generate.data.findings} />}
                  <p className="font-mono text-[0.6875rem] text-ink-faint">
                    Same-day clustering: {generate.data.objective_values.same_day_clustering} (weight{" "}
                    {generate.data.objective_weights.same_day_clustering}) · Day-to-day spread:{" "}
                    {generate.data.objective_values.day_variance} (weight {generate.data.objective_weights.day_variance})
                  </p>
                </div>
              )}

              <div className="flex gap-2">
                <Button onClick={handleSubmit} disabled={!canSubmit || preflightBlocked || generate.isPending}>
                  {generate.isPending ? (
                    <>
                      <Loader2 className="h-4 w-4 animate-spin" /> Generating…
                    </>
                  ) : (
                    "Generate"
                  )}
                </Button>
                <DialogClose asChild>
                  <Button variant="ghost">{generate.isSuccess ? "Close" : "Cancel"}</Button>
                </DialogClose>
              </div>
              {!canSubmit && !generate.isPending && (
                <p className="text-xs text-ink-faint">
                  Needs at least: 1 grade level, sections/grade ≥ 1, 1 included subject with periods/wk ≥ 1, 1 included teacher, 1 room.
                </p>
              )}
            </div>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
