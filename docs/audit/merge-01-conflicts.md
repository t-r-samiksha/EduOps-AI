# Merge 01 — Conflict map: `akshaya` → `samiksha`

**Phase 1 output. Read-only analysis. No merge performed, no files touched outside this document.**

| | |
|---|---|
| Target branch (to create) | `integration/b-into-ac` from `samiksha` |
| `samiksha` head | `ab6a8c8` |
| `akshaya` head | **`6ccbe0c`** (fetched from `origin/akshaya`) |
| Merge base | `548c5e1` ("student bot nd notif") |
| Commits on akshaya not in samiksha | 12 |
| Commits on samiksha not in akshaya | 3 |
| Auto-merge tree (verified against) | `6a7bc2b1d9820a91c0d7f01b32dee7fa98754735` |

## Two corrections to the briefing before anything else

**1. `akshaya` was not at the SHA in the report.** The report cites `6468d4fbfe1d…`. That commit is real but is akshaya's **second-to-last**; one further commit (`6ccbe0c`, "last changes", 2026-08-18 00:06) landed after the report was written. It touches `routers/assignments.py`, `services/calendar_sync_service.py`, `api/hooks/useAssignments.ts`, `components/gradebook/GradebookPage.tsx` (+51/−29). All four are Person B's own files, so it changes no conclusion below — but the report is not describing the current tip. There was also no local `akshaya` ref at all; it had to be fetched.

**2. The headline collision in the briefing does not exist.** The report states `GET /remarks/student/{student_id}` "exists on both sides in different files" and instructs me to stop and not pick. It does not. akshaya **appended** their endpoints to the *same* file, leaving samiksha's handler byte-identical:

```
backend/app/routers/remarks.py  (akshaya = samiksha + 147 lines)
  GET  /remarks/student/{student_id}   <- samiksha's, unchanged, still first
  POST /remarks                        <- akshaya, new
  POST /remarks/bulk                   <- akshaya, new
  GET  /remarks/{student_id}           <- akshaya, new
```

`/remarks/{student_id}` (2 segments) cannot shadow `/remarks/student/{id}` (3 segments) — FastAPI cannot route one to the other, in any registration order. There is **no silent win and nothing to decide here.** The parent portal feed, Parent Assistant Bot summary, and risk-scorer sentiment input are unaffected.

The real remarks problem is different and is item **D-1** below.

Also disproven from the briefing's suspect list: `requirements.txt`, `frontend/package.json`, `tailwind.config.*`, `postcss.config.js`, `src/index.css`, `.gitignore` and `CLAUDE.md` are **byte-identical** across the two tips. No dependency or design-token divergence exists.

---

## Conflict counts

| Category | Count |
|---|---|
| **ADDITIVE** — one side only, merges clean | 61 akshaya files + 25 samiksha files |
| **TEXTUAL** — git conflict, mechanical union | **5** |
| **Auto-merged but both-touched** — needs eyes, no marker | **4** |
| **SEMANTIC** — no git conflict, wrong at runtime | **5** |
| **DUPLICATE** — same thing built twice | **3** |
| **NEEDS HUMAN DECISION** | **4** |

Only **9 files** were touched by both sides since the merge base. Everything else is a clean one-sided change. The full `git diff samiksha origin/akshaya` "modified" list (~45 files) is misleading: most of those entries are files **only samiksha** changed, which merge with samiksha's version intact.

### Route table: verified safe

Extracted statically from the auto-merge tree, so this is the real post-merge table.

| | |
|---|---|
| samiksha routes | 148 |
| akshaya routes | 179 |
| **merged total** | **198** = 130 shared + 49 akshaya-only + 19 samiksha-only |
| Exact duplicate `METHOD + path` in merged app | **0** |
| samiksha's 19 unique routes present post-merge | **19 / 19 OK** |

All 19 checked individually: `/threads` ×5, `/admin/fee-payment-requests` ×4, `/parent/child/…` ×3, `/attendance/{register,analytics,my-records,manual}`, `/bots/parent/ask`, `/admin/fees/reminders/preview`. **Nothing dropped.**

Path-shadowing order was checked in every akshaya router. All safe — the two genuine risks are correctly ordered already: `/resources/units` before `/resources/{class_id}`, and `/classroom/my-classrooms` before `/classroom/{classroom_id}`.

### Migration graph: verified safe (statically, no DB touched)

