"""add living questions tables

Revision ID: 003_living_questions
Revises: 002_nullable_notes
Create Date: 2026-03-28

Adds tables for the Living Questions / Thesis Tracker feature:
- living_questions: user-submitted questions with system analysis
- question_assumptions: falsifiable assumptions that the thesis depends on
- question_evidence: evidence log for/against each assumption
- question_reanalyses: history of re-analyses
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '003_living_questions'
down_revision = '002_nullable_notes'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Living Questions
    op.create_table(
        'living_questions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('question', sa.Text(), nullable=False),
        sa.Column('context', sa.Text(), nullable=True),
        sa.Column('category', sa.String(), nullable=True),
        sa.Column('thesis_summary', sa.Text(), nullable=True),
        sa.Column('thesis_verdict', sa.String(), nullable=True),
        sa.Column('overall_confidence', sa.Integer(), nullable=True),
        sa.Column('overall_status', sa.String(), server_default='green'),
        sa.Column('recommendation', sa.Text(), nullable=True),
        sa.Column('initial_analysis', sa.JSON(), nullable=True),
        sa.Column('latest_analysis', sa.JSON(), nullable=True),
        sa.Column('agent_perspectives', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(), server_default='active'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('last_analyzed_at', sa.DateTime(), nullable=True),
        sa.Column('last_evidence_at', sa.DateTime(), nullable=True),
        sa.Column('next_review_date', sa.Date(), nullable=True),
        sa.Column('resolution_note', sa.Text(), nullable=True),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('priority', sa.String(), server_default='normal'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_living_questions_status', 'living_questions', ['status'])

    # Question Assumptions
    op.create_table(
        'question_assumptions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('question_id', sa.String(), sa.ForeignKey('living_questions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assumption_text', sa.Text(), nullable=False),
        sa.Column('assumption_number', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), server_default='green'),
        sa.Column('confidence', sa.Integer(), nullable=True),
        sa.Column('green_to_yellow_trigger', sa.Text(), nullable=True),
        sa.Column('yellow_to_red_trigger', sa.Text(), nullable=True),
        sa.Column('red_conditions', sa.Text(), nullable=True),
        sa.Column('supporting_evidence_count', sa.Integer(), server_default='0'),
        sa.Column('challenging_evidence_count', sa.Integer(), server_default='0'),
        sa.Column('current_assessment', sa.Text(), nullable=True),
        sa.Column('last_status_change_at', sa.DateTime(), nullable=True),
        sa.Column('last_status_change_reason', sa.Text(), nullable=True),
        sa.Column('keywords', sa.JSON(), nullable=True),
        sa.Column('relevant_agents', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_question_assumptions_question', 'question_assumptions', ['question_id'])

    # Question Evidence
    op.create_table(
        'question_evidence',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('question_id', sa.String(), sa.ForeignKey('living_questions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('assumption_id', sa.String(), sa.ForeignKey('question_assumptions.id', ondelete='CASCADE'), nullable=True),
        sa.Column('event_id', sa.String(), sa.ForeignKey('events.id'), nullable=True),
        sa.Column('evidence_type', sa.String(), nullable=False),
        sa.Column('evidence_summary', sa.Text(), nullable=False),
        sa.Column('evidence_detail', sa.Text(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('source_url', sa.Text(), nullable=True),
        sa.Column('impact_level', sa.String(), nullable=True),
        sa.Column('triggered_status_change', sa.Boolean(), server_default='false'),
        sa.Column('previous_status', sa.String(), nullable=True),
        sa.Column('new_status', sa.String(), nullable=True),
        sa.Column('detected_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('detected_by', sa.String(), nullable=True),
        sa.Column('agent_that_flagged', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_question_evidence_question', 'question_evidence', ['question_id'])
    op.create_index('idx_question_evidence_assumption', 'question_evidence', ['assumption_id'])

    # Question Reanalyses
    op.create_table(
        'question_reanalyses',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('question_id', sa.String(), sa.ForeignKey('living_questions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('trigger_type', sa.String(), nullable=True),
        sa.Column('trigger_description', sa.Text(), nullable=True),
        sa.Column('previous_verdict', sa.String(), nullable=True),
        sa.Column('new_verdict', sa.String(), nullable=True),
        sa.Column('previous_confidence', sa.Integer(), nullable=True),
        sa.Column('new_confidence', sa.Integer(), nullable=True),
        sa.Column('previous_status', sa.String(), nullable=True),
        sa.Column('new_status', sa.String(), nullable=True),
        sa.Column('full_analysis', sa.JSON(), nullable=True),
        sa.Column('changes_summary', sa.Text(), nullable=True),
        sa.Column('assumption_updates', sa.JSON(), nullable=True),
        sa.Column('included_in_newsletter', sa.Boolean(), server_default='false'),
        sa.Column('newsletter_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('idx_question_reanalyses_question', 'question_reanalyses', ['question_id'])


def downgrade() -> None:
    op.drop_table('question_reanalyses')
    op.drop_table('question_evidence')
    op.drop_table('question_assumptions')
    op.drop_table('living_questions')
