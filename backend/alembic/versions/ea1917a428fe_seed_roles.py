"""seed roles

Revision ID: ea1917a428fe
Revises: b6e69c28c955
Create Date: 2026-08-09 10:52:51.097287

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ea1917a428fe'
down_revision: Union[str, None] = 'b6e69c28c955'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ROLE_NAMES = ["principal", "admin", "teacher", "student", "parent"]


def upgrade() -> None:
    roles = sa.table("roles", sa.column("name", sa.String))
    op.bulk_insert(roles, [{"name": name} for name in ROLE_NAMES])


def downgrade() -> None:
    roles = sa.table("roles", sa.column("name", sa.String))
    op.execute(roles.delete().where(roles.c.name.in_(ROLE_NAMES)))
