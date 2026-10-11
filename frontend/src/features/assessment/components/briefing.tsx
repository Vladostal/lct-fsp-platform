import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import { ErrorState, PageHeader, StickyActionBar } from '@/components/app'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage, hasCode, isApiError } from '@/lib/api'
import { PLURALS, plural } from '@/lib/format'
import { invalidateGuardData } from '@/lib/guards'
import { assessmentStateQuery } from '@/lib/query'
import { blueprintsQuery, createSession } from '../api'
import { ASSESSMENT } from '../content'
import { Tile } from './briefing-parts'
import { unavailableReason } from './next-actions'

const ITEMS = PLURALS.task

export function Briefing({ grade }: { grade?: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const state = useQuery(assessmentStateQuery)
  const blueprints = useQuery(blueprintsQuery)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<{ message: string; gradeNotAllowed?: boolean } | null>(null)

  const gradeCode = grade ?? state.data?.claimed_grade?.code ?? null
  const outsideWizard = grade != null

  useEffect(() => {
    if (state.data && !gradeCode) void navigate({ to: '/candidate/category', replace: true })
  }, [state.data, gradeCode, navigate])

  const failure = state.error ?? blueprints.error
  if (failure) {
    return (
      <>
        <PageHeader title="Тест" />
        <ErrorState
          error={failure}
          onRetry={() => {
            void state.refetch()
            void blueprints.refetch()
          }}
          homeHref="/candidate"
        />
      </>
    )
  }
  if (!state.data || !blueprints.data || !gradeCode) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <PageHeader title="Тест" />
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-48 w-full" />
      </div>
    )
  }

  const bp = blueprints.data.find((b) => b.grade.code === gradeCode)
  const specialization = state.data.specialization?.title ?? state.data.category?.specialization.title ?? ''
  const title = `Тест: ${specialization ? `${specialization} · ` : ''}${bp?.grade.title ?? gradeCode}`
  const action = state.data.next_actions?.find((a) => a.grade.code === gradeCode)
  const blocked = action != null && !action.available
  const crumbs = outsideWizard
    ? [{ label: 'Категория и тесты', href: '/candidate/category' }, { label: 'Новый тест' }]
    : undefined

  if (!bp?.available) {
    return (
      <>
        <PageHeader title={title} breadcrumbs={crumbs} />
        <ErrorState
          title="Тест для этого грейда готовится"
          text="Выберите другой грейд."
          homeHref="/candidate/category"
        />
      </>
    )
  }

  const handle = async () => {
    setBusy(true)
    setError(null)
    try {
      const id = (await createSession(gradeCode)).id
      await invalidateGuardData(queryClient)
      await navigate({ to: '/candidate/test/$sessionId', params: { sessionId: id } })
    } catch (e) {
      if (hasCode(e, 'session_active') && isApiError(e) && e.params.session_id) {
        await navigate({ to: '/candidate/test/$sessionId', params: { sessionId: String(e.params.session_id) } })
      } else if (hasCode(e, 'cooldown_active')) {
        await state.refetch()
        setError({ message: errorMessage(e) })
      } else if (hasCode(e, 'survey_required')) {
        await navigate({ to: '/candidate/onboarding/survey' })
      } else if (hasCode(e, 'claim_required')) {
        await navigate({ to: '/candidate/onboarding/grade' })
      } else {
        setError({ message: errorMessage(e), gradeNotAllowed: hasCode(e, 'grade_not_allowed') })
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader title={title} breadcrumbs={crumbs} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Tile value={`${bp.items_min} ${plural(bp.items_min, ITEMS)}`} />
        <Tile value={`До ${bp.time_limit_min} мин`} />
        <Tile value={ASSESSMENT.briefing.tiles.noUndo} />
        <Tile value={ASSESSMENT.briefing.tiles.noPause} />
      </div>
      <p className="type-sm min-w-0 text-ink-muted">
        Если результат окажется на границе, тест добавит до двух блоков по 6 заданий и продлит время: всего до{' '}
        <span className="num">{bp.items_max}</span> {plural(bp.items_max, ITEMS)} и до{' '}
        <span className="num">{bp.time_limit_max_min}</span> мин.
      </p>
      <section className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6" aria-labelledby="bp-composition">
        <h2 id="bp-composition" className="type-h3">
          {ASSESSMENT.briefing.composition}
        </h2>
        <ul className="flex min-w-0 flex-wrap gap-2">
          {bp.skills.map((s) => (
            <li key={s.group_code} className="type-sm min-w-0 break-words rounded-full bg-fill px-3 py-1">
              {s.label}
            </li>
          ))}
        </ul>
        <p className="type-sm min-w-0">{ASSESSMENT.briefing.perCandidate}</p>
        <p className="type-sm min-w-0">{ASSESSMENT.briefing.pythonNote}</p>
        <Link to="/how-it-works" hash="testing" className="text-link type-sm w-fit">
          {ASSESSMENT.briefing.howItWorks}
        </Link>
      </section>
      <section className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6" aria-labelledby="bp-rules">
        <h2 id="bp-rules" className="type-h3">
          {ASSESSMENT.briefing.rulesTitle}
        </h2>
        <ul className="type-sm flex min-w-0 list-disc flex-col gap-1 pl-5">
          {ASSESSMENT.briefing.rules.map((rule) => (
            <li key={rule} className="min-w-0">
              {rule}
            </li>
          ))}
        </ul>
        <Label className="mt-2 flex min-w-0 cursor-pointer items-start gap-3 font-normal">
          <Checkbox checked={confirmed} onCheckedChange={(v) => setConfirmed(v === true)} className="mt-0.5" />
          <span className="min-w-0">У меня есть {bp.time_limit_max_min} минут без перерыва</span>
        </Label>
      </section>
      {blocked && action ? <Alert variant="warning">{unavailableReason(action)}</Alert> : null}
      {error ? (
        <Alert variant="destructive">
          {error.message}{' '}
          {error.gradeNotAllowed ? (
            <Link to="/candidate/category" className="text-link">
              Категория и тесты
            </Link>
          ) : null}
        </Alert>
      ) : null}
      <StickyActionBar
        note={confirmed || blocked ? undefined : ASSESSMENT.briefing.needCheck}
        secondary={
          outsideWizard ? undefined : (
            <Button variant="ghost" asChild>
              <Link to="/candidate/onboarding/grade">Назад</Link>
            </Button>
          )
        }
      >
        <Button variant="primary" loading={busy} disabled={!confirmed || busy || blocked} onClick={() => handle()}>
          {ASSESSMENT.briefing.start}
        </Button>
      </StickyActionBar>
    </div>
  )
}