The briefing has samiksha's two revisions in the wrong order. Actual chain:

```
35f1fab38e0b                        (shared; pre-dates the merge base)
├─ 6b10048f8738  fee payment requests      ← samiksha
│  └─ bbf5b96300f8  doubt threads          ← samiksha HEAD
└─ c1a55001b001 → c2b66002b002 → c3c77003c003 → c4d88004d004   ← akshaya HEAD
```

Confirmed by reading `down_revision` in every one of the 30 revision files. A fork with two heads, as described. Resolution is one `alembic merge` revision, empty body.

**All four akshaya `upgrade()` bodies are purely additive** — `create_table`, `add_column`, `create_index`, `create_foreign_key` only. Zero `drop_*`, zero `alter_*`, zero `execute`. The `drop_table` calls I found are in `downgrade()` only, which we never run.

The `CLAUDE.md` hazard checklist is **not** triggered:
- **pgvector HNSW index** — `hnsw` appears only in `35f1fab38e0b` and `a78ec6eac8a4`, both shared ancestors. akshaya's four revisions never mention it.
- **Partial unique index `uq_fee_payment_request_one_open`** — lives in samiksha's `6b10048f8738`. akshaya has no such revision and drops nothing.
- **Circular inline FK** — `c2b66002b002` correctly uses a separate `op.create_foreign_key`, not an inline one.

---

## TEXTUAL — 5 files, mechanical union

All five resolve by taking **both** sides and sorting deterministically. No judgement required.

| File | Conflict | Resolution |
|---|---|---|
| `backend/app/models/__init__.py` | 1 region: samiksha added `FeePaymentRequest` to the `fees` import; akshaya inserted a `gradebook` import at the same line | Union: `from app.models.fees import FeePaymentRequest, FeeRecord, FeeReminder, FeeSchedule` **plus** the `gradebook` line. `__all__` already auto-merged correctly — verified `DoubtThread`, `ThreadReply`, `FeePaymentRequest`, `Remark`, `RemarkStub` all present |
| `backend/app/routers/bots.py` | 1 region: samiksha added `POST /parent/ask`, akshaya added `POST /teacher/ask` in the same place | Union both handlers. **`POST /student/ask` is byte-identical on both sides** — verified line by line; this is not a duplicate implementation. Also union the imports akshaya's copy lacks: `SOURCE_TYPE_RESOURCE`, `from app.routers.parent import child_summary`, `assert_parent_linked` |
| `frontend/src/App.tsx` | 2 regions (imports, route elements) | Union |
| `frontend/src/lib/navConfig.ts` | 3 regions | Union |
| `frontend/src/api/types.ts` | 1 region | Union |

## Auto-merged but both-touched — 4 files, no conflict marker to warn you

| File | Verdict |
|---|---|
| `backend/app/main.py` | **Clean.** Both sides added distinct router imports + `include_router` calls. Union is what git produced. akshaya adds 8 routers (`analytics`, `assignments`, `calendar`, `classroom`, `gradebook`, `library`, `quizzes`, `report_cards`), samiksha adds `threads`. All 9 registered post-merge |
| `backend/app/services/supabase_admin.py` | **Clean — and I initially misread this.** akshaya's copy has no `PAYMENT_PROOFS_BUCKET` and a narrowed `upload_resource_file`/`download_resource_file`/`ensure_resources_bucket` API. But samiksha never diverged from base here in a conflicting hunk, and the merged tree carries samiksha's **full** file: `PAYMENT_PROOFS_BUCKET` (line 91), generic `ensure_bucket`/`upload_file`/`download_file`, **and** akshaya's three names as thin delegating wrappers. Person B's 5 call sites and samiksha's fee-proof upload/download both work. No action |
| `backend/app/services/retrieval.py` | **Additive but buggy** — see S-1. samiksha's `search_chunks` untouched; akshaya appended `search_chunks_for_teacher` |
| `backend/app/services/ingestion.py` | **Silent regression** — see S-2. This is the most dangerous file in the merge |
| `docs/api-contract.md` | Auto-merged, both sections present. See S-5 |

---

## SEMANTIC — no git conflict, breaks at runtime

### S-1 · `search_chunks_for_teacher` omits the `source_type` filter — wrong citations in the Teacher Bot
`backend/app/services/retrieval.py` (appended by akshaya, ~line 209)

```python
.outerjoin(Resource, Resource.id == KbChunk.source_id)   # no source_type condition
```

