# Person B integration seam audit

Read-only. Branch `samiksha` at `db5a624`, Riverside (5707) live data. Every verdict
below cites the calling code or the actual request/response; live proofs are marked
**PROVEN** and were run against the shared database with real sign-ins unless stated.

One correction to the briefing: Ananya Joshi's login is
`student1.1786787329065@riverside-school.test`, **not** `ananya.student@…` — the latter
does not exist in `users`. Diya's `diya.student@…` is real.

## Verdict summary

| Seam | Verdict |
|---|---|
| S-A resources → KB ingestion | **WIRED** (one endpoint behind both pages) — PROVEN |
| S-B gradebook → risk scoring | **NOT WIRED** — and naive wiring would *unflag Diya* |
| S-C Person B remarks → risk/portal | **NOT WIRED** (by recorded decision); remarks *do* reach report cards |
| S-D stream post → announcement engine | **PARTIAL** — dispatches bell rows, never creates an announcement |
| S-E teacher bot quiz hook | **MOCKED** — hardcoded placeholders, zero callers |
| S-F assignment grade → gradebook | **NOT WIRED** — teacher must double-enter |
| S-G quiz attempt → gradebook | **WIRED** (with two data bugs, see Phase 2) |
| S-H late/missing → parent alert | **PARTIAL** — manual nudge only, no scheduled task |
| S-I report card → parent notification | **PARTIAL** — dispatches, but with an invalid `source_type` and on every regenerate |
| S-J report card ← attendance | **WIRED** to Person A's table, **numbers can't match the portal** (different window & rules) |
| S-K enrollment → stream visibility | **WIRED** — PROVEN indirectly (RBAC probes) |
| S-L timetable/exams/deadlines → calendar | **PARTIAL** — add-only sync, stale rows on change/delete |
| S-M risk flag → analytics banner + portal | **WIRED** — PROVEN |
| S-N syllabus summary → pace tracker | **WIRED** in code, **UNVERIFIED** end-to-end (no syllabus plans in 5707) |
| S-O resource update → re-index | **NOT WIRED** — no update endpoint exists at all |

---

## S-A · Two resource upload paths — WIRED, one nuance

**The "two hooks" are one hook.** `frontend/src/hooks/useResources.ts:1` is a single
line: `export * from "@/api/hooks/useResources";`. Both pages therefore call the same
`POST /resources/upload` via the same `useUploadResource` (`api/hooks/useResources.ts:73`).

Reachability (`App.tsx`): teacher gets Person C's `TeacherResources`
(`/teacher/resources`, App.tsx:131); principal/admin/student/parent get Person B's
`ResourcesPage`. The difference is payload shape only — `routes/teacher/Resources.tsx:163`
sends `grade_level`, `components/resources/ResourcesPage.tsx:130` sends `class_id`.

**PROVEN, both shapes, as Meera (real sign-in):**

| Upload | HTTP | resource | kb_chunks | indexed |
|---|---|---|---|---|
| grade-path (`grade_level=3`) | 201 | id 291, grade=3, class=None | **1** | yes |
| class-path (`class_id=5208`) | 201 | id 292, grade=3, class=5208 | **1** | yes |

Ingestion is inline at `routers/resources.py:319` for every upload. Both fixtures were
deleted afterwards via `DELETE /resources/{id}` → 204, and **the delete cleaned its
`kb_chunks`** (`resources.py:561-564`) — 0 rows left. Nothing from this audit remains in
the KB.

**Nuance worth knowing:** chunks are stamped with `grade_level` only
(`services/ingestion.py:174`) and retrieval filters `school+grade`
(`services/retrieval.py:186`). So a **class-scoped** (3-A-only) resource is still
retrievable by **3-B students through the bot**, even though the listing hides it from
them. Scope mismatch between listing and retrieval — minor, by current data, but real.

## S-B · Gradebook → risk scoring — NOT WIRED, and the fix is a judgement call

Nothing anywhere builds a `GradeSignal` from `gradebook_entries`.
`risk_scorer.py:79-81` still says "PLACEHOLDER … construct this from real data once
Person B's gradebook exists", and the only production call site is
`run_nightly_risk_scoring.py:103`: `score_student(attendance, grades=None, remarks=remarks)`.
The 29 Riverside gradebook rows contribute nothing to any flag. The "grades → early
warning" chain is fiction today.

**PROVEN — Diya's composite computed both ways through the real scorer:**

| | score | band |
|---|---|---|
| Production today (`grades=None`) | 0.366 | **MEDIUM** — flagged |
| If wired naively (`average_score_pct=50.5`) | 0.293 | **LOW** — *unflagged* |

