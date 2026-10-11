import { Ban } from 'lucide-react'
import type { QuotaView } from '@/client'
import { cn } from '@/lib/utils'

export type QuotaIndicatorProps = {
  quota: Pick<QuotaView, 'frozen'>
  className?: string
}

/** Отметка в шапке работодателя: показывается, только когда отправка приглашений приостановлена. */
export function QuotaIndicator({ quota, className }: QuotaIndicatorProps) {
  if (!quota.frozen) return null
  return (
    <span
      data-slot="quota-indicator"
      data-tone="danger"
      className={cn(
        'inline-flex h-9 shrink-0 items-center gap-2 rounded-full bg-danger-bg px-3 text-sm leading-5 font-medium whitespace-nowrap text-danger',
        className,
      )}
    >
      <Ban className="size-4" aria-hidden="true" />
      <span>Отправка приостановлена</span>
    </span>
  )
}
