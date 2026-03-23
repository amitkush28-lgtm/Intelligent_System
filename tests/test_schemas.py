"""
Test Pydantic schema validation: construction, field types, defaults.
"""

import pytest
from datetime import date, datetime


class TestPredictionSchemas:
    def test_prediction_create_valid(self):
        from shared.schemas import PredictionCreate
        pred = PredictionCreate(
            agent="economist",
            claim="GDP growth will exceed 3% in Q2 2026",
            time_condition_type="range",
            time_condition_start=date(2026, 4, 1),
            time_condition_end=date(2026, 6, 30),
            resolution_criteria="BEA advance estimate shows annualized GDP growth >= 3.0%",
            current_confidence=0.65,
        )
        assert pred.agent == "economist"
        assert pred.current_confidence == 0.65

    def test_prediction_create_rejects_invalid_confidence(self):
        from shared.schemas import PredictionCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PredictionCreate(
                agent="economist",
                claim="test",
                time_condition_type="point",
                resolution_criteria="test",
                current_confidence=1.5,  # > 1.0
            )

    def test_prediction_create_rejects_negative_confidence(self):
        from shared.schemas import PredictionCreate
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PredictionCreate(
                agent="economist",
                claim="test",
                time_condition_type="point",
                resolution_criteria="test",
                current_confidence=-0.1,  # < 0.0
            )

    def test_prediction_response_from_dict(self):
        from shared.schemas import PredictionResponse
        data = {
            "id": "PRED-2026-A1B2",
            "agent": "geopolitical",
            "claim": "Test claim",
            "time_condition_type": "point",
            "resolution_criteria": "Observable outcome",
            "status": "ACTIVE",
            "current_confidence": 0.7,
        }
        resp = PredictionResponse(**data)
        assert resp.id == "PRED-2026-A1B2"
        assert resp.brier_score is None  # optional field defaults

    def test_prediction_detail_has_nested(self):
        from shared.schemas import PredictionDetail
        data = {
            "id": "PRED-2026-C3D4",
            "agent": "investor",
            "claim": "S&P will reach 6000",
            "time_condition_type": "range",
            "resolution_criteria": "S&P 500 closes above 6000",
            "status": "ACTIVE",
            "current_confidence": 0.55,
            "confidence_trail": [],
            "notes": [],
            "debates": [],
            "sub_predictions": [],
        }
        detail = PredictionDetail(**data)
        assert isinstance(detail.confidence_trail, list)
        assert isinstance(detail.sub_predictions, list)


class TestDashboardSchemas:
    def test_dashboard_metrics_defaults(self):
        from shared.schemas import DashboardMetrics
        m = DashboardMetrics()
        assert m.active_predictions == 0
        assert m.total_predictions == 0
        assert m.system_brier_score is None
        assert m.agents == []
        assert m.recent_activity == []

    def test_calibration_bucket(self):
        from shared.schemas import CalibrationBucket
        b = CalibrationBucket(
            bucket="50-60%",
            predicted_avg=0.55,
            actual_avg=0.62,
            count=15,
        )
        assert b.bucket == "50-60%"
        assert b.count == 15

    def test_calibration_curve_response(self):
        from shared.schemas import CalibrationCurveResponse
        resp = CalibrationCurveResponse(overall=[], by_agent={})
        assert resp.overall == []
        assert resp.by_agent == {}


class TestAgentSchemas:
    def test_agent_metrics_defaults(self):
        from shared.schemas import AgentMetrics
        m = AgentMetrics(agent="economist")
        assert m.total_predictions == 0
        assert m.known_biases == []
        assert m.accuracy is None

    def test_agent_list_response(self):
        from shared.schemas import AgentListResponse, AgentMetrics
        r = AgentListResponse(agents=[
            AgentMetrics(agent="economist"),
            AgentMetrics(agent="geopolitical"),
        ])
        assert len(r.agents) == 2


class TestOtherSchemas:
    def test_note_create(self):
        from shared.schemas import NoteCreate
        n = NoteCreate(type="observation", text="Interesting development")
        assert n.type == "observation"

    def test_debate_response(self):
        from shared.schemas import DebateResponse
        d = DebateResponse(
            id="DBT-001",
            agent="economist",
            trigger_reason="confidence moved >5pp",
        )
        assert d.prediction_id is None
        assert d.rounds is None

    def test_weak_signal_response(self):
        from shared.schemas import WeakSignalResponse
        s = WeakSignalResponse(id=1, signal="[ORPHAN] Unusual trade pattern")
        assert s.strength is None
        assert s.status is None

    def test_decision_response(self):
        from shared.schemas import DecisionResponse
        d = DecisionResponse(
            id=1,
            action="Hedge exposure to EUR",
            trigger_condition="ECB signals rate cut",
        )
        assert d.prediction is None
        assert d.urgency is None

    def test_paginated_response(self):
        from shared.schemas import PaginatedResponse
        p = PaginatedResponse(items=["a", "b"], total=100, page=1, page_size=50)
        assert len(p.items) == 2
        assert p.total == 100

    def test_event_response(self):
        from shared.schemas import EventResponse
        e = EventResponse(
            id="evt-001",
            source="gdelt",
            source_reliability=0.5,
            timestamp=datetime(2026, 3, 15, 10, 0, 0),
            domain="geopolitical",
        )
        assert e.severity is None

    def test_claim_verification_response(self):
        from shared.schemas import ClaimVerificationResponse
        c = ClaimVerificationResponse(
            id="CLM-001",
            claim_text="Test claim",
            initial_source="reuters",
            initial_integrity=0.75,
            current_integrity=0.80,
            verification_status="CORROBORATED",
            corroboration_count=3,
            contradiction_count=0,
            independent_source_count=3,
            sponsored_flag=False,
        )
        assert c.verification_status == "CORROBORATED"


class TestEnums:
    def test_prediction_status_values(self):
        from shared.schemas import PredictionStatus
        assert set(PredictionStatus) == {
            PredictionStatus.ACTIVE,
            PredictionStatus.RESOLVED_TRUE,
            PredictionStatus.RESOLVED_FALSE,
            PredictionStatus.SUPERSEDED,
            PredictionStatus.EXPIRED,
        }

    def test_agent_name_values(self):
        from shared.schemas import AgentName
        names = {a.value for a in AgentName}
        assert names == {"geopolitical", "economist", "investor", "political", "sentiment", "master"}

    def test_domain_values(self):
        from shared.schemas import Domain
        domains = {d.value for d in Domain}
        assert domains == {"geopolitical", "economic", "market", "political", "sentiment"}
