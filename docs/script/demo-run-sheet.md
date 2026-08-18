# EduOps AI — Demo Run Sheet (v1, 5:10)

**School:** Shikshaa Public School · `school_id 55621` · **Runtime:** 5:10 · single take
**Order:** Admin → Teacher → Parent → Student · **4 role switches**
**Recorded at:** `localhost:5173`

The short cut. Two closed loops in depth, then breadth as a montage — because a tour of twenty
screens loses to one fact you can watch travel.

> **This is the 5-minute version.** [`demo-run-sheet-v2.md`](demo-run-sheet-v2.md) is the 6-minute
> cut: it adds the Principal (opening *and* closing, so all five roles appear), the scoped
> announcement feed, the three-bot triptych, the homework-calendar timeline, a live quiz and
> syllabus pace. **Prefer v2 unless you are hard-capped at five minutes.**

> Seeded by `backend/scripts/seed_shikshaa.py`. The timetable comes from the real CP-SAT solver,
> the risk flags from the real nightly scorer, the bot corpus from real uploads and embeddings.

---

## Credentials

**Password for every account: `1234567890`**

| Role | Login | Who |
| --- | --- | --- |
| Admin | `admin@shikshaa.in` | Ravi Shankar |
| Teacher | `t5@shikshaa.in` | **Deepa Krishnan — homeroom of Grade 3-A** |
| Student | `s21@shikshaa.in` | **Myra Sinha, Grade 3-A — the high-risk student** |
| Parent | `p6@shikshaa.in` | **Prakash Sharma — Myra's father, also has a child in Grade 1** |

A principal account also exists (`principal@shikshaa.in`) but this cut does not use it — v2 does.

**Myra Sinha** is the only **high**-risk student in the school: score **0.649** from 40%
attendance, a 23% average and three strongly negative remarks. Her classmate **Kiara Jain
(`s25`)** is at 95% with no flag, so the contrast sits inside one class.

---

## Before you hit record

### BLOCKER 1 — `.env` must not be on screen

It holds the Supabase password, service-role key and Gemini API key. If VS Code appears in one
frame, those are in the recording — and hackathon submissions get downloaded.

**Fix:** close the `.env` tab, close any terminal showing `DATABASE_URL`, record the **browser
window only**.

### BLOCKER 2 — enrol faces for CV attendance

Shikshaa has **0 face embeddings**. A script cannot fabricate a face.

**Fix:** `POST /attendance/enroll` with photos of 3–4 Grade 3-A students (`s21`–`s25`). Then say
*"the students we've enrolled"*, never *"the whole class"*.

### Verified in the database — do not re-seed

30 students · 8 teachers · 6 classes · **84 timetable periods** · 600 attendance records ·
**1 high-risk + 5 medium-risk flags** · 270 gradebook entries · 12 report cards · 18 assignments ·
6 quizzes with real questions · 9 resources · **10 bot-corpus chunks** · 3 doubt threads (1 with a
verified answer in the corpus) · 40 outstanding fee records · 6 exams with seating · 1 pending
leave request · 17 notifications dispatched.

### Final checklist

- [ ] **Do not run the test suite while recording** — it holds pooled connections for 13 minutes.
- [ ] Four pre-authenticated browser profiles. Never record a login form.
- [ ] Pre-open every page in tab order. You switch tabs, not navigate menus.
- [ ] **Pre-select Grade 3-A** in Gradebook and Remarks — their "choose a class" states are
      correct but read as empty on camera.
- [ ] 100% zoom, 1920×1080, bookmarks bar hidden, light theme.
- [ ] Clear the admin notification bell first.
- [ ] One PDF named believably — `Grade 3 Fractions Practice.pdf`.
- [ ] Rehearse **two** Doubt Bot questions answerable from the seeded Grade 3 material.

---

## The argument: one nervous system, not twenty screens

Every other team will demo a school ERP as a feature tour. Judges see six of those and remember
none.

This build has something almost none of them have: **the data actually flows.** A camera marks
attendance; that attendance is 50% of a risk score; a teacher's typed remark is sentiment-analysed
into the same score; the flag notifies the homeroom teacher and every linked guardian
automatically; an admin reads the actual remarks before logging an intervention. Separately, a
worksheet posted to a class stream becomes a source the student's Doubt Bot cites back.

**Two loops in depth, then breadth as a montage.** Depth earns belief; the montage earns scope.

---

## ACT I — The early-warning loop · 0:00–2:25

### 0:00 · Cold open · Admin `admin@shikshaa.in` → Command Center

**Do:** Open on the alert feed, scrolled to show the risk flags and the pending leave request.
Don't click.

> **SAY:** "This is Shikshaa Public School's operations desk on a Tuesday morning. Six students
> flagged as at risk, one of them urgently. A teacher out sick on Monday. Forty fee records
> outstanding. Nobody assembled this list. I want to show you where one of these came from."

