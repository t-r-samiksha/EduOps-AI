# Person B Playbook — Classroom & Academics (Learning Layer)

## Scope
You own everything a teacher/student touches day-to-day for actual coursework. Specifically:

- Classroom Hub: class stream, resources library, assignments, submission tracking
- Academics Suite: online quizzes with auto-grading, gradebook, report cards, digital library, homework calendar, timetable-calendar sync
- Student/teacher-facing views: personal analytics, at-risk flag display, bulk remarks, syllabus pace UI, remark system

## Task Groups

### 1. Classroom Stream
- [ ] PostgreSQL tables: `classrooms` (per class/subject), `stream_posts` (with attachments)
- [ ] POST `/classroom/[id]/post` endpoint: teacher posts note/announcement/material to a class stream
- [ ] GET `/classroom/[id]/stream` endpoint: fetches chronological feed for a class
- [ ] DELETE `/classroom/[id]/post/[post_id]` endpoint: teacher removes a post
- [ ] File attachment upload/storage (S3-compatible) for stream posts
- [ ] Frontend: class stream feed view, teacher post composer, attachment preview

Integrate with:
- Person A: enrollment table determines who sees which class's stream
- Person C: stream posts feed into the announcement engine when marked as announcements

### 2. Resources Library
- [ ] PostgreSQL table: `resources` (subject/unit tagged, searchable, linked to file storage)
- [ ] POST `/resources/upload` endpoint: teacher uploads material tagged by subject/unit
- [ ] GET `/resources/[class_id]` endpoint: fetches organized resource list for a class
- [ ] Frontend: resources browser organized by subject/unit, upload flow

Integrate with:
- Person C: resources feed the Doubt Bot's knowledge base — flag new/updated resources for re-indexing

### 3. Assignments
- [ ] PostgreSQL tables: `assignments` (title, deadline, attachments, class), `submissions` (student, file, grade, status)
- [ ] POST `/assignments` endpoint: teacher creates assignment with deadline + attachments
- [ ] GET `/assignments/[class_id]` endpoint: lists assignments for a class
- [ ] POST `/assignments/[id]/submit` endpoint: student submits file
- [ ] PUT `/assignments/[id]/grade/[submission_id]` endpoint: teacher grades a submission
- [ ] Scheduled task: detect approaching/passed deadlines, trigger nudges for missing submissions
- [ ] Frontend: assignment creation form, student submission flow, teacher grading queue

Integrate with:
- Person A: grades flow into early-warning risk scoring
- Person C: late-submission nudges trigger parent auto-alerts via notification center

### 4. Submission Tracking
- [ ] GET `/assignments/[id]/submissions` endpoint: teacher view of submitted vs pending, per student
- [ ] Frontend: submission tracker table (status column: submitted/late/missing), one-click nudge trigger

### 5. Online Quizzes & Auto-Grading
- [ ] PostgreSQL tables: `quizzes`, `questions`, `quiz_attempts`
- [ ] POST `/quizzes` endpoint: teacher creates quiz with MCQ questions
- [ ] POST `/quizzes/[id]/attempt` endpoint: student submits quiz answers
- [ ] Auto-grading logic: score MCQ attempts immediately on submission
- [ ] GET `/quizzes/[id]/results` endpoint: teacher views class results, per-question breakdown
- [ ] Frontend: quiz builder (question types, correct-answer marking), student quiz-taking UI with timer, results dashboard

Integrate with:
- Person A: quiz grades feed into early-warning risk scoring
- Person C: Teacher Assistant Bot can draft quiz questions — expose a "generate questions" hook it can call into

### 6. Gradebook
- [ ] PostgreSQL table: `gradebook_entries` (weighted assessment scores, per student/subject/term)
- [ ] POST `/gradebook/entry` endpoint: records a weighted assessment score
- [ ] GET `/gradebook/[student_id]` endpoint: fetches full gradebook with term averages, GPA calc
- [ ] Weighting/GPA calculation logic (configurable weights per assessment type)
- [ ] Frontend: gradebook entry grid (teacher), student/parent gradebook view (read-only)

