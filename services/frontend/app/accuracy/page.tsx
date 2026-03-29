'use client';

import { useEffect, useState } from 'react';
import { getAccuracyHistory } from '@/lib/api';
import { AccuracyHistoryResponse } from '@/lib/types';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import MetricCard from '@/components/layout/MetricCard';
import { formatPercent, formatBrier, AGENT_LABELS } from '@/lib/utils';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from 'recharts';

export default function AccuracyPage() {
  const [data, setData] = useState<AccuracyHistoryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [days, setDays] = useState(90);

  useEffect(() => {
    loadAccuracyHistory();
  }, [days]);

  async function loadAccuracyHistory() {
    try {
      const result = await getAccuracyHistory(days);
      setData(result);
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Failed to load accuracy history');
    }
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="text-red-400 text-sm font-medium">Error Loading Data</div>
        <p className="text-xs text-slate-500 max-w-md text-center">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="mt-2 text-xs px-4 py-2 rounded-lg bg-surface-700 text-slate-300 hover:bg-surface-600 transition-colors"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) return <LoadingSpinner text="Loading accuracy history..." />;

  const summary = data.summary;

  // Prepare chart data
  const chartData = data.timeline.map(point => ({
    date: new Date(point.date).toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
    cumulative: point.cumulative_accuracy !== null ? Math.round(point.cumulative_accuracy * 100) : null,
    rolling_7d: point.rolling_7d_accuracy !== null ? Math.round(point.rolling_7d_accuracy * 100) : null,
  })).filter(d => d.cumulative !== null || d.rolling_7d !== null);

  // Build agent breakdown table
  const agentStats = Object.entries(data.by_agent).map(([agent, entries]) => {
    if (entries.length === 0) return null;
    const last = entries[entries.length - 1];
    return {
      agent,
      resolved: last.resolved_count,
      correct: last.correct_count,
      accuracy: last.cumulative_accuracy,
      brier: last.cumulative_brier,
    };
  }).filter(Boolean) as Array<any>;

  agentStats.sort((a, b) => (b.accuracy ?? 0) - (a.accuracy ?? 0));

  // Build domain breakdown table
  const domainStats = Object.entries(data.by_domain).map(([domain, entries]) => {
    if (entries.length === 0) return null;
    const last = entries[entries.length - 1];
    return {
      domain,
      resolved: last.resolved_count,
      correct: last.correct_count,
      accuracy: last.cumulative_accuracy,
    };
  }).filter(Boolean) as Array<any>;

  domainStats.sort((a, b) => (b.accuracy ?? 0) - (a.accuracy ?? 0));

  function getAccuracyColor(accuracy: number | null): string {
    if (accuracy === null) return 'text-slate-400';
    if (accuracy >= 0.7) return 'text-emerald-400';
    if (accuracy >= 0.5) return 'text-amber-400';
    return 'text-red-400';
  }

  function getAccuracyBg(accuracy: number | null): string {
    if (accuracy === null) return 'bg-transparent';
    if (accuracy >= 0.7) return 'bg-emerald-500/10';
    if (accuracy >= 0.5) return 'bg-amber-500/10';
    return 'bg-red-500/10';
  }

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Accuracy History</h1>
          <p className="text-xs text-slate-500 mt-0.5">Prediction accuracy tracking and performance analysis</p>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400">Time Range:</label>
          <select
            value={days}
            onChange={(e) => setDays(parseInt(e.target.value))}
            className="px-3 py-2 rounded-lg bg-surface-700 text-slate-300 text-xs border border-slate-600/50 hover:border-slate-500/50 transition-colors"
          >
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
            <option value={180}>Last 180 days</option>
            <option value={365}>Last year</option>
          </select>
        </div>
      </div>

      {/* Summary Cards */}
      <div className="grid grid-cols-5 gap-4">
        <MetricCard
          label="Total Resolved"
          value={String(summary.total_resolved)}
          subtitle="Predictions resolved"
        />
        <MetricCard
          label="Overall Accuracy"
          value={formatPercent(summary.overall_accuracy)}
          subtitle="Success rate"
        />
        <MetricCard
          label="System Brier"
          value={formatBrier(summary.overall_brier)}
          subtitle="Lower is better"
        />
        <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase tracking-widest mb-2">Best Agent</p>
          <p className="text-lg font-semibold text-emerald-400">
            {summary.best_agent ? (AGENT_LABELS[summary.best_agent as keyof typeof AGENT_LABELS] || summary.best_agent) : '—'}
          </p>
          <p className="text-xs text-slate-500 mt-1">{formatPercent(summary.best_agent_accuracy)}</p>
        </div>
        <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-4">
          <p className="text-xs text-slate-500 uppercase tracking-widest mb-2">Worst Agent</p>
          <p className="text-lg font-semibold text-red-400">
            {summary.worst_agent ? (AGENT_LABELS[summary.worst_agent as keyof typeof AGENT_LABELS] || summary.worst_agent) : '—'}
          </p>
          <p className="text-xs text-slate-500 mt-1">{formatPercent(summary.worst_agent_accuracy)}</p>
        </div>
      </div>

      {/* Accuracy Over Time Chart */}
      <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
        <h3 className="text-sm font-semibold text-slate-200 mb-4">Accuracy Over Time</h3>
        {chartData.length > 0 ? (
          <ResponsiveContainer width="100%" height={400}>
            <LineChart data={chartData} margin={{ top: 5, right: 30, left: 0, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1E293B" />
              <XAxis dataKey="date" stroke="#64748B" style={{ fontSize: '12px' }} />
              <YAxis stroke="#64748B" label={{ value: 'Accuracy %', angle: -90, position: 'insideLeft' }} style={{ fontSize: '12px' }} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1E293B', border: '1px solid #334155' }}
                labelStyle={{ color: '#94A3B8' }}
              />
              <Legend />
              <Line
                type="monotone"
                dataKey="cumulative"
                stroke="#3B82F6"
                dot={false}
                name="Cumulative Accuracy"
                strokeWidth={2}
              />
              <Line
                type="monotone"
                dataKey="rolling_7d"
                stroke="#10B981"
                dot={false}
                name="7-Day Rolling"
                strokeWidth={2}
              />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="h-[400px] flex items-center justify-center text-slate-500">
            No data available
          </div>
        )}
      </div>

      {/* Agent Comparison Table */}
      <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5 overflow-x-auto">
        <h3 className="text-sm font-semibold text-slate-200 mb-4">Agent Performance</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-widest">Agent</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-widest">Resolved</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-widest">Correct</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-widest">Accuracy</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-widest">Brier Score</th>
            </tr>
          </thead>
          <tbody>
            {agentStats.map((stat) => (
              <tr key={stat.agent} className="border-b border-slate-800/50 hover:bg-surface-600/30 transition-colors">
                <td className="px-4 py-3 text-slate-300">
                  {AGENT_LABELS[stat.agent as keyof typeof AGENT_LABELS] || stat.agent}
                </td>
                <td className="px-4 py-3 text-right text-slate-400">{stat.resolved}</td>
                <td className="px-4 py-3 text-right text-slate-400">{stat.correct}</td>
                <td className={`px-4 py-3 text-right font-semibold ${getAccuracyColor(stat.accuracy)}`}>
                  {formatPercent(stat.accuracy)}
                </td>
                <td className="px-4 py-3 text-right text-slate-400">
                  {formatBrier(stat.brier)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* Domain Breakdown Table */}
      <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5 overflow-x-auto">
        <h3 className="text-sm font-semibold text-slate-200 mb-4">Domain Performance</h3>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50">
              <th className="px-4 py-3 text-left text-xs font-medium text-slate-400 uppercase tracking-widest">Domain</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-widest">Resolved</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-widest">Correct</th>
              <th className="px-4 py-3 text-right text-xs font-medium text-slate-400 uppercase tracking-widest">Accuracy</th>
            </tr>
          </thead>
          <tbody>
            {domainStats.map((stat) => (
              <tr key={stat.domain} className={`border-b border-slate-800/50 hover:bg-surface-600/30 transition-colors ${getAccuracyBg(stat.accuracy)}`}>
                <td className="px-4 py-3 text-slate-300 capitalize">{stat.domain}</td>
                <td className="px-4 py-3 text-right text-slate-400">{stat.resolved}</td>
                <td className="px-4 py-3 text-right text-slate-400">{stat.correct}</td>
                <td className={`px-4 py-3 text-right font-semibold ${getAccuracyColor(stat.accuracy)}`}>
                  {formatPercent(stat.accuracy)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