Wiring it is not plumbing. Adding the grade signal redistributes weight
(attendance 76.9%→50%), and Diya's grade risk ((60−50.5)/60 = 0.158) is *lower* than her
attendance risk (0.343) — so connecting the flagship seam **as-is demotes the demo's
at-risk child below the 0.30 flag line**. Fixing this requires a decision on weights or
band thresholds, flagged for Phase 3.

(Aarav: 0.073 → 0.047, LOW either way.)

## S-C · Remarks → risk scoring — NOT WIRED (recorded decision), one new fact

Read paths, by table:

| Table | Read by |
|---|---|
| `remark_stubs` (12 rows) | risk scorer (`run_nightly_risk_scoring.py`), parent portal (`parent.py`), `GET /remarks/student/{id}` (`remarks.py`) |
| `remarks` (7 rows) | `GET /remarks/{id}` (`remarks.py`), **and `report_card_service.py:19`** |

A remark filed through Bulk Remark Entry affects **zero** risk scoring and never appears
in the parent portal feed — confirmed, matching `docs/audit/remarks-disconnect.md`.
**New fact:** Person B's remarks *do* flow into report cards (`teacher_remarks` in the
snapshot), so the disconnect is now three-way: report cards show one remark set, the
portal and scorer another.

## S-D · Stream post → announcement engine — PARTIAL

`classroom.py:379-392`: a stream post with `post_type="announcement"` calls
`dispatch_bulk(source_type="announcement", source_id=post.id)` — students only (no
parents, no other teachers). It **never creates an `announcements` row**, so it does not
appear in `/announcements/feed`, has no scope label, no acknowledgment, no ack-status.

**Latent id collision:** those bell rows carry `source_type="announcement"` with
`source_id` from the *stream_posts* id namespace, colliding with real announcement ids.
Currently harmless only because the bell never uses `source_id` — and `announcement`
isn't even in the bell's `SOURCE_ROUTE` map (`NotificationBell.tsx:47-57`), so clicking
*any* announcement notification (including real ones) dead-ends at the dashboard instead
of the feed page. Two findings for Phase 2/3: add the route mapping; decide whether
stream-announcements should create real announcement rows.

## S-E · Teacher Bot quiz hook — MOCKED

`quiz_service.py:123-140` `generate_draft_quiz_questions_hook` returns hardcoded
`"Sample question on {topic} #N?"` with `correct_option="A"` for every question.
**Zero callers** anywhere in the tree. `POST /bots/teacher/ask` has a keyword-detected
"quiz mode" (`bots.py:420-421`) that changes the LLM prompt only — it never calls the
hook, and no path exists from a bot draft into `POST /quizzes`. A drafted quiz cannot be
inserted into a real quiz except by hand-copying text.

## S-F · Assignment graded → gradebook — NOT WIRED

`assignments.py:501` `grade_submission` writes `submission.grade/feedback/status` and
commits. No `GradebookEntry` write, no dispatch, nothing else. A teacher who grades a
submission must re-enter the same score in the gradebook, and an assignment grade never
reaches analytics, report cards, or (even if S-B were fixed) risk. Asymmetric with
quizzes (S-G), which *do* auto-write.

## S-G · Quiz attempt → gradebook — WIRED

`quizzes.py:372-395`: submitting an attempt upserts a `GradebookEntry`
(`assessment_type="quiz"`, `assessment_id=quiz_id`). Fires on create; re-attempt updates
score in place. Two data bugs inside it for Phase 2: `subject_id=quiz.subject_id or 1`
(hardcoded FK fallback to subject 1, which belongs to whatever school owns id 1) and
`term="Term 1"` hardcoded.

## S-H · Late/missing submission → parent alert — PARTIAL

`assignments.py:629` (`nudge_student`) and `:691` (`nudge_all_missing`) dispatch through
the real `dispatch_bulk`, and `:670-678` includes linked parents. But both are
**teacher-initiated buttons**. There is no scheduled task: `app/scheduler.py` contains
no assignment/submission job, so nothing fires when a deadline passes unless a human
clicks. "Late submission → parent alert" is a manual feature described as automatic.

## S-I · Report card → parent notification — PARTIAL, two defects

`report_card_service.py:141-155` dispatches to linked parents on generation — wired in
principle. But:

1. `source_type="report_card_ready"` is **not in `SOURCE_TYPES`**
   (`models/notification.py` has `report_card`). `notify.py` deliberately doesn't
   validate, so rows land with an unknown type — no icon mapping, invisible to any
   future filter. The exact `"issued"`-vs-`"active"` vocabulary class of bug.
2. The dispatch sits **outside the upsert branch**, so *every* regenerate re-notifies
   every parent. Bulk-regenerating a class of 30 twice = 60 duplicate notifications.

