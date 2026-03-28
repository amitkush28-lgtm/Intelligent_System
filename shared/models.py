"""
SQLAlchemy ORM models implementing the complete database schema (Part 5).
Single source of truth — all services import these models.
"""

from sqlalchemy import (
    Column, String, Text, Float, Integer, Boolean, Date, DateTime,
    ForeignKey, Index, JSON, func
)
from sqlalchemy.orm import relationship
from shared.database import Base


# ============================================
# CORE TABLES
# ============================================

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(String, primary_key=True)  # "PRED-2026-0047"
    agent = Column(String, nullable=False)  # geopolitical|economist|investor|political|sentiment|master
    claim = Column(Text, nullable=False)  # precise, falsifiable statement
    time_condition_type = Column(String, nullable=False)  # point|range|ongoing
    time_condition_date = Column(Date, nullable=True)  # for point type
    time_condition_start = Column(Date, nullable=True)  # for range type
    time_condition_end = Column(Date, nullable=True)  # for range type (= deadline)
    resolution_criteria = Column(Text, nullable=False)
    status = Column(String, nullable=False, default="ACTIVE")  # ACTIVE|RESOLVED_TRUE|RESOLVED_FALSE|SUPERSEDED|EXPIRED
    current_confidence = Column(Float, nullable=False)  # 0.0 to 1.0
    parent_id = Column(String, ForeignKey("predictions.id"), nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    resolved_date = Column(Date, nullable=True)
    resolved_outcome = Column(Boolean, nullable=True)
    brier_score = Column(Float, nullable=True)
    post_mortem = Column(JSON, nullable=True)  # {what_went_wrong, correct_signals, missed_signals}

    # Relationships
    parent = relationship("Prediction", remote_side="Prediction.id", backref="sub_predictions")
    confidence_trail = relationship("ConfidenceTrail", back_populates="prediction", cascade="all, delete-orphan")
    notes = relationship("Note", back_populates="prediction", cascade="all, delete-orphan")
    debates = relationship("Debate", back_populates="prediction", cascade="all, delete-orphan")
    decision_mappings = relationship("DecisionMapping", back_populates="prediction", cascade="all, delete-orphan")


class ConfidenceTrail(Base):
    __tablename__ = "confidence_trail"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prediction_id = Column(String, ForeignKey("predictions.id", ondelete="CASCADE"), nullable=False)
    date = Column(DateTime, server_default=func.now())
    value = Column(Float, nullable=False)  # 0.0 to 1.0
    trigger = Column(Text, nullable=False)  # what event caused this update
    reasoning = Column(Text, nullable=False)  # WHY the confidence changed
    event_ref = Column(String, nullable=True)  # link to triggering event
    created_at = Column(DateTime, server_default=func.now())

    prediction = relationship("Prediction", back_populates="confidence_trail")


class Note(Base):
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prediction_id = Column(String, ForeignKey("predictions.id", ondelete="CASCADE"), nullable=False)
    date = Column(DateTime, server_default=func.now())
    type = Column(String, nullable=False)  # observation|key_signal|counter_signal|analysis
    text = Column(Text, nullable=False)

    prediction = relationship("Prediction", back_populates="notes")


class Event(Base):
    __tablename__ = "events"

    id = Column(String, primary_key=True)
    source = Column(String, nullable=False)
    source_reliability = Column(Float, nullable=False)
    timestamp = Column(DateTime, nullable=False)
    domain = Column(String, nullable=False)  # geopolitical|economic|market|political|sentiment
    event_type = Column(String, nullable=True)
    severity = Column(String, nullable=True)  # routine|notable|significant|critical
    entities = Column(JSON, nullable=True)  # [{name, type, role}]
    claims = Column(JSON, nullable=True)  # extracted factual claims
    raw_text = Column(Text, nullable=True)
    integrity_score = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ============================================
# KNOWLEDGE GRAPH
# ============================================

class Actor(Base):
    __tablename__ = "actors"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    type = Column(String, nullable=True)  # person|organization|nation|alliance
    attributes = Column(JSON, nullable=True)
    objective_function = Column(Text, nullable=True)  # from deep motivational analysis
    deep_motivations = Column(JSON, nullable=True)  # which of the 6 forces apply
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class Relationship(Base):
    __tablename__ = "relationships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    actor_from = Column(String, ForeignKey("actors.id"), nullable=False)
    actor_to = Column(String, ForeignKey("actors.id"), nullable=False)
    relationship_type = Column(String, nullable=True)
    weight = Column(Float, nullable=True)
    evidence = Column(JSON, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    actor_from_rel = relationship("Actor", foreign_keys=[actor_from])
    actor_to_rel = relationship("Actor", foreign_keys=[actor_to])


# ============================================
# VERIFICATION ENGINE
# ============================================

class Claim(Base):
    __tablename__ = "claims"

    id = Column(String, primary_key=True)
    event_id = Column(String, ForeignKey("events.id"), nullable=True)
    claim_text = Column(Text, nullable=False)
    initial_source = Column(String, nullable=False)
    initial_integrity = Column(Float, nullable=False)
    current_integrity = Column(Float, nullable=False)
    verification_status = Column(String, default="UNVERIFIED")  # UNVERIFIED|CORROBORATED|CONTRADICTED|LOW_CONFIDENCE
    corroboration_count = Column(Integer, default=0)
    contradiction_count = Column(Integer, default=0)
    independent_source_count = Column(Integer, default=1)
    cross_modal_sources = Column(JSON, nullable=True)  # [{modality, source, finding, timestamp}]
    provenance_trace = Column(JSON, nullable=True)
    evidence_chain = Column(JSON, nullable=True)  # [{source, integrity, corroborates: bool, detail}]
    sponsored_flag = Column(Boolean, default=False)
    sponsored_reasoning = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    verified_at = Column(DateTime, nullable=True)

    event = relationship("Event")


class SourceReliability(Base):
    __tablename__ = "source_reliability"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_name = Column(String, nullable=False)
    domain = Column(String, nullable=True)  # geopolitical|economic|market|political|sentiment
    total_claims = Column(Integer, default=0)
    verified_accurate = Column(Integer, default=0)
    verified_inaccurate = Column(Integer, default=0)
    reliability_score = Column(Float, default=0.50)
    last_updated = Column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("uq_source_domain", "source_name", "domain", unique=True),
    )


# ============================================
# CALIBRATION & FEEDBACK
# ============================================

class CalibrationScore(Base):
    __tablename__ = "calibration_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent = Column(String, nullable=False)
    domain = Column(String, nullable=True)
    confidence_bucket = Column(String, nullable=True)  # "30-40%", "50-60%", etc.
    predicted_avg = Column(Float, nullable=True)
    actual_avg = Column(Float, nullable=True)
    count = Column(Integer, nullable=True)
    brier_avg = Column(Float, nullable=True)
    bias_direction = Column(String, nullable=True)  # overconfident|underconfident|calibrated
    calculated_at = Column(DateTime, server_default=func.now())


class AgentPrompt(Base):
    __tablename__ = "agent_prompts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    agent = Column(String, nullable=False)
    version = Column(Integer, nullable=False)
    prompt_text = Column(Text, nullable=False)
    calibration_notes = Column(Text, nullable=True)
    reasoning_guidance = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    active = Column(Boolean, default=True)


class Debate(Base):
    __tablename__ = "debates"

    id = Column(String, primary_key=True)
    prediction_id = Column(String, ForeignKey("predictions.id"), nullable=True)
    agent = Column(String, nullable=False)
    trigger_reason = Column(Text, nullable=False)
    rounds = Column(JSON, nullable=True)  # [{advocate: {text}, devil: {text}, resolution}]
    devil_impact = Column(Float, nullable=True)
    created_at = Column(DateTime, server_default=func.now())

    prediction = relationship("Prediction", back_populates="debates")


# ============================================
# BASE RATES & REFERENCE
# ============================================

class BaseRateClass(Base):
    __tablename__ = "base_rate_classes"

    id = Column(String, primary_key=True)
    class_name = Column(String, nullable=False)
    cases = Column(Integer, nullable=False)
    timespan = Column(String, nullable=True)
    base_rate = Column(Float, nullable=False)
    description = Column(Text, nullable=True)
    examples = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# ============================================
# ADVANCED LAYERS
# ============================================

class WeakSignal(Base):
    __tablename__ = "weak_signals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    signal = Column(Text, nullable=False)
    strength = Column(String, nullable=True)  # LOW|MEDIUM|HIGH
    status = Column(String, nullable=True)  # unattributed|investigating|attributed
    attributed_to = Column(String, nullable=True)
    detected_at = Column(DateTime, server_default=func.now())


class DecisionMapping(Base):
    __tablename__ = "decision_mappings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    prediction_id = Column(String, ForeignKey("predictions.id"), nullable=True)
    action = Column(Text, nullable=False)
    trigger_condition = Column(Text, nullable=False)
    urgency = Column(String, nullable=True)  # LOW|MEDIUM|HIGH|PREP_NOW
    domain = Column(String, nullable=True)  # portfolio|business|risk|strategy
    inert_threshold = Column(Float, nullable=True)

    prediction = relationship("Prediction", back_populates="decision_mappings")


# ============================================
# INDEXES (defined via __table_args__ or explicit Index objects)
# ============================================

Index("idx_predictions_status", Prediction.status)
Index("idx_predictions_agent", Prediction.agent)
Index("idx_predictions_parent", Prediction.parent_id)
Index("idx_confidence_trail_pred", ConfidenceTrail.prediction_id)
Index("idx_notes_pred", Note.prediction_id)
Index("idx_events_domain", Event.domain)
Index("idx_events_timestamp", Event.timestamp)
Index("idx_claims_status", Claim.verification_status)
Index("idx_claims_integrity", Claim.current_integrity)
Index("idx_calibration_agent", CalibrationScore.agent)


# ============================================
# LIVING QUESTIONS (Thesis Tracker)
# ============================================

class LivingQuestion(Base):
    __tablename__ = "living_questions"

    id = Column(String, primary_key=True)  # "LQ-2026-0001"

    # User input
    question = Column(Text, nullable=False)
    context = Column(Text, nullable=True)
    category = Column(String, nullable=True)

    # System analysis
    thesis_summary = Column(Text, nullable=True)
    thesis_verdict = Column(String, nullable=True)
    overall_confidence = Column(Integer, nullable=True)
    overall_status = Column(String, default="green")
    recommendation = Column(Text, nullable=True)

    # Full analysis
    initial_analysis = Column(JSON, nullable=True)
    latest_analysis = Column(JSON, nullable=True)
    agent_perspectives = Column(JSON, nullable=True)

    # Lifecycle
    status = Column(String, default="active")
    created_at = Column(DateTime, server_default=func.now())
    last_analyzed_at = Column(DateTime, nullable=True)
    last_evidence_at = Column(DateTime, nullable=True)
    next_review_date = Column(Date, nullable=True)
    resolution_note = Column(Text, nullable=True)

    # Metadata
    tags = Column(JSON, nullable=True)
    priority = Column(String, default="normal")

    # Relationships
    assumptions = relationship("QuestionAssumption", back_populates="question", cascade="all, delete-orphan")
    evidence = relationship("QuestionEvidence", back_populates="question", cascade="all, delete-orphan")
    reanalyses = relationship("QuestionReanalysis", back_populates="question", cascade="all, delete-orphan")


class QuestionAssumption(Base):
    __tablename__ = "question_assumptions"

    id = Column(String, primary_key=True)
    question_id = Column(String, ForeignKey("living_questions.id", ondelete="CASCADE"), nullable=False)

    assumption_text = Column(Text, nullable=False)
    assumption_number = Column(Integer, nullable=False)

    status = Column(String, default="green")
    confidence = Column(Integer, nullable=True)

    green_to_yellow_trigger = Column(Text, nullable=True)
    yellow_to_red_trigger = Column(Text, nullable=True)
    red_conditions = Column(Text, nullable=True)

    supporting_evidence_count = Column(Integer, default=0)
    challenging_evidence_count = Column(Integer, default=0)

    current_assessment = Column(Text, nullable=True)
    last_status_change_at = Column(DateTime, nullable=True)
    last_status_change_reason = Column(Text, nullable=True)

    keywords = Column(JSON, nullable=True)
    relevant_agents = Column(JSON, nullable=True)

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    question = relationship("LivingQuestion", back_populates="assumptions")
    evidence_entries = relationship("QuestionEvidence", back_populates="assumption", cascade="all, delete-orphan")


class QuestionEvidence(Base):
    __tablename__ = "question_evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(String, ForeignKey("living_questions.id", ondelete="CASCADE"), nullable=False)
    assumption_id = Column(String, ForeignKey("question_assumptions.id", ondelete="CASCADE"), nullable=True)

    event_id = Column(String, ForeignKey("events.id"), nullable=True)
    evidence_type = Column(String, nullable=False)
    evidence_summary = Column(Text, nullable=False)
    evidence_detail = Column(Text, nullable=True)
    source = Column(String, nullable=True)
    source_url = Column(Text, nullable=True)

    impact_level = Column(String, nullable=True)
    triggered_status_change = Column(Boolean, default=False)
    previous_status = Column(String, nullable=True)
    new_status = Column(String, nullable=True)

    detected_at = Column(DateTime, server_default=func.now())
    detected_by = Column(String, nullable=True)
    agent_that_flagged = Column(String, nullable=True)

    question = relationship("LivingQuestion", back_populates="evidence")
    assumption = relationship("QuestionAssumption", back_populates="evidence_entries")
    event = relationship("Event")


class QuestionReanalysis(Base):
    __tablename__ = "question_reanalyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(String, ForeignKey("living_questions.id", ondelete="CASCADE"), nullable=False)

    trigger_type = Column(String, nullable=True)
    trigger_description = Column(Text, nullable=True)

    previous_verdict = Column(String, nullable=True)
    new_verdict = Column(String, nullable=True)
    previous_confidence = Column(Integer, nullable=True)
    new_confidence = Column(Integer, nullable=True)
    previous_status = Column(String, nullable=True)
    new_status = Column(String, nullable=True)

    full_analysis = Column(JSON, nullable=True)
    changes_summary = Column(Text, nullable=True)
    assumption_updates = Column(JSON, nullable=True)

    included_in_newsletter = Column(Boolean, default=False)
    newsletter_summary = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    question = relationship("LivingQuestion", back_populates="reanalyses")


# Living Questions indexes
Index("idx_living_questions_status", LivingQuestion.status)
Index("idx_question_assumptions_question", QuestionAssumption.question_id)
Index("idx_question_evidence_question", QuestionEvidence.question_id)
Index("idx_question_evidence_assumption", QuestionEvidence.assumption_id)
Index("idx_question_reanalyses_question", QuestionReanalysis.question_id)
