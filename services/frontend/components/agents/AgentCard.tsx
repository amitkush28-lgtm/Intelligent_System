'use client';

import Link from 'next/link';
import { AgentMetrics } from '@/lib/types';
import {
  AGENT_COLORS,
  AGENT_LABELS,
  AGENT_ICONS,
  formatBrier,
  formatPercent,
} from '@/lib/utils';

interface AgentCardProps {
  agent: AgentMetrics;
}

export default function AgentCard({ agent }: AgentCardProps) {
  const color = AGENT_COLORS[agent.agent] || '#6B7280';
  const label = AGENT_LABELS[agent.agent] || agent.agent;
  const icon = AGENT_ICONS[agent.agent] || '\u2726';

  return (
    <Link href={`/agents/${agent.agent}`} className="block group">
      <div
        className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/60 transition-all group-hover:translate-y-[-1px]"
        style={{ borderTopColor: color, borderTopWidth: '2px' }}
      >
        <div className="flex items-center gap-3 mb-4">
          <span className="text-2xl">{icon}</span>
          <div>
            <h3 className="text-sm font-semibold text-slate-200">{label}</h3>
            <p className="text-[10px] text-slate-500 uppercase tracking-wider">
              {agent.agent}
            </p>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3 text-xs">
          <div>
            <p className="text-slate-500 mb-0.5">Predictions</p>
            <p className="text-slate-200 font-medium">
              {agent.active_predictions} active / {agent.total_predictions} total
            </p>
          </div>
          <div>
            <p className="text-slate-500 mb-0.5">Accuracy</p>
            <p className="text-slate-200 font-medium">
              {formatPercent(agent.accuracy)}
            </p>
          </div>
          <div>
            <p className="text-slate-500 mb-0.5">Brier Score</p>
            <p className="text-slate-200 font-medium">
              {formatBrier(agent.brier_avg)}
            </p>
          </div>
          <div>
            <p className="text-slate-500 mb-0.5">Calibration Error</p>
            <p className="text-slate-200 font-medium">
              {formatBrier(agent.calibration_error)}
            </p>
          </div>
        </div>

        {agent.known_biases.length > 0 && (
          <div className="mt-3 pt-3 border-t border-slate-700/50">
            <p className="text-[10px] text-slate-500 uppercase tracking-wider mb-1.5">
              Known Biases
            </p>
            <div className="flex flex-wrap gap-1">
              {agent.known_biases.slice(0, 3).map((b, i) => (
                <span
                  key={i}
                  className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400"
                >
                  {b.length > 40 ? b.slice(0, 40) + '...' : b}
                </span>
              ))}
              {agent.known_biases.length > 3 && (
                <span className="text-[10px] text-slate-500">
                  +{agent.known_biases.length - 3} more
                </span>
              )}
            </div>
          </div>
        )}

        {agent.devil_impact_avg != null && (
          <div className="mt-3 pt-3 border-t border-slate-700/50 flex items-center justify-between text-xs">
            <span className="text-slate-500">Devil Impact Avg</span>
            <span className="text-slate-300 font-medium">
              {(agent.devil_impact_avg * 100).toFixed(1)}pp
            </span>
          </div>
        )}
      </div>
    </Link>
  );
}
