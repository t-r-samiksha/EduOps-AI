# EduOps AI — Demo Run Sheet (v2, 6:00)

**School:** Shikshaa Public School · `school_id 55621` · **Runtime:** 6:00 · single take
**Order:** Principal → Teacher → Admin → Parent → Student → Principal
**Recorded at:** `localhost:5173` · **Windows:** 5 pre-authenticated browser profiles

Six minutes. Two closed loops in depth, the academic spine, then breadth as a montage — opening
and closing on the same person, so it reads as one arc rather than a tour.

> **Seeded by** `backend/scripts/seed_shikshaa.py`. Every derived thing comes from the real code
> path: the timetable from the CP-SAT solver, the risk flags from the nightly scorer, the report
> cards from `report_card_service`, the bot corpus from real uploads and real embeddings.

---

## Credentials

**Password for every account: `1234567890`**

| Role | Login | Who |
| --- | --- | --- |
| Principal | `principal@shikshaa.in` | Lakshmi Subramanian |
| Admin | `admin@shikshaa.in` | Ravi Shankar |
| Teacher | `t5@shikshaa.in` | **Deepa Krishnan — homeroom of Grade 3-A. The teacher window for this demo.** |
| Student | `s21@shikshaa.in` | **Myra Sinha, Grade 3-A — the high-risk student.** |
| Student | `s25@shikshaa.in` | Kiara Jain, Grade 3-A — healthy, for contrast |
| Parent | `p6@shikshaa.in` | **Prakash Sharma — children in TWO grades (Meera, 1-A and Myra, 3-A).** |

Other accounts: teachers `t1`–`t8`, students `s1`–`s30`, parents `p1`–`p6`, all `@shikshaa.in`.

### The two people the demo is built around

**Myra Sinha (`s21`)** is the only **high**-risk student in the school — score **0.649**, from 40%
attendance, a 23% average and three strongly negative remarks. Her classmate **Kiara Jain (`s25`)**
sits at 95% attendance with no flag, so the contrast lives inside one class.

**Prakash Sharma (`p6`)** is Myra's father *and* has a child in Grade 1. That single fact powers
three beats: the child selector is meaningful, the Grade 3 announcement is visibly **absent** from
Meera's feed, and the parent portal shows a genuinely urgent flag.

---

## Before you hit record

### BLOCKER 1 — `.env` must not be on screen

It holds the Supabase password, service-role key and Gemini API key. If VS Code appears in a
single frame, those are in the recording — and hackathon submissions get downloaded.

**Fix:** close the `.env` tab, close any terminal showing `DATABASE_URL`, and record the
**browser window only**.

### BLOCKER 2 — enrol faces for CV attendance

Shikshaa has **0 face embeddings**. A seed script cannot fabricate a face, so Act I's opening beat
needs you to enrol a few first.

**Fix:** `POST /attendance/enroll` with photos of 3–4 Grade 3-A students (`s21`–`s25`). Include
Myra if you can — recognising the student the rest of the video is about is a nice touch.

Then say *"the students we've enrolled"*, never *"the whole class"*. A judge who counts faces and
catches an overclaim stops believing everything after it.

### Verified in the database — do not re-seed

| Surface | Rows | | Surface | Rows |
| --- | --- | --- | --- | --- |
| Students / teachers | 30 / 8 | | Timetable periods | 84 |
| Classes | 6 | | Attendance records | 600 |
| **High-risk flags** | **1** | | Medium-risk flags | 5 |
| Gradebook entries | 270 | | Report cards | 12 |
| Assignments | 18 | | Quizzes (with real questions) | 6 / 18 |
| Resources | 9 | | **Bot corpus chunks** | **10** |
| Doubt threads | 3 | | Verified answers in corpus | 1 |
| Fee records outstanding | 40 | | Announcements (school / class) | 1 / 1 |
| Exams / seats | 6 / 30 | | Library loans (1 overdue) | 3 |
| Syllabus plans / checkpoints | 18 / 102 | | Notifications dispatched | 17 |

Re-running the seed is unnecessary risk. If you must, use `--skip-rag --skip-timetable`.

### Final checklist

