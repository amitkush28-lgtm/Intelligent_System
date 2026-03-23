"""
Test that all service modules can be imported without errors.

This catches broken imports, missing dependencies, and circular references
that would prevent services from starting.
"""

import pytest


# ============================================
# SHARED LIBRARY
# ============================================

class TestSharedImports:
    def test_import_models(self):
        from shared.models import (
            Prediction, ConfidenceTrail, Note, Event,
            Actor, Relationship,
            Claim, SourceReliability,
            CalibrationScore, AgentPrompt, Debate,
            BaseRateClass, WeakSignal, DecisionMapping,
        )
        # Verify all 14 models exist
        models = [
            Prediction, ConfidenceTrail, Note, Event,
            Actor, Relationship,
            Claim, SourceReliability,
            CalibrationScore, AgentPrompt, Debate,
            BaseRateClass, WeakSignal, DecisionMapping,
        ]
        assert len(models) == 14

    def test_import_schemas(self):
        from shared.schemas import (
            PredictionStatus, TimeConditionType, Severity, Domain,
            AgentName, SignalStrength, Urgency, VerificationStatus,
            PredictionCreate, PredictionUpdate, PredictionResponse,
            PredictionDetail, ConfidenceTrailCreate, ConfidenceTrailResponse,
            NoteCreate, NoteResponse, EventResponse,
            AgentMetrics, AgentListResponse,
            DebateResponse, DashboardMetrics,
            CalibrationBucket, CalibrationCurveResponse,
            WeakSignalResponse, ClaimVerificationResponse,
            DecisionResponse, PaginatedResponse,
        )
        assert PredictionStatus.ACTIVE == "ACTIVE"

    def test_import_config(self):
        from shared.config import get_settings, Settings
        settings = get_settings()
        assert isinstance(settings, Settings)
        assert settings.ENVIRONMENT == "testing"

    def test_import_llm_client(self):
        from shared.llm_client import (
            call_claude_sonnet, call_claude_haiku,
            call_gpt4o, call_claude_with_web_search,
            parse_structured_json,
        )
        assert callable(call_claude_sonnet)
        assert callable(call_claude_haiku)
        assert callable(call_gpt4o)
        assert callable(call_claude_with_web_search)
        assert callable(parse_structured_json)

    def test_import_utils(self):
        from shared.utils import (
            generate_prediction_id, generate_event_id,
            generate_claim_id, generate_debate_id,
            cap_confidence_change, clamp_confidence,
            get_initial_source_integrity, confidence_bucket,
            is_past_deadline, brier_score, setup_logging,
        )
        assert callable(generate_prediction_id)
        assert callable(brier_score)

    def test_import_database(self):
        from shared.database import Base, get_db, get_db_session
        assert Base is not None
        assert callable(get_db)
        assert callable(get_db_session)


# ============================================
# API SERVICE
# ============================================

class TestAPIImports:
    def test_import_api_main(self):
        from services.api.main import app
        assert app is not None
        assert app.title == "Multi-Agent Intelligence System"

    def test_import_api_auth(self):
        from services.api.auth import verify_api_key
        assert callable(verify_api_key)

    def test_import_all_routes(self):
        from services.api.routes.predictions import router as r1
        from services.api.routes.agents import router as r2
        from services.api.routes.dashboard import router as r3
        from services.api.routes.debates import router as r4
        from services.api.routes.signals import router as r5
        from services.api.routes.claims import router as r6
        from services.api.routes.decisions import router as r7
        from services.api.routes.events import router as r8
        from services.api.routes.chat import router as r9
        routers = [r1, r2, r3, r4, r5, r6, r7, r8, r9]
        assert len(routers) == 9


# ============================================
# INGESTION SERVICE
# ============================================

