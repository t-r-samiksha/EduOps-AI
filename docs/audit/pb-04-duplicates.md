# Duplicate-page audit

Read-only. Branch `samiksha`, merged tree. **Nothing implemented** — proposals only.

Person A built operational screens and Person B built academic ones, and the two overlap.
The sidebar grouping did not create any of this; it made one instance visible.

## Classification

Each finding is tagged by the kind of fix it needs, because they are different problems:

| Kind | Meaning | Fix shape |
|---|---|---|
| **K1** | Same component, two routes | Delete one, redirect |
| **K2** | Different components, same user intent | Decide which survives |
| **K3** | Complementary components, colliding labels | Rename and co-locate, delete nothing |
| **K4** | Same intent, **disagreeing data** | Dangerous. Reconcile the data, not the UI |

## Findings

| # | Pair | Kind | Severity |
|---|---|---|---|
| D-1 | Syllabus (Operations) vs Syllabus Pace (Academics) | **K3** | cosmetic, admin/principal only |
| D-2 | `TeacherResources` vs `ResourcesPage` | **K2** | real, one endpoint, two UIs |
| D-3 | `GET /remarks/student/{id}` vs `GET /remarks/{id}` | **K4** | **dangerous — data disagrees** |
| D-4 | Student analytics vs Gradebook | not a duplicate | — |
| D-5 | Homework Calendar vs Timetable | not a duplicate | — |
| D-6 | Attendance screens | not a duplicate | — |
| D-7 | Doubt Bot vs Doubts (student) | **K3** | cosmetic, arguably fine |

**One K4. One K2. Two K3. Three cleared.** Nothing is K1: no component is mounted at two
routes serving the same intent — the four components that appear on multiple paths
(`ClassroomStreamPage`, `ResourcesPage`, `AssignmentsPage`, `TeacherResources`) are all
index/detail pairs (`/resources` and `/resources/:classId`), which is correct routing.

---

## D-1 · Syllabus vs Syllabus Pace — **K3**, and it is a labelling problem

**You reasoned from two cards on one screen and called it a component duplicate. It is
not.** The two are different components on different endpoints:

| | Syllabus | Syllabus Pace |
|---|---|---|
| Component | `components/syllabus/SyllabusPage.tsx` | `components/syllabus/TeacherSyllabusPacePage.tsx` |
| Purpose | Create a plan, log checkpoints (CRUD) | Read pace: expected vs actual, drift, status |
| Hooks | `useCreateSyllabusPlan`, `useLogCheckpoint`, `useReferenceLookup` | `useSyllabusSummary`, `useLogCheckpoint` |
| Endpoint | plan/checkpoint writes | `GET /syllabus/summary` |

They share exactly one hook, `useLogCheckpoint` — so both can log a checkpoint, which is
the overlap you noticed. Neither is redundant: one authors the plan, the other reads its
pace. **Delete nothing.**

**What makes it look duplicated is my grouping, not their code.** Measured across all five
roles, exactly one label collision is split across groups:

```
admin      "syllabus": Syllabus Pace [Academics]  |  Syllabus [Operations]   <-- SPLIT
principal  "syllabus": Syllabus Pace [Academics]  |  Syllabus [Operations]   <-- SPLIT
teacher    "syllabus": Syllabus [School Ops]  |  Syllabus Pace [School Ops]  (adjacent, fine)
student    "doubt":    Doubt Bot [top]  |  Doubts [top]                      (adjacent, fine)
parent     none
```

I put them in different groups for admin and principal. The teacher menu already has them
adjacent in one group and reads fine, which is the evidence that co-location is the fix.

### Proposed naming and placement

Both under **Academics**, adjacent, renamed so the distinction is in the label rather than
inferred:

| Current | Proposed | Why |
|---|---|---|
| `Syllabus` | **Syllabus Plans** | It is the plan/checkpoint authoring screen. "Syllabus" alone reads as the whole feature area, which is why the pair looks like a duplicate. |
| `Syllabus Pace` | **Syllabus Pace** (unchanged) | Already unambiguous, and it names the metric it shows. |