### 0:22 · Teacher `t5@shikshaa.in` → `/teacher/attendance`

**Do:** Run the CV attendance capture for Grade 3-A. Show the matched students, then the day
register.

> **SAY:** "Attendance starts with a camera, not a register. OpenCV matches faces against the
> student embeddings we've enrolled and marks the period. The teacher confirms — the machine
> doesn't get the last word."

*If recognition misses:* "…and where it isn't confident, it hands back to the teacher." Switch to
the manual register.

### 0:52 · Teacher → `/teacher/remarks`

**Do:** Grade 3-A selected. **Myra's row already shows three remarks** — point at those. Type a
fourth for another student, tag it **Behavioral**, save.

> **SAY:** "Now the part that's usually dead weight in an ERP — a teacher's written observation.
> Here the sentiment is scored, and it becomes fifteen percent of that student's risk signal, next
> to attendance at fifty and grades at thirty-five."

*The strongest true thing you can say:* Myra's attendance and grades alone score **0.539 —
medium**. The remark sentiment is what carries her to **0.649 — high**. A sentence a teacher typed
genuinely changed the classification.

### 1:20 · Admin → `/admin/risk`

**Do:** Command Center → **Early-Warning** → open **Myra's high-risk flag**. Expand **Teacher
remarks**, then **Actions taken**. Log an intervention: *"called parent"* / *"No answer, will retry
Thursday."*

> **SAY:** "The flag says attendance is forty percent, the average twenty-three, and remark
> sentiment negative. So — which remarks? They're right here, on the flag. An admin reads the
> evidence, not just a number, then records what the school did. The next teacher sees that
> history. And every action here writes an audit entry — if an algorithm influenced a decision
> about a child, somebody has to answer for it later."

*The audit trail is real but has **no UI**.* Say the line over this screen. Do **not** navigate to
`/admin/audit` — that route does not exist.

### 1:52 · Parent `p6@shikshaa.in` → `/parent` and `/parent/child`

**Do:** With Myra selected, show attendance, the risk banner, the remarks. Then switch child to
**Meera (Grade 1-A)** to show the selector is real.

> **SAY:** "And her father already knows. The flag notified the homeroom teacher and every linked
> guardian the moment it was raised — nobody had to remember to make a call. He has another child
> in Grade 1, and her view is entirely her own."

*Blackout:* never type a student ID here.

---

## ACT II — The learning loop · 2:25–3:55

### 2:25 · Teacher `t5` → `/teacher/classroom`

**Do:** Grade 3-A stream. Publish a **Material** post with your PDF, **Share with the whole grade**
ticked. Point at the **Bot-searchable** tag, then click the file to open it in the viewer.

> **SAY:** "A teacher shares a worksheet with their class. One upload. Watch what it becomes —
> filed in the resource library for the whole grade, chunked, embedded, tagged bot-searchable. And
> it opens right here; nobody downloads anything."

*Verify the tag rendered* — it only appears once `resource_id` is set:

```bash
cd backend
venv/Scripts/python.exe -c "from app.database import engine; from sqlalchemy import text; \
print(engine.connect().execute(text('select id,file_name,resource_id from attachments order by id desc limit 3')).fetchall())"
```

### 2:55 · Student `s21@shikshaa.in` → `/student/doubt-bot`

**Do:** Ask your rehearsed question. Let the citation render. Point at it.

> **SAY:** "Same minute, the student asks her doubt bot. It answers from her grade's own material —
> and it cites it. Not a general-purpose model guessing about fractions. Her teachers' material,
> scoped to Grade 3."

*The seeded corpus covers* fractions (numerator/denominator, 1/2 + 1/4, 3/5 of 20), verbs and
tenses, and the water cycle. **Rehearse two** — this is the only beat depending on retrieval
quality.

### 3:20 · Student → Teacher — `/student/doubts` → `/teacher/doubts`

**Do:** Grade 3-A already has 3 open doubts. Post a new one as `s21`, cut to `t5`, reply, **Mark
verified**.

> **SAY:** "When the bot isn't enough, the question goes to a human. The teacher answers and marks
> it verified — and that answer joins the knowledge base for the entire grade. One student's
> question becomes every student's answer, with a teacher's name on it. Any teacher who teaches the
> class can verify, not just the homeroom teacher."

*One verified answer is already in the corpus* (why a puddle dries up), so the claim holds even if
your live verification is slow.

---

## ACT III — And it runs the school · 3:55–4:55

*Sixty seconds, six screens, no lingering. Roughly eight seconds each — if you feel like
explaining, you're over.*

### 3:55 · Admin → `/admin/timetable`

**Do:** Hit **Generate**, let the solver run, show the filled grid.

