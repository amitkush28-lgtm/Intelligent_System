'use client';

import { useEffect, useState } from 'react';
import {
  getDashboardMetrics,
  getCalibrationCurve,
  triggerIngestion,
  triggerAgents,
  triggerFeedback,
  triggerSignals,
} from '@/lib/api';
import { DashboardMetrics, CalibrationCurveResponse } from '@/lib/types';
import MetricCard from '@/components/layout/MetricCard';
import CalibrationChart from '@/components/charts/CalibrationChart';
import AgentCard from '@/components/agents/AgentCard';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import StatusBadge from '@/components/common/StatusBadge';
import {
  formatBrier,
  formatPercent,
  timeAgo,
  AGENT_LABELS,
  getAgentBgClass,
} from '@/lib/utils';

type TriggerStatus = 'idle' | 'running' | 'done' | 'error';

interface PipelineStep {
  label: string;
  trigger: () => Promise<any>;
  status: TriggerStatus;
  message?: string;
}

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [calibration, setCalibration] = useState<CalibrationCurveResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [steps, setSteps] = useState<PipelineStep[]>([
    { label: 'Ingest Data', trigger: triggerIngestion, status: 'idle' },
    { label: 'Run Agents', trigger: triggerAgents, status: 'idle' },
    { label: 'Run Feedback', trigger: triggerFeedback, status: 'idle' },
    { label: 'Scan Signals', trigger: triggerSignals, status: 'idle' },
  ]);
  const [pipelineRunning, setPipelineRunning] = useState(false);

  useEffect(() => {
    loadDashboard();
  }, []);

  async function loadDashboard() {
    try {
      const [m, c] = await Promise.all([
        getDashboardMetrics(),
        getCalibrationCurve(),
      ]);
      setMetrics(m);
      setCalibration(c);
      setError(null);
    } catch (e: any) {
      setError(e.message || 'Failed to load dashboard');
    }
  }

  function updateStep(index: number, updates: Partial<PipelineStep>) {
    setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, ...updates } : s)));
  }

  async function runSingleStep(index: number) {
    const step = steps[index];
    updateStep(index, { status: 'running', message: undefined });
    try {
      const result = await step.trigger();
      updateStep(index, { status: 'done', message: result.message });
    } catch (e: any) {
      updateStep(index, { status: 'error', message: e.message });
    }
  }

  async function runFullPipeline() {
    setPipelineRunning(true);
    for (let i = 0; i < steps.length; i++) {
      updateStep(i, { status: 'running', message: undefined });
      try {
        const result = await steps[i].trigger();
        updateStep(i, { status: 'done', message: result.message });
        // Wait a moment between steps to let background tasks start
        await new Promise((r) => setTimeout(r, 2000));
      } catch (e: any) {
        updateStep(i, { status: 'error', message: e.message });
      }
    }
    setPipelineRunning(false);
    // Refresh dashboard after pipeline
    setTimeout(loadDashboard, 5000);
  }

  function resetPipeline() {
    setSteps((prev) => prev.map((s) => ({ ...s, status: 'idle' as TriggerStatus, message: undefined })));
  }

  const statusIcon = (status: TriggerStatus) => {
    switch (status) {
      case 'idle': return <span className="text-slate-600">&#x25CB;</span>;
      case 'running': return <span className="text-blue-400 animate-spin inline-block">&#x25E0;</span>;
      case 'done': return <span className="text-emerald-400">&#x2713;</span>;
      case 'error': return <span className="text-red-400">&#x2717;</span>;
    }
  };

  if (error && !metrics) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="text-red-400 text-sm font-medium">Connection Error</div>
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

  if (!metrics) return <LoadingSpinner text="Loading dashboard..." />;

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-slate-100">Dashboard</h1>
          <p className="text-xs text-slate-500 mt-0.5">System-wide intelligence overview</p>
        </div>
        <div className="text-[10px] text-slate-600 uppercase tracking-widest">
          Live
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-emerald-500 ml-1.5 animate-pulse-soft" />
        </div>
      </div>

      {/* Pipeline Control Panel */}
      <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold text-slate-200">Pipeline Control</h3>
          <div className="flex gap-2">
            <button
              onClick={runFullPipeline}
              disabled={pipelineRunning}
              className="text-xs px-4 py-2 rounded-lg bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              {pipelineRunning ? 'Running...' : 'Run Full Pipeline'}
            </button>
            <button
              onClick={resetPipeline}
              disabled={pipelineRunning}
              className="text-xs px-3 py-2 rounded-lg bg-surface-600 text-slate-300 hover:bg-surface-500 disabled:opacity-50 transition-colors"
            >
              Reset
            </button>
            <button
              onClick={loadDashboard}
              className="text-xs px-3 py-2 rounded-lg bg-surface-600 text-slate-300 hover:bg-surface-500 transition-colors"
            >
              Refresh Data
            </button>
          </div>
        </div>
        <div className="grid grid-cols-4 gap-3">
          {steps.map((step, i) => (
            <div
              key={step.label}
              className="bg-surface-800/50 border border-slate-700/30 rounded-lg p-3"
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="text-sm">{statusIcon(step.status)}</span>
                  <span className="text-xs font-medium text-slate-300">{step.label}</span>
                </div>
                <button
                  onClick={() => runSingleStep(i)}
                  disabled={pipelineRunning || step.status === 'running'}
                  className="text-[10px] px-2 py-1 rounded bg-surface-600 text-slate-400 hover:bg-surface-500 hover:text-slate-200 disabled:opacity-30 transition-colors"
                >
                  Run
                </button>
              </div>
              {step.message && (
                <p className={`text-[10px] truncate ${step.status === 'error' ? 'text-red-400' : 'text-slate-500'}`}>
                  {step.message}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Top metrics */}
      <div className="grid grid-cols-5 gap-4">
        <MetricCard
          label="System Brier"
          value={formatBrier(metrics.system_brier_score)}
          subtitle="Lower is better"
        />
        <MetricCard
          label="Accuracy"
          value={formatPercent(metrics.overall_accuracy)}
          subtitle="Resolved predictions"
        />
        <MetricCard
          label="Active"
          value={String(metrics.active_predictions)}
          subtitle="Predictions being tracked"
        />
        <MetricCard
          label="Total"
          value={String(metrics.total_predictions)}
          subtitle="All-time predictions"
        />
        <MetricCard
          label="Cal. Error"
          value={formatBrier(metrics.calibration_error)}
          subtitle="Avg bucket deviation"
        />
      </div>

      {/* Calibration chart + Activity */}
      <div className="grid grid-cols-3 gap-4">
        <div className="col-span-2">
          {calibration ? (
            <CalibrationChart data={calibration} />
          ) : (
            <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5 h-[400px] flex items-center justify-center text-sm text-slate-500">
              No calibration data yet
            </div>
          )}
        </div>
        <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5 max-h-[400px] overflow-y-auto">
          <h3 className="text-sm font-semibold text-slate-200 mb-3">Recent Activity</h3>
          {metrics.recent_activity.length === 0 ? (
            <p className="text-xs text-slate-500">No recent activity. Run the pipeline to get started.</p>
          ) : (
            <div className="space-y-2.5">
              {metrics.recent_activity.slice(0, 15).map((item, i) => (
                <div
                  key={i}
                  className="flex items-start gap-2.5 text-xs border-b border-slate-800/50 pb-2.5 last:border-0"
                >
                  <div className="mt-0.5">
                    {item.type === 'confidence_update' && (
                      <span className="text-blue-400">&#x25B2;</span>
                    )}
                    {item.type === 'note' && (
                      <span className="text-amber-400">&#x270E;</span>
                    )}
                    {item.type === 'debate' && (
                      <span className="text-red-400">&#x2694;</span>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    {item.type === 'confidence_update' && (
                      <p className="text-slate-300">
                        Confidence updated to{' '}
                        <span className="text-blue-400 font-mono">
                          {((item.value || 0) * 100).toFixed(0)}%
                        </span>
                        <span className="text-slate-600"> &middot; {item.trigger}</span>
                      </p>
                    )}
                    {item.type === 'note' && (
                      <p className="text-slate-300 truncate">{item.text}</p>
                    )}
                    {item.type === 'debate' && (
                      <p className="text-slate-300">
                        <span className={`${getAgentBgClass(item.agent || '')} px-1.5 py-0.5 rounded text-[10px]`}>
                          {AGENT_LABELS[item.agent || ''] || item.agent}
                        </span>{' '}
                        {item.trigger_reason}
                      </p>
                    )}
                    <p className="text-slate-600 mt-0.5">{timeAgo(item.timestamp)}</p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Agent cards */}
      <div>
        <h3 className="text-sm font-semibold text-slate-200 mb-3">Agent Performance</h3>
        <div className="grid grid-cols-3 gap-4">
          {metrics.agents.map((a) => (
            <AgentCard key={a.agent} agent={a} />
          ))}
        </div>
      </div>
    </div>
  );
}
