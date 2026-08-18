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

---

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
