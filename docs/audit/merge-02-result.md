# Merge 02 — Result: `akshaya` → `samiksha`

**Phase 3 output.** Branch `integration/b-into-ac`, merge staged and **not committed**.
Companion to `merge-01-conflicts.md` (conflict map) and `remarks-disconnect.md`.

## Headline

| | |
|---|---|
| Full suite (after the fix below) | **1164 passed, 3 failed** in 12:05 |
| First run, before the fix | 1163 passed, 4 failed in 12:01 |
| Pre-merge baseline (`samiksha`) | 1114 passing |
| Real integration breaks | **1 — found and FIXED** |
| Pre-existing failures inherited from either branch | **3** |
| Route table | 199 routes, 0 duplicates, nothing dropped |
| Migration graph | single head `d1e99005e005`, DB stamped, no DDL run |
| Demo paths | all working; one stale-notification cosmetic issue |

Test count reconciles: 1114 (samiksha) + 49 (Person B's six test files) + 4 (new
regression tests written this session) = 1167 = 1163 + 4.

**Caveat on the baseline.** 1114 was measured before 2026-08-18. Re-running one of the
failures against unmerged `samiksha` today shows it failing there too, so today's true
`samiksha` baseline is **1113 passing / 1 failing**, not 1114/0. See failure 4.

---

## The four failures, individually

Every one was re-run against its own unmerged branch in a throwaway git worktree, so
"pre-existing" below is a measured result, not an inference.

### 1. `tests/test_assignments_api.py::test_unauthorized_teacher_cannot_create`
**Owner: Person B. Pre-existing — not a merge break.**

```
tests\test_assignments_api.py:166: in test_unauthorized_teacher_cannot_create
    assert res.status_code == 403
E   assert 201 == 403
```

A teacher who should not be able to create an assignment for a class **can** — the
endpoint returns `201 Created` where the test demands `403`. Reproduced identically on
unmerged `akshaya`. This is an authorization gap in Person B's own
`POST /assignments`, and it is a genuine defect, not a stale test: the test states the
intended rule and the code does not implement it.

Left failing, as instructed. **Person B should fix the endpoint, not the test.**

### 2. `tests/test_person_b_comprehensive_api.py::test_homework_calendar_events`
**Owner: Person B. Pre-existing — not a merge break.**

```
app\services\calendar_sync_service.py:178: in get_homework_calendar_events
    from app.models.school import SchoolClass
E   ImportError: cannot import name 'SchoolClass' from 'app.models.school'
```

A plain wrong import — `SchoolClass` lives in `app/models/class_.py`, not
`app/models/school.py`. `GET /calendar/homework/{student_id}` raises a 500 on every
call. Reproduced identically on unmerged `akshaya`.

Worth knowing: `calendar_sync_service.py` is one of the four files touched by akshaya's
commit `6ccbe0c` ("last changes"), which landed **after** the Person B report was
written — so this is newly broken on their branch and the report predates it.

One-line fix (`from app.models.class_ import SchoolClass`), not applied — it is Person
B's file and the instruction was to report, not fix.

### 3. `tests/test_rag_pipeline.py::test_student_requesting_another_grade_gets_403_not_empty_list`
**Owner: Person A/C. → THE ONE REAL INTEGRATION BREAK — now FIXED, test passes. ←**

```
tests\test_rag_pipeline.py:610: assert resp.status_code == 403
E   assert 200 == 403
```

**Passes on unmerged `samiksha`. Fails merged.** Caused by akshaya's `list_resources`
replacing samiksha's wholesale — exactly the silent-win class flagged in Phase 1, on
exactly the file flagged there.

samiksha's `GET /resources` rejected an out-of-scope grade outright:

```python
if grade_level is not None:
    # A grade outside the caller's scope is a 403, never a silently empty list -
    # an empty list would read as "no resources exist" rather than "not yours".
    if allowed is not None and grade_level not in allowed:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized to view this grade's resources")
```

akshaya's replacement has no such check — it applies `grade_level` as one more filter
on top of an already role-scoped query.

**Severity: weakened boundary, not a data leak.** The adjacent test
`test_student_listing_resources_sees_only_their_own_grade` still **passes**, because the
role-scoping `or_(...)` clause still constrains the student to their own grade. A grade-3
student asking for grade 4 now receives `200 []` instead of `403`. No other grade's
material is exposed.

