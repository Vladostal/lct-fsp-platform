import { Link } from '@tanstack/react-router'
import { ChevronsDown, ChevronsUp, Hourglass, type LucideIcon, Play, RotateCw } from 'lucide-react'
import type { NextAction } from '@/client'
import { GoChevron, IconTile, SoftPill, type TileTone } from '@/components/app'
import { Button } from '@/components/ui/button'
import { errorText } from '@/lib/api'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/utils'
import { ASSESSMENT } from '../content'

export function nextActionLabel(action: NextAction): string {
  return ASSESSMENT.kinds[action.kind](action.grade.title)
}

/** Причина недоступности действия: текст `cooldown_active` по `reason` с датой сервера (не вычисляется на клиенте). */
export function unavailableReason(action: NextAction): string {
  const params: Record<string, string> = { reason: action.reason ?? '' }
  if (action.available_at) params.available_at = action.available_at
  return errorText('cooldown_active', params)
}

export type NextActionButtonProps = {
  action: NextAction
  primary?: boolean
  className?: string
}

/** Действие смены грейда: доступное ведёт на C4 `?grade=`, недоступное — неактивная кнопка и причина с датой. */
export function NextActionButton({ action, primary = false, className }: NextActionButtonProps) {
  const label = nextActionLabel(action)
  const variant = primary ? 'primary' : 'secondary'
  if (!action.available) {
    return (
      <div className={cn('flex min-w-0 flex-col items-start gap-1', className)}>
        <Button variant={variant} disabled>
          {label}
        </Button>
        <p className="type-caption min-w-0 text-ink-muted">{unavailableReason(action)}</p>
      </div>
    )
  }
  return (
    <Button variant={variant} asChild className={className}>
      <Link to="/candidate/test/new" search={{ grade: action.grade.code }}>
        {label}
      </Link>
    </Button>
  )
}

const KIND_ICON: Record<NextAction['kind'], LucideIcon> = {
  take_claimed: Play,
  take_lower: ChevronsDown,
  take_higher: ChevronsUp,
  retake_same: RotateCw,
}

/**
 * Карточка действия: плитка-направление (выше, ниже, ещё раз), грейд крупно и подпись в два слова.
 * Доступная — ссылка на брифинг во всю карточку; недоступная — пунктирная, со сроком в пилюле
 * (полная причина с датой сервера остаётся текстом для скринридера и в подсказке).
 */
export function NextActionCard({ action, index = 0 }: { action: NextAction; index?: number }) {
  const label = nextActionLabel(action)
  const Icon = KIND_ICON[action.kind]
  const hint = ASSESSMENT.kindHints[action.kind]
  const style = { '--i': index } as React.CSSProperties
  if (!action.available) {
    const reason = unavailableReason(action)
    return (
      <li
        style={style}
        data-slot="next-action"
        data-available="false"
        className="stagger flex min-w-0 animate-rise-in items-center gap-3 rounded-md border border-dashed border-line-strong bg-surface p-3 md:p-4"
      >
        <IconTile icon={Icon} tone="neutral" size="lg" />
        <span className="flex min-w-0 flex-1 flex-col">
          <span className="type-h3 min-w-0 break-words text-ink-muted">
            <span className="sr-only">{label}: </span>
            <span aria-hidden="true">{action.grade.title}</span>
          </span>
          <span className="type-caption text-ink-muted" aria-hidden="true">
            {hint}
          </span>
        </span>
        {action.available_at ? (
          <SoftPill tone="warning" icon={Hourglass} title={reason}>
            <span aria-hidden="true" className="num">
              {ASSESSMENT.category.from(formatDate(action.available_at))}
            </span>
            <span className="sr-only">{reason}</span>
          </SoftPill>
        ) : (
          <span className="type-caption min-w-0 max-w-[55%] break-words text-warning">{reason}</span>
        )}
      </li>
    )
  }
  const recommended = action.recommended === true
  return (
    <li
      style={style}
      data-slot="next-action"
      data-available="true"
      className={cn(
        'lift-card surface-row stagger relative flex min-w-0 animate-rise-in items-center gap-3 p-3 md:p-4',
        recommended && 'accent-card border-brand-200',
      )}
    >
      <IconTile icon={Icon} tone={recommended ? 'solid' : 'brand'} size="lg" />
      <span className="flex min-w-0 flex-1 flex-col">
        <Link
          to="/candidate/test/new"
          search={{ grade: action.grade.code }}
          aria-label={label}
          className="type-h3 min-w-0 break-words text-ink after:absolute after:inset-0 after:z-[1] after:rounded-md after:content-[''] hover:text-brand-700"
        >
          {action.grade.title}
        </Link>
        <span className="type-caption text-ink-muted">{hint}</span>
      </span>
      {recommended ? (
        <SoftPill tone="solid" size="sm">
          {ASSESSMENT.category.recommended}
        </SoftPill>
      ) : null}
      <GoChevron />
    </li>
  )
}

/** Карточка-ссылка в ряду действий (не тест): плитка, название, стрелка — тот же вид, что у карточек грейда. */
export function LinkActionCard({
  icon,
  tone = 'brand',
  index = 0,
  children,
}: {
  icon: LucideIcon
  tone?: TileTone
  index?: number
  /** Ссылка `Link`/`a`: растягивается на всю карточку. */
  children: React.ReactNode
}) {
  return (
    <li
      style={{ '--i': index } as React.CSSProperties}
      data-slot="next-action"
      className="lift-card surface-row stagger relative flex min-w-0 animate-rise-in items-center gap-3 p-3 md:p-4 [&_a]:after:absolute [&_a]:after:inset-0 [&_a]:after:rounded-md [&_a]:after:content-[''] [&_a]:hover:text-brand-700"
    >
      <IconTile icon={icon} tone={tone} size="lg" />
      <span className="type-h3 min-w-0 flex-1 break-words text-ink">{children}</span>
      <GoChevron />
    </li>
  )
}

/** Список действий карточками; `extra` — дополнительные карточки (`LinkActionCard`) в том же ряду. Пуст — блок скрыт. */
export function NextActionList({
  actions,
  extra,
  extraCount = 0,
  className,
}: {
  actions: readonly NextAction[]
  extra?: React.ReactNode
  /** Сколько карточек в `extra` — для числа колонок. */
  extraCount?: number
  className?: string
}) {
  const total = actions.length + extraCount
  if (total === 0) return null
  return (
    <ul className={cn('grid min-w-0 gap-3 sm:grid-cols-2', total >= 3 ? 'lg:grid-cols-3' : null, className)}>
      {actions.map((action, i) => (
        <NextActionCard key={action.kind + action.grade.code} action={action} index={i} />
      ))}
      {extra}
    </ul>
  )
}
