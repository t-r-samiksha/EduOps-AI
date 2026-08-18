# Deferred, by decision

Companion to `pb-01-seams.md` (integration audit) and `pb-02-bugs.md` (bug audit).
Everything here was found, understood, and **deliberately not fixed**. Each entry states
the consequence of leaving it, so none of these reads as an oversight later.

---

## S-E · Teacher Bot quiz-question hook — MOCKED, left mocked

`app/services/quiz_service.py:123-140` `generate_draft_quiz_questions_hook` returns
hardcoded `"Sample question on {topic} #N?"` with `correct_option="A"` for every question,
and has **zero callers**. `POST /bots/teacher/ask` has a keyword-detected "quiz mode"
that only changes the LLM prompt; there is no path from a bot draft into `POST /quizzes`.

**Not fixed because this is building a feature from a stub, not repairing a defect.** A
bot that drafts real quiz questions needs its own design pass: where the questions come
from (the KB, or free generation), how a teacher reviews and edits them before they
become a real quiz, and what happens when the model produces four plausible options and
the wrong key. Wiring the stub through would produce a feature that generates fake
questions convincingly.

**Consequence of leaving it:** the "AI drafts your quiz" capability does not exist. If it
is claimed in a demo, that claim is false. The hook is dead code and safe to delete.

## S-O · Resource update → KB re-index — no update path exists

`app/routers/resources.py` has no PUT or PATCH. The only mutation is DELETE, which
**does** correctly clean the resource's `kb_chunks`
(`resources.py:561-564`, proven live: chunks back to 0 after a 204), followed by a
re-upload which re-ingests.

**Not fixed because the absence is defensible.** "Update fires re-index" is vacuously
false — update does not exist — and delete-then-reupload achieves the same outcome with
no stale-chunk window. Adding an update endpoint means deciding whether a title-only edit
should re-embed (it should not) and whether replacing the file keeps the same id, which
is a design question rather than a bug.

**Consequence of leaving it:** a teacher who wants to correct a resource must delete and
re-upload. The chunk cleanup makes that safe.

## M-6 · Quiz and assignment grades are filed under a hardcoded term

`app/services/gradebook_service.py` now has **one** named `DEFAULT_TERM = "Term 1"`
instead of the literal scattered across call sites, with a docstring explaining why.

**The hardcoding itself remains.** Nothing in the schema maps dates to terms, and
inventing term boundaries was explicitly rejected — the same decision that put
report-card attendance on the academic year rather than a fabricated term range.

**Consequence of leaving it, stated plainly: once Term 2 begins, every auto-graded quiz
and assignment will be filed into Term 1.** A Term 2 gradebook will silently absorb Term
1 scores, and a Term 2 report card built from it will be wrong. This is fine for a demo
that only ever shows Term 1 and is a real defect the moment a second term exists. The fix
is a term calendar (dates → term name) plus passing `term=` at the two call sites;
`DEFAULT_TERM` is the single place that changes.

## N-4 · `GradebookEntry.assessment_id` has no foreign key

`app/models/gradebook.py:32` — `assessment_id: Mapped[int | None]` is a plain integer
pointing at either an `assignments.id` or a `quizzes.id` depending on `assessment_type`.
It is polymorphic, so a single FK is not expressible.

**Not fixed.** Deleting a quiz cascades its questions and attempts but leaves the
gradebook entry behind with a dangling `assessment_id`. That is arguably correct — a
grade a student earned should survive the assessment being withdrawn — but it is
undocumented, and nothing distinguishes "assignment 7" from "quiz 7".

**Consequence:** an orphaned entry still counts toward the term average, and there is no
way to navigate from it back to a deleted assessment. Same shape as `kb_chunks.source_id`,
which solves it with a `source_type` discriminator plus a load-bearing join condition —
the pattern to copy if this is ever tightened.

## N-7 · N+1 queries in the list serialisers

