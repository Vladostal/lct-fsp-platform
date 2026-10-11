import { useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { Megaphone } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { ConsentCheckbox } from '@/components/app'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { errorMessage, hasCode } from '@/lib/api'
import { invalidateGuardData } from '@/lib/guards'
import { grantPublication } from '../api'
import { ASSESSMENT } from '../content'
import { CardHead } from './parts'

/**
 * Публикация профиля: согласие и кнопка. Показывается на результате теста (категория подтверждена) и на экране
 * категории (грейд заявлен, теста нет) — у заявленного грейда страницы результата не бывает.
 */
export function PublishCard({
  version,
  refetchConsents,
  declared = false,
}: {
  version: string | null
  refetchConsents: () => Promise<unknown>
  /** Грейд заявлен, а не подтверждён тестом: текст не обещает интервал уровня. */
  declared?: boolean
}) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [agreed, setAgreed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ message: string; profile?: boolean } | null>(null)

  useEffect(() => {
    if (window.location.hash === '#publish') document.getElementById('publish')?.scrollIntoView()
  }, [])

  const publish = async () => {
    if (!version) return
    setBusy(true)
    setError(null)
    try {
      await grantPublication(version)
      await invalidateGuardData(queryClient)
      toast.success('Профиль опубликован')
      await navigate({ to: '/candidate' })
    } catch (e) {
      if (hasCode(e, 'profile_incomplete')) setError({ message: ASSESSMENT.result.incomplete, profile: true })
      else if (hasCode(e, 'consent_version_outdated')) {
        setAgreed(false)
        await refetchConsents()
        setError({ message: errorMessage(e) })
      } else setError({ message: errorMessage(e) })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section
      id="publish"
      className="surface-card accent-card flex min-w-0 scroll-mt-24 flex-col gap-3 p-4 md:p-6"
      aria-labelledby="r-publish"
    >
      <CardHead id="r-publish" icon={Megaphone} tone="solid" title={ASSESSMENT.result.publishTitle} />
      <p className="type-sm min-w-0">
        {declared ? ASSESSMENT.result.publishTextDeclared : ASSESSMENT.result.publishText}
      </p>
      <Link to="/candidate/settings/privacy" className="text-link tap-target type-sm w-fit">
        {ASSESSMENT.result.publishLink}
      </Link>
      <ConsentCheckbox checked={agreed} onCheckedChange={setAgreed} href="/legal/publication" version={version}>
        {ASSESSMENT.result.publishConsent}
      </ConsentCheckbox>
      {error ? (
        <Alert variant="destructive">
          {error.message}{' '}
          {error.profile ? (
            <Link to="/candidate/profile" className="text-link">
              Открыть профиль
            </Link>
          ) : null}
        </Alert>
      ) : null}
      <div>
        <Button variant="primary" loading={busy} disabled={!agreed || busy || !version} onClick={publish}>
          {ASSESSMENT.result.publish}
        </Button>
      </div>
    </section>
  )
}
