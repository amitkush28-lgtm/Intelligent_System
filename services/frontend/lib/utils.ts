import { AgentName, PredictionStatus, SignalStrength, Urgency } from './types';

// ============================================
// DATE FORMATTING
// ============================================

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const d = new Date(dateStr);
  return d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return '—';
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diff = now - then;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 30) return `${days}d ago`;
  return formatDate(dateStr);
}

// ============================================
// NUMBER FORMATTING
// ============================================

export function formatPercent(value: number | null | undefined): string {
  if (value == null) return '—';
  return `${(value * 100).toFixed(1)}%`;
}

export function formatBrier(value: number | null | undefined): string {
  if (value == null) return '—';
  return value.toFixed(3);
}

export function formatConfidence(value: number): string {
  return `${(value * 100).toFixed(0)}%`;
}

// ============================================
// STATUS COLORS
// ============================================

export const STATUS_COLORS: Record<string, { bg: string; text: string; dot: string }> = {
  ACTIVE: { bg: 'bg-blue-500/15', text: 'text-blue-400', dot: 'bg-blue-400' },
  RESOLVED_TRUE: { bg: 'bg-emerald-500/15', text: 'text-emerald-400', dot: 'bg-emerald-400' },
  RESOLVED_FALSE: { bg: 'bg-red-500/15', text: 'text-red-400', dot: 'bg-red-400' },
  EXPIRED: { bg: 'bg-gray-500/15', text: 'text-gray-400', dot: 'bg-gray-400' },
  SUPERSEDED: { bg: 'bg-amber-500/15', text: 'text-amber-400', dot: 'bg-amber-400' },
};

export const STATUS_HEX: Record<string, string> = {
  ACTIVE: '#3B82F6',
  RESOLVED_TRUE: '#10B981',
  RESOLVED_FALSE: '#EF4444',
  EXPIRED: '#6B7280',
  SUPERSEDED: '#F59E0B',
};

// ============================================
// AGENT COLORS
// ============================================

export const AGENT_COLORS: Record<string, string> = {
  geopolitical: '#8B5CF6',
  economist: '#3B82F6',
  investor: '#10B981',
  political: '#EF4444',
  sentiment: '#F59E0B',
  master: '#6366F1',
};

export const AGENT_LABELS: Record<string, string> = {
  geopolitical: 'Geopolitical',
  economist: 'Economist',
  investor: 'Investor',
  political: 'Political',
  sentiment: 'Sentiment',
  master: 'Master Strategist',
};

export const AGENT_ICONS: Record<string, string> = {
  geopolitical: '\u{1F30D}',
  economist: '\u{1F4CA}',
  investor: '\u{1F4B9}',
  political: '\u{1F3DB}',
  sentiment: '\u{1F4E1}',
  master: '\u{1F9E0}',
};

export function getAgentColor(agent: string): string {
  return AGENT_COLORS[agent] || '#6B7280';
}

export function getAgentBgClass(agent: string): string {
  const map: Record<string, string> = {
    geopolitical: 'bg-purple-500/15 text-purple-400',
    economist: 'bg-blue-500/15 text-blue-400',
    investor: 'bg-emerald-500/15 text-emerald-400',
    political: 'bg-red-500/15 text-red-400',
    sentiment: 'bg-amber-500/15 text-amber-400',
    master: 'bg-indigo-500/15 text-indigo-400',
  };
  return map[agent] || 'bg-gray-500/15 text-gray-400';
}

// ============================================
// SIGNAL STRENGTH COLORS
// ============================================

export const STRENGTH_COLORS: Record<string, { bg: string; text: string }> = {
  HIGH: { bg: 'bg-red-500/15', text: 'text-red-400' },
  MEDIUM: { bg: 'bg-amber-500/15', text: 'text-amber-400' },
  LOW: { bg: 'bg-blue-500/15', text: 'text-blue-400' },
};

// ============================================
// URGENCY COLORS
// ============================================

export const URGENCY_COLORS: Record<string, { bg: string; text: string }> = {
  PREP_NOW: { bg: 'bg-red-500/15', text: 'text-red-400' },
  HIGH: { bg: 'bg-orange-500/15', text: 'text-orange-400' },
  MEDIUM: { bg: 'bg-amber-500/15', text: 'text-amber-400' },
  LOW: { bg: 'bg-blue-500/15', text: 'text-blue-400' },
};

// ============================================
// SIGNAL TYPE PARSING
// ============================================

export interface SignalType {
  label: string;
  color: string;
  bgClass: string;
}

export function parseSignalType(signal: string): SignalType {
  if (signal.startsWith('[ORPHAN]'))
    return { label: 'ORPHAN', color: '#F59E0B', bgClass: 'bg-amber-500/15 text-amber-400' };
  if (signal.startsWith('[ANOMALY:'))
    return { label: signal.match(/\[ANOMALY:([^\]]+)\]/)?.[1] || 'ANOMALY', color: '#EF4444', bgClass: 'bg-red-500/15 text-red-400' };
  if (signal.startsWith('[PRE-MORTEM]'))
    return { label: 'PRE-MORTEM', color: '#8B5CF6', bgClass: 'bg-purple-500/15 text-purple-400' };
  if (signal.startsWith('[CONVERGENCE]'))
    return { label: 'CONVERGENCE', color: '#10B981', bgClass: 'bg-emerald-500/15 text-emerald-400' };
  if (signal.startsWith('[DIVERGENCE]'))
    return { label: 'DIVERGENCE', color: '#F97316', bgClass: 'bg-orange-500/15 text-orange-400' };
  if (signal.startsWith('[RED_TEAM:'))
    return { label: signal.match(/\[RED_TEAM:([^\]]+)\]/)?.[1] || 'RED_TEAM', color: '#EF4444', bgClass: 'bg-red-500/15 text-red-400' };
  return { label: 'SIGNAL', color: '#6B7280', bgClass: 'bg-gray-500/15 text-gray-400' };
}

export function stripSignalPrefix(signal: string): string {
  return signal.replace(/^\[[^\]]+\]\s*/, '');
}

// ============================================
// NOTE TYPE
// ============================================

export const NOTE_TYPE_COLORS: Record<string, string> = {
  observation: 'bg-blue-500/15 text-blue-400',
  key_signal: 'bg-emerald-500/15 text-emerald-400',
  counter_signal: 'bg-red-500/15 text-red-400',
  analysis: 'bg-purple-500/15 text-purple-400',
};

// ============================================
// TRUNCATION
// ============================================

export function truncate(str: string, len: number): string {
  if (str.length <= len) return str;
  return str.slice(0, len) + '...';
}
