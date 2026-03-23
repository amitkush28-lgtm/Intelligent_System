"""
Pydantic schemas for API request/response models.
Used by the API server and any service that produces/consumes structured data.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Any
from datetime import date, datetime
from enum import Enum


# ============================================
# ENUMS
# ============================================

class PredictionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED_TRUE = "RESOLVED_TRUE"
    RESOLVED_FALSE = "RESOLVED_FALSE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class TimeConditionType(str, Enum):
    POINT = "point"
    RANGE = "range"
    ONGOING = "ongoing"


class Severity(str, Enum):
    ROUTINE = "routine"
    NOTABLE = "notable"
    SIGNIFICANT = "significant"
    CRITICAL = "critical"


class Domain(str, Enum):
    GEOPOLITICAL = "geopolitical"
    ECONOMIC = "economic"
    MARKET = "market"
    POLITICAL = "political"
    SENTIMENT = "sentiment"


class AgentName(str, Enum):
    GEOPOLITICAL = "geopolitical"
    ECONOMIST = "economist"
    INVESTOR = "investor"
    POLITICAL = "political"
    SENTIMENT = "sentiment"
    MASTER = "master"


class SignalStrength(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Urgency(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    PREP_NOW = "PREP_NOW"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    CORROBORATED = "CORROBORATED"
    CONTRADICTED = "CONTRADICTED"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"


# ============================================
# PREDICTION SCHEMAS
# ============================================

class PredictionCreate(BaseModel):
    agent: AgentName
    claim: str
    time_condition_type: TimeConditionType
    time_condition_date: Optional[date] = None
    time_condition_start: Optional[date] = None
    time_condition_end: Optional[date] = None
    resolution_criteria: str
    current_confidence: float = Field(ge=0.0, le=1.0)
    parent_id: Optional[str] = None


class PredictionUpdate(BaseModel):
    status: Optional[PredictionStatus] = None
    current_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    resolved_date: Optional[date] = None
    resolved_outcome: Optional[bool] = None
    post_mortem: Optional[dict] = None


class PredictionResponse(BaseModel):
    id: str
    agent: str
    claim: str
    time_condition_type: str
    time_condition_date: Optional[date] = None
    time_condition_start: Optional[date] = None
    time_condition_end: Optional[date] = None
    resolution_criteria: str
    status: str
    current_confidence: float
    parent_id: Optional[str] = None
    created_at: Optional[datetime] = None
    resolved_date: Optional[date] = None
    resolved_outcome: Optional[bool] = None
    brier_score: Optional[float] = None
    post_mortem: Optional[dict] = None

    model_config = {"from_attributes": True}


class PredictionDetail(PredictionResponse):
    confidence_trail: List["ConfidenceTrailResponse"] = []
    notes: List["NoteResponse"] = []
    debates: List["DebateResponse"] = []
    sub_predictions: List[PredictionResponse] = []


# ============================================
# CONFIDENCE TRAIL SCHEMAS
# ============================================

class ConfidenceTrailCreate(BaseModel):
    prediction_id: str
    value: float = Field(ge=0.0, le=1.0)
    trigger: str
    reasoning: str
    event_ref: Optional[str] = None


class ConfidenceTrailResponse(BaseModel):
    id: int
    prediction_id: str
    date: Optional[datetime] = None
    value: float
    trigger: str
    reasoning: str
    event_ref: Optional[str] = None

    model_config = {"from_attributes": True}


# ============================================
# NOTE SCHEMAS
# ============================================

class NoteCreate(BaseModel):
    type: str  # observation|key_signal|counter_signal|analysis
    text: str


class NoteResponse(BaseModel):
    id: int
    prediction_id: str
    date: Optional[datetime] = None
    type: str
    text: str

    model_config = {"from_attributes": True}


# ============================================
# EVENT SCHEMAS
# ============================================

class EventResponse(BaseModel):
    id: str
    source: str
    source_reliability: float
    timestamp: datetime
    domain: str
    event_type: Optional[str] = None
    severity: Optional[str] = None
    entities: Optional[list] = None
    claims: Optional[list] = None
    integrity_score: Optional[float] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ============================================
# AGENT SCHEMAS
# ============================================

class AgentMetrics(BaseModel):
    agent: str
    total_predictions: int = 0
    active_predictions: int = 0
    resolved_predictions: int = 0
    accuracy: Optional[float] = None  # % resolved correctly
    brier_avg: Optional[float] = None
    calibration_error: Optional[float] = None
    known_biases: List[str] = []
    devil_impact_avg: Optional[float] = None


class AgentListResponse(BaseModel):
    agents: List[AgentMetrics]


# ============================================
# DEBATE SCHEMAS
# ============================================

class DebateResponse(BaseModel):
    id: str
    prediction_id: Optional[str] = None
    agent: str
    trigger_reason: str
    rounds: Optional[list] = None
    devil_impact: Optional[float] = None
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ============================================
# DASHBOARD SCHEMAS
# ============================================

class DashboardMetrics(BaseModel):
    system_brier_score: Optional[float] = None
    overall_accuracy: Optional[float] = None
    active_predictions: int = 0
    total_predictions: int = 0
    calibration_error: Optional[float] = None
    agents: List[AgentMetrics] = []
    recent_activity: List[dict] = []


class CalibrationBucket(BaseModel):
    bucket: str  # "30-40%"
    predicted_avg: float
    actual_avg: float
    count: int


class CalibrationCurveResponse(BaseModel):
    overall: List[CalibrationBucket] = []
    by_agent: dict = {}  # agent_name -> List[CalibrationBucket]


# ============================================
# WEAK SIGNAL SCHEMAS
# ============================================

class WeakSignalResponse(BaseModel):
    id: int
    signal: str
    strength: Optional[str] = None
    status: Optional[str] = None
    attributed_to: Optional[str] = None
    detected_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ============================================
# CLAIM / VERIFICATION SCHEMAS
# ============================================

class ClaimVerificationResponse(BaseModel):
    id: str
    claim_text: str
    initial_source: str
    initial_integrity: float
    current_integrity: float
    verification_status: str
    corroboration_count: int
    contradiction_count: int
    independent_source_count: int
    cross_modal_sources: Optional[list] = None
    evidence_chain: Optional[list] = None
    sponsored_flag: bool
    created_at: Optional[datetime] = None
    verified_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ============================================
# DECISION SCHEMAS
# ============================================

class DecisionResponse(BaseModel):
    id: int
    prediction_id: Optional[str] = None
    action: str
    trigger_condition: str
    urgency: Optional[str] = None
    domain: Optional[str] = None
    inert_threshold: Optional[float] = None
    prediction: Optional[PredictionResponse] = None

    model_config = {"from_attributes": True}


# ============================================
# GENERIC
# ============================================

class PaginatedResponse(BaseModel):
    items: List[Any]
    total: int
    page: int
    page_size: int


# Rebuild forward refs
PredictionDetail.model_rebuild()
