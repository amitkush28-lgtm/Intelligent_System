'use client';

import { useEffect, useState, useCallback } from 'react';
import { getPredictions } from '@/lib/api';
import { PredictionResponse, PaginatedResponse } from '@/lib/types';
import PredictionTable from '@/components/predictions/PredictionTable';
import Pagination from '@/components/common/Pagination';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { AGENT_LABELS } from '@/lib/utils';

const STATUSES = ['', 'ACTIVE', 'RESOLVED_TRUE', 'RESOLVED_FALSE', 'EXPIRED', 'SUPERSEDED'];
const AGENTS = ['', 'geopolitical', 'economist', 'investor', 'political', 'sentiment', 'master'];
const DOMAINS = ['', 'geopolitical', 'economic', 'market', 'political', 'sentiment'];

export default function PredictionsPage() {
  const [data, setData] = useState<PaginatedResponse<PredictionResponse> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState('');
  const [agent, setAgent] = useState('');
  const [domain, setDomain] = useState('');
  const [page, setPage] = useState(1);
  const [sortKey, setSortKey] = useState('created_at');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getPredictions({
        status: status || undefined,
        agent: agent || undefined,
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
  }, [status, agent, domain, page]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleSort = (key: string) => {
    if (sortKey === key) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

  // Client-side sort since API doesn't support sort params
  const sorted = data
    ? [...data.items].sort((a, b) => {
        let av: any, bv: any;
        if (sortKey === 'current_confidence') {
          av = a.current_confidence;
          bv = b.current_confidence;
        } else if (sortKey === 'created_at') {
          av = a.created_at || '';
          bv = b.created_at || '';
        } else if (sortKey === 'agent') {
          av = a.agent;
          bv = b.agent;
        } else if (sortKey === 'status') {
          av = a.status;
          bv = b.status;
        } else {
          av = a.claim;
          bv = b.claim;
        }
        if (av < bv) return sortDir === 'asc' ? -1 : 1;
        if (av > bv) return sortDir === 'asc' ? 1 : -1;
        return 0;
      })
    : [];

  const selectClass =
    'bg-surface-700 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-blue-500/50 transition-colors';

  return (
    <div className="space-y-5 animate-fadeIn">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Predictions</h1>
        <p className="text-xs text-slate-500 mt-0.5">All system predictions with filters</p>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3">
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className={selectClass}>
          <option value="">All statuses</option>
          {STATUSES.filter(Boolean).map((s) => (
            <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>
          ))}
        </select>
        <select value={agent} onChange={(e) => { setAgent(e.target.value); setPage(1); }} className={selectClass}>
          <option value="">All agents</option>
          {AGENTS.filter(Boolean).map((a) => (
            <option key={a} value={a}>{AGENT_LABELS[a] || a}</option>
          ))}
        </select>
        <select value={domain} onChange={(e) => { setDomain(e.target.value); setPage(1); }} className={selectClass}>
          <option value="">All domains</option>
          {DOMAINS.filter(Boolean).map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>
        {(status || agent || domain) && (
          <button
            onClick={() => { setStatus(''); setAgent(''); setDomain(''); setPage(1); }}
            className="text-xs text-slate-500 hover:text-slate-300 transition-colors"
          >
            Clear filters
          </button>
        )}
        <div className="flex-1" />
        <span className="text-xs text-slate-500">
          {data ? `${data.total} prediction${data.total !== 1 ? 's' : ''}` : ''}
        </span>
      </div>

      {/* Table */}
      <div className="bg-surface-700/30 border border-slate-700/50 rounded-xl overflow-hidden">
        {loading ? (
          <LoadingSpinner />
        ) : error ? (
          <div className="p-8 text-center text-sm text-red-400">{error}</div>
        ) : (
          <>
            <PredictionTable
              predictions={sorted}
              sortKey={sortKey}
              sortDir={sortDir}
              onSort={handleSort}
            />
            {data && (
              <div className="px-4 pb-3">
                <Pagination
                  page={data.page}
                  pageSize={data.page_size}
                  total={data.total}
                  onPageChange={setPage}
                />
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
