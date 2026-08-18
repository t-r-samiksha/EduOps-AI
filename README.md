# EduOps AI

**An AI-first, unified school operations _and_ learning platform.**

Live link: https://eduops-ai-one.vercel.app

Video link: https://drive.google.com/file/d/1ILSkCM_AZziuY_I4qJKxsKnmOZflj101/view?usp=drivesdk

EduOps AI collapses the fragmented mix of manual data entry, physical document storage,
siloed scheduling and disconnected communication tools that schools rely on today into a
single, role-aware platform — where documents digitize themselves, timetables resolve
their own conflicts, attendance captures itself, classes live in dedicated online rooms,
and administrators are alerted to problems before they escalate.

Five roles — **Principal**, **Office Admin**, **Teacher**, **Student**, **Parent** — each
get a purpose-built dashboard over one shared data core.

> Design principle: **minimal clicks, maximum intelligence.** Every key action reachable in
> two clicks; every screen surfaces what matters without the user hunting for it.

---

## Table of Contents

- [Highlights](#highlights)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Repository Layout](#repository-layout)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [Database & Migrations](#database--migrations)
- [Testing](#testing)
- [Scheduled Jobs](#scheduled-jobs)
- [API Surface](#api-surface)
- [Roles & Access Control](#roles--access-control)
- [Deployment](#deployment)
- [Further Documentation](#further-documentation)

---

## Highlights

| Capability | What it does | Where it lives |
|---|---|---|
| **AI Document Processing** | Tesseract OCR pipeline extracts fields from scanned admission forms, TCs and fee receipts, then routes them into the right workflow — no manual entry. | [ocr_engine.py](backend/app/services/ocr_engine.py), [ocr_routing.py](backend/app/services/ocr_routing.py) |
| **Smart Timetable Generator** | Google OR-Tools CP-SAT constraint solver produces conflict-free, school-wide schedules, with a preflight feasibility check before solving. | [timetable_solver.py](backend/app/services/timetable_solver.py), [timetable_preflight.py](backend/app/services/timetable_preflight.py) |
| **Automated Attendance (CV)** | dlib / `face_recognition` 128-d face embeddings match a classroom photo against enrolled students, with separate confident-match and manual-review thresholds. | [attendance_cv.py](backend/app/services/attendance_cv.py) |
| **Early-Warning System** | Heuristic risk scorer blends attendance, gradebook trajectory and remark sentiment (VADER) into one tunable 0–1 risk signal; runs nightly. | [risk_scorer.py](backend/app/services/risk_scorer.py), [remark_sentiment.py](backend/app/services/remark_sentiment.py) |
| **Predictive Staffing & Smart Substitution** | Forecasts under/over-staffed days and auto-suggests a free, qualified substitute when a teacher requests leave. | [staffing_forecast.py](backend/app/services/staffing_forecast.py), [substitute_solver.py](backend/app/services/substitute_solver.py) |
| **RAG Chatbots (3)** | Student Doubt Bot, Teacher Assistant and Parent Assistant, grounded via pgvector search over class notes, library resources and teacher-verified doubt answers. | [llm.py](backend/app/services/llm.py), [retrieval.py](backend/app/services/retrieval.py), [bots.py](backend/app/routers/bots.py) |
| **Classroom Hub** | Per-class stream, assignments with submission tracking and auto-nudges, resource library, threaded doubts. | [classroom/](frontend/src/components/classroom/), [assignments/](frontend/src/components/assignments/) |
| **Academics Suite** | Gradebook, report cards, online exams with seating and invigilation duties, auto-graded quizzes, digital library, unified calendar. | [gradebook.py](backend/app/routers/gradebook.py), [exams.py](backend/app/routers/exams.py) |
| **Admin Command Center** | Proactive alert stream — attendance anomalies, pending approvals, fee backlogs, teacher overload — with live SSE updates. | [admin_alerts.py](backend/app/routers/admin_alerts.py), [alert_aggregator.py](backend/app/services/alert_aggregator.py) |
| **Anomaly Detection & Syllabus Pace** | Flags sudden attendance drops, document backlogs, low submission rates, and curriculum falling behind term progress. | [anomaly_detector.py](backend/app/services/anomaly_detector.py), [syllabus_pace.py](backend/app/services/syllabus_pace.py) |
| **Audit Log** | Every privileged action written to an immutable, queryable audit trail. | [audit_log.py](backend/app/services/audit_log.py), [audit.py](backend/app/routers/audit.py) |

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      PRESENTATION LAYER                       │
│  React 18 SPA · Vite · TypeScript · Tailwind + Radix UI       │
│  Role-based dashboards · Responsive · Accessible              │
│  State: TanStack Query (server) + Zustand (client)            │
└──────────────────────────────────────────────────────────────┘
                              │  REST (Bearer JWT)
┌──────────────────────────────────────────────────────────────┐
│                      APPLICATION LAYER                        │
│  FastAPI · Supabase JWT auth (ES256/JWKS) · RBAC & scoping    │
│  34 routers · Notification & announcement engine ·            │
│  Approval chains · Audit logging · APScheduler jobs           │
└──────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────┐
│                      INTELLIGENCE LAYER                       │
│  Tesseract OCR · dlib face recognition · OR-Tools CP-SAT ·    │
│  Predictive staffing · Heuristic risk scoring · VADER         │
│  sentiment · Gemini embeddings + generation (RAG)             │
└──────────────────────────────────────────────────────────────┘
                              │
┌──────────────────────────────────────────────────────────────┐
│                         DATA LAYER                            │
│  PostgreSQL (Supabase) · pgvector (KB embeddings, 1536-d)     │
│  SQLAlchemy 2.0 ORM · Alembic migrations · Supabase Storage   │
└──────────────────────────────────────────────────────────────┘
```

The intelligence services are deliberately **decoupled from the ORM** — the timetable solver,
CV pipeline, OCR engine and risk scorer each take plain dataclasses and return plain
dataclasses, so every one of them is runnable and testable without a database or a live camera.

---

## Tech Stack

**Backend** — Python 3.11 · FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · PostgreSQL +
pgvector · APScheduler · OR-Tools · OpenCV + dlib · pytesseract · scikit-learn ·
vaderSentiment · `google-genai` (Gemini) · python-jose

**Frontend** — React 18 · TypeScript 5 · Vite 5 · TanStack Query v5 · Zustand · React Router 6 ·
Tailwind CSS 3 · Radix UI · lucide-react · `@supabase/supabase-js`

**Platform** — Supabase (Postgres + Auth + Storage) · Docker · Vercel (frontend) ·
Render / Railway (backend)

---

## Repository Layout

```
eduopsai/
├─ backend/
│  ├─ app/
│  │  ├─ main.py            # FastAPI app: CORS, router registration, lifespan
│  │  ├─ database.py        # Engine, SessionLocal, get_db dependency
│  │  ├─ scheduler.py       # APScheduler wiring for the nightly/monthly jobs
│  │  ├─ models/            # 32 SQLAlchemy model modules
│  │  ├─ routers/           # 34 routers · ~212 endpoints
│  │  └─ services/          # Business logic + the whole intelligence layer
│  ├─ alembic/versions/     # 37 migrations
│  ├─ scripts/              # Seeders + the nightly/monthly job CLIs
│  ├─ tests/                # 66 pytest modules
│  └─ Dockerfile
├─ frontend/
│  └─ src/
│     ├─ api/               # fetch client, 33 typed query hooks, Supabase client
│     ├─ components/        # 65 feature components, grouped by module
│     ├─ routes/            # Per-role route trees (principal/admin/teacher/student/parent)
│     ├─ store/             # Zustand auth store
│     └─ App.tsx            # Role-guarded route table
└─ docs/
   ├─ spec/                 # Product doc & build playbook
   ├─ api-contract.md       # Full endpoint contract
   ├─ audit/                # Merge, seam & route-health audits
   └─ script/               # Demo run sheets
```

---

## Quick Start

### Prerequisites

- **Python 3.11** (see [.python-version](.python-version))
- **Node.js 18+**
- **PostgreSQL with the `pgvector` extension** — a Supabase project is the intended target.
  Migration `fd046d263fe1` runs `CREATE EXTENSION vector`, which plain `postgres` cannot
  satisfy; locally, use the `pgvector/pgvector:pg16` image.
- **Tesseract OCR** — a *system binary*, not a pip package. `pytesseract` is only a wrapper:
  - Windows: `winget install --id UB-Mannheim.TesseractOCR`
  - Debian / Ubuntu: `apt-get install tesseract-ocr`
  - If it isn't on `PATH`, set `TESSERACT_CMD` in `.env` to the full binary path.
- **A Google Gemini API key** — the RAG pipeline fails loudly at import without it.
  Get one at <https://aistudio.google.com/apikey>.

### 1. Backend

```bash
cd backend

python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

pip install -r requirements-dev.txt   # or requirements.txt for production only

cp .env.example .env                  # then fill in the values (see below)

python -m alembic upgrade head        # create / refresh the schema

uvicorn app.main:app --reload         # http://localhost:8000
```

Interactive API docs: <http://localhost:8000/docs> · Health probe: `GET /health`

### 2. Frontend

```bash
cd frontend
npm install
```

Create `frontend/.env`:

```
VITE_API_BASE_URL=http://localhost:8000
VITE_SUPABASE_URL=https://your-project-ref.supabase.co
VITE_SUPABASE_ANON_KEY=your-anon-key
```

```bash
npm run dev        # http://localhost:5173
```

Other scripts: `npm run build` (`tsc -b && vite build`) · `npm run preview` · `npm run lint`

### 3. Seed demo data

Every seeder is **idempotent** — each row is guarded by a natural key, so a re-run creates
nothing, and never updates or clobbers manual edits made during testing.

```bash
cd backend

python -m scripts.seed_demo_data --force            # schools, classes, rooms, subjects, staff
python -m scripts.seed_riverside_fixtures --force   # the Riverside demo school's operational data
python -m scripts.seed_person_b_riverside --force   # academics: classroom, assignments, gradebook, library

python -m scripts.wipe_seeded_data                  # roll it all back
```

Seeded users are direct DB inserts and **cannot log in themselves** — their `supabase_id` is a
deterministic UUID that satisfies the NOT NULL column but maps to no real Supabase Auth
identity. They exist so their IDs can be used in API calls made as an already-authenticated
user; [gettoken.py](backend/gettoken.py) mints a bearer token for a real account.

---

## Environment Variables

### `backend/.env`

| Variable | Required | Purpose |
|---|:---:|---|
| `DATABASE_URL` | ✅ | Postgres connection string (Supabase → Project Settings → Database → URI). *Session* pooler for local dev, *Transaction* for serverless. |
| `SUPABASE_URL` | ✅ | Used to fetch the project's JWKS for verifying ES256 auth JWTs — no shared secret needed. |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | Supabase Admin API calls (teacher account creation in the master-data endpoints). **Server-side only.** |
| `GEMINI_API_KEY` | ✅ | Embeddings and generation for the RAG pipeline and all three bots. |
| `CORS_ORIGINS` | — | Comma-separated allowlist. Defaults to `http://localhost:5173,http://localhost:3000`; any `*.vercel.app` origin is additionally allowed by regex. |
| `TESSERACT_CMD` | — | Full path to the Tesseract binary when it isn't on `PATH`. |
| `TEST_DATABASE_URL` | — | Separate database for the test suite. Unset by default — see [Testing](#testing). |
| `ENVIRONMENT` | — | `development` / `production`. |

### `frontend/.env`

| Variable | Required | Purpose |
|---|:---:|---|
| `VITE_API_BASE_URL` | — | Backend origin. Defaults to `http://localhost:8000`. |
| `VITE_SUPABASE_URL` | ✅ | Supabase project URL. |
| `VITE_SUPABASE_ANON_KEY` | ✅ | Supabase anon / publishable key. |

---

## Database & Migrations

37 Alembic migrations live in [backend/alembic/versions/](backend/alembic/versions/).
`alembic.ini` deliberately omits `sqlalchemy.url` — [alembic/env.py](backend/alembic/env.py)
reads `DATABASE_URL` from the environment instead, so migrations always target the same
database as the app.

```bash
cd backend
python -m alembic upgrade head                       # apply all
python -m alembic revision --autogenerate -m "msg"   # new migration
python -m alembic downgrade -1                       # roll back one
python -m alembic current                            # what's applied
```

> **pgvector caveat:** Alembic cannot reflect a pgvector HNSW index, so autogenerate sees an
> existing one as an orphan and proposes dropping it. Several migrations carry hand-written
> notes about this — read the docstrings before trusting an autogenerated diff that touches
> `kb_chunks`.

---

## Testing

66 pytest modules covering routers, services, solvers, the scheduler, and RBAC/scoping.

```bash
cd backend
venv/Scripts/python.exe -m pytest                        # full suite
venv/Scripts/python.exe -m pytest tests/test_risk_scorer.py -v
venv/Scripts/python.exe -m pytest --cov=app              # with coverage
```

> ⚠️ **The test suite shares the app's database by default.** `TEST_DATABASE_URL` is honoured
> if set, but nothing requires it. Consequences: sequences on real tables advance, and roughly
> one unreproducible failure per full run is expected rather than a bug. **Do not run the suite
> during a demo.** To separate them, point `TEST_DATABASE_URL` at another pgvector-capable
> Postgres and run `alembic upgrade head` against it — full instructions are in
> [backend/.env.example](backend/.env.example).

---

## Scheduled Jobs

Four jobs run automatically via APScheduler, started in the FastAPI lifespan
([app/scheduler.py](backend/app/scheduler.py)) whenever the backend process is up. Each wrapper
calls the *same* pure function its manual CLI uses — no duplicated business logic — and iterates
every `(school_id, academic_year)` pair that has at least one active class.

| Job | Cadence | Manual equivalent |
|---|---|---|
| Nightly risk scoring | nightly | `python -m scripts.run_nightly_risk_scoring --school-id N --academic-year YYYY-YY` |
| Syllabus / anomaly scan | nightly | `python -m scripts.run_nightly_syllabus_anomaly_scan --school-id N --academic-year YYYY-YY` |
| Admin briefing | nightly | `python -m scripts.run_nightly_admin_briefing` |
| Fee invoicing | monthly | `python -m scripts.run_monthly_fee_invoicing --school-id N` |

The manual CLIs keep working unchanged alongside the scheduler — the wiring is purely additive.

---

## API Surface

~212 endpoints across 34 routers. The full request/response contract is in
[docs/api-contract.md](docs/api-contract.md); live OpenAPI is at `/docs`.

Authentication is a Supabase-issued **ES256 JWT** sent as `Authorization: Bearer <token>`. The
backend verifies it against the project's published JWKS (cached for an hour, refreshed once on
an unknown `kid`) — there is no shared secret anywhere. A verified user is auto-provisioned into
the local `users` table on first request.

| Area | Representative endpoints |
|---|---|
| Auth | `/auth/me`, `/auth/signup` |
| Attendance | `/attendance/mark`, `/attendance/register`, `/attendance/enroll`, `/attendance/analytics` |
| Timetable | `/timetable/*` — preflight, generate, publish, swap |
| Classroom | `/classroom`, `/classroom/{id}/stream`, `/classroom/{id}/post` |
| Assignments | `/assignments`, `/assignments/{id}/submit`, `/assignments/{id}/grade/{sid}`, `/assignments/{id}/nudge-missing` |
| Academics | `/gradebook/*`, `/report-cards/*`, `/quizzes/*`, `/exams/*`, `/library/*`, `/calendar/*` |
| Operations | `/admin/alerts`, `/admin/approvals`, `/admin/admissions/*`, `/fees/*`, `/documents/*` |
| Intelligence | `/risk/*`, `/staffing/*`, `/syllabus/*`, `/analytics/student/{id}` |
| Bots | `/bots/student/ask`, `/bots/parent/ask`, `/bots/teacher/ask`, `/bots/insights/top-doubts`, `/bots/reindex` |
| Master data | `/admin/students`, `/admin/teachers`, `/admin/parents`, `/reference/*` |

`/admin/alerts/stream` is a Server-Sent Events endpoint powering the live command centre.

---

## Roles & Access Control

| Role | Purpose | Scope |
|---|---|---|
| **Principal / Super Admin** | Oversight & governance | Everything: analytics, staff management, approvals, audit logs |
| **Admin / Office Staff** | Day-to-day operations | Documents, fees, admissions, data-entry oversight |
| **Teacher** | Teaching & class management | Own timetable, classes, attendance, remarks, classroom hub, syllabus |
| **Student** | Self-service & learning | Own profile, attendance, remarks, timetable, classrooms, doubt bot |
| **Parent** | Monitoring their child | Child's attendance, remarks, performance, fees, alerts, messaging |

RBAC is enforced **at the API layer** — every endpoint checks role *and* ownership — and mirrored
in the UI by a role-guarded route table ([App.tsx](frontend/src/App.tsx),
[ProtectedRoute.tsx](frontend/src/components/ProtectedRoute.tsx)). The role itself comes from the
Supabase JWT's `app_metadata.role` claim.

Shared scoping helpers live in [services/scoping.py](backend/app/services/scoping.py) —
`assert_parent_linked` and friends guarantee a parent can only ever name one of their own linked
children. RAG access is guarded by `assert_student_class_access` in
[services/retrieval.py](backend/app/services/retrieval.py), placed in the service rather than a
router so no future retrieval path can skip it. Privileged actions are written to an immutable
audit log.

---

## Deployment

**Backend** — containerized via [backend/Dockerfile](backend/Dockerfile) (`python:3.11-slim` plus
`tesseract-ocr` and `libgomp1`, with prebuilt `dlib-bin` so nothing compiles from source):

```bash
cd backend
docker build -t eduops-api .
docker run -p 8000:8000 --env-file .env eduops-api
```

For Render / Railway-style hosts, [backend/build.sh](backend/build.sh) is the build command and
`uvicorn app.main:app --host 0.0.0.0 --port $PORT` the start command.

**Frontend** — Vercel. Both [vercel.json](vercel.json) and
[frontend/vercel.json](frontend/vercel.json) rewrite every path to `/index.html` for SPA routing.
Set the three `VITE_*` variables in the Vercel project, and add the deployed origin to
`CORS_ORIGINS` on the backend (any `*.vercel.app` origin is already permitted by regex).

---

## Further Documentation

| Document | Contents |
|---|---|
| [docs/spec/eduops-product-doc.md](docs/spec/eduops-product-doc.md) | Complete product documentation — vision, all modules, data model, full feature catalog |
| [docs/api-contract.md](docs/api-contract.md) | Endpoint-by-endpoint request/response contract |
| [docs/spec/person-b-playbook.md](docs/spec/person-b-playbook.md) | Academics-suite build playbook |
| [docs/audit/](docs/audit/) | Route-health sweep, seam analysis, known bugs, deferred work |
| [docs/script/](docs/script/) | Demo run sheets |
