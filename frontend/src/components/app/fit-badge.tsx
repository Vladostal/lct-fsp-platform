import { ChevronsUp, ChevronUp, Gauge, Minus } from 'lucide-react'
import type { FitBand } from '@/client'
import { Badge } from '@/components/ui/badge'
import { FIT_BAND_LABELS, STRENGTH_LABELS, type StrengthLabel } from '@/content/common'

export type FitBadgeProps = {
  /** Полоса совпадения с потребностью; null — вне контекста потребности (банк). */
  band: FitBand | null
  /** Сила подтверждённого профиля — показывается, когда полосы нет. */
  strength?: StrengthLabel
  size?: 'sm' | 'md'
  className?: string
}

/**
 * Полоса совпадения текстом: процентов и баллов в списках нет (Арх. 11.7, п. 5).
 * Без полосы — «Сила профиля: высокая / средняя / базовая».
 */
export function FitBadge({ band, strength, size = 'md', className }: FitBadgeProps) {
  if (band === 'strong') {
    return (
      <Badge variant="success" size={size} data-slot="fit-badge" className={className}>
        <ChevronsUp aria-hidden="true" />
        {FIT_BAND_LABELS.strong}
      </Badge>
    )
  }
  if (band === 'good') {
    return (
      <Badge variant="info" size={size} data-slot="fit-badge" className={className}>
        <ChevronUp aria-hidden="true" />
        {FIT_BAND_LABELS.good}
      </Badge>
    )
  }
  if (band === 'partial') {
    return (
      <Badge variant="neutral" size={size} data-slot="fit-badge" className={className}>
        <Minus aria-hidden="true" />
        {FIT_BAND_LABELS.partial}
      </Badge>
    )
  }
  if (!strength) return null
  return (
    <Badge variant="neutral" size={size} data-slot="fit-badge" className={className}>
      <Gauge aria-hidden="true" />
      Сила профиля: {STRENGTH_LABELS[strength]}
    </Badge>
  )
}