samiksha's own `search_chunks` does this, with a comment three lines above it:

```python
# THE source_type CONDITION IS LOAD-BEARING, not defensive tidiness.
and_(Resource.id == KbChunk.source_id, KbChunk.source_type == SOURCE_TYPE_RESOURCE),
```

`kb_chunks.source_id` is only meaningful *together with* `source_type` — a verified-doubt-answer chunk with `source_id=12` will join to `Resource id=12`, an unrelated document, and the Teacher Bot will cite that resource's title for text that never came from it. akshaya wrote this function against the pre-`source_type` schema; samiksha's newest commit (`ab6a8c8`, "retrieval source_type fix") is exactly what introduced the column. Neither side conflicts, so this lands silently.

**Proposed resolution:** add the `source_type == SOURCE_TYPE_RESOURCE` condition to the join, matching `search_chunks`. One line. *Correctness — top of the priority order.* Listed as **HD-3** because hard rule 6/§Phase-2 says stop rather than change behaviour unilaterally.

### S-2 · `extract_text` rewritten to swallow every failure — silently unsearchable resources
`backend/app/services/ingestion.py::extract_text`

akshaya's rewrite wins the auto-merge. Behaviour change:

| | samiksha | akshaya (wins) |
|---|---|---|
| Corrupt / scanned PDF | raises → upload endpoint returns **422** | `except Exception: return ""` |
| Result of empty text | resource not ingested, caller told | marked `indexed_at`, **0 chunks, no error anywhere** |
| `image/*` | falls through to utf-8 decode | early `return ""` |
| NUL bytes | not stripped | `.replace("\x00", "")` |

The empty-chunk path then sets `resource.indexed_at` and `needs_reindex = False`, so the nightly re-index job (`indexed_at IS NULL`) will **never retry it**. A teacher uploads a scanned worksheet, gets `201 Created`, and the file is permanently invisible to every bot with no error logged. samiksha's deleted docstring warned about precisely this ("*extracts to nothing, and that is reported as a 422 … rather than being ingested as an empty resource*").

Not all of akshaya's change is wrong: the `\x00` strip is a genuine fix (Postgres `text` rejects NUL), and the `image/*` early return is needed by Person B's image upload path.

**Proposed resolution — hybrid, keeps both features:** restore samiksha's raise-don't-swallow semantics for PDF/decode failures; keep akshaya's `image/*` early return and `\x00` stripping. **HD-2.**

### S-3 · `ChatbotLog.class_id` — model says nullable, database says `NOT NULL`, no migration exists
`backend/app/models/knowledge.py` (akshaya-only change)

```python
- class_id: Mapped[int]        = mapped_column(ForeignKey("classes.id"), nullable=False)
+ class_id: Mapped[int | None] = mapped_column(ForeignKey("classes.id"), nullable=True)
```

I checked all four akshaya revisions for `chatbot_logs`: **none touches it.** The live column is `nullable=False` (`a78ec6eac8a4` line 36). So:

- `alembic check` will report drift and want to emit an `ALTER`.
- akshaya's own `POST /bots/teacher/ask` passes `class_id=body.class_id`, and `TeacherAskRequest.class_id` is `int | None = None`. **Any teacher asking without naming a class → `IntegrityError`, HTTP 500.** This is Person B's flagship new feature failing on its default request shape.

**Proposed resolution:** a 5th revision doing `op.alter_column('chatbot_logs', 'class_id', nullable=True)` — additive, non-destructive, safe on live data (widening a constraint). Alternative is reverting the model and making `class_id` required in the request. Needs your call because it is a schema change to a shared table: **HD-4.**

### S-4 · `resources.updated_at` nullability drift
Model (`models/resource.py`) declares `Mapped[datetime]` (NOT NULL); migration `c2b66002b002` creates it `nullable=True`. Cosmetic at runtime — the `server_default` means rows always have a value — but `alembic check` will flag it, which matters because Phase 2 asks for a clean `alembic check`. Fix inside the merge revision or accept a known drift line.

### S-5 · `docs/api-contract.md` Person B section documents endpoints that were never built
The merged contract still carries the *spec* shapes, which do not match the implementation:

