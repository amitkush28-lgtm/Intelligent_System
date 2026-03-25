'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import { getPrediction, addNote } from '@/lib/api';
import { PredictionDetail, NoteCreate } from '@/lib/types';
import ConfidenceTrailChart from '@/components/charts/ConfidenceTrailChart';
import StatusBadge from '@/components/common/StatusBadge';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import {
  formatDate,
  formatDateTime,
  formatConfidence,
  formatBrier,
  getAgentBgClass,
  AGENT_LABELS,
  AGENT_ICONS,
  NOTE_TYPE_COLORS,
} from '@/lib/utils';

export default function PredictionDetailPage() {
  const params = useParams();
  const id = params.id as string;
  const [prediction, setPrediction] = useState<PredictionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [noteType, setNoteType] = useState('observation');
  const [noteText, setNoteText] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    async function load() {
      try {
        const data = await getPrediction(id);
        setPrediction(data);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [id]);

  const handleAddNote = async () => {
    if (!noteText.trim()) return;
    setSubmitting(true);
    try {
      const note = await addNote(id, { type: noteType, text: noteText.trim() });
      setPrediction((prev) =>
        prev ? { ...prev, notes: [...prev.notes, note] } : prev
      );
      setNoteText('');
    } catch (e: any) {
      alert('Failed to add note: ' + e.message);
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <LoadingSpinner text="Loading prediction..." />;
  if (error || !prediction) {
    return (
      <div className="py-20 text-center">
        <p className="text-red-400 text-sm">{error || 'Prediction not found'}</p>
        <Link href="/predictions" className="text-xs text-blue-400 mt-2 inline-block hover:underline">
          Back to predictions
        </Link>
      </div>
    );
  }

  const p = prediction;
  const deadline = p.time_condition_end || p.time_condition_date;

  // Extract initial reasoning from first confidence trail entry
  const initialTrail = p.confidence_trail.length > 0
    ? [...p.confidence_trail].sort((a, b) => new Date(a.date || 0).getTime() - new Date(b.date || 0).getTime())[0]
    : null;
  const initialReasoning = initialTrail?.reasoning || '';

  // Collect all unique reasoning entries from confidence trail (excluding initial)
  const reasoningHistory = p.confidence_trail
    .filter((t) => t.reasoning && t.reasoning !== initialReasoning)
    .sort((a, b) => new Date(b.date || 0).getTime() - new Date(a.date || 0).getTime());

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Link href="/predictions" className="hover:text-slate-300 transition-colors">
          Predictions
        </Link>
        <span>/</span>
        <span className="text-slate-400 font-mono">{p.id}</span>
      </div>

      {/* Header */}
      <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-6">
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="flex items-center gap-3">
            <span className="text-2xl">{AGENT_ICONS[p.agent] || '\u2726'}</span>
            <span className={`text-xs px-2.5 py-1 rounded-full ${getAgentBgClass(p.agent)}`}>
              {AGENT_LABELS[p.agent] || p.agent}
            </span>
            <StatusBadge status={p.status} size="md" />
          </div>
          <div className="text-right">
            <p className="text-3xl font-semibold text-slate-100 font-mono">
              {formatConfidence(p.current_confidence)}
            </p>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mt-0.5">
              Confidence
            </p>
          </div>
        </div>
        <h2 className="text-lg text-slate-200 leading-relaxed mb-4">{p.claim}</h2>
        <div className="grid grid-cols-4 gap-4 text-xs">
          <div>
            <p className="text-slate-500 mb-0.5">Created</p>
            <p className="text-slate-300">{formatDate(p.created_at)}</p>
          </div>
          <div>
            <p className="text-slate-500 mb-0.5">Deadline</p>
            <p className="text-slate-300">{deadline ? formatDate(deadline) : 'Ongoing'}</p>
          </div>
          <div>
            <p className="text-slate-500 mb-0.5">Brier Score</p>
            <p className="text-slate-300">{formatBrier(p.brier_score)}</p>
          </div>
          <div>
            <p className="text-slate-500 mb-0.5">Type</p>
            <p className="text-slate-300">{p.time_condition_type}</p>
          </div>
        </div>
      </div>

      {/* Analysis & Reasoning — PROMINENT SECTION */}
      {initialReasoning && (
        <div className="bg-surface-700/50 border border-blue-500/20 rounded-xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="text-blue-400 text-lg">&#x1F9E0;</span>
            <h3 className="text-sm font-semibold text-slate-200">Analysis & Reasoning</h3>
          </div>
          <div className="text-sm text-slate-300 leading-relaxed whitespace-pre-wrap">
            {initialReasoning}
          </div>
        </div>
      )}

      {/* Resolution Criteria + Key Info */}
      <div className="grid grid-cols-2 gap-4">
        <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-200 mb-3">Resolution Criteria</h3>
          <p className="text-sm text-slate-300 leading-relaxed">{p.resolution_criteria}</p>
        </div>

        {/* Post-mortem */}
        {p.post_mortem && Object.keys(p.post_mortem).length > 0 && (
          <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-slate-200 mb-3">Post-Mortem</h3>
            <div className="space-y-2 text-sm">
              {Object.entries(p.post_mortem).map(([key, value]) => (
                <div key={key}>
                  <p className="text-slate-500 text-xs uppercase tracking-wider">{key.replace(/_/g, ' ')}</p>
                  <p className="text-slate-300">{String(value)}</p>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Confidence trail chart */}
      <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-slate-200 mb-3">Confidence History</h3>
        <ConfidenceTrailChart trail={p.confidence_trail} />
      </div>

      {/* Reasoning History — shows all confidence change explanations */}
      {reasoningHistory.length > 0 && (
        <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-200 mb-4">
            Confidence Change Log ({reasoningHistory.length})
          </h3>
          <div className="space-y-3">
            {reasoningHistory.map((t, i) => (
              <div
                key={t.id}
                className="flex items-start gap-3 text-sm border-b border-slate-800/50 pb-3 last:border-0"
              >
                <div className="text-right min-w-[60px]">
                  <span className="text-blue-400 font-mono text-xs">
                    {(t.value * 100).toFixed(0)}%
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-xs text-amber-400/80 mb-1">{t.trigger}</p>
                  <p className="text-xs text-slate-400 leading-relaxed whitespace-pre-wrap">{t.reasoning}</p>
                  <p className="text-[10px] text-slate-600 mt-1">{formatDateTime(t.date)}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Parent / Sub-predictions */}
      <div className="grid grid-cols-2 gap-4">
        {p.parent_id && (
          <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-slate-200 mb-3">Parent Prediction</h3>
            <Link
              href={`/predictions/${encodeURIComponent(p.parent_id)}`}
              className="text-sm text-blue-400 hover:underline font-mono"
            >
              {p.parent_id}
            </Link>
          </div>
        )}

        {p.sub_predictions.length > 0 && (
          <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
            <h3 className="text-sm font-semibold text-slate-200 mb-3">
              Sub-Predictions ({p.sub_predictions.length})
            </h3>
            <div className="space-y-2">
              {p.sub_predictions.map((sp) => (
                <Link
                  key={sp.id}
                  href={`/predictions/${encodeURIComponent(sp.id)}`}
                  className="block p-2.5 rounded-lg bg-surface-800/50 hover:bg-surface-600/50 transition-colors"
                >
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-slate-300 truncate max-w-xs">{sp.claim}</p>
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-mono text-slate-400">
                        {formatConfidence(sp.current_confidence)}
                      </span>
                      <StatusBadge status={sp.status} />
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Notes */}
      <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-slate-200 mb-4">
          Notes ({p.notes.length})
        </h3>
        {p.notes.length > 0 && (
          <div className="space-y-3 mb-5">
            {p.notes.map((n) => (
              <div
                key={n.id}
                className="flex items-start gap-3 text-sm border-b border-slate-800/50 pb-3 last:border-0"
              >
                <span
                  className={`text-[10px] px-2 py-0.5 rounded-full whitespace-nowrap mt-0.5 ${
                    NOTE_TYPE_COLORS[n.type] || 'bg-gray-500/15 text-gray-400'
                  }`}
                >
                  {n.type}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-slate-300 whitespace-pre-wrap">{n.text}</p>
                  <p className="text-[10px] text-slate-600 mt-1">{formatDateTime(n.date)}</p>
                </div>
              </div>
            ))}
          </div>
        )}
        {/* Add note form */}
        <div className="flex items-start gap-3">
          <select
            value={noteType}
            onChange={(e) => setNoteType(e.target.value)}
            className="bg-surface-800 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-blue-500/50"
          >
            <option value="observation">Observation</option>
            <option value="key_signal">Key Signal</option>
            <option value="counter_signal">Counter Signal</option>
            <option value="analysis">Analysis</option>
          </select>
          <textarea
            value={noteText}
            onChange={(e) => setNoteText(e.target.value)}
            placeholder="Add a note..."
            rows={2}
            className="flex-1 bg-surface-800 border border-slate-700/50 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-600 focus:outline-none focus:border-blue-500/50 resize-none"
          />
          <button
            onClick={handleAddNote}
            disabled={submitting || !noteText.trim()}
            className="px-4 py-2 text-xs font-medium rounded-lg bg-blue-500/20 text-blue-400 hover:bg-blue-500/30 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? 'Adding...' : 'Add Note'}
          </button>
        </div>
      </div>

      {/* Debates */}
      {p.debates.length > 0 && (
        <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-200 mb-4">
            Debates ({p.debates.length})
          </h3>
          <div className="space-y-4">
            {p.debates.map((d) => (
              <div
                key={d.id}
                className="border border-slate-800/50 rounded-lg p-4"
              >
                <div className="flex items-center justify-between mb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-red-400 text-sm">&#x2694;</span>
                    <span className="text-xs text-slate-400">{d.trigger_reason}</span>
                  </div>
                  {d.devil_impact != null && (
                    <span className="text-xs text-slate-500">
                      Impact: <span className="text-slate-300 font-mono">{(d.devil_impact * 100).toFixed(1)}pp</span>
                    </span>
                  )}
                </div>
                {d.rounds && Array.isArray(d.rounds) && d.rounds.map((round: any, ri: number) => (
                  <div key={ri} className="space-y-2 mb-3">
                    {round.advocate && (
                      <div className="pl-3 border-l-2 border-blue-500/30">
                        <p className="text-[10px] text-blue-400 uppercase tracking-wider mb-1">Advocate</p>
                        <p className="text-xs text-slate-300">{typeof round.advocate === 'string' ? round.advocate : round.advocate.text}</p>
                      </div>
                    )}
                    {round.devil && (
                      <div className="pl-3 border-l-2 border-red-500/30">
                        <p className="text-[10px] text-red-400 uppercase tracking-wider mb-1">Devil&apos;s Advocate</p>
                        <p className="text-xs text-slate-300">{typeof round.devil === 'string' ? round.devil : round.devil.text}</p>
                      </div>
                    )}
                    {round.resolution && (
                      <div className="pl-3 border-l-2 border-emerald-500/30">
                        <p className="text-[10px] text-emerald-400 uppercase tracking-wider mb-1">Resolution</p>
                        <p className="text-xs text-slate-300">{typeof round.resolution === 'string' ? round.resolution : round.resolution.text}</p>
                      </div>
                    )}
                  </div>
                ))}
                <p className="text-[10px] text-slate-600">{formatDateTime(d.created_at)}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