Integrate with:
- Person A: gradebook data feeds early-warning system
- Person C: gradebook summary feeds Parent Assistant Bot's "how is my child doing" answers

### 7. Report Card Automation
- [ ] Report card template design (PDF layout: grades + attendance + remarks)
- [ ] POST `/report_cards/generate/[student_id]` endpoint: pulls gradebook + attendance + remarks, generates formatted PDF
- [ ] PostgreSQL table: `report_cards` (generated PDFs + source data snapshot)
- [ ] Frontend: report card generation trigger (bulk + individual), download/preview

Integrate with:
- Person A: attendance data sourced from Person A's attendance tables
- Person C: report card ready → triggers parent notification

### 8. Digital Library
- [ ] PostgreSQL tables: `library_items` (book catalog), `loans` (issue/return tracking)
- [ ] POST `/library/issue` endpoint: issues a book to a student, sets due date
- [ ] PUT `/library/return/[loan_id]` endpoint: marks a book returned
- [ ] GET `/library/catalog` endpoint: searchable book/past-paper catalog
- [ ] Frontend: catalog browser, issue/return flow (admin/librarian view), student "my loans" view

### 9. Homework Calendar
- [ ] GET `/calendar/homework/[student_id]` endpoint: aggregates deadlines across all subjects for a student
- [ ] Frontend: unified calendar view combining assignment + quiz deadlines across subjects

### 10. Timetable-to-Calendar Sync
- [ ] Consume Person A's `/timetable/active` endpoint output
- [ ] PostgreSQL table: `calendar_events` (unified per-role calendar: classes, exams, deadlines, events)
- [ ] Sync job: pulls timetable slots + exam schedule + homework deadlines into `calendar_events`
- [ ] GET `/calendar/[user_id]` endpoint: fetches unified calendar for logged-in user
- [ ] Frontend: personal calendar view (day/week/month), color-coded by event type

Integrate with:
- Person A: timetable + exam schedule are the source data
- Person C: calendar surfaces on parent portal too

### 11. Student Personal Analytics
- [ ] GET `/analytics/student/[id]` endpoint: attendance % + subject-wise performance graphs data
- [ ] Consume Person A's `/risk/flagged` endpoint for at-risk flag display
- [ ] Frontend: personal analytics dashboard (charts via Recharts), at-risk banner if flagged

### 12. Teacher Bulk Remark Entry
- [ ] PostgreSQL table: `remarks` (sentiment_tag, author, student, timestamp)
- [ ] POST `/remarks/bulk` endpoint: teacher submits remarks for multiple students at once
- [ ] Sentiment tagging: academic / behavioral / appreciation (manual selection or auto-suggested)
- [ ] Frontend: bulk remark entry grid (one row per student, quick-tag UI)
Integrate with:
- Person A: remark sentiment feeds early-warning scoring

### 13. Teacher Syllabus Pace Tracker UI
- [ ] Consume Person A's `/syllabus/summary` endpoint
- [ ] Frontend: teacher-facing syllabus progress view (own subjects), "behind plan" warnings surfaced

### 14. Remark System (Sentiment Tags)
- [ ] GET `/remarks/[student_id]` endpoint: fetches remark history for a student
- [ ] Frontend: remark timeline view (student/parent-facing), filter by sentiment tag

## Cross-Cutting Concerns
- Test coverage: 80%+ on grading/GPA calculation logic (money-adjacent correctness bar), 60%+ elsewhere
- Performance: report card generation for a full class (~40 students) completes in under 30s
- Data integrity: gradebook/report card generation must be idempotent — re-running shouldn't duplicate entries
- Accessibility: gradebook and calendar views must be screen-reader navigable (feeds into Person C's WCAG pass)
- Documentation: document the GPA/weighting formula clearly — judges may ask about it directly