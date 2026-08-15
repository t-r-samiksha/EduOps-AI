import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { GraduationCap, Loader2, Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import Field from "@/components/ui/field";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import PageHeader from "@/components/shared/PageHeader";
import { ApiError } from "@/api/client";
import { useCurrentUser } from "@/api/hooks/useAuth";
import { useReferenceLookup, type LookupResponse } from "@/api/hooks/useTimetable";
import {
  useSchool,
  useUpdateSchool,
  useCreateClass,
  useCreateSubject,
  useCreateRoom,
  useCreateTeacher,
  useCreateStudent,
  useCreateParent,
} from "@/api/hooks/useMasterData";
import { DEFAULT_ACADEMIC_YEAR } from "@/lib/constants";
import { cn } from "@/lib/utils";

const STEP_KEYS = ["school", "classes", "subjects", "rooms", "teachers", "students", "parents", "review"] as const;
type StepKey = (typeof STEP_KEYS)[number];
const STEP_LABELS: Record<StepKey, string> = {
  school: "School",
  classes: "Classes",
  subjects: "Subjects",
  rooms: "Rooms",
  teachers: "Teachers",
  students: "Students",
  parents: "Parents",
  review: "Review",
};

const STORAGE_KEY = "eduops-onboarding-step";

function ExistingList({ items, empty }: { items: { id: number; label: string }[]; empty: string }) {
  if (items.length === 0) return <p className="text-sm text-ink-muted">{empty}</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item) => (
        <Badge key={item.id} variant="outline">
          {item.label}
        </Badge>
      ))}
    </div>
  );
}

// --- Step: School --------------------------------------------------------------

