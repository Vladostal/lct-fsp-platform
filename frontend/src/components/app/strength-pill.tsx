import { STRENGTH_LABELS, type StrengthLabel } from '@/content/common'
import { cn } from '@/lib/utils'
import { SoftPill } from './soft-pill'
import type { Tone } from './tone'

const STRENGTH: Record<StrengthLabel, { bars: number; tone: Tone; fill: string }> = {
  high: { bars: 3, tone: 'success', fill: 'bg-success' },
  medium: { bars: 2, tone: 'brand', fill: 'bg-brand-600' },
  base: { bars: 1, tone: 'neutral', fill: 'bg-ink-muted' },
}

export type StrengthPillProps = {
  strength: StrengthLabel
  size?: 'sm' | 'md'
  className?: string
}

/**
 * Сила профиля — одинаково у кандидата и работодателя: три столбика и одно слово, тон по уровню.
 * Полное название — в подсказке и для скринридера.
 */
export function StrengthPill({ strength, size = 'sm', className }: StrengthPillProps) {
  const s = STRENGTH[strength]
  return (
    <SoftPill tone={s.tone} size={size} title={`Сила профиля: ${STRENGTH_LABELS[strength]}`} className={className}>
      <span aria-hidden="true" className="flex items-end gap-0.5">
        {[0, 1, 2].map((n) => (
          <span
            key={n}
            className={cn('w-1 rounded-full', n < s.bars ? s.fill : 'bg-line-strong')}
            style={{ height: 6 + n * 3 }}
          />
        ))}
      </span>
      <span className="sr-only">Сила профиля: </span>
      <span className={cn('font-medium', size === 'sm' && 'text-xs')}>{STRENGTH_LABELS[strength]}</span>
    </SoftPill>
  )
}
