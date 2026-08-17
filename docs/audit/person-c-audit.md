# EduOps AI — Codebase Audit (Person C scope)

Read-only architectural audit. Every claim below cites a file path plus a line number
or symbol name. `NOT FOUND` means no trace in the repo — not "probably elsewhere".

Audit date: 2026-08-16. Branch: `samiksha` @ `e2cb754`. Working tree clean.

---

## Executive summary

**There is no team.** `git log --format='%an' | sort | uniq -c` returns exactly one
author — `Samiksha`, 13 commits, 2026-08-08 → 2026-08-15. The "Person A / B / C"
split exists only in `CLAUDE.md` and `docs/api-contract.md` prose. Every line of
committed code is Person A's operational backbone.

**What works today (verified):** 116 registered routes across 19 routers, 843 passing
pytest tests (`435s`, run against the real Supabase DB), 22 Alembic migrations with
models in sync (`alembic check` → "No new upgrade operations detected", head
`f4d0c4b0a6c9` applied). Auth is real Supabase ES256 JWKS verification. Timetable
generation, CV attendance, OCR, fees, admissions, exam seating, staffing, risk
flags, approvals, audit log — all `IMPLEMENTED` with live-data React screens. The
five dashboards are all real, not shells.

**What's fake:** everything in Person B's and Person C's `api-contract.md` sections.
Zero of it is code. No `notifications`, `announcements`, `chat_channels`,
`chat_messages`, `doubt_threads`, `kb_chunks`, `assignments`, `gradebook`, `quizzes`,
`remarks` (only a `RemarkStub` placeholder), or `resources` table. No LLM client, no
embedding code, no Socket.io, no object storage. Your scope is a greenfield build on
top of a solid, tested Person A foundation.

**Top three risks for a 14-day build:**

1. **Every RAG/chat/notification table, endpoint, and UI is day-1 work.** You inherit
   ~0% of your scope. The one exception is `GET /parent/children` and the multi-child
   selector, which are already live.
2. **Your two biggest dependencies do not exist and are not being built.** The Doubt
   Bot needs curriculum content; the Parent Assistant Bot needs grades. There is no
   `resources` table, no `gradebook`, and no second developer. `GET /parent/children/
   {id}/performance` returns a `gradebook_summary` in the doc — from a table that
   isn't in the schema.
3. **Parent ownership-scoping is copy-pasted inline in four routers with no shared
   helper**, and `GET /reference/lookup` accepts an arbitrary `school_id` from any
   authenticated caller. If you add parent-facing endpoints you will either extend
   the duplication or be the person who factors it out.

---

## Section 1 — Repo orientation

### Directory tree (depth 3, exclusions applied)

```
/
├── CLAUDE.md                  (tracked, but listed in .gitignore — see below)
├── README.md                  (1 line: "# EduOps-AI", UTF-16 BOM)
├── .gitignore
├── backend/
│   ├── .env / .env.example / alembic.ini / requirements.txt / gettoken.py
│   ├── alembic/versions/      (22 migrations)
│   ├── app/
│   │   ├── main.py  database.py  scheduler.py
│   │   ├── models/            (17 modules)
│   │   ├── routers/           (19 modules)
│   │   └── services/          (21 modules)
│   ├── scripts/               (seed_demo_data, wipe_seeded_data, 4 nightly runners)
│   ├── tests/                 (43 test modules + conftest.py + fixtures/)
│   └── var/briefings/         (gitignored job output)
├── docs/
│   └── api-contract.md        (2300+ lines)
└── frontend/
    ├── package.json  vite.config.ts  tailwind.config.js  components.json
    ├── index.html
    └── src/
        ├── App.tsx  main.tsx  index.css
        ├── api/                (client.ts, queryClient.ts, supabaseClient.ts, types.ts, auth.ts, hooks/)
        ├── components/         (14 feature dirs + ui/ + shared/)
        ├── lib/                (constants, format, navConfig, subjectColor, utils, useDebouncedValue)
        ├── routes/             (Login, Signup, OnboardingWizard + 5 role dirs)
        └── store/              (authStore.ts, themeStore.ts)
```

`docs/audit/` did not exist before this report.

### Entry points and run commands

