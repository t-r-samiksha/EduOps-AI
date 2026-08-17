"""add person b remaining tables: quizzes, gradebook, report cards, library, calendar, remarks

Revision ID: c4d88004d004
Revises: c3c77003c003
Create Date: 2026-08-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'c4d88004d004'
down_revision: Union[str, None] = 'c3c77003c003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. quizzes
    op.create_table(
        'quizzes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('class_id', sa.Integer(), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('teacher_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('duration_minutes', sa.Integer(), server_default='30', nullable=False),
        sa.Column('available_from', sa.DateTime(timezone=True), nullable=True),
        sa.Column('available_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['teacher_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_quizzes_school_class', 'quizzes', ['school_id', 'class_id'], unique=False)
    op.create_index('ix_quizzes_teacher_id', 'quizzes', ['teacher_id'], unique=False)

    # 2. quiz_questions
    op.create_table(
        'quiz_questions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quiz_id', sa.Integer(), nullable=False),
        sa.Column('question_text', sa.Text(), nullable=False),
        sa.Column('option_a', sa.String(length=500), nullable=False),
        sa.Column('option_b', sa.String(length=500), nullable=False),
        sa.Column('option_c', sa.String(length=500), nullable=False),
        sa.Column('option_d', sa.String(length=500), nullable=False),
        sa.Column('correct_option', sa.String(length=1), nullable=False),
        sa.Column('marks', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('order_index', sa.Integer(), server_default='0', nullable=False),
        sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_quiz_questions_quiz_id', 'quiz_questions', ['quiz_id'], unique=False)

    # 3. quiz_attempts
    op.create_table(
        'quiz_attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('quiz_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('answers', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=False),
        sa.Column('score', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('total_marks', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('submitted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=30), server_default='completed', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['quiz_id'], ['quizzes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('quiz_id', 'student_id', name='uq_quiz_student_attempt')
    )
    op.create_index('ix_quiz_attempts_student', 'quiz_attempts', ['student_id'], unique=False)

    # 4. gradebook_entries
    op.create_table(
        'gradebook_entries',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=False),
        sa.Column('class_id', sa.Integer(), nullable=False),
        sa.Column('term', sa.String(length=50), nullable=False),
        sa.Column('assessment_type', sa.String(length=50), nullable=False),
        sa.Column('assessment_id', sa.Integer(), nullable=True),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('max_score', sa.Float(), server_default='100.0', nullable=False),
        sa.Column('weight', sa.Float(), server_default='1.0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'subject_id', 'term', 'assessment_type', 'assessment_id', name='uq_gradebook_student_assessment')
    )
    op.create_index('ix_gradebook_student_term', 'gradebook_entries', ['student_id', 'term'], unique=False)
    op.create_index('ix_gradebook_class_subject', 'gradebook_entries', ['class_id', 'subject_id'], unique=False)

    # 5. gradebook_weights
    op.create_table(
        'gradebook_weights',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('class_id', sa.Integer(), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('term', sa.String(length=50), server_default='Term 1', nullable=False),
        sa.Column('assignment_weight', sa.Float(), server_default='0.20', nullable=False),
        sa.Column('quiz_weight', sa.Float(), server_default='0.20', nullable=False),
        sa.Column('midterm_weight', sa.Float(), server_default='0.20', nullable=False),
        sa.Column('final_weight', sa.Float(), server_default='0.40', nullable=False),
        sa.Column('other_weight', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_gradebook_weights_school_term', 'gradebook_weights', ['school_id', 'term'], unique=False)

    # 6. report_cards
    op.create_table(
        'report_cards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('class_id', sa.Integer(), nullable=False),
        sa.Column('term', sa.String(length=50), nullable=False),
        sa.Column('academic_year', sa.String(length=20), server_default='2026-27', nullable=False),
        sa.Column('pdf_url', sa.String(length=500), nullable=True),
        sa.Column('gpa', sa.Float(), nullable=True),
        sa.Column('term_average', sa.Float(), nullable=True),
        sa.Column('attendance_percentage', sa.Float(), nullable=True),
        sa.Column('source_data_snapshot', sa.JSON().with_variant(JSONB, 'postgresql'), nullable=False),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('student_id', 'term', 'academic_year', name='uq_report_card_student_term_year')
    )
    op.create_index('ix_report_cards_class_term', 'report_cards', ['class_id', 'term'], unique=False)

    # 7. library_items
    op.create_table(
        'library_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('author', sa.String(length=255), nullable=True),
        sa.Column('isbn', sa.String(length=50), nullable=True),
        sa.Column('category', sa.String(length=100), server_default='General', nullable=False),
        sa.Column('type', sa.String(length=50), server_default='book', nullable=False),
        sa.Column('available_copies', sa.Integer(), server_default='1', nullable=False),
        sa.Column('total_copies', sa.Integer(), server_default='1', nullable=False),
        sa.Column('file_url', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_library_items_school_cat', 'library_items', ['school_id', 'category'], unique=False)
    op.create_index('ix_library_items_type', 'library_items', ['type'], unique=False)

    # 8. library_loans
    op.create_table(
        'library_loans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('library_item_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('issued_by', sa.Integer(), nullable=True),
        sa.Column('issued_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('due_date', sa.DateTime(timezone=True), nullable=False),
        sa.Column('returned_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=30), server_default='active', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['issued_by'], ['users.id']),
        sa.ForeignKeyConstraint(['library_item_id'], ['library_items.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_library_loans_student_status', 'library_loans', ['student_id', 'status'], unique=False)
    op.create_index('ix_library_loans_item', 'library_loans', ['library_item_id'], unique=False)

    # 9. calendar_events
    op.create_table(
        'calendar_events',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source_id', sa.Integer(), nullable=True),
        sa.Column('source_type', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'source_type', 'source_id', 'start_time', name='uq_calendar_user_source_time')
    )
    op.create_index('ix_calendar_user_times', 'calendar_events', ['user_id', 'start_time', 'end_time'], unique=False)
    op.create_index('ix_calendar_event_type', 'calendar_events', ['event_type'], unique=False)

    # 10. remarks
    op.create_table(
        'remarks',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('school_id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('author_id', sa.Integer(), nullable=False),
        sa.Column('class_id', sa.Integer(), nullable=False),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('sentiment_tag', sa.String(length=50), server_default='academic', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['users.id']),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['school_id'], ['schools.id']),
        sa.ForeignKeyConstraint(['student_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_remarks_student_id', 'remarks', ['student_id'], unique=False)
    op.create_index('ix_remarks_class_subject', 'remarks', ['class_id', 'subject_id'], unique=False)
    op.create_index('ix_remarks_sentiment', 'remarks', ['sentiment_tag'], unique=False)


def downgrade() -> None:
    op.drop_table('remarks')
    op.drop_table('calendar_events')
    op.drop_table('library_loans')
    op.drop_table('library_items')
    op.drop_table('report_cards')
    op.drop_table('gradebook_weights')
    op.drop_table('gradebook_entries')
    op.drop_table('quiz_attempts')
    op.drop_table('quiz_questions')
    op.drop_table('quizzes')
