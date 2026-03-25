"""make notes prediction_id nullable

Revision ID: 002_nullable_notes
Revises: 001_initial
Create Date: 2026-03-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_nullable_notes"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("notes", "prediction_id",
                     existing_type=sa.String(),
                     nullable=True)


def downgrade() -> None:
    op.alter_column("notes", "prediction_id",
                     existing_type=sa.String(),
                     nullable=False)
