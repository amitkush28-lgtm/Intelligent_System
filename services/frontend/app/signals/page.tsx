'use client';

import { useEffect, useState, useCallback } from 'react';
import { getWeakSignals } from '@/lib/api';
import { WeakSignalResponse, PaginatedResponse } from '@/lib/types';
import StrengthBadge from '@/components/common/StrengthBadge';
import Pagination from '@/components/common/Pagination';
import LoadingSpinner from '@/components/common/LoadingSpinner';
import { parseSignalType, stripSignalPrefix, formatDateTime } from '@/lib/utils';

export default function SignalsPage() {
  const [data, setData] = useState<PaginatedResponse<WeakSignalResponse> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [strength, setStrength] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const result = await getWeakSignals({
        strength: strength || undefined,
        status: status || undefined,
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
  }, [strength, status, page]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const selectClass =
    'bg-surface-700 border border-slate-700/50 rounded-lg px-3 py-2 text-xs text-slate-300 focus:outline-none focus:border-blue-500/50 transition-colors';

  return (
    <div className="space-y-5 animate-fadeIn">
      <div>
        <h1 className="text-xl font-semibold text-slate-100">Weak Signals</h1>
        <p className="text-xs text-slate-500 mt-0.5">Orphans, anomalies, pre-mortems, convergences, and red team findings</p>
      </div>

      <div className="flex items-center gap-3">
        <select value={strength} onChange={(e) => { setStrength(e.target.value); setPage(1); }} className={selectClass}>
          <option value="">All strengths</option>
          <option value="HIGH">HIGH</option>
          <option value="MEDIUM">MEDIUM</option>
          <option value="LOW">LOW</option>
        </select>
        <select value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }} className={selectClass}>
          <option value="">All statuses</option>
          <option value="unattributed">Unattributed</option>
          <option value="investigating">Investigating</option>
          <option value="attributed">Attributed</option>
        </select>
      </div>

      {loading ? (
        <LoadingSpinner />
      ) : error ? (
        <div className="py-10 text-center text-sm text-red-400">{error}</div>
      ) : data && data.items.length === 0 ? (
        <div className="py-10 text-center text-sm text-slate-500">No signals found</div>
      ) : (
        <div className="space-y-2">
          {data?.items.map((s) => {
            const signalType = parseSignalType(s.signal);
            return (
              <div
                key={s.id}
                className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-4"
              >
                <div className="flex items-start justify-between gap-4">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`text-[10px] px-2 py-0.5 rounded-full font-semibold ${signalType.bgClass}`}>
                        {signalType.label}
                      </span>
                      <StrengthBadge strength={s.strength} />
                      {s.status && (
                        <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-500/15 text-slate-400">
                          {s.status}
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-slate-300 leading-relaxed">
                      {stripSignalPrefix(s.signal)}
                    </p>
                  </div>
                  <div className="text-right flex-shrink-0">
                    <p className="text-[10px] text-slate-500">{formatDateTime(s.detected_at)}</p>
                    {s.attributed_to && (
                      <p className="text-[10px] text-slate-600 mt-0.5">
                        Attributed: {s.attributed_to}
                      </p>
                    )}
                  </div>
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
