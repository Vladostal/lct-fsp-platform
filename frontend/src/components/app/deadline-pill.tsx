import { Clock, Hourglass } from 'lucide-react'
import { formatDate, formatRemaining } from '@/lib/format'
import { msUntil } from '@/lib/time'
import { SoftPill } from './soft-pill'

export type DeadlinePillProps = {
  /** Срок ответа на приглашение (ISO). */
  until: string
  size?: 'sm' | 'md'
  className?: string
}

/**
 * Срок ответа — одинаково у кандидата и работодателя: «до 17 окт. · 5 дней». Сутки и больше — нейтральный
 * тон, меньше суток — янтарный. Слова «ответить» и «осталось» — для скринридера.
 */
export function DeadlinePill({ until, size = 'md', className }: DeadlinePillProps) {
  const remaining = formatRemaining(until)
  if (remaining === null)
    return (
      <SoftPill size={size} icon={Clock} className={className}>
        <span className="num">срок истёк {formatDate(until)}</span>
      </SoftPill>
    )
  const soon = msUntil(until) < 24 * 3600_000
  return (
    <SoftPill
      size={size}
      tone={soon ? 'warning' : 'neutral'}
      icon={Hourglass}
      className={soon ? `font-medium ${className ?? ''}` : className}
    >
      <span className="num whitespace-nowrap">
        <span className="sr-only">ответить </span>до {formatDate(until)} ·<span className="sr-only"> осталось</span>{' '}
        {remaining}
      </span>
    </SoftPill>
  )
}
