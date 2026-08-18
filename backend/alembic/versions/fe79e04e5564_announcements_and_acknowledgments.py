"""announcements and acknowledgments

Revision ID: fe79e04e5564
Revises: d1e99005e005
Create Date: 2026-08-18 09:34:57.847736

HAND-CHECKED. Autogenerate emitted FOUR operations beyond the two new tables; all four
were stripped. Recording them here because the next autogenerate will emit them again:

  1. op.drop_index('uq_fee_payment_request_one_open')  -- FALSE POSITIVE, NEVER APPLY.
     A partial unique index (WHERE status = 'pending'). Alembic cannot express or
     introspect partial indexes, so it sees an index with no model counterpart and
     proposes dropping it. Dropping it lets a parent open two concurrent fee payment
     claims for the same fee record - the exact race the index exists to prevent.

  2. op.drop_index('ix_kb_chunks_embedding_hnsw')      -- FALSE POSITIVE, NEVER APPLY.
     A pgvector HNSW index, created with raw op.execute because autogenerate cannot
     emit pgvector index types. Dropping it silently degrades every RAG and chatbot
     query to a sequential scan over the whole embedding table. No error is raised
     anywhere; the bots keep answering, just slower as the corpus grows.

  3. op.alter_column('resources', 'updated_at', nullable=False)  -- known drift, left.
     The model declares NOT NULL, c2b66002b002 created it nullable. Cosmetic: the
     server_default means every row has a value.

  4. op.create_index('ix_resources_unit')              -- known gap, deliberately left.
     Deferred by decision - the table holds a handful of rows and adding an index
     pre-demo is unnecessary risk.

See CLAUDE.md's hazard checklist. Items 1 and 2 are permanent - neither index can be
expressed in a model, so this drift can never be resolved and must never be "cleaned up".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'fe79e04e5564'
down_revision: Union[str, None] = 'd1e99005e005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'announcements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('scope_type', sa.String(length=10), nullable=False),
        sa.Column('scope_grade_level', sa.Integer(), nullable=True),
        sa.Column('scope_class_id', sa.Integer(), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('category', sa.String(length=20), nullable=False),
        sa.Column('priority', sa.String(length=10), server_default='normal', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        # A half-populated scope resolves to the wrong audience - or to nobody - with no
        # error anywhere. It just looks posted. Enforced in the DB, not only the service.
        sa.CheckConstraint(
            "(scope_type = 'school' AND scope_grade_level IS NULL AND scope_class_id IS NULL)"
            " OR (scope_type = 'grade' AND scope_grade_level IS NOT NULL AND scope_class_id IS NULL)"
            " OR (scope_type = 'class' AND scope_class_id IS NOT NULL AND scope_grade_level IS NULL)",
            name='ck_announcement_scope_columns_match_type',
        ),
        sa.ForeignKeyConstraint(['author_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ),
        sa.ForeignKeyConstraint(['scope_class_id'], ['classes.id'], ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_announcements_school_id'), 'announcements', ['school_id'], unique=False)

    op.create_table(
        'announcement_acknowledgments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('announcement_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['announcement_id'], ['announcements.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        # The ack count is a COUNT over this table - a duplicate would overstate readership.
        sa.UniqueConstraint('announcement_id', 'user_id', name='uq_announcement_ack_user'),
    )
    op.create_index(
        op.f('ix_announcement_acknowledgments_announcement_id'),
        'announcement_acknowledgments', ['announcement_id'], unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_announcement_acknowledgments_announcement_id'), table_name='announcement_acknowledgments')
    op.drop_table('announcement_acknowledgments')
    op.drop_index(op.f('ix_announcements_school_id'), table_name='announcements')
    op.drop_table('announcements')