class TestIngestionImports:
    def test_import_pipeline(self):
        from services.ingestion.pipeline.nlp import enrich_event_entities
        from services.ingestion.pipeline.classifier import classify_events_batch
        from services.ingestion.pipeline.dedup import deduplicate_batch
        from services.ingestion.pipeline.claim_extractor import extract_claims_batch
        assert callable(enrich_event_entities)
        assert callable(classify_events_batch)

    def test_import_sources(self):
        from services.ingestion.sources.gdelt import fetch_gdelt_events
        from services.ingestion.sources.fred import fetch_fred_events
        from services.ingestion.sources.rss_feeds import fetch_rss_events
        from services.ingestion.sources.newsdata import fetch_newsdata_events
        from services.ingestion.sources.twelve_data import fetch_twelve_data_events
        from services.ingestion.sources.propublica import fetch_propublica_events
        from services.ingestion.sources.acled import fetch_acled_events
        from services.ingestion.sources.polymarket import fetch_polymarket_events
        from services.ingestion.sources.cftc import fetch_cftc_events
        assert callable(fetch_gdelt_events)


# ============================================
# VERIFICATION SERVICE
# ============================================

class TestVerificationImports:
    def test_import_scoring(self):
        from services.verification.scoring import (
            compute_updated_integrity,
            apply_sponsored_penalty,
            determine_verification_status,
        )
        assert callable(compute_updated_integrity)

    def test_import_sponsored_detector(self):
        from services.verification.sponsored_detector import (
            detect_sponsored_content,
            should_flag_sponsored,
        )
        assert callable(detect_sponsored_content)

    def test_import_modalities(self):
        from services.verification.modalities import (
            MODALITY_REGISTRY,
            get_modalities_for_domain,
        )
        assert isinstance(MODALITY_REGISTRY, dict)
        assert callable(get_modalities_for_domain)


# ============================================
# AGENTS SERVICE
# ============================================

class TestAgentsImports:
    def test_import_specialists(self):
        from services.agents.specialists.economist import EconomistAgent
        from services.agents.specialists.geopolitical import GeopoliticalAgent
        from services.agents.specialists.investor import InvestorAgent
        from services.agents.specialists.political import PoliticalAgent
        from services.agents.specialists.sentiment import SentimentAgent
        from services.agents.specialists.master import MasterAgent
        agents = [
            EconomistAgent, GeopoliticalAgent, InvestorAgent,
            PoliticalAgent, SentimentAgent, MasterAgent,
        ]
        assert len(agents) == 6

    def test_import_context_builder(self):
        from services.agents.context_builder import build_agent_context
        assert callable(build_agent_context)

    def test_import_output_parser(self):
        from services.agents.output_parser import parse_agent_output
        assert callable(parse_agent_output)

    def test_import_devils_advocate(self):
        from services.agents.devils_advocate import (
            run_devil_advocate, compute_devil_impact, format_debate_rounds,
        )
        assert callable(run_devil_advocate)


# ============================================
# FEEDBACK SERVICE
# ============================================

class TestFeedbackImports:
    def test_import_scorer(self):
        from services.feedback.scorer import run_scoring_cycle
        assert callable(run_scoring_cycle)

    def test_import_calibration(self):
        from services.feedback.calibration import rebuild_calibration_curves
        assert callable(rebuild_calibration_curves)

    def test_import_bias_detector(self):
        from services.feedback.bias_detector import run_bias_detection
        assert callable(run_bias_detection)

    def test_import_prompt_updater(self):
        from services.feedback.prompt_updater import update_agent_prompts
        assert callable(update_agent_prompts)

    def test_import_sub_prediction_health(self):
        from services.feedback.sub_prediction_health import check_sub_prediction_health
        assert callable(check_sub_prediction_health)

    def test_import_cross_agent_scanner(self):
        from services.feedback.cross_agent_scanner import scan_cross_agent_correlations
        assert callable(scan_cross_agent_correlations)

    def test_import_red_team(self):
        from services.feedback.red_team import run_monthly_red_team
        assert callable(run_monthly_red_team)


# ============================================
# SIGNALS SERVICE
# ============================================

class TestSignalsImports:
    def test_import_anomaly_detector(self):
        from services.signals.anomaly_detector import detect_anomalies
        assert callable(detect_anomalies)

    def test_import_orphan_scanner(self):
        from services.signals.orphan_scanner import scan_orphan_events
        assert callable(scan_orphan_events)

    def test_import_premortem(self):
        from services.signals.premortem import run_premortem
        assert callable(run_premortem)
