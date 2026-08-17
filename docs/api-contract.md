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

_Endpoints here are genuinely cross-cutting - not scoped to one person's domain.
See CLAUDE.md's "Out-of-turn endpoints" note for a one-line pointer to anything added
here outside the normal "agree in this doc first" flow._

| Method | Path        | Roles | Description                          |
| ------ | ----------- | ----- | ------------------------------------ |
| GET    | `/health`   | any   | Liveness check                       |
| GET    | `/auth/me`  | any authenticated | Current user's identity + role |
| POST   | `/auth/signup` | **public, no auth** | Real self-serve school + admin account signup |
| GET    | `/reference/lookup` | any authenticated | Id -> name lookup for subjects/teachers/rooms/classes |

#### `POST /auth/signup`
**Public/unauthenticated by design** - this is how a school's first admin account
gets created, so it can't itself require already being logged in. Creates, in order:
(1) a real, login-capable Supabase Auth account (`app_metadata.role="admin"`, via the
same `auth.admin.create_user` mechanism `POST /admin/teachers` uses), (2) a real
`School` row, (3) a local `User` row linking the two - then signs in immediately
server-side and returns a real `access_token` so the frontend never needs a separate
login step after signup.
- **Roles:** none (public)
- **Request:** `{ "full_name": "Asha Rao", "email": "asha@newschool.example", "password": "correct horse battery staple", "school_name": "Riverside Public School" }`
- **Response:**
```json
{ "access_token": "eyJ...", "user_id": 501, "school_id": 42, "email": "asha@newschool.example", "school_name": "Riverside Public School" }
```
- **Errors:** `400` empty `full_name`/`school_name` or `password` under 8 characters;
  `409` email already registered (checked locally first, then propagated if Supabase
  Auth itself already has the email even with no local row yet); `500` if the real
  Supabase Auth account was created but the local `School`/`User` creation then failed
  - the local half of the operation is rolled back cleanly in that case (no orphaned
    `School`/`User` row), but the external Supabase Auth account itself can't be
    un-created by our own DB transaction - the same accepted edge case documented on
    `POST /admin/teachers`.
- **No rate-limiting exists yet** for this genuinely public endpoint (no
  slowapi/API-gateway layer in this repo) - a real, honestly-flagged gap. Every
  attempt (success or failure) is logged via a dedicated `eduops.signup` logger so
  abuse is at least visible after the fact.

#### `GET /reference/lookup`
**Not in the original Phase 0 stub - added out-of-turn during Person A's frontend
session**, i.e. implemented directly rather than proposed here first, then written up
after the fact. Phase 0 built the users/school/class/subject schema but never exposed
a way to resolve their ids to display names, and every Person A endpoint (timetable
slots, attendance matches, ...) only carries `subject_id`/`teacher_id`/`room_id`/
`class_id` per this doc - a frontend has no way to show "Math" instead of "Subject #3"
without this. Deliberately homed here rather than under Person A: it resolves ids
across subjects/teachers/rooms/classes/students, i.e. every domain's entities at once,
so it doesn't belong to any single person's section. Read-only, not role-gated beyond
authentication (these entities carry no sensitive data themselves).

**Enriched for the timetable generation form (Stage 2 of the generation overhaul)**:
`teachers[]`/`rooms[]`/`classes[]` gained extra fields below so the frontend can build
a real teacher/room picker without a dedicated CRUD endpoint (still none - see
CLAUDE.md's scope note on `TeacherProfile`/`TeacherSubject`/`Room` staying seed-script-
managed). Additive only, existing consumers reading just `id`/`name` are unaffected.
- **Roles:** any authenticated
- **Query:** `?school_id=` (required)
- **Response:**
```json
{
  "subjects": [ { "id": 3, "name": "Math", "periods_per_week": 4, "lab_required": false } ],
  "teachers": [
    { "id": 7, "name": "Demo Teacher 1", "max_periods_per_week": 24, "subject_ids": [3, 5] }
  ],
  "students": [ { "id": 103, "name": "Demo Student Class 8A #01" } ],
  "rooms": [ { "id": 1, "name": "Room 12", "room_type": "classroom" } ],
  "classes": [ { "id": 41, "name": "Class 8A", "grade_level": 8, "grade_label": null, "section": "A", "class_teacher_id": 7 } ]
}
```
- `subjects[].periods_per_week`/`lab_required`: real, persisted `Subject` master-data
  defaults (School Management's Subjects tab - new this session, `Subject` previously
  had neither field). `POST /timetable/generate`'s per-run `subjects[].periods_per_week`/
  `lab_required` still exist and still win for that one run (a genuine one-off override,
  e.g. an exam-term schedule needing different periods), but the frontend now
  pre-fills them from these real defaults instead of an arbitrary hardcoded value
  every time.