> **SAY:** "A constraint solver builds the entire timetable — teacher availability, room types, lab
> requirements, weekly caps. Eighty-four periods across six classes, every Science period routed
> into the one science lab. When it's impossible, it names the constraint that made it impossible
> instead of just failing."

### 4:10 · Admin → `/admin/staffing`

**Do:** Approve **Anjali Menon's pending leave for Monday 24 August**. Show the substitutes.

> **SAY:** "Remember the teacher out sick in the first shot? Approving that leave proposes
> substitutes who are genuinely free that period and qualified to teach that subject."

*Payoff:* closes a thread planted at 0:00.

### 4:24 · Admin → `/admin/fees` and `/admin/ocr`

**Do:** Outstanding fees → payment-request queue → approve one. Then OCR a marksheet.

> **SAY:** "Fees invoice themselves nightly — forty outstanding here. Parents upload proof, an
> admin confirms, the ledger updates. Admissions paperwork is read by OCR into structured fields;
> nobody retypes a marksheet."

### 4:40 · Teacher `t5` → `/teacher/gradebook`

**Do:** Marks tab → enter one mark → **Report Cards** → **Generate all** → **Preview & Print** →
scroll to the remarks at the bottom.

> **SAY:** "And it compiles. Weighted marks, GPA, attendance for the year — and the same remarks we
> read at the start of this video, on one printable transcript. Enter a mark, publish a report
> card, done."

*This is the closing argument.* Myra's remarks from 0:52 appearing at 4:40 proves it's one system.
Point at it and pause.

---

## CLOSE · 4:55–5:10

### 4:55 · Admin → Command Center

**Do:** Return to the screen you opened on, now with your intervention logged. Hold still. Stop
talking a beat before you stop recording.

> **SAY:** "Five roles, one system. A camera marks a register, a sentence a teacher typed moves a
> risk score, a father gets told without anyone remembering to call, and a worksheet becomes
> something a student can ask questions of. That's not twenty features. That's one nervous system
> for a school."

*End on the frame you started on.*

---

## Blackout list — never on camera

| Don't show | Why | Instead |
| --- | --- | --- |
| `.env`, or a terminal printing `DATABASE_URL` | Live Supabase password, service-role key, Gemini key | Record the browser window only |
| `/admin/audit` | No such route — the audit trail has no UI | Say the audit line over the intervention |
| Any page before a class is selected | Correct behaviour, reads as empty on camera | Pre-select Grade 3-A |
| A student ID typed by hand | Undercuts the claim that the system knows who's who | Class → student picker, or `p6`'s children |
| "The whole class was recognised" | Only the faces you enrolled exist | "The students we've enrolled" |
| The `sam` or Riverside schools | Different data and logins; breaks the narrative | Stay in Shikshaa throughout |
| The full test suite running | Competes for pooled connections for 13 minutes | Run it before, never during |
| Wide tables scrolled sideways | Scrollbars are hidden app-wide, so a cut edge looks like a bug | Full-screen; keep tables in frame |
| Dark mode | Compresses worse; thin borders vanish | Light theme |

---

## If it breaks mid-take

**A page errors** — "…and that's a real system talking to a real database, so let me reload rather
than pretend." Judges forgive a reload; they don't forgive a fake.

**The bot answers badly** — "Retrieval is scoped to this grade's material, so if it hasn't been
taught yet the bot won't invent it —" then ask your second question. Refusing to hallucinate is a
selling point.

**Face recognition misses** — "Confidence was low, so it defers to the teacher." Switch to the
manual register.

**You're running long** — cut the fees/OCR beat (0:16). **Never cut** the intervention beat (1:20),
the bot citation (2:55), or the report-card callback (4:40).

---

## Timing card

| Time | Role / login | Page | Beat |
| --- | --- | --- | --- |
| 0:00 | admin | Command Center | Cold open |
| 0:22 | t5 | `/teacher/attendance` | CV attendance, Grade 3-A |
| 0:52 | t5 | `/teacher/remarks` | Myra's remarks → 15% of risk |
| 1:20 | admin | `/admin/risk` | Evidence + intervention + audit line |
| 1:52 | p6 | `/parent/child` | Already notified, 2 children |
| 2:25 | t5 | `/teacher/classroom` | Worksheet → indexed |
| 2:55 | s21 | `/student/doubt-bot` | Bot cites the material |
| 3:20 | s21 → t5 | `/*/doubts` | Verified → corpus |
| 3:55 | admin | `/admin/timetable` | Solver, 84 periods |
| 4:10 | admin | `/admin/staffing` | Substitute (payoff) |
| 4:24 | admin | `/admin/fees`, `/admin/ocr` | Proof → approve, marksheet |
| 4:40 | t5 | `/teacher/gradebook` | Report card, remark callback |
| 4:55 | admin | Command Center | Close on frame one |
