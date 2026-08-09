# API Contract

Shared endpoint spec for EduOps AI. **Agree here before implementing** — the frontend
owner should never be blocked waiting on a backend endpoint's shape.

## Conventions

- Base URL: `VITE_API_BASE_URL` (frontend) / served by FastAPI at `/` (backend). All
  routes below are relative to that base, e.g. `/auth/me`.
- Auth: `Authorization: Bearer <supabase_access_token>` on every protected route.
  Role is read from the token's `app_metadata.role` (or `user_metadata.role`) claim —
  one of `principal | admin | teacher | student | parent`.
- Request/response bodies: JSON, snake_case keys.
- Errors: FastAPI default `{ "detail": string | object }` shape with a matching HTTP
  status code (400 validation, 401 unauthenticated, 403 wrong role, 404 not found).
- Pagination (when needed): `?page=1&page_size=20`, response wraps list results as
  `{ "items": [...], "total": number, "page": number, "page_size": number }`.
- Every new endpoint gets added here (method, path, request, response, roles allowed)
  before it's implemented.

## Shared / Phase 0

| Method | Path        | Roles | Description                          |
| ------ | ----------- | ----- | ------------------------------------ |
| GET    | `/health`   | any   | Liveness check                       |
| GET    | `/auth/me`  | any authenticated | Current user's identity + role |

## Person A — AI/algorithm core + admin/ops backbone

_Owns: OCR ingestion, timetable optimization, attendance (CV/RFID), predictive
staffing, early-warning, admin command center, approvals/audit, fees, admissions,
exam seating._

<!-- Add endpoints below as they're agreed, e.g.:
| Method | Path | Roles | Description |
| ------ | ---- | ----- | ----------- |
| POST   | `/admin/timetable/generate` | admin, principal | Kick off timetable optimization run |
-->

## Person B — Classroom & academics

_Owns: assignments, quizzes, gradebook, report cards, library, homework calendar._

<!-- Add endpoints below as they're agreed -->

## Person C — Communication, RAG chatbots, parent portal, cross-cutting

_Owns: chat, notifications, announcements, multilingual, accessibility, offline
sync, search, the three RAG chatbots._

<!-- Add endpoints below as they're agreed -->

## Open questions

- [ ] Where do custom `role` claims get set on the Supabase user (raw_app_meta_data
      via admin API / DB trigger on signup)?
- [ ] Do we need a `staff` vs `student`/`parent` split beyond the 5 roles for
      finer-grained permissions later?
