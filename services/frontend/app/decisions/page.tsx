'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { getDecisions } from '@/lib/api';
import { DecisionResponse, PaginatedResponse } from '@/lib/types';
import Pagination from '@/components/common/Pagination';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import StatusBadge from '@/components/common/StatusBadge';
import { URGENCY_COLORS, formatConfidence } from '@/lib/utils';

const URGENCY_ORDER = ['PREP_NOW', 'HIGH', 'MEDIUM', 'LOW'];

export default function DecisionsPage() {
  const [data, setData] = useState<PaginatedResponse<DecisionResponse> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [urgency, setUrgency] = useState('');
  const [domain, setDomain] = useState('');
  const [page, setPage] = useState(1);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getDecisions({
        urgency: urgency || undefined,
        domain: domain || undefined,
        page,
        page_size: 30,
      });
      setData(result);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [urgency, domain, page]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Sort by urgency
  const sorted = data
    ? [...data.items].sort(
        (a, b) =>
          URGENCY_ORDER.indexOf(a.urgency || 'LOW') -
          URGENCY_ORDER.indexOf(b.urgency || 'LOW')
      )
    : [];

  const selectClass =
    'bg-surface-700 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-blue-500/50 transition-colors';

  return (
    <div className="space-y-5 animate-fadeIn">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Decisions</h1>
        <p className="text-xs text-slate-500 mt-0.5">Decision-relevance map ranked by urgency</p>
      </div>

      <div className="flex items-center gap-3">
        <select value={urgency} onChange={(e) => { setUrgency(e.target.value); setPage(1); }} className={selectClass}>
          <option value="">All urgencies</option>
          {URGENCY_ORDER.map((u) => (
            <option key={u} value={u}>{u.replace(/_/g, ' ')}</option>
          ))}
        </select>
        <select value={domain} onChange={(e) => { setDomain(e.target.value); setPage(1); }} className={selectClass}>
          <option value="">All domains</option>
          {['portfolio', 'business', 'risk', 'strategy'].map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <LoadingSpinner />
      ) : error ? (
        <div className="py-10 text-center text-sm text-red-400">{error}</div>
      ) : sorted.length === 0 ? (
        <div className="py-10 text-center text-sm text-slate-500">No decisions found</div>
      ) : (
        <div className="space-y-2">
          {sorted.map((d) => {
            const uColors = URGENCY_COLORS[d.urgency || 'LOW'] || URGENCY_COLORS.LOW;
            return (
              <div
                key={d.id}
                className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`text-[10px] px-2.5 py-0.5 rounded-full font-semibold ${uColors.bg} ${uColors.text}`}>
                        {(d.urgency || 'LOW').replace(/_/g, ' ')}
                      </span>
                      {d.domain && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-500/15 text-slate-400">
                          {d.domain}
                        </span>
                      )}
                    </div>
                    <p className="text-sm font-medium text-slate-200 mb-1">{d.action}</p>
                    <p className="text-xs text-slate-400">
                      Trigger: {d.trigger_condition}
                    </p>
                    {d.inert_threshold != null && (
                      <p className="text-xs text-slate-500 mt-1">
                        Inert below: {formatConfidence(d.inert_threshold)}
                      </p>
                    )}
                  </div>
                  {d.prediction && (
                    <Link
                      href={`/predictions/${encodeURIComponent(d.prediction.id)}`}
                      className="flex-shrink-0 bg-surface-800/50 rounded-lg p-3 hover:bg-surface-600/50 transition-colors text-right"
                    >
                      <p className="text-xs text-slate-500 mb-1">Linked Prediction</p>
                      <p className="text-sm font-mono text-blue-400">
                        {formatConfidence(d.prediction.current_confidence)}
                      </p>
                      <StatusBadge status={d.prediction.status} />
                    </Link>
                  )}
                </div>
              </div>
            );
          })}
          {data && (
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
          )}
        </div>
      )}
    </div>
  );
}
