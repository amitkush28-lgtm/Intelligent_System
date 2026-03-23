'use client';

import Link from 'next/link';
import { PredictionResponse } from '@/lib/types';
import StatusBadge from '@/components/common/StatusBadge';
import { formatDate, formatConfidence, getAgentBgClass, AGENT_LABELS, truncate } from '@/lib/utils';

export default function PredictionCard({ prediction }: { prediction: PredictionResponse }) {
  return (
    <Link
      href={`/predictions/${encodeURIComponent(prediction.id)}`}
      className="block bg-surface-700/50 border border-slate-700/50 rounded-xl p-4 hover:border-slate-600/60 transition-all hover:translate-y-[-1px]"
    >
      <div className="flex items-start justify-between gap-3 mb-2">
        <span className={`text-[10px] px-2 py-0.5 rounded-full ${getAgentBgClass(prediction.agent)}`}>
          {AGENT_LABELS[prediction.agent] || prediction.agent}
        </span>
        <StatusBadge status={prediction.status} />
      </div>
      <p className="text-sm text-slate-200 leading-relaxed mb-3">
        {truncate(prediction.claim, 120)}
      </p>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-20 h-1.5 bg-surface-600 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full"
              style={{ width: `${prediction.current_confidence * 100}%` }}
            />
          </div>
          <span className="text-xs text-slate-300 font-mono">
            {formatConfidence(prediction.current_confidence)}
          </span>
        </div>
        <span className="text-[10px] text-slate-500">{formatDate(prediction.created_at)}</span>
      </div>
    </Link>
  );
}
