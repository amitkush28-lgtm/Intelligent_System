"""Add sub-assumption hierarchy support.

Adds parent_id, sub_label, monitoring_data_points, and baseline_data
columns to question_assumptions for nested assumption tracking.
Also adds tool_actions column to question_followups to track
structured actions taken during follow-up conversations.

Revision ID: 005
"""

from alembic import op
import sqlalchemy as sa

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    # Add hierarchy columns to question_assumptions
    op.add_column(
        "question_assumptions",
        sa.Column("parent_id", sa.String(), sa.ForeignKey("question_assumptions.id", ondelete="CASCADE"), nullable=True),
    )
    op.add_column(
        "question_assumptions",
        sa.Column("sub_label", sa.String(), nullable=True),
    )
    op.add_column(
        "question_assumptions",
        sa.Column("monitoring_data_points", sa.JSON(), nullable=True),
    )
    op.add_column(
        "question_assumptions",
        sa.Column("baseline_data", sa.JSON(), nullable=True),
    )

    # Add tool_actions column to question_followups to track structured actions
    op.add_column(
        "question_followups",
        sa.Column("tool_actions", sa.JSON(), nullable=True),
    )

    # Index for sub-assumption lookup
    op.create_index("idx_assumption_parent", "question_assumptions", ["parent_id"])


def downgrade():
    op.drop_index("idx_assumption_parent")
    op.drop_column("question_followups", "tool_actions")
    op.drop_column("question_assumptions", "baseline_data")
    op.drop_column("question_assumptions", "monitoring_data_points")
    op.drop_column("question_assumptions", "sub_label")
    op.drop_column("question_assumptions", "parent_id")