| Contract says | akshaya actually built |
|---|---|
| `POST /classroom/{class_id}/assignments` | `POST /assignments` |
| `GET /classroom/{class_id}/assignments` | `GET /assignments/{class_id}` |
| `POST /assignments/{id}/submissions` | `POST /assignments/{assignment_id}/submit` |
| `POST /assignments/{id}/submissions/{sid}/grade` | `PUT /assignments/{assignment_id}/grade/{submission_id}` |
| `POST /gradebook/entries` | `POST /gradebook/entry` |

Consistent with the briefing's warning that the docs describe things that don't exist. Doc-only; no runtime effect. Resolution: keep both sides' sections, and annotate the Person B block with the as-built paths rather than deleting either.

---

## DUPLICATE — same thing built twice

### D-1 · Two parallel remark systems that never talk to each other ← *the real remarks problem*
Not a route collision (see the correction at the top). The duplication is at the **data layer**, and it means Person B's remarks UI is wired to a table nothing on the samiksha side reads.

| | `remark_stubs` (samiksha) | `remarks` (akshaya) |
|---|---|---|
| Written by | seed fixtures only | `POST /remarks`, `POST /remarks/bulk` |
| Read by | parent portal feed, Parent Assistant Bot summary, nightly risk scorer sentiment, `GET /remarks/student/{id}` | `GET /remarks/{student_id}` only |
| Sentiment | VADER, computed per request → `{label, compound}` | `sentiment_tag` string, defaulted, never computed |
| Rows in demo school 5707 | 12 | 0 |

Post-merge, a teacher filing a remark through Person B's `BulkRemarksPage` writes to `remarks`, and it will **not** appear in the parent feed, will **not** reach the Parent Bot, and will **not** affect risk scoring. Both features "work"; they are simply disconnected. Nothing is lost by merging as-is, so this need not block Phase 2 — but it must be a conscious deferral, not an accident. **HD-1.**

### D-2 · `needs_reindex` (akshaya) duplicates `indexed_at` (samiksha)
Both columns now exist on `resources`. `indexed_at` is authoritative — the nightly job and `ingest_pending()` both select `indexed_at IS NULL`; `scheduler.py`'s comment documents it. `needs_reindex` is written in 5 places and **read by nothing that gates ingestion** — only echoed in the `GET /resources` response. Harmless but it invites a future bug where someone flips `needs_reindex` and nothing re-indexes. Recommend: keep the column (dropping it needs a destructive migration), document `indexed_at` as authoritative in the model docstring. Folded into **HD-1** as a deferral.

### D-3 · akshaya's three `*_resource_file` wrappers duplicate samiksha's generic API
Already resolved correctly by the auto-merge as delegating one-liners. No action.

---

## `resources` schema — which code paths read which column

The briefing asked specifically for this. Answer: **`grade_level` survives and is still the retrieval scope unit. Nothing was removed.**

`c2b66002b002` only *adds* `class_id` (nullable), `description`, `unit`, `file_size`, `needs_reindex`, `updated_at`. It does not drop `grade_level`, and akshaya's model keeps `grade_level` as `nullable=False` plus the `ix_resources_school_grade` index. akshaya's model is a strict **superset** of samiksha's.

| Column | Read by |
|---|---|
| `grade_level` | **All RAG paths** — `services/ingestion.py` (stamps chunks), `services/retrieval.py` (scope), `GET /resources` filter, upload permission check, `GET /resources/{class_id}` fallback |
| `class_id` | Person B UI paths only — `GET /resources/units`, `GET /resources/{class_id}`, `GET /resources?class_id=`, upload scope-folder naming |

The two coexist by design in akshaya's read path: `Resource.class_id.is_(None) & (Resource.grade_level == …)` — a class-scoped resource is class-only, a grade-scoped one is visible to the whole grade. That is coherent. **No change needed to either column.**

What *is* lost is documentation: akshaya's rewrite deleted the load-bearing docstrings explaining *why* the scope unit is grade and not class, why `school_id` is required alongside it, and the `Resource` vs `Document` contrast. Per your "prefer samiksha" instruction these should be restored on top of akshaya's superset — no functional change, but this is exactly the institutional knowledge that gets re-litigated later.

## Supabase Storage buckets — verified safe

| Bucket | Used by | Private |
|---|---|---|
| `resources` | samiksha RAG source material **and** akshaya's `attachments` / assignment uploads / classroom uploads | yes |
| `payment-proofs` | samiksha fee proof upload + admin read-back | yes |

