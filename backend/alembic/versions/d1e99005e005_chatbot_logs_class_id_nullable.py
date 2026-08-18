"""make chatbot_logs.class_id nullable for the Teacher Assistant Bot

Revision ID: d1e99005e005
Revises: 2cbc07054aac
Create Date: 2026-08-18 03:12:00.000000

Chained off the merge revision (2cbc07054aac) rather than off either parent, so the
graph stays single-headed.

WHY THIS EXISTS
`chatbot_logs.class_id` was created NOT NULL by a78ec6eac8a4, back when the only
consumer was the Student Doubt Bot - a student always asks from inside a class they
had to prove enrollment in, so a class was always available to log.

The Teacher Assistant Bot (POST /bots/teacher/ask, added on the person-B branch) is
not class-scoped. A teacher asking "give me 5 MCQs on photosynthesis" names a grade
and a subject, not a section; `TeacherAskRequest.class_id` is `int | None = None`.
Its handler passes that straight through to the ChatbotLog insert, so on the default
request shape the NOT NULL constraint fires and the endpoint 500s with an
IntegrityError.

app/models/knowledge.py was already changed to `Mapped[int | None] / nullable=True` on
the person-B branch, but no migration accompanied it - so the model and the live
database disagreed and `alembic check` reported drift. This closes that gap in the
direction the model already declares.

SAFETY
Widening a constraint (DROP NOT NULL) is non-destructive: no data is read, rewritten
or lost, existing rows all satisfy the looser constraint, and the operation does not
rewrite the table. Safe against the shared database holding live demo data.

Top Doubts clustering is unaffected - services/doubt_insights.py aggregates over
`bot_type == "student"` rows, which still always carry a class_id.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e99005e005'
down_revision: Union[str, None] = '2cbc07054aac'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'chatbot_logs',
        'class_id',
        existing_type=sa.Integer(),
        nullable=True,
    )


def downgrade() -> None:
    # Re-tightening will fail if any teacher-bot row with a NULL class_id exists by
    # then. That is correct: those rows are real logged interactions and must not be
    # silently deleted to satisfy a rollback.
    op.alter_column(
        'chatbot_logs',
        'class_id',
        existing_type=sa.Integer(),
        nullable=False,
    )
