// TypeScript types mirroring shared/schemas.py Pydantic models

// ============================================
// ENUMS
// ============================================

export type PredictionStatus =
  | 'ACTIVE'
  | 'RESOLVED_TRUE'
  | 'RESOLVED_FALSE'
  | 'SUPERSEDED'
  | 'EXPIRED';

export type TimeConditionType = 'point' | 'range' | 'ongoing';

export type Severity = 'routine' | 'notable' | 'significant' | 'critical';

export type Domain = 'geopolitical' | 'economic' | 'market' | 'political' | 'sentiment';

export type AgentName =
  | 'geopolitical'
  | 'economist'
  | 'investor'
  | 'political'
  | 'sentiment'
  | 'master';

export type SignalStrength = 'LOW' | 'MEDIUM' | 'HIGH';

export type Urgency = 'LOW' | 'MEDIUM' | 'HIGH' | 'PREP_NOW';

export type VerificationStatus =
  | 'UNVERIFIED'
  | 'CORROBORATED'
  | 'CONTRADICTED'
  | 'LOW_CONFIDENCE';

// ============================================
// PREDICTION
// ============================================

export interface PredictionResponse {
  id: string;
  agent: string;
  claim: string;
  time_condition_type: string;
  time_condition_date: string | null;
  time_condition_start: string | null;
  time_condition_end: string | null;
  resolution_criteria: string;
  status: PredictionStatus;
  current_confidence: number;
  parent_id: string | null;
  created_at: string | null;
  resolved_date: string | null;
  resolved_outcome: boolean | null;
  brier_score: number | null;
  post_mortem: Record<string, unknown> | null;
}

export interface PredictionDetail extends PredictionResponse {
  confidence_trail: ConfidenceTrailResponse[];
  notes: NoteResponse[];
  debates: DebateResponse[];
  sub_predictions: PredictionResponse[];
}

// ============================================
// CONFIDENCE TRAIL
// ============================================

export interface ConfidenceTrailResponse {
  id: number;
  prediction_id: string;
  date: string | null;
  value: number;
  trigger: string;
  reasoning: string;
  event_ref: string | null;
}

// ============================================
// NOTE
// ============================================

export interface NoteResponse {
  id: number;
  prediction_id: string;
  date: string | null;
  type: string;
  text: string;
}

export interface NoteCreate {
  type: string;
  text: string;
}

// ============================================
// EVENT
// ============================================

export interface EventResponse {
  id: string;
  source: string;
  source_reliability: number;
  timestamp: string;
  domain: string;
  event_type: string | null;
  severity: string | null;
  entities: unknown[] | null;
  claims: unknown[] | null;
  integrity_score: number | null;
  created_at: string | null;
}

// ============================================
// AGENT
// ============================================

export interface AgentMetrics {
  agent: string;
  total_predictions: number;
  active_predictions: number;
  resolved_predictions: number;
  accuracy: number | null;
  brier_avg: number | null;
  calibration_error: number | null;
  known_biases: string[];
  devil_impact_avg: number | null;
}

export interface AgentListResponse {
  agents: AgentMetrics[];
}

// ============================================
// DEBATE
// ============================================

export interface DebateRound {
  advocate?: { text: string };
  devil?: { text: string };
  resolution?: { text: string };
  [key: string]: unknown;
}

export interface DebateResponse {
  id: string;
  prediction_id: string | null;
  agent: string;
  trigger_reason: string;
  rounds: DebateRound[] | null;
  devil_impact: number | null;
  created_at: string | null;
}

// ============================================
// DASHBOARD
// ============================================

export interface DashboardMetrics {
  system_brier_score: number | null;
  overall_accuracy: number | null;
  active_predictions: number;
  total_predictions: number;
  calibration_error: number | null;
  agents: AgentMetrics[];
  recent_activity: ActivityItem[];
}

export interface ActivityItem {
  type: string;
  prediction_id: string;
  value?: number;
  trigger?: string;
  note_type?: string;
  text?: string;
  agent?: string;
  trigger_reason?: string;
  timestamp: string | null;
}

