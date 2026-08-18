# Person B correctness and bug audit

Read-only. Branch `samiksha` at `db5a624`, Riverside (5707) live data. Every finding
cites `file:line` or the request made and the body returned. Live proofs marked
**PROVEN**. Anything I could not confirm is marked **UNVERIFIED** with what it would take.

Two audit fixtures were created and **removed**: resources 291/292 (deleted via the API,
`kb_chunks` verified back to 0) and quiz 27 (deleted with its questions, attempt and
gradebook entry). Nothing from this audit remains.

## Counts

| Severity | Count |
|---|---|
| BLOCKER | **3** |
| MAJOR | **9** |
| MINOR | **7** |

**Good news first, since it was the top-listed blocker risk: there is no answer-key
leakage.** PROVEN — as an *unattempted* student, `GET /quizzes/detail/{id}` returned
`correct_option: null` on 1/1 questions; `GET /quizzes` never includes questions at all
(`quizzes.py:299`, `include_questions=False`). The gate is `show_correct = is_teacher or
has_completed` (`quizzes.py:172`). An attempted student *does* see the key — that is
post-submission review and correct. Multiple attempts are blocked (400,
`quizzes.py:347-351`) and enrollment is checked on both detail and attempt.

---

# BLOCKER

## B-1 · `POST /remarks` and `POST /remarks/bulk` have no role gate — anyone can write teacher remarks

`app/routers/remarks.py` — `create_remark` and `create_bulk_remarks_endpoint` both use
`user: CurrentUser = Depends(get_current_user)`. **No `require_role`.** Every other
Person B write path uses `require_role("teacher","admin","principal")`; these two do not.

Any authenticated user — student or parent — can create remarks against **any**
`student_id`, in any class, attributed to themselves as `author_id`. `school_id` falls
back to `user.school_id or 1`, so an account with no school writes into school 1.

**Repro:** sign in as `aarav.student@riverside-school.test`, then
`POST /remarks {"student_id": 21546, "class_id": 5208, "content": "...", "sentiment_tag": "behavioral"}`
→ expect `201`. *Not executed:* it would write a fabricated remark about Diya into demo
data. The absence of `require_role` on those two handlers is the evidence; the fix
carries a test.

## B-2 · Teachers can create assignments and quizzes for classes they don't teach

This is known failure 1, confirmed, **and it has a sibling**.

`assignments.py:143-159` `_assert_can_manage_class_assignment` checks only (a) the caller
has a school, (b) the class is in *that school*, (c) role ∈ {admin, principal, teacher}.
It **never checks the teacher teaches the class** — despite `_classes_taught_by` existing
12 lines above at `:134` and being used correctly by `grade_submission` (`:513-516`).

`quizzes.py:214-220` `create_quiz` has the identical shape: school-scoped class lookup,
no taught check.

So Meera can create assignments and quizzes for Grade 1-A. `test_unauthorized_teacher_cannot_create`
fails for exactly this reason. Both are one call to the existing helper.

## B-3 · `POST /report_cards/generate/{student_id}` is not school-scoped — cross-tenant write and notification

`report_cards.py:43-56` gates on `require_role("teacher","admin","principal")` and passes
`student_id` straight to `generate_single_report_card`. That service
(`report_card_service.py:30-52`) resolves the student by id alone — **no comparison to
the caller's `school_id` anywhere in either layer** (the service has no `user` parameter
at all).

A teacher at Riverside can therefore generate a report card for a student at school 6318,
persisting a `report_cards` row in another tenant *and* dispatching notifications to that
school's parents (`report_card_service.py:141-155`).

**Not executed deliberately** — proving it means writing a row and sending notifications
into another developer's demo school. The absent check is the evidence
(`report_cards.py:43-56`, `report_card_service.py:30-52`). Same gap on
`bulk-generate/{class_id}` (`report_cards.py:59-73`), which takes an unscoped `class_id`.

---

# MAJOR

## M-1 · Report card parent notifications are added to the session and never committed — silently lost

`report_card_service.py` commits **inside** the upsert branch (`:117` existing, `:137`
new) and then calls `dispatch_bulk` at `:146` — **with no commit after it**. The
`Notification` rows are added to the session and discarded when the request ends.