`_format_quiz` (`quizzes.py:127-131`) issues three lookups per quiz — class, subject,
teacher — and `list_quizzes` calls it per row. `_format_submission`,
`_format_assignment` and the report-card generation loop follow the same pattern.

**Not fixed.** At Riverside's scale (2 quizzes, 8 assignments, 5 students) this is a
handful of queries and measurably fine: bulk report-card generation runs 0.6s per student.
The fix is `joinedload`/`selectinload` on each serialiser's relationships, which is
mechanical but touches every Person B list endpoint — a poor trade the day before a demo.

**Consequence:** visible above roughly 30 rows. A class of 40 loading the submission
tracker issues ~120 extra queries. Worth doing before any real deployment; irrelevant now.

## Syllabus pace: `Expected 0%` is ambiguous between "starts today" and "starts later"

`services/syllabus_pace.py:80-82` computes
`expected_fraction = clamp((today - term_start_date) / (term_end_date - term_start_date))`.
`_clamp` floors at 0, so a plan whose `term_start_date` is in the FUTURE yields a negative
elapsed and displays exactly the same **Expected 0%** as a plan starting today.

Observed live in school 6318: Grade 1-A Math starts 2026-08-18 (today) → 0%, while social
studies in the *same class* starts 2026-08-01 → 8%. Both correct; the pair looks like a
bug because `term_start_date` is a **per-plan** column and nothing in the schema owns
"when is Term 1" — the same gap as M-6.

**Consequence:** a plan created with a future term start reports every logged checkpoint as
**ahead of schedule**, because actual > 0 while expected is pinned at 0. Riverside's seeded
plans all start in the past deliberately, so the demo does not show this. The honest fix is
either a `status="not_started"` when `today < term_start_date`, or a school-level term
calendar — a design decision, not a patch.

## Resource scope: the listing and the bot disagree about who can see a class-scoped file

Kept as a deferral because consolidating the two resources pages (`pb-04-duplicates.md`
D-2, Step 2) was skipped — but **this defect is independent of the page duplication and
outlives that decision.**

`resources` carries BOTH `grade_level` (NOT NULL) and `class_id` (nullable). The two read
paths disagree about which one scopes visibility:

| Path | Scopes on | Code |
|---|---|---|
| Listing (`GET /resources`) | `class_id` when set, else `grade_level` | `resources.py` role branches |
| **Bot retrieval** | **`grade_level` only** | chunks stamped at `ingestion.py:174`, filtered at `retrieval.py:186` |

`kb_chunks` has no `class_id` column at all, so a chunk cannot carry class scope even in
principle.

**Consequence, concretely:** a teacher uploads a worksheet scoped to **Grade 3 - A only**.
A Grade 3 - B student does **not** see it in their resources list — correct, and it looks
like the scope is being honoured. But that student asks the Doubt Bot a question it answers,
and **the bot retrieves and cites it**, because retrieval matches on grade 3. The listing
implies an isolation the retrieval path does not provide.

Nobody is currently affected: Riverside's seeded resources are all grade-scoped
(`class_id IS NULL`), so the two paths agree by accident. It becomes live the first time
anyone uploads through Person B's screen, which sends `class_id`.

**Fix shape** (not applied): either add `class_id` to `kb_chunks` and filter on it in
`search_chunks`, or drop class scoping from the listing so both paths agree that grade is
the only unit. The second is smaller and matches what the RAG pipeline already assumes.
Doing it properly means touching upload, listing and retrieval together on a live screen,
which is why it was deferred rather than half-done.

## SCHEMA GAP · Nothing owns "when is Term 1"

Stated on its own because it is one missing concept with **two** distinct symptoms already
recorded above, and a future term-calendar feature should find both consequences written
down in one place.

There is no table, column or constant mapping dates to terms. What exists instead:

- `SyllabusPlan.term_start_date` / `term_end_date` — **per-plan** date columns. Every plan
  carries its own private definition of the term window.
- `GradebookEntry.term` / `GradebookWeight.term` — **free-text strings** (`"Term 1"`),
  with nothing tying them to dates.
