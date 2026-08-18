"""reunify person-b and person-ac heads

Revision ID: 2cbc07054aac
Revises: bbf5b96300f8, c4d88004d004
Create Date: 2026-08-18 03:08:29.436007

GRAPH-ONLY REVISION. Both `upgrade()` and `downgrade()` are deliberately empty and
must stay that way.

The two branches forked at 35f1fab38e0b and grew independently:

    35f1fab38e0b
      |-- 6b10048f8738 (fee payment requests) -> bbf5b96300f8 (doubt threads)   [person A/C]
      `-- c1a55001b001 -> c2b66002b002 -> c3c77003c003 -> c4d88004d004          [person B]

BOTH PARENTS ARE ALREADY PHYSICALLY APPLIED to the shared Supabase database - each
developer ran their own chain against it before the branches were merged. There is no
schema work left for this revision to do; every table, column and index either chain
creates already exists. Its only job is to give the graph a single head again so
`alembic upgrade head` is unambiguous and future revisions have one place to chain from.

Adding DDL here would attempt to re-apply something already present and fail.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2cbc07054aac'
down_revision: Union[str, None] = ('bbf5b96300f8', 'c4d88004d004')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
