# Route-health sweep — merged `samiksha` (post Person B merge)

Read-only. Every GET called against real Riverside (school 5707) data as a real
signed-in user of each role. No fixes applied. Commit `eda8bf1`.

| | |
|---|---|
| Total routes | 199 |
| GET routes swept | 85 |
| Skipped (SSE, hang by design) | 2 |
| Not called (mutating verbs) | 112 |
| **Endpoints returning 5xx** | **3 — all Person B** |
| 200 with an empty collection | 23 |
| 404 on a missing id (correct) | 10 |
| Dead nav links | 0 |

---

## ERRORS — 5xx / unhandled exception

All three are Person B code calling Person A/C models with attribute names that do not
exist. All three are independent of the merge: the model attributes they get wrong
(`RiskFlag.reasons`, `Exam.exam_type`) are unchanged by it, and neither service file was
edited during the merge.

### E1 · `GET /analytics/student/{student_id}` — crashes only for AT-RISK students
`app/services/analytics_service.py:80` — **Person B**

```python
risk_reasons = [f.reason for f in risk_flags] if is_at_risk else []
```

`RiskFlag` has **`reasons`** (a JSONB list), not `reason`. Because the comprehension sits
behind `if is_at_risk`, it is never evaluated for a student with no open flag.

| Called for | Result |
|---|---|
| Aarav (21533, no flag) | **200 OK** |
| Diya (21546, open medium flag) | **AttributeError → 500** |

This is the worst shape a bug can take for a demo: the screen works on every healthy
student and fails on exactly the at-risk ones the feature exists to show. Diya is the
demo's flagged child.

Backs the **Student Analytics / My Analytics / Child Analytics** nav entry — present in
**all five** role menus.

### E2 · `GET /calendar/homework/{student_id}` — 500 for every caller
`app/services/calendar_sync_service.py:178` — **Person B**

```python
from app.models.school import SchoolClass   # SchoolClass lives in app/models/class_.py
```

`ImportError` on every call, every role. Previously reported from the test suite
(`test_homework_calendar_events`); confirmed here against live data.

### E3 · `GET /calendar/{user_id}` — 500 for every caller
`app/services/calendar_sync_service.py:155` — **Person B**

```python
title=f"Exam: {ex.name}"    # Exam has no `name` column (it has `exam_type`)
```

`AttributeError` on every call, every role. **New — not caught by the test suite.**

Together E2 and E3 mean **Person B's entire calendar router is non-functional**: both of
its GET endpoints raise. The **Homework Calendar** nav entry appears in all five role
menus and cannot render for anyone.

---

## EMPTY BUT HANDLED — 200, no data, renders fine

### Person B screens: empty in Riverside because their data is in school 6318

Row counts, measured:

| table | 5707 | 6318 |
|---|---|---|
| classrooms, assignments, quizzes, library_items | **0** | 1 each |
| report_cards | **0** | 2 |
| gradebook_entries, gradebook_weights, remarks | **0** | 0 |
| submissions, quiz_attempts, library_loans, calendar_events | **0 anywhere** | |

Returning `200 []` cleanly: `/assignments`, `/assignments/{class_id}`,
`/classroom/my-classrooms`, `/quizzes`, `/library/catalog`, `/library/loans`,
`/library/my-loans/{id}`, `/report_cards/{id}`, `/remarks/{id}`, `/gradebook/{id}`.

Detail routes correctly **404** rather than crashing when the id does not exist in 5707:
`/assignments/detail/{id}`, `/assignments/{id}/submissions`, `/classroom/{id}`,
`/classroom/{id}/stream`, `/quizzes/detail/{id}`, `/quizzes/{id}/results`,
`/report_cards/detail/{id}`.

### Person A/C endpoints legitimately empty in the current seed

`/admin/ocr/documents` (no OCR runs), `/admin/admissions/applications`, `/admin/exams`,
`/admin/exams/seating`, `/admin/exams/invigilations/me`, `/admin/fee-payment-requests`
(none raised yet), `/syllabus/summary`, `/audit/by_user/{id}`, `/audit/by_object/...`,
`/staff/my-substitute-duties`.

Populated and healthy: `/parent/children` (2), `/parent/child/{id}/summary`,
`/remarks/student/{id}` (6 each), `/attendance/summary` (2), `/attendance/analytics`,
`/attendance/register`, `/attendance/my-records`, `/staff/leave_requests` (6 for admin),
`/notifications` (2 for parent and teacher), `/bots/insights/my-top-doubts` (1 cluster),
`/admin/staffing/forecast`, `/resources`, `/threads`.

---

## UNVERIFIABLE — needs a browser, or not safely callable

