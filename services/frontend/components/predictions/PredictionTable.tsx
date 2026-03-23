'use client';

import Link from 'next/link';
import { PredictionResponse } from '@/lib/types';
import StatusBadge from '@/components/common/StatusBadge';
import {
  formatDate,
  formatConfidence,
  truncate,
  getAgentBgClass,
  AGENT_LABELS,
} from '@/lib/utils';

interface PredictionTableProps {
  predictions: PredictionResponse[];
  sortKey?: string;
  sortDir?: 'asc' | 'desc';
  onSort?: (key: string) => void;
}

export default function PredictionTable({
  predictions,
  sortKey,
  sortDir,
  onSort,
}: PredictionTableProps) {
  const headers = [
    { key: 'claim', label: 'Claim' },
    { key: 'agent', label: 'Agent' },
    { key: 'current_confidence', label: 'Confidence' },
    { key: 'status', label: 'Status' },
    { key: 'created_at', label: 'Created' },
  ];

  const sortIcon = (key: string) => {
    if (sortKey !== key) return '';
    return sortDir === 'asc' ? ' \u2191' : ' \u2193';
  };

  if (predictions.length === 0) {
    return (
      <div className="text-center py-12 text-sm text-slate-500">
        No predictions found
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-700/50">
            {headers.map((h) => (
              <th
                key={h.key}
                onClick={() => onSort?.(h.key)}
                className="text-left py-3 px-3 text-[10px] uppercase tracking-wider text-slate-500 font-semibold cursor-pointer hover:text-slate-300 transition-colors"
              >
                {h.label}{sortIcon(h.key)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {predictions.map((p) => (
            <tr
              key={p.id}
              className="border-b border-slate-800/50 hover:bg-surface-700/30 transition-colors"
            >
              <td className="py-3 px-3 max-w-md">
                <Link
                  href={`/predictions/${encodeURIComponent(p.id)}`}
                  className="text-slate-200 hover:text-blue-400 transition-colors"
                >
                  {truncate(p.claim, 80)}
                </Link>
                <p className="text-[10px] text-slate-600 mt-0.5 font-mono">{p.id}</p>
              </td>
              <td className="py-3 px-3">
                <span
                  className={`inline-flex items-center text-xs px-2 py-0.5 rounded-full ${getAgentBgClass(p.agent)}`}
                >
                  {AGENT_LABELS[p.agent] || p.agent}
                </span>
              </td>
              <td className="py-3 px-3">
                <div className="flex items-center gap-2">
                  <div className="w-16 h-1.5 bg-surface-600 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-500 rounded-full"
                      style={{ width: `${p.current_confidence * 100}%` }}
                    />
                  </div>
                  <span className="text-slate-300 font-mono text-xs">
                    {formatConfidence(p.current_confidence)}
                  </span>
                </div>
              </td>
              <td className="py-3 px-3">
                <StatusBadge status={p.status} />
              </td>
              <td className="py-3 px-3 text-slate-400 text-xs">
                {formatDate(p.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