- [ ] **Do not run the test suite while recording.** It holds pooled connections for 13 minutes.
- [ ] **Five** pre-authenticated browser profiles. Never record a login form.
- [ ] Pre-open every page in tab order per window. You switch tabs, not navigate menus.
- [ ] **Pre-select Grade 3-A** in Gradebook, Remarks and Student Analytics — their "choose a
      class" states are correct but read as empty on camera.
- [ ] 100% zoom, 1920×1080, bookmarks bar hidden, **light theme** (compresses better).
- [ ] Clear the admin notification bell first, so the badge incrementing in Act I reads as real.
- [ ] One PDF on the desktop named believably — `Grade 3 Fractions Practice.pdf`.
- [ ] Rehearse **two** Doubt Bot questions answerable from the seeded Grade 3 Fractions resource.

---

## The argument: one nervous system, not twenty screens

Every other team will demo a school ERP as a feature tour — attendance, then fees, then a chatbot.
Judges see six of those and remember none.

This build has something almost none of them have: **the data actually flows.** A camera marks
attendance; that attendance is 50% of a risk score; a teacher's typed remark is sentiment-analysed
into the same score; the resulting flag notifies the homeroom teacher and every linked guardian
automatically; an admin reads the very remarks behind the number before logging an intervention.
Separately, a worksheet posted to a class stream becomes a retrievable source the student's Doubt
Bot cites back — and a teacher-verified answer joins that corpus for the whole grade.

**Two closed loops in depth, then the academic spine, then breadth as a montage.** Depth earns
belief; the montage earns scope. In that order, never the reverse.

---

## COLD OPEN · 0:00–0:20 · Principal

### 0:00 · `principal@shikshaa.in` → `/principal`

**Do:** Open on the principal's dashboard. Do not click. Let the numbers sit for a beat before
you speak.

> **SAY:** "This is what the head of Shikshaa Public School sees at eight in the morning. Six
> students flagged as at risk, one of them urgently. A teacher out sick on Monday. Forty fee
> records outstanding. Nobody built this list by hand — and by the end of this video you'll have
> watched exactly where one of these came from, and who closed it."

*Why open here:* you start at the consequence and work backwards, and you promise a payoff you
actually deliver at 5:35.

---

## ACT I — The early-warning loop · 0:20–2:15

*A camera, a sentence a teacher typed, and a parent's phone — connected by a score nobody
assembled by hand.*

### 0:20 · Teacher `t5@shikshaa.in` → `/teacher/attendance`

**Do:** Run the CV attendance capture for Grade 3-A. Show the matched students, then the day
register with the period marked.

> **SAY:** "Attendance starts with a camera, not a register. OpenCV matches faces against the
> student embeddings we've enrolled and marks the period. The teacher confirms — the machine
> doesn't get the last word."

*If recognition misses:* "…and where it isn't confident, it hands back to the teacher." Switch to
the manual register. A graceful fallback reads as maturity, not failure.

### 0:48 · Teacher → `/teacher/remarks`

**Do:** Grade 3-A already selected. **Myra Sinha's row already shows three existing remarks** —
point at those first. Then type a fourth for a different student and save.

> **SAY:** "Now the part that's usually dead weight in an ERP — a teacher's written observation.
> Here it isn't just stored. The sentiment is scored, and it becomes fifteen percent of that
> student's risk signal, next to attendance at fifty and grades at thirty-five. Look at Myra's row
> — three concerns already logged, so nobody records the same worry twice."

*The strongest true thing you can say here:* Myra's attendance and grades alone score her **0.539
— medium**. It is the remark sentiment that carries her to **0.649 — high**. A sentence a teacher
typed genuinely moved the classification. That is not a slide; it is arithmetic you can point at.

### 1:13 · Admin `admin@shikshaa.in` → `/admin/risk`

**Do:** Command Center → **Early-Warning**. Open **Myra Sinha's high-risk flag**. Expand
**Teacher remarks**, then **Actions taken**. Log an intervention: action *"called parent"*, note
*"No answer, will retry Thursday."*

> **SAY:** "The flag says attendance is forty percent, the average is twenty-three, and remark
> sentiment is trending negative. So — which remarks? They're right here, on the flag itself. The
> admin reads the actual evidence, not just a number, then records what the school did about it.
> The next teacher to open Myra sees that history."

**Say this over the same screen — do not navigate:**