- **2 SSE endpoints**: `/admin/alerts/stream` and `/notifications/stream` return
  `text/event-stream` and never close. Correct for the live Command Center feed, but a
  plain GET blocks forever — it stalled this harness for 20 minutes. Any naive client,
  health check or uptime probe pointed at them will hang. (`/classroom/{id}/stream` is
  **not** SSE despite the name — ordinary JSON.)
- **112 mutating routes** (POST/PUT/DELETE) — not called; a read-only sweep must not write.
- Rendering, loading and error states for every screen — browser only.

---

## Nav / role findings

**No dead links.** All 102 `navConfig.ts` paths resolve against the 122 `ROUTE_CONFIG`
entries in `App.tsx`.

**No nav entry 403s for the role it is shown to.** Several 403s in the raw matrix were an
artifact of the harness requesting Diya's id while signed in as Aarav; re-tested with each
student's own id, every student-facing route returns 200. The role gates are correct.

**2 nav entries per role are backed by a 5xx** — *Student Analytics* (E1, for flagged
students) and *Homework Calendar* (E2/E3, always). Both appear in all five role menus.

**11 Person B nav entries per role render empty for a Riverside user**: Classroom,
Resources, Assignments, Quizzes, Gradebook, Report Cards, Digital Library, Homework
Calendar, Student Analytics, Remarks, Syllabus Pace.

**Ordering problem.** Those 11 sit at positions **2–12** in the admin, principal and
teacher menus — directly under the dashboard, above every Person A/C feature that has
data. Fees lands at **21 of 24** for admin and principal, 19 of 21 for teacher: below the
fold at common window heights. A judge clicking top-down hits eleven empty screens before
reaching anything populated.

---

## Zero-row crash patterns — clean

Every division site is guarded: `gradebook_service` (`if all_pcts else 0.0`,
`if subject_percentages`, `by_category` built only from non-empty lists),
`risk_scorer:142` (early return when there are no remarks), `staffing_forecast:75`
(`if total_teacher_count <= 0`), `syllabus_pace:83` (degenerate-term guard),
`ocr_postprocess:147` (`if not matched`), `anomaly_detector:228` (`if not others`).
No unguarded `max()` over a possibly-empty sequence, and no unguarded `[0]` in a request
path.

`.one()` appears 18 times. Most are `Role.name == '...'` lookups, safe because roles are
seeded. Seven dereference a foreign key and would 500 on a dangling row —
`staffing.py:821-824` and `parent.py:573-576`. Not reachable with current data; fragile
rather than broken.

---

## Separate finding: cross-tenant scoping gap (Person A/C, pre-existing)

13 GET endpoints accept `school_id` as a **client-supplied query parameter** and use it
directly, without checking it against the caller's own `user.school_id`:

`/admin/admissions/grade-levels`, `/enrollments`, `/admin/ocr/documents`,
`/admin/ocr/documents/{id}`, `/admin/fees/schedules`, `/admin/schools/{school_id}`,
`/admin/classes`, `/admin/subjects`, `/admin/rooms`, `/parents`, `/students`, `/teachers`,
`/admin/staffing/forecast`.

An authenticated admin of one school can read another school's master data by changing one
query parameter. `/reference/lookup` is the only one that consults `user.school_id` — and
even there it is a *fallback* (`school_id or user.school_id`), not a check, so an explicit
foreign id is still honoured.

Pre-existing and unrelated to the merge, but it is the same recurring class this repo has
hit before, and it is 13 endpoints wide. Not fixed — reported only.

---

## Priority

1. **E2/E3 — Person B's calendar router**: two one-line fixes (`app.models.class_`, and
   `ex.exam_type` or a real title field). Currently 500s for every role, from a nav entry
   all five roles can see.
2. **E1 — `f.reason` → `f.reasons`**: one line. Breaks Student Analytics for exactly the
   at-risk students the screen is meant to surface.
3. **Sidebar order**: move Person B's 11 academics entries below the operational ones, or
   group the menu. Highest visibility, zero backend risk.
4. Cross-tenant `school_id` audit — 13 endpoints, post-demo.
5. `.one()` hardening on FK dereferences — post-demo.

---

## RBAC matrix — enforcement, and one amendment to the matrix itself

Audited against the five-role feature matrix and fixed. Three classes of gap existed;
all three are now enforced and covered by regression tests in
`backend/tests/test_route_health_regressions.py`.

### 1. Parents could read any student's records (fixed)

Every per-student endpoint guarded with:

```python
if user.role == "student" and user.id != student_id: 403
```

which constrains **students only**. No parent-link check existed anywhere in Person B's
code, so any authenticated parent could read any student's records by changing the id in
the URL. Verified live before the fix: `guardian.kumar`, parent of 21533 and 21546, got
**200** on student 22401's gradebook.

Replaced eight near-duplicate inline checks with `assert_can_view_student_record()` in
`app/services/scoping.py`, covering `/gradebook/{id}`, `/report_cards/{id}`,
`/report_cards/detail/{id}`, `/analytics/student/{id}`, `/remarks/{id}`,
`/calendar/homework/{id}`, `/calendar/{user_id}` and `/library/my-loans/{id}`.

