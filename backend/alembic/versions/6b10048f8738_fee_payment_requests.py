"""fee payment requests

Revision ID: 6b10048f8738
Revises: 35f1fab38e0b
Create Date: 2026-08-17 19:08:21.795268

HAND-EDITED AFTER AUTOGENERATE - two changes, both necessary:

1. REMOVED an `op.drop_index('ix_kb_chunks_embedding_hnsw')` that autogenerate
   invented. Alembic cannot reflect a pgvector HNSW index, so it sees the live
   index, finds nothing matching in the models, and proposes dropping it. That
   index is what makes the RAG chatbots' similarity search fast - applying the
   generated migration as written would have silently degraded every bot query
   to a sequential scan. Nothing about this migration touches kb_chunks.

2. ADDED the partial unique index below, which autogenerate cannot express.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b10048f8738'
down_revision: Union[str, None] = '35f1fab38e0b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'fee_payment_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('fee_record_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('parent_id', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Float(), nullable=False),
        sa.Column('payment_method', sa.String(length=20), nullable=False),
        sa.Column('payment_reference', sa.String(length=120), nullable=False),
        sa.Column('proof_url', sa.String(length=500), nullable=True),
        sa.Column('status', sa.String(length=10), server_default='pending', nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('reviewed_by', sa.Integer(), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rejection_reason', sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(['fee_record_id'], ['fee_records.id'], ),
        sa.ForeignKeyConstraint(['parent_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['reviewed_by'], ['users.id'], ),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        op.f('ix_fee_payment_requests_fee_record_id'), 'fee_payment_requests', ['fee_record_id'], unique=False
    )

    # ONE OPEN REQUEST PER FEE, enforced in the database rather than only by the
    # route's pre-check - two concurrent submits would both pass a SELECT-then-
    # INSERT check and both land, letting a parent flood the admin queue.
    #
    # PARTIAL (WHERE status = 'pending'), not a plain unique constraint: a plain
    # one would permit only one request per fee ever, so a parent whose claim was
    # rejected could never resubmit - and the resubmit flow is the entire point of
    # having a reject branch. Confirmed and rejected rows are history and must be
    # free to accumulate.
    #
    # Raw SQL because Alembic autogenerate cannot express a partial index.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_fee_payment_request_one_open
        ON fee_payment_requests (fee_record_id)
        WHERE status = 'pending'
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_fee_payment_request_one_open")
    op.drop_index(op.f('ix_fee_payment_requests_fee_record_id'), table_name='fee_payment_requests')
    op.drop_table('fee_payment_requests')