But the failing test's docstring is the whole point: *"403, never a silently empty list
— an empty list reads as 'nothing exists here' rather than 'not yours', which hides the
boundary from anyone testing it."* The security property survives; the ability to
observe it does not.

**FIXED.** `list_resources` now tracks `allowed_grades` (the student's enrolled grades /
the teacher's taught grades; `None` for admin and principal, meaning unrestricted) and
raises `403` when `grade_level` falls outside it — restoring samiksha's boundary while
keeping every other change akshaya made to that endpoint (`class_id`, `unit`,
`file_type`, `q` filters and the class-or-grade `or_` scoping).

The guard carries a comment explaining why it is load-bearing despite not protecting
data, so the next person merging over this file does not delete it as redundant:

> THIS LINE IS LOAD-BEARING AND HAS BEEN LOST ONCE ALREADY. The role filters above
> already prevent another grade's material from being returned, so deleting this guard
> does not leak data — which is exactly why it is easy to drop by accident and hard to
> notice. What it protects is the ABILITY TO OBSERVE the boundary.

Verified: the failing test now passes, as do
`test_student_listing_resources_sees_only_their_own_grade` and all of Person B's
`test_resources_library_api.py` (10 passed), and the full suite is 1164/3.

### 4. `tests/test_staffing_api.py::test_my_substitute_duties_returns_the_confirmed_assignment`
**Owner: Person A/C. Pre-existing time bomb — not a merge break.**

```
tests\test_staffing_api.py:718: assert len(duties) == 1
E   assert 0 == 1
```

**Fails on unmerged `samiksha` too.** The test hardcodes a leave date of `2026-08-17`
and carries the comment *"A future Monday … must stay in the future relative to whenever
this suite runs."* Today is **2026-08-18**. The date went into the past yesterday.

The endpoint filters `LeaveRequest.end_date >= today` (`app/routers/staffing.py:908`),
so the confirmed substitution is correctly excluded and the test correctly fails. The
code is right; the fixture expired.

This is what drops today's real `samiksha` baseline from 1114 to 1113. Not fixed — but
it will fail every day from now on, so it wants a relative date before anyone trusts a
green suite again.

---

## Migration state

| | |
|---|---|
| `alembic_version` **before** | single row, `c4d88004d004` |
| `alembic stamp d1e99005e005` | ran; zero DDL |
| `alembic_version` **after** | single row, `d1e99005e005` |
| `alembic heads` | `d1e99005e005 (head)` — single |
| `alembic current` | `d1e99005e005 (head)` |

The stamp was safe because every object from *both* chains was verified physically
present first: `fee_payment_requests`, `doubt_threads`, `thread_replies`, `quizzes`,
`gradebook_entries`, `report_cards`, `remarks`, `classrooms`, `kb_chunks.source_type`,
`uq_fee_payment_request_one_open`, `ix_kb_chunks_embedding_hnsw`. The version table had
simply been overwritten — both developers ran migrations against the same database and
each `upgrade` clobbered the other's row; akshaya's ran last.

`alembic check` now runs (it refused before, with *"Target database is not up to
date"*) and reports exactly four items, all expected and all documented in `CLAUDE.md`:

1. `remove_index ix_kb_chunks_embedding_hnsw` — **permanent false positive, never apply**
2. `remove_index uq_fee_payment_request_one_open` — **permanent false positive, never apply**
3. `modify_nullable resources.updated_at` — known cosmetic drift, deliberately left
4. `add_index ix_resources_unit` — genuine but trivial; deferred post-demo by decision

---

## Seed pinned, and two further bugs found while pinning

`SEED_ANCHOR_DATE = date(2026, 8, 18)` now anchors every generated date, including the
fee due date. `ATTENDANCE_SCHOOL_DAYS` dropped 30 → **21**, so the window spans 28
calendar days and sits *inside* `ATTENDANCE_LOOKBACK_DAYS = 30` instead of overflowing
it by ~12 days.

Pinning alone would have done nothing, and two additional defects had to be fixed for it
to take effect:

- **`_get_or_create_attendance` skipped days that already had a row**, so a changed
  pattern could never apply — the fixtures kept whatever an earlier run wrote. It now
  **realigns** an existing row's status to the pattern. Inserts and updates only, never
  deletes: the genuine `source="cv"` rows from the real CV-attendance run on 2026-08-15
  are untouched.
- **The "Parent-portal profiles" printout queried every attendance row ever created**,
  with no date filter at all, while the portal and scorer both look back 30 days. Under
  that heading it could never agree with the parent portal. It now uses the same window.

A `_warn_if_anchor_is_stale()` guard prints a loud warning once the window ages out of
the lookback — the failure it guards against is silent: `_attendance_component()` returns
`(0.0, None)` on zero records, Diya's flag is downgraded, and the demo's best beat
disappears with no error anywhere.

### The real checklist figures (portal-computed, replacing the stale 47.6%)

| | Aarav Kumar (21533) | Diya Kumar (21546) |
|---|---|---|
| Attendance | **81.5%** (P22 / A4 / L1 over 30d) | **59.1%** (P13 / A9 / L0 over 30d) |
| Risk flag | **none** (healthy) | **medium**, score 0.366 |
| Banner reason 1 | — | `attendance rate 59% is below the 90% threshold` |
| Banner reason 2 | — | `recent teacher remarks skew negative (avg sentiment -0.44)` |
| Remarks | 6 (positive, +0.637 / +0.818) | 6 (negative, −0.649 / −0.542) |
| Fee | paid | **overdue** |

**The differential holds**: healthy vs flagged, positive vs negative sentiment, paid vs
overdue. The seed's own printout now reports 22/27 (81%) and 13/22 (59%) — matching the
portal exactly, which was the point of the window fix.

**Banner/card agreement verified empirically**, as requested. The attendance card shows
**59.1%**; the banner reason string says **"attendance rate 59%"**. Same number, and it
is *computed* at scoring time (`risk_scorer.py:113` builds the string from the live
rate), not copied from the seed's hardcoded constant. The Parent Bot independently
states *"present for 13 days and absent for 9 days, giving her an attendance rate of
59.1%"* — the same figure a third time, on a third surface.

### Why Aarav is unflagged at 81.5% — what the composite actually weighs

Aarav sits at **81.5%**, itself below the 90% threshold, and is still unflagged. A judge
reading the two numbers side by side will ask why. Computed from the real scorer, not
from reading the code:

| | Aarav | Diya |
|---|---|---|
| Attendance | 22/27 = **81.5%** | 13/22 = **59.1%** |
| Attendance component risk | 0.094 | 0.343 |
| Composite score | **0.073 → LOW** | **0.366 → MEDIUM** |
| Score without the remark signal | 0.095 → LOW | 0.343 → MEDIUM |
| Remarks shift the score by | −0.022 | +0.023 |

`DEFAULT_WEIGHTS` is `attendance 0.50 / grades 0.35 / remarks 0.15`, but **grades have no
backing table in this schema**, so that signal is always missing and the remaining
weights are renormalised: in practice **attendance 76.9%, remarks 23.1%**. Bands are
low ≤ 0.30, medium ≤ 0.60, high > 0.60.

**The correct explanation is that the attendance component is proportional, not a
cliff.** 90% is where risk *starts accruing*, not where a flag fires. Aarav is 8.5 points
under it, which maps to 0.094 — nowhere near the 0.30 flag line. Diya is 31 points under,
which maps to 0.343 and crosses it on attendance alone.

**An earlier draft of this document said Aarav's positive remarks are what keep him
unflagged. That is wrong** — the table above shows both children land in the same band
with or without the remark signal. Remarks move each score by about ±0.02. They are
corroborating evidence, not the deciding factor.

Positive remarks *do* buy real relief, just not enough to matter at Aarav's distance from
the line: a student with no remark signal is flagged below **63%** attendance, while one
with neutral-or-positive remarks is flagged below **54.9%**.

Safe things to say on stage:
- *"Ninety percent is where risk starts accruing, not where the flag fires. Aarav is a
  few points under; Diya is thirty under, and that's the difference the score reflects."*
- *"It's a weighted composite of attendance and remark sentiment — grades aren't in this
  schema, so the weights renormalise onto the two signals we actually have."*
- *"Diya's negative remarks show up as a second reason on the banner. They corroborate
  the attendance signal rather than cause the flag."*

Avoid claiming remarks are what separate the two children — the numbers don't support it.

Aarav's 4 absences are the real `source="cv"` period-level rows from an actual CV
attendance run, deliberately left untouched by the seed.

---

## Demo-path checks

All run against the real endpoints through real Supabase sign-in — no dependency
overrides, because the scoping is part of what is being verified.

| Path | Result |
|---|---|
| `GET /parent/children` | 200 — Aarav 21533, Diya 21546, both Grade 3 - A |
| `GET /remarks/student/21533` as `guardian.kumar` | 200 — **6 remarks**, `{label, compound}` intact |
| `GET /remarks/student/21546` as `guardian.kumar` | 200 — **6 remarks**, `{label, compound}` intact |
| `GET /parent/child/21546/summary` | 200 — 59.1%, medium flag, 6 remarks, overdue fee |
| `GET /parent/child/21533/summary` | 200 — 81.5%, no flag, 6 remarks, paid fee |
| `POST /bots/student/ask` as Aarav | 200 — grounded, with citations |
| `POST /bots/parent/ask` as guardian | 200 — quotes the portal's own figures |
| `POST /bots/teacher/ask` as Meera | 200 — **works with `class_id` omitted** |
| `GET /bots/insights/my-top-doubts` as Meera | 200 — 3 clusters, **spanning Grade 3 - A and 3 - B** |
| `GET /admin/fee-payment-requests` | 200 — 0 in queue (seed creates none; expected) |
| Notification bell | 200 — parent 1 unread, teacher 1, admin 0 |

The remarks feed is the check that mattered most: the `remark_stubs` read path survived
the merge fully intact, confirming the Phase 1 finding that the reported
`/remarks/student/{id}` collision never existed.

`POST /bots/teacher/ask` succeeding with `class_id` omitted confirms the Phase 2
correction — `chatbot_logs.class_id` was already nullable in this database, so the 500 I
predicted in Phase 1 does not occur here. Migration `d1e99005e005` remains correct for
CI and any fresh environment.

### Two things to know before demoing

**The notification bell is a stale snapshot.** The one unread parent notification
(id 701, created 2026-08-16) reads:

> **Diya Kumar flagged as high risk** — *attendance rate 60% is below the 90% threshold…*

Current state is **59%** and **medium**. Notifications are immutable point-in-time
records — arguably correct behaviour — but a judge who opens the bell and then the portal
sees `60% / high` on one screen and `59% / medium` on the next. The seed deliberately
does not create notifications ("they are a side effect of the real endpoints"); re-firing
`POST /risk/flag` for Diya before the demo would regenerate it with current numbers.

**Pick the Doubt Bot question to match the corpus.** Asked "What are the stages of the
water cycle?", the bot correctly answered *"That is not in your class notes. Please ask
your teacher!"* — right behaviour, wrong question. The only indexed resources are
Photosynthesis, Multiplication/Regrouping, and Nouns/Adjectives. Ask about
photosynthesis or multiplication. (Citations are chunk-level, so one document can appear
as five citation entries — presentational, not wrong.)

Resource titles are clean UTF-8 in the database (`'Grade 3 Science — How Plants Make
Their Food'`); the `�` in captured console output is a Windows console encoding artifact,
not stored data.

---

## Prioritised: what stands between here and demo-ready

1. ~~Restore the `GET /resources` 403~~ — **done**, suite now 1164/3.
2. **Person B: fix the `SchoolClass` import** (failure 2). One line;
   `GET /calendar/homework/{id}` 500s on every call until then. It landed in their
   post-report commit `6ccbe0c`, so they may not know it is broken.
3. **Re-fire Diya's risk notification** so the bell agrees with the portal.
4. **Person B: fix the assignment authorization gap** (failure 1). A teacher can create
   assignments for a class that is not theirs.
5. **Re-pin `SEED_ANCHOR_DATE`** on demo day if it is not 2026-08-18 (~2 days of slack;
   the script warns).
6. Give the staffing test a relative date (failure 4) so the suite can be green again.
7. Post-demo: `ix_resources_unit`; unify the two remark systems
   (`remarks-disconnect.md`); move Person B's uploads off the shared `resources` bucket;
   reconcile `docs/api-contract.md` spec paths with as-built.
