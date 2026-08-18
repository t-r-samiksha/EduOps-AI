"""add assignments and submissions tables

Revision ID: c3c77003c003
Revises: c2b66002b002
Create Date: 2026-08-17 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3c77003c003'
down_revision: Union[str, None] = 'c2b66002b002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. assignments
    op.create_table(
        'assignments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('class_id', sa.Integer(), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('deadline', sa.DateTime(timezone=True), nullable=False),
        sa.Column('max_marks', sa.Float(), server_default='100.0', nullable=False),
        sa.Column('attachment_url', sa.String(length=500), nullable=True),
        sa.Column('attachment_name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id'], ),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_assignments_school_class', 'assignments', ['school_id', 'class_id'], unique=False)
    op.create_index('ix_assignments_deadline', 'assignments', ['deadline'], unique=False)
    op.create_index('ix_assignments_teacher_id', 'assignments', ['teacher_id'], unique=False)

    # 2. assignment_submissions
    op.create_table(
        'assignment_submissions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('assignment_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('file_url', sa.String(length=500), nullable=True),
        sa.Column('file_name', sa.String(length=255), nullable=True),
        sa.Column('file_size', sa.Integer(), server_default='0', nullable=False),
        sa.Column('grade', sa.Float(), nullable=True),
        sa.Column('feedback', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=30), server_default='submitted', nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('graded_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['assignment_id'], ['assignments.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('assignment_id', 'student_id', name='uq_assignment_student_submission')
    )
    op.create_index('ix_submissions_assignment_student', 'assignment_submissions', ['assignment_id', 'student_id'], unique=False)
    op.create_index('ix_submissions_student_status', 'assignment_submissions', ['student_id', 'status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_submissions_student_status', table_name='assignment_submissions')
    op.drop_index('ix_submissions_assignment_student', table_name='assignment_submissions')
    op.drop_table('assignment_submissions')

    op.drop_index('ix_assignments_teacher_id', table_name='assignments')
    op.drop_index('ix_assignments_deadline', table_name='assignments')
    op.drop_index('ix_assignments_school_class', table_name='assignments')
    op.drop_table('assignments')
