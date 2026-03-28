"""
Living Questions Models — APPEND these to shared/models.py

These models support the Living Questions / Thesis Tracker feature.
Add them after the existing model definitions in shared/models.py.
"""

# ============================================
# LIVING QUESTIONS (Thesis Tracker)
# ============================================
# Add these imports to the top of models.py if not already present:
# from sqlalchemy import Column, String, Text, Float, Integer, Boolean, Date, DateTime, ForeignKey, Index, JSON, func
# from sqlalchemy.orm import relationship
# from shared.database import Base


class LivingQuestion(Base):
    __tablename__ = "living_questions"

    id = Column(String, primary_key=True)  # "LQ-2026-0001"

    # User input
    question = Column(Text, nullable=False)           # "Should I invest in data center stocks?"
    context = Column(Text, nullable=True)              # Optional user context about their situation
    category = Column(String, nullable=True)           # INVESTMENT | SAFETY | BUSINESS | GEOPOLITICAL | PERSONAL

    # System analysis
    thesis_summary = Column(Text, nullable=True)       # 2-3 sentence summary of the system's position
    thesis_verdict = Column(String, nullable=True)     # BULLISH | BEARISH | NEUTRAL | MIXED | INSUFFICIENT_DATA
    overall_confidence = Column(Integer, nullable=True) # 0-100
    overall_status = Column(String, default="green")   # green | yellow | red
    recommendation = Column(Text, nullable=True)       # Specific actionable recommendation

    # Full analysis
    initial_analysis = Column(JSON, nullable=True)     # Complete first analysis from all agents
    latest_analysis = Column(JSON, nullable=True)      # Most recent re-analysis
    agent_perspectives = Column(JSON, nullable=True)   # Each agent's individual take

    # Lifecycle
    status = Column(String, default="active")          # active | paused | resolved | archived
    created_at = Column(DateTime, server_default=func.now())
    last_analyzed_at = Column(DateTime, nullable=True)
    last_evidence_at = Column(DateTime, nullable=True)
    next_review_date = Column(Date, nullable=True)
    resolution_note = Column(Text, nullable=True)

    # Metadata
    tags = Column(JSON, nullable=True)                 # ['ai', 'technology', 'investment']
    priority = Column(String, default="normal")        # high | normal | low

    # Relationships
    assumptions = relationship("QuestionAssumption", back_populates="question", cascade="all, delete-orphan")
    evidence = relationship("QuestionEvidence", back_populates="question", cascade="all, delete-orphan")
    reanalyses = relationship("QuestionReanalysis", back_populates="question", cascade="all, delete-orphan")


class QuestionAssumption(Base):
    __tablename__ = "question_assumptions"

    id = Column(String, primary_key=True)  # "LQ-2026-0001-A1"
    question_id = Column(String, ForeignKey("living_questions.id", ondelete="CASCADE"), nullable=False)

    # The assumption
    assumption_text = Column(Text, nullable=False)     # "AI requires massive compute infrastructure"
    assumption_number = Column(Integer, nullable=False) # 1, 2, 3...

    # Status tracking
    status = Column(String, default="green")           # green | yellow | red
    confidence = Column(Integer, nullable=True)        # 0-100

    # Tripwires
    green_to_yellow_trigger = Column(Text, nullable=True)
    yellow_to_red_trigger = Column(Text, nullable=True)
    red_conditions = Column(Text, nullable=True)

    # Evidence tracking
    supporting_evidence_count = Column(Integer, default=0)
    challenging_evidence_count = Column(Integer, default=0)

    # Analysis
    current_assessment = Column(Text, nullable=True)
    last_status_change_at = Column(DateTime, nullable=True)
    last_status_change_reason = Column(Text, nullable=True)

    # Monitoring keywords for automated event matching
    keywords = Column(JSON, nullable=True)             # ["AI compute", "data center", "GPU demand"]
    relevant_agents = Column(JSON, nullable=True)      # ["economist", "investor", "wildcard"]

    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Relationships
    question = relationship("LivingQuestion", back_populates="assumptions")
    evidence_entries = relationship("QuestionEvidence", back_populates="assumption", cascade="all, delete-orphan")


class QuestionEvidence(Base):
    __tablename__ = "question_evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(String, ForeignKey("living_questions.id", ondelete="CASCADE"), nullable=False)
    assumption_id = Column(String, ForeignKey("question_assumptions.id", ondelete="CASCADE"), nullable=True)

    # The evidence
    event_id = Column(String, ForeignKey("events.id"), nullable=True)
    evidence_type = Column(String, nullable=False)     # SUPPORTS | CHALLENGES | NEUTRAL
    evidence_summary = Column(Text, nullable=False)
    evidence_detail = Column(Text, nullable=True)
    source = Column(String, nullable=True)
    source_url = Column(Text, nullable=True)

    # Impact assessment
    impact_level = Column(String, nullable=True)       # HIGH | MEDIUM | LOW
    triggered_status_change = Column(Boolean, default=False)
    previous_status = Column(String, nullable=True)
    new_status = Column(String, nullable=True)

    # Metadata
    detected_at = Column(DateTime, server_default=func.now())
    detected_by = Column(String, nullable=True)        # 'pipeline' | 'reanalysis' | 'manual'
    agent_that_flagged = Column(String, nullable=True)

    # Relationships
    question = relationship("LivingQuestion", back_populates="evidence")
    assumption = relationship("QuestionAssumption", back_populates="evidence_entries")
    event = relationship("Event")


class QuestionReanalysis(Base):
    __tablename__ = "question_reanalyses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question_id = Column(String, ForeignKey("living_questions.id", ondelete="CASCADE"), nullable=False)

    # Trigger
    trigger_type = Column(String, nullable=True)       # SCHEDULED | EVENT_DRIVEN | ASSUMPTION_CHANGE | MANUAL
    trigger_description = Column(Text, nullable=True)

    # Results
    previous_verdict = Column(String, nullable=True)
    new_verdict = Column(String, nullable=True)
    previous_confidence = Column(Integer, nullable=True)
    new_confidence = Column(Integer, nullable=True)
    previous_status = Column(String, nullable=True)
    new_status = Column(String, nullable=True)

    # Analysis
    full_analysis = Column(JSON, nullable=True)
    changes_summary = Column(Text, nullable=True)
    assumption_updates = Column(JSON, nullable=True)

    # Newsletter inclusion
    included_in_newsletter = Column(Boolean, default=False)
    newsletter_summary = Column(Text, nullable=True)

    created_at = Column(DateTime, server_default=func.now())

    # Relationships
    question = relationship("LivingQuestion", back_populates="reanalyses")


# Add these indexes at the bottom of models.py:
Index("idx_living_questions_status", LivingQuestion.status)
Index("idx_question_assumptions_question", QuestionAssumption.question_id)
Index("idx_question_evidence_question", QuestionEvidence.question_id)
Index("idx_question_evidence_assumption", QuestionEvidence.assumption_id)
Index("idx_question_reanalyses_question", QuestionReanalysis.question_id)
