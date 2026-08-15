"""Nightly admin briefing: compiles the current unified alerts feed
(services/alert_aggregator.py) into a plain-text summary for admins/principals.

SCHEDULING - now real, wired into APScheduler (was manual-only for several sessions)
--------------------------------------------------------------------------------------
`compile_briefing()` (below) now runs automatically every night at 02:30 UTC via
`app/scheduler.py`'s `run_nightly_admin_briefing_job()` - started in
`app/main.py`'s FastAPI lifespan. Unlike the other 3 nightly/monthly jobs, this
one isn't looped per school (the alerts feed it reads has no school scoping of
its own - see `alert_aggregator.py`). `compile_briefing()` itself is unchanged:
still a pure function of a Session; `main()` below remains a thin CLI wrapper
for manual/on-demand invocation: `python -m scripts.run_nightly_admin_briefing`.

EMAIL SENDING - stubbed, not fabricated
------------------------------------------
Checked first: no smtplib usage, SendGrid/Mailgun/SES client, or fastapi-mail exists
anywhere in this repo - there is no real email-sending capability to wire this into.
send_briefing_email() below is a clearly-labeled stub that logs what WOULD be sent
and to whom; it does not send anything. Wire in a real provider there once one is
chosen for the project - nothing else in this script needs to change.

OUTPUT - written to a file, not just printed
------------------------------------------------
Unlike run_nightly_risk_scoring.py (which only prints counts), the compiled briefing
IS the content a real email would carry, so it's also written to
backend/var/briefings/{date}.txt (directory auto-created, gitignored - generated
output, not source) - lets you inspect exactly what a real send would have contained
without needing real email infrastructure.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv()

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.alerts import AlertDismissal
from app.services.alert_aggregator import aggregate_alerts, summarize_alerts

BRIEFING_OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "var", "briefings")


def _dismissed_alert_ids(session: Session) -> set[str]:
    return {row.alert_id for row in session.query(AlertDismissal.alert_id).all()}


def compile_briefing(session: Session, *, generated_at: datetime | None = None) -> str:
    """Everything currently active in the alerts feed (not just "new since last
    run") - a nightly briefing should be a complete picture of outstanding work, the
    same content GET /admin/alerts would show right now, not a delta."""
    generated_at = generated_at or datetime.now(timezone.utc)
    alerts = aggregate_alerts(session, dismissed_ids=_dismissed_alert_ids(session))
    summary = summarize_alerts(alerts)

    lines = [
        f"EduOps AI - Admin Briefing - {generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
        "=" * 60,
        f"Total open alerts: {summary['total']}",
        f"  urgent: {summary['by_severity'].get('urgent', 0)}   normal: {summary['by_severity'].get('normal', 0)}",
        "By source: " + (", ".join(f"{k}={v}" for k, v in sorted(summary["by_source"].items())) or "(none)"),
        "",
    ]

    if not alerts:
        lines.append("Nothing outstanding - clean slate.")
    else:
        urgent = [a for a in alerts if a.severity == "urgent"]
        normal = [a for a in alerts if a.severity == "normal"]
        for label, group in (("URGENT", urgent), ("NORMAL", normal)):
            if not group:
                continue
            lines.append(f"--- {label} ({len(group)}) ---")
            for a in group:
                lines.append(f"[{a.id}] {a.title}: {a.message} (since {a.created_at.strftime('%Y-%m-%d %H:%M UTC')})")
            lines.append("")

    return "\n".join(lines)


def send_briefing_email(recipients: list[str], subject: str, body: str) -> None:
    """STUB - does not send anything. See this module's docstring: no email-sending
    capability exists anywhere in this repo yet. Logs clearly instead of silently
    no-opping, so this integration point is impossible to miss."""
    print(f"[STUB - no email integration exists yet] Would send to {recipients!r}, subject={subject!r}, {len(body)} chars")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--recipients", nargs="*", default=[], help="Admin email addresses for the stubbed send step")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        briefing = compile_briefing(session)
    finally:
        session.close()

    print(briefing)

    os.makedirs(BRIEFING_OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(BRIEFING_OUTPUT_DIR, f"{date.today().isoformat()}.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(briefing)
    print(f"\nBriefing written to {output_path}")

    if args.recipients:
        send_briefing_email(args.recipients, "EduOps AI - Nightly Admin Briefing", briefing)


if __name__ == "__main__":
    main()