> **SAY:** "And every sensitive action here writes an audit entry — who acted, on what, when. If
> an algorithm influenced a decision about a child, somebody has to answer for it later."

*The audit trail is real* (`services/audit_log.py`) but **has no frontend page**. Say the line over
the intervention you just logged. Do **not** go looking for `/admin/audit` — that route does not
exist.

### 1:50 · Parent `p6@shikshaa.in` → `/parent/announcements`

**Do:** Show the feed. Switch child to **Meera (Grade 1-A)** and show that the Grade 3 field-trip
notice is **absent**. Switch back to Myra and it appears.

> **SAY:** "Communication is scoped, not broadcast. Same parent, two children, two different
> grades — and the Grade 3 field trip notice simply isn't in his Grade 1 daughter's feed. The
> audience is computed, and the school can see who acknowledged what."

### 1:59 · Parent → `/parent/child`

**Do:** With Myra selected, show attendance, the risk banner and the teacher's remarks.

> **SAY:** "And her father already knows. The flag notified the homeroom teacher and every linked
> guardian the moment it was raised — nobody had to remember to make a call."

*Blackout:* never type a student ID here. The portal resolves the child automatically.

---

## ACT II — The learning loop · 2:15–3:40

*A worksheet becomes something the AI can cite. A verified answer becomes something the whole
grade inherits.*

### 2:15 · Teacher `t5` → `/teacher/classroom`

**Do:** Grade 3-A stream. Publish a **Material** post with your PDF, **Share with the whole
grade** ticked. Point at the **Bot-searchable** tag, then click the file to open it in the in-app
viewer.

> **SAY:** "A teacher shares a worksheet with their class. One upload. Watch what it becomes —
> filed in the resource library for the whole grade, chunked, embedded, tagged bot-searchable. And
> it opens right here. Nobody downloads anything."

*Verify after posting* that the tag rendered — it only appears once `resource_id` is set:

```bash
cd backend
venv/Scripts/python.exe -c "from app.database import engine; from sqlalchemy import text; \
print(engine.connect().execute(text('select id,file_name,resource_id from attachments order by id desc limit 3')).fetchall())"
```

### 2:40 · Student `s21@shikshaa.in` → `/student/doubt-bot`

**Do:** Ask your rehearsed question. Let the citation render. Point at it.

> **SAY:** "Same minute, the student asks their doubt bot. It answers from her grade's own material
> — and it cites it. Not a general-purpose model guessing about fractions. Her teachers' material,
> scoped to Grade 3."

*The seeded corpus already covers:* fractions (numerator/denominator, adding 1/2 + 1/4, 3/5 of 20),
verbs and tenses, and the water cycle. Ask about one of those and it will answer from a real
source. **Rehearse two** — this is the only beat that depends on retrieval quality.

### 3:02 · Student → Teacher — `/student/doubts` → `/teacher/doubts`

**Do:** Grade 3-A already has **3 open doubts**. Post a new one as `s21`, then cut to `t5`, open
it, reply, **Mark verified**.

> **SAY:** "When the bot isn't enough, the question goes to a human. The teacher answers, and marks
> it verified — and that answer joins the knowledge base for the entire grade. One student's
> question becomes every student's answer, with a teacher's name on it. Any teacher who teaches the
> class can verify, not just the homeroom teacher — because the person qualified to judge a maths
> answer is the one who teaches maths."

*There is already one verified answer in the corpus* (about why a puddle dries up), so the claim is
demonstrable even if your live verification is slow.

### 3:22 · Three windows — student bot · `/teacher/assistant` · `/parent/bot`

**Do:** Three fast cuts. Student bot (open). Teacher Assistant Bot as `t5` — ask about her class.
Parent Bot as `p6` — ask about his child.

> **SAY:** "Three chatbots, one retrieval stack, three different scopes. The student gets her
> grade's material. The teacher gets her own classes' data. The parent gets his own child — and
> nothing else. Role-aware AI isn't three prompts; it's three permission boundaries."

*Eighteen seconds for the whole triptych.* The point is the boundary, not the answers.

---

## ACT III — The academic spine · 3:40–4:45

*Set work, see it land, sit the test, publish the record.*

### 3:40 · Teacher → Student — `/teacher/assignments` → `/student/calendar`

