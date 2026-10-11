import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import {
  AppWindow,
  CircleHelp,
  CirclePause,
  GitFork,
  Layers,
  ListChecks,
  Lock,
  type LucideIcon,
  MousePointerClick,
  ScrollText,
  Shuffle,
  StepForward,
  Timer,
  TimerOff,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import type { Catalog } from '@/client'
import { ErrorState, IconTile, PageHeader, SoftPill, StatTile, StickyActionBar, SummaryStrip } from '@/components/app'
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
import { CardHead, RuleList } from './parts'

const ITEMS = PLURALS.task

/** Значки правил — по порядку строк `ASSESSMENT.briefing.rules`. */
const RULE_ICONS: readonly LucideIcon[] = [StepForward, CircleHelp, AppWindow, TimerOff, MousePointerClick]

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
      <SummaryStrip label={ASSESSMENT.briefing.summary}>
        <StatTile icon={ListChecks} value={bp.items_min} label={plural(bp.items_min, ITEMS)} tone="solid" />
        <StatTile icon={Timer} value={bp.time_limit_min} label={ASSESSMENT.briefing.minutesLabel} />
      </SummaryStrip>
      <ul className="flex min-w-0 flex-wrap items-center gap-2">
        <li className="min-w-0">
          <SoftPill tone="brand" icon={Lock}>
            {ASSESSMENT.briefing.tiles.noUndo}
          </SoftPill>
        </li>
        <li className="min-w-0">
          <SoftPill tone="brand" icon={CirclePause}>
            {ASSESSMENT.briefing.tiles.noPause}
          </SoftPill>
        </li>
        <li className="type-sm inline-flex min-h-7 min-w-0 items-center gap-1.5 rounded-full bg-warning-bg px-2.5 py-0.5 text-warning">
          <GitFork aria-hidden="true" className="size-4 shrink-0" />
          <span className="min-w-0">
            {ASSESSMENT.briefing.border(`${bp.items_max} ${plural(bp.items_max, ITEMS)}`, bp.time_limit_max_min)}
          </span>
        </li>
      </ul>
      <section className="surface-card flex min-w-0 animate-rise-in flex-col gap-4" aria-labelledby="bp-composition">
        <CardHead
          id="bp-composition"
          icon={Layers}
          title={ASSESSMENT.briefing.composition}
          aside={
            <SoftPill tone="brand">
              <span className="num font-semibold">{bp.skills.length}</span>
            </SoftPill>
          }
        />
        <ul className="flex min-w-0 flex-wrap gap-2">
          {bp.skills.map((sk) => (
            <li
              key={sk.group_code}
              className="type-sm min-w-0 max-w-full break-words rounded-full bg-fill px-3 py-1 text-ink"
            >
              {sk.label}
            </li>
          ))}
        </ul>
        <p className="type-sm flex min-w-0 items-start gap-2.5">
          <IconTile icon={Shuffle} tone="soft" size="xs" />
          <span className="min-w-0 pt-1">
            {ASSESSMENT.briefing.perCandidate}{' '}
            <Link to="/how-it-works" hash="testing" className="text-link">
              {ASSESSMENT.briefing.howItWorks}
            </Link>
          </span>
        </p>
      </section>
      <section className="surface-card flex min-w-0 animate-rise-in flex-col gap-4" aria-labelledby="bp-rules">
        <CardHead id="bp-rules" icon={ScrollText} tone="soft" title={ASSESSMENT.briefing.rulesTitle} />
        <RuleList
          columns={2}
          items={ASSESSMENT.briefing.rules.map((rule, i) => ({ icon: RULE_ICONS[i] ?? ScrollText, text: rule }))}
        />
        <Label className="flex min-h-11 min-w-0 cursor-pointer items-center gap-3 rounded-md bg-brand-50 p-3 font-medium">
          <Checkbox checked={confirmed} onCheckedChange={(v) => setConfirmed(v === true)} />
          <span className="min-w-0">{ASSESSMENT.briefing.confirm(bp.time_limit_max_min)}</span>
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