export interface CalibrationBucket {
  bucket: string;
  predicted_avg: number;
  actual_avg: number;
  count: number;
}

export interface CalibrationCurveResponse {
  overall: CalibrationBucket[];
  by_agent: Record<string, CalibrationBucket[]>;
}

// ============================================
// WEAK SIGNAL
// ============================================

export interface WeakSignalResponse {
  id: number;
  signal: string;
  strength: string | null;
  status: string | null;
  attributed_to: string | null;
  detected_at: string | null;
}

// ============================================
// CLAIM / VERIFICATION
// ============================================

export interface ClaimVerificationResponse {
  id: string;
  claim_text: string;
  initial_source: string;
  initial_integrity: number;
  current_integrity: number;
  verification_status: string;
  corroboration_count: number;
  contradiction_count: number;
  independent_source_count: number;
  cross_modal_sources: unknown[] | null;
  evidence_chain: unknown[] | null;
  sponsored_flag: boolean;
  created_at: string | null;
  verified_at: string | null;
}

// ============================================
// DECISION
// ============================================

export interface DecisionResponse {
  id: number;
  prediction_id: string | null;
  action: string;
  trigger_condition: string;
  urgency: string | null;
  domain: string | null;
  inert_threshold: number | null;
  prediction: PredictionResponse | null;
}

// ============================================
// LIVING QUESTIONS
// ============================================

export type QuestionStatus = 'analyzing' | 'active' | 'paused' | 'resolved' | 'archived';
export type TrafficLight = 'green' | 'yellow' | 'red';
export type ThesisVerdict = 'BULLISH' | 'BEARISH' | 'NEUTRAL' | 'MIXED';

export interface QuestionAssumptionResponse {
  id: string;
  assumption_text: string;
  assumption_number: number;
  status: TrafficLight;
  confidence: number | null;
  green_to_yellow_trigger: string | null;
  yellow_to_red_trigger: string | null;
  supporting_evidence_count: number;
  challenging_evidence_count: number;
  current_assessment: string | null;
  keywords: string[] | null;
}

export interface QuestionEvidenceResponse {
  id: number;
  assumption_id: string | null;
  evidence_type: string;
  evidence_summary: string;
  impact_level: string | null;
  source: string | null;
  triggered_status_change: boolean;
  detected_at: string | null;
  agent_that_flagged: string | null;
}

export interface QuestionSummaryResponse {
  id: string;
  question: string;
  category: string | null;
  thesis_verdict: ThesisVerdict | null;
  overall_confidence: number | null;
  overall_status: TrafficLight | null;
  thesis_summary: string | null;
  status: QuestionStatus;
  created_at: string | null;
  last_analyzed_at: string | null;
  next_review_date: string | null;
  assumption_count: number;
  evidence_count: number;
  tags: string[] | null;
}

export interface QuestionDetailResponse extends QuestionSummaryResponse {
  recommendation: string | null;
  agent_perspectives: Record<string, string> | null;
  assumptions: QuestionAssumptionResponse[];
  recent_evidence: QuestionEvidenceResponse[];
}

export interface QuestionCreateRequest {
  question: string;
  context?: string;
  category?: string;
  priority?: string;
  tags?: string[];
}

// ============================================
// GENERIC
// ============================================

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ============================================
// ACCURACY HISTORY
// ============================================

export interface AccuracyTimelinePoint {
  date: string;
  cumulative_accuracy: number | null;
  cumulative_brier: number | null;
  resolved_count: number;
  correct_count: number;
  rolling_7d_accuracy: number | null;
  rolling_7d_brier: number | null;
}

export interface AccuracyHistoryResponse {
  timeline: AccuracyTimelinePoint[];
  by_agent: Record<string, AccuracyTimelinePoint[]>;
  by_domain: Record<string, AccuracyTimelinePoint[]>;
  summary: {
    total_resolved: number;
    total_correct: number;
    overall_accuracy: number | null;
    overall_brier: number | null;
    best_agent: string | null;
    best_agent_accuracy: number | null;
    worst_agent: string | null;
    worst_agent_accuracy: number | null;
  };
}
