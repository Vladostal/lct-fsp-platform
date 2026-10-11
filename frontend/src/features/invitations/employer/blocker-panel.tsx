import { Link } from '@tanstack/react-router'
import { Ban } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { type ErrorParams, errorText } from '@/lib/api'

export type BlockerPanelProps = {
  /** Код блокера (Арх. 6.4) или код ошибки отправки. */
  code: string
  /** Текст сервера; используется, если кода нет в словаре интерфейса. */
  message?: string | null
  params?: ErrorParams
  /** Потребность: «К подборке» ведёт на её подборку. */
  needId?: string | null
}

/** Панель блокера отправки: текст причины и одно действие. */
export function BlockerPanel({ code, message, params, needId }: BlockerPanelProps) {
  const known = errorText(code, params)
  const text = known.startsWith('Не получилось') && message ? message : known
  let action: React.ReactNode
  if (code === 'company_profile_incomplete')
    action = (
      <Button asChild variant="primary">
        <Link to="/employer/company">Заполнить профиль компании</Link>
      </Button>
    )
  else if (code === 'demo_sender_restricted')
    action = (
      <Button asChild variant="primary">
        <Link to="/signup" search={{ role: 'employer' }}>
          Зарегистрировать свою компанию
        </Link>
      </Button>
    )
  else if (code === 'active_invitation_exists')
    action = (
      <Button asChild variant="primary">
        <Link to="/employer/invitations">Открыть приглашение</Link>
      </Button>
    )
  else
    action = needId ? (
      <Button asChild variant="primary">
        <Link to="/employer/needs/$needId" params={{ needId }}>
          К подборке
        </Link>
      </Button>
    ) : (
      <Button asChild variant="primary">
        <Link to="/employer/search">К банку кандидатов</Link>
      </Button>
    )
  return (
    <div data-slot="blocker-panel" className="flex min-w-0 flex-col gap-4">
      <Alert variant="warning" icon={<Ban className="size-5" aria-hidden="true" />}>
        <AlertDescription className="[overflow-wrap:anywhere]">{text}</AlertDescription>
      </Alert>
      <div>{action}</div>
    </div>
  )
}