- `ReportCard.term` + `academic_year` — the same free text, which is why report-card
  attendance had to be scoped to the **academic year** rather than the term.

### Symptom 1 — M-6: auto-graded work is filed under a hardcoded term

`gradebook_service.DEFAULT_TERM = "Term 1"`. Quiz attempts and assignment grading cannot
derive a term, so they assert one. **Once Term 2 begins, every auto-graded quiz and
assignment still files into Term 1**, and a Term 2 gradebook silently absorbs Term 1
scores.

### Symptom 2 — syllabus pace: two subjects in one class disagree about the term

Because term dates are per-plan, two plans for the same class and academic year can hold
different windows. Observed live in school 6318, Grade 1 - A: Math starts 2026-08-18,
social studies starts 2026-08-01, so the pace tracker reports `Expected 0%` and
`Expected 8%` side by side. Both are arithmetically correct. The pair reads as a bug
because the term is not a shared concept.

And the latent form: a plan whose `term_start_date` is in the **future** yields negative
elapsed, floored to 0 by `_clamp`, so it displays the same `Expected 0%` as a plan starting
today — while every logged checkpoint reads as *ahead of schedule*.

### What the fix would need

A school-level term calendar: `(school_id, academic_year, term_name, start_date, end_date)`,
unique on the first three. Then `term_for(date)` replaces `DEFAULT_TERM` at the two
gradebook call sites, and `SyllabusPlan` reads its window from the calendar instead of
carrying its own dates — collapsing both symptoms. Migration, model, and a backfill for
existing plans; not a patch, and out of scope pre-demo.

---

## SCHEMA GAP · An announcement cannot be scoped to an elective

Surfaced while doing S-D (stream announcements now create real `Announcement` rows).

`SCOPE_TYPES` is `school` / `grade` / `class`. A classroom, however, is
`(class_id, subject_id)` — an elective classroom holds a *subset* of the class. So there is
no scope that says "the students taking Grade 3-A Music".

**How S-D handles it, and the residue.** `publish_announcement(..., audience_override=)`
delivers to the narrowed elective roster only, so the N-2 fix survives and **notifications
are correct**. But the row is stored `scope_type="class"`, and the feed's `can_see()` reads
that scope — so a classmate *not* taking the elective sees the announcement in
`GET /announcements/feed` even though they were never notified.

| | Elective announcement |
|---|---|
| Notified | elective students + linked guardians (correct) |
| Visible in feed | **every student in the class** (wider) |

Not a confidentiality problem — the content is "bring your recorder on Thursday", addressed
to a subset of a class that already shares a room. It is an inconsistency between the
delivery audience and the read audience, and it is **new surface area for the same missing
concept**: the schema has no unit smaller than a class.

**Proper fix** — a fourth scope: `scope_type="classroom"` with `scope_classroom_id`, which
makes `resolve_audience` do the narrowing itself and lets `audience_override` be deleted.
That is a migration (`SCOPE_TYPES`, the CHECK constraint, a nullable FK) plus a
`can_see`/`visible_scope_for` branch — deliberately not attempted in Group 6.

# Needs a real browser — the manual-pass checklist

Everything below was reasoned about from the code or computed arithmetically. **None of it
has been observed running.** Collected here so there is one checklist rather than several
scattered reports.

## Viewport / layout

- [ ] **`ReportCardsPage` table at 390px.** It was the only wide table in the app with no
      horizontal scroll container; it now has `overflow-x-auto` and `min-w-[420px]` inside
      a `max-w-3xl` dialog. Confirm the dialog itself does not push the page sideways.
- [ ] **Mobile drawer at 390px, parent and student roles** (the phone-demo roles).
      Arithmetic only: the drawer is `w-72` (288px) with `px-3`, so ~264px of content;
      grouped children indent `pl-6` (24px), leaving ~240px for icon plus label. Parent is
      flat (15 items, no indent). Longest labels to watch: "Homework Calendar",
      "Digital Library", "Teacher Remarks".
