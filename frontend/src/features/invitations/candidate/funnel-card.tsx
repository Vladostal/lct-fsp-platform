import { Link } from '@tanstack/react-router'
import type { FunnelView } from '@/client'
import { Button } from '@/components/ui/button'
import { formatNumber } from '@/lib/format'

export type FunnelCardProps = { funnel: FunnelView; fspLinked: boolean }

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <div className="min-w-0">
      <p className="num text-2xl leading-8 font-medium text-ink">{formatNumber(value)}</p>
      <p className="type-sm text-ink-muted">{label}</p>
    </div>
  )
}

/** «Спрос на ваш профиль»: четыре числа окна 30 дней, объяснение стадии и одно действие. */
export function FunnelCard({ funnel, fspLinked }: FunnelCardProps) {
  let text = ''
  let action: React.ReactNode = null
  switch (funnel.stage) {
    case 'hidden':
      text = 'Профиль не виден работодателям'
      break
    case 'ok':
      text = `Приглашений за ${funnel.window_days} дней: ${funnel.delivered}`
      action = (
        <Button asChild variant="secondary" size="sm">
          <Link to="/candidate/invitations">К приглашениям</Link>
        </Button>
      )
      break
    case 'blocked_by_min':
      text = `${funnel.not_delivered} приглашений не доставлено: вилка начиналась ниже вашего минимума`
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
      text = `Вы были в ${funnel.shown} подборках, карточку не открывали`
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
      text = `Карточку открыли ${funnel.opened} работодателей, приглашений пока нет`
      action = (
        <Button asChild variant="secondary" size="sm">
          <Link to="/candidate/category">Чем подтверждены навыки</Link>
        </Button>
      )
      break
  }
  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat value={funnel.shown} label="в подборках" />
        <Stat value={funnel.opened} label="открыли карточку" />
        <Stat value={funnel.delivered} label="приглашений" />
        <Stat value={funnel.not_delivered} label="не доставлено" />
      </div>
      <p className="type-body text-ink [overflow-wrap:anywhere]">{text}</p>
      {action}
    </div>
  )
}
