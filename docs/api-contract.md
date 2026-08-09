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

#### `POST /admin/ocr/documents`
Upload a document (marksheet, admission form, ID proof, ...) for OCR processing.
- **Roles:** admin, principal
- **Request:** `multipart/form-data` — `file` (binary) + form field `document_type` (`"marksheet" | "admission_form" | "id_proof" | "other"`)
- **Response:**
```json
{ "id": 1, "document_type": "admission_form", "status": "queued", "uploaded_at": "2026-08-09T10:00:00Z" }
```

#### `GET /admin/ocr/documents/{id}`
Fetch OCR processing status/result for a previously uploaded document.
- **Roles:** admin, principal
- **Response:**
```json
{
  "id": 1,
  "document_type": "admission_form",
  "status": "done",
  "extracted_fields": { "applicant_name": "...", "dob": "2015-04-01" },
  "error": null
}
```

### Timetable optimization

#### `POST /admin/timetable/generate`
Kick off a timetable optimization run for a school/academic year.
- **Roles:** admin, principal
- **Request:**
```json
{ "school_id": 1, "academic_year": "2026-27", "constraints": { "max_periods_per_day": 8 } }
```
- **Response:** `{ "run_id": 42, "status": "queued" }`

#### `GET /admin/timetable/runs/{run_id}`
Poll the status/result of a generation run.
- **Roles:** admin, principal
- **Response:**
```json
{ "run_id": 42, "status": "done", "timetable": [ { "day": "Mon", "period": 1, "subject_id": 3, "teacher_id": 7, "class_id": 2, "room": "204" } ] }
```

#### `GET /admin/timetable`
Fetch the active timetable for a class or teacher.
- **Roles:** admin, principal, teacher, student, parent
- **Query:** `?class_id=` or `?teacher_id=`
- **Response:**
```json
{ "items": [ { "day": "Mon", "period": 1, "subject_id": 3, "teacher_id": 7, "class_id": 2, "room": "204" } ] }
```

### Attendance

#### `POST /admin/attendance/mark`
Mark attendance for a class/date (manual entry, or written by the CV/RFID pipeline).
- **Roles:** admin, teacher
- **Request:**
```json
{
  "class_id": 2,
  "date": "2026-08-09",
  "records": [ { "student_id": 15, "status": "present", "source": "manual" } ]
}
```
- **Response:** `{ "class_id": 2, "date": "2026-08-09", "marked_count": 30 }`

#### `GET /admin/attendance`
Fetch attendance for a class/date.
- **Roles:** admin, principal, teacher; student (own record only); parent (own child only)
- **Query:** `?class_id=&date=`
- **Response:**
```json
{ "class_id": 2, "date": "2026-08-09", "records": [ { "student_id": 15, "status": "present" } ] }
```

### Predictive staffing / substitute suggestion

#### `GET /admin/staffing/substitute-suggestions`
Suggest substitute teachers for a teacher's absence.
- **Roles:** admin, principal
- **Query:** `?teacher_id=&date=`
- **Response:**
```json
{ "absent_teacher_id": 7, "date": "2026-08-09", "suggestions": [ { "teacher_id": 11, "score": 0.87, "reason": "same subject, free that period" } ] }
```

#### `GET /admin/staffing/forecast`
Predictive staffing shortage forecast for a week.
- **Roles:** admin, principal
- **Query:** `?school_id=&week_start=`
- **Response:**
```json
{ "school_id": 1, "week_start": "2026-08-10", "forecast": [ { "date": "2026-08-10", "predicted_absences": 3, "risk_level": "medium" } ] }
```

### Early-warning flags

#### `GET /admin/early-warning/students`
Fetch at-risk students (academic/attendance early-warning).
- **Roles:** admin, principal, teacher
- **Query:** `?class_id=&risk_level=`
- **Response:**
```json
{ "items": [ { "student_id": 15, "risk_level": "high", "reasons": ["attendance < 75%", "2 failed assessments"], "flagged_at": "2026-08-09T06:00:00Z" } ] }
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
