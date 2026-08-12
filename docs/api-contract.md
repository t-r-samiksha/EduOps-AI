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

This section is Person A's to extend — add/adjust endpoints here without touching
Person B/C's sections below.

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

#### `POST /admin/ocr/documents`
Upload a document (marksheet, admission form, ID proof, ...) for OCR processing.
- **Roles:** admin, principal
- **Request:** `multipart/form-data` — `file` (binary) + form field `document_type` (`"marksheet" | "admission_form" | "id_proof" | "other"`)
- **Response:**
```json
{ "id": 1, "document_type": "admission_form", "status": "done", "uploaded_at": "2026-08-11T10:00:00Z" }
```
- **Errors:** `400` invalid `document_type`; `422` undecodable image; `503` Tesseract binary unavailable on the server.

#### `GET /admin/ocr/documents/{id}`
Fetch OCR processing status/result for a previously uploaded document.
- **Roles:** admin, principal
- **Response:**
```json
{
  "id": 1,
  "document_type": "admission_form",
  "status": "done",
  "uploaded_at": "2026-08-11T10:00:00Z",
  "processed_at": "2026-08-11T10:00:01Z",
  "extracted_fields": { "applicant_name": "Priya Sharma", "dob": "2015-04-01", "guardian_name": "Rajesh Sharma", "guardian_phone": "9876543210" },
  "entities": [
    { "id": 5, "field_name": "applicant_name", "field_value": "Priya Sharma", "confidence_score": 0.96, "is_low_confidence": false, "corrected_value": null, "corrected_by": null, "corrected_at": null }
  ],
  "raw_text": "Applicant Name: Priya Sharma\nDate of Birth: 2015-04-01\n...",
  "ocr_confidence": 0.96,
  "routing": { "routed": false, "target_table": null, "reason": "No 'admissions/applications' table exists yet for document_type='admission_form' - extraction is persisted as ExtractedEntity rows, routing is a documented stub" },
  "error": null
}
```
`extracted_fields` uses each field's `corrected_value` where a manual correction
exists, else its OCR `field_value` - `entities` carries the full per-field detail
(confidence, correction state, entity `id` to `PUT` against) the flat dict can't.
- **Errors:** `404` unknown document id.

#### `PUT /admin/ocr/documents/{id}/entities/{entity_id}`
Manual correction of an extracted field (the "manual data fix" half of the playbook's
manual-fix-+-re-extract flow) - sets `corrected_value`/`corrected_by`/`corrected_at`
without touching the original OCR `field_value`.
- **Roles:** admin, principal
- **Request:** `{ "corrected_value": "Priya A. Sharma" }`
- **Response:** the updated entity, same shape as a `GET` response's `entities[]` item.
- **Errors:** `400` empty `corrected_value`; `404` unknown document/entity id (or entity belongs to a different document).

#### `POST /admin/ocr/documents/{id}/reextract`
Re-run postprocessing against the document's already-stored `raw_text` (no
re-upload) - the "re-extract" half of the manual-fix flow, e.g. after realizing a
document was mis-classified. Per-field confidence is recomputed from persisted
word-level OCR data, not just re-copied from the overall score. **Replaces** the
document's existing entities (and therefore any corrections made against them) -
old field names may not even apply if `document_type` changed.
- **Roles:** admin, principal
- **Request:** `{ "document_type": "marksheet" }` (optional - omit to retry with the existing `document_type`)
- **Response:** same shape as `GET /admin/ocr/documents/{id}`.
- **Errors:** `400` invalid `document_type`, or no OCR result exists yet for this document; `404` unknown document id.

### Timetable optimization

Backed by a CP-SAT (OR-Tools) constraint solver — hard constraints: no teacher, room,
or class double-booked in the same period. Solver input (`TeacherSubject` = who's
qualified to teach what, `ClassSubjectRequirement` = periods/week a class needs of a
subject, `TeacherUnavailability`, `SubjectRoomRequirement` = e.g. Science -> lab) lives
in `backend/app/models/timetable.py` and must be populated before `/generate` is
called. `day_of_week` is 0-indexed (0 = Monday); `period_number` is 0-indexed within
the day. Generation is synchronous (no run_id/polling) - small enough inputs solve in
well under the request timeout.