- [ ] **Collapsed icon rail height.** Computed to fit: top-level is 8–9 icons for every
      role except parent (15, flat). At 800px viewport, need 348–392px against ~708px
      available; parent needs 656px, the tightest case. Confirm parent's rail does not
      scroll at 800px.
- [ ] **The other four Person B tables at 390px** — Gradebook, SubmissionTracker,
      DigitalLibrary, BulkRemarks all wrap theirs in `overflow-x-auto` already; confirm the
      Gradebook grid in particular, since it is the widest.

## Sidebar behaviour

- [ ] **Groups appear on desktop hover.** This was broken until Group 4:
      `SidebarNav expanded={false}` was hardcoded while the rail widened via CSS, so the
      collapsible sections rendered only in the mobile drawer. Now React state drives the
      width, the labels and the menu shape together.
- [ ] **Rail width and content cannot desync.** Previously CSS `hover:w-64` and React state
      tracked the same thing separately. Confirm a fast pointer exit, and re-entry via a
      child element, leave the rail consistent.
- [ ] **Keyboard: Tab into the rail opens it; Escape closes it and returns focus out.**
- [ ] **A group containing the active route auto-opens** — navigate directly to
      `/admin/gradebook` by URL and confirm Academics is expanded.
- [ ] **Notification bell click targets.** 12 more source types now route. Confirm an
      announcement notification lands on the feed, and that a type with no route for that
      role (e.g. `quiz_published` as a parent) lands on the dashboard rather than a 404.

## Error and empty states

- [ ] **The five new error branches render** — DigitalLibrary, HomeworkCalendar,
      StudentAnalytics, SubmissionTracker, Resources. Easiest check: stop the backend and
      load each; previously a failed query fell through to the empty state, so a 500 read
      as "No assignments yet".
- [ ] **`BulkRemarksPage` has no error branch.** Its remarks list has no branch structure
      to hang one on without restructuring the component. Left as-is; a failed load shows
      an empty roster.

## Accessibility

- [ ] **Screen-reader pass on the Gradebook grid.** All 35 `<th>` across five tables now
      carry `scope="col"`; every one sits inside `<thead>`, so none needed `scope="row"`.
- [ ] **The three icon-only delete buttons announce their target** — they now carry
      `aria-label={\`Delete assignment: ${a.title}\`}` and equivalents on
      ClassroomStream and Resources, with `aria-hidden` on the icon.
- [ ] **Group headers announce state** — `aria-expanded` plus
      `aria-label="<Group> section, expanded|collapsed"`.

## Quiz timing (new surface in Group 3)

- [ ] **The countdown is anchored to the server's `started_at`.** Start a quiz, reload the
      page, and confirm the timer resumes rather than restarting at full duration.
- [ ] **Running over the limit still submits.** Confirm the student sees "Submitted after
      the time limit — your answers were still graded" and the teacher's results panel
      shows "N ran over time".

---

# Also deliberately untouched (carried over from the brief)

- The **13 GET endpoints taking a client-supplied `school_id`** without checking it against
  the caller's school. Real, pre-existing, 13 endpoints wide, post-demo.
- **`test_staffing_api::test_my_substitute_duties…`** — a hardcoded `2026-08-17` leave date
  that went into the past. The endpoint filters `end_date >= today`, so the code is right
  and the fixture expired. Will fail every day until given a relative date.
- **`resources.updated_at` nullability drift** and the missing **`ix_resources_unit`** —
  both appear in every `alembic check` and are documented in `CLAUDE.md`.
- **The shared `resources` bucket.** Person B's assignment and classroom uploads store into
  it alongside RAG source material. The escalation condition set in the brief — that a
  student submission could reach `kb_chunks` — was checked and is **not met**: ingestion is
  driven by rows in the `resources` *table*, and uploads create
  `attachments`/`assignment_submissions` rows, never `Resource` rows.
