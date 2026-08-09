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
- Backend dev: `uvicorn app.main:app --reload` (in `/backend`)
- Backend deps: `pip install -r requirements.txt --break-system-packages` (or use a venv)
- Migrations: `alembic revision --autogenerate -m "message"` then `alembic upgrade head`

## Current phase

**Phase 0 — Shared Foundation.** All three team members are working in this repo together right now. Scope for this phase only:
1. Repo/monorepo scaffold (frontend + backend folders above)
2. PostgreSQL schema: users, roles, school, class, subject
3. RBAC/auth + role-based routing shell (5 dashboards, empty but routed)
4. Shared Tailwind/shadcn design tokens + layout shell
5. `/docs/api-contract.md` skeleton

Do not build Person A/B/C's individual features yet — that starts after Phase 0 is merged.