import { Ban, Send, TriangleAlert } from 'lucide-react'
import type { QuotaView } from '@/client'
import { cn } from '@/lib/utils'

export type QuotaIndicatorProps = {
  quota: Pick<QuotaView, 'used' | 'limit' | 'frozen'>
  className?: string
}

/**
 * Квота работодателя в шапке: «Слоты {used} / {limit}» — число включает слоты, занятые недоставленными (Арх. 11.8).
 * Все слоты заняты — тон warning и иконка; отправка заморожена — danger. Состояние названо и текстом.
 */
export function QuotaIndicator({ quota, className }: QuotaIndicatorProps) {
  const full = quota.used >= quota.limit
  const tone = quota.frozen ? 'danger' : full ? 'warning' : 'neutral'
  const Icon = quota.frozen ? Ban : full ? TriangleAlert : Send
  const state = quota.frozen ? 'отправка приостановлена' : full ? 'все слоты заняты' : null

  return (
    <span
      data-slot="quota-indicator"
      data-tone={tone}
      className={cn(
        'inline-flex h-9 shrink-0 items-center gap-2 rounded-full px-3 text-sm leading-5 font-medium whitespace-nowrap',
        tone === 'danger' && 'bg-danger-bg text-danger',
        tone === 'warning' && 'bg-warning-bg text-warning',
        tone === 'neutral' && 'bg-fill text-ink',
        className,
      )}
    >
      <Icon className="size-4" aria-hidden="true" />
      <span>
        Слоты{' '}
        <span className="num">
          {quota.used} / {quota.limit}
        </span>
      </span>
      {state ? <span className="sr-only">: {state}</span> : null}
    </span>
  )
}
