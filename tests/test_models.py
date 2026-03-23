"""
Test ORM model definitions: table names, columns, foreign keys, relationships.
"""

import pytest
from sqlalchemy import inspect


class TestModelDefinitions:
    """Verify all 14 ORM models have correct table names and structure."""

    def test_prediction_table(self):
        from shared.models import Prediction
        assert Prediction.__tablename__ == "predictions"
        cols = {c.name for c in Prediction.__table__.columns}
        required = {
            "id", "agent", "claim", "time_condition_type",
            "resolution_criteria", "status", "current_confidence",
        }
        assert required.issubset(cols)

    def test_confidence_trail_table(self):
        from shared.models import ConfidenceTrail
        assert ConfidenceTrail.__tablename__ == "confidence_trail"
        cols = {c.name for c in ConfidenceTrail.__table__.columns}
        assert {"id", "prediction_id", "value", "trigger", "reasoning"}.issubset(cols)

    def test_note_table(self):
        from shared.models import Note
        assert Note.__tablename__ == "notes"
        cols = {c.name for c in Note.__table__.columns}
        assert {"id", "prediction_id", "type", "text"}.issubset(cols)

    def test_event_table(self):
        from shared.models import Event
        assert Event.__tablename__ == "events"
        cols = {c.name for c in Event.__table__.columns}
        assert {"id", "source", "source_reliability", "timestamp", "domain"}.issubset(cols)

    def test_actor_table(self):
        from shared.models import Actor
        assert Actor.__tablename__ == "actors"
        cols = {c.name for c in Actor.__table__.columns}
        assert {"id", "name", "type"}.issubset(cols)

    def test_relationship_table(self):
        from shared.models import Relationship
        assert Relationship.__tablename__ == "relationships"
        cols = {c.name for c in Relationship.__table__.columns}
        assert {"id", "actor_from", "actor_to", "relationship_type"}.issubset(cols)

    def test_claim_table(self):
        from shared.models import Claim
        assert Claim.__tablename__ == "claims"
        cols = {c.name for c in Claim.__table__.columns}
        assert {
            "id", "claim_text", "initial_source",
            "initial_integrity", "current_integrity", "verification_status",
        }.issubset(cols)

    def test_source_reliability_table(self):
        from shared.models import SourceReliability
        assert SourceReliability.__tablename__ == "source_reliability"
        cols = {c.name for c in SourceReliability.__table__.columns}
        assert {"id", "source_name", "domain", "reliability_score"}.issubset(cols)

    def test_calibration_score_table(self):
        from shared.models import CalibrationScore
        assert CalibrationScore.__tablename__ == "calibration_scores"
        cols = {c.name for c in CalibrationScore.__table__.columns}
        assert {"id", "agent", "confidence_bucket", "predicted_avg", "actual_avg"}.issubset(cols)

    def test_agent_prompt_table(self):
        from shared.models import AgentPrompt
        assert AgentPrompt.__tablename__ == "agent_prompts"
        cols = {c.name for c in AgentPrompt.__table__.columns}
        assert {"id", "agent", "version", "prompt_text", "active"}.issubset(cols)

    def test_debate_table(self):
        from shared.models import Debate
        assert Debate.__tablename__ == "debates"
        cols = {c.name for c in Debate.__table__.columns}
        assert {"id", "prediction_id", "agent", "trigger_reason", "rounds"}.issubset(cols)

    def test_base_rate_class_table(self):
        from shared.models import BaseRateClass
        assert BaseRateClass.__tablename__ == "base_rate_classes"
        cols = {c.name for c in BaseRateClass.__table__.columns}
        assert {"id", "class_name", "cases", "base_rate"}.issubset(cols)

    def test_weak_signal_table(self):
        from shared.models import WeakSignal
        assert WeakSignal.__tablename__ == "weak_signals"
        cols = {c.name for c in WeakSignal.__table__.columns}
        assert {"id", "signal", "strength", "status"}.issubset(cols)

    def test_decision_mapping_table(self):
        from shared.models import DecisionMapping
        assert DecisionMapping.__tablename__ == "decision_mappings"
        cols = {c.name for c in DecisionMapping.__table__.columns}
        assert {"id", "prediction_id", "action", "trigger_condition", "urgency"}.issubset(cols)


class TestForeignKeys:
    """Verify foreign key relationships are correctly defined."""

    def test_confidence_trail_fk(self):
        from shared.models import ConfidenceTrail
        fks = [fk.target_fullname for col in ConfidenceTrail.__table__.columns for fk in col.foreign_keys]
        assert "predictions.id" in fks

    def test_note_fk(self):
        from shared.models import Note
        fks = [fk.target_fullname for col in Note.__table__.columns for fk in col.foreign_keys]
        assert "predictions.id" in fks

    def test_debate_fk(self):
        from shared.models import Debate
        fks = [fk.target_fullname for col in Debate.__table__.columns for fk in col.foreign_keys]
        assert "predictions.id" in fks

    def test_prediction_self_ref_fk(self):
        from shared.models import Prediction
        fks = [fk.target_fullname for col in Prediction.__table__.columns for fk in col.foreign_keys]
        assert "predictions.id" in fks  # parent_id self-reference

    def test_claim_fk(self):
        from shared.models import Claim
        fks = [fk.target_fullname for col in Claim.__table__.columns for fk in col.foreign_keys]
        assert "events.id" in fks

    def test_relationship_fks(self):
        from shared.models import Relationship
        fks = [fk.target_fullname for col in Relationship.__table__.columns for fk in col.foreign_keys]
        assert fks.count("actors.id") == 2  # actor_from + actor_to

    def test_decision_mapping_fk(self):
        from shared.models import DecisionMapping
        fks = [fk.target_fullname for col in DecisionMapping.__table__.columns for fk in col.foreign_keys]
        assert "predictions.id" in fks


class TestNullability:
    """Verify critical columns are not nullable."""

    def test_prediction_required_fields(self):
        from shared.models import Prediction
        col_map = {c.name: c for c in Prediction.__table__.columns}
        assert col_map["agent"].nullable is False
        assert col_map["claim"].nullable is False
        assert col_map["time_condition_type"].nullable is False
        assert col_map["resolution_criteria"].nullable is False
        assert col_map["status"].nullable is False
        assert col_map["current_confidence"].nullable is False

    def test_event_required_fields(self):
        from shared.models import Event
        col_map = {c.name: c for c in Event.__table__.columns}
        assert col_map["source"].nullable is False
        assert col_map["source_reliability"].nullable is False
        assert col_map["timestamp"].nullable is False
        assert col_map["domain"].nullable is False

    def test_claim_required_fields(self):
        from shared.models import Claim
        col_map = {c.name: c for c in Claim.__table__.columns}
        assert col_map["claim_text"].nullable is False
        assert col_map["initial_source"].nullable is False
        assert col_map["initial_integrity"].nullable is False
        assert col_map["current_integrity"].nullable is False
