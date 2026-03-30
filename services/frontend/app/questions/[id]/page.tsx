'use client';

import { useEffect, useState, useCallback } from 'react';
import { useParams, useRouter } from 'next/navigation';
import Link from 'next/link';
import { getQuestion, reanalyzeQuestion, updateQuestionStatus, getFollowups, askFollowup } from '@/lib/api';
import { QuestionDetailResponse, QuestionAssumptionResponse, QuestionEvidenceResponse, FollowupMessage } from '@/lib/types';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { formatDateTime, timeAgo, formatDate } from '@/lib/utils';

const TRAFFIC_LIGHT: Record<string, { bg: string; text: string; dot: string; border: string; label: string }> = {
  green:  { bg: 'bg-emerald-500/15', text: 'text-emerald-400', dot: 'bg-emerald-400', border: 'border-emerald-500/30', label: 'Green' },
  yellow: { bg: 'bg-amber-500/15',   text: 'text-amber-400',   dot: 'bg-amber-400',   border: 'border-amber-500/30',   label: 'Yellow' },
  red:    { bg: 'bg-red-500/15',     text: 'text-red-400',     dot: 'bg-red-400',     border: 'border-red-500/30',     label: 'Red' },
};

const VERDICT_COLORS: Record<string, string> = {
  BULLISH: 'text-emerald-400',
  BEARISH: 'text-red-400',
  NEUTRAL: 'text-slate-400',
  MIXED: 'text-amber-400',
};

const AGENT_ICONS: Record<string, string> = {
  economist: '\u{1F4CA}',
  geopolitical: '\u{1F30D}',
  investor: '\u{1F4B9}',
  political: '\u{1F3DB}',
  sentiment: '\u{1F4E1}',
  wildcard: '\u{1F500}',
};

