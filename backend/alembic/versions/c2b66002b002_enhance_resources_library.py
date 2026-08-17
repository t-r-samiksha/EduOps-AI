"""enhance resources library

Revision ID: c2b66002b002
Revises: c1a55001b001
Create Date: 2026-08-17 11:09:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2b66002b002'
down_revision: Union[str, None] = 'c1a55001b001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('resources', sa.Column('class_id', sa.Integer(), nullable=True))
    op.add_column('resources', sa.Column('description', sa.Text(), nullable=True))
    op.add_column('resources', sa.Column('unit', sa.String(length=100), nullable=True))
    op.add_column('resources', sa.Column('file_size', sa.Integer(), server_default='0', nullable=False))
    op.add_column('resources', sa.Column('needs_reindex', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('resources', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True))

    op.create_foreign_key(
        'fk_resources_class_id_classes',
        'resources',
        'classes',
        ['class_id'],
        ['id'],
        ondelete='SET NULL'
    )
    op.create_index('ix_resources_class_id', 'resources', ['class_id'], unique=False)
    op.create_index('ix_resources_class_subject', 'resources', ['class_id', 'subject_id'], unique=False)
    op.create_index('ix_resources_school_unit', 'resources', ['school_id', 'unit'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_resources_school_unit', table_name='resources')
    op.drop_index('ix_resources_class_subject', table_name='resources')
    op.drop_index('ix_resources_class_id', table_name='resources')
    op.drop_constraint('fk_resources_class_id_classes', 'resources', type_='foreignkey')

    op.drop_column('resources', 'updated_at')
    op.drop_column('resources', 'needs_reindex')
    op.drop_column('resources', 'file_size')
    op.drop_column('resources', 'unit')
    op.drop_column('resources', 'description')
    op.drop_column('resources', 'class_id')