**akshaya's uploads do share the `resources` bucket** — `routers/assignments.py:424` and `routers/classroom.py:535` both call `upload_resource_file(...)`, which is hardcoded to `RESOURCES_BUCKET`.

The briefing flagged the risk: *"a shared bucket between RAG material and user uploads would make uploads chatbot-retrievable."* Assessment — **the risk is real but not currently live.** `POST /bots/reindex` → `ingest_pending()` iterates `db.query(Resource)`, i.e. it is driven by rows in the `resources` **table**, not by listing the bucket. Assignment and classroom attachments create `attachments`/`assignment_submissions` rows, never `Resource` rows, so they are never chunked or embedded. A student's submitted homework will not surface in a Doubt Bot answer today.

It is one bucket-listing away from becoming live, though, and it defeats the isolation rationale samiksha wrote for keeping `payment-proofs` separate. Recommend (not blocking): point Person B's uploads at a separate private `attachments` bucket via the generic `upload_file(..., bucket=…)` that already exists. Deferred, noted in the execution sequence as a post-merge item.

## Stray artifact

`backend/test_eduops.db` — a **364 KB committed SQLite binary** on akshaya's side. `.gitignore` is identical on both branches and does not cover it. Recommend removing from the merge and adding to `.gitignore`; it is a test scratch file, not a deliverable. Flagged rather than actioned since deleting a file the other developer committed is their call.

---

## Ordered execution sequence for Phase 2

1. `git checkout -b integration/b-into-ac samiksha`
2. `git merge origin/akshaya --no-ff` — expect exactly the 5 TEXTUAL conflicts
3. Resolve all 5 by union (table above). Sort import/registration lists deterministically
4. Re-add to `bots.py` the imports akshaya's copy dropped: `SOURCE_TYPE_RESOURCE`, `child_summary`, `assert_parent_linked`
5. **HD-2** — apply the agreed `extract_text` resolution
6. **HD-3** — apply the agreed `source_type` join fix
7. **HD-4** — create the agreed `chatbot_logs.class_id` revision (if approved)
8. Restore samiksha's `models/resource.py` docstrings on top of akshaya's superset
9. `alembic merge -m "reunify person-b and person-ac heads" bbf5b96300f8 c4d88004d004` — empty `upgrade()`/`downgrade()`, docstring noting both parents are already applied to the shared DB. **No `upgrade`, no `downgrade`, no `autogenerate`**
10. `alembic heads` → expect exactly 1. `alembic current` → unchanged
11. `alembic check` → expect clean, or the single known `resources.updated_at` drift line (S-4)
12. `python -c "from app.main import app"` — imports, no server left running
13. Route table extract → confirm 198 routes, 0 duplicates, all 19 samiksha-unique present
14. `npm run build` including TypeScript
15. Seed script idempotency check — reports "nothing created"
16. `git add -A`, **stop, do not commit**

Deferred to post-merge, tracked not fixed: **D-1** remarks unification, **D-2** `needs_reindex` redundancy, **S-5** contract/as-built drift, separate `attachments` bucket, `test_eduops.db` removal.

---

## NEEDS HUMAN DECISION

**HD-1 · Two disconnected remark systems (D-1).** Merging as-is loses no feature but leaves Person B's remark writes invisible to the parent portal, Parent Bot, and risk scorer. Options: (a) merge as-is, unify later — recommended, unblocks the demo, both features work independently; (b) repoint samiksha's readers at `remarks` and backfill the 12 demo rows; (c) have `create_remark` dual-write. (b) and (c) are real work and touch demo-critical read paths.

**HD-2 · `extract_text` error semantics (S-2).** akshaya's silent `return ""` vs samiksha's 422. My recommendation: samiksha's raise-don't-swallow behaviour, keeping akshaya's `image/*` early return and `\x00` strip. Confirm before I change ingestion behaviour.

**HD-3 · `search_chunks_for_teacher` missing `source_type` filter (S-1).** A one-line correctness fix to a function only Person B's Teacher Bot calls. Without it, Teacher Bot citations can name the wrong document. Phase 2 says stop on route/behaviour changes rather than decide — confirm and I'll apply it.

**HD-4 · `chatbot_logs.class_id` nullability (S-3).** Needs either a 5th migration (`alter_column … nullable=True`, additive and safe) or a model revert making `class_id` required. Until one is done, `POST /bots/teacher/ask` 500s on its default request shape and `alembic check` is dirty. This is a schema change to a shared table on a live database, so it is your call.
