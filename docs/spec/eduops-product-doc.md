# EduOps AI — Complete Product Documentation

**Hackathon:** Future-Ready Ops
**Track:** AI-Powered School Administration & Operations
**Team size:** 3
**Timeline:** 6+ months
**Document version:** 2.0

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Context](#2-problem-context)
3. [Product Vision](#3-product-vision)
4. [System Architecture](#4-system-architecture)
5. [Roles & Access Control (RBAC)](#5-roles--access-control-rbac)
6. [Core Modules](#6-core-modules)
7. [The Classroom Hub](#7-the-classroom-hub)
8. [Chat & Discussion Rooms](#8-chat--discussion-rooms)
9. [The Announcement Feed](#9-the-announcement-feed)
10. [Academics Suite](#10-academics-suite)
11. [Intelligence & AI Layer](#11-intelligence--ai-layer)
12. [Conversational AI (Chatbots)](#12-conversational-ai-chatbots)
13. [Role-Specific Feature Sets](#13-role-specific-feature-sets)
14. [The Parent Portal](#14-the-parent-portal)
15. [Cross-Cutting Platform Features](#15-cross-cutting-platform-features)
16. [Complete Feature Catalog](#16-complete-feature-catalog)
17. [Data Model](#17-data-model)
18. [Technology Stack](#18-technology-stack)
19. [How Modules Interconnect](#19-how-modules-interconnect)
20. [Team Split & Build Plan](#20-team-split--build-plan)
21. [Mapping to Evaluation Criteria](#21-mapping-to-evaluation-criteria)
22. [Suggested Demo Core](#22-suggested-demo-core)
23. [Demo Checklist](#23-demo-checklist)

---

## 1. Executive Summary

**EduOps AI** is an AI-first, unified school operations *and* learning platform that replaces the fragmented mix of manual data entry, physical document storage, siloed scheduling, and disconnected communication tools that schools rely on today. It collapses multiple legacy apps into a single, role-aware platform where documents digitize themselves, timetables resolve their own conflicts, attendance captures itself, classes live in dedicated online rooms, and administrators are alerted to problems before they escalate — instead of hunting for data.

The platform serves five distinct roles — Principal/Super Admin, Office Admin, Teacher, Student, and Parent — each with a purpose-built dashboard. Beyond operations, it provides a full **teaching-and-learning layer**: a Classroom Hub for notes, assignments and discussion; an academics suite with a gradebook, online exams, a digital library, and unified calendars; and a targeted announcement feed that routes the right information to the right audience automatically.

It is powered by an intelligence layer that predicts staffing needs, flags at-risk students early, and auto-suggests substitutes when teachers take leave, plus three purpose-built AI assistants for students, teachers, and parents.

The guiding design principle throughout is **minimal clicks, maximum intelligence**: every key action reachable in two clicks, every screen surfacing what matters without the user searching for it.

---

## 2. Problem Context

### 2.1 Background
School administration remains heavily reliant on manual data entry, physical document storage, and siloed scheduling systems, leading to extreme inefficiencies.

### 2.2 The Challenge
Build intelligent, AI-powered solutions that automate everyday school operations, digitize records, and drastically reduce the administrative workload.

### 2.3 Core Technical Requirements (from the problem statement)
- **AI Document Processing** — automate the extraction of data from physical forms.
- **Timetable Optimization** — algorithms to resolve scheduling conflicts.
- **School ERP Automation** — centralized data flows replacing multiple legacy apps, with robust reactive state management keeping UI components perfectly synced across the dashboard.
- **The Admin Dashboard** — a centralized command center designed for minimal clicks, where admins see proactive alerts for operational bottlenecks rather than hunting for data.

### 2.4 "Think Outside the Box" (encouraged directions)
- **Predictive Resource Allocation** — using historical data to manage staff assignments.
- **Automated Attendance** — integrating RFID or computer vision seamlessly into the ERP.

### 2.5 Tech Stack Guidelines
Complete freedom — no restrictions on programming languages, frameworks, or databases. Teams are free to architect, build, and deploy their solution however they choose.

### 2.6 Evaluation Criteria
- **Innovation & Impact** — does the solution uniquely solve a real-world problem with creative approaches to traditional workflows?
- **Technical Execution** — code quality, architecture, scalable logic, modern state management, clean backend integrations.
- **UI/UX Design** — a seamless, accessible, highly responsive experience that feels intuitive to end-users.

---

## 3. Product Vision

EduOps AI is not a collection of features bolted together — it is a single connected organism where every module feeds the others. Attendance flows into predictive staffing; staffing powers automatic substitution; that leave request surfaces as a proactive admin alert. Assignment grades flow into performance analytics, which feed the early-warning system, which alerts parents. Class notes become the knowledge base that makes the Doubt Bot smarter. Every announcement, from a school holiday to a single pending fee, flows through one targeted feed.

**Design pillars:**
- **AI-first** — automation is the default, manual entry the exception.
- **Role-aware** — five roles, five tailored experiences, one shared data core.
- **Proactive, not reactive** — the system surfaces problems; users don't dig for them.
- **Learning + operations in one** — the school runs *and* teaches on the same platform.
- **Production-grade** — deployed, accessible, responsive, auditable.

---

## 4. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     PRESENTATION LAYER                        │
│   React SPA · Role-based dashboards · Responsive · Accessible │
│   State: TanStack Query (server) + Zustand (client)          │
└─────────────────────────────────────────────────────────────┘
                              │
                    REST + WebSocket (real-time)
                              │
┌─────────────────────────────────────────────────────────────┐
│                     APPLICATION LAYER                         │
│   FastAPI · Auth & RBAC · Business logic · Socket.io server   │
│   Notification/announcement engine · Approval chains ·        │
│   Classroom & chat services · Audit logging                   │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                     INTELLIGENCE LAYER                        │
│  OCR · Face recognition · Timetable solver · Predictive       │
│  staffing · Early-warning ML · Auto-grading · RAG chatbots    │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                        DATA LAYER                             │
│   PostgreSQL (relational core) · Object storage (documents,   │
│   submissions, library) · Vector store (chatbot KB)           │
└─────────────────────────────────────────────────────────────┘
```

**Design notes:**
- The relational core holds every entity as one connected model — the "centralized data flows replacing multiple legacy apps" the PS calls for.
- The real-time layer (Socket.io) powers live dashboards, live attendance, class chat, and the announcement feed.
- The intelligence layer is separate so AI/ML components scale and develop independently of core CRUD.

---

## 5. Roles & Access Control (RBAC)

Five roles, each with a distinct dashboard and permission scope. RBAC is enforced at the API layer (every endpoint checks role + ownership) and reflected in the UI.

| Role | Primary Purpose | Access Scope |
|------|----------------|--------------|
| **Super Admin / Principal** | Oversight & governance | Everything: analytics, staff mgmt, approvals, audit logs |
| **Admin / Office Staff** | Day-to-day operations | Documents, fees, admissions, data-entry oversight |
| **Teacher** | Teaching & class management | Own timetable/classes, attendance, remarks, classroom hub, syllabus planning |
| **Student** | Self-service & learning | Own profile, attendance, remarks, timetable, classrooms, doubt bot |
| **Parent** | Monitoring their child | Child's attendance, remarks, performance, fees, alerts, teacher messaging |

**Principles:** ownership-scoped access, least privilege by default, every privileged action written to an immutable audit log.

---

## 6. Core Modules

### 6.1 AI Document Processing Engine
*Addresses: AI Document Processing.*
Upload scanned physical forms (admission forms, TCs, fee receipts). An OCR pipeline extracts fields automatically and auto-populates student/staff records — no manual entry. Each document is stored with structured extracted data, routed to the right workflow, and indexed for smart search.

### 6.2 Smart Timetable Generator
*Addresses: Timetable Optimization.*
Input teachers, subjects, rooms, and constraints. A constraint-satisfaction algorithm produces conflict-free schedules. Drag-to-adjust interface with live conflict warnings. Optimizes school-wide.

### 6.3 Automated Attendance System
*Addresses: Automated Attendance.*
Two capture modes — RFID scan and computer-vision face detection. Auto-syncs to records in real time and feeds the analytics and predictive layers.

### 6.4 Predictive Resource Allocation
*Addresses: Predictive Resource Allocation.*
Pulls historical attendance and workload data, flags under/over-staffed days ahead of time, and suggests optimal staff assignments. Powers smart substitution.

### 6.5 Admin Command Center
*Addresses: The Admin Dashboard.*
The single screen admins live in — proactive alerts for bottlenecks (attendance anomalies, scheduling conflicts, pending approvals, teacher overload, fee backlogs), key metrics, and quick actions. Every critical action in ≤2 clicks. Live-updating.

### 6.6 Centralized ERP Backbone
*Addresses: School ERP Automation.*
Students, staff, fees, documents, schedules — one unified data model replacing multiple legacy apps, with reactive state keeping UI synced.

---

## 7. The Classroom Hub

A dedicated online space for each class/subject — where teaching and learning actually happen day to day (think Google Classroom, built in).

### 7.1 Class Stream / Feed
- A chronological wall per class where the teacher posts notes, announcements, materials, and links.
- Students see the latest at a glance; nothing gets lost in email.

### 7.2 Assignments
- Teacher creates an assignment with a deadline and attachments.
- Students submit files directly.
- Teacher grades submissions → the grade flows into the student's performance analytics and gradebook.
- Late submissions auto-nudge the student (and parent via the portal).

### 7.3 Notes & Resources Library
- Materials organized by subject/unit, fully searchable.
- This same material feeds the Student Doubt Bot's knowledge base, so answers stay grounded in the class's actual content.

### 7.4 Submissions Tracking
- Teacher sees who has submitted and who is pending at a glance.
- Auto-nudges to late students and their parents.

---

## 8. Chat & Discussion Rooms

Real-time communication per class, built on the existing Socket.io layer.

> **Design decision (assumption — flip if you prefer):** a **hybrid** model. A fast, casual class group chat for everyday talk, *plus* structured doubt threads for organized Q&A. This gives both the immediacy of WhatsApp-style chat and the organization of Classroom-style threads — and the doubt threads double as knowledge for the Doubt Bot.

### 8.1 Class Group Chat
- Students + teacher, real-time messaging.

### 8.2 Doubt Threads
- A student posts a doubt; others reply; the teacher marks a **verified answer**.
- Keeps Q&A organized instead of an endless scroll, and feeds the Doubt Bot.

### 8.3 Announcements Channel
- Teacher-only posting so important messages don't get buried in chat.

### 8.4 Moderation
- Teacher controls: mute, delete, pin. Important for the production-grade bar.

---

## 9. The Announcement Feed

One announcement engine, with **audience targeting** — the same system as the Unified Notification Center, now scope-aware. Each person's feed is auto-filtered to only what's relevant to them, which *is* the "minimal clicks, no hunting for data" principle in action.

### 9.1 Audience Scopes
- **School-wide** — holidays, events, fee deadlines (from Principal/Admin).
- **Class/section-specific** — e.g., "Section 9-A: bring lab coats tomorrow."
- **Subject-specific** — posted into that subject's classroom stream.
- **Role-specific** — "all teachers," "all parents."
- **Individual** — one student or parent (pending fee, meeting request).

### 9.2 Announcement Attributes
- Title + body, author, timestamp.
- Scope/audience tag.
- **Priority** — normal / important / urgent (urgent pins to top + push alert).
- Optional attachment; category (event / academic / fee / general).
- Read/unread status; optional **acknowledge** button ("I've read this").

### 9.3 Powered by Every Module
- Assignment posted → appears in that class's feed.
- Fee pending → personal announcement to that parent.
- At-risk flag → targeted alert to teacher + parent.
- Timetable change → class-scoped announcement.
- Substitute assigned → alert to the affected class.

One engine, many scopes — clean architecture and an easy story for judges.

---

## 10. Academics Suite

The full teaching-and-assessment toolset layered on top of the Classroom Hub.

### 10.1 Digital Library / E-Resources
- Book catalog with issue/return tracking.
- Repository of past papers and study material.
- Feeds the Doubt Bot's knowledge base.

### 10.2 Online Exams & Quizzes
- Teacher builds a quiz; MCQs are **auto-graded**.
- Results flow straight into performance analytics.
- The Teacher Assistant Bot can draft the questions.

### 10.3 Homework / Assignment Calendar
- Every student sees deadlines across all subjects in one unified view.
- Kills the "I forgot it was due" problem.

### 10.4 Gradebook & Report Card Automation
- Full gradebook: weighted assessments, term averages, GPA.
- This is the engine beneath the auto-generated report cards — pull grades + attendance + remarks into a formatted PDF.

### 10.5 Timetable-to-Calendar Sync
- A personal calendar per role: classes + exams + deadlines + events, all in one place.
- Draws from the timetable, exam scheduler, and homework calendar.

---

## 11. Intelligence & AI Layer

### 11.1 Early-Warning System (At-Risk Detection)
ML combines attendance trends + remark sentiment + performance trajectory (now including assignment/exam grades) into one risk signal. Auto-flags at-risk students and notifies teacher, parent, and counselor simultaneously.

### 11.2 Smart Substitution
On a teacher leave request, the system auto-suggests a free, qualified substitute using the timetable + staffing data, and posts an alert to the affected class.

### 11.3 Syllabus Pace Tracker
Tracks % of curriculum covered vs. term progress; flags subjects falling behind. Teacher (own subjects) and admin (school-wide) views.

### 11.4 Anomaly Detection
Detects sudden attendance drops, document backlogs, teacher overload, and low submission rates. Feeds the proactive alert stream.

### 11.5 Auto-Grading
MCQ quizzes and objective assessments graded automatically, feeding the gradebook and analytics.

---

## 12. Conversational AI (Chatbots)

### 12.1 Student Doubt Bot
RAG-based, grounded on the syllabus + class notes + library resources + verified doubt-thread answers, so responses stay curriculum-accurate. Logs frequent doubts → teachers get a "top 5 confusions this week" summary. Voice input supported.

### 12.2 Teacher Assistant Bot
Plans lessons against the syllabus, suggests timetable adjustments, drafts quiz/assessment questions, and summarizes a student's performance on request. Voice input supported.

### 12.3 Parent Assistant Bot
Answers "How is my child doing?" with a plain-language summary of attendance, grades, and remarks. Voice input supported.

---

## 13. Role-Specific Feature Sets

### 13.1 Student
Profile, timetable, attendance %; remark system with sentiment tags (academic / behavioral / appreciation); personal analytics (attendance + subject-wise performance); auto at-risk flag with mentor notification; classroom hubs; homework calendar; online exams; Doubt Bot.

### 13.2 Teacher
Own timetable and classes; attendance marking (RFID / CV / manual); one-click leave request with auto-substitute; bulk remark entry; syllabus progress tracker; classroom hub management (post notes, create/grade assignments, moderate chat); quiz builder; gradebook; Teacher Bot.

### 13.3 Admin / Office Staff
Document processing oversight; smart fee reminders (auto-detect + notify parents); anomaly detection; audit log; admissions and data-entry management; school-wide announcement posting.

### 13.4 Principal / Super Admin
Full analytics; staff management and approvals; all audit logs; school-wide syllabus pace, staffing, and academic-performance views.

---

## 14. The Parent Portal

- **Performance & attendance** — child's attendance %, performance graphs, remarks (with sentiment tags), grades.
- **Fee management** — status, one-tap payment, receipts.
- **Direct teacher messaging** — async, logged channel.
- **Auto-alerts** — absence today, low-attendance warning, new remark, upcoming exam, missed assignment.
- **Parent Assistant Bot** — plain-language child summaries.
- **Multi-child support** — one account, multiple children.
- **Consent / approval flows** — leave, trips, with digital signature.

---

## 15. Cross-Cutting Platform Features

### 15.1 Automation & Operations
- Auto-generated report cards (PDF).
- Bulk notification center (now the targeted Announcement Feed).
- Digital approval chains with audit trail.
- Exam seating & invigilation auto-scheduler.

### 15.2 Unified Notification / Announcement Center
- A single targeted hub for alerts, approvals, reminders, and announcements across every role and scope.

### 15.3 Accessibility & Inclusivity
- Voice input on all chatbots.
- Multilingual UI — significant impact for Indian schools.
- WCAG compliance — keyboard navigation, contrast, screen-reader labels.

### 15.4 Reliability
- Offline-first document upload with sync on reconnect.

### 15.5 Reporting
- One-click analytics export (PDF) for board meetings.

### 15.6 Search
- Smart search across all digitized records and library resources.

---

## 16. Complete Feature Catalog

Every feature planned across the project, consolidated. Nothing omitted.

**Core (from problem statement)**
1. AI Document Processing Engine (OCR from physical forms)
2. Smart Timetable Generator (constraint-satisfaction)
3. Automated Attendance — RFID mode
4. Automated Attendance — computer-vision mode
5. Predictive Resource Allocation
6. Admin Command Center (proactive alerts, minimal clicks)
7. Centralized ERP backbone (unified data model, reactive sync)

**Roles & Access**
8. RBAC (5 roles)
9. Principal/Super Admin dashboard
10. Admin/Office Staff dashboard
11. Teacher dashboard
12. Student dashboard
13. Parent dashboard

**Classroom Hub**
14. Class stream/feed
15. Assignments (create → submit → grade)
16. Notes & resources library (feeds Doubt Bot)
17. Submissions tracking with auto-nudge

**Chat & Discussion**
18. Class group chat (real-time)
19. Doubt threads with verified answers
20. Teacher-only announcements channel
21. Chat moderation (mute/delete/pin)

**Announcement Feed**
22. Targeted announcements (school / class / subject / role / individual)
23. Priority levels + pinned urgent alerts
24. Read/unread + acknowledge tracking

**Academics Suite**
25. Digital library / e-resources + issue-return tracking
26. Past-papers & study-material repository
27. Online exams & quizzes with MCQ auto-grading
28. Homework/assignment calendar (all subjects, one view)
29. Gradebook (weighted assessments, term averages, GPA)
30. Report card automation (PDF)
31. Timetable-to-calendar sync (per role)

**Intelligence Layer**
32. Early-warning at-risk detection (multi-signal ML)
33. Smart substitution (auto-suggest on leave)
34. Syllabus pace tracker
35. Anomaly detection (attendance, backlog, overload, submissions)
36. Auto-grading engine

**Conversational AI**
37. Student Doubt Bot (RAG, logs FAQs)
38. Teacher Assistant Bot (planning, drafting, summaries)
39. Parent Assistant Bot (plain-language summaries)
40. Voice input across all chatbots

**Student Features**
41. Remark system with sentiment tags
42. Personal analytics (attendance + performance graphs)
43. Auto at-risk flag with mentor notification

**Teacher Features**
44. One-click leave request with auto-substitute
45. Bulk remark entry
46. Syllabus progress tracker

**Admin Features**
47. Smart fee reminders (auto-detect + notify)
48. Audit log of every action

**Parent Portal**
49. Child performance & attendance view
50. Fee status + one-tap payment + receipts
51. Direct teacher messaging (async, logged)
52. Parent auto-alerts
53. Multi-child support
54. Consent/approval flows with digital signature

**Cross-Cutting**
55. Bulk notification center (targeted feed)
56. Digital approval chains with audit trail
57. Exam seating + invigilation auto-scheduler
58. Multilingual UI
59. WCAG accessibility
60. Offline-first document upload with sync
61. Analytics export (PDF)
62. Smart search across records & library

---

## 17. Data Model

### 17.1 Core Tables
`students`, `staff`, `departments`, `subjects`, `rooms`, `timetable_slots`, `attendance_records`, `documents` (with `extracted_data` JSON), `alerts`, `fee_records`, `academic_years`

### 17.2 Extended Tables
- `users`, `roles` — auth and RBAC.
- `remarks` — sentiment_tag, author, student, timestamp.
- `parents`, `parent_student` — parent accounts + multi-child links.
- `leave_requests`, `substitutions` — leave + resolved substitute assignments.
- `syllabus_progress` — per subject, % covered vs. timeline.
- `notifications`, `announcements` — targeted feed (scope, priority, category, ack status).
- `approvals` — approval chains + status + audit trail.
- `messages` — parent–teacher channel.
- `audit_log` — immutable privileged-action record.
- `report_cards` — generated PDFs + source snapshot.
- `exam_schedule`, `seating_plan` — scheduling + invigilation.
- `risk_flags` — early-warning output + contributing signals.
- `chatbot_logs` — logged doubts + KB references.

### 17.3 Classroom & Academics Tables
- `classrooms` — one per class/subject, members, teacher.
- `stream_posts` — class feed posts + attachments.
- `assignments` — title, deadline, attachments, class.
- `submissions` — student, assignment, file, grade, status.
- `resources` — library/notes items, subject/unit, searchable + KB link.
- `library_items`, `loans` — book catalog + issue/return.
- `quizzes`, `questions`, `quiz_attempts` — online exams + auto-grading.
- `gradebook_entries` — weighted assessment scores.
- `calendar_events` — unified per-role calendar (classes, exams, deadlines, events).
- `chat_channels`, `chat_messages`, `doubt_threads`, `thread_replies` — chat + discussion.

---

## 18. Technology Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Frontend** | React + Tailwind + shadcn/ui | Fast, polished, responsive, accessible |
| **Charts** | Recharts | Dashboards & performance graphs |
| **Server state** | TanStack Query | Fetching, caching, live sync |
| **Client state** | Zustand | Modern reactive state the judges ask about |
| **Backend** | FastAPI (Python) | Native fit for AI/ML; clean, typed, fast |
| **ORM** | SQLAlchemy | Robust relational mapping |
| **Database** | PostgreSQL | Relational core fits interconnected data |
| **Object storage** | S3-compatible | Documents, submissions, library files |
| **Vector store** | pgvector / Qdrant | Chatbot knowledge base |
| **OCR** | Tesseract | Document field extraction |
| **Computer vision** | OpenCV + face_recognition | Attendance |
| **ML** | scikit-learn | Predictive staffing + early-warning |
| **Chatbots** | RAG + vector store | Curriculum-grounded answers |
| **Real-time** | Socket.io | Dashboards, attendance, chat, feed |
| **Deployment** | Vercel + Railway/Render | Live, production-grade URL |

> **State management note:** the PS mentions Riverpod, a Flutter library. With full tech freedom, this platform uses React, and TanStack Query + Zustand delivers the same "robust reactive state, UI perfectly synced" goal. State this explicitly when presenting.

---

## 19. How Modules Interconnect

**Flagship chain:**
```
Attendance (CV/RFID) → historical data → Predictive Staffing
   → flags under-staffed days → Teacher leave request (1 click)
   → Smart Substitution suggests sub → Alert on Admin Command Center
   → Class-scoped announcement to affected students
```

**Learning chain:**
```
Assignment/quiz → grade (auto or manual) → Gradebook
   → Performance analytics → Early-Warning ML → at-risk flag
   → Teacher + Parent + Counselor notified
```

**Knowledge chain:**
```
Class notes + library + verified doubt answers → Doubt Bot KB
   → smarter, curriculum-grounded answers
```

**Document chain:**
```
Physical form scanned → OCR → auto-populates ERP record
   → routed to workflow → indexed for search
```

**Communication chain:**
```
Any event (fee / assignment / at-risk / timetable change)
   → Announcement engine → targeted to the right scope
   → appears only in the relevant feeds
```

Every arrow is where two "features" become one product.

---

## 20. Team Split & Build Plan

### 20.1 Team Split (3 people)
- **Person A — Frontend:** all 5 dashboards, timetable UI, attendance view, classroom hub, chat, announcement feed, calendars, parent portal, chatbot UIs.
- **Person B — Backend + DB:** APIs, auth & RBAC, all schemas, real-time socket layer, notification/announcement/approval/audit engines, classroom & chat services, gradebook.
- **Person C — AI/ML:** OCR, face-recognition attendance, timetable solver, predictive staffing, early-warning model, auto-grading, RAG chatbots.

Everyone converges on integration in the final stretch.

### 20.2 Phased Build (6-month runway)

**Phase 1 — Foundation:** schema (core + extended), auth, RBAC, 5 role skeletons, CRUD APIs, frontend layout/routing/design system.

**Phase 2 — Core Modules:** document OCR, timetable solver + UI, attendance (RFID + CV), ERP data flows.

**Phase 3 — Classroom & Communication:** classroom hub (stream, assignments, resources), chat + doubt threads, targeted announcement feed.

**Phase 4 — Academics Suite:** gradebook, online exams + auto-grading, homework calendar, digital library, calendar sync, report cards.

**Phase 5 — Intelligence Layer:** predictive staffing, early-warning, smart substitution, anomaly detection, proactive alerts.

**Phase 6 — Conversational AI:** all three bots, voice input.

**Phase 7 — Parent Portal & Cross-Cutting:** full parent portal, notification center, approval chains, exam scheduler, multilingual, accessibility, offline-first, analytics export.

**Phase 8 — Polish & Deploy:** responsive + WCAG pass, error handling, demo-data seeding, live deployment, presentation rehearsal.

---

## 21. Mapping to Evaluation Criteria

**Innovation & Impact** — interconnected modules (attendance → staffing → substitution → alert; grades → early-warning → parent) rethink traditional workflows; multilingual, offline-first, and wellbeing-aware features deliver real impact for Indian schools.

**Technical Execution** — layered architecture, relational core, separate intelligence layer; modern state management (TanStack Query + Zustand); real-time sync; clean FastAPI integrations; audit logging and approval chains signal production-grade thinking.

**UI/UX Design** — five role-aware dashboards; "minimal clicks" as an explicit law; auto-filtered feeds so users never hunt for data; accessibility baked in; responsive across devices.

**Production-Grade (overarching)** — deployed to a live URL, not localhost.

---

## 22. Suggested Demo Core

The full catalog is the product *vision* — and with a 6-month runway it's buildable. But a jury experiences a ~10-minute demo, not 62 features. To protect the win, build this subset to a polished, deployed, production-grade finish and present the rest as a credible roadmap the architecture already supports. Nothing below is cut from the plan — this is just what to have flawless on demo day.

- The 5 role-based dashboards + RBAC
- Document scan → auto-populated record
- Timetable conflict auto-resolution
- Computer-vision attendance (live)
- Admin Command Center with real proactive alerts
- Classroom Hub: post note → create assignment → submit → grade → grade appears in analytics
- Targeted Announcement Feed (show school vs. class vs. individual scoping)
- One online quiz with auto-grading
- All three chatbots (including a voice query)
- The flagship interconnection chain, end to end
- Parent portal on a phone (responsive proof)
- Multilingual toggle

Everything else — digital library, exam seating, approval chains, offline sync — is shown as polished UI + roadmap.

---

## 23. Demo Checklist

- [ ] Live deployed URL, tested
- [ ] Seeded with realistic demo data
- [ ] Walk the flagship chain live (attendance → leave → substitute → alert)
- [ ] Document scan → auto-populated record, end to end
- [ ] Timetable conflict auto-resolved on screen
- [ ] Computer-vision attendance in real time
- [ ] Classroom Hub full loop: note → assignment → submission → grade → analytics
- [ ] Post a targeted announcement at three different scopes
- [ ] Run an auto-graded quiz
- [ ] Trigger an at-risk flag → show multi-role notification
- [ ] Demo all three chatbots, including a voice query
- [ ] Parent portal on a phone (responsive)
- [ ] Toggle language (multilingual proof)
- [ ] Admin command center updating live
- [ ] Architecture diagram ready to explain interconnection
- [ ] One-line answer to "what's your state management?" → TanStack Query + Zustand

---

*End of documentation — v2.0*