function StepSchool({ schoolId, onContinue }: { schoolId: number; onContinue: () => void }) {
  const school = useSchool(schoolId);
  const updateSchool = useUpdateSchool();
  const [address, setAddress] = useState("");

  useEffect(() => {
    if (school.data?.address) setAddress(school.data.address);
  }, [school.data?.address]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your school</CardTitle>
        <CardDescription>Created when you signed up - already real, nothing to redo here.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {school.isLoading ? (
          <div className="h-16 animate-pulse rounded-lg bg-elevated/60" />
        ) : (
          <>
            <Field label="School name">
              <Input value={school.data?.name ?? ""} disabled />
            </Field>
            <Field label="Address (optional)">
              <Input value={address} onChange={(e) => setAddress(e.target.value)} placeholder="Not set yet" />
            </Field>
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() => updateSchool.mutate({ schoolId, address })}
                disabled={updateSchool.isPending}
              >
                {updateSchool.isPending ? "Saving…" : "Save address"}
              </Button>
              <Button onClick={onContinue}>Continue</Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// --- Step: Classes ---------------------------------------------------------------

function StepClasses({ schoolId, lookup, onContinue }: { schoolId: number; lookup: LookupResponse | undefined; onContinue: () => void }) {
  const createClass = useCreateClass();
  const [gradeLevel, setGradeLevel] = useState("");
  const [gradeLabel, setGradeLabel] = useState("");
  const [section, setSection] = useState("");
  const [academicYear, setAcademicYear] = useState(DEFAULT_ACADEMIC_YEAR);

  function handleAdd() {
    const level = Number(gradeLevel);
    if (!level && level !== 0) return;
    const label = gradeLabel.trim() || undefined;
    const name = `${label || `Grade ${level}`}${section ? ` - ${section}` : ""}`;
    createClass.mutate(
      { school_id: schoolId, name, academic_year: academicYear, grade_level: level, grade_label: label, section: section || undefined },
      { onSuccess: () => { setGradeLevel(""); setGradeLabel(""); setSection(""); } }
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Classes</CardTitle>
        <CardDescription>Real classes, created directly - not a template. Add as many as you need.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-ink-muted">Already created</span>
          <ExistingList items={(lookup?.classes ?? []).map((c) => ({ id: c.id, label: c.name }))} empty="None yet." />
        </div>
        <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-elevated/40 px-3.5 py-3">
          <Field label="Grade level (number)" className="w-36" hint="Nursery=-3, LKG=-2, UKG=-1, Grade 1=1...">
            <Input type="number" value={gradeLevel} onChange={(e) => setGradeLevel(e.target.value)} />
          </Field>
          <Field label="Label (optional)" className="w-28">
            <Input value={gradeLabel} onChange={(e) => setGradeLabel(e.target.value)} placeholder="e.g. LKG" />
          </Field>
          <Field label="Section" className="w-24">
            <Input value={section} onChange={(e) => setSection(e.target.value)} placeholder="A" />
          </Field>
          <Field label="Academic year" className="w-32">
            <Input value={academicYear} onChange={(e) => setAcademicYear(e.target.value)} />
          </Field>
          <Button onClick={handleAdd} disabled={!gradeLevel || createClass.isPending}>
            {createClass.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add class
          </Button>
        </div>
        {createClass.isError && (
          <p className="text-sm text-urgent">{createClass.error instanceof ApiError ? createClass.error.message : "Failed to create class."}</p>
        )}
        <Button variant="ghost" className="self-start" onClick={onContinue}>
          Continue
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Step: Subjects --------------------------------------------------------------

function StepSubjects({ schoolId, lookup, onContinue }: { schoolId: number; lookup: LookupResponse | undefined; onContinue: () => void }) {
  const createSubject = useCreateSubject();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");

  function handleAdd() {
    if (!name.trim()) return;
    createSubject.mutate(
      { school_id: schoolId, name: name.trim(), code: code.trim() || undefined },
      { onSuccess: () => { setName(""); setCode(""); } }
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Subjects</CardTitle>
        <CardDescription>
          Just name + an optional short code - periods/week and lab requirements are set per timetable generation run, not stored here.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-ink-muted">Already created</span>
          <ExistingList items={(lookup?.subjects ?? []).map((s) => ({ id: s.id, label: s.name }))} empty="None yet." />
        </div>
        <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-elevated/40 px-3.5 py-3">
          <Field label="Name" className="w-48">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Math" />
          </Field>
          <Field label="Code (optional)" className="w-28">
            <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="MTH" />
          </Field>
          <Button onClick={handleAdd} disabled={!name.trim() || createSubject.isPending}>
            {createSubject.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add subject
          </Button>
        </div>
        {createSubject.isError && (
          <p className="text-sm text-urgent">{createSubject.error instanceof ApiError ? createSubject.error.message : "Failed to create subject."}</p>
        )}
        <Button variant="ghost" className="self-start" onClick={onContinue}>
          Continue
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Step: Rooms -------------------------------------------------------------------

function StepRooms({ schoolId, lookup, onContinue }: { schoolId: number; lookup: LookupResponse | undefined; onContinue: () => void }) {
  const createRoom = useCreateRoom();
  const [name, setName] = useState("");
  const [capacity, setCapacity] = useState("30");
  const [roomType, setRoomType] = useState("classroom");

  function handleAdd() {
    if (!name.trim()) return;
    createRoom.mutate(
      { school_id: schoolId, name: name.trim(), capacity: Number(capacity) || 30, room_type: roomType },
      { onSuccess: () => setName("") }
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Rooms</CardTitle>
        <CardDescription>Classrooms, labs, whatever your real space plan is.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-ink-muted">Already created</span>
          <ExistingList items={(lookup?.rooms ?? []).map((r) => ({ id: r.id, label: `${r.name} (${r.room_type})` }))} empty="None yet." />
        </div>
        <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-elevated/40 px-3.5 py-3">
          <Field label="Name" className="w-40">
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Room 101" />
          </Field>
          <Field label="Capacity" className="w-24">
            <Input type="number" value={capacity} onChange={(e) => setCapacity(e.target.value)} />
          </Field>
          <Field label="Type" className="w-32">
            <select
              value={roomType}
              onChange={(e) => setRoomType(e.target.value)}
              className="h-10 w-full rounded-xl border border-border bg-card px-3.5 text-sm text-ink shadow-sm"
            >
              <option value="classroom">classroom</option>
              <option value="lab">lab</option>
              <option value="auditorium">auditorium</option>
            </select>
          </Field>
          <Button onClick={handleAdd} disabled={!name.trim() || createRoom.isPending}>
            {createRoom.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add room
          </Button>
        </div>
        {createRoom.isError && (
          <p className="text-sm text-urgent">{createRoom.error instanceof ApiError ? createRoom.error.message : "Failed to create room."}</p>
        )}
        <Button variant="ghost" className="self-start" onClick={onContinue}>
          Continue
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Step: Teachers ----------------------------------------------------------------

function StepTeachers({ schoolId, lookup, onContinue }: { schoolId: number; lookup: LookupResponse | undefined; onContinue: () => void }) {
  const createTeacher = useCreateTeacher();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [maxPeriods, setMaxPeriods] = useState("24");
  const [subjectIds, setSubjectIds] = useState<Set<number>>(new Set());

  function toggleSubject(id: number) {
    setSubjectIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleAdd() {
    if (!email.trim() || password.length < 8) return;
    createTeacher.mutate(
      {
        school_id: schoolId, email: email.trim(), password, full_name: fullName.trim() || undefined,
        max_periods_per_week: Number(maxPeriods) || undefined, subject_ids: Array.from(subjectIds),
      },
      { onSuccess: () => { setFullName(""); setEmail(""); setPassword(""); setSubjectIds(new Set()); } }
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Teachers</CardTitle>
        <CardDescription>Each one gets a real, login-capable account immediately - same as your own signup.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-ink-muted">Already created</span>
          <ExistingList items={(lookup?.teachers ?? []).map((t) => ({ id: t.id, label: t.name }))} empty="None yet." />
        </div>
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-elevated/40 px-3.5 py-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Full name" className="w-44">
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </Field>
            <Field label="Email" className="w-56">
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Password" className="w-40" hint="At least 8 characters">
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
            <Field label="Max periods/wk" className="w-32">
              <Input type="number" value={maxPeriods} onChange={(e) => setMaxPeriods(e.target.value)} />
            </Field>
          </div>
          {lookup && lookup.subjects.length > 0 && (
            <div>
              <span className="mb-1 block text-xs font-medium text-ink-muted">Qualified subjects</span>
              <div className="flex flex-wrap gap-2">
                {lookup.subjects.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => toggleSubject(s.id)}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                      subjectIds.has(s.id) ? "border-accent bg-accent/10 text-accent" : "border-border bg-card text-ink-muted"
                    )}
                  >
                    {s.name}
                  </button>
                ))}
              </div>
            </div>
          )}
          <Button onClick={handleAdd} disabled={!email.trim() || password.length < 8 || createTeacher.isPending} className="self-start">
            {createTeacher.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add teacher
          </Button>
        </div>
        {createTeacher.isError && (
          <p className="text-sm text-urgent">{createTeacher.error instanceof ApiError ? createTeacher.error.message : "Failed to create teacher."}</p>
        )}
        <Button variant="ghost" className="self-start" onClick={onContinue}>
          Continue
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Step: Students ----------------------------------------------------------------

function StepStudents({ schoolId, lookup, onContinue }: { schoolId: number; lookup: LookupResponse | undefined; onContinue: () => void }) {
  const createStudent = useCreateStudent();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [classId, setClassId] = useState("");

  function handleAdd() {
    if (!email.trim() || password.length < 8) return;
    createStudent.mutate(
      {
        school_id: schoolId, email: email.trim(), password, full_name: fullName.trim() || undefined,
        class_id: classId ? Number(classId) : undefined,
      },
      { onSuccess: () => { setFullName(""); setEmail(""); setPassword(""); } }
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Students</CardTitle>
        <CardDescription>Real accounts, optionally enrolled into a class immediately.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-ink-muted">Already created</span>
          <ExistingList items={(lookup?.students ?? []).map((s) => ({ id: s.id, label: s.name }))} empty="None yet." />
        </div>
        <div className="flex flex-wrap items-end gap-3 rounded-xl border border-border bg-elevated/40 px-3.5 py-3">
          <Field label="Full name" className="w-44">
            <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
          </Field>
          <Field label="Email" className="w-56">
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password" className="w-40" hint="At least 8 characters">
            <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <Field label="Class (optional)" className="w-40">
            <select
              value={classId}
              onChange={(e) => setClassId(e.target.value)}
              className="h-10 w-full rounded-xl border border-border bg-card px-3.5 text-sm text-ink shadow-sm"
            >
              <option value="">Not enrolled yet</option>
              {(lookup?.classes ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </Field>
          <Button onClick={handleAdd} disabled={!email.trim() || password.length < 8 || createStudent.isPending}>
            {createStudent.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add student
          </Button>
        </div>
        {createStudent.isError && (
          <p className="text-sm text-urgent">{createStudent.error instanceof ApiError ? createStudent.error.message : "Failed to create student."}</p>
        )}
        <Button variant="ghost" className="self-start" onClick={onContinue}>
          Continue
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Step: Parents -----------------------------------------------------------------

function StepParents({
  schoolId, lookup, createdParents, onParentCreated, onContinue,
}: {
  schoolId: number; lookup: LookupResponse | undefined;
  createdParents: { id: number; name: string; studentNames: string[] }[];
  onParentCreated: (p: { id: number; name: string; studentNames: string[] }) => void;
  onContinue: () => void;
}) {
  const createParent = useCreateParent();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [studentIds, setStudentIds] = useState<Set<number>>(new Set());

  function toggleStudent(id: number) {
    setStudentIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleAdd() {
    if (!email.trim() || password.length < 8) return;
    const idsArray = Array.from(studentIds);
    createParent.mutate(
      { school_id: schoolId, email: email.trim(), password, full_name: fullName.trim() || undefined, student_ids: idsArray },
      {
        onSuccess: (result) => {
          const names = idsArray.map((id) => lookup?.students.find((s) => s.id === id)?.name ?? `#${id}`);
          onParentCreated({ id: result.id, name: fullName.trim() || email.trim(), studentNames: names });
          setFullName(""); setEmail(""); setPassword(""); setStudentIds(new Set());
        },
      }
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Parents</CardTitle>
        <CardDescription>Real accounts, linked to one or more of their real children above.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div>
          <span className="mb-1.5 block text-xs font-medium uppercase tracking-wide text-ink-muted">Already created this session</span>
          {createdParents.length === 0 ? (
            <p className="text-sm text-ink-muted">None yet.</p>
          ) : (
            <div className="flex flex-col gap-1">
              {createdParents.map((p) => (
                <p key={p.id} className="text-sm text-ink">
                  <span className="font-medium">{p.name}</span>{" "}
                  <span className="text-ink-muted">→ {p.studentNames.length ? p.studentNames.join(", ") : "no children linked"}</span>
                </p>
              ))}
            </div>
          )}
        </div>
        <div className="flex flex-col gap-3 rounded-xl border border-border bg-elevated/40 px-3.5 py-3">
          <div className="flex flex-wrap items-end gap-3">
            <Field label="Full name" className="w-44">
              <Input value={fullName} onChange={(e) => setFullName(e.target.value)} />
            </Field>
            <Field label="Email" className="w-56">
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
            </Field>
            <Field label="Password" className="w-40" hint="At least 8 characters">
              <Input type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
            </Field>
          </div>
          {lookup && lookup.students.length > 0 && (
            <div>
              <span className="mb-1 block text-xs font-medium text-ink-muted">Children (select one or more)</span>
              <div className="flex flex-wrap gap-2">
                {lookup.students.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    onClick={() => toggleStudent(s.id)}
                    className={cn(
                      "rounded-full border px-3 py-1 text-xs font-medium transition-colors",
                      studentIds.has(s.id) ? "border-accent bg-accent/10 text-accent" : "border-border bg-card text-ink-muted"
                    )}
                  >
                    {s.name}
                  </button>
                ))}
              </div>
            </div>
          )}
          <Button onClick={handleAdd} disabled={!email.trim() || password.length < 8 || createParent.isPending} className="self-start">
            {createParent.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
            Add parent
          </Button>
        </div>
        {createParent.isError && (
          <p className="text-sm text-urgent">{createParent.error instanceof ApiError ? createParent.error.message : "Failed to create parent."}</p>
        )}
        <Button variant="ghost" className="self-start" onClick={onContinue}>
          Continue to review
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Step: Review ------------------------------------------------------------------

function StepReview({
  schoolName, lookup, parentsCreated,
}: {
  schoolName: string | undefined; lookup: LookupResponse | undefined; parentsCreated: number;
}) {
  const navigate = useNavigate();
  const counts = [
    { label: "Classes", count: lookup?.classes.length ?? 0 },
    { label: "Subjects", count: lookup?.subjects.length ?? 0 },
    { label: "Rooms", count: lookup?.rooms.length ?? 0 },
    { label: "Teachers", count: lookup?.teachers.length ?? 0 },
    { label: "Students", count: lookup?.students.length ?? 0 },
    { label: "Parents", count: parentsCreated },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{schoolName ?? "Your school"} is set up</CardTitle>
        <CardDescription>Real counts from what you just created - not a placeholder summary.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {counts.map((c) => (
            <div key={c.label} className="rounded-xl border border-border bg-elevated/40 px-4 py-3 text-center">
              <div className="font-display text-2xl font-bold text-ink">{c.count}</div>
              <div className="text-xs font-medium uppercase tracking-wide text-ink-muted">{c.label}</div>
            </div>
          ))}
        </div>
        <p className="text-sm text-ink-muted">
          Timetable generation, attendance, and everything else in the product is ready to use with this real data whenever
          you are - nothing further happens automatically from here.
        </p>
        <Button onClick={() => navigate("/admin")} className="self-start">
          Go to dashboard
        </Button>
      </CardContent>
    </Card>
  );
}

// --- Wizard container --------------------------------------------------------------

function WizardBody({ schoolId }: { schoolId: number }) {
  const school = useSchool(schoolId);
  const lookup = useReferenceLookup(schoolId);
  const [step, setStep] = useState<StepKey>(() => {
    const saved = localStorage.getItem(STORAGE_KEY);
    return (STEP_KEYS as readonly string[]).includes(saved ?? "") ? (saved as StepKey) : "school";
  });
  const [parentsCreated, setParentsCreated] = useState<{ id: number; name: string; studentNames: string[] }[]>([]);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, step);
  }, [step]);

  function goTo(next: StepKey) {
    setStep(next);
  }
  function advanceFrom(current: StepKey) {
    const idx = STEP_KEYS.indexOf(current);
    setStep(STEP_KEYS[Math.min(idx + 1, STEP_KEYS.length - 1)]);
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-4 px-4 py-8">
      <PageHeader
        title="Set up your school"
        description="Every step creates real data immediately through the real API - close this anytime, your progress is saved."
      />
      <Tabs value={step} onValueChange={(v) => goTo(v as StepKey)}>
        <TabsList className="flex-wrap">
          {STEP_KEYS.map((key) => (
            <TabsTrigger key={key} value={key}>
              {STEP_LABELS[key]}
            </TabsTrigger>
          ))}
        </TabsList>

        <TabsContent value="school">
          <StepSchool schoolId={schoolId} onContinue={() => advanceFrom("school")} />
        </TabsContent>
        <TabsContent value="classes">
          <StepClasses schoolId={schoolId} lookup={lookup.data} onContinue={() => advanceFrom("classes")} />
        </TabsContent>
        <TabsContent value="subjects">
          <StepSubjects schoolId={schoolId} lookup={lookup.data} onContinue={() => advanceFrom("subjects")} />
        </TabsContent>
        <TabsContent value="rooms">
          <StepRooms schoolId={schoolId} lookup={lookup.data} onContinue={() => advanceFrom("rooms")} />
        </TabsContent>
        <TabsContent value="teachers">
          <StepTeachers schoolId={schoolId} lookup={lookup.data} onContinue={() => advanceFrom("teachers")} />
        </TabsContent>
        <TabsContent value="students">
          <StepStudents schoolId={schoolId} lookup={lookup.data} onContinue={() => advanceFrom("students")} />
        </TabsContent>
        <TabsContent value="parents">
          <StepParents
            schoolId={schoolId}
            lookup={lookup.data}
            createdParents={parentsCreated}
            onParentCreated={(p) => setParentsCreated((prev) => [...prev, p])}
            onContinue={() => advanceFrom("parents")}
          />
        </TabsContent>
        <TabsContent value="review">
          <StepReview schoolName={school.data?.name} lookup={lookup.data} parentsCreated={parentsCreated.length} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default function OnboardingWizard() {
  const currentUser = useCurrentUser();

  if (currentUser.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper">
        <Loader2 className="h-6 w-6 animate-spin text-accent" />
      </div>
    );
  }

  if (!currentUser.data?.school_id) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-paper px-4">
        <Card className="max-w-sm">
          <CardHeader>
            <div className="mb-2 flex items-center gap-3">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent text-accent-foreground shadow-sm">
                <GraduationCap className="h-5 w-5" />
              </div>
              <span className="font-display text-lg font-bold tracking-tight text-ink">EduOps AI</span>
            </div>
            <CardTitle>No school linked</CardTitle>
            <CardDescription>This account has no school_id - sign up again to create one.</CardDescription>
          </CardHeader>
        </Card>
      </div>
    );
  }

  return <WizardBody schoolId={currentUser.data.school_id} />;
}
