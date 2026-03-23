'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import {
  getAgentMetrics,
  getCalibrationCurve,
  getPredictions,
  getDebates,
} from '@/lib/api';
import { AgentMetrics, CalibrationCurveResponse, PredictionResponse, DebateResponse, PaginatedResponse } from '@/lib/types';
import CalibrationChart from '@/components/charts/CalibrationChart';
import PredictionTable from '@/components/predictions/PredictionTable';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import {
  AGENT_LABELS,
  AGENT_ICONS,
  AGENT_COLORS,
  formatBrier,
  formatPercent,
  formatDateTime,
} from '@/lib/utils';

export default function AgentDetailPage() {
  const params = useParams();
  const agentId = params.id as string;
  const [metrics, setMetrics] = useState<AgentMetrics | null>(null);
  const [calibration, setCalibration] = useState<CalibrationCurveResponse | null>(null);
  const [predictions, setPredictions] = useState<PredictionResponse[]>([]);
  const [debates, setDebates] = useState<DebateResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function load() {
      try {
        const [m, cal, pred, deb] = await Promise.all([
          getAgentMetrics(agentId),
          getCalibrationCurve(),
          getPredictions({ agent: agentId, page_size: 20 }),
          getDebates({ agent: agentId, page_size: 10 }),
        ]);
        setMetrics(m);
        // Filter calibration to only show this agent
        setCalibration({
          overall: cal.by_agent[agentId] || [],
          by_agent: { [agentId]: cal.by_agent[agentId] || [] },
        });
        setPredictions(pred.items);
        setDebates(deb.items);
      } catch (e: any) {
        setError(e.message);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [agentId]);

  if (loading) return <LoadingSpinner text="Loading agent..." />;
  if (error || !metrics) {
    return (
      <div className="py-20 text-center">
        <p className="text-red-400 text-sm">{error || 'Agent not found'}</p>
        <Link href="/agents" className="text-xs text-blue-400 mt-2 inline-block hover:underline">
          Back to agents
        </Link>
      </div>
    );
  }

  const label = AGENT_LABELS[agentId] || agentId;
  const icon = AGENT_ICONS[agentId] || '\u2726';
  const color = AGENT_COLORS[agentId] || '#6B7280';

  return (
    <div className="space-y-6 animate-fadeIn">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Link href="/agents" className="hover:text-slate-300 transition-colors">Agents</Link>
        <span>/</span>
        <span className="text-slate-400">{label}</span>
      </div>

      {/* Header */}
      <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-6" style={{ borderTopColor: color, borderTopWidth: '2px' }}>
        <div className="flex items-center gap-3 mb-5">
          <span className="text-3xl">{icon}</span>
          <div>
            <h1 className="text-xl font-semibold text-slate-100">{label}</h1>
            <p className="text-xs text-slate-500">{agentId} agent</p>
          </div>
        </div>
        <div className="grid grid-cols-5 gap-4 text-sm">
          <div>
            <p className="text-slate-500 text-xs mb-0.5">Total Predictions</p>
            <p className="text-slate-200 font-semibold">{metrics.total_predictions}</p>
          </div>
          <div>
            <p className="text-slate-500 text-xs mb-0.5">Active</p>
            <p className="text-slate-200 font-semibold">{metrics.active_predictions}</p>
          </div>
          <div>
            <p className="text-slate-500 text-xs mb-0.5">Accuracy</p>
            <p className="text-slate-200 font-semibold">{formatPercent(metrics.accuracy)}</p>
          </div>
          <div>
            <p className="text-slate-500 text-xs mb-0.5">Brier Score</p>
            <p className="text-slate-200 font-semibold">{formatBrier(metrics.brier_avg)}</p>
          </div>
          <div>
            <p className="text-slate-500 text-xs mb-0.5">Calibration Error</p>
            <p className="text-slate-200 font-semibold">{formatBrier(metrics.calibration_error)}</p>
          </div>
        </div>
      </div>

      {/* Known Biases */}
      {metrics.known_biases.length > 0 && (
        <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-amber-400 mb-3">Known Biases</h3>
          <div className="space-y-2">
            {metrics.known_biases.map((b, i) => (
              <p key={i} className="text-sm text-slate-300">{b}</p>
            ))}
          </div>
        </div>
      )}

      {/* Calibration chart */}
      {calibration && calibration.overall.length > 0 && (
        <CalibrationChart data={calibration} />
      )}

      {/* Predictions */}
      <div className="bg-surface-700/30 border border-slate-700/50 rounded-xl overflow-hidden">
        <div className="px-5 pt-5 pb-2">
          <h3 className="text-sm font-semibold text-slate-200">
            Predictions ({predictions.length})
          </h3>
        </div>
        <PredictionTable predictions={predictions} />
      </div>

      {/* Debates */}
      {debates.length > 0 && (
        <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
          <h3 className="text-sm font-semibold text-slate-200 mb-4">
            Recent Debates ({debates.length})
          </h3>
          <div className="space-y-3">
            {debates.map((d) => (
              <div key={d.id} className="flex items-center justify-between p-3 rounded-lg bg-surface-800/50 text-sm">
                <div className="flex items-center gap-3">
                  <span className="text-red-400">&#x2694;</span>
                  <span className="text-slate-300">{d.trigger_reason}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-500">
                  {d.devil_impact != null && (
                    <span>Impact: {(d.devil_impact * 100).toFixed(1)}pp</span>
                  )}
                  <span>{formatDateTime(d.created_at)}</span>
                  {d.prediction_id && (
                    <Link href={`/predictions/${encodeURIComponent(d.prediction_id)}`} className="text-blue-400 hover:underline">
                      View
                    </Link>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