export default function QuestionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const questionId = params.id as string;

  const [question, setQuestion] = useState<QuestionDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [followups, setFollowups] = useState<FollowupMessage[]>([]);
  const [followupInput, setFollowupInput] = useState('');
  const [followupLoading, setFollowupLoading] = useState(false);
  const [showChat, setShowChat] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getQuestion(questionId);
      setQuestion(result);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [questionId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const loadFollowups = useCallback(async () => {
    try {
      const msgs = await getFollowups(questionId);
      setFollowups(msgs);
      if (msgs.length > 0) setShowChat(true);
    } catch {
      // Followups table might not exist yet — that's OK
    }
  }, [questionId]);

  useEffect(() => { loadFollowups(); }, [loadFollowups]);

  const handleAskFollowup = async () => {
    const msg = followupInput.trim();
    if (!msg || followupLoading) return;
    setFollowupLoading(true);
    setFollowupInput('');
    // Optimistically add the user message
    setFollowups(prev => [...prev, { id: Date.now(), role: 'user', message: msg, created_at: new Date().toISOString() }]);
    try {
      const response = await askFollowup(questionId, msg);
      // Replace optimistic + add assistant response
      setFollowups(prev => [...prev, response]);
    } catch (e: any) {
      setFollowups(prev => [...prev, { id: Date.now(), role: 'assistant', message: `Error: ${e.message}`, created_at: new Date().toISOString() }]);
    } finally {
      setFollowupLoading(false);
    }
  };

  const handleReanalyze = async () => {
    setActionLoading(true);
    setActionMsg(null);
    try {
      const result = await reanalyzeQuestion(questionId);
      setActionMsg(result.message);
      // Poll for updated results after a delay
      setTimeout(fetchData, 5000);
    } catch (e: any) {
      setActionMsg('Re-analysis failed: ' + e.message);
    } finally {
      setActionLoading(false);
    }
  };

  const handleStatusChange = async (newStatus: string) => {
    setActionLoading(true);
    try {
      await updateQuestionStatus(questionId, newStatus);
      fetchData();
    } catch (e: any) {
      setActionMsg('Status update failed: ' + e.message);
    } finally {
      setActionLoading(false);
    }
  };

  if (loading) return <LoadingSpinner />;
  if (error) return (
    <div className="space-y-4">
      <Link href="/questions" className="text-xs text-slate-500 hover:text-slate-300">&larr; Back to Questions</Link>
      <div className="bg-surface-700/30 border border-slate-700/50 rounded-xl p-8 text-center text-sm text-red-400">{error}</div>
    </div>
  );
  if (!question) return null;

  const light = TRAFFIC_LIGHT[question.overall_status || 'green'];
  const assumptions = question.assumptions || [];
  const evidence = question.recent_evidence || [];
  const perspectives = question.agent_perspectives || {};

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Breadcrumb */}
      <Link href="/questions" className="text-xs text-slate-500 hover:text-slate-300 transition-colors">
        &larr; Back to Questions
      </Link>

      {/* Header Card */}
      <div className="bg-surface-700/30 border border-slate-700/50 rounded-xl p-6">
        <div className="flex items-start gap-4">
          <div className={`mt-1 h-4 w-4 rounded-full ${light.dot} flex-shrink-0`} />
          <div className="flex-1">
            <h1 className="text-lg font-semibold text-slate-100 leading-snug">
              {question.question}
            </h1>
            {question.thesis_summary && (
              <p className="text-sm text-slate-400 mt-2 leading-relaxed">
                {question.thesis_summary}
              </p>
            )}

            {/* Metrics Row */}
            <div className="flex flex-wrap items-center gap-4 mt-4">
              <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium ${light.bg} ${light.text}`}>
                <span className={`h-2 w-2 rounded-full ${light.dot}`} />
                {light.label}
              </span>
              {question.thesis_verdict && (
                <span className={`text-sm font-semibold ${VERDICT_COLORS[question.thesis_verdict] || 'text-slate-400'}`}>
                  {question.thesis_verdict}
                </span>
              )}
              {question.overall_confidence != null && (
                <span className="text-sm text-slate-300 tabular-nums font-medium">
                  {question.overall_confidence}% confidence
                </span>
              )}
              {question.category && (
                <span className="text-xs bg-surface-700 px-2 py-0.5 rounded text-slate-400">
                  {question.category}
                </span>
              )}
              <span className="text-xs text-slate-500 capitalize">{question.status}</span>
            </div>

            {/* Dates */}
            <div className="flex items-center gap-6 mt-3 text-xs text-slate-500">
              <span>Created {formatDateTime(question.created_at)}</span>
              <span>Analyzed {timeAgo(question.last_analyzed_at)}</span>
              {question.next_review_date && (
                <span>Next review {formatDate(question.next_review_date)}</span>
              )}
            </div>

            {/* Tags */}
            {question.tags && question.tags.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-3">
                {question.tags.map((tag) => (
                  <span key={tag} className="px-2 py-0.5 bg-surface-700 rounded text-[11px] text-slate-500">
                    {tag}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Actions */}
        <div className="flex items-center gap-3 mt-5 pt-4 border-t border-slate-700/50">
          <button
            onClick={handleReanalyze}
            disabled={actionLoading}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 text-white text-xs font-medium rounded-lg transition-colors"
          >
            {actionLoading ? 'Working...' : 'Re-analyze'}
          </button>
          {question.status === 'active' && (
            <button
              onClick={() => handleStatusChange('paused')}
              disabled={actionLoading}
              className="px-4 py-2 bg-surface-700 hover:bg-surface-600 border border-slate-700/50 text-slate-300 text-xs rounded-lg transition-colors"
            >
              Pause
            </button>
          )}
          {question.status === 'paused' && (
            <button
              onClick={() => handleStatusChange('active')}
              disabled={actionLoading}
              className="px-4 py-2 bg-surface-700 hover:bg-surface-600 border border-slate-700/50 text-slate-300 text-xs rounded-lg transition-colors"
            >
              Resume
            </button>
          )}
          {question.status !== 'resolved' && question.status !== 'archived' && (
            <button
              onClick={() => handleStatusChange('resolved')}
              disabled={actionLoading}
              className="px-4 py-2 bg-surface-700 hover:bg-surface-600 border border-slate-700/50 text-slate-300 text-xs rounded-lg transition-colors"
            >
              Resolve
            </button>
          )}
          {actionMsg && <span className="text-xs text-slate-400 ml-2">{actionMsg}</span>}
        </div>
      </div>

      {/* Recommendation */}
      {question.recommendation && (
        <div className="bg-blue-500/5 border border-blue-500/20 rounded-xl p-5">
          <h2 className="text-xs font-semibold text-blue-400 uppercase tracking-wider mb-2">Recommendation</h2>
          <p className="text-sm text-slate-300 leading-relaxed">{question.recommendation}</p>
        </div>
      )}

      {/* Assumptions Grid */}
      {assumptions.length > 0 && (() => {
        const parents = assumptions.filter(a => !a.parent_id);
        const subs = assumptions.filter(a => a.parent_id);
        const subMap: Record<string, QuestionAssumptionResponse[]> = {};
        subs.forEach(s => {
          if (s.parent_id) {
            if (!subMap[s.parent_id]) subMap[s.parent_id] = [];
            subMap[s.parent_id].push(s);
          }
        });

        return (
          <div>
            <h2 className="text-sm font-semibold text-slate-200 mb-3">
              Assumptions ({parents.length}{subs.length > 0 ? ` + ${subs.length} sub` : ''})
            </h2>
            <div className="grid gap-3 grid-cols-1 lg:grid-cols-2">
              {parents.map((a) => (
                <div key={a.id} className="space-y-2">
                  <AssumptionCard assumption={a} />
                  {(subMap[a.id] || []).map((sub) => (
                    <SubAssumptionCard key={sub.id} assumption={sub} />
                  ))}
                </div>
              ))}
            </div>
          </div>
        );
      })()}

      {/* Agent Perspectives */}
      {Object.keys(perspectives).length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-slate-200 mb-3">Agent Perspectives</h2>
          <div className="grid gap-3 grid-cols-1 md:grid-cols-2 lg:grid-cols-3">
            {Object.entries(perspectives).map(([agent, text]) => (
              <div
                key={agent}
                className="bg-surface-700/30 border border-slate-700/50 rounded-xl p-4"
              >
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-base">{AGENT_ICONS[agent] || '\u{1F916}'}</span>
                  <span className="text-xs font-semibold text-slate-300 capitalize">{agent}</span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">{text}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Follow-up Chat */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-slate-200">Ask Follow-up</h2>
          {!showChat && followups.length === 0 && (
            <button
              onClick={() => setShowChat(true)}
              className="text-xs text-blue-400 hover:text-blue-300 transition-colors"
            >
              Open Chat
            </button>
          )}
        </div>

        {(showChat || followups.length > 0) && (
          <div className="bg-surface-700/30 border border-slate-700/50 rounded-xl overflow-hidden">
            {/* Messages */}
            {followups.length > 0 && (
              <div className="max-h-[400px] overflow-y-auto p-4 space-y-3">
                {followups.map((msg) => (
                  <div
                    key={msg.id}
                    className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-xl px-4 py-2.5 text-sm leading-relaxed ${
                        msg.role === 'user'
                          ? 'bg-blue-600/20 border border-blue-500/30 text-slate-200'
                          : 'bg-surface-700/50 border border-slate-700/50 text-slate-300'
                      }`}
                    >
                      {msg.role === 'assistant' && (
                        <div className="text-[10px] text-slate-500 mb-1 font-medium uppercase tracking-wider">
                          Master Strategist
                        </div>
                      )}
                      <div className="whitespace-pre-wrap">{msg.message}</div>
                    </div>
                  </div>
                ))}
                {followupLoading && (
                  <div className="flex justify-start">
                    <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl px-4 py-2.5 text-sm text-slate-400">
                      <span className="inline-flex items-center gap-1.5">
                        Thinking
                        <span className="inline-block h-1 w-1 rounded-full bg-slate-400 animate-pulse" />
                        <span className="inline-block h-1 w-1 rounded-full bg-slate-400 animate-pulse" style={{ animationDelay: '0.2s' }} />
                        <span className="inline-block h-1 w-1 rounded-full bg-slate-400 animate-pulse" style={{ animationDelay: '0.4s' }} />
                      </span>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Input */}
            <div className="border-t border-slate-700/50 p-3 flex gap-2">
              <input
                type="text"
                value={followupInput}
                onChange={(e) => setFollowupInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleAskFollowup(); } }}
                placeholder="Ask about this question... e.g., &quot;How does the latest Fed data affect assumption #2?&quot;"
                disabled={followupLoading}
                className="flex-1 bg-surface-800/50 border border-slate-700/30 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500/50 transition-colors disabled:opacity-50"
              />
              <button
                onClick={handleAskFollowup}
                disabled={followupLoading || !followupInput.trim()}
                className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-xs font-medium rounded-lg transition-colors flex-shrink-0"
              >
                {followupLoading ? '...' : 'Ask'}
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Evidence Timeline */}
      {evidence.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-slate-200 mb-3">
            Recent Evidence ({evidence.length})
          </h2>
          <div className="space-y-2">
            {evidence.map((e) => (
              <EvidenceRow key={e.id} evidence={e} />
            ))}
          </div>
        </div>
      )}

      {assumptions.length === 0 && evidence.length === 0 && question.status === 'analyzing' && (
        <div className="bg-surface-700/30 border border-slate-700/50 rounded-xl p-12 text-center">
          <div className="animate-pulse text-2xl mb-3">&#9881;</div>
          <p className="text-slate-400 text-sm">Analysis in progress...</p>
          <p className="text-slate-500 text-xs mt-1">This typically takes 30-60 seconds. Refresh to check.</p>
          <button onClick={fetchData} className="mt-4 px-4 py-2 bg-surface-700 text-slate-300 text-xs rounded-lg hover:bg-surface-600 transition-colors">
            Refresh
          </button>
        </div>
      )}
    </div>
  );
}


