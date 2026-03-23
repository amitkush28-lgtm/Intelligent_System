'use client';

import { STRENGTH_COLORS } from '@/lib/utils';

interface StrengthBadgeProps {
  strength: string | null;
}

export default function StrengthBadge({ strength }: StrengthBadgeProps) {
  const s = strength || 'LOW';
  const colors = STRENGTH_COLORS[s] || STRENGTH_COLORS.LOW;

  return (
    <span
      className={`inline-flex items-center rounded-full text-xs font-semibold px-2.5 py-0.5 ${colors.bg} ${colors.text}`}
    >
      {s}
    </span>
  );
}
