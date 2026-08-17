# CLAUDE.md

This file gives Claude Code context on the EduOps AI project. Read this before making changes.

## Git policy — READ FIRST

**Never run `git commit` or `git push`, under any circumstances, even if asked indirectly (e.g. "wrap this up", "finish the task").**
- Stage and leave changes uncommitted so the team member can review `git diff` / `git status` themselves.
- If a task seems to require a commit to "complete" it, stop and say so instead of committing.
- Only commit or push if a human explicitly types the words "commit" or "push" in that exact message.

## Project overview

EduOps AI — an AI-first, role-aware school ERP + learning platform for the "Future-Ready Ops" hackathon (paperbuddy.in). Five roles: Principal, Admin, Teacher, Student, Parent. Unifies school operations (attendance, timetabling, staffing, admin workflows) with a learning layer (classroom, assignments, gradebook) and three RAG chatbots.

Team of 3, vertical domain ownership:
- **Person A** — AI/algorithm core + admin/ops backbone (OCR, timetable optimization, attendance CV/RFID, predictive staffing, early-warning, admin command center, approvals/audit/fees/admissions/exam seating)
- **Person B** — Classroom & academics (assignments, quizzes, gradebook, report cards, library, homework calendar)
- **Person C** — Communication, RAG chatbots, parent portal, cross-cutting (chat, notifications, announcements, multilingual, accessibility, offline sync, search)

## Tech stack

- **Frontend:** React, Tailwind, shadcn/ui, TanStack Query, Zustand
- **Backend:** FastAPI, PostgreSQL
- **AI/ML:** Tesseract (OCR), OpenCV (CV attendance), scikit-learn (predictive models), RAG stack for chatbots

## Repo structure (Phase 0 target)

```
/frontend          React app
  /src
    /routes         role-routed pages (principal/, admin/, teacher/, student/, parent/)
    /components      shared shadcn/tailwind components
    /store           zustand stores
    /api             TanStack Query hooks, API client
/backend            FastAPI app
  /app
    /models          SQLAlchemy models
    /routers         one router per domain (matches the 3-person split where possible)
    /services        business logic / AI pipelines
  /alembic           migrations
/docs
  api-contract.md    shared endpoint spec, agreed by all 3 before splitting off
```

## Conventions

- One router/service module per feature domain — keep Person A/B/C's code in separate files/folders so merges stay clean.
- All new endpoints go into `/docs/api-contract.md` before implementation, so the frontend owner isn't blocked.
- Use Alembic for every schema change — no manual DB edits.
- Env vars go in `.env.example` (never commit real `.env`).

## Commands

- Frontend dev: `npm run dev` (in `/frontend`)
- Backend dev: `uvicorn app.main:app --reload` (in `/backend`) — **this now starts a real
  APScheduler instance** (`backend/app/scheduler.py`, wired into the FastAPI lifespan)
  that runs 4 jobs automatically for every active school: nightly risk scoring (02:00
  UTC), nightly syllabus/anomaly scan (02:15 UTC), nightly admin briefing (02:30 UTC),
  nightly fee invoicing (02:45 UTC — changed from monthly this session: a monthly
  cadence meant a fee due mid-month could sit unmarked-overdue for weeks with no
  reminder logged; nightly closes that gap. `POST /admin/fees/schedules` also now
  triggers this immediately/synchronously for its own school+year on creation — but
  both this and the nightly job only actually generate a schedule's `FeeRecord`s
  once its `due_date` is within `AUTO_GENERATE_WINDOW_DAYS` (7,
  `scripts/run_monthly_fee_invoicing.py`) — a fee due 2 months out won't
  materialize records until it enters that window. `POST /admin/fees/schedules/
  {id}/generate` (per-schedule) and `POST /admin/fees/invoicing/run` (bulk) are the
  manual, ungated overrides for "generate this now regardless of due date").
  Leaving a dev server running past those times will produce real
  `RiskFlag`/`AnomalyFlag`/`FeeRecord` rows, not just when you manually run a script.
  The manual CLI scripts (`python -m scripts.run_nightly_risk_scoring --school-id ...
  --academic-year ...`, etc.) still work unchanged for on-demand/single-school runs.
