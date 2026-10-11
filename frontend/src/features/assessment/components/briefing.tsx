import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { useEffect, useState } from 'react'
import type { Catalog } from '@/client'
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
import { blueprintsQuery, createQuickSession, createSession } from '../api'
import { ASSESSMENT } from '../content'
import { unavailableReason } from './next-actions'

const ITEMS = PLURALS.task

// Быстрый демо-тест: маршрута `POST /demo/assessment/quick-session` в API сейчас нет (кнопка получала 404).
// Вернуть true, когда маршрут появится.
const QUICK_TEST_AVAILABLE = false

export function Briefing({ catalog, grade }: { catalog: Catalog | null; grade?: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const state = useQuery(assessmentStateQuery)
  const blueprints = useQuery(blueprintsQuery)
  const [confirmed, setConfirmed] = useState(false)
  const [busy, setBusy] = useState<'start' | 'quick' | null>(null)
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
        {/* Пустой список — теста нет по всей специализации: грейд заявляется на экране категории. */}
        <ErrorState
          title={blueprints.data.length === 0 ? 'Тест по специализации готовится' : 'Тест для этого грейда готовится'}
          text={blueprints.data.length === 0 ? 'Грейд можно заявить на странице категории.' : 'Выберите другой грейд.'}
          homeHref="/candidate/category"
        />
      </>
    )
  }

  const handle = async (kind: 'start' | 'quick') => {
    setBusy(kind)
    setError(null)
    try {
      const id =
        kind === 'start' ? (await createSession(gradeCode)).id : (await createQuickSession(gradeCode)).session_id
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
      setBusy(null)
    }
  }

  const demo = QUICK_TEST_AVAILABLE && catalog?.features.demo === true

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader title={title} breadcrumbs={crumbs} />
      <p className="type-body min-w-0 text-ink">
        <span className="num">
          {bp.items_min} {plural(bp.items_min, ITEMS)}
        </span>{' '}
        · <span className="num">до {bp.time_limit_min} мин</span> · {ASSESSMENT.briefing.tiles.noUndo.toLowerCase()} ·{' '}
        {ASSESSMENT.briefing.tiles.noPause.toLowerCase()}
        <span className="type-sm block text-ink-muted">
          На границе результата — до {bp.items_max} {plural(bp.items_max, ITEMS)} и до {bp.time_limit_max_min} мин.
        </span>
      </p>
      <section
        className="surface-card flex min-w-0 animate-rise-in flex-col divide-y divide-line"
        aria-labelledby="bp-composition"
      >
        <div className="flex min-w-0 flex-col gap-2 pb-4">
          <h2 id="bp-composition" className="type-h3">
            {ASSESSMENT.briefing.composition}
          </h2>
          <p className="type-sm min-w-0 break-words text-ink-muted">{bp.skills.map((s) => s.label).join(' · ')}</p>
          <p className="type-sm min-w-0">
            {ASSESSMENT.briefing.perCandidate}{' '}
            <Link to="/how-it-works" hash="testing" className="text-link">
              {ASSESSMENT.briefing.howItWorks}
            </Link>
          </p>
        </div>
        <div className="flex min-w-0 flex-col gap-2 py-4">
          <h2 id="bp-rules" className="type-h3">
            {ASSESSMENT.briefing.rulesTitle}
          </h2>
          <ul className="type-sm flex min-w-0 list-disc flex-col gap-1 pl-5 text-ink-muted">
            {ASSESSMENT.briefing.rules.map((rule) => (
              <li key={rule} className="min-w-0">
                {rule}
              </li>
            ))}
          </ul>
        </div>
        <Label className="flex min-w-0 cursor-pointer items-start gap-3 pt-4 font-normal">
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
      {demo ? <p className="type-caption min-w-0 text-ink-muted">{ASSESSMENT.briefing.quickHint}</p> : null}
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
        {demo ? (
          <Button
            variant="secondary"
            loading={busy === 'quick'}
            disabled={busy != null || blocked}
            onClick={() => handle('quick')}
          >
            {ASSESSMENT.briefing.quick}
          </Button>
        ) : null}
        <Button
          variant="primary"
          loading={busy === 'start'}
          disabled={!confirmed || busy != null || blocked}
          onClick={() => handle('start')}
        >
          {ASSESSMENT.briefing.start}
        </Button>
      </StickyActionBar>
    </div>
  )
}