function AssumptionCard({ assumption }: { assumption: QuestionAssumptionResponse }) {
  const light = TRAFFIC_LIGHT[assumption.status || 'green'];

  return (
    <div className={`bg-surface-700/30 border ${light.border} rounded-xl p-4`}>
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 flex items-center justify-center h-6 w-6 rounded-full bg-surface-700 text-xs text-slate-400 font-medium">
          {assumption.assumption_number}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm text-slate-200 leading-snug">{assumption.assumption_text}</p>

          <div className="flex items-center gap-3 mt-2">
            <span className={`inline-flex items-center gap-1 text-xs ${light.text}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${light.dot}`} />
              {light.label}
            </span>
            {assumption.confidence != null && (
              <span className="text-xs text-slate-400 tabular-nums">{assumption.confidence}%</span>
            )}
            <span className="text-xs text-slate-500">
              {assumption.supporting_evidence_count} supporting &middot; {assumption.challenging_evidence_count} challenging
            </span>
          </div>

          {assumption.current_assessment && (
            <p className="text-xs text-slate-400 mt-2 leading-relaxed">{assumption.current_assessment}</p>
          )}

          {/* Tripwires */}
          <div className="mt-3 space-y-1">
            {assumption.green_to_yellow_trigger && (
              <div className="flex gap-2 text-xs">
                <span className="text-amber-500 flex-shrink-0">&#9888;</span>
                <span className="text-slate-500">{assumption.green_to_yellow_trigger}</span>
              </div>
            )}
            {assumption.yellow_to_red_trigger && (
              <div className="flex gap-2 text-xs">
                <span className="text-red-500 flex-shrink-0">&#9888;</span>
                <span className="text-slate-500">{assumption.yellow_to_red_trigger}</span>
              </div>
            )}
          </div>

          {/* Keywords */}
          {assumption.keywords && assumption.keywords.length > 0 && (
            <div className="flex flex-wrap gap-1 mt-2">
              {assumption.keywords.map((kw) => (
                <span key={kw} className="px-1.5 py-0.5 bg-surface-700 rounded text-[10px] text-slate-500">
                  {kw}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


function SubAssumptionCard({ assumption }: { assumption: QuestionAssumptionResponse }) {
  const light = TRAFFIC_LIGHT[assumption.status || 'green'];

  return (
    <div className={`ml-6 bg-surface-700/20 border ${light.border} border-dashed rounded-lg p-3`}>
      <div className="flex items-start gap-2">
        <div className="flex-shrink-0 flex items-center justify-center h-5 w-auto px-1.5 rounded bg-surface-700 text-[10px] text-slate-400 font-medium">
          {assumption.assumption_number}{assumption.sub_label}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-xs text-slate-300 leading-snug">{assumption.assumption_text}</p>

          <div className="flex items-center gap-3 mt-1.5">
            <span className={`inline-flex items-center gap-1 text-[10px] ${light.text}`}>
              <span className={`h-1 w-1 rounded-full ${light.dot}`} />
              {light.label}
            </span>
            {assumption.confidence != null && (
              <span className="text-[10px] text-slate-400 tabular-nums">{assumption.confidence}%</span>
            )}
          </div>

          {/* Tripwires */}
          {(assumption.green_to_yellow_trigger || assumption.yellow_to_red_trigger) && (
            <div className="mt-2 space-y-0.5">
              {assumption.green_to_yellow_trigger && (
                <div className="flex gap-1.5 text-[10px]">
                  <span className="text-amber-500 flex-shrink-0">&#9650;</span>
                  <span className="text-slate-500">{assumption.green_to_yellow_trigger}</span>
                </div>
              )}
              {assumption.yellow_to_red_trigger && (
                <div className="flex gap-1.5 text-[10px]">
                  <span className="text-red-500 flex-shrink-0">&#9650;</span>
                  <span className="text-slate-500">{assumption.yellow_to_red_trigger}</span>
                </div>
              )}
            </div>
          )}

          {/* Monitoring Data Points */}
          {assumption.monitoring_data_points && assumption.monitoring_data_points.length > 0 && (
            <div className="mt-2">
              <span className="text-[10px] text-slate-500 font-medium">Tracking: </span>
              <span className="text-[10px] text-slate-400">
                {assumption.monitoring_data_points.join(' \u00B7 ')}
              </span>
            </div>
          )}

          {/* Baseline Data */}
          {assumption.baseline_data && Object.keys(assumption.baseline_data).length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-1.5">
              {Object.entries(assumption.baseline_data).map(([k, v]) => (
                <span key={k} className="px-1.5 py-0.5 bg-surface-700/50 rounded text-[10px] text-slate-500">
                  {k}: {v}
                </span>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


function EvidenceRow({ evidence }: { evidence: QuestionEvidenceResponse }) {
  const impactColors: Record<string, string> = {
    high: 'text-red-400',
    medium: 'text-amber-400',
    low: 'text-blue-400',
  };

  return (
    <div className="bg-surface-700/30 border border-slate-700/50 rounded-lg px-4 py-3 flex items-start gap-3">
      <div className={`mt-0.5 h-2 w-2 rounded-full flex-shrink-0 ${
        evidence.triggered_status_change ? 'bg-red-400' : 'bg-slate-600'
      }`} />
      <div className="flex-1 min-w-0">
        <p className="text-xs text-slate-300 leading-snug">{evidence.evidence_summary}</p>
        <div className="flex items-center gap-3 mt-1.5 text-[11px] text-slate-500">
          <span className="capitalize">{evidence.evidence_type.replace(/_/g, ' ')}</span>
          {evidence.impact_level && (
            <span className={impactColors[evidence.impact_level] || 'text-slate-400'}>
              {evidence.impact_level} impact
            </span>
          )}
          {evidence.source && <span>{evidence.source}</span>}
          {evidence.agent_that_flagged && <span>via {evidence.agent_that_flagged}</span>}
          <span className="ml-auto">{timeAgo(evidence.detected_at)}</span>
        </div>
      </div>
    </div>
  );
}
