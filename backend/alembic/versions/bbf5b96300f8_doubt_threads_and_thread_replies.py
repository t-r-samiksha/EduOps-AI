"""doubt threads and thread replies

Revision ID: bbf5b96300f8
Revises: 6b10048f8738
Create Date: 2026-08-17 21:23:48.707236

HAND-EDITED AFTER AUTOGENERATE - three changes. The fourth migration in a row where
this check caught something, and the first where it caught two destructive drops.

1. REMOVED `op.drop_index('ix_kb_chunks_embedding_hnsw')`. Alembic cannot reflect a
   pgvector HNSW index, so it sees the live index, finds no match in the models, and
   proposes dropping it. That index is what makes RAG similarity search fast -
   applying this as generated would have silently degraded every bot query to a
   sequential scan. Nothing here touches kb_chunks.

2. REMOVED `op.drop_index('uq_fee_payment_request_one_open')`. Same root cause,
   different index: it is a PARTIAL unique index (`WHERE status = 'pending'`) created
   with raw SQL in 6b10048f8738 precisely because autogenerate cannot express one -
   so autogenerate also cannot recognise it and wants it gone. It is the only thing
   stopping a parent from opening two concurrent payment claims against one fee.

3. RESTRUCTURED the circular foreign key. doubt_threads.verified_reply_id references
   thread_replies.id while thread_replies.thread_id references doubt_threads.id, so
   neither table can be created with both constraints inline. Autogenerate emitted
   the verified_reply_id FK INSIDE `create_table('doubt_threads', ...)`, which fails:
   `use_alter` is a SQLAlchemy create_all ordering hint and does not defer DDL inside
   an explicit op.create_table. Fixed by creating both tables first and adding that
   one constraint in its own op.create_foreign_key afterwards.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'bbf5b96300f8'
down_revision: Union[str, None] = '6b10048f8738'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

VERIFIED_REPLY_FK = "fk_doubt_threads_verified_reply_id"


def upgrade() -> None:
    # Step 1: doubt_threads WITHOUT the verified_reply_id constraint - the table it
    # points at does not exist yet. The column itself is created here.
    op.create_table(
        'doubt_threads',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('class_id', sa.Integer(), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('resolved', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('verified_reply_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_doubt_threads_class_id'), 'doubt_threads', ['class_id'], unique=False)

    # Step 2: thread_replies, which CAN reference doubt_threads inline now.
    op.create_table(
        'thread_replies',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('thread_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['thread_id'], ['doubt_threads.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_thread_replies_thread_id'), 'thread_replies', ['thread_id'], unique=False)

    # Step 3: close the cycle, now that both ends exist.
    op.create_foreign_key(
        VERIFIED_REPLY_FK, 'doubt_threads', 'thread_replies', ['verified_reply_id'], ['id']
    )


def downgrade() -> None:
    # Drop the cycle-closing constraint first, or thread_replies cannot be dropped.
    op.drop_constraint(VERIFIED_REPLY_FK, 'doubt_threads', type_='foreignkey')
    op.drop_index(op.f('ix_thread_replies_thread_id'), table_name='thread_replies')
    op.drop_table('thread_replies')
    op.drop_index(op.f('ix_doubt_threads_class_id'), table_name='doubt_threads')
    op.drop_table('doubt_threads')
