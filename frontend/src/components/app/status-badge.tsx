import {
  ChevronsUp,
  Circle,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  Eye,
  EyeOff,
  type LucideIcon,
  MailX,
  Send,
  Undo2,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

export type StatusTone = 'info' | 'success' | 'warning' | 'neutral' | 'danger'

/** Иконка и тон по статусу (E §3.3): приглашение, исход теста, видимость профиля. */
const STATUS_VIEW: Record<string, { icon: LucideIcon; tone: StatusTone }> = {
  // приглашение
  sent: { icon: Send, tone: 'info' },
  viewed: { icon: Eye, tone: 'info' },
  accepted: { icon: CircleCheck, tone: 'success' },
  declined: { icon: CircleX, tone: 'neutral' },
  expired: { icon: Clock, tone: 'warning' },
  withdrawn: { icon: Undo2, tone: 'neutral' },
  bounced: { icon: MailX, tone: 'warning' },
  // исход теста: у «не подтверждён» нет красного
  confirmed: { icon: CircleCheck, tone: 'success' },
  confirmed_with_margin: { icon: ChevronsUp, tone: 'success' },
  borderline: { icon: CircleDashed, tone: 'warning' },
  not_confirmed: { icon: CircleX, tone: 'neutral' },
  // видимость профиля
  visible: { icon: Eye, tone: 'success' },
  paused: { icon: EyeOff, tone: 'warning' },
  unpublished: { icon: CircleDashed, tone: 'neutral' },
  not_ready: { icon: CircleDashed, tone: 'neutral' },
}

export type StatusBadgeProps = {
  /** Код статуса: по нему выбирается иконка и тон. Неизвестный код — нейтральный бейдж с кружком. */
  status: string
  /** Подпись: `status_label` сервера; запасные подписи — в content/common.ts. */
  label: string
  /** Переопределить тон. */
  tone?: StatusTone
  size?: 'sm' | 'md'
  /** Объявлять смену статуса скринридеру (при обновлении опросом). */
  live?: boolean
  className?: string
}

/** Статус различим без цвета: у каждого бейджа иконка и подпись (Арх. 11.7, п. 2). */
export function StatusBadge({ status, label, tone, size = 'md', live = false, className }: StatusBadgeProps) {
  const view = STATUS_VIEW[status] ?? { icon: Circle, tone: 'neutral' as const }
  const Icon = view.icon
  return (
    <Badge
      // key: при смене статуса бейдж проявляется заново (E §5).
      key={status}
      variant={tone ?? view.tone}
      size={size}
      data-status={status}
      role={live ? 'status' : undefined}
      className={cn('animate-fade-in', className)}
    >
      <Icon aria-hidden="true" />
      {label}
    </Badge>
  )
}