Ordering: **Syllabus Plans** before **Syllabus Pace** — you author a plan before you can
have a pace against it, so the menu follows the workflow.

Teacher stays as-is (already adjacent in School Ops), though renaming `Syllabus` →
`Syllabus Plans` there too keeps one vocabulary across roles.

---

## D-2 · Two resources pages on one endpoint — **K2**

Already found in `pb-01-seams.md` (S-A) and re-confirmed here.

| | `routes/teacher/Resources.tsx` | `components/resources/ResourcesPage.tsx` |
|---|---|---|
| Reachable by | teacher only | principal, admin, student, parent |
| Hook | `@/hooks/useResources` — a **one-line re-export** of the other | `@/api/hooks/useResources` |
| Endpoint | `POST /resources/upload`, `GET /resources` | identical |
| Upload payload | `grade_level` | `class_id` |

**Same endpoint, same hook, two UIs.** Not K1 — they are genuinely different components,
and the split is by role, so no user sees both. But there is no product reason for a
teacher to get a different resources screen from a principal.

**Both upload paths ingest correctly** — PROVEN in S-A: one text file through each shape
produced 1 `kb_chunk` each, and deleting cleaned them back to 0.

**The substantive difference is the scope unit**, and it matters beyond cosmetics:
`grade_level` is what `ingestion.py:174` stamps on chunks and what `retrieval.py:186`
filters on, so a **class-scoped** resource is hidden from the other section in the listing
but still retrievable by that section through the Doubt Bot. Listing and retrieval
disagree.

**Proposal:** consolidate to one component for all five roles, keeping **Person C's
grade-level payload** as canonical since that is the scope unit the RAG pipeline actually
uses, with `class_id` retained as a **display tag only**. `TeacherResources` becomes a
redirect or is deleted; `/teacher/resources` points at the surviving component.

*(This matches the direction you already set for resources — recorded here so the
duplicate register is complete, not to re-open it.)*

---

## D-3 · Remarks — **K4, the dangerous kind**

Documented in depth in `docs/audit/remarks-disconnect.md`; summarised here because it is
the only finding in this register where **the data itself disagrees**.

| | `GET /remarks/student/{id}` | `GET /remarks/{id}` |
|---|---|---|
| Table | `remark_stubs` (12 Riverside rows) | `remarks` (7 Riverside rows) |
| Sentiment | VADER, computed per request → `{label, compound}` | `sentiment_tag` string, hand-picked |
| Written by | seed fixtures only | `POST /remarks`, `POST /remarks/bulk` |
| Read by | parent portal, Parent Bot, **risk scorer** | `GET /remarks/{id}`, **report cards** |

Not a route collision — three path segments versus two, so FastAPI cannot confuse them.
The duplication is at the data layer, and it is **three-way**: a teacher files a remark
through Bulk Remark Entry, it lands in `remarks`, and it reaches the **report card** but
**not** the parent portal, **not** the Parent Bot, and **not** risk scoring. Meanwhile the
12 seeded `remark_stubs` rows drive the parent-facing demo and are invisible to Person B's
UI.

So a parent and a report card can describe the same child's conduct from two disjoint
sources. **This is the one to fix properly**, and it is a data migration rather than a UI
decision — deliberately left alone per the recorded deferral, but it should not be filed
next to the cosmetic items.

---

## D-4 · Student analytics vs Gradebook — **not a duplicate**

`GET /analytics/student/{id}` **embeds** the gradebook payload
(`analytics_service.py:108`: `"gradebook": gradebook_summary`) by calling the same
`get_student_gradebook_summary` the gradebook endpoint uses. One source, two
presentations — analytics wraps it with attendance, quizzes, risk and a trend.

Verified they cannot disagree: both read the identical function. Composition, not
duplication. **No action.**

## D-5 · Homework Calendar vs Timetable — **not a duplicate**

Different endpoints, different data, one feeds the other:

- Timetable: `/timetable/active`, `/timetable/generate`, `/timetable/preflight`, `/timetable/update` — the recurring weekly grid.
- Calendar: `/calendar/{userId}`, `/calendar/homework/{studentId}`, `/calendar/sync` — dated events, of which timetable slots are one **source** (`calendar_sync_service.py`).

