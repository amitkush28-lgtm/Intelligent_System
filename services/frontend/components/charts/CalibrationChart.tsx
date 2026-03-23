'use client';

import { useState } from 'react';
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceLine,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { CalibrationBucket, CalibrationCurveResponse } from '@/lib/types';
import { AGENT_COLORS, AGENT_LABELS } from '@/lib/utils';

interface CalibrationChartProps {
  data: CalibrationCurveResponse;
}

function bucketToNumber(bucket: string): number {
  const match = bucket.match(/(\d+)/);
  return match ? (parseInt(match[1]) + 5) / 100 : 0.5;
}

function formatData(buckets: CalibrationBucket[]) {
  return buckets.map((b) => ({
    predicted: b.predicted_avg,
    actual: b.actual_avg,
    bucket: b.bucket,
    count: b.count,
  }));
}

export default function CalibrationChart({ data }: CalibrationChartProps) {
  const agents = Object.keys(data.by_agent);
  const [visibleAgents, setVisibleAgents] = useState<Set<string>>(new Set());
  const showOverall = visibleAgents.size === 0;

  const toggleAgent = (agent: string) => {
    setVisibleAgents((prev) => {
      const next = new Set(prev);
      if (next.has(agent)) next.delete(agent);
      else next.add(agent);
      return next;
    });
  };

  const diagonal = Array.from({ length: 11 }, (_, i) => ({
    predicted: i / 10,
    actual: i / 10,
  }));

  return (
    <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-sm font-semibold text-slate-200">Calibration Curve</h3>
        <div className="flex items-center gap-2 flex-wrap">
          {agents.map((agent) => (
            <button
              key={agent}
              onClick={() => toggleAgent(agent)}
              className={`text-[10px] uppercase tracking-wider px-2 py-1 rounded-md transition-all ${
                visibleAgents.has(agent)
                  ? 'opacity-100 font-semibold'
                  : 'opacity-40 hover:opacity-70'
              }`}
              style={{ color: AGENT_COLORS[agent] || '#6B7280' }}
            >
              {AGENT_LABELS[agent] || agent}
            </button>
          ))}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={320}>
        <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="predicted"
            type="number"
            domain={[0, 1]}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            tick={{ fill: '#64748b', fontSize: 11 }}
            label={{ value: 'Predicted', position: 'insideBottom', offset: -10, fill: '#64748b', fontSize: 11 }}
          />
          <YAxis
            dataKey="actual"
            type="number"
            domain={[0, 1]}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            tick={{ fill: '#64748b', fontSize: 11 }}
            label={{ value: 'Actual', angle: -90, position: 'insideLeft', fill: '#64748b', fontSize: 11 }}
          />
          <Tooltip
            content={({ payload }) => {
              if (!payload?.length) return null;
              const d = payload[0].payload;
              return (
                <div className="bg-surface-800 border border-slate-700 rounded-lg px-3 py-2 text-xs">
                  <p className="text-slate-300">
                    Predicted: {(d.predicted * 100).toFixed(1)}%
                  </p>
                  <p className="text-slate-300">
                    Actual: {(d.actual * 100).toFixed(1)}%
                  </p>
                  <p className="text-slate-500">n={d.count}</p>
                </div>
              );
            }}
          />
          <ReferenceLine
            segment={[{ x: 0, y: 0 }, { x: 1, y: 1 }]}
            stroke="#334155"
            strokeDasharray="6 4"
            strokeWidth={1}
          />
          {showOverall && data.overall.length > 0 && (
            <Scatter
              name="Overall"
              data={formatData(data.overall)}
              fill="#3B82F6"
              line={{ stroke: '#3B82F6', strokeWidth: 2 }}
              lineType="fitting"
            />
          )}
          {[...visibleAgents].map((agent) => (
            <Scatter
              key={agent}
              name={AGENT_LABELS[agent] || agent}
              data={formatData(data.by_agent[agent] || [])}
              fill={AGENT_COLORS[agent] || '#6B7280'}
              line={{
                stroke: AGENT_COLORS[agent] || '#6B7280',
                strokeWidth: 2,
              }}
              lineType="fitting"
            />
          ))}
        </ScatterChart>
      </ResponsiveContainer>
      <p className="text-[10px] text-slate-600 mt-2 text-center">
        Dashed line = perfect calibration. Points above = underconfident. Points below = overconfident.
      </p>
    </div>
  );
}
