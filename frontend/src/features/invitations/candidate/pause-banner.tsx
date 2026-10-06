import type { VisibilityDto } from '@/client'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { formatDate } from '@/lib/format'
import { useResumeVisibility } from './hooks'

/** Баннер паузы: автопауза («Я на связи») и, если нужно, ручная («Возобновить показ»). */
export function PauseBanner({ visibility, manual = false }: { visibility: VisibilityDto; manual?: boolean }) {
  const auto = visibility.state === 'paused' && visibility.pause_reason === 'auto_silence'
  const hand = manual && visibility.state === 'paused' && visibility.pause_reason === 'manual'
  const resume = useResumeVisibility('resume')
  const show = useResumeVisibility('visible')
  if (!auto && !hand) return null
  const action = auto ? resume : show
  return (
    <Alert variant="warning">
      <AlertDescription>
        {auto
          ? `Профиль скрыт: два приглашения подряд остались без ответа. Показ вернётся ${
              visibility.auto_paused_until ? formatDate(visibility.auto_paused_until) : 'позже'
            } или сразу — по кнопке`
          : 'Профиль скрыт: новые приглашения не приходят'}
      </AlertDescription>
      <Button size="sm" variant="secondary" loading={action.pending} onClick={action.run}>
        {auto ? 'Я на связи' : 'Возобновить показ'}
      </Button>
    </Alert>
  )
}