#### `POST /timetable/generate`
Run the solver for a school/academic year and persist the result. Deactivates
(`is_active=false`) any previous active slots for the same class(es)/academic_year
before inserting the new ones - a superseding run, not additive.
- **Roles:** admin, principal
- **Request:**
```json
{ "school_id": 1, "academic_year": "2026-27", "class_ids": [2], "days": 5, "periods_per_day": 6 }
```
`class_ids` omitted = every class in `school_id`. `days`/`periods_per_day` default to 5/6.
- **Response:**
```json
{
  "academic_year": "2026-27",
  "slots_created": 14,
  "slots": [ { "id": 101, "day_of_week": 0, "period_number": 0, "start_time": "08:00:00", "end_time": "08:45:00", "subject_id": 3, "teacher_id": 7, "class_id": 2, "room_id": 1, "academic_year": "2026-27", "is_active": true } ]
}
```
- **Errors:** `400` no matching classes/requirements found; `422` solver proved the
  input infeasible (e.g. no qualified teacher, or over-constrained availability).

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
- **Roles:** admin, teacher (teacher only for records in a class they're `class_teacher` of - `403` otherwise)
- **Request:** `{ "status": "present" }` (`present` | `absent` | `late`)
- **Response:** the updated record, same shape as a `matches[]` entry plus
  `reviewed_by`/`reviewed_at`:
```json
{ "id": 501, "student_id": 15, "class_id": 2, "timetable_slot_id": 5, "date": "2026-08-09", "status": "present", "source": "cv", "marked_at": "2026-08-09T08:05:00Z", "confidence_score": 0.42, "reviewed_by": 7, "reviewed_at": "2026-08-09T09:00:00Z" }
```
- **Errors:** `400` invalid `status`; `404` unknown `record_id`.

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
- **Request:** `{ "leave_request_id": 12, "decision": "approved", "academic_year": "2026-27" }`
(`academic_year` required when `decision` is `"approved"` - needed to resolve affected timetable slots; omit for `"rejected"`)
- **Response:**
```json
{
  "leave_request": { "id": 12, "teacher_id": 97, "start_date": "2026-08-14", "end_date": "2026-08-14", "reason": "Feeling unwell", "status": "approved", "requested_at": "2026-08-10T10:00:00Z", "decided_by": 41, "decided_at": "2026-08-10T10:05:00Z" },
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
- **Response:** array of the same leave-request shape as `/staff/request_leave`'s response.

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

### Admin command center

#### `GET /admin/alerts`
Unified alerts feed for the admin command center.
- **Roles:** admin, principal
- **Query:** `?since=&severity=`
- **Response:**
```json
{ "items": [ { "id": 9, "type": "attendance_drop", "severity": "warning", "message": "Class 8B attendance below 80%", "created_at": "2026-08-09T06:00:00Z", "resolved": false } ] }
```

#### `POST /admin/alerts/{id}/resolve`
Mark an alert as resolved.
- **Roles:** admin, principal
- **Response:** `{ "id": 9, "resolved": true }`

### Approval chains

#### `GET /admin/approvals`
Fetch pending approval requests visible to the current user.
- **Roles:** admin, principal, teacher
- **Response:**
```json
{ "items": [ { "id": 4, "type": "leave_request", "requested_by": 7, "status": "pending", "payload": { "reason": "..." }, "created_at": "2026-08-09T06:00:00Z" } ] }
```

#### `POST /admin/approvals/{id}/decision`
Approve or reject a pending request.
- **Roles:** admin, principal
- **Request:** `{ "decision": "approve", "comment": null }`
- **Response:** `{ "id": 4, "status": "approved" }`

### Audit log

#### `GET /admin/audit-log`
Fetch the audit trail.
- **Roles:** admin, principal
- **Query:** `?entity_type=&entity_id=&actor_id=&page=&page_size=`
- **Response:**
```json
{ "items": [ { "id": 100, "actor_id": 3, "action": "update", "entity_type": "user", "entity_id": 15, "created_at": "2026-08-09T06:00:00Z" } ], "total": 1, "page": 1, "page_size": 20 }
```

### Fees

#### `POST /admin/fees/reminders`
Trigger a batch fee-reminder send.
- **Roles:** admin, principal
- **Request:** `{ "class_id": null, "overdue_only": true }`
- **Response:** `{ "sent_count": 24 }`

#### `GET /admin/fees/status`
Fetch fee status across students (admin view — see also Person C's parent-scoped `/parent/children/{student_id}/fees`).
- **Roles:** admin, principal
- **Query:** `?class_id=&status=`
- **Response:**
```json
{ "items": [ { "student_id": 15, "amount_due": 5000, "due_date": "2026-08-15", "status": "overdue" } ] }
```

### Admissions

#### `POST /admin/admissions/applications`
Submit a new admission application (typically entered by office staff, possibly pre-filled via OCR).
- **Roles:** admin
- **Request:**
```json
{ "applicant_name": "Jane Doe", "dob": "2015-04-01", "guardian_email": "guardian@example.com", "grade_applied": "6", "ocr_document_ids": [1] }
```
- **Response:** `{ "id": 3, "status": "submitted" }`

#### `GET /admin/admissions/applications`
List/search admission applications.
- **Roles:** admin, principal
- **Query:** `?status=&page=`
- **Response:**
```json
{ "items": [ { "id": 3, "applicant_name": "Jane Doe", "grade_applied": "6", "status": "under_review" } ], "total": 1 }
```

#### `PATCH /admin/admissions/applications/{id}`
Update an application's status.
- **Roles:** admin, principal
- **Request:** `{ "status": "accepted" }`
- **Response:** `{ "id": 3, "status": "accepted" }`

### Exam seating

#### `POST /admin/exams/seating/generate`
Generate a seating plan for an exam.
- **Roles:** admin, principal
- **Request:**
```json
{ "exam_id": 5, "rooms": [ { "room": "204", "capacity": 30 } ] }
```
- **Response:**
```json
{ "exam_id": 5, "status": "generated", "seating": [ { "student_id": 15, "room": "204", "seat_no": 1 } ] }
```

#### `GET /admin/exams/seating`
Fetch a generated seating plan.
- **Roles:** admin, principal, teacher, student
- **Query:** `?exam_id=` or `?exam_id=&student_id=`
- **Response:**
```json
{ "exam_id": 5, "items": [ { "student_id": 15, "room": "204", "seat_no": 1 } ] }
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

### RAG chatbots

#### `POST /chat/student-bot`
Ask the student-facing RAG chatbot.
- **Roles:** student
- **Request:** `{ "message": "When is the Ch.4 assignment due?", "conversation_id": null }`
- **Response:**
```json
{ "conversation_id": 12, "reply": "It's due Aug 15.", "sources": [ { "title": "Ch. 4 problems", "url": null } ] }
```

#### `POST /chat/teacher-bot`
Ask the teacher-facing RAG chatbot. Same request/response shape as `/chat/student-bot`.
- **Roles:** teacher

#### `POST /chat/parent-bot`
Ask the parent-facing RAG chatbot. Same request/response shape as `/chat/student-bot`.
- **Roles:** parent

### Class chat + doubt threads

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

#### `GET /notifications`
Fetch the current user's notification feed.
- **Roles:** any authenticated
- **Query:** `?unread_only=&page=`
- **Response:**
```json
{ "items": [ { "id": 30, "type": "grade_posted", "message": "New grade posted for Ch. 4", "read": false, "created_at": "2026-08-09T06:00:00Z" } ], "total": 1, "page": 1, "page_size": 20 }
```

#### `POST /notifications/{id}/read`
Mark a notification as read.
- **Roles:** any authenticated
- **Response:** `{ "id": 30, "read": true }`

### Parent portal

#### `GET /parent/children`
List the children linked to the current parent account.
- **Roles:** parent
- **Response:** `{ "items": [ { "student_id": 15, "full_name": "Jane Doe", "class_id": 2 } ] }`

#### `GET /parent/children/{student_id}/performance`
Child's academic performance summary.
- **Roles:** parent (own child only)
- **Response:**
```json
{ "student_id": 15, "gradebook_summary": [ { "subject_id": 3, "average": 17.5 } ], "attendance_summary": { "present_pct": 92.5 } }
```

#### `GET /parent/children/{student_id}/attendance`
Child's attendance record.
- **Roles:** parent (own child only)
- **Query:** `?from=&to=`
- **Response:** `{ "student_id": 15, "items": [ { "date": "2026-08-09", "status": "present" } ] }`

#### `GET /parent/children/{student_id}/fees`
Child's fee status. Mirrors Person A's `/admin/fees/status` but scoped to one child.
- **Roles:** parent (own child only)
- **Response:** `{ "student_id": 15, "items": [ { "amount_due": 5000, "due_date": "2026-08-15", "status": "overdue" } ] }`

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
