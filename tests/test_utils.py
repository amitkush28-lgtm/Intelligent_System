"""
Test shared utility functions: ID generation, confidence capping, Brier scores.
"""

import pytest
from datetime import date


class TestIDGeneration:
    def test_prediction_id_format(self):
        from shared.utils import generate_prediction_id
        pid = generate_prediction_id("economist", "GDP will grow 3%")
        assert pid.startswith("PRED-")
        parts = pid.split("-")
        assert len(parts) == 3
        assert parts[1].isdigit()  # year
        assert len(parts[2]) == 4  # hex hash

    def test_event_id_deterministic_length(self):
        from shared.utils import generate_event_id
        from datetime import datetime
        eid = generate_event_id("gdelt", "test event", datetime(2026, 1, 1))
        assert len(eid) == 16

    def test_claim_id_format(self):
        from shared.utils import generate_claim_id
        cid = generate_claim_id("GDP grew 3%", "reuters")
        assert cid.startswith("CLM-")
        assert len(cid) == 12  # CLM- + 8 hex chars

    def test_debate_id_format(self):
        from shared.utils import generate_debate_id
        did = generate_debate_id("PRED-2026-A1B2", "economist")
        assert did.startswith("DBT-PRED-2026-A1B2-economist-")


class TestConfidenceCapping:
    def test_no_cap_within_limit(self):
        from shared.utils import cap_confidence_change
        # 0.70 integrity * 0.40 multiplier * 100 = 28pp max
        result = cap_confidence_change(10.0, 0.70)
        assert result == 10.0  # not capped

    def test_cap_applied(self):
        from shared.utils import cap_confidence_change
        # 0.40 integrity * 0.40 multiplier * 100 = 16pp max
        result = cap_confidence_change(20.0, 0.40)
        assert result == pytest.approx(16.0)  # capped

    def test_cap_negative_direction(self):
        from shared.utils import cap_confidence_change
        result = cap_confidence_change(-20.0, 0.40)
        assert result == pytest.approx(-16.0)

    def test_clamp_confidence(self):
        from shared.utils import clamp_confidence
        assert clamp_confidence(1.5) == 1.0
        assert clamp_confidence(-0.3) == 0.0
        assert clamp_confidence(0.7) == 0.7


class TestBrierScore:
    def test_perfect_prediction_true(self):
        from shared.utils import brier_score
        assert brier_score(1.0, True) == 0.0

    def test_perfect_prediction_false(self):
        from shared.utils import brier_score
        assert brier_score(0.0, False) == 0.0

    def test_worst_prediction(self):
        from shared.utils import brier_score
        assert brier_score(1.0, False) == 1.0
        assert brier_score(0.0, True) == 1.0

    def test_partial_confidence(self):
        from shared.utils import brier_score
        score = brier_score(0.7, True)
        assert abs(score - 0.09) < 0.001


class TestSourceIntegrity:
    def test_reuters_score(self):
        from shared.utils import get_initial_source_integrity
        assert get_initial_source_integrity("reuters") == 0.75

    def test_ap_score(self):
        from shared.utils import get_initial_source_integrity
        assert get_initial_source_integrity("ap") == 0.75

    def test_blog_score(self):
        from shared.utils import get_initial_source_integrity
        assert get_initial_source_integrity("blog") == 0.15

    def test_unknown_source_default(self):
        from shared.utils import get_initial_source_integrity
        assert get_initial_source_integrity("random_unknown_source") == 0.50


class TestConfidenceBucket:
    def test_bucket_ranges(self):
        from shared.utils import confidence_bucket
        assert confidence_bucket(0.55) == "50-60%"
        assert confidence_bucket(0.30) == "30-40%"
        assert confidence_bucket(0.99) == "90-100%"
        assert confidence_bucket(0.05) == "0-10%"


class TestIsPassedDeadline:
    def test_past_point_deadline(self):
        from shared.utils import is_past_deadline
        from unittest.mock import MagicMock
        pred = MagicMock()
        pred.time_condition_type = "point"
        pred.time_condition_date = date(2020, 1, 1)
        assert is_past_deadline(pred) is True

    def test_future_point_deadline(self):
        from shared.utils import is_past_deadline
        from unittest.mock import MagicMock
        pred = MagicMock()
        pred.time_condition_type = "point"
        pred.time_condition_date = date(2099, 12, 31)
        assert is_past_deadline(pred) is False

    def test_past_range_deadline(self):
        from shared.utils import is_past_deadline
        from unittest.mock import MagicMock
        pred = MagicMock()
        pred.time_condition_type = "range"
        pred.time_condition_end = date(2020, 6, 30)
        assert is_past_deadline(pred) is True


class TestLLMClientParsing:
    def test_parse_json_clean(self):
        from shared.llm_client import parse_structured_json
        result = parse_structured_json('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_with_fences(self):
        from shared.llm_client import parse_structured_json
        result = parse_structured_json('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_invalid(self):
        from shared.llm_client import parse_structured_json
        result = parse_structured_json("not json at all")
        assert result == {}
