import { Link } from '@tanstack/react-router'
import type { NextAction } from '@/client'
import { Button } from '@/components/ui/button'
import { errorText } from '@/lib/api'
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

/** Список действий; пуст — блок скрыт. */
export function NextActionList({ actions, className }: { actions: readonly NextAction[]; className?: string }) {
  if (actions.length === 0) return null
  return (
    <div className={cn('flex min-w-0 flex-wrap items-start gap-3', className)}>
      {actions.map((action) => (
        <NextActionButton key={action.kind + action.grade.code} action={action} primary={action.recommended === true} />
      ))}
    </div>
  )
}
