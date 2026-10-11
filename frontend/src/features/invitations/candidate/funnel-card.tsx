import { Link } from '@tanstack/react-router'
import { Eye, Info, MailCheck, MailX, Users } from 'lucide-react'
import type { FunnelView } from '@/client'
import { Pipeline, SoftPill, StageCell } from '@/components/app'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

export type FunnelCardProps = {
  funnel: FunnelView
  fspLinked: boolean
  /** Рядом уже стоит блок приглашений со своей ссылкой: карточка не тянется по его высоте и ссылку не повторяет. */
  hasAwaiting?: boolean
}

const share = (pct: number) => `${pct} % от предыдущей ступени`

/**
 * Доля от предыдущей ступени. Ступени считаются по разным событиям окна, поэтому следующая бывает больше
 * предыдущей (пригласили из банка, не открывая подборку): тогда полоса конверсии не рисуется вовсе.
 */
const conversion = (value: number, prev: number) => (prev > 0 && value <= prev ? value / prev : undefined)

/**
 * «Спрос на ваш профиль»: путь окна 30 дней — в подборках → открыли карточку → пригласили; недоставленные —
 * отдельным счётчиком. Под ним одна короткая подсказка стадии и одно действие; то, что уже сказано статусом
 * в карточке категории или блоком «Не доставлено», здесь не повторяется.
 */
export function FunnelCard({ funnel, fspLinked, hasAwaiting = false }: FunnelCardProps) {
  let text = ''
  let action: React.ReactNode = null
  switch (funnel.stage) {
    case 'hidden':
      break
    case 'ok':
      action = hasAwaiting ? null : (
        <Button asChild variant="secondary" size="sm">
          <Link to="/candidate/invitations">К приглашениям</Link>
        </Button>
      )
      break
    case 'blocked_by_min':
      // Причина названа в блоке «Не доставлено» ниже; здесь — только счётчик и действие.
      text = funnel.not_delivered > 0 ? '' : 'Вилка начиналась ниже вашего минимума'
      action = (
        <Button asChild variant="secondary" size="sm">
          <Link to="/candidate/profile" hash="conditions">
            Изменить минимум
          </Link>
        </Button>
      )
      break
    case 'not_shown':
      text = `Запросов на вашу категорию за ${funnel.window_days} дней не было`
      break
    case 'not_opened':
      text = 'Карточку пока не открывали'
      action = fspLinked ? (
        <Button asChild variant="secondary" size="sm">
          <Link to="/candidate/category">Чем подтверждены навыки</Link>
        </Button>
      ) : (
        <Button asChild variant="secondary" size="sm">
          <Link to="/candidate/settings/fsp">Привязать ФСП ID</Link>
        </Button>
      )
      break
    case 'not_invited':
      text = 'Приглашений пока нет'
      action = (
        <Button asChild variant="secondary" size="sm">
          <Link to="/candidate/category">Чем подтверждены навыки</Link>
        </Button>
      )
      break
  }
  return (
    <div
      className={cn(
        'surface-card flex min-w-0 animate-rise-in flex-col justify-center gap-4',
        hasAwaiting ? 'self-start' : 'h-full',
      )}
    >
      <Pipeline label={`Спрос за ${funnel.window_days} дней`}>
        <StageCell icon={Users} value={funnel.shown} label="в подборках" tone="brand" />
        <StageCell
          icon={Eye}
          value={funnel.opened}
          label="открыли карточку"
          share={conversion(funnel.opened, funnel.shown)}
          shareText={share}
          tone="deep"
          index={1}
        />
        <StageCell
          icon={MailCheck}
          value={funnel.delivered}
          label="пригласили"
          share={conversion(funnel.delivered, funnel.opened)}
          shareText={share}
          tone="success"
          index={2}
        />
      </Pipeline>
      {funnel.not_delivered > 0 || text || action ? (
        <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
          {funnel.not_delivered > 0 ? (
            <SoftPill icon={MailX}>
              <span>
                не доставлено: <span className="num font-medium text-ink">{funnel.not_delivered}</span>
              </span>
            </SoftPill>
          ) : null}
          {text ? (
            <p className="type-sm flex min-w-0 flex-1 basis-48 items-center gap-1.5 text-ink-muted [overflow-wrap:anywhere]">
              {funnel.not_delivered > 0 ? null : <Info aria-hidden="true" className="size-4 shrink-0" />}
              {text}
            </p>
          ) : null}
          {action ? <div className="ml-auto flex shrink-0">{action}</div> : null}
        </div>
      ) : null}
    </div>
  )
}