**PROVEN, and the number is diagnostic.** Four generations for Riverside students
(2 × single for Diya, then bulk for class 5208's 2 students) produced **exactly 1**
`report_card_ready` notification:

| Action | notifications before | after |
|---|---|---|
| `POST /report_cards/generate/21546` ×2 | 0 | **0** |
| `POST /report_cards/bulk-generate/5208` (2 students) | 0 | **1** |

Single generation delivers **nothing**. Bulk delivers **N−1 of N** — each student's
pending notification is flushed only by the *next* student's commit, so the last one is
always lost. That is the mechanism, not a coincidence: it is why 2 students yielded 1.

"Report card generated → parent notified" does not work on the single-student path, which
is the demo path.

## M-2 · Three different attendance percentages for the same child

**PROVEN** for both Riverside children:

| Surface | Aarav | Diya |
|---|---|---|
| Parent portal `/parent/child/{id}/summary` | **81.5%** | **59.1%** |
| Student analytics `/analytics/student/{id}` | **88.9%** | **71.0%** |
| Report card `report_cards.attendance_percentage` | **88.9%** | **71.0%** |

Person B's two surfaces agree with each other and both disagree with Person A's portal,
for two independent reasons (`analytics_service.py:36-45`, `report_card_service.py:52-59`):

1. **No date window.** Both count *all* attendance rows ever; the portal and risk scorer
   use `ATTENDANCE_LOOKBACK_DAYS = 30`.
2. **`late` counts as present** (`status in ("present","late")`); the portal counts
   `present` only.

Third defect in the same lines: **zero attendance records returns `100.0`**, not `None` —
a student with no data reads as perfect attendance.

A judge comparing the parent portal to the report card sees two different numbers for the
same child. Which is canonical is a product decision — flagged for Phase 3, not picked.

## M-3 · Quiz `available_until` is not enforced

**PROVEN.** Created a quiz with `available_until: 2026-08-02` (16 days past), attempted it
as Aarav today → **HTTP 200, attempt accepted and graded**. `submit_quiz_attempt`
(`quizzes.py:326-360`) never reads `available_from` or `available_until`.

## M-4 · The quiz timer is fabricated, not enforced

`quizzes.py:361`: `started_at = now - timedelta(minutes=quiz.duration_minutes)`. The
server invents a start time at *submit* time, so `duration_minutes` is decorative — a
student may take unlimited time and the stored `started_at` always shows exactly the
allowed duration. **PROVEN** in the same probe: `started_at` came back exactly
5 minutes before `submitted_at` for a quiz I answered instantly.

There is no "start attempt" endpoint, so enforcing this needs a design decision, not just
a check.

## M-5 · Hardcoded FK fallbacks write into the wrong school

Three places substitute literal `1` for a missing id:

- `quizzes.py:388` — `subject_id=quiz.subject_id or 1` on the auto-created gradebook
  entry. A quiz with no subject files its grade under **subject 1**, whichever school
  owns that row.
- `gradebook.py:117` — `school_id=user.school_id or 1`
- `remarks.py` `create_remark` / `create_bulk_remarks_endpoint` — `school_id=user.school_id or 1`

Same family as the `"issued"`/`"active"` bug: writes succeed, data lands in the wrong
place, nothing raises.

## M-6 · Quiz gradebook entries hardcode `term="Term 1"`

`quizzes.py:390`. Every auto-graded quiz files under Term 1 regardless of when it was
taken, so Term 2 gradebooks will silently absorb Term 1 quiz scores.

## M-7 · `source_type="report_card_ready"` is not a valid notification source type

`report_card_service.py:149`. `models/notification.py:8-20` defines `report_card`, not
`report_card_ready`. `notify.py:59-63` deliberately does not validate, so the row lands
with an unknown type: no icon in `NotificationBell.tsx:27-42`, no route mapping, invisible
to any future filter. Exactly the vocabulary-drift class the library-loan bug came from.

## M-8 · The notification bell cannot route announcements

`NotificationBell.tsx:47-57` `SOURCE_ROUTE` has no `announcement` key, so `routeFor`
falls back to the role dashboard (`:60-62`). Clicking *any* announcement notification —
including the ones the new announcement engine dispatches, and stream-post announcements —
lands on the dashboard rather than the feed. The icon exists (`:38`); only the route is
missing.

## M-9 · Calendar events are never updated or deleted

`calendar_sync_service.py` is add-only — every branch is `if not existing: add`. Nothing
in `timetable.py` or elsewhere touches `calendar_events`. Moving a timetable slot adds a
second event and leaves the first; deleting an assignment leaves its deadline on every
student's calendar permanently. Grows monotonically.

---

# MINOR

- **N-1 · Seeded report cards had `attendance_percentage = NULL`.** My own
  `seed_person_b_riverside.py:513` passes `attendance_percentage=None`. Regeneration
  populates it (88.9 / 71.0 above). My gap, not Person B's — worth fixing in the seeder.
- **N-2 · `_get_enrolled_student_ids` ignores `is_primary`** for the subject branch
  (`classroom.py:126-131`), so an elective enrollment can pull in the whole homeroom.
- **N-3 · Stream-post announcements notify students only** (`classroom.py:380`) — not
  parents, not co-teachers.
- **N-4 · `GradebookEntry.assessment_id` has no FK.** Deleting a quiz cascades its
  attempts but leaves the gradebook entry orphaned with a dangling `assessment_id`.
  Arguably intentional (grades survive), but undocumented.
- **N-5 · No `<th scope=...>` on any Person B data table.** PROVEN by scan: `scope=`
  count is 0 in GradebookPage, ReportCardsPage, SubmissionTracker, DigitalLibrary,
  BulkRemarks. Screen readers cannot associate cells with headers.
- **N-6 · `aria-` attribute count is 0 on all 11 Person B screens.** Icon-only controls
  are unlabelled.
- **N-7 · N+1 queries.** `_format_quiz` (`quizzes.py:127-131`) issues 3 lookups per quiz
  and is called per row by `list_quizzes`; `_format_submission`, `_format_assignment` and
  the report-card loop follow the same pattern. Fine at Riverside scale, visible at 30+.

---

# Frontend: what needs a human in a browser

Static analysis only — I have not opened these.

| Screen | Loading | Error | Table | `overflow-x` |
|---|---|---|---|---|
| GradebookPage | ✅ | ✅ | 2 | ✅ 2 |
| SubmissionTracker | ✅ | ✗ | 1 | ✅ |
| DigitalLibrary | ✅ | ✗ | 1 | ✅ 2 |
| BulkRemarks | ✅ | ✗ | 1 | ✅ 2 |
| **ReportCardsPage** | ✅ | ✅ | **1** | **✗ NONE** |
| HomeworkCalendar | ✅ | ✗ | 0 | ✅ |
| ClassroomStream | ✅ | ✅ | 0 | ✅ |
| StudentAnalytics | ✅ | ✗ | 0 | ✗ |
| Assignments / Quizzes / Resources | ✅ | ✅/✗ | 0 | ✗ |

**390px prediction:** `ReportCardsPage.tsx:252` renders `<table className="w-full …">`
inside a `max-w-3xl` dialog with **no horizontal scroll container** — the only wide table
without one. Highest-probability overflow. Gradebook, SubmissionTracker, DigitalLibrary
and BulkRemarks all wrap theirs. **UNVERIFIED — needs a browser at 390px.**

Six of eleven screens have no error branch: a failed query renders an empty shell rather
than a message. Empty is acceptable per the brief; silent failure is the risk.

**No dead code found in the "two resources hooks":** `src/hooks/useResources.ts` is a
one-line re-export of `src/api/hooks/useResources.ts`. Both pages are live and reachable
(teacher → Person C's; other roles → Person B's). Neither is dead; see `pb-01-seams.md`
S-A. Which should be canonical is a product decision, not a bug.

---

# Checked and handled — no bug

- Answer-key leakage (above) — gated correctly.
- Duplicate quiz attempts — blocked, `quizzes.py:347-351`.
- Quiz enrollment checks — present on detail and attempt.
- Submission overwrite after grading — blocked, `assignments.py:466-471`.
- Cross-student submission — `submit_assignment` derives `student_id` from the token, never the body.
- Deadline timezone — `_to_utc` (`assignments.py:128-132`) normalises naive datetimes before comparison; no `DatatypeMismatch` class of error here (unlike the `Exam` bug fixed earlier).
- Weights not summing to 1.0 — renormalised by `total_weight_applied` (`gradebook_service.py:119-120`).
- Unknown `assessment_type` — defaults to weight 0.10 (`:115`).
- Zero graded assessments — guarded, returns `None` (`:90-98`, `:181-186`).
- Division by zero across gradebook, analytics, report cards — every site guarded.
- Report card idempotency — **PROVEN**: generating twice for Diya left exactly **1** row
  (upsert at `report_card_service.py:99-112`). No duplicate gradebook counting.
- `source_data_snapshot` — genuinely populated; **overwritten on regeneration**
  (`:114`), so an old card *does* change retroactively. Design choice, flagged not fixed.
- Bulk performance — **PROVEN** 1.2s for 2 students (0.6s each), ≈49 students inside the
  30s bar. Not a concern at Riverside scale.
- FK cascades — `ondelete="CASCADE"` and `delete-orphan` on assignments→submissions,
  quizzes→questions/attempts, classrooms→posts. No orphans except N-4.
- Upload size limits and empty-file checks — present on both upload paths.
- Path traversal — filenames are prefixed with `uuid4()` and used as object keys, not
  filesystem paths (`assignments.py:420`, `classroom.py`); collisions impossible.

# Explicitly NOT re-litigated (per brief)

The 13 client-supplied `school_id` GETs; the `test_staffing_api` date fixture;
`resources.updated_at` / `ix_resources_unit` drift.

**The shared `resources` bucket does NOT become a blocker.** Assignment and classroom
uploads store into it (`assignments.py:420`, `classroom.py`), but ingestion is driven by
rows in the `resources` **table** — `ingest_pending` selects `Resource` records
(`ingestion.py:190`) and uploads create `attachments`/`assignment_submissions` rows, never
`Resource` rows. A student submission cannot reach `kb_chunks`. Confirmed by code path;
the condition the brief set for escalation is not met.

---

# CONFIDENTIALITY · Top Doubts read `chatbot_logs` without filtering `bot_type`

**The most serious defect found in this pass.** Recorded separately from the severity
list because it is a confidentiality issue, not a correctness one, and because the
precise blast radius took two rounds of checking to establish — the first framing of it
was wrong in one direction and understated in another.

`chatbot_logs` is shared by all three bots — student Doubt Bot, Parent Assistant, Teacher
Assistant. `services/doubt_insights.py::_fetch_logs` filtered on school, grade, subject
and date, and **never on `bot_type`**. The teacher-facing "Top Doubts" widget therefore
drew from every bot's history.

## What was actually exposed, path by path

| Path | Condition | Parent queries exposed? |
|---|---|---|
| **Clustering** (`usable`) | ≥ 3 embedded logs for the (grade, subject) pair | **No** — filtered out by the embedding guard |
| **Degraded fallback** (`rows`) | < 3 embedded logs | **YES — verbatim, to a teacher** |

**The clustering path was protected, and not by accident.** `bots.py:235` deliberately
omits `query_embedding` when `bot_type="parent"`, precisely so parent queries could never
enter the student clustering pool. Verified live: all 8 Riverside parent logs have
`query_embedding IS NULL`, and `doubt_insights.py:230` keeps only rows where it is not
null. That write-time decision did its job and is worth preserving as defence in depth
even now that the read-time filter exists.

**The fallback path was not protected.** `doubt_insights.py:232-251` returns "recent
distinct questions, unlabelled" when there are too few embeddable logs, and reads from
`rows` rather than `usable` — a deliberate choice, since an unembeddable question is
still a real question. With no `bot_type` filter, that path listed **parent queries
verbatim to teaching staff**, including *"does Diya have ADHD or a learning disability?"*

On Riverside data the leak did not fire for Grade 3 Math (24 embedded student logs → the
clustering path), but **Grade 1 and Grade 2 have zero student logs**, so every request for
those pairs took the fallback. The exposure was one thin grade away, not hypothetical.

## Separately, teacher prompts DID contaminate clustering

`bot_type="teacher"` logs **do** carry embeddings (`bots.py:461`), so Teacher Assistant
prompts — *"give me 5 MCQs on fractions"* — entered the student-doubt clustering pool with
nothing filtering them out. Less sensitive than the parent case, and fully live.

## The fix

One filter at fetch time, so it closes both paths at once:

```python
return [
    (log, section) for log, section in rows
    if log.bot_type == "student" and _is_academic_doubt(log.query)
]
```

Covered by `test_top_doubts_excludes_parent_bot_questions`, which asserts a parent query
and a teacher query are both absent while a real student doubt survives.

## Scope check: no second instance

Every reader of `chatbot_logs` was audited. Three consumers exist: `routers/bots.py`
(writes only), `services/doubt_insights.py` (fixed here), and
`scripts/seed_riverside_fixtures.py` (writes student logs). No other insight, analytics
or export path touches the table, so this leak had exactly one site.

## Also fixed alongside it, and much less important

The widget's top cluster was labelled *"Casual Greetings — students are opening the chat
with casual greetings without asking academic questions"*: a true statement about the
data and useless as an insight. `_is_academic_doubt` drops pure small talk while keeping a
greeting that wraps a real question ("hi miss why do we carry the one"). This is the
cosmetic half of the change and should not be confused with the confidentiality half.