**Do:** Create an assignment with a near deadline as `t5`. Cut to `s21`'s **Homework Calendar** —
the timeline is already populated: **Fractions worksheet 2 is overdue**, *Reading comprehension*
is due today, *Science: plants and sunlight* is later this week, plus a quiz and an exam.
**Click the overdue card** and land on the assignment itself, highlighted.

> **SAY:** "A teacher sets work. The student's calendar ranks every deadline by urgency — overdue
> first, then today, then this week — across assignments, quizzes and exams together. And a
> deadline isn't a dead end: click it and you're on the actual assignment."

*This demos beautifully because the buckets are genuinely populated* — an overdue item, one due
today, and one later, without you staging anything.

### 4:02 · Student `s21` → `/student/quizzes`

**Do:** Start **"Grade 3 - A — Fractions check"** (3 real questions, 10-minute limit). Answer one
or two, submit, show the auto-graded score.

> **SAY:** "Quizzes are timed and auto-graded, and the attempt lives server-side — the clock isn't
> in the browser where it could be edited."

### 4:18 · Teacher `t5` → `/teacher/gradebook`

**Do:** Marks tab → enter one mark → **Report Cards** tab → **Generate all** → **Preview & Print**
→ scroll to the remarks section at the bottom.

> **SAY:** "And it compiles. Weighted marks, GPA on a four-point scale, attendance for the year —
> and the same remarks we were reading at the start of this video, on one printable transcript.
> Enter a mark, publish a report card, done."

*This is the closing argument.* Myra's remarks from 0:48 appearing here at 4:18 proves it's one
system. Point at it and pause.

### 4:38 · Teacher → `/teacher/syllabus-pace`

**Do:** Show expected vs actual, with the drift column.

> **SAY:** "And the school can see whether the syllabus is actually on schedule — expected against
> actual coverage, per class and subject, with the drift called out."

*The spread is deliberate:* Mathematics is **behind**, English is **on pace**, Science is **ahead**,
so the status column shows all three states at once rather than one value repeated.

---

## ACT IV — And it runs the school · 4:45–5:35

*Fifty seconds, six screens, no lingering. Proving scope, not explaining features.*

### 4:45 · Admin → `/admin/timetable`

**Do:** Hit **Generate** and let the solver run on camera. Show the filled grid.

> **SAY:** "A constraint solver builds the entire timetable — teacher availability, room types, lab
> requirements, weekly period caps. Eighty-four periods across six classes, and every Science
> period routed into the one science lab. When it's impossible, it names the constraint that made
> it impossible instead of just failing."

*True detail worth landing:* Anjali Menon is unavailable all Friday, and the solver routes around
her rather than being handed a trivially free grid.

### 4:59 · Admin → `/admin/staffing`

**Do:** Approve **Anjali Menon's pending leave for Monday 24 August**. Show the suggested
substitutes.

> **SAY:** "Remember the teacher out sick in the very first shot? Approving that leave proposes
> substitutes who are genuinely free that period and qualified to teach that subject."

*Payoff:* closes a thread planted at 0:00.

### 5:11 · Admin → `/admin/fees`

**Do:** Show the outstanding records, open the payment-request queue, approve one.

> **SAY:** "Fees invoice themselves nightly. Forty records outstanding here. Parents upload proof of
> payment, an admin confirms it, the ledger updates — and a parent can't open two claims on the
> same fee."

### 5:21 · Admin → `/admin/ocr`

**Do:** Drop a marksheet in, show the extracted structured fields.

> **SAY:** "Admissions paperwork is read by OCR into structured fields. Nobody retypes a marksheet."

### 5:29 · Admin → `/admin/exams` and `/admin/library`

**Do:** Exam seating plan, then the library queue with its overdue loan. Two flicks.

> **SAY:** "Exam seating is generated with invigilation duties. The library tracks issues, returns
> and overdue books."

---

## CLOSE · 5:35–6:00 · Principal

### 5:35 · Principal → `/principal/risk`

**Do:** Open **Myra's flag** — now carrying the admin's intervention. Click **Resolve**.

> **SAY:** "Back to where we started. That flag now carries what the school actually did about it —
> so the head of school isn't resolving a number, she's resolving a case with a history. And only
> she can close it."

