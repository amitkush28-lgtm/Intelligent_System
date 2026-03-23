'use client';

import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import { ConfidenceTrailResponse } from '@/lib/types';
import { formatDateTime } from '@/lib/utils';

interface ConfidenceTrailChartProps {
  trail: ConfidenceTrailResponse[];
  height?: number;
}

export default function ConfidenceTrailChart({
  trail,
  height = 280,
}: ConfidenceTrailChartProps) {
  const data = trail.map((t) => ({
    date: t.date,
    value: t.value,
    trigger: t.trigger,
    reasoning: t.reasoning,
  }));

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center h-40 text-sm text-slate-500">
        No confidence history yet
      </div>
    );
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 10, right: 20, bottom: 10, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis
          dataKey="date"
          tickFormatter={(v: string) => {
            if (!v) return '';
            const d = new Date(v);
            return `${d.getMonth() + 1}/${d.getDate()}`;
          }}
          tick={{ fill: '#64748b', fontSize: 11 }}
        />
        <YAxis
          domain={[0, 1]}
          tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
          tick={{ fill: '#64748b', fontSize: 11 }}
        />
        <ReferenceLine y={0.5} stroke="#334155" strokeDasharray="4 4" />
        <Tooltip
          content={({ payload }) => {
            if (!payload?.length) return null;
            const d = payload[0].payload;
            return (
              <div className="bg-surface-800 border border-slate-700 rounded-lg px-3 py-2 text-xs max-w-xs">
                <p className="text-slate-200 font-medium">
                  {(d.value * 100).toFixed(1)}%
                </p>
                <p className="text-slate-400 mt-1">{formatDateTime(d.date)}</p>
                <p className="text-blue-400 mt-1">{d.trigger}</p>
                {d.reasoning && (
                  <p className="text-slate-500 mt-1 line-clamp-3">{d.reasoning}</p>
                )}
              </div>
            );
          }}
        />
        <Line
          type="monotone"
          dataKey="value"
          stroke="#3B82F6"
          strokeWidth={2}
          dot={{ fill: '#3B82F6', r: 3, strokeWidth: 0 }}
          activeDot={{ fill: '#60A5FA', r: 5, strokeWidth: 2, stroke: '#1e293b' }}
        />
      </LineChart>
    </ResponsiveContainer>
  );
}
