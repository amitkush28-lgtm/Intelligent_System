'use client';

interface MetricCardProps {
  label: string;
  value: string;
  subtitle?: string;
  trend?: 'up' | 'down' | 'neutral';
  icon?: React.ReactNode;
}

export default function MetricCard({ label, value, subtitle, trend, icon }: MetricCardProps) {
  return (
    <div className="bg-surface-700/50 border border-slate-700/50 rounded-xl p-5 hover:border-slate-600/50 transition-colors">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-wider text-slate-500 mb-1">
            {label}
          </p>
          <p className="text-2xl font-semibold text-slate-100 tracking-tight">{value}</p>
          {subtitle && (
            <p className="text-xs text-slate-500 mt-1">{subtitle}</p>
          )}
        </div>
        {icon && (
          <div className="text-slate-600 text-xl">{icon}</div>
        )}
      </div>
    </div>
  );
}