- Backend deps: `pip install -r requirements.txt --break-system-packages` (or use a venv)
- **Always run backend tooling through the venv interpreter, not a bare command.**
  There is a venv at `backend/venv`, and the project's deps are installed only there.
  A bare `alembic ...` / `pytest ...` / `python ...` on this machine resolves to the
  global Python 3.14, which has no `pgvector` — every such command dies with
  `ModuleNotFoundError: No module named 'pgvector'` from `app/models/attendance.py`,
  which looks like a code error but is purely an interpreter-resolution problem.
  Use `backend/venv/Scripts/python.exe -m alembic <cmd>` (and `-m pytest`) instead.
  Ad-hoc one-off scripts that import `app.*` also need `PYTHONPATH=.` set from
  `/backend`, since only `alembic/env.py` and pytest add the app root to `sys.path`
  themselves: `PYTHONPATH=. backend/venv/Scripts/python.exe myscript.py`.
- **System dependency (not a pip package):** Document OCR (`backend/app/services/
  ocr_engine.py`) needs the actual Tesseract OCR engine binary installed separately -
  `pytesseract` is only a subprocess wrapper around it. Windows: `winget install
  --id UB-Mannheim.TesseractOCR` (installs to `C:\Program Files\Tesseract-OCR\
  tesseract.exe` by default, auto-detected; if it's elsewhere or not on PATH, set
  `TESSERACT_CMD` in `.env` to the full binary path). Linux/CI: `apt-get install
  tesseract-ocr` (Debian/Ubuntu) or your distro's equivalent. Without it,
  `POST /admin/ocr/documents` returns `503` rather than failing silently or crashing
  - see `ocr_engine.py::check_tesseract_available()`.
- Migrations: `alembic revision --autogenerate -m "message"` then `alembic upgrade head`
- Seed demo data: `python -m scripts.seed_demo_data` (in `/backend`, venv active) — populates
  a demo school/classes/subjects/teachers/students/rooms/timetable-solver-input so
  Timetable + Attendance endpoints have something real to hit instead of empty tables.
  Safe to re-run any time (checks for existing rows by natural key, never creates
  duplicates or updates rows it finds); prints ready-to-paste IDs for Postman when
  done. Does NOT create timetable_slots/attendance_records/face_embeddings - generate
  those for real by calling POST /timetable/generate and POST /attendance/enroll
  against the seeded base data. Add `--force` to skip its confirmation prompt when the
  DB already has non-trivial data.

## Out-of-turn endpoints

Person A's frontend session implemented two endpoints directly (code first, doc
written up after) instead of proposing them in `docs/api-contract.md` first, to avoid
blocking a real dashboard on cross-person coordination. Person B/C: check these before
building overlapping work, rather than diffing the whole api-contract.md file:

- **`GET /reference/lookup`** — id → name lookup across subjects/teachers/rooms/
  classes/students. Lives in api-contract.md's "Shared / Phase 0" section (genuinely
  cross-cutting, not any one person's domain).
- **`GET /parent/children`** — the calling parent's own linked children. Lives in
  Person C's "Parent portal" section. **Its real response shape (`id`/`name`/
  `class_id`/`class_name`) does not match Person C's original stub for the same path
  (`student_id`/`full_name`/`class_id`) — see that section for the full diff before
  building anything that assumes the stub's shape.**

## Current phase

**Phase 0 — Shared Foundation.** Scope for this phase:
1. Repo/monorepo scaffold (frontend + backend folders above)
2. PostgreSQL schema: users, roles, school, class, subject
3. RBAC/auth + role-based routing shell (5 dashboards, empty but routed)
4. Shared Tailwind/shadcn design tokens + layout shell
5. `/docs/api-contract.md` skeleton

Do not build Person A/B/C's individual features until Phase 0 is merged.

**Status as of 2026-08-09: Phase 0 looks functionally complete** (auth router/service,
5 routed dashboards, users/roles/school/class/subject/enrollment/parent_student models
all present on `main`) even though it was never formally marked merged. Person A's
Timetable Engine (models/solver/routes/tests) was started on top of it on this date.
If you're picking up Person B/C work and this note is still here, confirm with the
team whether Phase 0 is truly closed out before treating this as settled.