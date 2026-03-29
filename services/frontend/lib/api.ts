import {
  DashboardMetrics,
  CalibrationCurveResponse,
  PaginatedResponse,
  PredictionResponse,
  PredictionDetail,
  ConfidenceTrailResponse,
  NoteResponse,
  NoteCreate,
  AgentListResponse,
  AgentMetrics,
  DebateResponse,
  WeakSignalResponse,
  ClaimVerificationResponse,
  EventResponse,
  DecisionResponse,
  QuestionSummaryResponse,
  QuestionDetailResponse,
  QuestionCreateRequest,
  QuestionEvidenceResponse,
  AccuracyHistoryResponse,
} from './types';

const API_URL =
  typeof window !== 'undefined'
    ? (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000')
    : (process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000');

const API_KEY = process.env.NEXT_PUBLIC_API_KEY || '';

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${API_URL}${path}`;
  const res = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-API-Key': API_KEY,
      ...(options?.headers || {}),
    },
  });

  if (!res.ok) {
    const errorBody = await res.text().catch(() => '');
    throw new Error(`API ${res.status}: ${errorBody || res.statusText}`);
  }

  return res.json();
}

// ============================================
// DASHBOARD
// ============================================

export async function getDashboardMetrics(): Promise<DashboardMetrics> {
  return apiFetch<DashboardMetrics>('/dashboard/metrics');
}

export async function getCalibrationCurve(): Promise<CalibrationCurveResponse> {
  return apiFetch<CalibrationCurveResponse>('/dashboard/calibration');
}

export async function getAccuracyHistory(days?: number): Promise<AccuracyHistoryResponse> {
  const sp = new URLSearchParams();
  if (days) sp.set('days', String(days));
  const qs = sp.toString();
  return apiFetch<AccuracyHistoryResponse>(`/dashboard/accuracy-history${qs ? `?${qs}` : ''}`);
}

// ============================================
// PREDICTIONS
// ============================================

export async function getPredictions(params?: {
  status?: string;
  agent?: string;
  domain?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedResponse<PredictionResponse>> {
  const sp = new URLSearchParams();
  if (params?.status) sp.set('status', params.status);
  if (params?.agent) sp.set('agent', params.agent);
  if (params?.domain) sp.set('domain', params.domain);
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  const qs = sp.toString();
  return apiFetch<PaginatedResponse<PredictionResponse>>(
    `/predictions${qs ? `?${qs}` : ''}`
  );
}

export async function getPrediction(id: string): Promise<PredictionDetail> {
  return apiFetch<PredictionDetail>(`/predictions/${encodeURIComponent(id)}`);
}

export async function getConfidenceTrail(
  predictionId: string
): Promise<ConfidenceTrailResponse[]> {
  return apiFetch<ConfidenceTrailResponse[]>(
    `/predictions/${encodeURIComponent(predictionId)}/trail`
  );
}

export async function addNote(
  predictionId: string,
  note: NoteCreate
): Promise<NoteResponse> {
  return apiFetch<NoteResponse>(
    `/predictions/${encodeURIComponent(predictionId)}/notes`,
    {
      method: 'POST',
      body: JSON.stringify(note),
    }
  );
}

// ============================================
// AGENTS
// ============================================

export async function getAgents(): Promise<AgentListResponse> {
  return apiFetch<AgentListResponse>('/agents');
}

export async function getAgentMetrics(agentId: string): Promise<AgentMetrics> {
  return apiFetch<AgentMetrics>(`/agents/${encodeURIComponent(agentId)}/metrics`);
}

// ============================================
// DEBATES
// ============================================

export async function getDebates(params?: {
  agent?: string;
  prediction_id?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedResponse<DebateResponse>> {
  const sp = new URLSearchParams();
  if (params?.agent) sp.set('agent', params.agent);
  if (params?.prediction_id) sp.set('prediction_id', params.prediction_id);
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  const qs = sp.toString();
  return apiFetch<PaginatedResponse<DebateResponse>>(
    `/debates${qs ? `?${qs}` : ''}`
  );
}

// ============================================
// SIGNALS
// ============================================

export async function getWeakSignals(params?: {
  strength?: string;
  status?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedResponse<WeakSignalResponse>> {
  const sp = new URLSearchParams();
  if (params?.strength) sp.set('strength', params.strength);
  if (params?.status) sp.set('status', params.status);
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  const qs = sp.toString();
  return apiFetch<PaginatedResponse<WeakSignalResponse>>(
    `/signals/weak${qs ? `?${qs}` : ''}`
  );
}

// ============================================
// CLAIMS
// ============================================

export async function getClaimVerification(
  claimId: string
): Promise<ClaimVerificationResponse> {
  return apiFetch<ClaimVerificationResponse>(
    `/claims/${encodeURIComponent(claimId)}/verification`
  );
}

// ============================================
// EVENTS
// ============================================

export async function getEvents(params?: {
  domain?: string;
  severity?: string;
  source?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedResponse<EventResponse>> {
  const sp = new URLSearchParams();
  if (params?.domain) sp.set('domain', params.domain);
  if (params?.severity) sp.set('severity', params.severity);
  if (params?.source) sp.set('source', params.source);
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  const qs = sp.toString();
  return apiFetch<PaginatedResponse<EventResponse>>(
    `/events${qs ? `?${qs}` : ''}`
  );
}

// ============================================
// DECISIONS
// ============================================

export async function getDecisions(params?: {
  urgency?: string;
  domain?: string;
  page?: number;
  page_size?: number;
}): Promise<PaginatedResponse<DecisionResponse>> {
  const sp = new URLSearchParams();
  if (params?.urgency) sp.set('urgency', params.urgency);
  if (params?.domain) sp.set('domain', params.domain);
  if (params?.page) sp.set('page', String(params.page));
  if (params?.page_size) sp.set('page_size', String(params.page_size));
  const qs = sp.toString();
  return apiFetch<PaginatedResponse<DecisionResponse>>(
    `/decisions${qs ? `?${qs}` : ''}`
  );
}

// ============================================
// LIVING QUESTIONS
// ============================================

export async function getQuestions(params?: {
  status?: string;
}): Promise<QuestionSummaryResponse[]> {
  const sp = new URLSearchParams();
  if (params?.status) sp.set('status', params.status);
  const qs = sp.toString();
  return apiFetch<QuestionSummaryResponse[]>(
    `/questions${qs ? `?${qs}` : ''}`
  );
}

export async function getQuestion(id: string): Promise<QuestionDetailResponse> {
  return apiFetch<QuestionDetailResponse>(`/questions/${encodeURIComponent(id)}`);
}

export async function createQuestion(body: QuestionCreateRequest): Promise<{ id: string; status: string; message: string }> {
  return apiFetch(`/questions`, {
    method: 'POST',
    body: JSON.stringify(body),
  });
}

export async function reanalyzeQuestion(id: string): Promise<{ status: string; message: string }> {
  return apiFetch(`/questions/${encodeURIComponent(id)}/reanalyze`, {
    method: 'POST',
  });
}

export async function updateQuestionStatus(
  id: string,
  status: string,
  resolution_note?: string,
): Promise<{ id: string; status: string }> {
  return apiFetch(`/questions/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify({ status, resolution_note }),
  });
}

