"""link post attachments to indexed resources

Adds `attachments.resource_id` so a classroom stream attachment can point at the
`resources` row it was indexed as. Posting a file to a classroom stream previously wrote
bytes to storage and nothing else - no resource row, no ingestion - so the Doubt Bot could
never answer from anything a teacher shared with their own class. See
app/services/classroom_materials.py.

HAND-EDITED AFTER AUTOGENERATE. Autogenerate emitted six operations; four of them were
touching tables this change does not mention, which CLAUDE.md names as the tell. Removed:

  1. `op.drop_index('uq_fee_payment_request_one_open')` - a PARTIAL unique index
     (`WHERE status = 'pending'`), creatable only via raw `op.execute`, so autogenerate
     cannot express it and therefore cannot recognise it. Applying this would let a parent
     open two concurrent fee payment claims for the same fee record - the exact race the
     index exists to prevent.
  2. `op.drop_index('ix_kb_chunks_embedding_hnsw')` - the pgvector HNSW index. Alembic
     cannot reflect HNSW, sees no model match, and proposes dropping it. Applying this
     silently degrades every RAG and chatbot query to a sequential scan over the whole
     embedding table, with no error raised anywhere - the bots keep answering, just slower
     and slower as the corpus grows. Especially not this migration, whose entire purpose is
     to put MORE rows in that table.
  3. `op.alter_column('resources', 'updated_at', nullable=False)` - known, documented,
     deliberately unfixed cosmetic drift (the server_default means every row always has a
     value).
  4. `op.create_index('ix_resources_unit')` - a genuinely missing single-column index,
     deliberately deferred: the table holds a handful of rows so it buys nothing, and
     adding an index is unnecessary pre-demo risk.

All four are the permanent, expected steady state of `alembic check` - see CLAUDE.md's
"`alembic check` is NOT clean" section. They are not this migration's business.

The foreign key is also NAMED, where autogenerate passed `None`. An unnamed constraint gets
a server-generated name, which `downgrade()`'s `op.drop_constraint(None, ...)` cannot
resolve - the generated downgrade would have failed.

Revision ID: a8246eec59d8
Revises: fe79e04e5564
Create Date: 2026-08-18 14:07:41.095165

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a8246eec59d8'
down_revision: Union[str, None] = 'fe79e04e5564'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FK_NAME = "fk_attachments_resource_id_resources"


def upgrade() -> None:
    op.add_column('attachments', sa.Column('resource_id', sa.Integer(), nullable=True))
    # ondelete SET NULL, not CASCADE: removing a file from the resource library must not
    # delete the teacher's stream post along with it. The attachment keeps its own
    # file_url, so the download route still works - it just stops being indexed.
    op.create_foreign_key(
        FK_NAME,
        'attachments',
        'resources',
        ['resource_id'],
        ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint(FK_NAME, 'attachments', type_='foreignkey')
    op.drop_column('attachments', 'resource_id')
