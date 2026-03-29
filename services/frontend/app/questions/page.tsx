'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { getQuestions, createQuestion } from '@/lib/api';
import { QuestionSummaryResponse } from '@/lib/types';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { formatDateTime, timeAgo } from '@/lib/utils';

const TRAFFIC_LIGHT: Record<string, { bg: string; text: string; dot: string; label: string }> = {
  green:  { bg: 'bg-emerald-500/15', text: 'text-emerald-400', dot: 'bg-emerald-400', label: 'Green' },
  yellow: { bg: 'bg-amber-500/15',   text: 'text-amber-400',   dot: 'bg-amber-400',   label: 'Yellow' },
  red:    { bg: 'bg-red-500/15',     text: 'text-red-400',     dot: 'bg-red-400',     label: 'Red' },
};

const VERDICT_COLORS: Record<string, string> = {
  BULLISH: 'text-emerald-400',
  BEARISH: 'text-red-400',
  NEUTRAL: 'text-slate-400',
  MIXED: 'text-amber-400',
};

const CATEGORIES = ['', 'INVESTMENT', 'SAFETY', 'BUSINESS', 'GEOPOLITICAL', 'PERSONAL'];

export default function QuestionsPage() {
  const [questions, setQuestions] = useState<QuestionSummaryResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filterStatus, setFilterStatus] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [formQuestion, setFormQuestion] = useState('');
  const [formContext, setFormContext] = useState('');
  const [formCategory, setFormCategory] = useState('INVESTMENT');
  const [submitting, setSubmitting] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getQuestions(filterStatus ? { status: filterStatus } : undefined);
      setQuestions(result);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [filterStatus]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSubmit = async () => {
    if (!formQuestion.trim() || formQuestion.length < 10) return;
    setSubmitting(true);
    try {
      await createQuestion({
        question: formQuestion,
        context: formContext || undefined,
        category: formCategory,
      });
      setFormQuestion('');
      setFormContext('');
      setShowForm(false);
      fetchData();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  };

  const selectClass =
    'bg-surface-700 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-blue-500/50 transition-colors';
  const inputClass =
    'w-full bg-surface-700 border border-slate-700/50 rounded-lg px-3 py-2.5 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-blue-500/50 transition-colors';

  return (
    <div className="space-y-5 animate-fadeIn">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Living Questions</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Thesis tracking with falsifiable assumptions and continuous monitoring
          </p>
        </div>
        <button
          onClick={() => setShowForm(!showForm)}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {showForm ? 'Cancel' : '+ New Question'}
        </button>
      </div>

      {/* New Question Form */}
      {showForm && (
        <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5 space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Question or Thesis</label>
            <textarea
              value={formQuestion}
              onChange={(e) => setFormQuestion(e.target.value)}
              placeholder="e.g., Should I invest in data center stocks given the AI efficiency trend?"
              rows={2}
              className={inputClass}
            />
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Context (optional)</label>
              <textarea
                value={formContext}
                onChange={(e) => setFormContext(e.target.value)}
                placeholder="Any additional context about your situation..."
                rows={2}
                className={inputClass}
              />
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Category</label>
              <select
                value={formCategory}
                onChange={(e) => setFormCategory(e.target.value)}
                className={selectClass + ' w-full'}
              >
                {CATEGORIES.filter(Boolean).map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
            </div>
          </div>
          <div className="flex justify-end">
            <button
              onClick={handleSubmit}
              disabled={submitting || formQuestion.length < 10}
              className="px-5 py-2 bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:text-slate-500 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {submitting ? 'Submitting...' : 'Submit Question'}
            </button>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-3">
        <select
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
          className={selectClass}
        >
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="analyzing">Analyzing</option>
          <option value="paused">Paused</option>
          <option value="resolved">Resolved</option>
          <option value="archived">Archived</option>
        </select>
        {filterStatus && (
          <button
            onClick={() => setFilterStatus('')}
            className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            Clear
          </button>
        )}
        <div className="flex-1" />
        <span className="text-xs text-slate-500">
          {questions.length} question{questions.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Questions List */}
      {loading ? (
        <LoadingSpinner />
      ) : error ? (
        <div className="bg-surface-700/30 border border-slate-700/50 rounded-xl p-8 text-center text-sm text-red-400">
          {error}
        </div>
      ) : questions.length === 0 ? (
        <div className="bg-surface-700/30 border border-slate-700/50 rounded-xl p-12 text-center">
          <p className="text-slate-400 text-sm">No questions yet.</p>
          <p className="text-slate-500 text-xs mt-1">Submit a question to start tracking.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {questions.map((q) => {
            const light = TRAFFIC_LIGHT[q.overall_status || 'green'];
            return (
              <Link key={q.id} href={`/questions/${q.id}`}>
                <div className="bg-surface-700/30 border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/50 transition-all cursor-pointer group">
                  <div className="flex items-start gap-4">
                    {/* Traffic light indicator */}
                    <div className={`mt-1 h-3 w-3 rounded-full ${light.dot} flex-shrink-0`} />

                    <div className="flex-1 min-w-0">
                      {/* Top row: question + badges */}
                      <div className="flex items-start justify-between gap-3">
                        <h3 className="text-sm font-medium text-slate-200 group-hover:text-white transition-colors leading-snug">
                          {q.question}
                        </h3>
                        <div className="flex items-center gap-2 flex-shrink-0">
                          {q.thesis_verdict && (
                            <span className={`text-xs font-semibold ${VERDICT_COLORS[q.thesis_verdict] || 'text-slate-400'}`}>
                              {q.thesis_verdict}
                            </span>
                          )}
                          {q.overall_confidence != null && (
                            <span className="text-xs text-slate-400 tabular-nums">
                              {q.overall_confidence}%
                            </span>
                          )}
                        </div>
                      </div>

                      {/* Summary */}
                      {q.thesis_summary && (
                        <p className="text-xs text-slate-400 mt-1.5 line-clamp-2">
                          {q.thesis_summary}
                        </p>
                      )}

                      {/* Bottom row: metadata */}
                      <div className="flex items-center gap-4 mt-3 text-xs text-slate-500">
                        <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 ${light.bg} ${light.text}`}>
                          <span className={`h-1.5 w-1.5 rounded-full ${light.dot}`} />
                          {light.label}
                        </span>
                        {q.category && (
                          <span className="bg-surface-700 px-2 py-0.5 rounded text-slate-400">
                            {q.category}
                          </span>
                        )}
                        <span>{q.assumption_count} assumptions</span>
                        <span>{q.evidence_count} evidence</span>
                        {q.status !== 'active' && (
                          <span className="capitalize text-slate-400">{q.status}</span>
                        )}
                        <span className="ml-auto">{timeAgo(q.last_analyzed_at)}</span>
                      </div>

                      {/* Tags */}
                      {q.tags && q.tags.length > 0 && (
                        <div className="flex flex-wrap gap-1.5 mt-2">
                          {q.tags.map((tag) => (
                            <span
                              key={tag}
                              className="px-1.5 py-0.5 bg-surface-700 rounded text-[10px] text-slate-500"
                            >
                              {tag}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