### 5:48 · Principal → `/principal`

**Do:** Return to the dashboard from the first frame. The count is down by one. Hold still. Stop
talking a beat before you stop recording.

> **SAY:** "Five roles, one system. A camera marks a register. A sentence a teacher typed moves a
> risk score. A father is told without anyone remembering to call. A worksheet becomes something a
> student can ask questions of. And every step of it is on the record. That's not twenty features —
> that's one nervous system for a school."

*End on the frame you opened on, one number lighter.*

---

## Blackout list — never on camera

| Don't show | Why | Instead |
| --- | --- | --- |
| `.env`, or a terminal printing `DATABASE_URL` | Live Supabase password, service-role key, Gemini key | Record the browser window only |
| `/admin/audit` | No such route — the audit trail has no UI | Say the audit line over the intervention |
| Any page before a class is selected | Correct behaviour, reads as empty on camera | Pre-select Grade 3-A everywhere |
| A student ID typed by hand | Undercuts the claim that the system knows who's who | Class → student picker, or `p6`'s own children |
| "The whole class was recognised" | Only the faces you enrolled exist | "The students we've enrolled" |
| The `sam` or Riverside schools | Different data, different logins, breaks the narrative | Stay in Shikshaa throughout |
| The full test suite running | Competes for pooled connections for 13 minutes | Run it before, never during |
| Wide tables scrolled sideways | Scrollbars are hidden app-wide, so a cut edge looks like a bug | Full-screen; keep tables in frame |
| Dark mode | Compresses worse; thin borders vanish | Light theme |

---

## If it breaks mid-take

**A page errors** — "…and that's a real system talking to a real database, so let me reload rather
than pretend." Judges forgive a reload; they don't forgive a fake.

**The bot answers badly** — "Retrieval is scoped to this grade's material, so if it hasn't been
taught yet the bot won't invent it —" then ask your second rehearsed question. Refusing to
hallucinate is a selling point.

**Face recognition misses** — "Confidence was low, so it defers to the teacher." Switch to the
manual register.

**The solver takes too long** — talk over it: "it's solving eighty-four periods against teacher,
room and lab constraints, so this is real work, not a lookup." Dead air is the only failure here.

**You're running long** — cut in this order: exams/library (0:06), OCR (0:08), syllabus pace (0:07),
the quiz (0:16). **Never cut** the intervention beat (1:13), the bot citation (2:40), or the
report-card callback (4:18).

---

## Timing card — keep this visible while recording

| Time | Role / login | Page | Beat |
| --- | --- | --- | --- |
| 0:00 | principal | `/principal` | Cold open, the promise |
| 0:20 | t5 | `/teacher/attendance` | CV attendance, Grade 3-A |
| 0:48 | t5 | `/teacher/remarks` | Myra's remarks → 15% of risk |
| 1:13 | admin | `/admin/risk` | Evidence + intervention + audit line |
| 1:50 | p6 | `/parent/announcements` | Scoped: absent from Grade 1 feed |
| 1:59 | p6 | `/parent/child` | Already notified |
| 2:15 | t5 | `/teacher/classroom` | Worksheet → indexed |
| 2:40 | s21 | `/student/doubt-bot` | Bot cites the material |
| 3:02 | s21 → t5 | `/*/doubts` | Verified → corpus |
| 3:22 | s21 / t5 / p6 | 3 bots | Three scopes, one stack |
| 3:40 | t5 → s21 | `/student/calendar` | Timeline + click-through |
| 4:02 | s21 | `/student/quizzes` | Fractions check, timed |
| 4:18 | t5 | `/teacher/gradebook` | Report card, remark callback |
| 4:38 | t5 | `/teacher/syllabus-pace` | Drift: behind / on pace / ahead |
| 4:45 | admin | `/admin/timetable` | Solver, 84 periods |
| 4:59 | admin | `/admin/staffing` | Substitute (payoff) |
| 5:11 | admin | `/admin/fees` | Proof → approve |
| 5:21 | admin | `/admin/ocr` | Marksheet → fields |
| 5:29 | admin | `/admin/exams` | Seating, library |
| 5:35 | principal | `/principal/risk` | Resolve Myra's case |
| 5:48 | principal | `/principal` | Close on frame one |
