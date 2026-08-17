"""One-off backfill: rewrite raw entity ids into display names inside existing
`anomaly_flags.detail["message"]` strings.

WHY THIS SCRIPT EXISTS AT ALL
--------------------------------
Unlike every other alert source, an anomaly's message text is PERSISTED at detection
time rather than re-derived on read: `services/anomaly_detector.py` builds the string,
`scripts/run_nightly_syllabus_anomaly_scan.py::_upsert_flag` writes it into
`detail["message"]`, and `services/alert_aggregator.py::anomaly_flag_alerts` simply
replays whatever is stored. Fixing the generators (so new flags say "Ravi Kumar"
instead of "Teacher 26536") therefore does nothing for rows already in the table -
an open anomaly keeps its old text until it is resolved and re-detected.

This script closes that gap for existing rows. It is a display-text fix only: it never
changes a flag's type/severity/status/entity, only the human-readable `message` inside
`detail`.

WHAT IT REWRITES
-------------------
Two message shapes, matching the two generators that embedded a bare id:

  "Teacher {id} is teaching N periods/week vs a peer average of ~X"   (teacher_overload)
  "Class {id} attendance dropped to N% (baseline X%)"                 (attendance_drop)

Anything else is left untouched. `document_backlog` ("Document {id} has been stuck
in 'queued' for 30h") and `syllabus_drift` are deliberately NOT rewritten - a Document
has no display name of its own, and the id there IS the useful identifier for the
admin who then opens that document.

IDEMPOTENT: matching is anchored on the literal `Teacher {int} `/`Class {int} ` prefix,
which no longer matches once the name has been substituted in. Re-running is a no-op.

Run from `backend/` with the venv interpreter:

    PYTHONPATH=. venv/Scripts/python.exe -m scripts.backfill_anomaly_flag_names
    PYTHONPATH=. venv/Scripts/python.exe -m scripts.backfill_anomaly_flag_names --dry-run

`--dry-run` prints every rewrite it would make and commits nothing.
"""

from __future__ import annotations

import argparse
import re

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.class_ import SchoolClass
from app.models.syllabus import AnomalyFlag
from app.models.user import User

_TEACHER_PREFIX = re.compile(r"^Teacher (\d+) ")
_CLASS_PREFIX = re.compile(r"^Class (\d+) ")


def _teacher_names(session: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = session.query(User.id, User.full_name, User.email).filter(User.id.in_(ids)).all()
    return {r.id: (r.full_name or r.email or f"Teacher {r.id}") for r in rows}


def _class_names(session: Session, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    return {c.id: c.name for c in session.query(SchoolClass.id, SchoolClass.name).filter(SchoolClass.id.in_(ids)).all()}


def _rewrite(message: str, teacher_names: dict[int, str], class_names: dict[int, str]) -> str | None:
    """Returns the rewritten message, or None if nothing applies."""
    m = _TEACHER_PREFIX.match(message)
    if m:
        name = teacher_names.get(int(m.group(1)))
        # No name resolvable (deleted account) -> leave the id in place rather than
        # producing a message that identifies nobody at all.
        return f"{name} {message[m.end():]}" if name else None

    m = _CLASS_PREFIX.match(message)
    if m:
        name = class_names.get(int(m.group(1)))
        return f"{name} {message[m.end():]}" if name else None

    return None


def backfill(session: Session, *, dry_run: bool = False) -> tuple[int, int]:
    """Returns (rewritten, examined). Only touches flags that aren't resolved - a
    resolved flag is history, and rewriting its text would edit the record of what
    an admin actually saw when they acted on it."""
    flags = session.query(AnomalyFlag).filter(AnomalyFlag.status != "resolved").all()

    teacher_ids: set[int] = set()
    class_ids: set[int] = set()
    for flag in flags:
        message = (flag.detail or {}).get("message")
        if not isinstance(message, str):
            continue
        m = _TEACHER_PREFIX.match(message)
        if m:
            teacher_ids.add(int(m.group(1)))
            continue
        m = _CLASS_PREFIX.match(message)
        if m:
            class_ids.add(int(m.group(1)))

    teacher_names = _teacher_names(session, teacher_ids)
    class_names = _class_names(session, class_ids)

    rewritten = 0
    for flag in flags:
        detail = flag.detail or {}
        message = detail.get("message")
        if not isinstance(message, str):
            continue
        new_message = _rewrite(message, teacher_names, class_names)
        if new_message is None or new_message == message:
            continue

        print(f"  flag {flag.id} ({flag.type}):")
        print(f"    - {message}")
        print(f"    + {new_message}")
        if not dry_run:
            # Reassign the whole dict: JSONB columns are not change-tracked on
            # in-place mutation, so `detail["message"] = ...` alone would never be
            # flushed (the same trap this codebase's other JSONB writes avoid by
            # always assigning a fresh dict).
            flag.detail = {**detail, "message": new_message}
        rewritten += 1

    if not dry_run:
        session.commit()
    return rewritten, len(flags)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print rewrites without committing.")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        rewritten, examined = backfill(session, dry_run=args.dry_run)
    finally:
        session.close()

    verb = "Would rewrite" if args.dry_run else "Rewrote"
    print(f"\n{verb} {rewritten} of {examined} unresolved anomaly flag message(s).")
    if args.dry_run:
        print("Dry run - nothing committed.")


if __name__ == "__main__":
    main()