### 2. Teachers could read students they do not teach (fixed)

Gradebook, report cards, analytics and remarks had no teacher scoping at all. Now
enforced as **homeroom UNION timetable-taught** (`classes_taught_by`).

> **Why the union, and not `teacher_class_ids()`.** That helper is homeroom-only by
> design. On live Riverside data, scoping Meera Iyer by homeroom alone would have cut
> her from **12 students to 2**, removing Grade 3 - B and with it the cross-section Top
> Doubts cluster. Kavya Reddy has no homeroom at all and would have dropped to **zero**.

**Impact on the demo: none.** All three Riverside teachers appear on the timetable for
all four classes, so each still sees all 12 students. The control is real but cannot be
demonstrated on this data — there is no student any Riverside teacher does not teach. It
is proved by a synthetic fixture in the test suite instead.

### 3. Parents could reach Classroom Stream and Digital Library (fixed)

Both were reachable by any authenticated parent because the handlers only gated their
WRITE paths. Now `deny_parent()` on `/classroom/my-classrooms`, `/classroom/{id}`,
`/classroom/{id}/stream`, `/library/catalog` and `/library/my-loans/{id}`, and the
parent nav entries for Classroom and Digital Library were removed.

### AMENDMENTS TO THE MATRIX

Two entries in the original five-role matrix were amended by decision on 2026-08-18,
rather than the code being restricted to match them. Both are recorded here, in the
relevant docstring, and asserted by a test — so the matrix and the code stay in sync and
nobody "restores" the original rule and breaks a working screen.

#### Amendment 1 — Resources is parent-accessible

The matrix originally listed **Resources Library → Parent: No Access**. That has been
**amended to allow parent read access**, by decision on 2026-08-18: a parent seeing
their child's course material is reasonable, and it was already built and shipped in the
parent nav.

`/resources` therefore deliberately does **not** carry `deny_parent()`. Asserted by
`test_parent_keeps_access_to_resources`.

#### Amendment 2 — Digital Library splits: catalogue denied, own child's loans allowed

The matrix listed **Digital Library → Parent: No Access**, and that was first enforced
across the whole feature. It has been **amended to split the surface**:

| Endpoint | Parent | Why |
|---|---|---|
| `GET /library/catalog` | **403** | School-wide catalogue. Staff and students only. |
| `GET /library/my-loans/{child_id}` | **200 for their own child** | Per-child. A parent seeing their child's borrowed and overdue books is parent-portal territory. |

`my-loans` is gated by `assert_can_view_student_record()` — the same parent-link check as
gradebook and report cards — so a parent still gets **403** on a child who is not theirs.
It is deliberately NOT `deny_parent()`.

This matters concretely: Diya Kumar has a seeded overdue library book, which is part of
the same at-risk picture as her attendance, her negative remarks and her overdue fee.
Blocking the endpoint outright would have hidden it from the one person meant to act on
it. Asserted at the boundary by `test_parent_sees_own_childs_loans_but_not_the_catalog`.

### Also fixed: Teacher Bot was on the admin and principal dashboards

`POST /bots/teacher/ask` was gated `require_role("teacher", "admin", "principal")` and
routed at `/admin/assistant` and `/principal/assistant`. It is a lesson-planning and
quiz-authoring assistant scoped to the grades the caller teaches, and admin and principal
have no teaching scope for it to resolve. Now `require_role("teacher")`, with both routes
and both nav entries removed.

### Still not enforced (pre-existing, deferred)

- Cross-tenant `school_id` query parameters — 13 endpoints, listed above.
- Person B's `POST /assignments` authorization gap (`test_unauthorized_teacher_cannot_create`).
- No school-scope check on `GET /classroom/{id}`, `GET /gradebook/class/{class_id}`,
  `POST /report_cards/generate/{student_id}`, `POST /calendar/sync`.

---

## Method caveat — one feed was fetched with a dependency override

During the announcements checkpoint, every feed was fetched with a real Supabase
sign-in **except one**: the Grade 1 student's, because the non-demo Riverside students
had no known password. That one used a FastAPI dependency override, which bypasses the
real auth path — so it demonstrated the *scoping* but not the *authentication* around it.

Closed since: `student1.1786787329065@riverside-school.test` (Ananya Joshi, Grade 1 - A)
was added to `DEMO_LOGINS`, so her password is reset to the shared demo password on every
seed run and she can be signed into like any other demo account. Verified with a real
token — her feed returns the school-wide announcements and **not** the Grade 3 or 3-A
ones.

That matters beyond tidiness: showing the *absence* of a Grade 3 announcement in a real
browser is more convincing than asserting it in a test, and it needs a real login to do.
