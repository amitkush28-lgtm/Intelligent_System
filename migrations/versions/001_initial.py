"""initial schema - complete database from development brief Part 5

Revision ID: 001_initial
Revises: None
Create Date: 2026-03-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ============================================
    # CORE TABLES
    # ============================================
    op.create_table(
        "predictions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("time_condition_type", sa.String(), nullable=False),
        sa.Column("time_condition_date", sa.Date(), nullable=True),
        sa.Column("time_condition_start", sa.Date(), nullable=True),
        sa.Column("time_condition_end", sa.Date(), nullable=True),
        sa.Column("resolution_criteria", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="ACTIVE"),
        sa.Column("current_confidence", sa.Float(), nullable=False),
        sa.Column("parent_id", sa.String(), sa.ForeignKey("predictions.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("resolved_date", sa.Date(), nullable=True),
        sa.Column("resolved_outcome", sa.Boolean(), nullable=True),
        sa.Column("brier_score", sa.Float(), nullable=True),
        sa.Column("post_mortem", sa.JSON(), nullable=True),
    )
    op.create_index("idx_predictions_status", "predictions", ["status"])
    op.create_index("idx_predictions_agent", "predictions", ["agent"])
    op.create_index("idx_predictions_parent", "predictions", ["parent_id"])

    op.create_table(
        "confidence_trail",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("prediction_id", sa.String(), sa.ForeignKey("predictions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("reasoning", sa.Text(), nullable=False),
        sa.Column("event_ref", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("idx_confidence_trail_pred", "confidence_trail", ["prediction_id"])

    op.create_table(
        "notes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("prediction_id", sa.String(), sa.ForeignKey("predictions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
    )
    op.create_index("idx_notes_pred", "notes", ["prediction_id"])

    op.create_table(
        "events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("source_reliability", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(), nullable=True),
        sa.Column("severity", sa.String(), nullable=True),
        sa.Column("entities", sa.JSON(), nullable=True),
        sa.Column("claims", sa.JSON(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("integrity_score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("idx_events_domain", "events", ["domain"])
    op.create_index("idx_events_timestamp", "events", ["timestamp"])

    # ============================================
    # KNOWLEDGE GRAPH
    # ============================================
    op.create_table(
        "actors",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=True),
        sa.Column("objective_function", sa.Text(), nullable=True),
        sa.Column("deep_motivations", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "relationships",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor_from", sa.String(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("actor_to", sa.String(), sa.ForeignKey("actors.id"), nullable=False),
        sa.Column("relationship_type", sa.String(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ============================================
    # VERIFICATION ENGINE
    # ============================================
    op.create_table(
        "claims",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_id", sa.String(), sa.ForeignKey("events.id"), nullable=True),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("initial_source", sa.String(), nullable=False),
        sa.Column("initial_integrity", sa.Float(), nullable=False),
        sa.Column("current_integrity", sa.Float(), nullable=False),
        sa.Column("verification_status", sa.String(), server_default="UNVERIFIED"),
        sa.Column("corroboration_count", sa.Integer(), server_default="0"),
        sa.Column("contradiction_count", sa.Integer(), server_default="0"),
        sa.Column("independent_source_count", sa.Integer(), server_default="1"),
        sa.Column("cross_modal_sources", sa.JSON(), nullable=True),
        sa.Column("provenance_trace", sa.JSON(), nullable=True),
        sa.Column("evidence_chain", sa.JSON(), nullable=True),
        sa.Column("sponsored_flag", sa.Boolean(), server_default="false"),
        sa.Column("sponsored_reasoning", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_claims_status", "claims", ["verification_status"])
    op.create_index("idx_claims_integrity", "claims", ["current_integrity"])

    op.create_table(
        "source_reliability",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_name", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("total_claims", sa.Integer(), server_default="0"),
        sa.Column("verified_accurate", sa.Integer(), server_default="0"),
        sa.Column("verified_inaccurate", sa.Integer(), server_default="0"),
        sa.Column("reliability_score", sa.Float(), server_default="0.50"),
        sa.Column("last_updated", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_source_domain", "source_reliability", ["source_name", "domain"], unique=True)

    # ============================================
    # CALIBRATION & FEEDBACK
    # ============================================
    op.create_table(
        "calibration_scores",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("confidence_bucket", sa.String(), nullable=True),
        sa.Column("predicted_avg", sa.Float(), nullable=True),
        sa.Column("actual_avg", sa.Float(), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("brier_avg", sa.Float(), nullable=True),
        sa.Column("bias_direction", sa.String(), nullable=True),
        sa.Column("calculated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("idx_calibration_agent", "calibration_scores", ["agent"])

    op.create_table(
        "agent_prompts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("calibration_notes", sa.Text(), nullable=True),
        sa.Column("reasoning_guidance", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("active", sa.Boolean(), server_default="true"),
    )

    op.create_table(
        "debates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("prediction_id", sa.String(), sa.ForeignKey("predictions.id"), nullable=True),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("trigger_reason", sa.Text(), nullable=False),
        sa.Column("rounds", sa.JSON(), nullable=True),
        sa.Column("devil_impact", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ============================================
    # BASE RATES & REFERENCE
    # ============================================
    op.create_table(
        "base_rate_classes",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("class_name", sa.String(), nullable=False),
        sa.Column("cases", sa.Integer(), nullable=False),
        sa.Column("timespan", sa.String(), nullable=True),
        sa.Column("base_rate", sa.Float(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("examples", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    # ============================================
    # ADVANCED LAYERS
    # ============================================
    op.create_table(
        "weak_signals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("signal", sa.Text(), nullable=False),
        sa.Column("strength", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=True),
        sa.Column("attributed_to", sa.String(), nullable=True),
        sa.Column("detected_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "decision_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("prediction_id", sa.String(), sa.ForeignKey("predictions.id"), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("trigger_condition", sa.Text(), nullable=False),
        sa.Column("urgency", sa.String(), nullable=True),
        sa.Column("domain", sa.String(), nullable=True),
        sa.Column("inert_threshold", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("decision_mappings")
    op.drop_table("weak_signals")
    op.drop_table("base_rate_classes")
    op.drop_table("debates")
    op.drop_table("agent_prompts")
    op.drop_table("calibration_scores")
    op.drop_table("source_reliability")
    op.drop_table("claims")
    op.drop_table("relationships")
    op.drop_table("actors")
    op.drop_table("notes")
    op.drop_table("confidence_trail")
    op.drop_table("events")
    op.drop_table("predictions")
