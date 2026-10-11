import { Link } from '@tanstack/react-router'
import type { FunnelView } from '@/client'
import { FunnelStrip } from '@/components/app'
import { Button } from '@/components/ui/button'

export type FunnelCardProps = { funnel: FunnelView; fspLinked: boolean }

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
      <FunnelStrip
        steps={[
          { label: 'в подборках', value: funnel.shown },
          { label: 'открыли карточку', value: funnel.opened },
          { label: 'приглашений', value: funnel.delivered },
          { label: 'не доставлено', value: funnel.not_delivered },
        ]}
      />
      <p className="type-body text-ink [overflow-wrap:anywhere]">{text}</p>
      {action}
    </div>
  )
}