- `teachers[].max_periods_per_week`: this teacher's stored `TeacherProfile` cap, or
  `null` if they somehow have no profile row (shouldn't happen for seeded teachers).
- `teachers[].subject_ids`: this teacher's real `TeacherSubject` qualifications.
- `rooms[].room_type`: `"classroom"` or `"lab"` (matches `POST /timetable/generate`'s
  `subjects[].lab_required` -> `_LAB_ROOM_TYPE` mapping).
- `classes[].grade_level`/`section`: `null` only for a class whose name the migration's
  backfill regex couldn't parse (none in seeded demo data).
- `classes[].grade_label`: cosmetic display label for `grade_level`, e.g. `"LKG"` for
  `grade_level=-2` - see `SchoolClass.grade_label`'s docstring for the full
  Nursery=-3/LKG=-2/UKG=-1/Grade N=N convention. `null` for a plain numeric grade
  (e.g. Grade 8) - display code should fall back to `f"Grade {grade_level}"` in that
  case, never render `grade_level` directly (`"Grade -2"` is never correct).
- `classes[].class_teacher_id`: added this session - lets a teacher viewing this same
  non-role-gated lookup identify which class(es), if any, they're the class teacher
  of (e.g. `admin/fees` Fees page's teacher view) without needing the admin-only
  `GET /admin/classes`. `null` for a class with none assigned.

**Updated for real master-data CRUD (see Person A's "Master Data Management" section
below)**: every list here (`subjects`/`teachers`/`rooms`/`classes`) now excludes
deactivated rows by default (`is_active = false`) - this is what makes deactivating a
teacher/room/subject/class actually stop it from being offered anywhere real input is
collected, not just flip a column nothing reads.

## Person A — AI/algorithm core + admin/ops backbone

_Owns: OCR ingestion, timetable optimization, attendance (CV/RFID), predictive
staffing, early-warning, admin command center, approvals/audit, fees, admissions,
exam seating._

This section is Person A's to extend — add/adjust endpoints here without touching
Person B/C's sections below.

### Master Data Management (School / Class / Subject / Room / Teacher)

**New this session - closes the biggest gap found by a full reliability audit**:
every Person A feature that references a `school_id`/`class_id`/`subject_id`/
`room_id`/`teacher_id` previously assumed the row already existed via
`backend/scripts/seed_demo_data.py`, with zero real endpoint for an admin to create
one. `CLAUDE.md`'s prior scope note ("seed-script-managed, no CRUD API, by explicit
user decision") is superseded by this session's explicit build request. A real
school can now be onboarded from a literal empty database using only these
endpoints (see CHECKPOINT 1's empirical proof in this session's own report).

**Soft-delete only** - every entity has `is_active`, never a hard DELETE.
`GET` list endpoints default to active-only rows; pass `?include_inactive=true` to
see everything. Deactivating actually removes an entity from `GET /reference/lookup`
and from being a valid id for `POST /timetable/generate` (400, not silently ignored).

**Roles:** admin/principal only for every mutation below (create/update/deactivate/
reactivate/add/remove). `School` creation has no additional ownership check beyond
the role itself - any admin/principal can create a new school, which is what makes
cold-start bootstrapping possible (there's no existing school to check against yet).

- `backend/app/routers/master_data.py`: School, SchoolClass, Subject, Room -
  straightforward CRUD, each following the same shape:
  - `POST /admin/schools` | `/admin/classes` | `/admin/subjects` | `/admin/rooms`
  - `GET /admin/schools` | `/admin/classes?school_id=` | `/admin/subjects?school_id=`
    | `/admin/rooms?school_id=` (all accept `?include_inactive=true`)
  - `GET .../{id}`, `PUT .../{id}` (partial update, only sent fields change)
  - `PUT .../{id}/deactivate`, `PUT .../{id}/reactivate`
  - `Subject` gained real `periods_per_week` (default `3`) and `lab_required`
    (default `false`) columns this session (School Management page build) - real,
    persisted master-data defaults, settable via `POST`/`PUT /admin/subjects`.
    `POST /timetable/generate`'s per-run `subjects[]` override still exists and
    still wins for that one run; the frontend now pre-fills from these instead
    of a hardcoded value every time (see `GET /reference/lookup`'s own note).
  - Every foreign key in a request body (`school_id`, `class_teacher_id`) is
    validated with a clean `400 Unknown <field> <id>` before any write - never an
    unhandled `IntegrityError`/500 (a gap this session's audit found and fixed here
    and in three other pre-existing endpoints, see the "FK validation fixes" note
    at the end of this section).
  - `SchoolClass` gained `home_room_id` (nullable FK to `Room`) this session (the
    timetable solver's room-pinning fix - see "Timetable optimization" below for
    why). Settable via `POST`/`PUT /admin/classes`; unknown room id is a `400`, and
    a room already claimed as another ACTIVE class's home room is also a `400`
    (deactivating that other class frees the room for reuse) - two classes sharing
    one home room would otherwise silently double-book it every non-lab period.
  - `class_teacher_id` is **required** on `POST /admin/classes` (was optional) -
    every class must have a class teacher, a school-policy decision, not a schema
    one: the DB column itself stays nullable (existing classes created before this
    requirement may still have none), but creating a NEW class without one is now
    a `422`. `PUT /admin/classes/{id}` still can't be used to un-assign one once
    set (unchanged - `class_teacher_id` in the update body only ever sets, never
    clears). The real enforcement teeth are in `POST /timetable/generate` (Check G,
    below) - a class missing a class teacher blocks generation, not just class
    creation.

- `backend/app/routers/teachers.py`: Teacher is a compound entity - a real,
  login-capable Supabase Auth account (via `services/supabase_admin.py`'s
  `auth.admin.create_user`, the SAME real mechanism used ad-hoc for `admin@sam.in`/
  `test.*@eduopsai.test` in earlier sessions, now wired into a real endpoint instead
  of a one-off script) + the local `users` row + `TeacherProfile` + `TeacherSubject`
  qualifications + `TeacherUnavailability`.
  - `POST /admin/teachers` - body: `{ school_id, email, password, full_name?,
    max_periods_per_week?, subject_ids: [...], unavailability: [{day_of_week,
    period_number, academic_year}] }`. `subject_ids`/`unavailability` are a
    cold-start convenience - creates a REAL Supabase Auth account, `409` if the
    email is already registered (locally or in Supabase Auth itself), `502` for any
    other Supabase-side failure. `school_id`/`subject_ids` are validated locally
    BEFORE the external Supabase call, so a bad request never creates an orphaned
    auth account.
  - `GET /admin/teachers?school_id=` (`?include_inactive=true`), `GET .../{id}`
  - `PUT /admin/teachers/{id}` - scalar fields only (`full_name`,
    `max_periods_per_week`)
  - `PUT .../{id}/deactivate`, `PUT .../{id}/reactivate`
  - `POST .../{id}/subjects?subject_id=` / `DELETE .../{id}/subjects/{subject_id}` -
    **idempotent add/remove of ONE qualification** - adding a teacher's 4th subject
    never requires resending the other 3. This is what makes "add to a school that
    already has some real data" actually work, not just cold-start.
  - `POST .../{id}/unavailability` (body: `{day_of_week, period_number,
    academic_year}`) / `DELETE .../{id}/unavailability/{unavailability_id}` - same
    idempotent add/remove pattern.

**FK validation fixes (same session)**: the audit also found 4 pre-existing
endpoints where one sibling FK field was validated but another wasn't, risking an
unhandled `IntegrityError`/500 on a bad id - all fixed to return a clean `400`/`404`:
`POST /admin/fees/schedules` (`school_id`), `POST /admin/exams` (`school_id`),
`POST /staff/request_leave` (`teacher_id` when an admin/principal files on another
teacher's behalf), `PUT /timetable/update` (`teacher_id`/`room_id`/`subject_id`
overrides).

### Document OCR

Backed by Tesseract via `pytesseract` (`backend/app/services/ocr_engine.py`) +
regex-based per-`document_type` field extraction (`backend/app/services/
ocr_postprocess.py`, honest at this scale per the playbook - not an NLP/NER
pipeline). **System dependency, not just a pip package:** the actual Tesseract OCR
engine must be installed separately (`winget install --id UB-Mannheim.TesseractOCR`
on Windows, `apt-get install tesseract-ocr` on Linux/CI) - `pip install pytesseract`
alone only gets you the subprocess wrapper. See `ocr_engine.py`'s docstring and
CLAUDE.md's Commands section.

**Processing is synchronous**, same precedent as `/timetable/generate`: OCR +
extraction run inside the `POST` request itself, so the response reflects the real
final `status` (`done`/`failed`), not `queued` as an earlier draft of this doc showed
- there's no polling step because there's no async gap to poll across. Routing
extracted entities into other tables ("Async task... to auto-route extracted entities
to relevant tables" per the playbook) is likewise a plain synchronous function
(`backend/app/services/ocr_routing.py`) shaped so it could be handed to a real task
queue later - no Celery/Dramatiq/Huey/APScheduler exists anywhere in this repo yet
(checked before building this, same finding as Staffing/Early-Warning's scheduler
checks).

**Which document_types route for real vs. stay extraction-only - checked before
building, read before assuming otherwise:** `backend/app/models/` has no admissions/
applications table (Task Group 9, not started) and no grades table (Person B's
gradebook, not started, same finding as Early-Warning's grades caveat). **Every
document_type is therefore extraction-only today** - `admission_form`, `marksheet`,
and `id_proof` all OCR and structure-extract for real, persisted as real
`ExtractedEntity` rows, but nothing currently auto-routes anywhere beyond this
feature's own tables. Every `GET`/`reextract` response's `routing` field makes this
explicit per-document rather than silently omitting it. Wire a real handler into
`ocr_routing.ROUTING_TARGETS` once a target table exists - no other code changes.

**`school_id` is REQUIRED on every endpoint below (a reliability-audit fix)**:
`Document` originally had zero tenant scoping at all - `GET /admin/ocr/documents`
returned every school's documents to any admin/principal, confirmed by an
empirical test (two fresh schools, Admin A's list included Admin B's document).
Every endpoint below now takes `school_id` and 404s (not 403, to avoid confirming
a cross-tenant document's existence) on any id that doesn't belong to it -
`GET`/`PUT .../entities/{id}`/`POST .../reextract` alike, not just the two
originally flagged ("list/detail") - a correction/re-extract call on another
school's `document_id` is the same leak shape and was fixed in the same pass.
A small number of pre-existing rows predate this column and have `school_id:
null` (their uploader's own account had no `school_id` set either - see
`services/auth.py`); these are simply never reachable through the API now
(not deleted, not exposed to the wrong tenant, just permanently unmatched by
any real `school_id` filter) - see the migration's own docstring for why no
backfill was attempted.

#### `POST /admin/ocr/documents`
Upload a document (marksheet, admission form, ID proof, ...) for OCR processing.
- **Roles:** admin, principal
- **Request:** `multipart/form-data` — `file` (binary) + form fields `document_type` (`"marksheet" | "admission_form" | "id_proof" | "other"`) + `school_id`
- **Response:**
```json
{ "id": 1, "school_id": 41, "document_type": "admission_form", "status": "done", "uploaded_at": "2026-08-11T10:00:00Z" }
```
- **Errors:** `400` invalid `document_type` or unknown `school_id`; `422` undecodable image; `503` Tesseract binary unavailable on the server.

#### `GET /admin/ocr/documents`
**Not in the original stub - added because the frontend's document review screen
had no real way to browse previously-uploaded documents, only fetch one by a known
id (below). Previously worked around with a client-side session history of ids;
that workaround is now removed in favor of this real endpoint.** Summary shape
only (no `extracted_fields`/`entities`/`raw_text`) - that detail stays on the
single-document `GET`, same split as `GET /admin/admissions/applications` vs a
single application's full record.
- **Roles:** admin, principal
- **Query:** `?school_id=` (required) `&status=&document_type=&page=&page_size=` (`page_size` defaults to 20)
- **Response:**
```json
{
  "items": [ { "id": 1, "school_id": 41, "document_type": "admission_form", "status": "done", "uploaded_at": "2026-08-11T10:00:00Z", "processed_at": "2026-08-11T10:00:01Z", "application_id": 575, "application_applicant_name": "Priya Sharma" } ],
  "total": 1, "page": 1, "page_size": 20
}
```
`application_id` is `null` until this document is linked into some
`AdmissionApplication.ocr_document_ids` (via that document's own routing pre-fill, or
via `POST /admin/admissions/applications/{id}/documents`) - lets the document list
group/nest documents by the application they already belong to without a detail
fetch per row. `application_applicant_name` is the linked application's own real
`applicant_name` (null exactly when `application_id` is null) - not derived from
this document's own extracted fields, since a marksheet's `student_name` and an
id_proof's `full_name` aren't guaranteed to match the application's canonical name
verbatim; the board always shows the one real name off the application itself.

#### `GET /admin/ocr/documents/{id}`
Fetch OCR processing status/result for a previously uploaded document.
- **Roles:** admin, principal
- **Query:** `?school_id=` (required)
- **Response:**
```json
{
  "id": 1,
  "school_id": 41,
  "document_type": "admission_form",
  "status": "done",
  "uploaded_at": "2026-08-11T10:00:00Z",
  "processed_at": "2026-08-11T10:00:01Z",
  "extracted_fields": { "applicant_name": "Priya Sharma", "dob": "2015-04-01", "gender": "Female", "grade_applied": "6", "guardian_name": "Rajesh Sharma", "guardian_email": "rajesh@example.com", "guardian_phone": "9876543210" },
  "entities": [
    { "id": 5, "field_name": "applicant_name", "field_value": "Priya Sharma", "confidence_score": 0.96, "is_low_confidence": false, "corrected_value": null, "corrected_by": null, "corrected_at": null }
  ],
  "expected_fields": ["applicant_name", "dob", "gender", "grade_applied", "guardian_name", "guardian_email", "guardian_phone"],
  "application_id": null,
  "application_applicant_name": null,
  "raw_text": "Applicant Name: Priya Sharma\nDate of Birth: 01.04.2015\n...",
  "ocr_confidence": 0.96,
  "routing": {
    "routed": true,
    "target_table": "admission_applications",
    "reason": "Ready to pre-fill a new admission application from this document's extracted fields.",
    "suggested_payload": { "applicant_name": "Priya Sharma", "dob": "2015-04-01", "guardian_email": "rajesh@example.com", "guardian_name": "Rajesh Sharma", "guardian_phone": "9876543210", "grade_applied": "6", "school_id": 41, "ocr_document_ids": [1] }
  },
  "error": null
}
```
`suggested_payload`'s `guardian_name`/`guardian_phone` are only present when OCR
actually found them (they're NOT in the required-to-route field set, so a form
missing them still routes) - when present, they flow through to the real
`POST /admin/admissions/applications` submission and become the real guardian
account's `full_name` once accepted (see that endpoint's own note on this).
`extracted_fields` uses each field's `corrected_value` where a manual correction
exists, else its OCR `field_value` - `entities` carries the full per-field detail
(confidence, correction state, entity `id` to `PUT` against) the flat dict can't.

`expected_fields` is every field this `document_type`'s extraction rules look for
(`services/ocr_postprocess.py::EXTRACTION_RULES`), regardless of whether OCR actually
found each one on THIS document - a field can genuinely go missing (not merely
low-confidence) when OCR garbles the source line badly enough that the regex never
matches at all (found live: a real marksheet's "Total Marks:" line came back as
"otal Mark:", so no entity was ever created for `total_marks`). Diffing
`expected_fields` against `extracted_fields`'s keys tells a caller which fields have
no value AT ALL, as distinct from a low-confidence one - see
`POST .../entities` below for how to fill one in.

`application_id` - see `GET /admin/ocr/documents`'s own note above; same meaning here.

`dob` is extracted from any of ISO (`YYYY-MM-DD`) or common `DD.MM.YYYY`/`DD/MM/YYYY`/
`DD-MM-YYYY` forms and always normalized to ISO before storage - real forms are filled
in by office staff/parents in whatever format they're used to, not necessarily ISO
(found live: a real uploaded form wrote "12.04.2015", which the original ISO-only
extractor silently failed to match at all).

`routing` reflects `services/ocr_routing.py`'s real (not stubbed) `admission_form`
handler: once `applicant_name`/`dob`/`guardian_email`/`grade_applied` are ALL
extracted (or corrected), `routed` is `true` and `suggested_payload` is a ready-to-
review `POST /admin/admissions/applications` body (see that endpoint below) -
`school_id`/`ocr_document_ids` come from this Document row, `academic_year` is left
for a human to supply (never printed on the physical form). This is a PRE-FILL, never
silent auto-creation - the frontend surfaces it as a "Create application from this
document" action that still lands on the real endpoint for review/submit. When any
required field is missing, `routed` stays `false` and `suggested_payload` is `null`,
same as `marksheet`/`id_proof`/`other`, which remain honest stubs (no grades table or
generic document-subject linkage exists yet).
- **Errors:** `404` unknown document id, OR a real document id belonging to a different `school_id`.

#### `PUT /admin/ocr/documents/{id}/entities/{entity_id}`
Manual correction of an extracted field (the "manual data fix" half of the playbook's
manual-fix-+-re-extract flow) - sets `corrected_value`/`corrected_by`/`corrected_at`
without touching the original OCR `field_value`.
- **Roles:** admin, principal
- **Query:** `?school_id=` (required)
- **Request:** `{ "corrected_value": "Priya A. Sharma" }`
- **Response:** the updated entity, same shape as a `GET` response's `entities[]` item.
- **Errors:** `400` empty `corrected_value`; `404` unknown document/entity id, entity belongs to a different document, or the document belongs to a different `school_id`.

#### `POST /admin/ocr/documents/{id}/entities`
Manually supply a value for a field OCR never found at all - genuinely different
from `PUT .../entities/{entity_id}` above, which corrects an EXISTING (if wrong or
low-confidence) entity. When OCR garbles a line badly enough that the field's regex
never matches, no entity is ever created for it - there's no `entity_id` to `PUT`
to, so this creates one instead. Human-entered, so trusted outright:
`confidence_score: 1.0`, `is_low_confidence: false`, no `corrected_value` (nothing
to correct - this value IS the record).
- **Roles:** admin, principal
- **Query:** `?school_id=` (required)
- **Request:** `{ "field_name": "total_marks", "value": "450" }`
- **Response:** the full updated document detail, same shape as `GET /admin/ocr/documents/{id}`.
- **Errors:** `400` empty `field_name`/`value`, or `field_name` isn't one of this
  document's `expected_fields`; `409` this `field_name` already has a value on this
  document - use `PUT .../entities/{entity_id}` to correct it instead; `404` unknown
  document id, or the document belongs to a different `school_id`.

#### `POST /admin/ocr/documents/{id}/reextract`
Re-run postprocessing against the document's already-stored `raw_text` (no
re-upload) - the "re-extract" half of the manual-fix flow, e.g. after realizing a
document was mis-classified. Per-field confidence is recomputed from persisted
word-level OCR data, not just re-copied from the overall score. **Replaces** the
document's existing entities (and therefore any corrections made against them) -
old field names may not even apply if `document_type` changed.
- **Roles:** admin, principal
- **Query:** `?school_id=` (required)
- **Request:** `{ "document_type": "marksheet" }` (optional - omit to retry with the existing `document_type`)
- **Response:** same shape as `GET /admin/ocr/documents/{id}`.
- **Errors:** `404` unknown document id, OR a real document id belonging to a different `school_id`.
- **Errors:** `400` invalid `document_type`, or no OCR result exists yet for this document; `404` unknown document id.

### Timetable optimization

Backed by a CP-SAT (OR-Tools) constraint solver — hard constraints: no teacher, room,
or class double-booked in the same period, plus (as of this revision) a per-teacher
weekly load cap. `day_of_week` is 0-indexed (0 = Monday); `period_number` is 0-indexed
within the day. Generation is synchronous (no run_id/polling) - small enough inputs
solve in well under the request timeout.

**Request shape overhaul — read before assuming the original stub's shape still
applies.** `POST /timetable/generate` no longer reads `ClassSubjectRequirement` or
`SubjectRoomRequirement` at all (both tables still exist in the schema and are
unused going forward, not dropped). Every previous run's premise — that an admin
pre-seeds those rows out-of-band, then generation just consumes whatever's already
there — didn't match what a real generation flow needs: an admin specifying, per
run, which grade levels/sections, which subjects need how many periods/week and
whether they need a lab, which teachers are available/qualified for what (with a
per-run enable/disable + load-cap override), and which rooms are usable. The new
request captures all of that directly; nothing from it is persisted back into
those tables — every override is scoped to the one run that submitted it. Two new
pieces of master data back this, both seed-script-managed like everything else in
this section (see CLAUDE.md's Commands section on `seed_demo_data.py` — **no CRUD
API or admin UI exists for either, on purpose**, same "use the seed-script
pattern" scope decision as `TeacherSubject`/`TeacherUnavailability`/`Room`/
`Subject` already were):
- `TeacherProfile` (`backend/app/models/timetable.py`) — one row per teacher,
  currently just `max_periods_per_week` (weekly teaching-load cap, default 30 for
  seeded demo teachers). A generation run's `teacher_selections[]` can override
  this default for that run only.
- `SchoolClass` gained `grade_level`/`section` columns (previously just a free-form
  `name` like `"Class 8A"`) so `grade_levels[]`/`sections_per_grade` below can
  resolve to real rows. Existing seeded classes were backfilled via migration
  (`"Class 8A"` → `grade_level=8, section="A"`). **`grade_levels[]`/
  `sections_per_grade` only ever SELECT existing `SchoolClass` rows — a grade with
  fewer seeded sections than requested is a `400` naming exactly which grade(s)
  are short, never silently auto-created.** Creating new class sections is real
  class-management functionality, deliberately out of scope here (same "don't
  build CRUD nobody asked for" boundary as teacher/room/subject master data).

**Solver quality fixes (this revision) — surfaced by inspecting an actual generated
schedule, not theoretical:**
1. **Homeroom pinning.** `SchoolClass` gained `home_room_id` (nullable FK to `Room`,
   settable via `POST`/`PUT /admin/classes` — see "Master Data Management" above; two
   active classes may never share one, rejected with a `400` before it ever reaches
   the solver). Every period of a NON-lab-required subject for a class is now hard-
   pinned to that class's `home_room_id`, instead of freely choosing among every
   room passed in `room_ids[]` (which is how a class ended up bounced between
   different classrooms and even auditoriums across a single day for no subject-
   level reason). Lab-required subjects are unaffected — they still freely choose
   among `room_type="lab"` rooms, same as before. A class with no `home_room_id`
   configured falls back to the old free-choice behavior for its own periods only,
   and the response's new `warnings[]` names exactly which class(es) need one
   configured — this never fails the request, it's a signal, not a hard block.
2. **Same-subject-per-day spread.** A class-subject pair is now hard-capped at
   `ceil(periods_per_week / days_per_week)` occurrences per day — 1/day in the
   overwhelming common case (`periods_per_week <= days_per_week`), only rising above
   1 when the numbers genuinely force it (e.g. 8 periods/week on a 5-day week forces
   at least 3 days to carry 2). On top of that hard cap, the solver *minimizes* how
   much of the cap actually gets used (a heavily-weighted `same_day_clustering`
   objective term) so clustering happens on exactly the minimum number of days the
   math requires, never more. A lighter-weighted `day_variance` objective term
   additionally smooths out uneven day-to-day totals (e.g. "6 periods Monday, 0
   Friday") wherever the hard constraints leave room to. Both terms' weights and
   actual achieved values are returned in every response (see below) so they can be
   tuned later without reading the solver's source.
- **Reproducibility:** `random_seed` is now fixed in the solver, but
  `num_search_workers=8` runs several CP-SAT search strategies in parallel and
  returns whichever proves/finds a solution first — that race is real wall-clock-
  timing-dependent, so a fixed seed alone does not guarantee bit-for-bit identical
  output run-to-run at this parallelism. Only `num_search_workers=1` gives true
  determinism (at a real solve-time cost on larger inputs).

#### `POST /timetable/generate`
Run the solver for a school/academic year and persist the result. Deactivates
(`is_active=false`) any previous active slots for the resolved class(es)/
academic_year before inserting the new ones - a superseding run, not additive.
- **Roles:** admin, principal
- **Request:**
```json
{
  "school_id": 41,
  "academic_year": "2026-27",
  "grade_levels": [8],
  "sections_per_grade": 2,
  "periods_per_day": 6,
  "days_per_week": 5,
  "subjects": [
    { "subject_id": 40, "periods_per_week": 4, "lab_required": false },
    { "subject_id": 41, "periods_per_week": 3, "lab_required": true }
  ],
  "teacher_selections": [
    { "teacher_id": 97, "included": true, "max_periods_per_week_override": null },
    { "teacher_id": 98, "included": false }
  ],
  "room_ids": [64, 65]
}
```
- `grade_levels`/`sections_per_grade`: resolved against existing `SchoolClass` rows
  only, per the overhaul note above. Accepts negative values for pre-Grade-1 levels
  (Nursery=-3, LKG=-2, UKG=-1, per `SchoolClass.grade_level`'s documented convention)
  - `grade_levels[]` has no special-cased range, `[-2]` resolves/generates exactly
  like `[8]` (verified empirically, not just by code-read).
- `subjects[]`: `periods_per_week` and `lab_required` apply to every resolved class
  for this run (not persisted — see overhaul note); `lab_required: true` requires a
  room with `room_type="lab"` among `room_ids[]`, same room-type matching the
  solver always did, just sourced from the request now instead of
  `SubjectRoomRequirement`.
- `teacher_selections[]`: `included: false` **excludes** that teacher from solver
  input entirely for this run (not passed in with an empty qualification set) - a
  generation that would've needed them fails honestly (`422`), it never silently
  falls back to using them anyway. `max_periods_per_week_override` omitted/`null`
  = use that teacher's stored `TeacherProfile.max_periods_per_week`; a teacher
  with neither an override nor a stored profile row gets `days_per_week ×
  periods_per_day` (i.e. effectively uncapped) rather than an arbitrary number.
  Teacher qualification (which subjects) still comes from real `TeacherSubject`
  rows - `teacher_selections[]` doesn't grant qualifications, only opts a real
  qualified-or-not teacher in/out of this run and optionally overrides their cap.
- `room_ids[]`: only these rooms are usable for this run; must be real rooms
  belonging to `school_id`.
- **All of the above are also rejected if deactivated** (`400 Unknown or inactive
  <field>_id(s)`): a deactivated `SchoolClass`/`Subject`/`Room`/teacher `User` (see
  the new "Master Data Management" section above) can no longer be resolved or
  passed into a generation run, the same way an unknown id can't.
- **Response:**
```json
{
  "academic_year": "2026-27",
  "slots_created": 14,
  "slots": [ { "id": 101, "day_of_week": 0, "period_number": 0, "start_time": "08:00:00", "end_time": "08:45:00", "subject_id": 3, "teacher_id": 7, "class_id": 2, "room_id": 1, "academic_year": "2026-27", "is_active": true } ],
  "warnings": [ "Class 2 has no home_room_id configured - its non-lab periods may be assigned to different rooms across the week. Set a home room for it in School Management's Classes tab to pin it." ],
  "findings": [ { "severity": "warning", "code": "TEACHER_POOL_TIGHT", "subject": "english", "message": "english's teacher pool is at 34/36 (94%) capacity - technically feasible but likely to cause a slow solve or a late failure once combined with other constraints.", "numbers": { "demand": 34, "capacity": 36 }, "remedies": [], "details": null } ],
  "objective_weights": { "same_day_clustering": 1000, "day_variance": 1 },
  "objective_values": { "same_day_clustering": 0, "day_variance": 2 }
}
```
- `warnings[]`: non-fatal - names every resolved class with no `home_room_id` set.
  Empty when every resolved class has one configured.
- `findings[]` (this revision): any `"warning"`-severity pre-flight finding for this
  (successful) run — see "Actionable infeasibility diagnostics" below for the shape
  and full list of finding codes. `"error"`-severity findings never reach this far;
  they short-circuit into a `422` before the solver is ever called.
- `objective_weights`/`objective_values`: the solver's two soft-preference terms (see
  the "Solver quality fixes" note above) - `0` in `objective_values` means that
  preference was fully satisfied at the returned solution.
- **Errors:** `400` empty `grade_levels`/`subjects`/`room_ids`, `sections_per_grade
  < 1`, a requested grade with fewer seeded sections than `sections_per_grade`,
  an unknown `subject_id`, or an unknown `room_id` for this school; `422` (this
  revision — see below for the full structured shape) either a pre-flight
  arithmetic check failed (`stage: "preflight"`, before the solver ever runs) or
  every pre-flight check passed but CP-SAT itself still proved the input infeasible
  (`stage: "solve"`).

**Cross-grade/cross-class teacher conflicts are structurally prevented BOTH within
one `/generate` call and across separate calls (this revision fixes the latter — a
real gap, not just a diagnostics-layer one).** Within one call, the no-double-
booking constraint keys purely on `(teacher_id, day_of_week, period_number)` with
no class/grade dimension at all, so a teacher assigned to *any* requirement (any
class, any grade) at a slot already blocks every other requirement in that SAME
call from using that same teacher+slot (confirmed by
`test_generate_never_double_books_teacher_across_two_classes`). Generation happens
one grade/section-batch at a time in practice (the UI only allows selecting one
grade per run) though, and until this revision a teacher qualified across two
SEPARATE such runs had no cross-run awareness at all — nothing stopped a later
run from double-booking them into a slot an earlier run already gave them for a
different class's still-active slots. `POST /timetable/generate` now also queries
each included teacher's existing active `TimetableSlot` rows for this academic
year (excluding the classes THIS run is about to supersede) and merges those into
the solver's own unavailability input, so a later run correctly treats them as
blocked (confirmed by
`test_generate_never_double_books_a_teacher_across_two_separate_generate_calls`).

### Actionable infeasibility diagnostics (this revision)

Replaces the old behavior — a failed generation returning only `"No feasible
timetable exists for the given teachers/rooms/requirements"` after up to a 30s
solve — with specific, quantified, actionable reasons, computed in two stages.

**Stage 1 — pre-flight (`backend/app/services/timetable_preflight.py`), milliseconds,
before the solver ever runs.** Pure arithmetic (plus two small bipartite max-flow
computations to correctly handle overlapping teacher/room pools — a naive
independent-sum check can pass a genuinely infeasible input when, e.g., two
subjects share their only qualified teacher). Runs ALL checks and returns every
failure together, not just the first:
- **Section balance** — total required periods/week vs. `periods_per_day ×
  days_per_week`. Over-subscription is `"error"` (`SECTION_OVER_SUBSCRIBED`);
  under-subscription is `"warning"` (`SECTION_UNDER_SUBSCRIBED` — may be
  intentional free periods).
- **Teacher pool capacity** — per subject, qualified-teacher capacity vs. demand,
  overlap-aware (`TEACHER_POOL_SHORTFALL`, `"error"`); a pool above 85% utilization
  that still technically passes gets a `TEACHER_POOL_TIGHT` `"warning"`.
- **Room concurrency** — sections needing a room simultaneously vs. non-lab rooms
  selected for this run, including home-room-pinning collisions (two sections
  sharing one `home_room_id` — rejected earlier too, at the master-data layer, but
  re-checked here defensively) (`ROOM_HOME_COLLISION`, `ROOM_CONCURRENCY_SHORTFALL`).
- **Lab concurrency** — weekly total (`LAB_CAPACITY_SHORTFALL`) AND exact peak
  concurrency via a 3-layer max-flow modeling per-class slot exclusivity
  (`LAB_PEAK_CONCURRENCY_SHORTFALL`) — a single class needing two lab-required
  subjects can still only occupy one lab at a time, however many lab rooms exist,
  which a plain weekly-total check can't see.
- **Per-teacher availability** — `TeacherUnavailability` vs. each teacher's assigned
  share of demand (`TEACHER_AVAILABILITY_SHORTFALL`).
- **Cross-run collisions** — periods already committed to previously generated
  grades this academic year vs. periods free (`CROSS_RUN_COLLISION`) — see the
  cross-grade/cross-class note above for the related correctness fix.
- **Class teacher assigned** — every section in this run must have a
  `SchoolClass.class_teacher_id` set (`CLASS_TEACHER_MISSING`, `"error"`) — a
  school-operations policy gate (added this session), not a solver-feasibility
  one; lists every section still missing one together in one finding, not just
  the first. Fix in School Management → Classes → Edit → Class teacher.

Every `"error"`-severity finding carries at least one `remedies[]` entry with a
concrete quantity (never "add more teachers" — always "add 1 teacher qualified for
english, or reduce english by 2 periods/week"), offering alternatives (add
capacity vs. reduce demand) where both genuinely exist.

**Stage 2 — solve-time diagnosis (`timetable_solver.diagnose_infeasibility`),
only when pre-flight passes but CP-SAT still proves infeasible** (a genuine
constraint-interaction case pure arithmetic can't predict — e.g. a teacher's only
free slots are real in raw count but all land on one day, tripping the same-
subject-per-day spread cap). Rebuilds a similar model with each requirement's own
hard constraints gated behind a dedicated CP-SAT assumption literal
(`model.NewBoolVar` + `.OnlyEnforceIf` + `model.AddAssumptions`), leaving the
physical double-booking constraints as always-true bedrock, never assumptions.
On `INFEASIBLE`, `solver.SufficientAssumptionsForInfeasibility()` returns the
minimal set of assumptions that together cause it — i.e. the SPECIFIC conflicting
requirements — translated into a plain sentence naming them and the shared
teacher pool they're contending for (code `SOLVE_CONSTRAINT_CONFLICT`). Falls back
to `INFEASIBLE_NO_MAPPABLE_REQUIREMENT`/`INFEASIBLE_CORE_UNAVAILABLE` if no
requirement had any eligible teacher/room, or the core turns out empty/unmappable.

**Failure response shape** (both stages) — `POST /timetable/generate`'s `422`
`detail`, and `POST /timetable/preflight`'s `200` body:
```json
{
  "feasible": false,
  "stage": "preflight",
  "findings": [
    {
      "severity": "error",
      "code": "TEACHER_POOL_SHORTFALL",
      "subject": "english",
      "message": "english needs 20 periods/week but its qualified teachers supply at most 16 periods/week total - 4 short.",
      "numbers": { "demand": 20, "capacity": 16, "shortfall": 4, "additional_teachers_needed": 1 },
      "remedies": [
        { "action": "add_teachers", "quantity": 1, "detail": "1 more teacher(s) qualified for english" },
        { "action": "reduce_periods", "quantity": 4, "detail": "reduce english by 4 period(s)/week" }
      ],
      "details": null
    }
  ]
}
```

#### `POST /timetable/preflight`
Read-only: runs the exact same pre-flight checks (stage 1 above) `POST /generate`
itself gates on, without touching the database or running the solver — meant to
be called live as the admin edits the Generate dialog (debounced client-side),
so arithmetic problems surface before Generate is even pressed, not 30s after.
Deliberately calls this endpoint from the frontend rather than reimplementing the
arithmetic in TypeScript, so the live check and the real gate can never drift
apart.
- **Roles:** admin, principal
- **Request:** identical shape to `POST /timetable/generate`'s request.
- **Response:** the same `{ feasible, stage, findings }` shape shown above —
  `stage` is `null` when `feasible: true`.
- **Errors:** same `400`/`403` validation as `/generate` (unknown ids, school
  mismatch, etc.) — never a `422`, since this endpoint doesn't run the solver.

#### `GET /timetable/active`
Fetch active (`is_active=true`) slots for an academic year, scoped by role: admin/
principal may filter freely by `class_id`/`teacher_id`; teacher is forced to their own
`teacher_id`; student is scoped to their primary-enrollment class; parent must pass
`student_id` for a linked child (`403` if not linked).
- **Roles:** admin, principal, teacher, student, parent
- **Query:** `?academic_year=` (required) `&class_id=&teacher_id=&student_id=`
- **Response:** array of the same slot shape as `/generate`'s `slots`.

#### `PUT /timetable/update`
Manual slot edit (day/period/teacher/room/subject). Re-checks for teacher/room/class
conflicts against other active slots before applying - on conflict, the slot is left
untouched and the conflicts are returned instead (never silently overwritten).
- **Roles:** admin, principal
- **Request:** `{ "slot_id": 101, "day_of_week": 1, "period_number": 2, "teacher_id": null, "room_id": null, "subject_id": null }`
(only `slot_id` is required; other fields are optional partial updates)
- **Response (applied):** `{ "slot": { ...same slot shape... }, "conflicts": [] }`
- **Response (conflict, not applied):**
```json
{ "slot": null, "conflicts": [ { "type": "teacher", "conflicting_slot_id": 55, "message": "Teacher already booked in this period" } ] }
```
- **Errors:** `404` slot not found.

### Attendance (CV mode)

Face detection/recognition backed by OpenCV (image decoding) + face_recognition/dlib
(128-d embeddings, `backend/app/services/attendance_cv.py`), stored via pgvector
(`face_embeddings.embedding`). RFID mode and CV/RFID reconciliation are a later
session - the `attendance_reconciliations` table exists in the schema but nothing
populates it yet. `face_location` below is `[top, right, bottom, left]` pixel
coordinates. A match's `confidence` is `max(0, 1 - distance)` (not a calibrated
probability, just a monotonic ranking/threshold signal) - `needs_review: true` means
it matched but only past a looser distance threshold than the confident-auto-accept
one, not that it's unmatched.

#### `POST /attendance/enroll`
Upload one reference photo for a student and store its face embedding. The photo must
contain exactly one face - `422` if zero or more than one are detected (an ambiguous
reference photo would silently corrupt later matching).
- **Roles:** admin, teacher
- **Request:** `multipart/form-data` - `student_id` (form field) + `file` (image)
- **Response:** `{ "id": 12, "student_id": 15, "enrolled_at": "2026-08-09T10:00:00Z" }`
- **Errors:** `404` unknown student; `422` no/multiple faces detected or undecodable image.

#### `POST /attendance/mark`
Run recognition against every enrolled embedding for the slot's class and create
`AttendanceRecord` rows (`status: "present"`, `source: "cv"`) for each match. Faces
that don't match any enrolled student are returned but not persisted (no student to
attach them to). Re-running for the same slot/date is idempotent - already-marked
students are reported back with `already_marked: true` and no duplicate row.
- **Roles:** admin, teacher
- **Request:** `multipart/form-data` - `timetable_slot_id` (form field) + `file`
  (classroom photo) + optional `date` (form field, `YYYY-MM-DD`, defaults to today)
- **Response:**
```json
{
  "timetable_slot_id": 5,
  "class_id": 2,
  "date": "2026-08-09",
  "records_created": 2,
  "matches": [ { "student_id": 15, "confidence": 0.82, "needs_review": false, "face_location": [10, 200, 150, 50], "record_id": 501, "already_marked": false } ],
  "unmatched_faces": [ { "face_location": [10, 400, 150, 250], "best_confidence": 0.31 } ]
}
```
- **Errors:** `404` unknown `timetable_slot_id`; `422` undecodable image.

#### `GET /attendance/summary`
Per-student/class attendance stats over a date range. Role-scoped like
`/timetable/active`: admin/principal may filter freely; teacher is scoped to classes
where they're `class_teacher` (`403` if `class_id` isn't theirs); student is forced to
their own records regardless of any `student_id` passed; parent must pass `student_id`
for a linked child (`403` if not linked).
- **Roles:** admin, principal, teacher, student, parent
- **Query:** `?from_date=&to_date=` (required) `&class_id=&student_id=`
- **Response:**
```json
{
  "from_date": "2026-08-01",
  "to_date": "2026-08-09",
  "items": [ { "student_id": 15, "class_id": 2, "present_count": 6, "absent_count": 1, "late_count": 0, "total_records": 7, "present_pct": 85.7 } ]
}
```

#### `PUT /attendance/{record_id}/review`
Manual correction of a record (low-confidence CV match, or a mismatch caught during
reconciliation once that lands). Sets `reviewed_by`/`reviewed_at` to the caller.
- **Roles:** admin, principal, teacher (teacher only for records in a class they're `class_teacher` of - `403` otherwise)
- **Request:** `{ "status": "present" }` (`present` | `absent` | `late`)
- **Response:** the updated record, same shape as a `matches[]` entry plus
  `reviewed_by`/`reviewed_at`:
```json
{ "id": 501, "student_id": 15, "class_id": 2, "timetable_slot_id": 5, "date": "2026-08-09", "status": "present", "source": "cv", "marked_at": "2026-08-09T08:05:00Z", "confidence_score": 0.42, "reviewed_by": 7, "reviewed_at": "2026-08-09T09:00:00Z" }
```
- **Errors:** `400` invalid `status`; `404` unknown `record_id`.

### Attendance (day register, manual marking, analytics, per-student history)

The human-facing half of the attendance router: `POST /attendance/mark` writes
records from a photo, and these four are how a teacher/principal/admin reads a day
back, corrects it by hand, analyses it over a range, and how a student/parent sees
their own period-by-period history.

**Two conventions differ from the four CV endpoints above, on purpose:**

1. **Every class lookup is filtered by the caller's own `school_id`**, not only by
   the id in the query string, and returns `404` (not `403`) for a class outside it -
   so probing ids can't distinguish "exists, not yours" from "doesn't exist". The
   older endpoints don't do this.
2. **"A teacher's classes" is wider here.** `/summary` and `/{id}/review` mean
   homeroom ownership (`SchoolClass.class_teacher_id`). These four also count any
   class the teacher teaches ≥1 active `TimetableSlot` to, because the person who
   marks P3's attendance is P3's subject teacher, who often isn't the class teacher.
   Consequence worth knowing: a subject teacher can read and hand-mark a class's
   register but will still get `403` from `/{id}/review` for the same class.
   Widening those two tested endpoints is a separate change.

#### `GET /attendance/register`
One class's whole day as a period × student grid - the day view a teacher reads back
after the camera has run, and edits via `POST /attendance/manual`.
- **Roles:** admin, principal, teacher (scoped as above). Student/parent get `403` - they use `/attendance/my-records`.
- **Query:** `?class_id=&date=` (both required)
- **Response:**
```json
{
  "class_id": 2, "class_name": "Grade 8 - A", "grade_level": 8, "grade_label": null,
  "section": "A", "date": "2026-08-17", "day_of_week": 0, "academic_year": "2026-27",
  "periods": [
    { "timetable_slot_id": 5, "period_number": 1, "start_time": "08:00:00", "end_time": "08:45:00",
      "subject_id": 3, "subject_name": "Math", "teacher_id": 7, "teacher_name": "R. Iyer",
      "is_marked": true, "marked_count": 28 }
  ],
  "students": [
    { "student_id": 15, "name": "Aarav Sharma",
      "cells": [ { "timetable_slot_id": 5, "record_id": 501, "status": "present", "source": "cv",
                   "confidence_score": 0.47, "needs_review": true, "reviewed_by_name": null } ],
      "present_count": 1, "absent_count": 0, "late_count": 0, "unmarked_count": 0, "present_pct": 100.0 }
  ],
  "totals": { "roster_size": 30, "period_count": 8, "marked_periods": 7, "unmarked_periods": 1,
              "present_cells": 210, "absent_cells": 8, "late_cells": 2, "unmarked_cells": 20,
              "present_pct": 95.5 }
}
```
- **`periods[].is_marked: false`** means the period has NO records at all. Without it,
  "the teacher never marked P5" and "every student was absent in P5" are
  indistinguishable, and the second is far rarer - the UI raises a warning on it.
- **`cells[].status: null`** is unmarked (no record). Distinct from `"absent"`.
- **`cells[].needs_review`** is recomputed from the stored `confidence_score` (the
  0.45-0.6 distance band in `attendance_cv.py`, i.e. confidence 0.40-0.55) and is
  `false` once `reviewed_at` is set - so it survives a page reload rather than living
  only in the `POST /mark` response.
- **`students[].present_pct`** is of periods actually **marked** for that student;
  unmarked periods are excluded from the denominator, not counted as absent.
- **Errors:** `400` caller has no `school_id`; `403` teacher and not their class; `404` class not in caller's school.

#### `POST /attendance/manual`
Mark/correct attendance by hand for any number of student-period cells. Bulk on
purpose: "mark all 40 present" is one request, not 40.
- **Roles:** admin, principal, teacher (scoped as above)
- **Request:**
```json
{ "class_id": 2, "date": "2026-08-17",
  "entries": [ { "student_id": 15, "timetable_slot_id": 5, "status": "absent" } ] }
```
- **Response:** `{ "created": 1, "updated": 0, "unchanged": 0, "records": [ ...AttendanceRecord ] }`
- **UPSERTS, NEVER DOUBLE-INSERTS - the important part.** If a record already exists
  for a `(student_id, timetable_slot_id, date)` in **any** source, it is updated in
  place and stamped `reviewed_by`/`reviewed_at`. It deliberately does **not** insert a
  second `source: "manual"` row beside a `source: "cv"` one: the table's unique
  constraint is `(student_id, timetable_slot_id, date, source)`, so the DB *would*
  allow both, and that would silently double-count the period in
  `/attendance/summary`, `/attendance/analytics` and the nightly risk scorer.
- **`source` is left unchanged on update**, so a corrected camera record still reads
  as "the CV wrote this, then a human changed it"; `reviewed_by` is what proves the
  human touch. Only a genuinely new cell is inserted as `source: "manual"`.
- **No unmark.** There is no operation that deletes a record, only status changes, so
  a cell that has been marked cannot return to `status: null`.
- Duplicate entries for the same cell collapse, last one wins. `entries: []` is a
  no-op `200`. An entry whose status already matches counts as `unchanged` and writes
  **no** audit row, so bulk marking doesn't flood the audit log.
- Each created/updated record writes an `audit_log_entries` row with
  `action: "manual_mark"`, `entity_type: "attendance_records"` and a detail carrying
  `previous_status` / `new_status`.
- **Errors:** `400` invalid status, student not primary-enrolled in `class_id`, slot not an active period of `class_id`, or caller has no `school_id`; `403` teacher and not their class; `404` class not in caller's school.

#### `GET /attendance/analytics`
Attendance sliced by period, day, class/section, subject and student over a range -
the sort-and-analyse view.
- **Roles:** admin, principal, teacher (scoped as above). Student/parent `403`.
- **Query:** `?from_date=&to_date=` (required) `&class_id=&grade_level=&section=&period_number=&subject_id=&below_pct=`
- **Response:**
```json
{
  "from_date": "2026-07-18", "to_date": "2026-08-17",
  "overall": { "present_count": 210, "absent_count": 8, "late_count": 2, "total_records": 220, "present_pct": 95.5 },
  "by_period":  [ { "period_number": 1, "present_count": 28, "absent_count": 2, "late_count": 0, "total_records": 30, "present_pct": 93.3 } ],
  "by_day":     [ { "date": "2026-08-17", "day_of_week": 0, "present_count": 28, "absent_count": 2, "late_count": 0, "total_records": 30, "present_pct": 93.3 } ],
  "by_class":   [ { "class_id": 2, "class_name": "Grade 8 - A", "grade_level": 8, "grade_label": null, "section": "A", "present_pct": 93.3, "present_count": 28, "absent_count": 2, "late_count": 0, "total_records": 30 } ],
  "by_subject": [ { "subject_id": 3, "subject_name": "Math", "present_pct": 93.3, "present_count": 28, "absent_count": 2, "late_count": 0, "total_records": 30 } ],
  "students":   [ { "student_id": 15, "name": "Aarav Sharma", "class_id": 2, "class_name": "Grade 8 - A", "section": "A",
                    "present_count": 6, "absent_count": 1, "late_count": 0, "total_records": 7, "present_pct": 85.7,
                    "trend_delta": -4.2, "trend": "falling" } ],
  "roster_size": 30, "below_pct_count": 8
}
```
- **`by_period` and `by_subject` only cover records attached to a timetable slot**;
  `overall`, `by_day`, `by_class` and `students` count every record in range. Today
  every record this router writes has a slot so the two agree - a future holiday/ad-hoc
  record with a null slot would appear in the latter and not the former.
- **`trend_delta`** is `present_pct` over the newer half of the range minus the older
  half, in percentage points (`0.0` when either half has no records, so a single-day
  range never invents a trend). `trend` buckets it at ±2 points.
- **`students`** is sorted worst `present_pct` first. `below_pct` **filters** that
  list to students under the threshold (the defaulter list); `below_pct_count` is that
  count, or the count under 75% when `below_pct` is omitted.
- `section` matches `SchoolClass.section` exactly; `grade_level` matches
  `SchoolClass.grade_level` (see that model for the negative pre-Grade-1 convention).
- **Errors:** `400` `from_date` after `to_date`, or caller has no `school_id`; `403` teacher naming a class that isn't theirs; `404` `class_id` not in caller's school.

#### `GET /attendance/my-records`
One student's period-by-period attendance over a range. **This is the student and
parent portal attendance view.**
- **Roles:** all five, with different scoping:
  - **student** - always reads themselves; any `student_id` passed is **ignored**.
  - **parent** - must pass `student_id` for a linked child (`400` if omitted, `403` if not linked).
  - **admin/principal** - any student in their own school (`404` otherwise).
  - **teacher** - only students primarily enrolled in a class they can access (`403` otherwise).
- **Query:** `?from_date=&to_date=` (required) `&student_id=`
- **Response:**
```json
{
  "student_id": 15, "student_name": "Aarav Sharma", "class_id": 2, "class_name": "Grade 8 - A",
  "from_date": "2026-07-18", "to_date": "2026-08-17",
  "summary": { "present_count": 6, "absent_count": 1, "late_count": 0, "total_records": 7, "present_pct": 85.7 },
  "days": [
    { "date": "2026-08-17", "day_of_week": 0, "present_count": 2, "total_count": 2, "present_pct": 100.0,
      "periods": [ { "timetable_slot_id": 5, "period_number": 1, "start_time": "08:00:00", "end_time": "08:45:00",
                     "subject_name": "Math", "teacher_name": "R. Iyer", "status": "present", "source": "cv",
                     "marked_at": "2026-08-17T08:05:00Z" } ] }
  ]
}
```
- **`days` is newest-first** - a student opening this wants today, not the start of the
  range. `periods` within a day is period-number ascending.
- A record with no `timetable_slot_id` returns nulls for the period/subject/teacher
  fields rather than being dropped.
- **Errors:** `400` `from_date` after `to_date`, parent omitted `student_id`, staff omitted `student_id`, or staff caller has no `school_id`; `403` parent not linked / teacher not their student; `404` unknown student, or student outside a staff caller's school.

### Predictive staffing / substitute suggestion

Completes the flagship demo chain: Attendance -> Predictive Staffing -> Leave Request
-> Auto-Substitution -> Alert. Backed by `backend/app/services/staffing_forecast.py`
(scikit-learn `PoissonRegressor` over historical approved `LeaveRequest` rows, with a
rule-based per-weekday-mean fallback when there isn't enough history to fit anything -
**a demo-scale model, not production-grade**, see that module's docstring) and
`backend/app/services/substitute_solver.py` (hard-filters candidates to
qualified+free+available+not-on-leave, ranks survivors by workload balance). A
`Substitution` row is one per distinct recurring timetable slot affected by a leave,
not one per calendar occurrence - the same substitute covers every week of a
multi-week leave for that slot. `day_of_week`/`period_number` follow the Timetable
section's conventions (0 = Monday).

**Integration point for later work (not built here):** `PUT /substitution/{id}/confirm`'s
response includes everything Person C's notification system would need to alert the
right people - `class_id`, `class_name`, `subject_name`, both teachers' names, and
`affected_student_ids` (via that class's homeroom `Enrollment` rows) - without an
extra query. Nothing currently calls out to a notification system; this is just
making sure the data is there when someone does.

#### `POST /staff/request_leave`
A teacher requests leave; admin/principal can file on behalf of a teacher.
- **Roles:** teacher, admin, principal
- **Request:** `{ "teacher_id": 97, "start_date": "2026-08-14", "end_date": "2026-08-14", "reason": "Feeling unwell" }`
(`teacher_id` required for admin/principal filing on behalf of someone; ignored - forced to the caller - for the teacher role)
- **Response:** `{ "id": 12, "teacher_id": 97, "start_date": "2026-08-14", "end_date": "2026-08-14", "reason": "Feeling unwell", "status": "pending", "requested_at": "2026-08-10T10:00:00Z", "decided_by": null, "decided_at": null }`
- **Errors:** `400` `end_date` before `start_date`, or `teacher_id` missing when admin/principal files on behalf of someone.

#### `PUT /staff/approve_leave`
Approve or reject a leave request. On approval, resolves every distinct timetable
slot the teacher has during the leave window and creates a `Substitution` row per
slot, pre-populated with the solver's top suggestion (if any).
- **Roles:** admin, principal
- **Request:** `{ "leave_request_id": 12, "decision": "approved", "academic_year": "2026-27", "comment": null }`
(`academic_year` required when `decision` is `"approved"` - needed to resolve affected timetable slots; omit for `"rejected"`. `comment` is optional - an approver's note back to the teacher, persisted to `leave_requests.decision_comment` and appended to the teacher's notification. A null/blank `comment` never overwrites a note an earlier decision already recorded.)
- **Response:**
```json
{
  "leave_request": { "id": 12, "teacher_id": 97, "start_date": "2026-08-14", "end_date": "2026-08-14", "reason": "Feeling unwell", "status": "approved", "requested_at": "2026-08-10T10:00:00Z", "decided_by": 41, "decided_at": "2026-08-10T10:05:00Z", "decision_comment": "Approved - Meera covers your Friday periods." },
  "substitutions": [
    {
      "id": 5, "leave_request_id": 12, "timetable_slot_id": 501, "original_teacher_id": 97, "substitute_teacher_id": 99,
      "status": "suggested", "suggested_score": 0.85, "confirmed_at": null,
      "subject_id": 40, "class_id": 41, "day_of_week": 4, "period_number": 2,
      "candidates": [ { "teacher_id": 99, "score": 0.85, "reason": "qualified for subject, current workload 9 periods/week" } ]
    }
  ]
}
```
- **Errors:** `400` invalid `decision` or missing `academic_year` on approval; `404` unknown `leave_request_id`.

#### `POST /substitution/suggest`
Re-run the solver. Two mutually exclusive modes:
- **Mode A** (`leave_request_id` given): re-runs and persists fresh suggestions for
  every `Substitution` already tied to that leave - e.g. if the first approval pass
  had no good matches and circumstances changed.
- **Mode B** (`teacher_id`+`start_date`+`end_date`+`academic_year`, no `leave_request_id`):
  preview suggestions for a hypothetical date range with nothing persisted - useful
  before a leave request even exists.
- **Roles:** admin, principal
- **Request (mode A):** `{ "leave_request_id": 12, "academic_year": "2026-27" }`
- **Request (mode B):** `{ "teacher_id": 97, "start_date": "2026-08-14", "end_date": "2026-08-14", "academic_year": "2026-27" }`
- **Response:** `{ "substitutions": [ /* same shape as approve_leave's, except mode B entries have id/leave_request_id/status/suggested_score all null - nothing was persisted */ ] }`
- **Errors:** `400` neither mode's required fields present; `404` unknown `leave_request_id`.

#### `PUT /substitution/{id}/confirm`
Confirm a specific substitute for a slot, or override with a different teacher than
suggested. Re-checks eligibility first (qualified, free, available, not on leave, not
the absent teacher themselves) - on conflict, nothing is applied.
- **Roles:** admin, principal
- **Request:** `{ "substitute_teacher_id": 99 }` (omit to confirm whichever teacher is currently suggested)
- **Response (applied):**
```json
{
  "substitution": { "id": 5, "leave_request_id": 12, "timetable_slot_id": 501, "original_teacher_id": 97, "substitute_teacher_id": 99, "status": "confirmed", "suggested_score": 0.85, "confirmed_at": "2026-08-10T10:10:00Z", "subject_id": 40, "class_id": 41, "day_of_week": 4, "period_number": 2, "candidates": [] },
  "conflicts": [],
  "class_id": 41, "class_name": "Class 8A", "subject_name": "Math",
  "original_teacher_name": "Demo Teacher 1", "substitute_teacher_name": "Demo Teacher 3",
  "affected_student_ids": [103, 104, 105],
  "leave_start_date": "2026-08-14", "leave_end_date": "2026-08-14"
}
```
- **Response (conflict, not applied):** `{ "substitution": null, "conflicts": [ { "type": "already_busy", "message": "Teacher already has a class at this day/period" } ] }`
(`type` is one of: `not_qualified`, `already_busy`, `unavailable`, `on_leave`, `is_original_teacher`)
- **Errors:** `400` no `substitute_teacher_id` given and none currently suggested; `404` unknown substitution id.

#### `GET /staff/leave_requests`
List leave requests, filterable by status. Role-scoped: teacher sees only their own
(any `teacher_id` param is ignored); admin/principal see every leave request in the
system (no school-scoping yet, same simplification as `/timetable/active` and
`/attendance/summary`) and may filter by `teacher_id`.
- **Roles:** teacher, admin, principal
- **Query:** `?status=&teacher_id=` (both optional)
- **Response:** array of the same leave-request shape as `/staff/request_leave`'s response, including `decision_comment` (`null` while pending, or when the approver left it blank).

  `decision_comment` is the teacher's only durable view of *why* a request was
  decided the way it was. The Approvals Inbox has always accepted a `comment` on
  `POST /admin/approvals/{id}/decision`, but it was previously written **only** into
  `audit_log_entries.detail` - and `GET /audit/*` is admin/principal-only, so the note
  was unreadable by the person it was written for. It is now persisted on the leave
  request itself and rendered on the teacher's own leave card.

#### `GET /admin/staffing/forecast`
Predictive staffing shortage forecast for a week. Recomputes from historical approved
`LeaveRequest` rows and **upserts** into `staffing_forecasts` on every call, so later
reads (e.g. the admin command center) don't need to re-run the model.
- **Roles:** admin, principal
- **Query:** `?school_id=&week_start=`
- **Response:**
```json
{ "school_id": 41, "week_start": "2026-08-10", "forecast": [ { "date": "2026-08-10", "predicted_absences": 0.4, "risk_level": "low" }, { "date": "2026-08-14", "predicted_absences": 2.1, "risk_level": "medium" } ] }
```

#### `GET /admin/staffing/substitute-suggestions`
Suggest substitutes for every slot a specific teacher has on a specific date -
read-only, nothing persisted. Extended from the original stub with `academic_year`
(needed to resolve timetable slots) and a `slots` breakdown (a teacher can have
multiple different-subject slots in one day, each needing its own candidates).
- **Roles:** admin, principal
- **Query:** `?teacher_id=&date=&academic_year=`
- **Response:**
```json
{
  "absent_teacher_id": 97, "date": "2026-08-14",
  "slots": [ { "timetable_slot_id": 501, "subject_id": 40, "class_id": 41, "period_number": 2, "suggestions": [ { "teacher_id": 99, "score": 0.85, "reason": "qualified for subject, current workload 9 periods/week" } ] } ]
}
```

### Early-warning flags

Second flagship demo chain, the AI half: Assignment/quiz -> grade -> Gradebook ->
Performance analytics -> **Early-Warning ML** -> at-risk flag -> Teacher + Parent +
Counselor notified. Backed by `backend/app/services/risk_scorer.py` (a documented
heuristic, not a trained model - see its docstring for the weighting logic) and
`backend/app/services/remark_sentiment.py` (VADER sentiment analysis). Flags are
created either manually (`POST /risk/flag`) or by the nightly job
(`backend/scripts/run_nightly_risk_scoring.py` - no scheduler infra exists in this
repo yet, so it's a plain script for now, structured to drop into a real scheduler
later without rework).

**Which signals are real vs. placeholder - read before trusting a score:**
- **Attendance: fully real.** Computed from this project's own `attendance_records`.
- **Grades: placeholder, currently unused.** Person B's gradebook doesn't exist in
  this repo yet (checked before building this). `risk_scorer.py`'s `GradeSignal` is a
  documented dataclass *interface* with no backing table - nightly scoring currently
  always passes `grades=None`, and the scorer excludes it from the score entirely
  rather than assuming a fabricated average. Wire a real `GradeSignal` in once the
  gradebook lands; nothing else about the API or scoring changes.
- **Remark sentiment: the analysis is real, the text source is a placeholder.**
  `remark_stubs` (`backend/app/models/risk.py`) is an explicitly-marked stand-in
  table for Person B's not-yet-built remarks/report-card system, seeded with
  synthetic remark text so the sentiment pipeline is genuinely testable end-to-end
  today. Point it at the real remarks table once that exists.

**Integration point for later work (not built here):** every `FlagOut` response
(create and list alike) is enriched with `class_id`/`class_name` (via the student's
primary `Enrollment`), `homeroom_teacher_id` (via that class's `class_teacher_id`),
and `parent_ids` (via `parent_student`, plural for multi-parent support) - everything
Person C's future notifier needs to reach teacher + parent + counselor without a
re-query. Same pattern as Staffing's `confirm` endpoint. Nothing calls out to a
notification system yet.

#### `POST /risk/flag`
Manually flag a student as potentially at-risk (a human's judgment call, not an
algorithmic score - contrast with the nightly job's flags).
- **Roles:** teacher, admin, principal
- **Request:** `{ "student_id": 103, "risk_level": "high", "reasons": ["seems withdrawn in class", "missed 3 assignments"], "score": null }`
(`score` optional - omit to use a nominal value for the given `risk_level`: low=0.2, medium=0.5, high=0.8)
- **Response:** same shape as `/risk/flagged`'s items (below), including the alert-ready enrichment.
- **Errors:** `400` invalid `risk_level` or empty `reasons`; `404` unknown `student_id`.

#### `GET /risk/flagged`
List currently-flagged students (excludes `resolved` unless `status` is explicitly
requested). Role-scoped: teacher sees only students in classes where they're
`class_teacher` (`403` if `class_id` isn't theirs); parent must pass `student_id` for
a linked child (`400` if omitted, `403` if not linked); admin/principal see everything
and may filter freely. Student role is not authorized on this endpoint.
- **Roles:** teacher, admin, principal, parent
- **Query:** `?risk_level=&class_id=&student_id=&status=`
- **Response:**
```json
[
  {
    "id": 7, "student_id": 103, "risk_level": "high", "score": 0.75,
    "reasons": ["attendance rate 40% is below the 90% threshold", "recent teacher remarks skew negative (avg sentiment -0.67)"],
    "flagged_at": "2026-08-11T02:00:00Z", "status": "open", "resolved_by": null, "resolved_at": null,
    "class_id": 41, "class_name": "Class 8A", "homeroom_teacher_id": 97, "parent_ids": [127], "student_name": "Demo Student Class 8A #01"
  }
]
```

#### `PUT /risk/{id}/acknowledge`
Acknowledge an open flag (no separate "who/when" columns exist for this - only
`status` changes; contrast with `resolve`, which does record `resolved_by`/`resolved_at`).
- **Roles:** teacher, admin, principal
- **Response:** the updated flag, same shape as `/risk/flagged`'s items.
- **Errors:** `400` flag isn't currently `open`; `404` unknown flag id.

#### `POST /risk/{id}/intervention`
Log an outreach/intervention note against a flag - the history of what staff actually
did, independent of the flag's own status.
- **Roles:** teacher, admin, principal
- **Request:** `{ "note": "Called parent to discuss attendance", "action_taken": "called_parent" }`
(`action_taken` is free text, not an enum - e.g. "called parent", "counselor referral", "teacher meeting")
- **Response:** `{ "id": 3, "risk_flag_id": 7, "created_by": 97, "note": "Called parent to discuss attendance", "action_taken": "called_parent", "created_at": "2026-08-11T03:00:00Z" }`
- **Errors:** `400` empty `note`/`action_taken`; `404` unknown flag id.

#### `PUT /risk/{id}/resolve`
Mark a flag resolved.
- **Roles:** admin, principal
- **Response:** the updated flag (`status: "resolved"`, `resolved_by`/`resolved_at` set), same shape as `/risk/flagged`'s items.
- **Errors:** `400` flag is already resolved; `404` unknown flag id.

#### `GET /admin/early-warning/students`
Fetch at-risk students - reconciled with this pre-existing stub rather than
duplicated under `/risk/flagged`: same underlying flags, this endpoint keeps the
original role gate (no parent) and response shape (`{"items": [...]}`)  for whoever
was already coding against it.
- **Roles:** admin, principal, teacher
- **Query:** `?class_id=&risk_level=`
- **Response:**
```json
{ "items": [ { "student_id": 103, "risk_level": "high", "reasons": ["attendance rate 40% is below the 90% threshold"], "flagged_at": "2026-08-11T02:00:00Z" } ] }
```

### Remarks (read)

Read access to the teacher remarks that feed the early-warning scorer. Until this
endpoint existed, `remark_stubs` rows were only reachable indirectly - the sentiment
that came out of them showed up inside a `RiskFlag`'s `reasons` strings, but nothing
could show a parent or student the actual remark text behind a flag.

**Reads the placeholder table, deliberately.** `remark_stubs` is Person B's
stand-in (see the Early-warning section above and `app/models/risk.py`'s
`RemarkStub` docstring). This endpoint is a thin read over whatever that table
holds; when Person B's real remarks system lands, repoint the query and the
response shape below stays the same. It is read-only on purpose - creating remarks
is Person B's domain, not this one.

`sentiment` is computed per-request by `app/services/remark_sentiment.py` (VADER),
not stored - there is no sentiment column on the table.

#### `GET /remarks/student/{student_id}`
Remarks written about one student, newest first. Role-scoped the same way as
`GET /admin/fees/status`: a student may only read their own (`403` otherwise); a
parent must name a linked child (`403` if not linked); a teacher sees only students
in classes where they are `class_teacher` (`403` otherwise); admin/principal are
scoped to their own school via `User.school_id` (`404` for a student outside it).
- **Roles:** student, parent, teacher, admin, principal
- **Response:**
```json
{
  "items": [
    {
      "id": 12, "student_id": 103, "teacher_id": 97, "teacher_name": "Asha Rao",
      "remark_text": "Missed three consecutive homework submissions.",
      "sentiment": { "label": "negative", "compound": -0.4019 },
      "created_at": "2026-08-11T09:15:00Z"
    }
  ]
}
```
- **Errors:** `403` not authorized for this student (any role's scoping failure);
  `404` unknown `student_id`, or a student outside an admin/principal's own school.

### Admin command center

"The single screen admins live in" - a pure AGGREGATION feature over data every other
Person-A endpoint already owns and writes to. Backed by `backend/app/services/
alert_aggregator.py`: a registry of pluggable alert-source functions (one per
integrated feature), each reading its own table live and emitting a common `Alert`
shape. Nothing here creates or mutates a RiskFlag/LeaveRequest/Substitution/Document
row - it only reads them. Adding a future alert source (e.g. once Syllabus Tracking
exists) means writing one new function and registering it - see that module's
docstring.

**Alert sources wired in today**, with their severity rule (exactly two levels,
`normal`/`urgent` - not a third tier, so a notification consumer can act on severity
unambiguously):
| source | condition | severity |
| --- | --- | --- |
| `risk_flag` | RiskFlag open/acknowledged | `urgent` if `risk_level="high"` AND still `open`; `normal` once acknowledged or lower risk |
| `leave_request` | LeaveRequest `status="pending"` | always `normal` |
| `substitution` | Substitution `status="suggested"` (unconfirmed) | `urgent` if the covering leave's `start_date` is within 3 days (or past); else `normal` |
| `document_failed` | Document `status="failed"` | always `urgent` (the source image is never persisted - see `models/document.py` - so a failed document can't simply be retried) |
| `document_low_confidence` | a Document has an uncorrected `is_low_confidence` field | always `normal`, one alert per document (not per field) |
| `attendance_reconciliation` | AttendanceReconciliation `status="pending"` | always `normal` - included for completeness but expect this empty today; nothing populates that table yet (no RFID ingestion/reconciliation job exists) |
| `anomaly_flag` | AnomalyFlag open (Syllabus/Anomaly session) | copied straight from `AnomalyFlag.severity` |
| `fee_overdue` | FeeRecord `status="overdue"` (Fees & Admissions session) | `urgent` at >=30 days overdue (matches `fee_reminder_engine.py`'s own escalated tier), else `normal` |

Two sources above (`anomaly_flag`, `fee_overdue`) were added in later sessions than
this table itself - `anomaly_flag` was missing from this table even after being
wired in, an oversight caught and fixed while adding `fee_overdue` this session.

**A known gap, not silently solved:** `/timetable/update`'s conflict detection
(`_find_conflicts` in `routers/timetable.py`) is purely transient - conflicts are
returned in the response and never persisted, so there is no table for a "timetable
conflict" alert to read from. Not included as a source; retrofitting persistence
there is a real UX decision that belongs to whoever owns that endpoint.

**Composite alert ids - a new pattern, read before building a notification UI
against this:** an alert's `id` is `"{source}:{entity_id}"`, e.g. `"risk_flag:43"` -
`entity_id` alone is not unique across sources, so `id` is the only safe identifier
to hold onto or pass to resolve.

**Resolve routing is NOT the same mechanism for every source** - see
`alert_aggregator.py`'s "RESOLVE ROUTING" docstring for the full reasoning:
- `risk_flag` routes to RiskFlag's own real `status="resolved"` transition (the same
  one `PUT /risk/{id}/resolve` uses) - there's no separate dismissal state for it.
- Every other source (`leave_request`, `substitution`, `document_failed`,
  `document_low_confidence`, `attendance_reconciliation`) records a row in a new,
  intentionally tiny `alert_dismissals` table instead. These sources' real "next
  state" is a decision made through their own dedicated endpoint (approve/reject a
  leave, confirm a substitution with a chosen teacher) that a generic resolve must
  not fake - dismissing here only hides the alert from the feed, it does not touch
  the source row. See `models/alerts.py`'s `AlertDismissal` docstring.

#### `GET /admin/alerts`
Unified alerts feed.
- **Roles:** admin, principal
- **Query:** `?since=&severity=` (`severity` is `normal` or `urgent`)
- **Response:**
```json
{
  "items": [
    {
      "id": "risk_flag:43", "source": "risk_flag", "severity": "urgent",
      "title": "Student risk flag (high)", "message": "attendance rate 20% is below the 90% threshold",
      "entity_type": "risk_flags", "entity_id": 43,
      "created_at": "2026-08-11T14:23:27Z", "resolved": false
    }
  ]
}
```
Resolved/dismissed alerts are excluded by default (same convention as `/risk/flagged`) - there is no way to see them through this endpoint today.

#### `GET /admin/alerts/summary`
Lightweight counts-by-severity/source, for a dashboard header widget. **Not in the
original stub** - a small, natural addition alongside the feed, flagged here rather
than silently added.
- **Roles:** admin, principal
- **Query:** `?since=`
- **Response:**
```json
{ "total": 5, "by_severity": { "normal": 3, "urgent": 2 }, "by_source": { "risk_flag": 2, "leave_request": 3 } }
```

#### `POST /admin/alerts/{id}/resolve`
Mark an alert resolved - `{id}` is the composite string above, e.g. `risk_flag:43`.
See "Resolve routing" above for what actually changes per source.
- **Roles:** admin, principal
- **Response:** `{ "id": "risk_flag:43", "resolved": true }`
- **Errors:** `400` malformed id (not `"source:entity_id"`), or already resolved; `404` unknown source, or entity_id doesn't exist.

#### `GET /admin/alerts/stream`
Live alert feed - **SSE, not Socket.io.** Checked first: Socket.io is named in the
tech stack doc but nothing in this repo wires it up yet (Person C hasn't started
chat, the only other feature that would plausibly need it). A plain
`text/event-stream` response needs no new dependency and no server changes; Person C
can move this onto Socket.io later if unifying makes sense once chat needs it -
nothing here blocks that. Polls the aggregator every 5 seconds (documented as
`SSE_POLL_INTERVAL_SECONDS` in `routers/admin_alerts.py`) rather than pushing on
write - genuine push (DB LISTEN/NOTIFY, a message bus) is real infrastructure this
session doesn't take on, consistent with every other "no task queue exists yet"
finding across this project.
- **Roles:** admin, principal
- **Response:** `text/event-stream`, one `data: [ ...same array GET /admin/alerts/items would contain... ]\n\n` event every ~5s.
- **Auth caveat for a real frontend:** like every other endpoint here, this expects
  `Authorization: Bearer <token>` - browsers' native `EventSource` API can't set
  custom headers, so a real frontend client will need either a signed/short-lived
  URL token or a fetch-based SSE polyfill. Not solved here; noted for whoever wires
  up the frontend.

### Syllabus tracking + Anomaly detection

Genuinely new section - no prior stub existed for either. Backed by `backend/app/
services/syllabus_pace.py` (playbook 11.3) and `backend/app/services/
anomaly_detector.py` (playbook 11.4), both decoupled from the ORM and unit-testable
standalone; persisted via `backend/app/models/syllabus.py`.

**Pacing model, kept demo-honest:** a `SyllabusPlan` is a flat `total_units` count
across `[term_start_date, term_end_date]` - no week-by-week breakdown. Expected
progress is linear (`elapsed_days / total_days`); actual progress is a raw COUNT of
logged `SyllabusCheckpoint` rows, not their `sequence_number` (a teacher may
legitimately log topics out of syllabus order). A class/subject is `behind` once
`actual_fraction - expected_fraction <= -0.15`, `ahead` at `>= +0.15`, else
`on_pace`. See `syllabus_pace.py`'s docstring for the full reasoning.

**Anomaly categories - which are real, which are stubbed, read before trusting a
flag:**
- `attendance_drop`, `document_backlog`, `teacher_overload`: **fully real**, built
  from tables this codebase already owns (`AttendanceRecord`, `Document`,
  `TimetableSlot`). `teacher_overload` uses a scikit-learn `IsolationForest` once
  there are enough teachers to make that meaningful (>=6), else a documented
  mean-multiplier fallback rule - same honesty pattern as the Staffing session's
  `PoissonRegressor` hybrid.
- `submission_rate`: **honest stub**. Checked `backend/app/models/` before building
  this (same check as Early-Warning's grades gap and OCR's admissions gap): Person
  B's assignments/submissions tables do not exist yet - only documented as a future
  contract earlier in this doc (`POST /classroom/{class_id}/assignments` etc. are
  stubs, never implemented). `SubmissionRateSignal` is a pure dataclass interface
  with no backing table, exactly like Early-Warning's `GradeSignal`.
  `scripts/run_nightly_syllabus_anomaly_scan.py` never calls this detector today for
  exactly that reason - wire a real caller in once Person B's submissions table
  exists; nothing else changes.
- `syllabus_drift`: **fully real** (see pacing model above) - a fifth type beyond
  the playbook's literal four `AnomalyFlag` categories, added deliberately: both are
  "an admin needs to know something operational is off," so they share one
  detection job, one flag table, and one alert-source registration rather than two
  parallel systems. Flagged here as a scope decision, not silently done.

`AnomalyFlag` is the 7th source registered in `alert_aggregator.ALERT_SOURCES` (see
that module and the Admin Command Center section above) - anomalies surface in
`GET /admin/alerts` automatically. Resolving works both ways: directly via
`PUT /admin/anomalies/{id}/resolve` below, or via the unified
`POST /admin/alerts/{source}:{id}/resolve` path - both hit the same
`AnomalyFlag.status` field (`anomaly_flag` was added to `admin_alerts.py`'s
real-status-transition sources alongside `risk_flag`, not the dismissal-table path).

#### `POST /syllabus/plan`
**Not in the original playbook wording** - added because without a way to create a
`SyllabusPlan`, `POST /syllabus/checkpoint` would have nothing to attach to. Flagged
here, same pattern as the Command Center session's `GET /admin/alerts/summary`.
- **Roles:** teacher, admin, principal
- **Request:** `{ "class_id": 41, "subject_id": 40, "academic_year": "2026-27", "total_units": 10, "term_start_date": "2026-01-01", "term_end_date": "2026-03-12" }`
- **Response:** `{ "id": 1, "class_id": 41, "subject_id": 40, "academic_year": "2026-27", "total_units": 10, "term_start_date": "2026-01-01", "term_end_date": "2026-03-12", "created_by": 97, "created_at": "2026-08-12T10:00:00Z" }`
- **Errors:** `400` `total_units<=0`, `term_end_date<=term_start_date`, or a plan already exists for this class/subject/academic_year; `404` unknown class/subject.

#### `POST /syllabus/checkpoint`
Log one unit of actual progress.
- **Roles:** teacher, admin, principal (a teacher may only log against a plan for a
  class+subject they actually teach, per an active `TimetableSlot` - `403` otherwise)
- **Request:** `{ "plan_id": 1, "topic_label": "Algebra basics", "sequence_number": 1 }`
- **Response:** `{ "id": 5, "plan_id": 1, "topic_label": "Algebra basics", "sequence_number": 1, "logged_by": 97, "logged_at": "2026-08-12T10:05:00Z" }`
- **Errors:** `400` empty `topic_label`; `403` teacher doesn't teach this class/subject; `404` unknown `plan_id`.

#### `GET /syllabus/summary`
Progress and drift stats by class/subject. Role-scoped: teacher sees only plans for
subjects they actually teach (via `TimetableSlot`, not just homeroom); admin/
principal see everything (no school-scoping, same simplification as `/risk/flagged`
and staffing's `leave_requests`).
- **Roles:** teacher, admin, principal
- **Query:** `?class_id=&subject_id=&academic_year=`
- **Response:**
```json
{
  "items": [
    {
      "plan_id": 1, "class_id": 41, "class_name": "Class 8A", "subject_id": 40, "subject_name": "Math",
      "academic_year": "2026-27", "total_units": 10, "checkpoints_logged": 3,
      "term_start_date": "2026-01-01", "term_end_date": "2026-03-12",
      "expected_fraction": 0.5, "actual_fraction": 0.3, "drift": -0.2, "status": "behind"
    }
  ]
}
```

#### `GET /admin/anomalies`
List current anomaly flags. **Not in the original playbook's endpoint list** -
anomaly detection had no stub at all; added cleanly and flagged here.
- **Roles:** admin, principal
- **Query:** `?type=&severity=&status=` (excludes `resolved` unless `status` is explicitly requested, same convention as `/risk/flagged`)
- **Response:**
```json
{
  "items": [
    {
      "id": 3, "type": "teacher_overload", "entity_type": "users", "entity_id": 97, "severity": "urgent",
      "detail": { "periods_per_week": 40, "peer_baseline": 10.0, "message": "Teacher 97 is teaching 40 periods/week vs a peer average of ~10.0" },
      "detected_at": "2026-08-12T02:00:00Z", "status": "open", "resolved_by": null, "resolved_at": null
    }
  ]
}
```

#### `PUT /admin/anomalies/{id}/resolve`
Resolve an anomaly flag directly - equivalent to `POST /admin/alerts/anomaly_flag:{id}/resolve`, both hit the same row.
- **Roles:** admin, principal
- **Response:** the updated flag, same shape as `/admin/anomalies`'s items.
- **Errors:** `400` already resolved; `404` unknown id.

### Approval chains

A generalization, not new domain logic: this is an AGGREGATION over entities that
already have their own real approve/reject flow (same pattern as Command Center's
`alert_aggregator.py`, applied to approvals via `backend/app/services/
approval_aggregator.py`). Nothing here duplicates `LeaveRequest`'s status as a
second approval system.

**Which entities are genuinely approval-shaped - checked every prior session's
models, not assumed:** an entity qualifies here only if it has a real PENDING state
gating a decision made by someone other than the requester, with actual approve/
reject outcomes - not merely "has a status column." **2 of 8 considered entities
qualify** (up from 1/7 last session - the registry's pluggability, proven for real):
- `LeaveRequest` (Staffing session): **yes.**
- `AdmissionApplication` (Fees & Admissions session): **yes**, but only once
  `status="under_review"` - a freshly-`submitted` application is pending an initial
  triage step, not yet at the binary decision point this inbox's approve/reject
  vocabulary fits. See `services/approval_aggregator.py`'s module docstring.
- `RiskFlag`/`Intervention` (Early-Warning), `ExtractedEntity` correction (OCR),
  `AnomalyFlag` (Syllabus/Anomaly), `Substitution` confirm (Staffing), `FeeRecord`/
  `FeeReminder` (Fees & Admissions): **no** - all are either direct actions an
  admin/teacher takes on their own authority with no second party's sign-off gating
  them, or (fees specifically) alert-worthy but not decision-gated at all - a fee
  either gets paid or doesn't, nobody "approves" it becoming due. Checked and ruled
  out honestly, not padded into the registry to look more complete. Exam Management
  (a later session) may introduce another real candidate - adding one is a single
  new function registered in `APPROVAL_SOURCES`, per that module's docstring.

**Role scoping - admin/principal only, NOT teacher** (a deliberate deviation from
this section's original stub, which listed `teacher`): the one real source can only
be decided by admin/principal, so no teacher is ever a decision-maker for anything
in this inbox today. A teacher's own filed leave requests are already visible via
the existing `GET /staff/leave_requests` self-service view. See
`routers/approvals.py`'s own comment for the full reasoning; revisit once a
genuinely teacher-decidable source exists.

**Composite id - reused from Command Center, not reinvented:** `"{type}:{entity_id}"`
e.g. `"leave_request:47"`, the exact same scheme `alert_aggregator.Alert.id` /
`POST /admin/alerts/{source}:{id}/resolve` use.

#### `GET /admin/approvals`
Fetch pending approval requests.
- **Roles:** admin, principal
- **Response:**
```json
{ "items": [ { "id": "leave_request:47", "type": "leave_request", "requested_by": 97, "requested_at": "2026-08-12T06:00:00Z", "payload": { "start_date": "2026-08-20", "end_date": "2026-08-21", "reason": "medical" }, "entity_type": "leave_requests", "entity_id": 47 } ] }
```

#### `POST /admin/approvals/{id}/decision`
Approve or reject. For `leave_request`-type approvals, routes through the exact same
`decide_leave_request()` logic (and substitute-finding side effect) as
`PUT /staff/approve_leave` - both entry points are behaviorally identical, not a
unified endpoint that silently does less.
- **Roles:** admin, principal
- **Request:** `{ "decision": "approve", "comment": null, "academic_year": "2026-27" }`
  (`academic_year` is an **addition beyond the original stub** - required only when deciding a `leave_request` approval with `decision="approve"`, needed to resolve affected timetable slots, exactly like `PUT /staff/approve_leave` already requires. Flagged here rather than silently extending the shape.)
  (`comment` for a `leave_request` decision is now **persisted to `leave_requests.decision_comment`** and surfaced to the teacher via `GET /staff/leave_requests` + their notification - not only recorded in the audit detail as before. See that endpoint's note.)
- **Response:** `{ "id": "leave_request:47", "status": "approved" }`
- **Errors:** `400` invalid `decision`, malformed id, missing `academic_year` on an approve, or the request is no longer pending; `404` unknown type or entity_id.

### Audit log

Per the playbook: "Audit log writer with a consistent schema for all auditable
actions" - `backend/app/services/audit_log.py`'s `write_audit_log()`, called from
**every** router with a privileged state-changing endpoint. Before this session,
**nothing in this repo wrote anything audit-trail-shaped** - this closes a genuine,
repo-wide gap, not a partial extension of something that already existed. Wired into
11 endpoints across 8 routers:

| Router | Endpoint | action | entity_type |
| --- | --- | --- | --- |
| timetable | `PUT /update` | `update` | `timetable_slots` |
| attendance | `PUT /{id}/review` | `review` | `attendance_records` |
| attendance | `POST /manual` | `manual_mark` | `attendance_records` |
| fees | `PUT /admin/fee-payment-requests/{id}/confirm` | `record_payment` + `confirm_fee_payment_request` | `fee_records` + `fee_payment_requests` |
| fees | `PUT /admin/fee-payment-requests/{id}/reject` | `reject_fee_payment_request` | `fee_payment_requests` |
| staffing | `PUT /staff/approve_leave` | `approve`/`reject` | `leave_requests` |
| staffing | `PUT /substitution/{id}/confirm` | `confirm` | `substitutions` |
| risk | `PUT /{id}/acknowledge` | `acknowledge` | `risk_flags` |
| risk | `POST /{id}/intervention` | `create` | `interventions` |
| risk | `PUT /{id}/resolve` | `resolve` | `risk_flags` |
| documents | `PUT .../entities/{id}` | `correct` | `extracted_entities` |
| syllabus | `PUT /admin/anomalies/{id}/resolve` | `resolve` | `anomaly_flags` |
| admin_alerts | `POST /admin/alerts/{id}/resolve` | `resolve` (real-status sources) or `dismiss_alert` (dismissal sources - honest that the underlying row did NOT change) | varies by source |
| approvals | `POST /admin/approvals/{id}/decision` | `approve`/`reject` | `leave_requests` |

Deliberately NOT wired in: read-only `GET`s, and creates without a meaningful
"state changed" semantic (`POST /risk/flag`, `POST /syllabus/checkpoint`,
`POST /timetable/generate`, etc.) - audited actions are decisions/corrections/
transitions on an existing entity, not every write in the system.

`entity_id` is not a DB-enforced foreign key - which table it refers to depends on
`entity_type`, genuinely polymorphic across every feature this repo has built (same
reasoning as `AnomalyFlag.entity_id` and `Alert.entity_id`).

**A shape change from the original stub:** this section originally spec'd one
`GET /admin/audit-log?entity_type=&entity_id=&actor_id=&page=&page_size=` endpoint.
Replaced with the two path-based endpoints the playbook itself names (`fetch all
actions by a given user` / `fetch all actions on a given object`) - no pagination,
matching this project's other list endpoints at this data scale.

#### `GET /audit/by_user/{user_id}`
All actions performed by a given user.
- **Roles:** admin, principal
- **Response:**
```json
{ "items": [ { "id": 100, "actor_id": 252, "action": "resolve", "entity_type": "risk_flags", "entity_id": 43, "detail": null, "created_at": "2026-08-12T06:00:00Z" } ] }
```

#### `GET /audit/by_object/{object_type}/{object_id}`
All actions performed on a given entity, e.g. `/audit/by_object/leave_requests/47`.
- **Roles:** admin, principal
- **Response:** same item shape as `/audit/by_user/{user_id}`.

### Fees

Backed by `backend/app/models/fees.py` (`FeeSchedule` -> `FeeRecord` -> `FeeReminder`)
and `backend/app/services/fee_reminder_engine.py`'s cadence heuristic. `FeeSchedule`
is class-scoped (`class_id` nullable = school-wide, e.g. transport; set = class-
specific, e.g. tiered tuition) - matches how real fee structures vary by grade far
more than by individual student. `scripts/run_monthly_fee_invoicing.py`'s
`run_monthly_invoicing()` generates `FeeRecord` rows from active schedules and marks
past-due ones overdue; overdue records are the 8th `alert_aggregator.ALERT_SOURCES`
entry (`fee_overdue`), so they surface in `GET /admin/alerts` automatically.
Resolving a `fee_overdue` alert via `POST /admin/alerts/fee_overdue:{id}/resolve`
only dismisses it from the feed - a fee's real resolution is a payment (below), not
a generic resolve.

**Generation is automatic, but gated by due date** - `AUTO_GENERATE_WINDOW_DAYS = 7`
(`scripts/run_monthly_fee_invoicing.py`): a schedule due more than a week out does
NOT get its `FeeRecord`s the moment it's created - a fee due in two months
shouldn't materialize immediately. Two automatic paths, both respecting the
window:
1. `POST /admin/fees/schedules` calls `run_monthly_invoicing(...,
   generate_only_due_within_days=7)` synchronously right after creating the
   schedule - so a schedule due soon gets its records immediately, one due far out
   doesn't (yet).
2. `app/scheduler.py` also runs the same gated call **nightly** (02:45 UTC) for
   every active school/year - changed from monthly this session, since a monthly
   cadence left a mid-month-due fee un-marked-overdue (and un-reminded) for weeks.
   This is also what eventually generates a far-out schedule's records once its
   due date enters the 7-day window, with zero admin action needed.

Two manual, **ungated** overrides exist for "I don't want to wait":
- `POST /admin/fees/schedules/{id}/generate` - one schedule, right now, regardless
  of due date (the "Generate now" button on that schedule's own card).
- `POST /admin/fees/invoicing/run` - every schedule in the school+year, right now
  (the bulk button - mainly for backfilling students enrolled after their class's
  schedule already existed).

All of the above are idempotent - re-running never creates duplicate `FeeRecord`s
(`UniqueConstraint`), and reminders never re-fire once sent (tier-by-index
tracking, see `fee_reminder_engine.py`), so calling any combination of these
repeatedly is always safe.

**Reminder cadence, per playbook's "heuristic engine":** **1**/7/14/30 days overdue,
escalating to `urgent` severity at 30 (matching the alert feed's own threshold) -
round numbers, not calibrated against real payment-behavior data.
`FeeReminder.sent_at` stays null: checked, no email-sending infrastructure exists
anywhere in this repo (same finding as Command Center's briefing email) - a row here
means "the system determined a reminder was due," not "an email was delivered."

**⚠️ A PART PAYMENT NO LONGER SILENCES A DEBT — behaviour change.** `POST /admin/fees/
records/{id}/payment` flips a record's status from `overdue` to `partial` as soon as any
money is recorded, and both this endpoint's scope and the Command Center's `fee_overdue`
alert source used to filter on `status == "overdue"` **independently**. So paying ₹1 of
a ₹350 fee removed it from reminders *and* from the alert feed, while ₹349 stayed unpaid
and the due date stayed weeks in the past. Paying part of a debt made the school stop
chasing it.

Both now share one predicate, `models/fees.py::has_outstanding_balance` — *not settled,
amount_paid < amount_due, and past due*. `paid` is the only settled status. Consequences:
- **`overdue_only=true` (the default) now includes partially-paid past-due fees.** Its
  meaning changed from "status is overdue" to "still owed and late".
- **Reminder priority now comes from the tier severity**, not from `record.status`. It
  was `urgent if status == "overdue"`, so a part payment downgraded a 30-days-late
  reminder to `normal` — the escalated tier fired but arrived quietly.
- The reminder body quotes the **remainder** and names what was already received:
  `"Term 1 Tuition: 4400.00 due 2026-07-18 (remaining after 100.00 already paid)"`.
- The alert title becomes `"Partly paid fee overdue"` and the message appends
  `"(100.0 of 4500.0 paid)"`.

**The 1-day tier was added later, and it fixed a real contradiction.** With 7/14/30,
`fee_records.status` and the cadence engine disagreed about the word "overdue": the
invoicing job flips a record to `overdue` the moment its `due_date` passes, so the fee
list showed ten red overdue cards while `POST /admin/fees/reminders` returned
`sent_count: 0` - both correct, and indistinguishable from a broken button. Anything
the UI calls overdue now earns at least one notice.

⚠️ **Never rename an existing tier's `cadence_reason` without a data migration.** Those
strings are persisted in `fee_reminders.cadence_reason` and matched back against
`REMINDER_TIERS` to decide what has already fired. A rename orphans every historical
row - it stops resolving to a tier index, `highest_sent_index` falls back to `-1`, and
a reminder that already went out fires again. That's why the labels read oddly ("7 days
overdue - **first** reminder" now sits *after* the day-1 notice): the strings were left
untouched on purpose. Adding a tier at index 0 is safe, because eligibility requires
`i > highest_sent_index`, so a record that already had the 7-day reminder can never
receive the day-1 notice retroactively. Both properties have tests.

#### `GET /admin/fees/reminders/preview`
Dry run: what triggering reminders with these filters would do, and **why it might do
nothing**. Read-only - writes no `FeeReminder` rows, sends no notifications. Shares the
same scope query and the same `determine_reminder()` call as the POST, so `due_now`
always equals the `sent_count` the POST would return.
- **Roles:** admin, principal (school-scoped through `fee_records → users.school_id`)
- **Query:** `?class_id=&overdue_only=` (defaults to `overdue_only=true`)
- **Response:**
```json
{
  "in_scope": 28, "due_now": 10,
  "by_tier": [ { "cadence_reason": "due date passed - first notice", "severity": "normal", "count": 10 } ],
  "not_yet_due": 18, "waiting_for_next_tier": 0, "fully_escalated": 0,
  "next_due_date": "2026-08-18", "next_due_count": 16
}
```
- **`in_scope`** counts records matching the *status* filter, before the day-tier gate -
  the gap between it and `due_now` is the thing that used to be invisible.
- **`not_yet_due`** is records due today or later. They can never fire today whatever
  the scope says, which is why widening scope past `overdue` looks like it should help
  and doesn't - the UI now says so explicitly.
- **`next_due_date`** is the earliest date any in-scope record next becomes eligible,
  with `next_due_count` sharing that date. Turns "0 reminders" into "0 today, 16 tomorrow".
- **`fully_escalated`** has had every tier; nothing further will ever fire for it. The
  record still surfaces as a Command Center `fee_overdue` alert - stopping reminders is
  not the same as stopping tracking.

#### `POST /admin/fees/schedules`
Create a fee schedule. Immediately generates this school+year's `FeeRecord`s
afterward, but ONLY if `due_date` is within `AUTO_GENERATE_WINDOW_DAYS` (7) - see
"Generation is automatic, but gated by due date" above. Check the response's
`records_generated` to know which happened.
- **Roles:** admin, principal
- **Request:** `{ "school_id": 41, "class_id": 41, "academic_year": "2026-27", "fee_type": "tuition", "amount": 15000, "due_date": "2026-09-01" }`
- **Response:** the created schedule, including `id`/`created_at`/`records_generated`.
- **Errors:** `400` non-positive `amount` or empty `fee_type`; `404` unknown `class_id`.

#### `GET /admin/fees/schedules`
List fee schedules, **sorted ascending by due date** (soonest first).
- **Roles:** admin, principal
- **Query:** `?school_id=&academic_year=`
- **Response:** each item includes `records_generated: bool` - false means it's
  still waiting for the auto-generate window (or an explicit `.../generate` call).

#### `POST /admin/fees/schedules/{id}/generate`
The per-schedule manual override - generates THIS schedule's records right now,
regardless of due date. Scoped to the caller's own school.
- **Roles:** admin, principal
- **Response:** the schedule, with `records_generated` now `true`.
- **Errors:** `404` unknown schedule, or one belonging to another school.

#### `POST /admin/fees/invoicing/run`
The bulk manual override - generates EVERY schedule's records for the given
academic year in the caller's school, right now, regardless of due date (unlike
the automatic paths, unaffected by `AUTO_GENERATE_WINDOW_DAYS`). Also marks
past-due records overdue and logs reminders. Mainly useful for backfilling
students enrolled after their class's schedule already existed - nothing else
re-checks that until the next nightly run or an explicit call here.
Idempotent - re-running never creates duplicate `FeeRecord`s (same `UniqueConstraint`
the nightly job relies on). Scoped to `user.school_id` (not a body param) - always
the caller's own school.
- **Roles:** admin, principal
- **Request:** `{ "academic_year": "2026-27" }`
- **Response:** `{ "records_created": 10, "overdue_marked": 0, "reminders_sent": 0 }`

#### `POST /admin/fees/reminders`
Trigger a batch fee-reminder send - runs the cadence heuristic against matching
`FeeRecord`s and logs a `FeeReminder` for each that's due one.
- **Roles:** admin, principal
- **Request:** `{ "class_id": null, "overdue_only": true }`
- **Response:** `{ "sent_count": 24 }`

#### `GET /admin/fees/status`
Fetch fee status - **one shared endpoint across all 5 roles**, scoped differently per
caller, same pattern as `GET /risk/flagged`. Kept at this one path (superseding the
never-built `/parent/children/{student_id}/fees` stub this section previously
pointed to - that separate endpoint was never implemented; this is what actually
ships) rather than one variant per role, so admin/teacher/parent/student all read
from the same live data with no separate sync path to drift.
- **Roles:** admin, principal, teacher, parent, student
- **Query:** `?class_id=&student_id=&status=`
- **Scoping per role:**
  - admin/principal: every record in their own school. `class_id` filters by the
    record's `FeeSchedule.class_id` (which class the fee was raised for - not the
    student's current enrollment, so a fee stays under "Grade 8A" even if the
    student later transfers). `student_id` filters to one student.
  - teacher: only their own class(es) (`SchoolClass.class_teacher_id`). Passing a
    `class_id` they don't teach → `403`.
  - parent: `student_id` is **required** (`400` if omitted) and must be one of the
    caller's own linked children (`ParentStudent`) → `403` otherwise.
  - student: always their own records; `class_id`/`student_id` are ignored.
- **Response:**
```json
{ "items": [ { "student_id": 15, "fee_record_id": 9, "amount_due": 5000, "amount_paid": 0,
               "outstanding": 5000, "due_date": "2026-08-15", "status": "overdue", "fee_type": "tuition",
               "claim": { "id": 3, "status": "pending", "amount": 5000, "payment_method": "UPI",
                          "payment_reference": "UPI/428817263541", "submitted_at": "2026-08-17T10:00:00Z",
                          "rejection_reason": null, "has_proof": true } } ] }
```

**⚠️ `class_id` filters by ENROLLMENT, not by the schedule's class — behaviour change.**
It used to join through `FeeSchedule` and match `FeeSchedule.class_id == class_id`. But a
**school-wide** schedule has `class_id NULL` while still generating a `FeeRecord` for
every student in the school, so filtering to "Grade 1 - A" returned only fees whose
*schedule* was scoped to 1-A and silently hid every school-wide fee those same students
owed — an admin filtering to a class to chase its unpaid fees saw a fraction of them.
It also disagreed with the teacher branch, which has always filtered by enrollment. Both
now mean "the students enrolled in that class", which is the question a class filter
answers. `POST /admin/fees/reminders` and its preview take the same fix.

**`claim` and `outstanding` were added with the payment confirmation loop.** `status`
is the canonical `fee_records.status` and knows nothing about payment claims, so
without `claim` this endpoint contradicted `GET /parent/child/{id}/fees`: a fee a
parent had already reported paying still read plainly `"overdue"` here, and an admin
could fire a reminder chasing someone who was in fact waiting on the school. `claim`
is the open request against that fee, else the most recent closed one (so a rejection
stays visible to staff), or `null` if the parent never claimed. Batched into one query
for the whole list, not one per row.

#### `POST /admin/fees/records/{id}/payment`
Record a payment against a fee record, however it was collected (cash at the office,
bank transfer, etc.) - this only persists the outcome, not a real payment gateway.
Recomputes `status` (`partial` if `0 < amount_paid < amount_due`, `paid` if
`amount_paid >= amount_due`). Scoped to the caller's own school (via the record's
student) - previously unscoped, a real cross-tenant gap fixed this session.
- **Roles:** admin, principal
- **Request:** `{ "amount": 5000, "paid_at": null }`
- **Response:** `{ "fee_record_id": 9, "amount_paid": 5000, "amount_due": 5000, "status": "paid" }`
- **CLOSES AN OPEN PAYMENT CLAIM when this brings the fee to `paid`.** Confirm/reject
  are not the only things that can pay a fee: an admin recording the same payment here
  instead of through the review queue used to leave the claim `pending` forever, so
  `pending_count` never returned to zero and the dashboard badge could not be trusted.
  Now `services/fee_payments.py::close_open_claim_if_paid` marks it `confirmed`, stamps
  `reviewed_by`/`reviewed_at`, notifies the parent, and writes an audit row carrying
  `closed_indirectly: true` and `via: "record_payment"` so it never reads as a
  considered review. Fires only on `paid`, never `partial` - a part payment leaves a
  balance, so the claim for the remainder is still a live question.
- **Errors:** `400` non-positive `amount`; `404` unknown fee record, or one outside the caller's school.

#### `PATCH /admin/fees/records/{id}/mark-paid`
The class teacher's lightweight counterpart to `.../payment` above: a plain
paid/not-paid toggle rather than an amount-reconciliation tool - a class teacher
tracking "who in my class still owes the event fee" needs a checkbox, not to enter
partial payment amounts (that stays admin/principal-only, via the endpoint above).
`paid: true` sets `amount_paid = amount_due` and `status = "paid"`; `paid: false`
resets `amount_paid = 0` and recomputes `status` as `overdue`/`pending` from
`due_date`. Scoped to the teacher's own class (`SchoolClass.class_teacher_id`) -
marking a student outside it is `404`, not `403` (doesn't reveal the record exists).
- **Roles:** teacher
- **Request:** `{ "paid": true }`
- **Response:** same shape as `.../payment`'s.
- **DELIBERATELY DOES NOT close an open payment claim**, unlike `.../payment` above.
  Teachers are excluded from confirm/reject on purpose (that's the trust model), and
  auto-confirming from a teacher's toggle would hand them that authority through a side
  door. A fee a teacher marked paid while a claim is open is exactly the case a human
  should look at, so the claim stays `pending` and the queue shows it against an
  already-paid fee for an admin to close out in one click. There is a test pinning this.
- **Errors:** `404` if the fee record doesn't belong to a student in the caller's
  own class.

### Fee payment confirmation loop (parent claims → admin confirms)

**There is no payment gateway here, mocked or real, and that is the design.** Real
Indian schools collect fees by UPI, bank transfer or cash at the office and reconcile
against a bank statement by hand. So this models the actual operation: the parent pays
through their own bank, records the reference, an admin checks it and confirms, and
only that confirmation writes through to the canonical `fee_records` row.

Backed by `fee_payment_requests` (`backend/app/models/fees.py`, migration
`6b10048f8738`).

**A payment request is a CLAIM, never the source of truth.** `fee_records.status`
stays canonical. Two consequences that are load-bearing:

- **`POST /admin/fees/reminders` keeps firing while a request is pending** - it reads
  `FeeRecord.status`, which a claim never touches. Reminders stop only once an admin
  confirms and the record reads `paid`. A parent asserting they paid cannot silence
  the school's own alert chain; that's the point, and there's a test pinning it.
- **A parent can never confirm their own request.** Confirm/reject are
  `require_role("admin", "principal")`. This is the whole trust model of the feature.

**One open request per fee** is enforced by a partial unique index
(`uq_fee_payment_request_one_open` on `(fee_record_id) WHERE status = 'pending'`), not
just a route pre-check - two concurrent submits would both pass a SELECT-then-INSERT
check. It is partial so a *rejected* request can be resubmitted; a plain unique
constraint would make a rejection a permanent dead end.

#### `GET /parent/child/{student_id}/fees`
The parent's fee list for one linked child, with a **derived** status that folds in any
open claim. Supersedes the never-built `/parent/children/{student_id}/fees` stub in
Person C's section.
- **Roles:** parent (via `assert_parent_linked`), plus admin/principal/teacher for support
- **Response:**
```json
{
  "student_id": 21546, "student_name": "Diya Kumar",
  "items": [
    { "fee_record_id": 1742, "fee_type": "Term 1 Tuition", "amount_due": 4500.0,
      "amount_paid": 0.0, "outstanding": 4500.0, "due_date": "2026-07-26",
      "record_status": "overdue", "derived_status": "payment_pending",
      "request": { "id": 3, "amount": 4500.0, "payment_method": "UPI",
                   "payment_reference": "UPI/428817263541", "status": "pending",
                   "submitted_at": "2026-08-17T10:00:00Z", "rejection_reason": null,
                   "has_proof": true } }
  ]
}
```
- **`derived_status`** is one of `unpaid` / `partially_paid` / `payment_pending` / `paid`
  / `rejected`, in this precedence (most actionable first):
  - `paid` — `record_status == "paid"` **or** `amount_paid >= amount_due`. The **only**
    settled state: a fee is settled when the school has the whole amount, never merely
    because some of it arrived.
  - `payment_pending` — an open (`pending`) request row exists. Outranks
    `partially_paid`: "awaiting confirmation" is what the parent needs first.
  - `rejected` — no open request, and the most recent request was rejected. Carries
    `request.rejection_reason` so the parent can act on it and resubmit. Also outranks
    `partially_paid` — a declined submission matters more than the balance.
  - `partially_paid` — some money recorded, not all of it. **Added because `unpaid` was
    actively misleading:** a ₹300 fee with ₹200 recorded read exactly like one with
    nothing paid. Renders as "Partly paid" in amber, keeps the "I've paid" button (the
    remaining balance is exactly what still needs reporting), and shows
    "₹100 still to pay — ₹200 of ₹300 received".
  - `unpaid` — nothing recorded and no claim.
- **Anything short of the full amount stays visible in every portal until settled.** A
  part payment reduces what is owed; it never removes the obligation from view.
- **`request`** is the single most relevant request (the open one if any, else the
  latest by `submitted_at`), or `null` if the parent has never claimed against this fee.
  `has_proof` is a boolean rather than the path - the object path is private and a
  parent has no read route for it.
- **Errors:** `400` non-parent role without a resolvable link; `403` parent not linked to `student_id`.

#### `POST /parent/child/{student_id}/fees/{fee_record_id}/payment-request`
Raise a claim that this fee has been paid outside the system. **`multipart/form-data`,**
because of the optional proof photo.
- **Roles:** parent (linked to `student_id` only)
- **Form fields:** `payment_method` (UPI | Bank Transfer | Cash | Other), `payment_reference`, `amount`, optional `proof_file`
- **Response:** the created request, same shape as `request` above plus `fee_record_id`.
- **Validates, in this order:** parent is linked to the student → the fee record
  belongs to that student → the record isn't already `paid` → no `pending` request
  already exists → `amount > 0` → `amount <= outstanding balance`.
- **`amount` may be less than the outstanding balance** - part payments are normal and
  land the record on `partial` when confirmed. It may not exceed it.
- **`proof_file`** is stored in the **private `payment-proofs` bucket**, not the
  `resources` bucket: `resources` is RAG source material that `POST /bots/reindex`
  reads back and re-chunks, so a fee receipt in there would become bot-retrievable.
  `proof_url` holds the object path, and the only read route is the admin one below.
- **On success, notifies every admin and principal in the student's school** via
  `dispatch_bulk`, `source_type="fee_payment_request"`, title naming parent, child and
  amount. (Note for demo: school 5707 has exactly one admin and no principal, so this
  is legitimately one row.)
- **Errors:** `400` bad method, non-positive amount, amount over the outstanding balance, record already paid, or a pending request already exists; `403` not linked; `404` fee record not found for this student; `502` proof upload failed.

**FRONTEND SHAPE:** the review queue is a **tab on the Fees page**
(`/{role}/fees?tab=requests`), not a separate screen - a claim is a fee record awaiting
a decision, so the queue and the fee Status list are two views of one row, and keeping
them on separate screens is what let them drift out of sync twice. `/{role}/fee-payment-requests`
still resolves, as a redirect to that tab, because the dashboard tile, the sidebar
badge and the `fee_payment_request` notifications all point at it.

#### `GET /admin/fee-payment-requests?status=`
The review queue. **Explicitly scoped to the caller's own school** through
`fee_records → users.school_id` (`fee_payment_requests` has no `school_id` of its own),
the same bug class already fixed in `fees.py`, `admissions.py`, `approvals.py` and
`risk.py`.
- **Roles:** admin, principal
- **Query:** `?status=` — `pending` | `confirmed` | `rejected` | omitted for all
- **Response:**
```json
{ "items": [
  { "id": 3, "fee_record_id": 1742, "student_id": 21546, "student_name": "Diya Kumar",
    "class_name": "Grade 3 - A", "parent_id": 21565, "parent_name": "Rohan Kumar",
    "fee_type": "Term 1 Tuition", "amount": 4500.0, "amount_due": 4500.0,
    "amount_paid": 0.0, "outstanding": 4500.0, "payment_method": "UPI",
    "payment_reference": "UPI/428817263541", "has_proof": true, "status": "pending",
    "submitted_at": "2026-08-17T10:00:00Z", "reviewed_by_name": null,
    "reviewed_at": null, "rejection_reason": null }
], "pending_count": 1 }
```
- **`pending_count`** is the school's total pending count **ignoring the `status`
  filter**, so the admin dashboard badge and the queue can share one request.
- Ordered pending-first, then newest `submitted_at` first.

#### `GET /admin/fee-payment-requests/{id}/proof`
Streams the stored proof image back. Exists because `proof_url` is a path in a private
bucket - there is no public URL to link to.
- **Roles:** admin, principal (own school only)
- **Response:** the raw bytes, `Content-Type` from the stored object.
- **Errors:** `404` unknown id, outside the caller's school, or no proof attached; `502` storage read failed.

#### `PUT /admin/fee-payment-requests/{id}/confirm`
Approve a claim and **write through to the canonical fee record.**
- **Roles:** admin, principal (own school only)
- **Request:** `{}` (no body fields — the amount is the one the parent claimed)
- **Response:** `{ "request": {...}, "fee_record": { "fee_record_id": 1742, "amount_paid": 4500.0, "amount_due": 4500.0, "status": "paid" } }`
- **Reuses the exact `record_payment` arithmetic** rather than duplicating it: that
  logic was inline in the handler and is now
  `app/services/fee_payments.py::apply_payment_to_record`, which both this and
  `POST /admin/fees/records/{id}/payment` call. The amount/status derivation exists in
  one place only.
- Sets `status="confirmed"`, `reviewed_by`, `reviewed_at`. Notifies the submitting
  parent (`source_type="fee_payment_confirmed"`). Writes **two** audit rows, because
  two entities changed: `record_payment` on `fee_records` (from the shared service) and
  `confirm_fee_payment_request` on `fee_payment_requests`.
- **Errors:** `400` request is not `pending`; `404` unknown id or outside the caller's school.

#### `PUT /admin/fee-payment-requests/{id}/reject`
Decline a claim. The fee record is **not** touched, so it stays overdue and keeps
attracting reminders.
- **Roles:** admin, principal (own school only)
- **Request:** `{ "rejection_reason": "No matching UPI credit on the 14 Aug statement" }` — **required, non-blank**
- **Response:** the updated request.
- Notifies the parent (`source_type="fee_payment_rejected"`) quoting the reason. Audit
  row `reject_fee_payment_request` on `fee_payment_requests`.
- The parent may then submit a fresh request for the same fee - permitted precisely
  because the uniqueness index is partial on `status = 'pending'`.
- **Errors:** `400` blank/missing reason, or request is not `pending`; `404` unknown id or outside the caller's school.

### Admissions

Backed by `backend/app/models/admissions.py` (`AdmissionApplication`) and
`backend/app/services/admissions_rules.py` (state machine + eligibility + section
assignment). `AdmissionApplication` carries `school_id`/`academic_year`/
`submitted_by` beyond the original stub's field list - necessary, not decorative:
eligibility checking ("is `grade_applied` offered by the school") is meaningless
without knowing which school/year to check against, and `submitted_by` is the real
user id behind `PendingApproval.requested_by` once registered below (the applicant
has no user row of their own).

**`grade_applied` is a grade LEVEL, not a section name - a real bug fix.** Originally
stored (and validated against) a specific `SchoolClass.name` (e.g. `"Grade 3 - A"`) -
found live: this asked an applicant/admin to already know which exact section they'd
end up in before applying, which no real admission process works like. Now a
stringified `SchoolClass.grade_level` (e.g. `"3"`, `"-2"` for LKG/`"-1"` for
UKG/`"-3"` for Nursery - see that column's own docstring for the negative-int
convention), checked against every grade level offered by at least one real ACTIVE
section for the target academic year. **Which specific section** is a separate
concern, resolved automatically only at acceptance time (see below) - never supplied
by the caller.

**State machine - legal transitions only:**
```
submitted    -> under_review, rejected
under_review -> accepted, rejected
accepted, rejected -> (terminal - no further transitions)
```
`submitted -> accepted` directly is explicitly illegal (must pass through
`under_review`); `PATCH` rejects illegal transitions with `400` and a clear reason
rather than silently allowing them. **Rejecting requires a real, non-empty
`decision_justification`** - no reason, no reject (accepting has no such
requirement - the pipeline below succeeding is itself the affirmative justification).

**Registered as the 2nd real source in `approval_aggregator.APPROVAL_SOURCES`** (up
from 1/7 last session, now 2/8) - but only for `status="under_review"`, not
`"submitted"`: a freshly-submitted application is pending an initial triage step
(this `PATCH` endpoint, moved to `under_review`), not yet at the binary approve/
reject decision point `GET /admin/approvals` / `POST /admin/approvals/{id}/decision`
offer. See `services/approval_aggregator.py`'s module docstring for the full
reasoning.

**Accepting is a REAL, fully automatic pipeline now - not stubbed, not manual.**
Previously required the caller to already have an existing `student_user_id` (this
repo genuinely had no account-creation flow anywhere when that was written - true
at the time, stale the moment `routers/students.py::create_student` and
`routers/parents.py::create_parent` were built in a later session and never wired
back into this flow; found live). `PATCH .../accepted` (and the equivalent unified
`POST /admin/approvals/{id}/decision`) now, in order:
1. **Auto-assigns the least-filled real active section** at the requested
   `grade_level` with room (comparing real current primary-enrollment headcount
   against `Room.capacity` via the section's `home_room_id`, or a default of 30 if
   none is set) - `400` with a specific reason (`"No available seats in Grade 3 for
   2026-27 - all sections full"`) if none have room; never silently overfills, never
   invents a new section.
2. **Creates a real, genuinely login-capable student account** (Supabase Auth +
   local `User` row, `role=student`) - a brand-new applicant always needs one. Since
   nothing on an admission form captures the future student's own email (correctly -
   a new LKG applicant wouldn't have one), a synthetic-but-unique one is generated
   (`<slug>.<application_id>@eduops-student.local`) together with a real random
   password - genuinely real credentials, just no email-sending infrastructure
   exists anywhere in this repo to deliver that password to anyone (same honest
   limitation as `FeeReminder.sent_at` staying null elsewhere).
3. **Resolves `guardian_email`** to an existing real parent account (a returning
   family's second child) or creates a new one - checked and validated BEFORE any
   real account is created, so a guardian-email conflict (the email already belongs
   to a real non-parent account) never leaves an orphaned Supabase Auth account
   behind.
4. **Links them via a real `ParentStudent` row.**
5. **Enrolls** the new student in the assigned section (`enroll_student_primary`).

Every check that can still fail (transition legality, reject reason, `grade_applied`
parses as a real int, a section has room, guardian-email conflict) runs BEFORE any
mutation - the application's own `status`/`decided_by`/`decided_at` is only set once
none of those can fail anymore, so a failed accept (e.g. no seats available) never
leaves the application half-decided.

#### Two ways a student gets an `Enrollment` - both real, neither a duplicate
Two genuinely different real-world moments create the same `Enrollment` row, and
this API has one endpoint for each rather than overloading one:
- **A NEW applicant, going forward**: `POST /admin/admissions/applications` →
  triage (`under_review`) → `PATCH .../accepted`. The full automatic pipeline above
  creates the student account and enrolls them - no existing account needed.
- **Onboarding a school's EXISTING roster directly** (e.g. a founding admin adding
  the 30 students already enrolled at their school, with no "application" to
  process): `POST /admin/students` (below) - creates the account AND optionally
  enrolls in one call, no admissions workflow involved.

Both call the exact same underlying `enroll_student_primary()` function
(`routers/admissions.py`) for the actual `Enrollment` row - not duplicated logic,
just two real entry points for two real situations.

### Roster Onboarding (Student & Parent accounts)

**New this session** - closes the gap the admissions flow's own docstring used to
name explicitly ("this repo has no account-creation flow anywhere"). Same real
Supabase-Auth-account-creation mechanism as `POST /admin/teachers`
(`services/supabase_admin.py`'s `create_auth_account`), for the two remaining roles
that had no creation path at all.

#### `POST /admin/students`
- **Roles:** admin, principal
- **Request:** `{ "school_id": 41, "email": "priya@example.com", "password": "...", "full_name": "Priya Sharma", "class_id": 12 }` - `class_id` is optional; when given, the student is immediately primary-enrolled (same mechanism as the admissions accept flow - see above).
- **Response:** `{ "id": 501, "email": "priya@example.com", "full_name": "Priya Sharma", "school_id": 41, "is_active": true, "class_id": 12 }`
- **Errors:** `400` unknown `school_id`/`class_id`; `409` email already registered (locally or in Supabase Auth).

#### `POST /admin/parents`
- **Roles:** admin, principal
- **Request:** `{ "school_id": 41, "email": "guardian@example.com", "password": "...", "full_name": "Rajesh Sharma", "phone": "9876543210", "student_ids": [501, 502] }` - `student_ids` are real, already-created students (via `POST /admin/students` or otherwise) to link via `ParentStudent` - the same table `GET /parent/children` reads from. Supports linking more than one child (multi-guardian, multi-child families both work - `ParentStudent` has no uniqueness constraint on either side). `phone` is optional - a real gap found live: School Management's Parents tab had no contact number for a guardian at all (`AdmissionApplication.guardian_phone` existed but belongs to the application, never carried into the parent's own account - see that field's own note above).
- **Response:** `{ "id": 601, "email": "guardian@example.com", "full_name": "Rajesh Sharma", "phone": "9876543210", "school_id": 41, "is_active": true, "student_ids": [501, 502] }`
- **Errors:** `400` unknown `school_id` or any `student_id` (must be a real user with role=student); `409` email already registered.

### Ongoing roster management (Students & Parents) - new this session

**Closes the gap the "School Management" admin page build found**: `routers/students.py`/`routers/parents.py` had CREATE only - no way to list, view, edit, or deactivate an existing student/parent after onboarding, unlike Teacher (`routers/teachers.py`) and School/Class/Subject/Room (`master_data.py`), which already had the full shape. These new endpoints follow the exact same established pattern (soft-delete via `is_active`, `?include_inactive=true` on list, clean `400`/`404` on bad ids, admin/principal only) rather than inventing a new one.

#### `GET /admin/students`
- **Roles:** admin, principal
- **Query:** `?school_id=` (required) `&include_inactive=` (default `false`)
- **Response:** `[ { "id": 501, "email": "priya@example.com", "full_name": "Priya Sharma", "school_id": 41, "is_active": true, "class_id": 12 } ]`

#### `GET /admin/students/{id}`
- **Roles:** admin, principal
- **Response:** same shape as one list item.
- **Errors:** `404` unknown id, or a real id that isn't a student (e.g. a teacher's id).

#### `PUT /admin/students/{id}`
- **Roles:** admin, principal
- **Request:** `{ "full_name": "Priya A. Sharma", "class_id": 15 }` - both optional, partial update (only sent fields change).
- **`class_id` is a real class CHANGE, not an add** - unlike `enroll_student_primary()`'s additive-only semantics (used by the admissions accept flow and this student's own creation, neither of which ever needs to move a student OUT of a class), this endpoint first removes the student's existing primary enrollment row, then creates the new one. A student is never left primary-enrolled in two classes at once.
- **Response:** the updated student, same shape as `GET`.
- **Errors:** `400` unknown `class_id`; `404` unknown student id.

#### `PUT /admin/students/{id}/deactivate` / `PUT /admin/students/{id}/reactivate`
- **Roles:** admin, principal
- Soft-delete only, same as every other master-data entity - a deactivated student stops appearing in `GET /reference/lookup` and in this list's default (active-only) view.

#### `GET /admin/parents`
- **Roles:** admin, principal
- **Query:** `?school_id=` (required) `&include_inactive=` (default `false`)
- **Response:** `[ { "id": 601, "email": "guardian@example.com", "full_name": "Rajesh Sharma", "phone": "9876543210", "school_id": 41, "is_active": true, "student_ids": [501, 502] } ]`

#### `GET /admin/parents/{id}`
- **Roles:** admin, principal
- **Response:** same shape as one list item.
- **Errors:** `404` unknown id, or a real id that isn't a parent.

#### `PUT /admin/parents/{id}`
- **Roles:** admin, principal
- **Request:** `{ "full_name": "Rajesh K. Sharma", "phone": "9123456789" }` - both optional, partial update (only sent fields change). Linked children are managed via the add/remove sub-resource endpoints below, same idempotent one-at-a-time pattern as `teachers.py`'s subject qualifications - not a single big PUT that replaces the whole list.
- **Response:** the updated parent, same shape as `GET`.
- **Errors:** `404` unknown parent id.

#### `POST /admin/parents/{id}/children?student_id=` / `DELETE /admin/parents/{id}/children/{student_id}`
- **Roles:** admin, principal
- Idempotent add/remove of ONE linked child - adding a parent's 3rd child never requires resending the other 2. `student_id` must be a real user with `role=student`.
- **Response:** the parent, same shape as `GET`.
- **Errors:** `400` unknown/non-student `student_id` (add only); `404` unknown parent id.

#### `PUT /admin/parents/{id}/deactivate` / `PUT /admin/parents/{id}/reactivate`
- **Roles:** admin, principal
- Same soft-delete pattern as everywhere else.

#### `POST /admin/admissions/applications`
Submit a new admission application (typically entered by office staff, possibly pre-filled via OCR).
- **Roles:** admin
- **Request:**
```json
{ "school_id": 41, "academic_year": "2026-27", "applicant_name": "Jane Doe", "dob": "2015-04-01", "guardian_email": "guardian@example.com", "guardian_name": "Rajesh Sharma", "guardian_phone": "9876543210", "grade_applied": "6", "ocr_document_ids": [1] }
```
  `grade_applied` is a stringified grade LEVEL (`SchoolClass.grade_level`), not a section
  name - `"6"` means "Grade 6, any section," `"-2"`/`"-1"`/`"-3"` for LKG/UKG/Nursery.
  `ocr_document_ids` is optional - populated when the application was created via the
  OCR routing pre-fill flow (`documents.py`'s admissions routing), empty otherwise.
  `guardian_name`/`guardian_phone` are optional (not every submission path has them -
  the OCR routing pre-fill includes them when the admission_form extracted them, the
  Submit tab's own form asks for them directly, but neither is forced) - `guardian_name`
  becomes the real `full_name` on the guardian's account once this application is
  accepted (a real gap found live: parent accounts created with `full_name: null`
  because this never reached that far before).
- **Response:** the created application (`id`, `status: "submitted"`, etc).
- **Errors:** `400` empty `applicant_name`, or `grade_applied` isn't offered by any real
  active section at this school for that academic_year (message lists what IS offered,
  using friendly labels, e.g. `"Grade 13 is not offered by this school for this
  academic year (offered: ['LKG', 'UKG', 'Grade 1'])"`).

#### `GET /admin/admissions/applications`
List/search admission applications.
- **Roles:** admin, principal
- **Query:** `?status=&page=&page_size=` (`page_size` defaults to 20)
- **Response:**
```json
{ "items": [ { "id": 3, "applicant_name": "Jane Doe", "grade_applied": "6", "status": "under_review" } ], "total": 1, "page": 1, "page_size": 20 }
```

#### `GET /admin/admissions/applications/{id}`
Single-application detail fetch - backs the admin's full applicant detail view (was
previously nonexistent; clicking an application card did nothing).
- **Roles:** admin, principal
- **Response:** the full application row, including `ocr_document_ids`,
  `decision_justification`, `enrolled_student_id`, `decided_by`, `decided_at`, plus a
  **`documents` array** - full per-document detail (`document_type`,
  `extracted_fields`, `entities` with confidence flags, `routing`, etc. - the exact
  same shape `GET /admin/ocr/documents/{id}` returns for one document) for EVERY id
  in `ocr_document_ids`, not just their bare ids. A real admission process involves
  multiple supporting documents per applicant (admission form + marksheet + ID
  proof) - this lets the detail view show all of them together without a
  round-trip per document. Any id that no longer resolves to a real document in
  this school (e.g. deleted after linking) is silently skipped, never a 500.
- **Errors:** `404` unknown application id.

#### `POST /admin/admissions/applications/{id}/documents`
Attach an already-uploaded OCR document to an existing application - the missing
link for marksheet/id_proof, which have no routing handler of their own (see
`ocr_routing.py`'s module docstring) and were otherwise permanently orphaned
regardless of intent. `admission_form` still gets its first document linked via the
routing pre-fill at submission time (`POST /admin/admissions/applications`'s
`ocr_document_ids`) - this endpoint is for every document after the first, of any
type, attached after the fact.
- **Roles:** admin, principal
- **Request:** `{ "document_id": 42 }`
- **Response:** same enriched shape as `GET /admin/admissions/applications/{id}`
  above (the application plus every linked document's full detail) - so the
  frontend can refresh its whole detail view from this one response.
- **Idempotent:** attaching a `document_id` already present in `ocr_document_ids`
  is a no-op (200, no duplicate, no audit log entry) - not an error.
- **No restriction on application status** - attaching is record-keeping (evidence
  for a decision), not a decision itself, unlike accept/reject which the state
  machine gates. A late-arriving ID proof for an already-accepted student can still
  be attached.
- **Errors:** `404` unknown application id, or an id belonging to another school
  (same-shape 404 either way - doesn't leak which); `404` unknown `document_id`, or
  a document belonging to a different school than the application (reuses
  `GET /admin/ocr/documents/{id}`'s own scoped lookup, not a second check).

#### `GET /admin/admissions/grade-levels`
Real grade levels offered by this school for this academic year - backs the
submission form's grade dropdown (previously free-text, which is how a section-name
value like `"Grade 3 - A"` could ever get typed in as `grade_applied` in the first
place).
- **Roles:** admin
- **Query:** `?school_id=&academic_year=` (both required)
- **Response:** `{ "items": [ { "grade_level": -2, "display": "LKG" }, { "grade_level": 1, "display": "Grade 1" } ] }`
  - only grade levels with at least one real ACTIVE section this academic year.

#### `PATCH /admin/admissions/applications/{id}`
Update an application's status via the state machine above.
- **Roles:** admin, principal
- **Request:** `{ "status": "accepted", "decision_justification": null }`
  - `decision_justification` is **required, non-empty** when `status: "rejected"` - no
    reason, no reject. Never required for `accepted`/`under_review`.
  - **No `student_user_id`/`class_id` anymore** - accepting is now a fully automatic
    pipeline (real section auto-assignment + real student account + real guardian
    resolution + real `Enrollment`) - see "Accepting is a REAL, fully automatic
    pipeline" above. Supplying them is simply ignored (not a validation error) since
    they're no longer part of the schema at all.
- **Response:**
```json
{ "id": 3, "status": "accepted", "enrollment_created": true, "assigned_class_id": 12, "enrolled_student_id": 501, "parent_user_id": 601, "parent_account_created": true }
```
  `assigned_class_id`/`enrolled_student_id`/`parent_user_id`/`parent_account_created`
  are all `null`/`false` for a reject (or for accept in the impossible case
  `enrollment_created` is false).
- **Errors:** `400` illegal state transition (message names the required intermediate
  step, e.g. "must pass through 'under_review' first"); `400` rejecting without a
  real `decision_justification`; `400` accepting when a real marksheet and id_proof
  aren't BOTH already linked (`REQUIRED_DOCUMENT_TYPES_FOR_ACCEPTANCE` - a real hard
  requirement, e.g. `"Cannot accept: missing required document(s) - id_proof.
  Attach them (Document OCR page) before accepting."` - names only the genuinely
  missing type(s), checked before every other accept-time check); `400` accepting
  when `grade_applied` doesn't parse as a real int (a pre-existing application from
  before this fix, still stored as a section name); `400` accepting when zero active
  sections at the requested grade level have room (`"No available seats in Grade 3
  for 2026-27 - all sections full"` - never silently overfills, never auto-creates a
  new section); `400` accepting when `guardian_email` already belongs to a real
  non-parent account; `404` unknown application id.
  Rejecting has NO document requirement - an application with zero linked documents
  can still be rejected (there's no reason to demand evidence for a decision not to
  admit someone).

#### `PATCH /admin/admissions/applications/{id}/details`
Corrects the application's OWN declared details after submission - genuinely
separate from `PUT /admin/ocr/documents/{id}/entities/{entity_id}` (correcting a
linked OCR document's extracted field), which never flows back into an application
already created from it. Found live: an admin corrected a document's
`applicant_name` and expected the application to update too - it doesn't, by
design (the application is the human-confirmed submitted record, not a live
mirror of one document's OCR state). This is the real, explicit, audited way to
fix a mistake in the application's own record instead.
- **Roles:** admin, principal
- **Request:** `{ "applicant_name": "Jane A. Doe" }` - partial update, every field
  optional (`applicant_name`, `dob`, `guardian_email`, `guardian_name`,
  `guardian_phone`); only supplied fields change.
- **Response:** the full updated application, same enriched shape as
  `GET /admin/admissions/applications/{id}` (includes `documents`).
- **Blocked once `status: "accepted"`** - a real student/parent account and
  `Enrollment` already exist based on these exact values by that point; editing
  them afterward would silently diverge the application's own record from the
  real accounts already created from it. Editing while
  `submitted`/`under_review`/`rejected` is fine - none of those states have
  created anything real from this data (or, for `rejected`, ever will).
- **Errors:** `400` empty `applicant_name`/`guardian_email` when supplied; `400`
  application is already `accepted`; `404` unknown application id, or a real id
  belonging to a different school.

### Exam management

The final Person A backend task group. School-wide, seated/invigilated exams
(playbook: "exam scheduling, seating allocation, invigilation management") -
checked `backend/app/models/` before building: no `exams`/quizzes concept existed
anywhere yet, no naming collision with Person B's (separate, not-yet-built) online
assessments. Backed by `backend/app/models/exams.py` and `backend/app/services/
exam_scheduler.py`; reuses `Room` from `models/timetable.py` rather than a second
room concept.

**Seating is a plain bin-fill, not a CP-SAT solve** - unlike timetable generation,
seating has no interesting constraint beyond "one seat per student, room capacity
respected," so it's a deterministic greedy fill rather than search machinery bought
for no benefit. **Invigilation is `substitute_solver.py`'s filter+rank shape
adapted, not timetable_solver's full CSP** - genuinely the same kind of problem
(assign a qualified/free teacher to a slot), with real differences: no subject-
qualification filter (any teacher can invigilate), a real TIME-RANGE overlap check
against `TimetableSlot` (an exam's `start_time`/`end_time` may span multiple regular
periods, so this isn't an exact-slot match), and an approved-`LeaveRequest` check
for the exam date. See `exam_scheduler.py`'s module docstring for the full reasoning.

**A gap the response surfaces directly, not silently:** if no eligible teacher
remains for a room, that room's `teacher_id` is `null` and its `room_id` appears in
`unassigned_rooms` - an honest, immediately-actionable result rather than a partial
schedule pretending to be complete.

**Registry integration considered, declined with reasoning:** evaluated whether an
unconfirmed `InvigilationAssignment` close to its exam date deserves a 9th
`alert_aggregator` source, the same escalation logic as `Substitution`. Declined:
every `InvigilationAssignment` this session creates already has a real teacher
assigned (`status="assigned"` by construction), and no confirm/decline endpoint was
built this session (not requested) - so `status` has no path to ever change, making
an "unconfirmed" alert perpetually true and not actionable via any click-through.
The real analogous gap (a room genuinely left uncovered) is surfaced directly and
synchronously in this session's own generation response above, at the point an
admin can immediately act on it, instead of routed through an async alert. See
`alert_aggregator.py`'s module docstring for the full reasoning.

#### `POST /admin/exams`
Create an exam for one class/section. **Not in the original stub** - added because
`POST /admin/exams/{id}/schedules` has nothing to generate a schedule for without an
`Exam` already existing. Flagged here, same pattern as every prior session's
necessary additions. `exam_type` (added this session) is validated against a fixed
preset list, not free text - `class_test`/`unit_test`/`mid_term`/`end_term` - since
(unlike `FeeSchedule.fee_type`) there's no real reason an admin needs an arbitrary
value here.
- **Roles:** admin, principal
- **Request:** `{ "school_id": 41, "subject_id": 40, "class_id": 41, "academic_year": "2026-27", "exam_type": "mid_term", "exam_date": "2026-08-26", "start_time": "09:00:00", "end_time": "11:00:00", "total_marks": 100 }` (`exam_type` optional)
- **Response:** the created exam, including `id`/`created_at`.
- **Errors:** `403` `school_id` doesn't match the caller's own school; `400` `end_time<=start_time`, or `exam_type` not one of the fixed presets; `404` unknown `subject_id`/`class_id`.

**Cross-tenant scoping fixed this session** - found live, against real data, during
this session's own walkthrough: an admin from one school could see (`GET /admin/
exams`), and could have generated/overwritten (`POST .../schedules`), another
school's real exam. None of `POST /admin/exams`, `POST .../bulk-by-grade`,
`GET /admin/exams`, `GET .../room-suggestions`, `POST .../schedules`, or
`GET /admin/exams/seating` (admin/principal/teacher branch) had any `school_id`
check before this - same class of gap fixed earlier this session in
`fees.py`/`master_data.py`, and in `timetable.py`/`admissions.py` in prior
sessions. All now scope to `user.school_id`; a mismatch is `403` on the two create
endpoints (client-supplied `school_id`, mirroring `timetable.py`'s
`_validate_generate_request`) and `404` everywhere an `exam_id` is resolved first
(doesn't reveal whether the id exists at all).

#### `POST /admin/exams/bulk-by-grade`
Grade-wide creation, added this session - creates one `Exam` per active section in
`grade_level` (same subject/date/time/type/marks for all), in a single call. A
separate endpoint rather than a mode on `POST /admin/exams`, so that endpoint's
original single-class contract stays exactly as every existing caller expects -
this only adds a new capability.
- **Roles:** admin, principal
- **Request:** `{ "school_id": 41, "subject_id": 40, "grade_level": 8, "academic_year": "2026-27", "exam_type": "unit_test", "exam_date": "2026-08-26", "start_time": "09:00:00", "end_time": "11:00:00" }`
- **Response:** `{ "created": [ { "id": 5, ... }, { "id": 6, ... } ] }` - one exam per active section found.
- **Errors:** same as `POST /admin/exams`, plus `404` if no active class matches `grade_level` for that school/year.

#### `GET /admin/exams`
**Not in the original stub - added because the frontend's exam management screen
had no real way to browse existing exams, only remember ids from its own session's
creates.** Real RBAC-scoped list, not admin-only: a teacher only sees exams for
`(class_id, subject_id)` pairs they actually teach (an active `TimetableSlot` for
that pair - a class's homeroom teacher is often a different person than who
teaches a given subject to it, same distinction syllabus tracking's scoping
already makes); a student only sees exams for their own primary-enrollment class,
same scoping as their seat-lookup.
- **Roles:** admin, principal, teacher, student
- **Query:** `?class_id=&subject_id=&academic_year=&page=&page_size=` (`page_size` defaults to 20)
- **Response:**
```json
{
  "items": [ { "id": 5, "subject_id": 40, "class_id": 41, "academic_year": "2026-27", "exam_type": "mid_term", "exam_date": "2026-08-26", "start_time": "09:00:00", "end_time": "11:00:00" } ],
  "total": 1, "page": 1, "page_size": 20
}
```

#### `GET /admin/exams/{id}/room-suggestions`
Added this session - "room selection must suggest the best one based on
availability." Excludes any room already booked (`ExamRoomAssignment`) for a
DIFFERENT exam whose date+time overlaps this one, then picks the smallest-waste
subset of what's left to seat this exam's real enrolled headcount (prefers one
room that fits everyone; falls back to combining rooms largest-first). A
suggestion, not a forced choice - every available room is returned too, so the
caller can override.
- **Roles:** admin, principal
- **Response:** `{ "exam_id": 5, "headcount": 28, "available_rooms": [ { "room_id": 5, "room_name": "Room 204", "capacity": 30 } ], "suggested_room_ids": [5] }`
- **Errors:** `404` unknown `exam_id`.

#### `POST /admin/exams/{id}/schedules`
Generate a complete seating chart + invigilation schedule for an exam - supersedes
any previous generation for this exam (not additive), same convention as
`POST /timetable/generate`. **Path changed from the original stub**
(`POST /admin/exams/seating/generate` with `exam_id` in the body) to put the id in
the path, matching every other `.../{id}/...` action endpoint in this codebase -
flagged, not silently changed.

**HITL preview/confirm, added this session:** `dry_run` (default `false`, so every
caller written before this session keeps its old immediate-persist behavior
unchanged) - when `true`, computes and returns the exact same seating/invigilator
result WITHOUT writing anything (`status: "preview"`); the admin reviews it, then
calls again with `dry_run: false` to actually persist (`status: "generated"`). The
frontend always does the two-step version now; the single-step (`dry_run` omitted)
path still exists for any other caller.
- **Roles:** admin, principal
- **Request:** `{ "rooms": [ { "room_id": 5, "capacity": 30 } ], "dry_run": true }`
- **Response:**
```json
{
  "exam_id": 5, "status": "generated",
  "seating": [ { "student_id": 15, "room_id": 5, "seat_no": 1 } ],
  "invigilators": [ { "room_id": 5, "teacher_id": 97 } ],
  "unassigned_rooms": []
}
```
(`status` is `"preview"` when `dry_run: true` was sent, `"generated"` otherwise.)
- **Errors:** `400` no `rooms` given; `404` unknown `exam_id` or `room_id`; `422` total room capacity is less than the class's enrolled student count.

**Invigilator assignment already accounted for real teacher availability** before
this session (excludes anyone with a genuinely overlapping `TimetableSlot`, anyone
on approved leave covering the exam date, never double-books one teacher across two
rooms of the SAME exam) - this session adds a **3-tier priority** among whoever
passes those hard filters:
1. **Preferred** - whoever normally has THIS exact class at this exact day/time
   slot (any subject). The natural first pick: that period is being replaced BY
   the exam, so they were already going to be with this class then. (This also
   fixes a bug: their own regular slot for this class used to be wrongly counted
   as a "conflict" and excluded them entirely - only a DIFFERENT class's
   overlapping slot is a real conflict now.)
2. **Normal** - anyone else free, ranked by current invigilation workload (fewer
   existing duties scores higher) - the original behavior, for anyone not in tier
   1 or 3.
3. **Deprioritized, last resort** - whoever normally teaches this exam's OWN
   subject to this class (e.g. the English teacher for an English exam) - used
   only if nobody from tier 1/2 is eligible, to avoid a subject teacher
   invigilating their own subject's test. Wins over tier 1 if a candidate is in
   both (their regular slot for this class happens to BE this subject) - the bias
   concern applies regardless of scheduling convenience.

The first non-empty tier is used entirely (workload-ranking only breaks ties
within it) - see `services/exam_scheduler.py`'s module docstring for the full
filter+rank walkthrough.

#### `GET /admin/exams/seating`
Fetch a generated seating plan. **Changed this session** two ways:
1. A student used to see only their own single row; now they see every seat in
   the SAME room they're actually placed in (per exam), so the frontend can
   render the real room layout with their own seat highlighted instead of an
   isolated seat. Any `student_id` a student passes is still ignored in favor of
   their own id (only decides whose room(s) to resolve, never lets them view a
   room they're not in).
2. Every item now also carries the exam's own details (`subject_name`,
   `exam_type`, `exam_date`, `class_name`) and that room's invigilator
   (`invigilator_teacher_id`/`invigilator_name`, both `null` if the room has none
   yet) - so a bare "Exam #5" is never the only thing shown, and looking up who's
   invigilating a given class no longer requires re-running generation.
- **Roles:** admin, principal, teacher, student
- **Query:** `?exam_id=&student_id=` (both optional - a student with neither set sees every room they're seated in, across every exam)
- **Response:**
```json
{
  "exam_id": 5,
  "items": [
    {
      "exam_id": 5, "student_id": 15, "room_id": 5, "room_name": "Room 204", "seat_no": 1,
      "subject_id": 40, "subject_name": "Math", "exam_type": "mid_term", "exam_date": "2026-08-26",
      "class_id": 41, "class_name": "Class 8A", "invigilator_teacher_id": 97, "invigilator_name": "T. Rao"
    }
  ]
}
```

#### `GET /admin/exams/invigilations/me`
Backend for the playbook's "invigilator self-lookup" frontend note - built even
though the frontend itself is deferred. Strictly self-scoped to the caller's own
`user.id` (a "self-lookup," not a general admin-queries-any-teacher endpoint).
- **Roles:** teacher, admin, principal
- **Response:**
```json
[ { "exam_id": 5, "room_id": 5, "room_name": "Room 204", "subject_id": 40, "subject_name": "Math", "class_id": 41, "class_name": "Class 8A", "exam_date": "2026-08-26", "start_time": "09:00:00", "end_time": "11:00:00", "status": "assigned" } ]
```

## Person B — Classroom & academics

_Owns: assignments, quizzes, gradebook, report cards, library, homework calendar._

This section is Person B's to extend — add/adjust endpoints here without touching
Person A/C's sections.

### Classroom stream

#### `GET /classroom/{class_id}/stream`
Fetch the classroom stream (posts + shared resources).
- **Roles:** teacher (own class), student (enrolled), parent (child's class), admin, principal
- **Query:** `?page=&page_size=`
- **Response:**
```json
{ "items": [ { "id": 1, "author_id": 7, "type": "post", "content": "Homework due Friday", "attachment_url": null, "created_at": "2026-08-09T06:00:00Z" } ], "total": 1, "page": 1, "page_size": 20 }
```

#### `POST /classroom/{class_id}/stream`
Create a stream post or shared resource.
- **Roles:** teacher
- **Request:** `{ "type": "post", "content": "Homework due Friday", "attachment_url": null }`
- **Response:** `{ "id": 1, "created_at": "2026-08-09T06:00:00Z" }`

### Assignments

#### `POST /classroom/{class_id}/assignments`
Create an assignment.
- **Roles:** teacher
- **Request:**
```json
{ "title": "Ch. 4 problems", "instructions": "...", "subject_id": 3, "due_at": "2026-08-15T23:59:00Z", "max_score": 20 }
```
- **Response:** `{ "id": 10, "created_at": "2026-08-09T06:00:00Z" }`

#### `GET /classroom/{class_id}/assignments`
List assignments for a class.
- **Roles:** teacher, student, parent, admin, principal
- **Response:**
```json
{ "items": [ { "id": 10, "title": "Ch. 4 problems", "due_at": "2026-08-15T23:59:00Z", "max_score": 20, "submitted": false } ] }
```

#### `POST /assignments/{id}/submissions`
Student submits work for an assignment.
- **Roles:** student
- **Request:** `{ "content": "...", "attachment_url": null }`
- **Response:** `{ "submission_id": 55, "status": "submitted", "submitted_at": "2026-08-14T09:00:00Z" }`

#### `POST /assignments/{id}/submissions/{submission_id}/grade`
Grade a student's submission.
- **Roles:** teacher
- **Request:** `{ "score": 18, "feedback": "Good work" }`
- **Response:** `{ "submission_id": 55, "score": 18, "graded_at": "2026-08-16T06:00:00Z" }`

### Quizzes

#### `POST /classroom/{class_id}/quizzes`
Create a quiz.
- **Roles:** teacher
- **Request:**
```json
{
  "title": "Unit 2 quiz",
  "subject_id": 3,
  "questions": [ { "text": "2+2=?", "options": ["3", "4", "5"], "correct_index": 1, "points": 5 } ],
  "opens_at": "2026-08-10T00:00:00Z",
  "closes_at": "2026-08-12T23:59:00Z"
}
```
- **Response:** `{ "id": 20 }`

#### `GET /classroom/{class_id}/quizzes/{id}`
Fetch a quiz. Student view omits `correct_index`; teacher/admin view includes it.
- **Roles:** teacher, student, admin, principal
- **Response:**
```json
{ "id": 20, "title": "Unit 2 quiz", "questions": [ { "text": "2+2=?", "options": ["3", "4", "5"] } ], "closes_at": "2026-08-12T23:59:00Z" }
```

#### `POST /quizzes/{id}/submit`
Submit quiz answers — auto-graded immediately.
- **Roles:** student
- **Request:** `{ "answers": [ { "question_index": 0, "selected_index": 1 } ] }`
- **Response:** `{ "submission_id": 61, "score": 5, "max_score": 5, "graded_at": "2026-08-11T10:00:00Z" }`

### Gradebook

#### `POST /gradebook/entries`
Record a grade entry.
- **Roles:** teacher
- **Request:**
```json
{ "student_id": 15, "subject_id": 3, "term": "2026-T1", "assessment_type": "quiz", "score": 18, "max_score": 20 }
```
- **Response:** `{ "id": 200, "created_at": "2026-08-09T06:00:00Z" }`

#### `GET /gradebook/{student_id}`
Fetch a student's gradebook entries.
- **Roles:** teacher, student (self), parent (own child), admin, principal
- **Query:** `?term=&subject_id=`
- **Response:**
```json
{ "items": [ { "id": 200, "subject_id": 3, "term": "2026-T1", "assessment_type": "quiz", "score": 18, "max_score": 20 } ] }
```

#### `GET /gradebook/{student_id}/term-average`
Fetch per-subject term averages.
- **Roles:** teacher, student (self), parent (own child), admin, principal
- **Query:** `?term=`
- **Response:**
```json
{ "term": "2026-T1", "subjects": [ { "subject_id": 3, "average": 17.5, "max_score": 20 } ] }
```

### Report cards

#### `POST /report-cards/generate`
Generate a report card for a student/term.
- **Roles:** teacher, admin, principal
- **Request:** `{ "student_id": 15, "term": "2026-T1" }`
- **Response:** `{ "id": 8, "status": "generated", "pdf_url": "https://.../report-cards/8.pdf" }`

#### `GET /report-cards/{student_id}`
List a student's generated report cards.
- **Roles:** student (self), parent (own child), teacher, admin, principal
- **Query:** `?term=`
- **Response:**
```json
{ "items": [ { "id": 8, "term": "2026-T1", "pdf_url": "https://.../report-cards/8.pdf", "generated_at": "2026-08-09T06:00:00Z" } ] }
```

### Digital library

#### `POST /library/issue`
Issue a book to a student.
- **Roles:** teacher, admin
- **Request:** `{ "book_id": 4, "student_id": 15, "due_date": "2026-08-23" }`
- **Response:** `{ "issue_id": 30, "issued_at": "2026-08-09T06:00:00Z", "due_date": "2026-08-23" }`

#### `POST /library/return/{issue_id}`
Mark a book as returned.
- **Roles:** teacher, admin
- **Response:** `{ "issue_id": 30, "returned_at": "2026-08-20T06:00:00Z", "late": false }`

#### `GET /library/books`
Search/browse the library catalog.
- **Roles:** any authenticated
- **Query:** `?q=&available=`
- **Response:**
```json
{ "items": [ { "id": 4, "title": "...", "author": "...", "copies_available": 2 } ], "total": 1 }
```

### Homework calendar

#### `GET /homework-calendar`
Fetch upcoming assignments/quizzes as calendar events.
- **Roles:** student (self), parent (own child), teacher, admin
- **Query:** `?class_id=&from=&to=`
- **Response:**
```json
{ "items": [ { "id": 10, "type": "assignment", "title": "Ch. 4 problems", "subject_id": 3, "due_at": "2026-08-15T23:59:00Z" } ] }
```

## Person C — Communication, RAG chatbots, parent portal, cross-cutting

_Owns: chat, notifications, announcements, multilingual, accessibility, offline
sync, search, the three RAG chatbots._

This section is Person C's to extend — add/adjust endpoints here without touching
Person A/B's sections.

### Teaching resources (RAG source documents)

The corpus the bots retrieve from. Uploaded files are **actually persisted** to
Supabase Storage (bucket `resources`) and the returned `file_url` is a real,
fetchable object path — deliberately unlike `documents.file_url` in Person A's OCR
flow, which is a fabricated descriptive string for an image that is discarded after
text extraction (see `routers/documents.py`). Do not copy that behaviour here.

> **SCOPED BY GRADE, NOT CLASS.** Resources and their `kb_chunks` are scoped to
> `(school_id, grade_level)`. Sections of a grade follow the same curriculum, so a
> Grade 3 handout is Grade 3 material — uploading it once per section was duplicated
> work and left 3-B unable to read 3-A's notes. This also aligns retrieval with Top
> Doubts, which already aggregates by `(school_id, grade_level, subject_id)`.
>
> **`school_id` is load-bearing.** `grade_level` is a plain integer, not an FK — grade
> 1 exists in every school — so filtering on grade alone would cross tenants. Both
> columns are always applied together.
>
> **Consequence:** a Grade 3 - A student can now retrieve material uploaded for Grade
> 3 - B. That is the intended widening, covered by
> `test_sibling_sections_of_a_grade_now_share_material`.

#### `POST /resources/upload`
Upload a teaching resource and ingest it into the vector store synchronously.
- **Roles:** teacher, admin, principal
- **Request:** `multipart/form-data` — `file`, `title`, `grade_level`, `subject_id` (optional)
- **Accepted types:** `.txt`, `.md`, **`.pdf`**. Max 20 MB.
  **PDF extraction is text-layer only** (`pypdf`) — it does **not** OCR. A scanned PDF
  whose pages are images extracts to nothing and returns `422` rather than being
  stored as an unretrievable resource. Tesseract exists in this codebase
  (`services/ocr_engine.py`) but serves the separate `documents` admin flow and is
  deliberately not bridged in.
- **Scoping:** a teacher may upload for a grade they actually teach (homeroom class or
  any grade they hold timetable slots for). Admin/principal may upload for any grade
  **in their own school**. `school_id` is taken from the caller's token and is not a
  request field, so targeting another tenant is structurally impossible rather than
  merely forbidden.
- **Ingestion is inline and synchronous**, following the `POST /admin/fees/schedules`
  precedent (which triggers invoicing directly rather than via a queue). The response
  is returned only after chunks are embedded and stored, so `chunk_count` is truthful.
- **Response:**
```json
{ "id": 27, "title": "FECU101 — Science", "school_id": 6318, "grade_level": 1, "subject_id": 3802,
  "file_url": "6318/grade-1/27-fecu101-science.pdf", "mime_type": "application/pdf",
  "indexed_at": "2026-08-17T04:10:00Z", "chunk_count": 7 }
```
- **Errors:** `400` no class exists at that grade in the caller's school (the resource
  would be unreachable); `403` teacher uploading for a grade they don't teach; `413`
  over 20 MB; `415` unsupported file type; `422` no readable text extracted (scanned
  PDF); `502` storage or embedding failure. Nothing is left half-written — the
  `resources` row is only committed once ingestion succeeds.

#### `GET /resources`
List teaching resources, role-scoped.
- **Roles:** any authenticated
- **Query:** `?grade_level=&subject_id=` (both optional)
- **Scoping:** student → their own enrolled grade; teacher → grades they teach;
  admin/principal → their own school. `school_id` is applied for **every** role. A
  `grade_level` outside the caller's scope is `403`, never silently empty.
- **Response:** `{ "items": [ { "id": 27, "title": "...", "school_id": 6318, "grade_level": 1, "subject_id": 3802, "mime_type": "application/pdf", "indexed_at": "2026-08-17T04:10:00Z", "created_at": "2026-08-17T04:09:58Z" } ] }`

### RAG chatbots

**This section replaces the original `/chat/{student,teacher,parent}-bot` stub.**
Same reconcile-in-place treatment as the notification-center stub above: the built
shape differs from the proposal in several ways that matter, so the doc now describes
what is live rather than what was once proposed.

| Original stub | As built | Why |
| --- | --- | --- |
| `POST /chat/student-bot` | `POST /bots/student/ask` | One `/bots` namespace covering ask + reindex + insights, rather than three sibling `/chat/*` paths that would collide with the class-chat stubs below. |
| `{ "message": ... }` | `{ "query": ... }` | Matches the retrieval vocabulary used throughout (`embed_query`, `RETRIEVAL_QUERY`). |
| — | `class_id` **required** | **`class_id` is the security boundary.** See the callout below. |
| — | `subject_id` optional | Narrows retrieval when a student is asking within one subject. |
| `{ "reply": ... }` | `{ "answer": ... }` | — |
| `sources: [{title, url}]` | `citations: [{chunk_id, source_id, title, snippet}]` | A `url` to an object-storage path is useless to a student; a text `snippet` plus the `chunk_id` that produced it is the visible proof of grounding. |
| `conversation_id` | **not built** | Multi-turn conversation state is not implemented. Each ask is stateless. `chatbot_logs` records history for analytics, not for context carry-over. Do not build a UI that assumes follow-up questions retain context. |

> **`class_id` is a security boundary, not a filter.** The `class_id` in the request
> body is validated server-side against the caller's own primary `Enrollment` before
> any retrieval happens, and the retrieval scope — `(school_id, grade_level)` — is then
> derived from that *validated* class.
>
> The request still names a **class**, not a grade, even though scope is grade-level:
> a client that supplied `grade_level` directly could name any grade in the school,
> whereas a class is something it must prove membership of. Covered by
> `test_student_cannot_claim_a_class_they_are_not_enrolled_in`.

#### `POST /bots/student/ask`
Ask the student Doubt Bot. Retrieval-augmented, grounded, and refuses outside its context.
- **Roles:** student
- **Request:** `{ "query": "why do we carry the one when multiplying?", "class_id": 5208, "subject_id": 3631 }`
- **Behaviour:** embeds the query (`RETRIEVAL_QUERY`), retrieves top-5 `kb_chunks` by
  cosine distance filtered to the validated `class_id`, and passes only those chunks
  to the model. **If the retrieved context does not cover the question the bot says
  so rather than answering from general knowledge** — the grounded refusal is
  intended behaviour, not a failure.
- **Response:**
```json
{ "answer": "Your notes call it regrouping...",
  "citations": [ { "chunk_id": 41, "source_id": 12, "title": "Grade 3 Math — Multiplication", "snippet": "When a column adds to more than 9..." } ] }
```
- **Errors:** `400` empty query; `403` `class_id` the caller is not enrolled in;
  `502` embedding or generation failure.

#### `POST /bots/reindex`
Manually re-ingest resources. Idempotent — re-running never duplicates chunks
(`kb_chunks` has a unique key on `(source_type, source_id, chunk_index)`).
- **Roles:** admin, principal
- **Request:** `{ "resource_id": 12 }` — omit to reindex every not-yet-indexed
  resource in the caller's school.
- **Response:** `{ "resources_indexed": 3, "chunks_written": 21 }`

### Bot insights — Top Doubts

When students across several sections of the same grade ask about the same concept,
the teacher who teaches that subject at that grade sees one ranked list of confusions
rather than several disconnected question logs.

> **Aggregation is by `(school_id, grade_level, subject_id)` — deliberately NOT by
> `class_id`.** Confusion shared between Grade 3 - A and Grade 3 - B is *one* insight,
> not two. **This supersedes the older `POST /doubts` thread stubs' per-class framing**
> below; those describe human-to-human threads and are still unbuilt. Same
> reconcile-in-place treatment as the notification and chatbot stubs.

Clusters are computed **live** from `chatbot_logs.query_embedding` — the vector already
stored when the student asked, never re-embedded. Nothing is persisted; there is no
`doubt_clusters` table to keep fresh.

#### `GET /bots/insights/top-doubts`
Ranked confusions for one (grade, subject).
- **Roles:** teacher (only grades/subjects they actually teach), admin, principal
  (any, within their own school). Everyone else `403`.
- **Query:** `?grade_level=3&subject_id=3631&days=7&limit=5`
- **Teaching assignment is resolved from `timetable_slots`** joined to `classes` on
  `grade_level`, not from `teacher_subjects` — a timetable slot is evidence of actually
  teaching that grade, whereas `teacher_subjects` only records qualification. Falls
  back to `teacher_subjects` when a grade has no slots at all.
- **Response:**
```json
{ "items": [
  { "label": "Regrouping when multiplying",
    "description": "Students are unsure what the carried digit represents.",
    "question_count": 6, "distinct_student_count": 5,
    "sections": ["Grade 3 - A", "Grade 3 - B"],
    "sample_questions": ["why do we carry the one", "i dont get the small number on top"] } ] }
```
- **`sections`** is the cross-section proof — two section names on one cluster is the
  whole point of the feature.
- **Degraded mode:** with fewer than 3 usable logs, returns the most recent distinct
  questions with `label: null` and `description: null` rather than an empty panel or a
  crash. A widget must handle `label === null`.

#### `GET /bots/insights/my-top-doubts`
The teacher-dashboard convenience call. Resolves the caller's own
`(grade_level, subject_id)` pairs from `timetable_slots` and returns clusters per pair.
- **Roles:** teacher (admin/principal get an empty `items`, since they teach nothing)
- **Query:** `?days=7&limit=5`
- **Response:**
```json
{ "items": [ { "grade_level": 3, "subject_id": 3631, "subject_name": "Math", "clusters": [ /* as above */ ] } ] }
```

#### `POST /bots/parent/ask` — Parent Assistant Bot
Answers a parent's question about their own child, grounded in that child's record.

> **STRUCTURED CONTEXT, NOT RAG.** A child's attendance, remarks, risk and fees are
> **never embedded and never enter `kb_chunks`**. That corpus is grade-scoped teaching
> material shared across a whole grade, so putting one child's record into it would let
> another family's question retrieve it. Instead the handler calls
> `GET /parent/child/{id}/summary`'s own function and serializes the result into the
> prompt — which also means the bot can never disagree with the portal page the parent
> is looking at.

- **Roles:** parent (own linked child only)
- **Request:** `{ "query": "how is my child doing?", "student_id": 21546 }`
- **`student_id` is a security boundary** — revalidated with
  `scoping.assert_parent_linked` on **every** request. The frontend child selector is
  never trusted. Covered by `test_parent_bot_cannot_be_asked_about_an_unlinked_child`.
- **Response:** same shape as the student bot (`{answer, citations}`) so `ChatShell`
  needs no branching. **`citations` is always `[]`** — nothing was retrieved; the
  "source" is the child's own record, already on screen.
- **Guardrails in the system prompt:** no medical, psychological or diagnostic opinions;
  no prediction; no invented numbers; and an explicit "say so plainly" when the record
  doesn't cover the question. Verified live — asked whether a child has ADHD it declines
  and points at the school and a doctor; asked for exam marks it states there is no
  grade data in the system.
- **`chatbot_logs`:** written with `bot_type="parent"` and **`query_embedding = NULL`,
  deliberately.** Top Doubts clusters that table by (school, grade, subject) to show
  teachers what *students* are stuck on, and it skips null-embedding rows. Embedding a
  parent query would surface "how is my child doing" in a teacher's cluster feed as
  though a child had asked it. Guarded by
  `test_parent_ask_never_writes_a_query_embedding`.
- **Errors:** `400` empty query; `403` not linked to that student.

#### Teacher bot
`POST /bots/teacher/ask` is **not built**. It would reuse the student bot's retrieval
core with a taught-classes scope resolver. The original stub's claim that all three bots
share one request shape no longer holds: the student bot takes `class_id`, the parent bot
takes `student_id`, and a teacher has neither a single enrollment nor a single child to
validate against.

### Class chat + doubt threads

> **✅ BUILT — as `/threads/*`, not `/doubts/*`.** The stubs below described
> human-to-human doubt threads and are now implemented, with divergences, in the
> **Doubt threads** section that follows them. The stubs are kept verbatim for
> reference; the divergence table is the reconciliation. They were never satisfied by
> the Doubt Bot or by Top Doubts — those answer questions with an LLM and aggregate
> them for teachers, and neither creates a thread or a reply anyone can post into.

#### `GET /classroom/{class_id}/chat`
Fetch class chat messages.
- **Roles:** teacher, student (enrolled), admin, principal
- **Query:** `?since=`
- **Response:**
```json
{ "items": [ { "id": 1, "sender_id": 15, "message": "Is there homework today?", "created_at": "2026-08-09T06:00:00Z" } ] }
```

#### `POST /classroom/{class_id}/chat`
Post a class chat message.
- **Roles:** teacher, student (enrolled)
- **Request:** `{ "message": "Is there homework today?" }`
- **Response:** `{ "id": 1, "created_at": "2026-08-09T06:00:00Z" }`

#### `POST /doubts`
Post a new doubt or reply to an existing thread.
- **Roles:** student, teacher
- **Request:** `{ "class_id": 2, "subject_id": 3, "thread_id": null, "message": "Don't understand Q3" }`
- **Response:** `{ "thread_id": 9, "message_id": 40, "created_at": "2026-08-09T06:00:00Z" }`

#### `GET /doubts/{thread_id}`
Fetch a doubt thread.
- **Roles:** student (own class), teacher
- **Response:**
```json
{ "thread_id": 9, "subject_id": 3, "messages": [ { "id": 40, "sender_id": 15, "message": "Don't understand Q3", "created_at": "2026-08-09T06:00:00Z" } ] }
```

### Doubt threads (implements the two stubs above)

Students post doubts to their class; classmates and the teacher reply; **the teacher
marks one reply as the verified answer, and that answer is ingested into the bot's
knowledge base.** Backed by `doubt_threads` + `thread_replies`
(`backend/app/models/doubt.py`, migration `bbf5b96300f8`).

**Reconciliation with the `POST /doubts` / `GET /doubts/{thread_id}` stubs:**

| Stub | Built | Why it diverged |
| --- | --- | --- |
| `POST /doubts` did double duty (new thread *and* reply, via a nullable `thread_id`) | `POST /threads` + `POST /threads/{id}/reply` | Different auth (posting needs class membership; replying needs a thread you can already see) and different validation. One endpoint branching on a nullable field hides both. |
| `/doubts/*` | `/threads/*` | `/doubts` now collides conceptually with the Doubt **Bot** (`/bots/student/ask`) and **Top Doubts** (`/bots/insights/top-doubts`), both shipped. `threads` is unambiguous about which of the three you're calling. |
| `message` | `title` + `body` | A thread list needs something scannable; `message` alone renders as a column of paragraph openings. |
| flat `messages[]` | `replies[]` + `verified_reply_id` | The stub had no notion of a verified answer, which is the entire point of the feature. |
| — | `PUT .../verify/{reply_id}`, `PUT .../unverify` | Not in the stub at all; they are what feeds and retracts KB content. |

**THE SCOPE ASYMMETRY — deliberate.** A thread is **class-scoped**; its verified answer
is ingested at **grade level**. A doubt belongs to the room it was asked in, so 3-B
cannot open 3-A's threads. But once a teacher certifies an answer it stops being
classroom chatter and becomes curriculum — exactly as reusable as an uploaded handout,
and resources are already grade-scoped for the same reason. So 3-B's students *do* get
3-A's verified answers through the bot while never seeing the thread. Verifying widens
an answer's audience from one class to a whole grade; that is the intended trade, and
it is why unverify must **delete** the `kb_chunks` rows rather than just clear a flag.

**Teacher scope, two different rules on purpose.** Read/reply accept the homeroom
teacher **or** any teacher with ≥1 active `TimetableSlot` for that class — a subject
teacher who teaches Grade 1-A Math must be able to answer a Grade 1-A Math doubt.

**Verify/unverify are homeroom-teacher only** (`scoping.teacher_class_ids`), and this
narrower rule is **deliberate — do not widen it.** "The teacher who owns the class
certifies what enters the knowledge base" is a cleaner authority story than "anyone who
teaches a period here," and a verified answer is grade-wide content, not a classroom
reply. Consequence, accepted: a subject teacher can reply in a class but not verify
there. Distinct from the attendance router, which *did* widen teacher scope for its new
endpoints — that widening was about who may record a fact, this restriction is about who
may certify content for a shared corpus. Note this is a narrower rule than
`_teaching_class_ids` used elsewhere in the same router, on purpose.

#### `POST /threads`
- **Roles:** student (enrolled), teacher (of that class)
- **Request:** `{ "class_id": 5208, "subject_id": 3, "title": "Why does ice float?", "body": "Everything else sinks when solid." }`
- **`class_id` is validated against the caller's own enrollment / teaching assignment server-side.** Never trusted from the body — that is the same boundary `assert_student_class_access` enforces for the bot.
- **Response:** the created thread, same shape as a `GET /threads/{id}` item without replies.
- **Errors:** `400` blank title/body; `403` not a member of that class; `404` unknown class.

#### `GET /threads?class_id=&resolved=`
- **Roles:** student (enrolled), teacher (of that class), admin/principal (own school)
- **Query:** `class_id` required; `resolved` optional (`true`/`false`)
- **Response:**
```json
{ "items": [ { "id": 9, "class_id": 5208, "subject_id": 3, "title": "Why does ice float?",
               "body": "...", "author_id": 21533, "author_name": "Aarav Kumar",
               "resolved": true, "reply_count": 3, "created_at": "...",
               "verified_reply": { "id": 40, "author_id": 22398, "author_name": "Meera Iyer",
                                   "body": "Water expands when it freezes...", "created_at": "..." } } ] }
```
- **Unresolved first**, then newest — a thread list is a work queue for the teacher.
- `verified_reply` is `null` unless resolved.

#### `GET /threads/{id}`
- **Roles:** as the list
- **Response:** the thread plus `replies[]` **chronological**, each with `is_verified`.
- **Errors:** `403` not a member of the thread's class; `404` unknown thread.

#### `POST /threads/{id}/reply`
- **Roles:** student (enrolled in the thread's class), teacher (homeroom or teaching it)
- **Request:** `{ "body": "I think it's about density." }`
- **Response:** the created reply.
- **Errors:** `400` blank body; `403` not a member; `404` unknown thread.

#### `PUT /threads/{id}/verify/{reply_id}`
Certify a reply as the answer **and ingest it into the knowledge base.**
- **Roles:** teacher, **homeroom teacher of that class only**
- **Request:** no body
- **Response:** `{ "thread": {...}, "chunks_written": 1, "kb_note": "Added to the Grade 3 knowledge base" }`
- Sets `resolved=true` and `verified_reply_id`, writes an audit row
  (`verify_doubt_answer` on `doubt_threads`), notifies the thread author
  (`source_type="doubt_answer_verified"`), then calls
  `ingestion.ingest_verified_doubt_answer`.
- **SYNCHRONOUS ingestion, ~2.7s measured** for one Q&A pair (embedding round-trip).
  Same inline-on-write precedent as `POST /resources/upload` and
  `POST /admin/fees/schedules`. Short enough not to need a job queue; long enough that
  the UI must show a real pending state.
- **Idempotent** via `kb_chunks`' unique `(source_type, source_id, chunk_index)` —
  re-verifying updates chunk 0 in place rather than appending a duplicate.
- **Errors:** `400` reply doesn't belong to this thread, or the class has no `grade_level` (nothing to scope the chunk by); `403` not the homeroom teacher; `404` unknown thread or reply.

#### `PUT /threads/{id}/unverify`
- **Roles:** teacher, homeroom teacher of that class only
- **Response:** `{ "thread": {...}, "chunks_deleted": 1 }`
- Clears `resolved`/`verified_reply_id` **and deletes the corresponding `kb_chunks`
  rows.** Leaving them would mean unretractable content in the bot: a teacher who
  withdraws a wrong answer would keep seeing it cited.
- Audit row `unverify_doubt_answer`. Idempotent — unverifying an unverified thread is a `400`, but a thread with no chunks deletes zero and still succeeds.
- **Errors:** `400` thread is not currently verified; `403` not the homeroom teacher; `404` unknown thread.

**Citations carry teacher attribution.** A verified-answer chunk cites as
`Verified answer · Meera Iyer · "Why does ice float?"`, built by
`retrieval.verified_answer_title`, and `Citation.source_type` is
`verified_doubt_answer` so the UI can label and style it distinctly from a document.
See the ⚠️ note under `POST /bots/student/ask` about the join that makes this correct.

### Announcements

#### `POST /announcements`
Create an announcement.
- **Roles:** admin, principal, teacher
- **Request:** `{ "title": "Sports day", "body": "...", "target": "class", "target_id": 2, "roles": null }`
- **Response:** `{ "id": 5, "created_at": "2026-08-09T06:00:00Z" }`

#### `GET /announcements`
Fetch announcements targeted at the current user.
- **Roles:** any authenticated
- **Query:** `?since=&page=`
- **Response:**
```json
{ "items": [ { "id": 5, "title": "Sports day", "body": "...", "created_at": "2026-08-09T06:00:00Z" } ], "total": 1, "page": 1, "page_size": 20 }
```

### Notification center

**BUILT — and it diverges from the stub that was here. Read this before coding
against it.** This section previously held a 2-endpoint stub (`GET /notifications`
with `?unread_only=&page=`, and `POST /notifications/{id}/read`) that nothing
implemented. It has now been built for real, out of Person A's session, because
six of Person A's handlers already computed a notification audience and dropped it
on the floor. Same reconciliation situation as `GET /parent/children` below - the
implementation is the source of truth; the differences from the old stub are:

| Stub said | Actually built | Why |
|---|---|---|
| `?unread_only=` | `?read=true\|false` | Tri-state: omit for all, `false` for unread, `true` for read. `unread_only=false` couldn't express "only read ones". |
| `POST /{id}/read` | `PUT /{id}/read` | Idempotent state set, not a creation. Matches `PUT /risk/{id}/acknowledge` elsewhere in this doc. |
| `type` | `source_type` | Avoids shadowing a JS builtin-ish name, and matches the column. |
| `message` | `title` + `body` | The bell needs a one-line title and an optional longer body; one field couldn't serve both. |
| `read: false` (bool) | `read_at: null` (timestamp) | "When did they see it" is answerable, not just "did they". `null` = unread. |
| — | `priority`, `source_id`, `acknowledged_at` | Urgency styling, deep-linking to the originating entity, and explicit dismissal. |

The `{items, total, page, page_size}` envelope is unchanged from the stub - and
note this is the **first actually-paginated endpoint in the repo**; every other
list route returns an unpaginated `{"items": [...]}` despite this doc's
Conventions section specifying pagination. New list endpoints should follow this
one, not the older routers.

Notifications are written only by `app/services/notify.py`, inside the
transaction of the state change that caused them (see that module's docstring).
There is no endpoint to create one: a notification is a side effect of something
real happening, never a thing a client posts.

#### `GET /notifications`
The caller's own inbox, newest first. **There is deliberately no `user_id`
parameter** - a user reads their own inbox and nobody else's, so there is nothing
to authorize and nothing to leak.
- **Roles:** any authenticated
- **Query:** `?read=true|false&page=1&page_size=20` (`read` omitted = both; `page_size` max 100)
- **Response:**
```json
{
  "items": [
    {
      "id": 30, "source_type": "early_warning", "source_id": 1435,
      "title": "Aarav Kumar flagged as high risk",
      "body": "attendance rate 40% is below the 90% threshold",
      "priority": "urgent", "read_at": null, "acknowledged_at": null,
      "created_at": "2026-08-16T06:00:00Z"
    }
  ],
  "total": 1, "page": 1, "page_size": 20
}
```
- **Errors:** `400` `page` < 1, or `page_size` outside 1-100.

#### `GET /notifications/unread-count`
Cheap count for the bell badge - hit frequently, served by the
`(user_id, read_at)` composite index.
- **Roles:** any authenticated
- **Response:** `{ "count": 3 }`

#### `PUT /notifications/{id}/read`
Mark one notification read. Idempotent: re-reading an already-read one leaves the
original `read_at` untouched rather than bumping it.
- **Roles:** any authenticated (own notifications only)
- **Response:** the updated notification, same item shape as `GET /notifications`.
- **Errors:** `404` unknown id **or** someone else's notification - deliberately
  not `403`, which would confirm the row exists.

#### `PUT /notifications/read-all`
Mark every one of the caller's unread notifications read.
- **Roles:** any authenticated
- **Response:** `{ "updated": 7 }`

#### `PUT /notifications/{id}/acknowledge`
Explicitly acknowledge/dismiss. Independent of read state rather than implying it
(same separation as `PUT /risk/{id}/acknowledge` vs `resolve`).
- **Roles:** any authenticated (own notifications only)
- **Response:** the updated notification.
- **Errors:** `404` unknown id or not the caller's.

#### `GET /notifications/stream`
SSE live feed of the caller's own unread count and most recent notifications.
Same mechanism and the same `_format_sse_event` shape as `GET /admin/alerts/stream`
(see that endpoint's "SSE, not Socket.io" note - still no Socket.io in this repo,
still no new dependency). Polls on an interval rather than pushing on write.
- **Roles:** any authenticated
- **Response:** `text/event-stream`, each event `data: {...}\n\n`:
```json
{ "unread_count": 3, "latest": [ { "id": 30, "source_type": "early_warning", "title": "...", "priority": "urgent", "read_at": null, "created_at": "..." } ] }
```
- **Auth caveat:** as with the alerts stream, `EventSource` can't send an
  `Authorization` header - the frontend reads this with `fetch` + a
  `ReadableStream` reader instead.

### Parent portal

#### `GET /parent/children`
List the children linked to the current parent account.

**Already implemented out-of-turn by Person A's frontend session** (`backend/app/routers/
parent.py`), ahead of Person C picking up parent portal work, to unblock a real parent
dashboard that needs its child set up front rather than having every screen make the
parent type in a `student_id` by hand. Strictly scoped to the caller's own links via
`ParentStudent.parent_id = user.id`.

**Shape mismatch, please read before building on this:** the version below is the
original Person C stub's proposed shape. The version actually running is different -
`{ "items": [ { "id": 103, "name": "Demo Student Class 8A #01", "class_id": 41, "class_name":
"Class 8A" } ] }`, i.e. `id`/`name` instead of `student_id`/`full_name`, plus a
`class_name` the stub didn't have (`null` if the child has no primary `Enrollment` yet).
The frontend (`ParentDashboard.tsx`) is already wired to the real shape. If Person C
needs the stub's shape instead, that's a coordinate-before-changing conversation, not a
silent edit - this doc is now describing what's live, not the original proposal.
- **Roles:** parent
- **Response (as implemented):** `{ "items": [ { "id": 103, "name": "Demo Student Class 8A #01", "class_id": 41, "class_name": "Class 8A" } ] }`
- ~~**Response (original stub, not what's running):** `{ "items": [ { "student_id": 15, "full_name": "Jane Doe", "class_id": 2 } ] }`~~

#### `GET /parent/child/{student_id}/summary` — **the parent portal's single call**
Everything the parent portal shows for one child, in one round trip.

**Supersedes the `/performance` and `/attendance` stubs below**, which are unbuilt and
would have needed three or four sequential calls to fill one screen. A phone on venue
wifi making four round trips is a visibly slow page; this is one. Nothing here is
re-implemented — it composes the existing attendance-summary logic, `risk_flags`, the
Day 1 remarks query, and fee status.

- **Roles:** parent (own linked child only, via `scoping.assert_parent_linked`);
  admin/principal within their own school. Everyone else `403`.
- **Response:**
```json
{
  "student": {"id": 21546, "name": "Diya Kumar", "class_id": 5208, "class_name": "Grade 3 - A", "grade_level": 3},
  "attendance": {"present_pct": 47.6, "present_count": 10, "absent_count": 11, "late_count": 0, "days": 30},
  "risk": {"level": "medium", "score": 0.464, "reasons": ["attendance rate 48% is below the 90% threshold"], "flagged_at": "..."},
  "remarks": [{"id": 9, "teacher_name": "Kavya Reddy", "remark_text": "...", "sentiment": {"label": "negative", "compound": -0.85}, "created_at": "..."}],
  "fees": [{"fee_record_id": 1742, "fee_type": "Term 1 Tuition", "amount_due": 4500.0, "amount_paid": 0.0, "status": "overdue", "due_date": "2026-07-26"}],
  "upcoming": []
}
```
- `risk` is the most recent **open** flag, or `null` — `null` is the healthy case and
  the UI must hide the banner entirely rather than render an empty one.
- **`attendance.days` is a 30-CALENDAR-day window, deliberately matching
  `run_nightly_risk_scoring.ATTENDANCE_LOOKBACK_DAYS`.** If the card used a different
  window from the scorer, the banner would quote one attendance figure while the card
  above it showed another — which is exactly the contradiction this endpoint exists to
  avoid. Change one, change both.
- `remarks` is the last 10, newest first, with sentiment computed per-request (never
  stored — see `remark_stubs`).
- `upcoming` is currently always `[]`. Deliberately deferred rather than faked; the
  field is in the contract so adding exams/timetable events later is not a shape change.
- **Errors:** `403` not linked / wrong school; `404` unknown student.

#### ~~`GET /parent/children/{student_id}/performance`~~ — superseded, never built
Would have returned a `gradebook_summary`, which is unbuildable: there is no gradebook
table in this schema. The attendance half is served by the summary endpoint above.

#### ~~`GET /parent/children/{student_id}/attendance`~~ — superseded, never built
Per-day attendance rows. **Now genuinely served by `GET /attendance/my-records`**
(see the attendance section) - period-by-period, day-by-day, with the parent-link
check built in. `/parent/child/{id}/summary` still carries the 30-day aggregate the
dashboard card renders; use `/attendance/my-records` for the drill-down. Don't build
a parent-only copy of either.

#### ~~`GET /parent/children/{student_id}/fees`~~ - superseded, now built at a different path
**Built as `GET /parent/child/{student_id}/fees`** (singular `child`, matching
`/parent/child/{id}/summary`) - see "Fee payment confirmation loop" in the Fees
section. It exists as its own endpoint rather than reusing
`GET /admin/fees/status?student_id={id}` because the parent view needs a status the
canonical record cannot express: `payment_pending` and `rejected` come from
`fee_payment_requests`, not from `fee_records.status`. The shared status endpoint is
still the right call for the raw record view.

#### `POST /parent/messages`
Send a message from a parent to a teacher/school.
- **Roles:** parent
- **Request:** `{ "recipient_id": 7, "subject": "Question about homework", "body": "..." }`
- **Response:** `{ "id": 70, "created_at": "2026-08-09T06:00:00Z" }`

### Search

#### `GET /search`
Global search across announcements, resources, and people.
- **Roles:** any authenticated
- **Query:** `?q=&type=&page=`
- **Response:**
```json
{ "items": [ { "type": "announcement", "id": 5, "title": "Sports day", "snippet": "..." } ], "total": 1, "page": 1, "page_size": 20 }
```

## Open questions

- [ ] Where do custom `role` claims get set on the Supabase user (raw_app_meta_data
      via admin API / DB trigger on signup)?
- [ ] Do we need a `staff` vs `student`/`parent` split beyond the 5 roles for
      finer-grained permissions later?
- [x] ~~Phase 0 schema has no student↔class enrollment table yet~~ — resolved: see
      `enrollments` (`backend/app/models/enrollment.py`, migration `1af99f18bbe6`).
      `"enrolled"` scoping in Person B/C's endpoints above (`classroom/*`,
      `gradebook/*`, `homework-calendar`, attendance) now checks
      `enrollments.student_id / class_id` (rows with `subject_id IS NULL` are a
      student's primary/homeroom enrollment; non-null `subject_id` rows are
      subject-specific/elective enrollment).
- [x] ~~Phase 0 schema has no parent↔student relationship table yet~~ — resolved: see
      `parent_student` (`backend/app/models/parent_student.py`, migration
      `1af99f18bbe6`). `"own child only"` scoping in Person C's `parent/*` endpoints
      now checks `parent_student.parent_id / student_id` (a parent can have multiple
      rows for multi-child support).
- [ ] Class chat / doubt threads / notifications: polling or WebSocket? Affects
      whether `GET .../chat?since=` is the real transport or just a fallback.
- [ ] Attendance RFID mode + CV/RFID reconciliation: `attendance_reconciliations`
      (`backend/app/models/attendance.py`, migration `fd046d263fe1`) is schema-ready
      (cross-references a `cv`-source and `rfid`-source `AttendanceRecord` per
      student/slot/date, flags `status_mismatch` / `cv_only` / `rfid_only`) but
      nothing populates or resolves it yet - no RFID ingestion endpoint exists, and no
      job compares CV vs RFID rows. Next session.
- [ ] **HARDENING: app-clock vs DB-clock skew on review timestamps.** Creation
      timestamps (`submitted_at`, `marked_at`, `created_at`, …) come from the DB via
      `server_default=func.now()`, while every review/decision timestamp
      (`reviewed_at`, `resolved_at`, `decided_at`, …) is set in Python with
      `datetime.now(timezone.utc)`. When the app host's clock differs from the DB's,
      a review can carry a timestamp *earlier* than the thing it reviewed - observed
      as an ~88ms inversion on a fee payment request during this session's
      walkthrough (`reviewed_at` 13:52:44.232 vs `submitted_at` 13:52:44.320).
      Cosmetic at demo scale and consistent across the whole codebase, so it was
      deliberately NOT changed mid-feature. The fix is to source both from the same
      clock - either `server_default`/`onupdate` for review columns too, or
      `func.now()` passed as the value on assignment. One change, applied
      repo-wide, in its own commit.