## S-J · Report card ← attendance — WIRED to the right table, wrong arithmetic

`report_card_service.py:52-59` reads Person A's `attendance_records` — no duplicate
logic. But: **no date window** (all-time, vs the portal/scorer's 30-day
`ATTENDANCE_LOOKBACK_DAYS`), **counts `late` as present** (portal counts present only),
and **returns 100.0 when a student has zero records**. The report card's
attendance percentage cannot match `GET /parent/child/{id}/summary` for any student with
more than 30 days of history or any late marks. Quantified for Diya/Aarav in Phase 2.

## S-K · Enrollment → stream visibility — WIRED

`classroom.py:124-131` resolves membership from Person A's `Enrollment`;
`_assert_can_view_classroom` (`:133-186`) checks student enrollment, parent link via
`ParentStudent`, teacher via classroom.teacher_id ∪ homeroom ∪ active `TimetableSlot`.
No parallel membership notion. (Parents are currently denied all classroom endpoints by
the recorded RBAC decision — the parent branch is dead code but harmless.)

## S-L · Timetable/exams/deadlines → calendar — PARTIAL: add-only, stale rows

`calendar_sync_service.py` syncs slots, exams, assignments, quizzes into
`calendar_events` idempotently — every branch is `if not existing: add`. **Nothing
updates or deletes** an event when the source changes: no `CalendarEvent` reference in
`timetable.py` or anywhere outside the sync, and the sync never reconciles deletions. A
moved timetable slot leaves the old event in place *and* adds a new one; a deleted
assignment leaves its deadline on every student's calendar forever.

## S-M · Risk flag → analytics banner + portal — WIRED, PROVEN

`analytics_service.py:75-80` reads open `RiskFlag`s directly (fixed this session —
`reasons` flattening); `parent.py:221-226` reads the newest open flag. Live: Diya's
analytics returns `is_at_risk: true` with both real reasons; portal shows the same
medium flag. One caveat: **nightly-created flags notify nobody** —
`run_nightly_risk_scoring.py` contains no dispatch call; only the manual
`POST /risk/flag` notifies. The banner is wired; the "teacher + parent notified" tail of
the chain only holds for manual flags.

## S-N · Syllabus summary → pace tracker — WIRED in code, UNVERIFIED live

`TeacherSyllabusPacePage.tsx` renders from `useSyllabusSummary` → Person A's
`GET /syllabus/summary`. No parallel implementation. But school 5707 has **zero syllabus
plans**, so the summary returns `items: []` and no "behind plan" warning can render.
UNVERIFIED end to end; needs a seeded syllabus plan to prove.

## S-O · Resource update/replace → re-index — NOT WIRED (no update path)

`resources.py` has no PUT/PATCH. The only mutation is DELETE (which does clean
`kb_chunks` — proven above) followed by re-upload (which re-ingests). "Update fires
re-index" is vacuously false: update does not exist. Replace-by-delete works.

---

## Flagship chain traces

### Learning chain — breaks at three links

```
quiz attempt ──✅ auto-grade ──✅ gradebook ──✅ analytics ──❌ (1) risk scorer
assignment ──✅ grade ──❌ (2) gradebook
nightly flag ──❌ (3) notification
```

1. **First break: gradebook → risk scorer** (S-B). Grades never reach the scorer;
   Diya's D contributes nothing to her flag.
2. **Assignment branch breaks earlier**: grading a submission writes no gradebook entry
   (S-F), so assignment grades never even reach analytics.
3. **Tail break**: a nightly-scored flag notifies nobody (S-M caveat). Today Diya's flag
   is visible in banner/portal only because the flag exists; her parents were notified
   only because a human called `POST /risk/flag` manually during this session.

The only fully-intact path from "student does work" to "someone is told" is:
quiz attempt → gradebook → analytics **banner** (pull, not push).

### Knowledge chain — holds for two of three sources

```
class resources ──✅ ingest ──✅ kb_chunks ──✅ retrieval ──✅ cited answer   (PROVEN)
verified doubt answers ──✅ ingest_verified (ingestion.py:275-283) ──✅ same  (pre-existing, tested)
library items ──❌ never ingested
```

**First break: the digital library.** `library.py`/`library_service.py` contain no
ingestion call; `LibraryItem.file_url` is an optional client-supplied string
(`library.py:127`), never fetched, never chunked. A "book" uploaded to the digital
library is invisible to the Doubt Bot. If the demo claims "library resources feed the
bot", that is false; if the claim is only "class resources + verified answers", the
chain is fully proven — live citation test earlier returned resource-grounded answers
with correct titles.
