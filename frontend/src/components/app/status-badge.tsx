import {
  ChevronsUp,
  Circle,
  CircleCheck,
  CircleDashed,
  CircleX,
  Clock,
  Eye,
  EyeOff,
  Hourglass,
  type LucideIcon,
  MailX,
  Send,
  Undo2,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

export type StatusTone = 'info' | 'success' | 'warning' | 'neutral' | 'danger'

/**
 * Иконка и тон по статусу: приглашение, исход теста, видимость профиля. Тона едины для всех экранов:
 * отказ — красный, отправка и просмотр — фирменный, «ждёт ответа» и истёкшее — янтарные, отозванное и
 * недоставленное — серые. Глаз значит только «просмотрено»; ожидание ответа — всегда песочные часы.
 */
const STATUS_VIEW: Record<string, { icon: LucideIcon; tone: StatusTone }> = {
  // приглашение
  sent: { icon: Send, tone: 'info' },
  viewed: { icon: Eye, tone: 'info' },
  // глазами кандидата просмотренное приглашение «ждёт ответа»: код `awaiting` вместо `viewed`
  awaiting: { icon: Hourglass, tone: 'warning' },
  accepted: { icon: CircleCheck, tone: 'success' },
  declined: { icon: CircleX, tone: 'danger' },
  expired: { icon: Clock, tone: 'warning' },
  withdrawn: { icon: Undo2, tone: 'neutral' },
  // не дошло до кандидата: нейтрально, как пунктирная строка сводки
  bounced: { icon: MailX, tone: 'neutral' },
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
  /** Подсказка вместо подписи: причина состояния («нет категории»). */
  title?: string
  /** Переопределить тон. */
  tone?: StatusTone
  size?: 'sm' | 'md'
  /** `pill` — плашка-пилюля с иконкой (по умолчанию, единый вид); `dot` — точка и подпись без фона для плотных таблиц. */
  appearance?: 'dot' | 'pill'
  /** Объявлять смену статуса скринридеру (при обновлении опросом). */
  live?: boolean
  className?: string
}

/** Статус различим без цвета: подпись всегда, точка или иконка дублируют (Арх. 11.7, п. 2). */
const DOT_TONE: Record<StatusTone, string> = {
  info: 'bg-brand-600',
  success: 'bg-success',
  warning: 'bg-warning',
  neutral: 'bg-ink-subtle',
  danger: 'bg-danger',
}

export function StatusBadge({
  status,
  label,
  title,
  tone,
  size = 'md',
  appearance = 'pill',
  live = false,
  className,
}: StatusBadgeProps) {
  const view = STATUS_VIEW[status] ?? { icon: Circle, tone: 'neutral' as const }
  const Icon = view.icon
  if (appearance === 'dot') {
    return (
      <span
        key={status}
        data-slot="status-badge"
        data-status={status}
        data-tone={tone ?? view.tone}
        role={live ? 'status' : undefined}
        title={title}
        className={cn(
          'inline-flex max-w-full items-center gap-2 text-[13px] leading-5 text-ink animate-fade-in',
          className,
        )}
      >
        <span aria-hidden="true" className={cn('size-1.5 shrink-0 rounded-full', DOT_TONE[tone ?? view.tone])} />
        {label}
      </span>
    )
  }
  return (
    <Badge
      // key: при смене статуса бейдж проявляется заново (E §5).
      key={status}
      variant={tone ?? view.tone}
      size={size}
      data-status={status}
      role={live ? 'status' : undefined}
      className={cn('animate-fade-in rounded-full px-2.5', className)}
    >
      <Icon aria-hidden="true" />
      {/* В узкой ячейке длинная подпись усекается, полный текст — в title. */}
      <span title={title ?? label} className="min-w-0 truncate">
        {label}
      </span>
    </Badge>
  )
}