A slot is a rule; a calendar event is an occurrence. **No action** — though the sync is
add-only and leaves stale rows, which is seam S-L, a separate defect.

## D-6 · Attendance screens — **not a duplicate**

Four components, and only one is routed:

- `AttendanceCapture` → `/{admin,principal,teacher}/attendance`. **Same component, three roles** — legitimate role reuse, not duplication.
- `AttendanceRegister` and `AttendanceAnalytics` are **tabs inside** `AttendanceCapture` (`AttendanceCapture.tsx:583,586`), not routes.
- `StudentAttendance` → `/student/attendance`, a different intent (my own record) on a different endpoint (`/attendance/my-records`).

**No action.**

## D-7 · Doubt Bot vs Doubts (student) — **K3**, arguably fine as-is

Both flat and adjacent in the student menu. Genuinely different: **Doubt Bot** is the RAG
chatbot (`/student/doubt-bot`), **Doubts** is the human thread list (`/student/doubts`)
where a teacher answers and can mark a reply verified.

They are adjacent, which is the K3 remedy already applied by accident. **Optional**
rename for clarity: `Doubts` → **"Ask a Teacher"**, which names the human path and stops
it reading as a variant of the bot. Low value; listed for completeness.

---

# Consolidation plan

Ordered by value, and none of it implemented.

| Step | Kind | Change | Risk |
|---|---|---|---|
| 1 | K3 | Rename `Syllabus` → **Syllabus Plans**; move it into **Academics** beside **Syllabus Pace**, plans first. Admin and principal only. | None — `navConfig.ts` labels and grouping only. No routes, no components, no endpoints. |
| 2 | K2 | Consolidate the two resources pages to one component for all five roles, grade-level payload canonical, `class_id` as display tag. Redirect `/teacher/resources`. | Moderate — touches a live screen and the upload payload. Needs the S-A listing/retrieval mismatch fixed in the same change or the inconsistency persists. |
| 3 | K3 | Optional: `Doubts` → **Ask a Teacher**. | None. |
| 4 | K4 | Remarks reconciliation — migrate `remark_stubs` into `remarks`, repoint the four read paths, delete the stub table last. | **High.** Touches the parent portal, Parent Bot and risk scorer, all demo-critical. Deferred by decision; not a menu change. |

Step 1 is the only one I would do before a demo. Step 2 is a real improvement with real
risk. Step 4 should not be attempted under time pressure.

---

# The `Expected 0%` question — confirmed as data, not arithmetic, but not the reason you expected

Your hypothesis was that a **future** term start floors `expected` to zero via the clamp.
**That is not what happened in the screenshot.** The real rows, school 6318, Grade 1 - A,
both plans in the same class and academic year:

| Subject | `term_start_date` | elapsed / total | Expected |
|---|---|---|---|
| **Math** | **2026-08-18 — exactly today** | **0** / 210 | **0%** |
| social studies | 2026-08-01 | 17 / 214 | 8% |

`expected_fraction = clamp((today − term_start_date) / (term_end_date − term_start_date))`
(`syllabus_pace.py:80-82`). Math's term starts **today**, so `elapsed_days = 0` and
`0 / 210 = 0.0` — a genuine zero. **The clamp was never involved**; there was nothing
negative to floor.

**So: bad data, correct arithmetic, and nothing to fix.** The two subjects diverge because
`term_start_date` and `term_end_date` are **per-plan columns** — nothing in the schema owns
"when is Term 1", so two plans in one class carry two different term windows, and these two
were created 17 days apart.

**The future-start case is real but separate, and latent.** A plan with `term_start_date`
after today yields negative elapsed, which `_clamp` floors to 0, displaying **the same
`Expected 0%`** as a plan starting today — and every logged checkpoint then reads as *ahead
of schedule*. No live row is in that state. Recorded in `pb-03-deferred.md` with a proposed
`status="not_started"` remedy.

Riverside's three seeded plans all start deliberately in the **past** so the pace feature
demonstrates something: Grade 3-A Math reads **ahead** (+0.167), Grade 3-B Math reads
**behind** (−0.333).
