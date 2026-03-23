'use client';

import { useEffect, useState, useCallback } from 'react';
import Link from 'next/link';
import { getDebates } from '@/lib/api';
import { DebateResponse, PaginatedResponse } from '@/lib/types';
import Pagination from '@/components/common/Pagination';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import {
  AGENT_LABELS,
  getAgentBgClass,
  formatDateTime,
} from '@/lib/utils';

export default function DebatesPage() {
  const [data, setData] = useState<PaginatedResponse<DebateResponse> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [agent, setAgent] = useState('');
  const [page, setPage] = useState(1);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getDebates({
        agent: agent || undefined,
        page,
        page_size: 20,
      });
      setData(result);
      setError(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [agent, page]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const toggle = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const selectClass =
    'bg-surface-700 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-blue-500/50 transition-colors';

  return (
    <div className="space-y-5 animate-fadeIn">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Debates</h1>
        <p className="text-xs text-slate-500 mt-0.5">Devil&apos;s advocate challenges</p>
      </div>

      <div className="flex items-center gap-3">
        <select value={agent} onChange={(e) => { setAgent(e.target.value); setPage(1); }} className={selectClass}>
          <option value="">All agents</option>
          {['geopolitical', 'economist', 'investor', 'political', 'sentiment', 'master'].map((a) => (
            <option key={a} value={a}>{AGENT_LABELS[a] || a}</option>
          ))}
        </select>
      </div>

      {loading ? (
        <LoadingSpinner />
      ) : error ? (
        <div className="py-10 text-center text-sm text-red-400">{error}</div>
      ) : data && data.items.length === 0 ? (
        <div className="py-10 text-center text-sm text-slate-500">No debates found</div>
      ) : (
        <div className="space-y-2">
          {data?.items.map((d) => (
            <div
              key={d.id}
              className="bg-surface-700/50 border border-slate-700/50 rounded-xl overflow-hidden"
            >
              <button
                onClick={() => toggle(d.id)}
                className="w-full flex items-center justify-between p-4 text-left hover:bg-surface-700/80 transition-colors"
              >
                <div className="flex items-center gap-3">
                  <span className="text-red-400">&#x2694;</span>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full ${getAgentBgClass(d.agent)}`}>
                    {AGENT_LABELS[d.agent] || d.agent}
                  </span>
                  <span className="text-sm text-slate-300">{d.trigger_reason}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-slate-500">
                  {d.devil_impact != null && (
                    <span className="font-mono">{(d.devil_impact * 100).toFixed(1)}pp</span>
                  )}
                  <span>{formatDateTime(d.created_at)}</span>
                  {d.prediction_id && (
                    <Link
                      href={`/predictions/${encodeURIComponent(d.prediction_id)}`}
                      onClick={(e) => e.stopPropagation()}
                      className="text-blue-400 hover:underline"
                    >
                      Prediction
                    </Link>
                  )}
                  <span className="text-slate-600">{expanded.has(d.id) ? '\u25B2' : '\u25BC'}</span>
                </div>
              </button>
              {expanded.has(d.id) && d.rounds && Array.isArray(d.rounds) && (
                <div className="px-4 pb-4 space-y-3">
                  {d.rounds.map((round: any, ri: number) => (
                    <div key={ri} className="space-y-2 ml-6">
                      {round.advocate && (
                        <div className="pl-3 border-l-2 border-blue-500/30">
                          <p className="text-[10px] text-blue-400 uppercase tracking-wider mb-1">Advocate</p>
                          <p className="text-xs text-slate-300 whitespace-pre-wrap">
                            {typeof round.advocate === 'string' ? round.advocate : round.advocate.text}
                          </p>
                        </div>
                      )}
                      {round.devil && (
                        <div className="pl-3 border-l-2 border-red-500/30">
                          <p className="text-[10px] text-red-400 uppercase tracking-wider mb-1">Devil&apos;s Advocate</p>
                          <p className="text-xs text-slate-300 whitespace-pre-wrap">
                            {typeof round.devil === 'string' ? round.devil : round.devil.text}
                          </p>
                        </div>
                      )}
                      {round.resolution && (
                        <div className="pl-3 border-l-2 border-emerald-500/30">
                          <p className="text-[10px] text-emerald-400 uppercase tracking-wider mb-1">Resolution</p>
                          <p className="text-xs text-slate-300 whitespace-pre-wrap">
                            {typeof round.resolution === 'string' ? round.resolution : round.resolution.text}
                          </p>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
          {data && (
            <Pagination page={data.page} pageSize={data.page_size} total={data.total} onPageChange={setPage} />
          )}
        </div>
      )}
    </div>
  );
}
