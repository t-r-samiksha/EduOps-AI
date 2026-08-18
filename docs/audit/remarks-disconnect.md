# Two remark systems, deliberately left disconnected

**Status: accepted deferral, decided during the `akshaya` → `samiksha` merge (2026-08-18).**
Recorded here so nobody assumes one table feeds the other. Cross-referenced from
`app/models/risk.py::RemarkStub` and `app/models/remark.py::Remark`.

## What happened

Person A/C built the read side against a placeholder table before Person B's remarks
feature existed. Person B then built the real write side against a new table. Both
shipped. The merge kept both, because dropping either would lose a working feature.

## The two systems

| | `remark_stubs` (person A/C) | `remarks` (person B) |
|---|---|---|
| Model | `app/models/risk.py::RemarkStub` | `app/models/remark.py::Remark` |
| Written by | seed fixtures only | `POST /remarks`, `POST /remarks/bulk` |
| Read by | parent portal feed, Parent Assistant Bot summary, nightly risk scorer, `GET /remarks/student/{student_id}` | `GET /remarks/{student_id}` |
| Text column | `remark_text` | `content` |
| Sentiment | VADER, computed per request → `{label, compound}` | `sentiment_tag` string, defaulted to `"academic"`, never computed |
| Rows in demo school 5707 | 12 | 0 |

Both live in the same router (`app/routers/remarks.py`). The endpoints do **not**
collide: `/remarks/student/{id}` is three path segments, `/remarks/{id}` is two, so
FastAPI can never route one to the other regardless of registration order. An earlier
report claimed a silent route collision here; that was incorrect.

## The consequence, stated plainly

A teacher filing a remark through Person B's `BulkRemarksPage` writes to `remarks`.
That remark will **not** appear in the parent portal feed, will **not** be seen by the
Parent Assistant Bot, and will **not** affect the nightly risk score. It is visible
only through `GET /remarks/{student_id}`.

Conversely the 12 seeded rows that drive the parent-facing demo live in `remark_stubs`
and are invisible to Person B's UI.

Neither is broken. They are two features that happen to share a noun.

## Why it was left this way

Repointing the read side at `remarks` means touching the parent portal feed, the
Parent Bot's context builder, and the risk scorer's sentiment input — three
demo-critical paths — and backfilling the 12 seeded rows into a table with a different
column shape and no computed sentiment. That is not a change to make the day before a
demo. Merging as-is loses no functionality.

## If you unify later

Two workable directions, in rough order of preference:

1. **Make `remarks` the single source of truth.** Migrate the 12 `remark_stubs` rows
   into `remarks` (`remark_text` → `content`, `sentiment_tag` defaulted), repoint the
   four read paths, and run VADER over `content` at read time exactly as the stub path
   does today. Delete `remark_stubs` last, in its own migration.
2. **Dual-write from `create_single_remark` / `create_bulk_remarks`.** Cheaper and
   reversible, but leaves two tables permanently in sync-by-convention, which is the
   failure mode that produced this note.

Whichever is chosen, keep `RemarkOut.sentiment` as `{label, compound}` — the parent UI
renders `compound` as visual weight, not just a label, and the risk scorer consumes the
same numeric field.

## Related

- `docs/audit/merge-01-conflicts.md` — item **D-1**, and the correction to the
  route-collision claim
- `app/services/remark_sentiment.py` — the VADER wrapper the read side depends on