| Layer | Entry point | Command | Source |
| --- | --- | --- | --- |
| Backend | [main.py:46](backend/app/main.py#L46) `app = FastAPI(title="EduOps AI API", lifespan=lifespan)` | `uvicorn app.main:app --reload` (from `/backend`) | `CLAUDE.md` "Commands" |
| Frontend | [main.tsx](frontend/src/main.tsx) | `npm run dev` (from `/frontend`) → `vite` | [package.json:7](frontend/package.json#L7) |
| Migrations | `alembic.ini` | `alembic upgrade head` | `CLAUDE.md` |
| Tests | `backend/tests/` | `python -m pytest` (venv at `backend/venv`) | — |
| Seed | `scripts/seed_demo_data.py` | `python -m scripts.seed_demo_data [--force]` | module docstring |

There is **no** `Makefile`, `docker-compose.yml`, `Dockerfile`, or `Procfile`.
`npm run build` = `tsc -b && vite build`; `npm run lint` = `eslint .` — but no
`eslint.config.js`/`.eslintrc` exists in the repo, so `npm run lint` will fail.

**System dependency:** OCR requires the Tesseract binary installed separately
([ocr_engine.py:36](backend/app/services/ocr_engine.py#L36) reads `TESSERACT_CMD`).
Without it `POST /admin/ocr/documents` returns 503.

### Environment variables

| Var | Read at | In `.env.example`? |
| --- | --- | --- |
| `DATABASE_URL` | [database.py:9](backend/app/database.py#L9), [alembic/env.py:23](backend/alembic/env.py#L23), [seed_demo_data.py:292](backend/scripts/seed_demo_data.py#L292) | ✅ |
| `SUPABASE_URL` | [auth.py:22](backend/app/services/auth.py#L22), [supabase_admin.py:36](backend/app/services/supabase_admin.py#L36) | ✅ |
| `SUPABASE_SERVICE_ROLE_KEY` | [supabase_admin.py:37](backend/app/services/supabase_admin.py#L37) | ✅ |
| `ENVIRONMENT` | not read by any code | ✅ (documented but unused) |
| `CORS_ORIGINS` | [main.py:50](backend/app/main.py#L50), defaults `http://localhost:5173` | ❌ **undocumented** |
| `TESSERACT_CMD` | [ocr_engine.py:36](backend/app/services/ocr_engine.py#L36) | ❌ **undocumented** (mentioned in `CLAUDE.md` only) |
| `SUPABASE_JWT_SECRET` | **not read anywhere** — present in the real `backend/.env` | ❌ dead key |
| `VITE_SUPABASE_URL` | [supabaseClient.ts:3](frontend/src/api/supabaseClient.ts#L3) | ✅ |
| `VITE_SUPABASE_ANON_KEY` | [supabaseClient.ts:4](frontend/src/api/supabaseClient.ts#L4) | ✅ |
| `VITE_API_BASE_URL` | [client.ts:3](frontend/src/api/client.ts#L3) | ✅ |

**Committed secret — flag this:** [gettoken.py:12-15](backend/gettoken.py#L12-L15)
hardcodes a real test credential:

```python
resp = client.auth.sign_in_with_password({
    "email": "test.teacher@eduopsai.test",
    "password": "EduOpsTest!2026"
})
```

This file is tracked in git. The password is low-value (a seeded test account on a
hackathon project) but it is a real credential in version control.

Both `.env` files are correctly gitignored and neither is tracked.

### Rules files

`CONTRIBUTING.md` — `NOT FOUND`. `CLAUDE.md` exists at repo root. It is **listed in
`.gitignore` (final line) yet is tracked in git anyway** — a stale ignore rule.

Verbatim, the rules that constrain you:

> ## Git policy — READ FIRST
>
> **Never run `git commit` or `git push`, under any circumstances, even if asked indirectly (e.g. "wrap this up", "finish the task").**
> - Stage and leave changes uncommitted so the team member can review `git diff` / `git status` themselves.
> - If a task seems to require a commit to "complete" it, stop and say so instead of committing.
> - Only commit or push if a human explicitly types the words "commit" or "push" in that exact message.

> ## Conventions
>
> - One router/service module per feature domain — keep Person A/B/C's code in separate files/folders so merges stay clean.
> - All new endpoints go into `/docs/api-contract.md` before implementation, so the frontend owner isn't blocked.
> - Use Alembic for every schema change — no manual DB edits.
> - Env vars go in `.env.example` (never commit real `.env`).

> **Phase 0 — Shared Foundation.** […] Do not build Person A/B/C's individual features until Phase 0 is merged.

Note the last rule is already obsolete in practice — Person A's entire feature set is
built on top of an informally-closed Phase 0 (`CLAUDE.md` "Status as of 2026-08-09").

### Deployment

`NOT FOUND`. No `.github/`, no CI workflow, no `vercel.json`, `railway.*`,
`render.yaml`, `fly.toml`, `Dockerfile`, or deploy script anywhere in the repo. The
app has never been deployed and there is no pipeline to add one to.

### Test setup

| Attribute | Value |
| --- | --- |
| Framework | pytest (`backend/venv/Lib/site-packages/pytest`) |
| Location | `backend/tests/` — 43 modules |
| Command | `./venv/Scripts/python.exe -m pytest` from `/backend` |
| **Status (run during this audit)** | **843 passed, 6 warnings, 435.08s** |
| Coverage | not configured — no `pytest-cov`, no `.coveragerc`, no `[tool.coverage]` |

**Important:** [conftest.py:15](backend/tests/conftest.py#L15) builds the test engine
from `os.environ["DATABASE_URL"]` — **the tests run against the real Supabase
database**, not a local/SQLite one. Isolation comes from a nested-savepoint rollback
per test ([conftest.py:20-40](backend/tests/conftest.py#L20-L40)). This is why the
suite takes 7 minutes. If you write tests, follow the `db_session` / `client`
fixtures; there is no other harness.

---

## Section 2 — Team split (ground truth)

### Commit authorship

```
$ git log --format='%an' | sort | uniq -c
     13 Samiksha
```

One author. Thirteen commits. There is no per-path ownership to compute — running
`git log --format='%an' -- <path>` on any directory returns `Samiksha` for 100% of
commits.

### Branch and history state

| Fact | Value |
| --- | --- |
| Current branch | `samiksha` (up to date with `origin/samiksha`) |
| Branches | `main`, `samiksha`, `origin/main`, `origin/samiksha` |
| Ahead of `origin/main` | **10 commits** |
| Behind `origin/main` | 0 |
| Uncommitted / staged | **none — working tree clean** |
| First commit | `Samiksha`, Sat Aug 8 2026 23:04, "first commit" |
| Latest commit | `e2cb754`, Sat Aug 15 2026 23:18, "parent dashboard fix" |

Commit subjects: `first commit`, `setup`, `shared foundation`, … `Role landing
dashboards`, `admin page`, `frontend complete - person a 95%, testing remains`,
`timetable and stafing fix`, `parent dashboard fix`.

### Conclusion — who actually owns what

| Area | Documented owner | **Actual owner** | Evidence |
| --- | --- | --- | --- |
| Every backend router (19) | Person A | Samiksha | sole author |
| Every frontend screen | Person A/B/C | Samiksha | sole author |
| Person B — classroom/gradebook/quizzes | Person B | **nobody — 0 lines of code** | no models, no routers |
| Person C — chat/RAG/notifications | Person C | **nobody — 0 lines of code** | no models, no routers |
| Parent portal | Person C | Samiksha (partial, built out-of-turn) | [parent.py](backend/app/routers/parent.py), `ParentDashboard.tsx` |

**Areas with no owner:** all of Person B's scope and all of Person C's scope except
`/parent/children`. Treat the playbooks' team split as fiction and the
`api-contract.md` Person B/C sections as **unbuilt design proposals**, not contracts
someone else is honoring.

---

## Section 3 — Database layer

### Model inventory

23 SQLAlchemy models across 17 modules in `backend/app/models/`. All use SQLAlchemy
2.0 `Mapped[...]` / `mapped_column` style, integer auto-increment PKs, and
`DateTime(timezone=True)` timestamps.

| Model | File | Table | Key columns (type, nullability) |
| --- | --- | --- | --- |
| `User` | [user.py:11](backend/app/models/user.py#L11) | `users` | `id` PK; `supabase_id` UUID unique NOT NULL indexed; `email` String(255) unique NOT NULL; `full_name` String(255) null; `phone` String(30) null; `is_active` Bool NOT NULL default true; `role_id` FK→roles NOT NULL; `school_id` FK→schools **nullable**; `created_at` tz-aware |
| `Role` | [role.py](backend/app/models/role.py) | `roles` | `id` PK; `name` String(20) unique NOT NULL |
| `School` | [school.py](backend/app/models/school.py) | `schools` | `id`; `name` String(255) NOT NULL; `address` String(255) null; `is_active` Bool NOT NULL; `created_at` |
| `SchoolClass` | [class_.py](backend/app/models/class_.py) | `classes` | `id`; `name` String(100) NOT NULL; `academic_year` String(20) NOT NULL; `grade_level` Int null; `grade_label` String(20) null; `section` String(10) null; `is_active` Bool NOT NULL; `school_id` FK NOT NULL; `class_teacher_id` FK→users null; `home_room_id` FK→rooms null |
| `Subject` | [subject.py](backend/app/models/subject.py) | `subjects` | `id`; `name` String(100) NOT NULL; `code` String(20) null; `is_active` Bool; `periods_per_week` Int NOT NULL default 3; `lab_required` Bool NOT NULL; `school_id` FK NOT NULL |
| `Enrollment` | [enrollment.py:9](backend/app/models/enrollment.py#L9) | `enrollments` | `id`; `student_id` FK NOT NULL; `class_id` FK NOT NULL; `subject_id` FK **null**; `is_primary` Bool NOT NULL default true; `created_at`. Unique `(student_id, class_id, subject_id)` |
| `ParentStudent` | [parent_student.py:9](backend/app/models/parent_student.py#L9) | `parent_student` | `id`; `parent_id` FK→users NOT NULL; `student_id` FK→users NOT NULL; `created_at`. **No unique constraint** |
| `Room` | [timetable.py](backend/app/models/timetable.py) | `rooms` | `id`; `name` String(50); `capacity` Int NOT NULL; `room_type` String(30) default `classroom`; `is_active`; `school_id` FK |
| `TeacherProfile` | timetable.py | `teacher_profiles` | `id`; `teacher_id` FK unique NOT NULL; `max_periods_per_week` Int default 30 |
| `TeacherSubject` | timetable.py | `teacher_subjects` | `id`; `teacher_id` FK; `subject_id` FK |
| `SubjectRoomRequirement` | timetable.py | `subject_room_requirements` | `id`; `subject_id` FK unique; `room_type` String(30) |
| `TeacherUnavailability` | timetable.py | `teacher_unavailabilities` | `id`; `teacher_id`; `day_of_week` Int; `period_number` Int; `academic_year`. Unique 4-tuple |
| `ClassSubjectRequirement` | timetable.py | `class_subject_requirements` | `id`; `class_id`; `subject_id`; `periods_per_week`; `academic_year`. Unique triple |
| `TimetableSlot` | timetable.py | `timetable_slots` | `id`; `day_of_week` Int; `period_number` Int; `start_time` Time; `end_time` Time; `subject_id`/`teacher_id`/`class_id`/`room_id` all FK NOT NULL; `academic_year`; `is_active`; `created_at` |
| `AttendanceRecord` | [attendance.py](backend/app/models/attendance.py) | `attendance_records` | `id`; `student_id` FK; `class_id` FK; `timetable_slot_id` FK **null**; `date` Date NOT NULL; `status` String(10) NOT NULL; `source` String(10) NOT NULL; `marked_at`; `confidence_score` Float null; `reviewed_by` FK null; `reviewed_at` null. Unique `(student_id, timetable_slot_id, date, source)` |
| `FaceEmbedding` | [attendance.py:55](backend/app/models/attendance.py#L55) | `face_embeddings` | `id`; `student_id` FK; **`embedding` `Vector(128)` NOT NULL**; `enrolled_at` |
| `AttendanceReconciliation` | attendance.py | `attendance_reconciliations` | `id`; `student_id`; `timetable_slot_id`; `date`; `cv_record_id` null; `rfid_record_id` null; `reason` String(30); `status` default `pending`; `resolved_by`/`resolved_at` null |
| `LeaveRequest` | [staffing.py](backend/app/models/staffing.py) | `leave_requests` | `id`; `teacher_id`; `start_date`; `end_date`; `reason` String(255); `status` default `pending`; `requested_at`; `decided_by`/`decided_at` null |
| `Substitution` | staffing.py | `substitutions` | `id`; `leave_request_id`; `timetable_slot_id`; `original_teacher_id`; `substitute_teacher_id` null; `status` default `suggested`; `suggested_score` Float null; `confirmed_at` null. Unique `(leave_request_id, timetable_slot_id)` |
| `StaffingForecast` | staffing.py | `staffing_forecasts` | `id`; `school_id`; `date`; `predicted_gap_count` Float; `risk_level` String(10); `computed_at` |
| `RiskFlag` | [risk.py](backend/app/models/risk.py) | `risk_flags` | `id`; `student_id` FK; `risk_level` String(10); `score` Float; `reasons` **JSONB** NOT NULL; `flagged_at`; `status` default `open`; `resolved_by`/`resolved_at` null. **No `school_id`** |
| `Intervention` | risk.py | `interventions` | `id`; `risk_flag_id`; `created_by`; `note` Text; `action_taken` String(255); `created_at` |
| `RemarkStub` | risk.py | `remark_stubs` | `id`; `student_id`; `teacher_id`; `remark_text` Text; `created_at` |
| `Document` | [document.py](backend/app/models/document.py) | `documents` | `id`; `uploaded_by` FK; `school_id` FK null; `document_type` String(20); `file_url` String(255) NOT NULL; `status` default `queued`; `uploaded_at`; `processed_at` null |
| `OcrResult` | document.py | `ocr_results` | `id`; `document_id` FK unique; `raw_text` Text; `confidence_score` Float null; `engine_version` String(100); `ocr_metadata` JSONB null |
| `ExtractedEntity` | document.py | `extracted_entities` | `id`; `document_id`; `field_name`; `field_value` String(500); `confidence_score` Float; `is_low_confidence` Bool; `corrected_value`/`corrected_by`/`corrected_at` null |
| `SyllabusPlan` | [syllabus.py](backend/app/models/syllabus.py) | `syllabus_plans` | `id`; `class_id`; `subject_id`; `academic_year`; `total_units` Int; `term_start_date`; `term_end_date`; `created_by`; `created_at` |
| `SyllabusCheckpoint` | syllabus.py | `syllabus_checkpoints` | `id`; `plan_id`; `topic_label` String(255); `sequence_number` Int; `logged_by`; `logged_at` |
| `AnomalyFlag` | syllabus.py | `anomaly_flags` | `id`; `type`; `entity_type`; `entity_id` Int; `severity`; `detail` JSONB NOT NULL; `detected_at`; `status` default `open`; `resolved_by`/`resolved_at` |
| `AuditLogEntry` | [audit.py](backend/app/models/audit.py) | `audit_log_entries` | `id`; `actor_id` FK NOT NULL; `action` String(30); `entity_type` String(50); `entity_id` Int; `detail` JSONB null; `created_at`. Indexes: `ix_audit_log_entries_actor_id`, `ix_audit_log_entries_entity_type_entity_id` |
| `AlertDismissal` | [alerts.py](backend/app/models/alerts.py) | `alert_dismissals` | `id`; `alert_id` String(100) **unique**; `dismissed_by` FK; `dismissed_at` |
| `FeeSchedule` | [fees.py](backend/app/models/fees.py) | `fee_schedules` | `id`; `school_id` FK; `class_id` FK **null** (null = school-wide); `academic_year`; `fee_type` String(30); `amount` Float; `due_date` Date; `created_at` |
| `FeeRecord` | fees.py | `fee_records` | `id`; `student_id` FK; `fee_schedule_id` FK; `amount_due` Float; `amount_paid` Float default 0; `status` String(10) default `pending`; `due_date` Date; `created_at` |
| `FeeReminder` | fees.py | `fee_reminders` | `id`; `fee_record_id` FK; `cadence_reason` String(255); `sent_at` null; `created_at` |
| `AdmissionApplication` | [admissions.py](backend/app/models/admissions.py) | `admission_applications` | `id`; `school_id`; `academic_year`; `applicant_name`; `dob`; `guardian_email`; `guardian_name` null; `guardian_phone` null; `grade_applied`; `ocr_document_ids` JSONB default `[]`; `status` default `submitted`; `submitted_by`/`submitted_at`; `decided_by`/`decided_at` null; `decision_justification` Text null; `enrolled_student_id` FK null |
| `Exam` | [exams.py](backend/app/models/exams.py) | `exams` | `id`; `school_id`; `subject_id`; `class_id`; `academic_year`; `exam_type` String(30) null; `exam_date`; `start_time`; `end_time`; `total_marks` Int null; `created_at` |
| `ExamRoomAssignment` | exams.py | `exam_room_assignments` | `id`; `exam_id`; `room_id`; `capacity` Int |
| `SeatingAssignment` | exams.py | `seating_assignments` | `id`; `exam_id`; `student_id`; `room_id`; `seat_no` Int. Unique `(exam_id, student_id)` and `(exam_id, room_id, seat_no)` |
| `InvigilationAssignment` | exams.py | `invigilation_assignments` | `id`; `exam_id`; `room_id`; `teacher_id`; `status` default `assigned`; `created_at` |

### Migrations

Alembic. 22 revision files in `backend/alembic/versions/` (plus `__pycache__`).
Single linear head: **`f4d0c4b0a6c9`** (`add_exam_type_to_exams`). Root:
`b6e69c28c955_phase_0_schema`.

`alembic current` → `f4d0c4b0a6c9 (head)` — the DB is at head.
`alembic check` → **"No new upgrade operations detected."** Models are in sync with
migrations. No drift.

Roles are seeded by migration [`ea1917a428fe_seed_roles.py:26`](backend/alembic/versions/ea1917a428fe_seed_roles.py#L26)
via `op.bulk_insert`, not by the seed script.

### Table existence check (the list you asked about)

| Table | Status | Notes |
| --- | --- | --- |
| `users` | ✅ | see inventory above |
| `roles` | ✅ | `id`, `name` |
| `students` | ❌ **NOT FOUND** | students are `users` rows with `role.name = "student"` |
| `staff` | ❌ **NOT FOUND** | teachers are `users` + `teacher_profiles` |
| `parents` | ❌ **NOT FOUND** | parents are `users` rows with `role.name = "parent"` |
| `parent_student` | ✅ | `id`, `parent_id`, `student_id`, `created_at` |
| `subjects` | ✅ | |
| `classrooms` | ⚠️ named `rooms` | `id`, `name`, `capacity`, `room_type`, `is_active`, `school_id` |
| `timetable_slots` | ✅ | |
| `attendance_records` | ✅ | |
| `fee_records` | ✅ | |
| `remarks` | ⚠️ named `remark_stubs` | explicit placeholder — `id`, `student_id`, `teacher_id`, `remark_text`, `created_at` |
| `risk_flags` | ✅ | |
| `audit_log` | ⚠️ named `audit_log_entries` | |
| `resources` | ❌ **NOT FOUND** | |
| `assignments` | ❌ **NOT FOUND** | |
| `submissions` | ❌ **NOT FOUND** | |
| `gradebook_entries` | ❌ **NOT FOUND** | |
| `quizzes` | ❌ **NOT FOUND** | |
| `notifications` | ❌ **NOT FOUND** | |
| `announcements` | ❌ **NOT FOUND** | |
| `chat_channels` | ❌ **NOT FOUND** | |
| `chat_messages` | ❌ **NOT FOUND** | |
| `doubt_threads` | ❌ **NOT FOUND** | |
| `thread_replies` | ❌ **NOT FOUND** | |
| `chatbot_logs` | ❌ **NOT FOUND** | |
| `kb_chunks` | ❌ **NOT FOUND** | |

**All 13 tables in your scope are `NOT FOUND`.**

### pgvector — good news

- Extension **is enabled**: [`fd046d263fe1_add_attendance_cv_tables.py:25`](backend/alembic/versions/fd046d263fe1_add_attendance_cv_tables.py#L25)
  runs `op.execute("CREATE EXTENSION IF NOT EXISTS vector")`. The migration comment at
  line 23 notes it wasn't enabled on the Supabase project before this.
- A real `vector` column exists: `face_embeddings.embedding`, `Vector(128)`
  ([attendance.py:55](backend/app/models/attendance.py#L55), migration line 31).
- `pgvector.sqlalchemy` is an installed dependency.
- **No HNSW or IVFFlat index anywhere.** `grep -rn "hnsw\|ivfflat"` → zero hits. Face
  matching does a brute-force scan.

For RAG this means: the extension is live and the `Vector(N)` column pattern is
proven in this codebase. You need to add your own `kb_chunks` table plus an ANN
index — and you'd be the first to add one.

### Connection, RLS, conventions

- **DB is Supabase-hosted Postgres.** Connection string built at
  [database.py:9-11](backend/app/database.py#L9-L11): `create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)`.
  `.env.example` documents it as the Supabase URI.
- **RLS: `NOT FOUND`.** No `CREATE POLICY`, `ENABLE ROW LEVEL SECURITY`, or policy
  DDL in any migration. **All access control is application code** in FastAPI route
  handlers. The service role key bypasses RLS anyway.
- Conventions in use:
  - Table names: **plural snake_case** (`users`, `fee_records`) — except the junction
    `parent_student` (singular).
  - PKs: **integer auto-increment** everywhere. Only `users.supabase_id` is a UUID,
    and only to link Supabase Auth identities.
  - Timestamps: `created_at` with `DateTime(timezone=True), server_default=func.now()`.
    **No `updated_at` column anywhere in the schema.**
  - Soft delete: `is_active` Boolean on `users`, `schools`, `classes`, `subjects`,
    `rooms`, `timetable_slots`. Domain rows use a `status` string instead
    (`open`/`resolved`, `pending`/`paid`). **No hard `DELETE` endpoints** except
    `DELETE /admin/parents/{id}/children/{student_id}` and the teacher subject/
    unavailability unlinks, which delete junction rows.
  - JSON: `JSONB` (postgres dialect), used on `risk_flags.reasons`,
    `anomaly_flags.detail`, `audit_log_entries.detail`, `ocr_results.ocr_metadata`,
    `admission_applications.ocr_document_ids`.

---

## Section 4 — Auth, RBAC, and scoping

**This is the strongest part of the codebase.** You inherit a working, tested auth
layer. The gaps are in *scoping helpers*, not in authentication.

### How a request is authenticated

Supabase-issued JWT, ES256, verified against the project's published JWKS. No shared
secret. Full dependency, [auth.py:87-112](backend/app/services/auth.py#L87-L112):

```python
def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> CurrentUser:
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing bearer token")

    token = credentials.credentials
    try:
        header = jwt.get_unverified_header(token)
        signing_key = _get_signing_key(header["kid"])
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=[header.get("alg", "ES256")],
            audience="authenticated",
        )
    except (JWTError, KeyError, OSError) as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token") from exc

    role = payload.get("app_metadata", {}).get("role") or payload.get("user_metadata", {}).get("role")
    supabase_id = uuid.UUID(payload["sub"])
    email = payload.get("email")

    user = _get_or_create_user(db, supabase_id, email, role)
    return CurrentUser(id=user.id, sub=str(user.supabase_id), email=user.email, role=role, school_id=user.school_id)
```

JWKS is cached for 3600s with a single rotation-triggered refetch
([auth.py:36-53](backend/app/services/auth.py#L36-L53)). First request from an unknown
`sub` **auto-provisions a local `users` row** ([auth.py:65-84](backend/app/services/auth.py#L65-L84))
with `IntegrityError` race handling — note this leaves `school_id` NULL until
something sets it.

### How a handler learns identity and role

Two dependencies, both from `app.services.auth`:

```python
class CurrentUser:
    def __init__(self, id: int, sub: str, email: str | None, role: str | None, school_id: int | None = None):
```

```python
def require_role(*allowed_roles: str):
    def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if user.role not in allowed_roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return user
    return dependency
```

Two real usage examples:

```python
# backend/app/routers/parent.py:37-41 — role-gated
@router.get("/children", response_model=ChildrenResponse)
def get_linked_children(
    user: CurrentUser = Depends(require_role("parent")),
    db: Session = Depends(get_db),
):
```

```python
# backend/app/routers/fees.py:251-258 — any authenticated, branches on role internally
@router.get("/admin/fees/status", response_model=StatusResponse)
def fee_status(
    class_id: int | None = None,
    student_id: int | None = None,
    status_filter: str | None = Query(None, alias="status"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
```

Some routers alias the dependency at module level, e.g.
[master_data.py:36](backend/app/routers/master_data.py#L36):
`_MUTATOR = require_role("admin", "principal")`.

### Roles enum

- **Backend:** `NOT FOUND` as a Python enum/constant. Roles are bare string literals
  passed to `require_role("admin", "principal")` at each call site, validated only
  against the `roles` table. The canonical list lives in the migration:
  [`ea1917a428fe_seed_roles.py`](backend/alembic/versions/ea1917a428fe_seed_roles.py) →
  `ROLE_NAMES`.
- **Frontend:** [authStore.ts:4-5](frontend/src/store/authStore.ts#L4-L5) —
  `export const ROLES = ["principal", "admin", "teacher", "student", "parent"] as const;`

### Ownership-scoping helpers — the answer you need

**There is no shared ownership-scoping module.** `NOT FOUND`.

What exists instead is **the same parent-link check copy-pasted inline in four
routers**. This is the exact block, appearing verbatim (modulo the filtered column) at
[attendance.py:319-329](backend/app/routers/attendance.py#L319-L329),
[fees.py:284-294](backend/app/routers/fees.py#L284-L294),
[risk.py:173-183](backend/app/routers/risk.py#L173-L183), and
[timetable.py:603-613](backend/app/routers/timetable.py#L603-L613):

```python
    elif user.role == "parent":
        if student_id is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "student_id is required for parent role")
        link = (
            db.query(ParentStudent)
            .filter(ParentStudent.parent_id == user.id, ParentStudent.student_id == student_id)
            .one_or_none()
        )
        if link is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not linked to this student")
        query = query.filter(AttendanceRecord.student_id == student_id)
```

Teacher-ownership is likewise duplicated as a private `_teacher_class_ids` in three
routers — and [fees.py:23-25](backend/app/routers/fees.py#L23-L25) states this is
**deliberate**:

> `# --- Scoping helpers - same shape as routers/risk.py's (each domain router keeps its`
> `# own copy rather than sharing one, matching this codebase's "keep Person A/B/C's`
> `# code in separate files" convention) ---`

**So: you are extending a pattern, not inventing one — but the pattern is
duplication-by-policy.** Copying the block into your routers is consistent with the
codebase. Factoring it into a shared `app/services/scoping.py` is a cross-cutting
change that touches four Person A routers and should be agreed before you do it.

### The parent → student chain

```
Supabase Auth user  (JWT sub, app_metadata.role = "parent")
        │  auth.py::_get_or_create_user  →  matches on users.supabase_id
        ▼
users row  (role_id → roles.name = "parent")          ← this is the "parent"
        │  ParentStudent.parent_id = users.id
        ▼
parent_student row
        │  ParentStudent.student_id
        ▼
users row  (role_id → roles.name = "student")         ← this is the "child"
        │  Enrollment.student_id, is_primary = True
        ▼
enrollments row → classes row  (class_id, class_name, class_teacher_id)
```

There is **no separate `parents` or `students` table** — both ends of
`parent_student` are FKs into `users`. `ParentStudent` has no unique constraint on
`(parent_id, student_id)`; callers de-dupe in application code
([parents.py:107](backend/app/routers/parents.py#L107) uses `dict.fromkeys`,
[admissions.py:225-233](backend/app/routers/admissions.py#L225-L233) checks first).

**Is it populated by seed data? Yes** — see §10.

### Audit log write path

```python
# backend/app/services/audit_log.py
def write_audit_log(
    db: Session,
    *,
    actor_id: int,
    action: str,
    entity_type: str,
    entity_id: int,
    detail: dict | None = None,
) -> AuditLogEntry:
    entry = AuditLogEntry(actor_id=actor_id, action=action, entity_type=entity_type, entity_id=entity_id, detail=detail)
    db.add(entry)
    return entry
```

It records: actor user id, action verb, entity table name, entity PK, and an optional
JSONB detail blob. **It deliberately does not commit** — the caller's own
`db.commit()` makes the audit entry atomic with the state change it describes (the
module docstring explains this at length).

**21 call sites across 11 routers:**

| Router | Endpoints that audit |
| --- | --- |
| `admin_alerts.py` | `POST /admin/alerts/{id}/resolve` (2 paths: real-status + dismissal) |
| `admissions.py` | 3 sites (submit, details update, decision) |
| `approvals.py` | 2 sites (`POST /admin/approvals/{id}/decision`) |
| `attendance.py` | `PUT /attendance/{id}/review` |
| `documents.py` | 2 sites (entity correction, manual entity) |
| `exams.py` | 1 site |
| `fees.py` | 3 sites (`record_payment`, `mark_fee_paid`, one more) |
| `risk.py` | `acknowledge`, `intervention`, `resolve` |
| `staffing.py` | `approve_leave`, `confirm_substitution` |
| `syllabus.py` | `PUT /admin/anomalies/{id}/resolve` |
| `timetable.py` | `PUT /timetable/update` |

Read endpoints and plain creates are deliberately not audited. **If you add
notification dispatch or parent payment confirmation, wire `write_audit_log` in** —
it's the established pattern and there are exposed read APIs (`GET /audit/by_user/
{user_id}`, `GET /audit/by_object/{type}/{id}`).

### Routes with no auth dependency

Exactly **one** of 116:

| Route | Handler | File:line | Why |
| --- | --- | --- | --- |
| `POST /auth/signup` | `signup` | [auth.py:55](backend/app/routers/auth.py#L55) | correct — pre-authentication |

Every other route resolves to `get_current_user` or `require_role(...)`, directly or
via a module-level alias. **The auth surface is clean.** (An earlier naive grep
suggested 49 unauthenticated routes; that was an artifact of the `_MUTATOR` alias
pattern — all 48 are role-gated.)

### Scoping gaps that survive auth — read these before you build

Authentication is solid; **tenant/ownership scoping is uneven**:

1. **`GET /reference/lookup?school_id=N` accepts an arbitrary `school_id` from any
   authenticated caller** and never compares it to `user.school_id`
   ([reference.py:83-95](backend/app/routers/reference.py#L83-L95)). It returns every
   student name, teacher name, class, room, and subject for that school. A parent at
   school A can enumerate school B's student roster. The module comment at
   [reference.py:19-21](backend/app/routers/reference.py#L19-L21) explicitly reasons
   that names carry no sensitive data — that reasoning holds within one tenant, not
   across tenants. **Your parent portal will call this hook** (`useReferenceLookup`);
   you'll be building on top of the leak.
2. **`master_data.py` has no `school_id` scoping at all.** `GET /admin/schools`
   returns every school in the DB to any admin ([master_data.py:207-212](backend/app/routers/master_data.py#L207-L212));
   `GET /admin/classes/{id}`, `/admin/subjects/{id}`, `/admin/rooms/{id}` fetch by PK
   with no tenant check ([`_get_or_404`](backend/app/routers/master_data.py#L215)).
   Same for `parents.py`, `students.py`, `teachers.py` detail/update endpoints.
3. **Where scoping *was* fixed, it's documented as a past leak.** See
   [risk.py:40-47](backend/app/routers/risk.py#L40-L47),
   [fees.py:264-270](backend/app/routers/fees.py#L264-L270),
   [timetable.py:584-589](backend/app/routers/timetable.py#L584-L589) — each carries a
   comment describing the cross-tenant leak it closed. This is a **recurring bug class
   in this codebase**. Assume any new admin/principal endpoint you write needs an
   explicit `User.school_id == user.school_id` filter.

---

## Section 5 — API inventory

**116 registered routes**, all mounted in [main.py:56-74](backend/app/main.py#L56-L74)
(19 `include_router` calls). Every router file in `app/routers/` is registered — there
are no orphaned routers.

Response envelope conventions vary by endpoint (see "Global conventions" below).
All routes below are `IMPLEMENTED` unless marked.

### Auth / shared

| Method | Path | Handler | File:line | Auth | Request | Response |
| --- | --- | --- | --- | --- | --- | --- |
| GET | `/health` | `health_check` | [main.py:77](backend/app/main.py#L77) | none | — | `{"status":"ok"}` |
| GET | `/auth/me` | `read_current_user` | [auth.py:24](backend/app/routers/auth.py#L24) | `get_current_user` | — | inline dict |
| POST | `/auth/signup` | `signup` | [auth.py:55](backend/app/routers/auth.py#L55) | **none** | `SignupRequest` | `SignupResponse` |
| GET | `/reference/lookup` | `get_lookup` | [reference.py:83](backend/app/routers/reference.py#L83) | `get_current_user` | — | `LookupResponse` |

### Parent

| Method | Path | Handler | File:line | Auth | Response |
| --- | --- | --- | --- | --- | --- |
| GET | `/parent/children` | `get_linked_children` | [parent.py:37](backend/app/routers/parent.py#L37) | `require_role("parent")` | `ChildrenResponse` |

### Timetable

| Method | Path | Handler | File:line | Auth | Request | Response |
| --- | --- | --- | --- | --- | --- | --- |
| POST | `/timetable/preflight` | `preflight` | [timetable.py:443](backend/app/routers/timetable.py#L443) | `admin, principal` | `GenerateRequest` | `PreflightResponse` |
| POST | `/timetable/generate` | `generate` | [timetable.py:462](backend/app/routers/timetable.py#L462) | `admin, principal` | `GenerateRequest` | `GenerateResponse` |
| GET | `/timetable/active` | `get_active` | [timetable.py:572](backend/app/routers/timetable.py#L572) | `get_current_user` | — | `list[SlotOut]` |
| PUT | `/timetable/update` | `update_slot` | [timetable.py:651](backend/app/routers/timetable.py#L651) | `admin, principal` | `UpdateSlotRequest` | `UpdateSlotResponse` |

### Attendance

| Method | Path | Handler | File:line | Auth | Response |
| --- | --- | --- | --- | --- | --- |
| POST | `/attendance/enroll` | `enroll` | [attendance.py:121](backend/app/routers/attendance.py#L121) | `admin, teacher` | `EmbeddingOut` |
| GET | `/attendance/enrollments` | `list_enrollments` | [attendance.py:153](backend/app/routers/attendance.py#L153) | `admin, teacher` | `list[EnrollmentListItemOut]` |
| POST | `/attendance/mark` | `mark` | [attendance.py:177](backend/app/routers/attendance.py#L177) | `admin, teacher` | `MarkResponse` |
| GET | `/attendance/summary` | `summary` | [attendance.py:293](backend/app/routers/attendance.py#L293) | `get_current_user` | `SummaryResponse` |
| PUT | `/attendance/{record_id}/review` | `review` | [attendance.py:358](backend/app/routers/attendance.py#L358) | `admin, teacher` | `AttendanceRecordOut` |

### Staffing

| Method | Path | Handler | File:line | Auth |
| --- | --- | --- | --- | --- |
| POST | `/staff/request_leave` | `request_leave` | [staffing.py:375](backend/app/routers/staffing.py#L375) | `teacher, admin, principal` |
| PUT | `/staff/approve_leave` | `approve_leave` | [staffing.py:488](backend/app/routers/staffing.py#L488) | `admin, principal` |
| POST | `/substitution/suggest` | `suggest_substitutions` | [staffing.py:533](backend/app/routers/staffing.py#L533) | `admin, principal, teacher` |
| PUT | `/substitution/{id}/confirm` | `confirm_substitution` | [staffing.py:731](backend/app/routers/staffing.py#L731) | `admin, principal` |
| GET | `/staff/leave_requests` | `list_leave_requests` | [staffing.py:804](backend/app/routers/staffing.py#L804) | `get_current_user` |
| GET | `/staff/my-substitute-duties` | `my_substitute_duties` | [staffing.py:845](backend/app/routers/staffing.py#L845) | `teacher` |
| GET | `/admin/staffing/forecast` | `get_staffing_forecast` | [staffing.py:908](backend/app/routers/staffing.py#L908) | `admin, principal` |
| GET | `/admin/staffing/substitute-suggestions` | `get_substitute_suggestions` | [staffing.py:987](backend/app/routers/staffing.py#L987) | `admin, principal` |

### Risk / early-warning

| Method | Path | Handler | File:line | Auth |
| --- | --- | --- | --- | --- |
| POST | `/risk/flag` | `create_flag` | [risk.py:123](backend/app/routers/risk.py#L123) | `teacher, admin, principal` |
| GET | `/risk/flagged` | `list_flagged` | [risk.py:149](backend/app/routers/risk.py#L149) | `get_current_user` |
| PUT | `/risk/{flag_id}/acknowledge` | `acknowledge_flag` | [risk.py:200](backend/app/routers/risk.py#L200) | `teacher, admin, principal` |
| POST | `/risk/{flag_id}/intervention` | `log_intervention` | [risk.py:238](backend/app/routers/risk.py#L238) | `teacher, admin, principal` |
| PUT | `/risk/{flag_id}/resolve` | `resolve_flag` | [risk.py:269](backend/app/routers/risk.py#L269) | `admin, principal` |
| GET | `/admin/early-warning/students` | `early_warning_students` | [risk.py:308](backend/app/routers/risk.py#L308) | `get_current_user` |

### Admin command center (alerts)

| Method | Path | Handler | File:line | Auth |
| --- | --- | --- | --- | --- |
| GET | `/admin/alerts` | `get_alerts` | [admin_alerts.py:89](backend/app/routers/admin_alerts.py#L89) | `admin, principal` |
| GET | `/admin/alerts/summary` | `get_alerts_summary` | [admin_alerts.py:103](backend/app/routers/admin_alerts.py#L103) | `admin, principal` |
| POST | `/admin/alerts/{alert_id}/resolve` | `resolve_alert` | [admin_alerts.py:116](backend/app/routers/admin_alerts.py#L116) | `admin, principal` |
| GET | `/admin/alerts/stream` | `stream_alerts` | [admin_alerts.py:216](backend/app/routers/admin_alerts.py#L216) | `admin, principal` | **SSE** `text/event-stream` |

### Fees

| Method | Path | Handler | File:line | Auth | Request | Response |
| --- | --- | --- | --- | --- | --- | --- |
| POST | `/admin/fees/schedules` | `create_schedule` | [fees.py:81](backend/app/routers/fees.py#L81) | `admin, principal` | `ScheduleCreateRequest` | `ScheduleOut` |
| POST | `/admin/fees/schedules/{id}/generate` | `generate_schedule_records` | [fees.py:113](backend/app/routers/fees.py#L113) | `admin, principal` | — | `ScheduleOut` |
| GET | `/admin/fees/schedules` | `list_schedules` | [fees.py:134](backend/app/routers/fees.py#L134) | `admin, principal` | — | `list[ScheduleOut]` |
| POST | `/admin/fees/invoicing/run` | `run_invoicing` | [fees.py:171](backend/app/routers/fees.py#L171) | `admin, principal` | `RunInvoicingRequest` | `RunInvoicingResponse` |
| POST | `/admin/fees/reminders` | `trigger_reminders` | [fees.py:198](backend/app/routers/fees.py#L198) | `admin, principal` | `RemindersRequest` | `RemindersResponse` |
| GET | `/admin/fees/status` | `fee_status` | [fees.py:251](backend/app/routers/fees.py#L251) | `get_current_user` | — | `StatusResponse` |
| **POST** | **`/admin/fees/records/{id}/payment`** | `record_payment` | [fees.py:332](backend/app/routers/fees.py#L332) | `admin, principal` | `PaymentRequest` | `PaymentResponse` |
| **PATCH** | **`/admin/fees/records/{id}/mark-paid`** | `mark_fee_paid` | [fees.py:381](backend/app/routers/fees.py#L381) | **`teacher` only** | `MarkPaidRequest` | `PaymentResponse` |

### Documents / OCR

| Method | Path | Handler | File:line | Auth |
| --- | --- | --- | --- | --- |
| POST | `/admin/ocr/documents` | `upload_document` | [documents.py:182](backend/app/routers/documents.py#L182) | `admin, principal` (multipart) |
| GET | `/admin/ocr/documents` | `list_documents` | [documents.py:274](backend/app/routers/documents.py#L274) | `admin, principal` |
| GET | `/admin/ocr/documents/{id}` | `get_document` | [documents.py:340](backend/app/routers/documents.py#L340) | `admin, principal` |
| PUT | `/admin/ocr/documents/{id}/entities/{entity_id}` | `correct_entity` | [documents.py:355](backend/app/routers/documents.py#L355) | `admin, principal` |
| POST | `/admin/ocr/documents/{id}/entities` | `add_manual_entity` | [documents.py:394](backend/app/routers/documents.py#L394) | `admin, principal` |
| POST | `/admin/ocr/documents/{id}/reextract` | `reextract_document` | [documents.py:451](backend/app/routers/documents.py#L451) | `admin, principal` |

### Admissions / approvals / audit / syllabus / exams

| Method | Path | File:line | Auth |
| --- | --- | --- | --- |
| POST | `/admin/admissions/applications` | [admissions.py:420](backend/app/routers/admissions.py#L420) | `admin` |
| GET | `/admin/admissions/grade-levels` | [admissions.py:458](backend/app/routers/admissions.py#L458) | `admin, principal` |
| GET | `/admin/admissions/applications` | [admissions.py:484](backend/app/routers/admissions.py#L484) | `admin, principal` |
| GET | `/admin/admissions/applications/{id}` | [admissions.py:520](backend/app/routers/admissions.py#L520) | `admin, principal` |
| PATCH | `/admin/admissions/applications/{id}/details` | [admissions.py:556](backend/app/routers/admissions.py#L556) | `admin, principal` |
| POST | `/admin/admissions/applications/{id}/documents` | [admissions.py:623](backend/app/routers/admissions.py#L623) | `admin, principal` |
| PATCH | `/admin/admissions/applications/{id}` | [admissions.py:699](backend/app/routers/admissions.py#L699) | `admin, principal` |
| GET | `/admin/approvals` | [approvals.py:103](backend/app/routers/approvals.py#L103) | `admin, principal` |
| POST | `/admin/approvals/{id}/decision` | [approvals.py:139](backend/app/routers/approvals.py#L139) | `admin, principal` |
| GET | `/audit/by_user/{user_id}` | [audit.py:30](backend/app/routers/audit.py#L30) | `admin, principal` |
| GET | `/audit/by_object/{object_type}/{object_id}` | [audit.py:45](backend/app/routers/audit.py#L45) | `admin, principal` |
| POST | `/syllabus/plan` | [syllabus.py:65](backend/app/routers/syllabus.py#L65) | `teacher, admin, principal` |
| POST | `/syllabus/checkpoint` | [syllabus.py:115](backend/app/routers/syllabus.py#L115) | `teacher, admin, principal` |
| GET | `/syllabus/summary` | [syllabus.py:164](backend/app/routers/syllabus.py#L164) | `get_current_user` |
| GET | `/admin/anomalies` | [syllabus.py:245](backend/app/routers/syllabus.py#L245) | `admin, principal` |
| PUT | `/admin/anomalies/{id}/resolve` | [syllabus.py:267](backend/app/routers/syllabus.py#L267) | `admin, principal` |
| POST | `/admin/exams` | [exams.py:87](backend/app/routers/exams.py#L87) | `admin, principal` |
| POST | `/admin/exams/bulk-by-grade` | [exams.py:137](backend/app/routers/exams.py#L137) | `admin, principal` |
| GET | `/admin/exams` | [exams.py:223](backend/app/routers/exams.py#L223) | `get_current_user` |
| GET | `/admin/exams/{id}/room-suggestions` | [exams.py:303](backend/app/routers/exams.py#L303) | `admin, principal` |
| POST | `/admin/exams/{id}/schedules` | [exams.py:393](backend/app/routers/exams.py#L393) | `admin, principal` |
| GET | `/admin/exams/seating` | [exams.py:557](backend/app/routers/exams.py#L557) | `get_current_user` |
| GET | `/admin/exams/invigilations/me` | [exams.py:652](backend/app/routers/exams.py#L652) | `teacher, admin, principal` |

### Master data CRUD (all `require_role("admin","principal")` via `_MUTATOR`)

`master_data.py` — 24 routes: full CRUD + deactivate/reactivate for
`/admin/schools`, `/admin/classes`, `/admin/subjects`, `/admin/rooms`
([master_data.py:198-465](backend/app/routers/master_data.py#L198-L465)).

`teachers.py` — 10 routes under `/admin/teachers`, incl. `POST /{id}/subjects`,
`DELETE /{id}/subjects/{subject_id}`, `POST /{id}/unavailability`,
`DELETE /{id}/unavailability/{unavailability_id}`.

`students.py` — 6 routes under `/admin/students` (create/list/get/update/deactivate/reactivate).

`parents.py` — 8 routes under `/admin/parents`, incl.
**`POST /admin/parents/{parent_id}/children`** ([parents.py:164](backend/app/routers/parents.py#L164))
and **`DELETE /admin/parents/{parent_id}/children/{student_id}`**
([parents.py:182](backend/app/routers/parents.py#L182)) — this is how parent-child
links get created outside admissions.

### Confirm/deny: the endpoints your playbook claims are live

| Playbook endpoint | Verdict | Reality |
| --- | --- | --- |
| `GET /attendance/summary/{student_id}` | ⚠️ **wrong shape** | Path is `GET /attendance/summary?from_date=&to_date=&student_id=` — query params, not a path segment. Parents **must** pass `student_id` or get a 400. |
| `GET /risk/flagged/{student_id}` | ⚠️ **wrong shape** | Path is `GET /risk/flagged?student_id=`. Same parent rule. |
| `GET /fees/schedule/{student_id}` | ❌ **NOT FOUND** | The parent-facing fee view is `GET /admin/fees/status?student_id=`. `GET /admin/fees/schedules` is admin config, not per-student. `api-contract.md` line ~2255 explicitly records `GET /parent/children/{id}/fees` as "superseded, never built". |
| `GET /timetable/active` | ✅ **exists as documented** | `?academic_year=&class_id=&teacher_id=&student_id=` |
| `GET /gradebook/student/{id}` | ❌ **NOT FOUND** | No gradebook router, model, or table. Documented only at `api-contract.md:2069` as `GET /gradebook/{student_id}`. |
| `GET /gradebook/class/{id}/subject/{id}` | ❌ **NOT FOUND** | Not even in the contract doc. |
| `GET /remarks/student/{id}` | ❌ **NOT FOUND** | Only the `remark_stubs` table and `services/remark_sentiment.py` exist. No endpoint. |
| `GET /analytics/student/{id}` | ❌ **NOT FOUND** | Nowhere in code or contract. |
| `POST /resources/upload` | ❌ **NOT FOUND** | No resources table/router. The only upload endpoint is `POST /admin/ocr/documents`. |
| `POST /quizzes/{id}/questions` | ❌ **NOT FOUND** | No quizzes anything. |
| **Any API that marks a fee paid** | ✅ **TWO EXIST** | See below — **this is not a blocker.** |

**Fee payment — you have what you need.** Two endpoints:

```python
# backend/app/routers/fees.py:332 — admin/principal, amount reconciliation
@router.post("/admin/fees/records/{fee_record_id}/payment", response_model=PaymentResponse)
def record_payment(fee_record_id: int, body: PaymentRequest,
                   user: CurrentUser = Depends(require_role("admin", "principal")), ...)

class PaymentRequest(BaseModel):
    amount: float
    paid_at: datetime | None = None   # defaults to now

class PaymentResponse(BaseModel):
    fee_record_id: int
    amount_paid: float
    amount_due: float
    status: str      # "paid" | "partial" | "pending" | "overdue"
```

```python
# backend/app/routers/fees.py:381 — TEACHER ONLY, boolean toggle
@router.patch("/admin/fees/records/{fee_record_id}/mark-paid", response_model=PaymentResponse)
def mark_fee_paid(fee_record_id: int, body: MarkPaidRequest,
                  user: CurrentUser = Depends(require_role("teacher")), ...)

class MarkPaidRequest(BaseModel):
    paid: bool
```

`record_payment` scopes by `User.school_id == user.school_id`; `mark_fee_paid` scopes
to the teacher's own classes via `SchoolClass.class_teacher_id`. Both write audit
entries. Both mutate `amount_paid` and derive `status`. **Neither is reachable by a
parent** — there is no parent-initiated payment endpoint, which is correct for an
"admin confirms payment" flow but means your parent-side UI is display-only until an
admin acts.

### Actual response shapes (verbatim from the Pydantic models)

```python
# GET /parent/children  →  ChildrenResponse   (routers/parent.py:26-35)
class LinkedChild(BaseModel):
    id: int
    name: str                 # User.full_name or falls back to User.email
    class_id: int | None      # None if no primary Enrollment
    class_name: str | None
class ChildrenResponse(BaseModel):
    items: list[LinkedChild]
```
Example: `{"items":[{"id":103,"name":"Demo Student Class 8A #01","class_id":41,"class_name":"Class 8A"}]}`

```python
# GET /attendance/summary  →  SummaryResponse
class SummaryItemOut(BaseModel):
    student_id: int
    class_id: int
    present_count: int
    absent_count: int
    late_count: int
    total_records: int
    present_pct: float        # rounded to 1dp, 0.0 when total == 0
class SummaryResponse(BaseModel):
    from_date: date
    to_date: date
    items: list[SummaryItemOut]
```

```python
# GET /risk/flagged  →  list[FlagOut]   (routers/risk.py:52-70)
class FlagOut(BaseModel):
    id: int
    student_id: int
    risk_level: str           # "high" | "medium" | "low"
    score: float
    reasons: list[str]
    flagged_at: datetime
    status: str               # "open" | "acknowledged" | "resolved"
    resolved_by: int | None
    resolved_at: datetime | None
    # enrichment, computed per-response, not persisted:
    class_id: int | None
    class_name: str | None
    homeroom_teacher_id: int | None
    parent_ids: list[int]     # ← already built for a future notifier
    student_name: str | None
```

**Note `FlagOut.parent_ids`** — [risk.py:73-77](backend/app/routers/risk.py#L73-L77)
says it exists so "a future notifier [can] reach teacher+parent+counselor without a
re-query". That future notifier is you. This is the cleanest hook in the codebase for
your auto-alerts.

```python
# GET /admin/fees/status  →  StatusResponse   (routers/fees.py:235-248)
class StatusItemOut(BaseModel):
    student_id: int
    fee_record_id: int
    amount_due: float
    amount_paid: float
    due_date: date
    status: str               # "pending" | "partial" | "paid" | "overdue"
    fee_type: str             # from the joined FeeSchedule
class StatusResponse(BaseModel):
    items: list[StatusItemOut]
```

```python
# GET /timetable/active  →  list[SlotOut]   (routers/timetable.py:57-70)
class SlotOut(BaseModel):
    id: int
    day_of_week: int          # 0 = Monday
    period_number: int
    start_time: time          # serialized "HH:MM:SS"
    end_time: time
    subject_id: int
    teacher_id: int
    class_id: int
    room_id: int
    academic_year: str
    is_active: bool
```
Returns **bare IDs only** — resolve names via `GET /reference/lookup`.

```python
# GET /reference/lookup?school_id=N  →  LookupResponse   (routers/reference.py:64-69)
class LookupResponse(BaseModel):
    subjects: list[SubjectItem]    # {id, name, periods_per_week, lab_required}
    teachers: list[TeacherItem]    # {id, name, max_periods_per_week, subject_ids}
    students: list[NamedItem]      # {id, name}
    rooms:    list[RoomItem]       # {id, name, room_type}
    classes:  list[ClassItem]      # {id, name, grade_level, grade_label, section, class_teacher_id}
```

```python
# GET /auth/me  →  inline dict (frontend type at api/hooks/useAuth.ts:4-10)
{ "sub": str, "email": str | None, "role": str | None,
  "user_id": int, "school_id": int | None }
```

### Global conventions

| Concern | Reality |
| --- | --- |
| Envelope | **Inconsistent.** Three shapes coexist: bare list (`GET /timetable/active` → `list[SlotOut]`, `GET /admin/fees/schedules` → `list[ScheduleOut]`, `GET /risk/flagged` → `list[FlagOut]`), `{items: [...]}` (`/parent/children`, `/admin/fees/status`, `/attendance/summary`, `/admin/alerts`), and bare objects (`/auth/me`). There is **no** `{data: ...}` wrapper anywhere. |
| Errors | FastAPI default `{"detail": string}`. Handlers raise `HTTPException(status.HTTP_4XX, "message")`. 422 bodies carry FastAPI's structured validation list. Frontend flattens it at [client.ts:25-40](frontend/src/api/client.ts#L25-L40) into `ApiError{status, message, body}`. |
| Pagination | **Not implemented anywhere.** `api-contract.md:16-17` specifies `?page=&page_size=` with `{items,total,page,page_size}`, but **no route accepts a `page` param and no response carries `total`**. Every list endpoint returns everything. |
| Datetimes | ISO 8601 with offset (tz-aware columns). `date` → `"YYYY-MM-DD"`, `time` → `"HH:MM:SS"`. |
| Validation errors | Pydantic → FastAPI 422 with `detail: [{loc, msg, type}]`. |
| Casing | snake_case throughout, request and response. |

### OpenAPI

[main.py:46](backend/app/main.py#L46) constructs `FastAPI(...)` with no `docs_url` /
`openapi_url` override, so the defaults are live: **`/docs` (Swagger UI), `/redoc`,
`/openapi.json`**. No auth gate on them.

---

## Section 6 — Real-time layer

**No Socket.io. This was an explicit, documented decision — not an oversight.**

[admin_alerts.py:170-178](backend/app/routers/admin_alerts.py#L170-L178):

> ```
> # --- Live feed: SSE, not Socket.io ---
> # Checked first: Socket.io is named in the tech stack doc but nothing in this repo
> # [uses it] … Standing up Socket.io infrastructure for this one feature
> # [is not justified] … can introduce Socket.io later for chat and this endpoint can
> # move onto the same [transport].
> ```

| Question | Answer |
| --- | --- |
| `python-socketio` server? | **NOT FOUND** — not in `requirements.txt`, not imported anywhere |
| `socket.io-client` on frontend? | **NOT FOUND** — not in `package.json` |
| ASGI mount / separate service? | N/A |
| Handshake auth | N/A |
| Rooms / namespaces | N/A |

**What exists instead — Server-Sent Events, one endpoint:**

| Event/stream | Payload | Emitter | Consumer |
| --- | --- | --- | --- |
| `GET /admin/alerts/stream` (`text/event-stream`) | `data: [AlertOut, …]` — a full snapshot of the alert list, re-sent every poll interval | [admin_alerts.py:216-221](backend/app/routers/admin_alerts.py#L216-L221) `stream_alerts` → `_alert_event_stream` ([:195](backend/app/routers/admin_alerts.py#L195)) → `_format_sse_event` ([:190](backend/app/routers/admin_alerts.py#L190)) | [useAlerts.ts:`useAlertsLiveStream`](frontend/src/api/hooks/useAlerts.ts) → `AdminDashboard.tsx` |

It's **snapshot-push, not event-diff**: the server re-runs `aggregate_alerts(db, …)`
on a `poll_interval` loop and pushes the whole array. Auth is `require_role("admin",
"principal")` on the HTTP request itself.

**The frontend client is the pattern worth stealing.** `EventSource` can't attach an
`Authorization` header, so `useAlertsLiveStream` uses `fetch` + a manual
`ReadableStream` reader and writes snapshots directly into the TanStack Query cache
via `queryClient.setQueryData`:

```ts
const res = await fetch(`${API_BASE_URL}/admin/alerts/stream`, { headers, signal: controller.signal });
const reader = res.body.getReader();
// … split on "\n\n", parse "data: " lines …
queryClient.setQueryData(["admin-alerts", undefined], { items });
```

**Reconnection: there is none.** On stream error it `console.warn`s and stops
([useAlerts.ts](frontend/src/api/hooks/useAlerts.ts), `catch (err) { … console.warn("Alert stream disconnected", err) }`).
No backoff, no retry. If you build a notification bell on this pattern you must add
reconnection yourself.

**Day-1 impact:** for a notification bell and a doubt-thread feed, this SSE + fetch-reader
+ `setQueryData` pattern is a proven, working template you can copy in an afternoon.
Real bidirectional class chat would need new infrastructure. That materially favors
cutting casual class chat (see §9).

---

## Section 7 — Frontend architecture

### Router

`react-router-dom` v6. Single route table, [App.tsx:38-82](frontend/src/App.tsx#L38-L82)
— a declarative `ROUTE_CONFIG[]` array mapping `{path, role, element}`, rendered at
[App.tsx:114-120](frontend/src/App.tsx#L114-L120) with every entry wrapped in
`<ProtectedRoute allowedRoles={[routeRole]}>`.

| Path | Component | Guard |
| --- | --- | --- |
| `/login` | `Login` | none |
| `/signup` | `Signup` | none |
| `/onboarding` | `OnboardingWizard` | `admin, principal` |
| `/` | `<Navigate to={role ? "/"+role : "/login"}>` | inside `Layout` |
| `/principal` + 10 sub-routes | dashboard + Timetable/Staffing/Risk/Syllabus/Approvals/Ocr/Fees/Admissions/Exams/SchoolManagement | `principal` |
| `/admin` + 11 sub-routes | same + Attendance | `admin` |
| `/teacher` + 7 sub-routes | Timetable/Attendance/Staffing/Risk/Syllabus/Fees/InvigilationDuties | `teacher` |
| `/student` + 3 sub-routes | Timetable/Fees/StudentSeatLookup | `student` |
| `/parent` + 3 sub-routes | Timetable/Risk/Fees | `parent` |
| `*` | `<Navigate to="/">` | — |

**42 routes total.** Guarding is `ProtectedRoute` ([components/ProtectedRoute.tsx](frontend/src/components/ProtectedRoute.tsx)),
which reads `useAuthStore().role` — the role comes from the Supabase JWT's
`app_metadata.role` claim ([authStore.ts:17-22](frontend/src/store/authStore.ts#L17-L22)),
not from `/auth/me`.

### App shell

[Layout.tsx](frontend/src/components/Layout.tsx) — persistent shell with `<Outlet/>`.
Structure: a **desktop hover-expand icon rail** (`w-20` → `hover:w-64`, a real flex
sibling not an overlay, [Layout.tsx:90-93](frontend/src/components/Layout.tsx#L90-L93)),
a **mobile drawer** ([:96-113](frontend/src/components/Layout.tsx#L96-L113)), and a
**sticky header**.

Here is the header verbatim — **your notification bell goes at [Layout.tsx:133](frontend/src/components/Layout.tsx#L133)**,
in the right-hand `flex items-center gap-3` cluster, before `<ThemeToggle />`:

```tsx
<header className="sticky top-0 z-30 flex h-16 shrink-0 items-center justify-between border-b border-border bg-panel/80 px-4 backdrop-blur-md sm:px-6">
  <div className="flex items-center gap-3">
    <Button variant="ghost" size="icon" className="md:hidden"
            onClick={() => setMobileOpen(true)} aria-label="Open navigation menu">
      <Menu className="h-5 w-5" />
    </Button>
    {role && (
      <span className="hidden rounded-full bg-accent/10 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-accent sm:inline-block">
        {ROLE_LABEL[role]}
      </span>
    )}
  </div>
  <div className="flex items-center gap-3 text-sm">
    <span className="hidden truncate text-ink-muted sm:inline">{user?.email}</span>
    <ThemeToggle />
    <Button variant="outline" size="sm" onClick={handleLogout}>
      <LogOut className="h-3.5 w-3.5" />
      <span className="hidden sm:inline">Log out</span>
    </Button>
  </div>
</header>
```

Nav is data-driven from [lib/navConfig.ts](frontend/src/lib/navConfig.ts) —
`NAV_ITEMS: Record<Role, NavItem[]>`. Adding a "Messages"/"Announcements" entry per
role is a one-line-per-role edit there, no `Layout.tsx` change needed.

`handleLogout` calls `queryClient.clear()` before navigating
([Layout.tsx:70-78](frontend/src/components/Layout.tsx#L70-L78)) — query keys aren't
user-scoped, so cache must be nuked on logout. **Your notification query keys will
inherit this constraint.**

### The five dashboards — all real

| Role | File | LOC | State | What actually renders |
| --- | --- | --- | --- | --- |
| Principal | [PrincipalDashboard.tsx](frontend/src/routes/principal/PrincipalDashboard.tsx) | 102 | **complete** | Alert summary stat tiles, live alert feed with inline resolve, pending-approvals count, active-classes count from timetable, 30-day attendance %, `<Link>` quick-nav |
| Admin | [AdminDashboard.tsx](frontend/src/routes/admin/AdminDashboard.tsx) | 97 | **complete** | Tabbed alert feed (all/urgent/normal) + `useAlertsLiveStream` SSE + resolve mutation + skeletons + empty states |
| Teacher | [TeacherDashboard.tsx](frontend/src/routes/teacher/TeacherDashboard.tsx) | 154 | **complete** | Today's periods (name-resolved), flagged students, pending leave, syllabus "behind" count, substitute duties, quick links |
| Student | [StudentDashboard.tsx](frontend/src/routes/student/StudentDashboard.tsx) | 94 | **complete** | Today's schedule, 30-day attendance; handles the "not enrolled" 404 explicitly with `retry: false` |
| Parent | [ParentDashboard.tsx](frontend/src/routes/parent/ParentDashboard.tsx) | 133 | **complete** | **Multi-child `<Select>`**, attendance %, open risk flags, today's schedule, honest "No linked children" empty state |

None are shells. All fetch live data, show loading skeletons (`animate-pulse`), and
handle empty/error states. Your "dashboard polish" task is **enhancement, not
construction** — the realistic additions are a notification bell, an announcement
strip, and accessibility (§9.11).

### Design system

`tailwind.config.js` + CSS custom properties in `src/index.css`. `darkMode: ["class"]`,
toggled by [store/themeStore.ts](frontend/src/store/themeStore.ts) + `ThemeToggle.tsx`.

**Your brand hexes are real, named tokens — nothing is hardcoded.**
[index.css:11-24](frontend/src/index.css#L11-L24):

```css
--paper:  216 29% 97%;   /* #F4F6F9 */
--panel:  0 0% 100%;     /* #FFFFFF — sidebar/header surface */
--card:   0 0% 100%;     /* #FFFFFF */
--ink:    222 47% 11%;   /* #0F172A */
--accent: 215 100% 41%;  /* #0056D2 */
--accent-hover: 216 100% 33%;  /* #0043A8 */
--urgent: 0 84% 60%;   --positive: 160 84% 39%;   --warning: 38 92% 50%;
--radius: 0.625rem;
```

A full `.dark` block redefines every token ([index.css:56+](frontend/src/index.css#L56)).
Six `--chip-N` hues exist for timetable subject color-coding.

Fonts: `font-display` = **Montserrat**, `font-sans` = **Roboto**, `font-mono` =
Roboto Mono ([tailwind.config.js](frontend/tailwind.config.js) `fontFamily`), loaded
from Google Fonts at [index.html:9-10](frontend/index.html#L9-L10).

Custom `fontSize` scale (base = `0.9375rem`), `borderRadius` up to `3xl: 1.75rem`,
and three shadow tokens (`panel`, `elevated`, `floating`). **Use the semantic tokens
(`bg-paper`, `text-ink-muted`, `bg-accent`), not raw hex** — that's the codebase
convention and it's what makes dark mode work.

### shadcn/ui

Installed (`components.json` present, `class-variance-authority` + `tailwind-merge` +
`clsx` in deps). **10 components in `components/ui/`:**

`badge.tsx`, `button.tsx`, `card.tsx`, `dialog.tsx`, `field.tsx`, `input.tsx`,
`select.tsx`, `table.tsx`, `tabs.tsx`, `textarea.tsx`

Radix primitives installed: `@radix-ui/react-dialog`, `react-select`, `react-tabs`
only. **Missing for your scope:** no `popover` (bell dropdown), `dropdown-menu`,
`scroll-area`, `avatar`, `toast`/`sonner`, `skeleton`, `sheet`, `tooltip`,
`accordion`. Each needs its Radix package added.

Plus 7 hand-rolled shared components: `ConfirmDialog`, `EntityCard`, `FileDropzone`,
`PageHeader`, `ProgressBar`, `QuickLinkCard`, `StatTile`.

### Zustand stores

| Store | File | Shape | Subscribers |
| --- | --- | --- | --- |
| `useAuthStore` | [authStore.ts](frontend/src/store/authStore.ts) | `{session, user, role, isLoading, setSession, setLoading, clear}` | `App.tsx`, `Layout.tsx`, `ProtectedRoute.tsx`, `ParentDashboard.tsx`, `FeesPage.tsx`, `RiskDashboard.tsx`, `TimetablePage.tsx` |
| `useThemeStore` | [themeStore.ts](frontend/src/store/themeStore.ts) | theme + toggle | `ThemeToggle.tsx` |

Only two stores. No middleware, no persist, no devtools. Server state lives entirely
in TanStack Query — **follow that split**; don't put notifications in Zustand.

### TanStack Query

Provider: `queryClient` from [api/queryClient.ts](frontend/src/api/queryClient.ts),
mounted in `main.tsx`.

```ts
export const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, retry: 1 } },
});
```

**Query-key convention: a flat array — `[kebab-case-resource, ...params]`.** No
hierarchical key factory, no `as const` objects. Two real examples:

```ts
// frontend/src/api/hooks/useAlerts.ts
export function useAlerts(severity?: "normal" | "urgent") {
  return useQuery({
    queryKey: ["admin-alerts", severity],
    queryFn: () => apiGet<{ items: Alert[] }>("/admin/alerts", { severity }),
  });
}
```

```ts
// frontend/src/api/hooks/useFees.ts
export function useFeeStatus(params: { classId?: number; studentId?: number; status?: string; enabled?: boolean } = {}) {
  return useQuery({
    queryKey: ["fee-status", params.classId, params.studentId, params.status],
    queryFn: () => apiGet<{ items: FeeStatusItem[] }>("/admin/fees/status", {
      class_id: params.classId, student_id: params.studentId, status: params.status,
    }),
    enabled: params.enabled ?? true,
  });
}
```

Mutations invalidate by key prefix: `queryClient.invalidateQueries({ queryKey: ["fee-status"] })`.

**14 hook modules** in `api/hooks/`: `useAdmissions`, `useAlerts`, `useApprovals`,
`useAttendance`, `useAuth`, `useExams`, `useFees`, `useMasterData`, `useOcr`,
`useParent`, `useRisk`, `useStaffing`, `useSyllabus`, `useTimetable`. Add
`useNotifications.ts`, `useChat.ts`, `useAnnouncements.ts` alongside them.

### API client

[api/client.ts](frontend/src/api/client.ts) — hand-written `fetch` wrapper, **no
axios**.

- Token attachment: `authHeaders()` calls `supabase.auth.getSession()` **per request**
  and returns `{ Authorization: \`Bearer ${token}\` }` ([client.ts:5-9](frontend/src/api/client.ts#L5-L9)).
- Exports: `apiGet`, `apiPost`, `apiPostForm` (multipart), `apiPut`, `apiPatch`,
  `apiDelete`, plus `API_BASE_URL` and `authHeaders` (the latter two exist so the SSE
  hook can build its own `fetch`).
- Errors: `handle<T>()` throws `ApiError{status, message, body}` — `body` preserves
  the raw parsed JSON for structured details ([client.ts:11-40](frontend/src/api/client.ts#L11-L40)).
- 204 → `undefined`.

**Types: hand-written**, not generated. [api/types.ts](frontend/src/api/types.ts)
holds interfaces mirroring the Pydantic models (`LinkedChild`, `FeeStatusItem`,
`Alert`, `AlertsSummary`, `FeeSchedule`, `PaymentResult`, …). There is no
`openapi-typescript` step — **types drift silently if the backend changes**.

### Existing chat / notification / parent / bot UI

**This is the most important paragraph in this report for you.**

| UI | Status | Evidence |
| --- | --- | --- |
| Chat UI (any kind) | **NOT FOUND** | no component, no route, no hook |
| Notification UI / bell | **NOT FOUND** | `Layout.tsx` header has only email + theme + logout |
| Bot / conversation UI | **NOT FOUND** | — |
| Doubt threads | **NOT FOUND** | — |
| Announcement feed | **NOT FOUND** | — |
| **Parent screens** | **IMPLEMENTED — 4 of them** | see below |
| **Multi-child selector** | **IMPLEMENTED — 4 duplicated copies** | see below |

Parent-facing screens that already work:
- [ParentDashboard.tsx](frontend/src/routes/parent/ParentDashboard.tsx) — attendance %, risk flags, today's schedule, child selector
- [TimetablePage.tsx:20-38](frontend/src/components/timetable/TimetablePage.tsx#L20-L38) — parent mode with child selector
- [RiskDashboard.tsx:226-240](frontend/src/components/risk/RiskDashboard.tsx#L226-L240) — parent mode with child selector
- [FeesPage.tsx:531-556](frontend/src/components/fees/FeesPage.tsx#L531-L556) — parent mode with child selector; `mode: "admin" | "teacher" | "parent" | "student"` at [:287](frontend/src/components/fees/FeesPage.tsx#L287)

The multi-child pattern, repeated verbatim in all four:

```tsx
const children = useParentChildren();
const [selectedChildId, setSelectedChildId] = useState("");
useEffect(() => {
  if (!selectedChildId && children.data?.items.length) {
    setSelectedChildId(String(children.data.items[0].id));
  }
}, [children.data, selectedChildId]);
const parentStudentId = role === "parent" && selectedChildId ? Number(selectedChildId) : undefined;
const showChildSelect = role === "parent" && (children.data?.items.length ?? 0) > 1;
```

**Extract this into a `useSelectedChild()` hook before adding a fifth copy.** That's
the single highest-leverage cleanup in your scope.

### Libraries

| Concern | Library | Status |
| --- | --- | --- |
| Icons | `lucide-react` ^0.446.0 | ✅ installed, used everywhere |
| Toast / notifications | — | **NOT FOUND** — errors render as inline `<p className="text-urgent">` |
| Forms | — | **NOT FOUND** — no `react-hook-form`, no `zod`. All forms are manual `useState` + a hand-rolled `ui/field.tsx` |
| Charts | — | **NOT FOUND** — no recharts/chart.js/d3. `shared/ProgressBar.tsx` + `StatTile.tsx` are the only "viz" |
| Date handling | — | **NOT FOUND** — no date-fns/dayjs. Native `Date` + helpers in `lib/format.ts` and inline `daysAgo()` (duplicated in 3 dashboards) |
| Animation | — | none |
| i18n | — | **NOT FOUND** — no `react-i18next`. Your multilingual task is greenfield |

### Mobile responsiveness

**Partial and uneven.** The shell is genuinely responsive: `Layout.tsx` has a real
mobile drawer and `md:`/`sm:` breakpoints throughout. Feature components use
`flex-wrap` and `overflow-x-auto` on tables.

**The dashboards are not.** Breakpoint usage across all of `src/routes/`: **2 `sm:`
and 1 `lg:`** total. `ParentDashboard`, `StudentDashboard`, `TeacherDashboard` rely on
`flex flex-wrap gap-3` for stat tiles, which degrades acceptably but was never
designed for small screens. `TimetableGrid` and the seating chart will overflow
badly on mobile.

---

## Section 8 — AI / RAG readiness

**Thin. Almost nothing here is reusable for RAG.** Summary in one line: the ML in
this repo is classical (OpenCV/scikit-learn/VADER), there is no LLM, and the only
"AI infra" you inherit is pgvector-the-extension and APScheduler.

### LLM client

**`NOT FOUND`.** `grep -rniE "openai|anthropic|langchain|llm|gemini|ollama"` across
`backend/app`, `backend/scripts`, `frontend/src` → zero hits.

`requirements.txt` has no LLM SDK. There is no API key env var, no wrapper module, no
inline call. Provider choice, key management, prompt templates, streaming, cost
guarding — **all day-1 decisions for you.**

### Embeddings and chunking

**`NOT FOUND`** for text. What exists is unrelated:
- `face_recognition` / `dlib` produce 128-dim **face** embeddings
  ([services/attendance_cv.py](backend/app/services/attendance_cv.py), stored in
  `face_embeddings.embedding`).
- No text chunker, no tokenizer, no splitter, no `kb_chunks`.

What you *can* reuse is the **pattern**, not the code: `Vector(N)` columns work here,
the extension is enabled, and `pgvector.sqlalchemy` is installed.

### Background jobs — this part is genuinely good

**APScheduler is wired into the FastAPI lifespan and running for real.**

[app/scheduler.py](backend/app/scheduler.py) + [main.py:34-43](backend/app/main.py#L34-L43):

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    shutdown_scheduler()
```

`BackgroundScheduler` + `CronTrigger`. Four jobs, each fanning out over every
`(school_id, academic_year)` pair with at least one active class:

| Job | Schedule | Underlying function |
| --- | --- | --- |
| Nightly risk scoring | 02:00 UTC | `scripts.run_nightly_risk_scoring.run_nightly_scoring` |
| Nightly syllabus/anomaly scan | 02:15 UTC | `scripts.run_nightly_syllabus_anomaly_scan.run_scan` |
| Nightly admin briefing | 02:30 UTC | `scripts.run_nightly_admin_briefing.compile_briefing` |
| Nightly fee invoicing | 02:45 UTC | `scripts.run_monthly_fee_invoicing.run_monthly_invoicing` |

**This is exactly what you need for a weekly doubt-clustering job and for KB
reindexing.** Adding a fifth job is a `scheduler.add_job(...)` call plus a pure
function in `scripts/`, following the established "wrapper calls the same function
the CLI script calls" convention.

Caveats: it's **in-process** — jobs run in the uvicorn process, with no job store, no
distributed lock, no retry. Two backend replicas = duplicate runs. For a hackathon
that's fine. Note also that leaving a dev server running overnight **writes real
rows** (`CLAUDE.md` warns about this).

**Also available:** FastAPI's `BackgroundTasks` (never used in this codebase —
`grep` → 0 hits). **`NOT FOUND`:** Celery, RQ, Dramatiq, Huey, Redis, cron.

### Object storage

**`NOT FOUND`.** No R2, S3, `boto3`, or Supabase Storage. `grep -rniE
"boto3|s3_|cloudflare|r2_"` → zero hits outside `venv`.

The one upload path in the codebase **deliberately discards the file**:

```python
# backend/app/routers/documents.py:196-206
document = Document(uploaded_by=user.id, school_id=school_id,
                    document_type=document_type, file_url="pending", status="queued")
db.add(document); db.flush()
# Descriptive reference only - see Document's docstring: the image itself is
# processed in-memory below and not persisted anywhere durable.
document.file_url = f"documents/{document.id}/{file.filename or 'upload'}"

image_bytes = await file.read()
```

`Document.file_url` is a **fabricated descriptive string**, not a real URL. Nothing
in this repo stores a binary anywhere.

**Impact on you:** `POST /resources/upload` (teacher uploads notes → RAG ingests
them) has no storage layer beneath it. You must add one — Supabase Storage is the
path of least resistance since the project already has a Supabase service-role key
([supabase_admin.py:36-37](backend/app/services/supabase_admin.py#L36-L37)) and an
admin client helper.

### Webhook pattern for reindex triggers

**`NOT FOUND`.** No inbound webhook receiver, no signature verification, no outbound
webhook dispatch anywhere.

The closest analogue to "state change triggers work" is the **synchronous inline
trigger** in `POST /admin/fees/schedules`, which calls the invoicing routine directly
on creation (documented in `CLAUDE.md`). For resource-upload → reindex, follow that
same shape: call the ingestion function inline (or via `BackgroundTasks`) from the
upload handler, and let the APScheduler job handle periodic full reindex. Don't
invent a webhook layer — there's no precedent to follow and no second service to
call it.

---

## Section 9 — What already exists in Person C's scope

| # | Task | Status | Evidence |
| --- | --- | --- | --- |
| 1 | **Notification center** | **NOT FOUND** | No `notifications` table/model/migration. No `/notifications` route. No bell UI in `Layout.tsx`. Spec'd only at `api-contract.md:2212-2226`. |
| 2 | **Student Doubt Bot / RAG** | **NOT FOUND** | No `kb_chunks`, no ingestion, no `/chat/student-bot`, no chat UI, no LLM client. Spec'd at `api-contract.md:2147-2155`. |
| 3 | **Teacher Assistant Bot** | **NOT FOUND** | `api-contract.md:2156` only. |
| 4 | **Parent Assistant Bot** | **NOT FOUND** | `api-contract.md:2160` only. |
| 5 | **Doubt threads** | **NOT FOUND** | No `doubt_threads`/`thread_replies`. `POST /doubts`, `GET /doubts/{id}` spec'd at `api-contract.md:2181-2193`, never built. |
| 6 | **Announcement feed** | **NOT FOUND** | No `announcements` table, no scoping logic, no acknowledgment concept anywhere. Spec'd at `api-contract.md:2195-2210`. |
| 7 | **Parent portal — performance/attendance** | **PARTIAL** | Attendance: ✅ `GET /attendance/summary?student_id=` + rendered on `ParentDashboard.tsx:94-98`. Academic performance: **NOT FOUND** — no gradebook exists to summarize. `GET /parent/children/{id}/performance` (`api-contract.md:2260`) is unbuilt and unbuildable until grades exist. |
| 8 | **Parent portal — fees + payment** | **PARTIAL** | Parent fee view ✅ live: `FeesPage.tsx:531+` parent mode → `GET /admin/fees/status?student_id=`. Payment **confirmation** ✅ exists backend-side (`POST …/payment` admin/principal, `PATCH …/mark-paid` teacher) with a "Record payment" dialog at `FeesPage.tsx:233-258`. **Parent-initiated payment: NOT FOUND** — no gateway, no parent-callable endpoint. |
| 9 | **Multi-child selector** | **IMPLEMENTED ×4 (duplicated)** | `ParentDashboard.tsx:57-71`, `TimetablePage.tsx:20-38`, `RiskDashboard.tsx:226-240`, `FeesPage.tsx:531-556` — all via `useParentChildren()` → `GET /parent/children`. **Extend/refactor, don't rebuild.** |
| 10 | **Dashboard polish** | **All 5 complete** | See §7. Enhancement work only. |
| 11 | **Accessibility** | **Very thin** | See below. |

### 11 — Accessibility density (measured)

Across **48 `.tsx` files**, only **7 contain any `aria-*` attribute**. Full census:

| Attribute | Count | Where |
| --- | --- | --- |
| `aria-label` | 7 | `Layout.tsx:105,123`; `ThemeToggle.tsx:13`; `GenerateTimetableForm.tsx:48`; `TimetableGrid.tsx:242,256,271` |
| `aria-hidden` | 4 | `ProgressBar.tsx:28`; `FeesPage.tsx:275`; `StatTile.tsx:49`; `TimetableGrid.tsx:327` |
| `role="…"` | 2 | `FileDropzone.tsx:39` (`button`); `GenerateTimetableForm.tsx:41` (`switch`) |
| `tabIndex` | 1 | `FileDropzone.tsx:40` |
| `sr-only` | 2 | `AttendanceCapture.tsx:60`; `ui/dialog.tsx:40` |
| `aria-live` | **0** | — |
| `htmlFor` | **0** | **no form label is programmatically associated with its input** |
| `alt=` | 1 | — |

**Are icon-only buttons labeled? Only in 4 files.** The `Layout.tsx` menu buttons,
`ThemeToggle`, and three `TimetableGrid` dismiss buttons are labeled. Every other
icon-only `<Button size="icon">` in the codebase is unlabeled.

Concrete gaps: no `aria-live` region means loading/error state changes are silent to
screen readers; `htmlFor: 0` means `ui/field.tsx` renders visual labels not bound to
inputs; no skip-link; no focus-visible audit. **This is a real, well-defined,
demo-able task with a clear before/after.**

### Does any chat implementation exist? — the cut/keep decision

**No. Zero.** Not the tables, not the endpoints, not the socket events, not the UI.

The evidence that matters for your decision:

1. **No transport.** No Socket.io server or client (§6). The only real-time primitive
   is one SSE snapshot-push endpoint with **no reconnection logic**.
2. **Explicitly deferred by the codebase author.** [admin_alerts.py:176-178](backend/app/routers/admin_alerts.py#L176-L178)
   says a future session "can introduce Socket.io later **for chat**" — chat was
   consciously left out.
3. **No polling fallback exists either**, and `api-contract.md:2306` records the open
   question of "whether `GET .../chat?since=` is the real transport or just a
   fallback" — unanswered.
4. Existing frontend has **no message-list, composer, or avatar component**, and no
   `scroll-area` primitive.

**Recommendation: cut casual class chat.** Nothing is half-built, so cutting costs
you zero sunk work. Spend the transport budget on doubt threads instead — those can
be plain request/response with TanStack Query `refetchInterval`, need no socket, and
directly feed the Doubt Bot's corpus. If you later want live-ness, the SSE +
fetch-reader + `setQueryData` pattern in `useAlerts.ts` is a proven template you can
copy for notifications and thread updates without adding Socket.io at all.

---

## Section 10 — Seed data

Script: [`backend/scripts/seed_demo_data.py`](backend/scripts/seed_demo_data.py)
(plus `wipe_seeded_data.py`). Run: `python -m scripts.seed_demo_data [--force]`.

Idempotent by design — "check-then-insert by natural key" via `get_or_create()`;
re-running never duplicates or clobbers ([docstring lines 9-21](backend/scripts/seed_demo_data.py#L9)).

### What it creates

| Entity | Seeded? | Detail |
| --- | --- | --- |
| School | ✅ | one demo school |
| Classes | ✅ | `Class 8A`, `Class 8B` |
| Subjects, Rooms | ✅ | with `periods_per_week` / `lab_required` / `room_type` |
| Teachers | ✅ | `demo.teacher{i}@eduopsai.test` + `TeacherProfile` + `TeacherSubject` + one Friday `TeacherUnavailability` |
| Students | ✅ | `demo.student.{class_slug}.{i:02d}@eduopsai.test`, enrolled in classes |
| Enrollments | ✅ | primary (`subject_id=None, is_primary=True`) |
| **Parents** | ✅ | `demo.parent1..3@eduopsai.test` — 3 total, spread across both classes ([:163-166](backend/scripts/seed_demo_data.py#L163)) |
| **`parent_student` links** | ✅ | [:494](backend/scripts/seed_demo_data.py#L494) and [:510](backend/scripts/seed_demo_data.py#L510) |
| Attendance history | ✅ | `ATTENDANCE_HISTORY_DAYS` of synthetic records, `source="manual"`, for two students — one `"at_risk"` profile, one `"healthy"` |
| Leave history | ✅ | `HISTORY_WEEKS` of approved `LeaveRequest` rows with a deliberate Friday pattern for the forecaster |
| **Remarks** | ✅ | a handful of `RemarkStub` rows for sentiment analysis |
| `timetable_slots` | ❌ **deliberately empty** | generate via `POST /timetable/generate` |
| `face_embeddings` | ❌ **deliberately empty** | generate via `POST /attendance/enroll` |
| **Fee records** | ❌ **NOT SEEDED** | `FeeRecord`/`FeeSchedule` appear nowhere in the script |
| **Grades / assignments / resources** | ❌ | tables don't exist |
| Roles | ✅ (via migration `ea1917a428fe`, not this script) | |

### Can you get a working parent login with 2+ children today?

**Yes — one account, and it was set up specifically for this.**

[seed_demo_data.py:167-181](backend/scripts/seed_demo_data.py#L167-L181):

> ```
> # EXTENSION (frontend session - real multi-child parent dashboard testing):
> # test.parent@eduopsai.test is a genuine Supabase Auth account (see gettoken.py) an
> # engineer can actually log in as - unlike demo.parentN above, which are direct DB
> # [inserts] … It had zero parent_student links, which meant the
> # real multi-child selector on the parent dashboard could only ever be verified
> # [with] … ("Class 8A", 1): the SAME student as demo.parent1 above (real multi-guardian
> #   support …) … to any other parent, purely to exercise the multi-child selector for real.
> REAL_TEST_PARENT_EMAIL = f"test.parent@{DEMO_EMAIL_DOMAIN}"
> ```

- **Email: `test.parent@eduopsai.test`** — a real Supabase Auth account, **linked to
  2 children** by the seed script ([:505-512](backend/scripts/seed_demo_data.py#L505-L512)).
- **Password: not in the seed script.** `gettoken.py` hardcodes `EduOpsTest!2026` for
  `test.teacher@eduopsai.test`. It's plausible the parent account shares that
  password, but **the code does not state it** — verify with whoever provisioned the
  Supabase accounts. That's the one credential gap.
- **Caveat:** the seed script only links `test.parent@` **if its `users` row already
  exists** (`if real_parent is not None:` at [:507](backend/scripts/seed_demo_data.py#L507)).
  The row is created lazily by `_get_or_create_user` on that account's **first
  authenticated API call**. So the required order is: **log in once, then run the seed
  script** — running the seed first silently skips the multi-child links.
- `demo.parent1..3@eduopsai.test` have links but **cannot log in** — they're direct DB
  inserts with `uuid5`-derived `supabase_id`s and no Supabase Auth identity
  ([docstring lines 23-28](backend/scripts/seed_demo_data.py#L23)).

The script prints ready-to-paste IDs on completion, including
`"{REAL_TEST_PARENT_EMAIL} (user_id N) linked to real children: …"`
([:621-623](backend/scripts/seed_demo_data.py#L621-L623)).

### Is there enough content for a non-trivial RAG demo?

**No. You will author 100% of the demo curriculum content yourself.**

There is no `resources` table, no notes, no syllabus *content* (only
`SyllabusPlan.total_units` counts and `SyllabusCheckpoint.topic_label` strings), no
assignment text, and no document storage (§8 — OCR images are discarded after text
extraction). The only free text in the database is a handful of `RemarkStub` rows and
`ocr_results.raw_text` from whatever images someone happened to upload.

Budget real time for: authoring 2-3 chapters of plausible curriculum text, writing an
ingestion path, and seeding `kb_chunks`. This is not a half-day task.

---

## Section 11 — Risks and blockers

### Blockers for you specifically

| # | Blocked work | Missing piece | Who must resolve |
| --- | --- | --- | --- |
| 1 | **Parent Assistant Bot's "how is my child doing academically"** and `GET /parent/children/{id}/performance` | `gradebook_entries` table + `GET /gradebook/…` — **`NOT FOUND`, and nobody is building it** | Nobody is assigned. Decide: build a minimal gradebook yourself, or cut academic performance from the parent portal and ship attendance + fees + risk only. |
| 2 | **RAG ingestion** (`POST /resources/upload` → chunk → embed) | (a) no `resources` table, (b) **no object storage of any kind** (§8 — `Document.file_url` is a fabricated string), (c) no curriculum content to ingest | You. Add Supabase Storage using the existing service-role client (`services/supabase_admin.py`), and author demo content. |
| 3 | **All three bots** | No LLM client, no provider decision, no API key env var, no `.env.example` entry | You. This is genuinely day-1 — pick a provider before writing anything else. |
| 4 | **`test.parent@eduopsai.test` login** | Password not recorded in any file | Ask whoever provisioned the Supabase accounts (§10). |
| 5 | **Announcement scoping** ("target: class / role / school") | No precedent — no existing endpoint filters by role-set or targets a mixed audience | You. Design it; nothing constrains you. |

**Not blockers, despite the playbook's framing:** fee-mark-paid ✅ exists (two
endpoints), `/parent/children` ✅ exists, multi-child selector ✅ exists, attendance
summary ✅ exists, risk flags ✅ exist with `parent_ids` pre-computed.

### Contradictions between the playbooks and the code

Blunt list:

1. **"3-person team, vertical ownership."** One author, 13 commits. The split is
   fiction; nobody is building Person B's or Person C's scope but you.
2. **"Socket.io real-time" (tech stack).** Not installed on either side, and
   explicitly rejected in a code comment ([admin_alerts.py:172-178](backend/app/routers/admin_alerts.py#L172-L178)).
3. **"pgvector for RAG."** The extension is enabled and a `Vector(128)` column exists
   — but only for **face recognition**. Zero text-embedding infrastructure, and **no
   ANN index anywhere** (brute-force scan).
4. **"`GET /gradebook/student/{id}` is live, integrate rather than stub."** It does not
   exist in any form. Neither does `/remarks/student/{id}`, `/analytics/student/{id}`,
   `/resources/upload`, or `/quizzes/{id}/questions`.
5. **`GET /attendance/summary/{student_id}` / `GET /risk/flagged/{student_id}`.** Both
   are query-param endpoints, not path-param. Parents get a **400** if `student_id` is
   omitted, not an implicit "my children".
6. **`GET /fees/schedule/{student_id}`.** Doesn't exist. `api-contract.md` records the
   parent fee endpoint as "superseded, never built" — the real path is
   `GET /admin/fees/status?student_id=`, an `/admin/`-prefixed route that parents call.
7. **`api-contract.md` "Conventions" promises `?page=&page_size=` pagination and
   `{items, total, page, page_size}`.** **No route implements pagination.** No
   response carries `total`. Your notification and announcement feeds would be the
   first — decide whether to match the doc or match the code.
8. **`api-contract.md` implies one consistent envelope.** Three coexist (bare list,
   `{items}`, bare object) — §5.
9. **`CLAUDE.md`: "Do not build Person A/B/C's individual features until Phase 0 is
   merged."** Phase 0 was never formally merged, and Person A's entire feature set was
   built anyway. Treat this rule as dead.
10. **`GET /parent/children` response shape.** `api-contract.md:2240-2252` documents
    the mismatch honestly: the live shape is `{id, name, class_id, class_name}`, **not**
    the original stub's `{student_id, full_name, class_id}`. The frontend is wired to
    the live shape. Don't "fix" it toward the stub.

### Integration contracts to negotiate

Since there are no teammates, "negotiate" means "decide and write down". Concrete
proposals, each matching an existing codebase convention:

**A. Gradebook read (needed by Parent Bot + performance view)**

```http
GET /gradebook/student/{student_id}?academic_year=2026-27
Roles: student(self) | parent(linked) | teacher(own class) | admin | principal
```
```json
{ "student_id": 103,
  "items": [ { "subject_id": 7, "subject_name": "Mathematics", "assessment_count": 4,
               "average_pct": 78.5, "latest_score": 82, "latest_at": "2026-08-10T00:00:00Z" } ] }
```
Follow `fees.py`'s role-branching shape (`get_current_user` + per-role filter,
400 if a parent omits `student_id`, 403 if not linked).

**B. Notification dispatch (internal service, not HTTP)**

```python
# app/services/notify.py — mirrors services/audit_log.py exactly: db.add(), NO commit
def dispatch_notification(
    db: Session, *, user_id: int, type: str, message: str,
    entity_type: str | None = None, entity_id: int | None = None,
) -> Notification: ...
```
Call sites to wire in, all of which already compute their audience: `risk.py`'s
`_enrich_flag_out` (**`parent_ids` is already there**), `fees.py`'s
`trigger_reminders`, `staffing.py`'s `approve_leave`, `approvals.py`'s
`decide_approval`, `admissions.py`'s decision path.

**C. Resource upload + reindex**

```http
POST /resources/upload   (multipart: file, class_id, subject_id, title)
→ { "id": 12, "file_url": "https://…supabase.co/storage/v1/object/public/resources/…",
    "indexed": false }
```
Follow `documents.py`'s multipart handler shape — but **actually persist the file**,
unlike `documents.py`. Then either ingest inline (like `POST /admin/fees/schedules`
triggers invoicing synchronously) or enqueue for the APScheduler job.

**D. Parent-facing performance aggregate** — depends entirely on (A). Don't design
this until (A) is decided.

**E. Shared ownership-scoping helper** — proposed `app/services/scoping.py`:

```python
def assert_parent_linked(db: Session, parent_id: int, student_id: int | None) -> int: ...
def teacher_class_ids(db: Session, teacher_id: int) -> list[int]: ...
def students_in_classes(db: Session, class_ids: list[int]) -> set[int]: ...
```
This **contradicts the stated convention** at [fees.py:23-25](backend/app/routers/fees.py#L23-L25)
("each domain router keeps its own copy"). It's the right call, but it's a
deliberate reversal of a documented decision that touches four Person A routers —
make it a conscious choice, not a drive-by refactor.

### Landmines

| Landmine | Location | Bite |
| --- | --- | --- |
| **Parent-link check copy-pasted 4×** | `attendance.py:319`, `fees.py:284`, `risk.py:173`, `timetable.py:603` | Every new parent endpoint copies it again. A fix in one place silently misses three. |
| **Multi-child selector copy-pasted 4×** | `ParentDashboard.tsx:57`, `TimetablePage.tsx:20`, `RiskDashboard.tsx:226`, `FeesPage.tsx:531` | Same. Extract `useSelectedChild()` before adding a fifth. |
| **Cross-tenant leak in `/reference/lookup`** | [reference.py:83-95](backend/app/routers/reference.py#L83-L95) | Any authenticated user reads any school's full roster. Your parent portal calls this hook. |
| **`master_data.py` / `parents.py` / `students.py` / `teachers.py` have zero `school_id` scoping** | `GET /admin/schools`, all `_get_or_404` detail routes | Recurring bug class — three separate routers carry comments describing leaks they fixed. Assume every new admin endpoint needs it. |
| **`PATCH /admin/fees/records/{id}/mark-paid` is `require_role("teacher")` — admins are locked out** | [fees.py:381-385](backend/app/routers/fees.py#L381-L385) | Deliberate (teachers get a checkbox, admins get amount reconciliation) but genuinely surprising on an `/admin/`-prefixed path. If your parent portal shows "confirmed by", the two paths write different audit actions (`record_payment` vs `teacher_mark_fee_paid`). |
| **`Document.file_url` is a fabricated string, not a URL** | [documents.py:200-202](backend/app/routers/documents.py#L200-L202) | Anything that treats it as fetchable will 404. Uploaded images are **gone** after OCR. |
| **`RemarkStub` is a placeholder masquerading as a table** | [models/risk.py](backend/app/models/risk.py) | It has seeded rows and a sentiment service, so it looks real. It has **no endpoint**. Don't build the parent portal's "teacher remarks" on it without deciding it's the permanent model. |
| **Tests run against the live Supabase DB** | [conftest.py:15](backend/tests/conftest.py#L15) | A test that escapes the savepoint rollback writes real rows. Also: 7-minute suite, network-dependent. |
| **APScheduler writes real rows overnight** | [scheduler.py](backend/app/scheduler.py), `CLAUDE.md` | Leaving `uvicorn --reload` running past 02:00 UTC generates real `RiskFlag`/`AnomalyFlag`/`FeeRecord` rows. In-process, no lock — two replicas double-run. |
| **SSE stream has no reconnection** | [useAlerts.ts](frontend/src/api/hooks/useAlerts.ts) `catch { console.warn("Alert stream disconnected") }` | Copying this for notifications inherits a bell that silently dies on the first network blip. |
| **`queryClient.clear()` on logout** | [Layout.tsx:76](frontend/src/components/Layout.tsx#L76) | Query keys aren't user-scoped by design. Any cached notification state must survive this correctly. |
| **Hand-written API types, no codegen** | [api/types.ts](frontend/src/api/types.ts) | Backend shape changes fail silently at runtime, not at `tsc`. |
| **`npm run lint` is broken** | [package.json:9](frontend/package.json#L9) | Script references `eslint`, but there's no eslint config **and no eslint dependency**. Don't trust it as a gate. |
| **Committed test credential** | [gettoken.py:14](backend/gettoken.py#L14) | `EduOpsTest!2026` in version control. |
| **`.gitignore` lists `CLAUDE.md` and `.claude/` but `CLAUDE.md` is tracked** | [.gitignore](.gitignore) final lines | Stale rule; edits to `CLAUDE.md` still show in `git status`, confusing anyone who trusts the ignore file. |
| **Three copies of `daysAgo()` / `todayDow()`** | `ParentDashboard.tsx:15-23`, `StudentDashboard.tsx:11-19`, `PrincipalDashboard.tsx:15-19` | Trivial, but symptomatic — `lib/format.ts` exists and isn't being used for these. |
| **No `updated_at` on any table** | entire schema | "Mark notification as read" has no natural mutation timestamp unless you add one. |

### Three questions to ask your teammates

1. **What is the password for `test.parent@eduopsai.test`?** The seed script links it
   to two children specifically to exercise the multi-child selector
   ([seed_demo_data.py:167-181](backend/scripts/seed_demo_data.py#L167)), but the
   password appears nowhere in the repo — only `test.teacher@`'s does
   ([gettoken.py:14](backend/gettoken.py#L14)). Without it you cannot log in as a
   real multi-child parent, which is the single most important demo path in your scope.
   **Related:** which Supabase project sets `app_metadata.role` on signup, and how?
   `api-contract.md`'s own first open question is still unanswered: *"Where do custom
   `role` claims get set on the Supabase user?"*

2. **Is anyone building a gradebook, or do I cut academic performance from the parent
   portal?** No `gradebook_entries`, `assignments`, or `submissions` table exists, one
   person has committed everything, and `GET /parent/children/{id}/performance` is
   spec'd to return a `gradebook_summary`. Either I build a minimal gradebook myself
   (multi-day, outside my scope) or the parent portal ships as attendance + fees +
   risk only. **This changes my 14-day plan more than anything else in this audit.**

3. **Is cross-tenant scoping in scope for me, or accepted hackathon debt?**
   `GET /reference/lookup?school_id=N` returns any school's full student and teacher
   roster to any authenticated caller ([reference.py:83](backend/app/routers/reference.py#L83)),
   and `master_data.py` / `parents.py` / `students.py` / `teachers.py` have no
   `school_id` filtering at all — while three other routers carry comments describing
   the identical leak they already fixed. My parent portal builds directly on
   `/reference/lookup`. Do I fix it (touching four Person A routers), or ship on top
   of it and flag it?