export async function getQuestionEvidence(
  id: string,
  limit?: number,
): Promise<QuestionEvidenceResponse[]> {
  const sp = new URLSearchParams();
  if (limit) sp.set('limit', String(limit));
  const qs = sp.toString();
  return apiFetch<QuestionEvidenceResponse[]>(
    `/questions/${encodeURIComponent(id)}/evidence${qs ? `?${qs}` : ''}`
  );
}

// ============================================
// TRIGGER (manual pipeline runs)
// ============================================

export interface TriggerResponse {
  status: string;
  service: string;
  message: string;
  triggered_at: string;
}

export async function triggerIngestion(): Promise<TriggerResponse> {
  return apiFetch<TriggerResponse>('/trigger/ingestion', { method: 'POST' });
}

export async function triggerAgents(): Promise<TriggerResponse> {
  return apiFetch<TriggerResponse>('/trigger/agents', { method: 'POST' });
}

export async function triggerFeedback(): Promise<TriggerResponse> {
  return apiFetch<TriggerResponse>('/trigger/feedback', { method: 'POST' });
}

export async function triggerSignals(): Promise<TriggerResponse> {
  return apiFetch<TriggerResponse>('/trigger/signals', { method: 'POST' });
}

// ============================================
// WEBSOCKET
// ============================================

export function createChatWebSocket(): WebSocket | null {
  const wsUrl = API_URL.replace(/^http/, 'ws') + '/chat';
  try {
    return new WebSocket(wsUrl);
  } catch {
    return null;
  }
}
