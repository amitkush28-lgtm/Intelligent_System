"""add question followups table

Revision ID: 004_question_followups
Revises: 003_living_questions
Create Date: 2026-03-29

Adds the question_followups table for follow-up conversations on Living Questions.
"""

from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '004_question_followups'
down_revision = '003_living_questions'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'question_followups',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('question_id', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(['question_id'], ['living_questions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_question_followups_question', 'question_followups', ['question_id'])


def downgrade() -> None:
    op.drop_index('idx_question_followups_question', table_name='question_followups')
    op.drop_table('question_followups')
