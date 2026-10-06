import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { ChevronsUp, CircleCheck, CircleDashed, CircleX, type LucideIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import type { NextAction, TestOutcome, TestResultView } from '@/client'
import { CategoryChip, ConsentCheckbox, ErrorState, LevelScale, PageHeader, Stepper } from '@/components/app'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { WIZARD_STEPS } from '@/content/common'
import { errorMessage, hasCode } from '@/lib/api'
import { formatDate, formatDuration } from '@/lib/format'
import { invalidateGuardData } from '@/lib/guards'
import { cn } from '@/lib/utils'
import { consentsQuery, grantPublication, isResult, resultQuery } from '../api'
import { ASSESSMENT } from '../content'
import { NextActionButton, NextActionList } from './next-actions'

const OUTCOME_VIEW: Record<TestOutcome, { icon: LucideIcon; tone: string }> = {
  confirmed: { icon: CircleCheck, tone: 'text-success' },
  confirmed_with_margin: { icon: ChevronsUp, tone: 'text-success' },
  borderline: { icon: CircleDashed, tone: 'text-warning' },
  not_confirmed: { icon: CircleX, tone: 'text-ink-muted' },
}

const VERDICT_ICON = { confirmed: CircleCheck, partial: CircleDashed, not_confirmed: CircleX } as const
const VERDICT_TONE = { confirmed: 'text-success', partial: 'text-warning', not_confirmed: 'text-ink-muted' } as const

const MAX_POLLS = 10

export function ResultScreen({ sessionId }: { sessionId: string }) {
  const query = useQuery({
    ...resultQuery(sessionId),
    refetchInterval: (q) =>
      q.state.data && !isResult(q.state.data) && q.state.dataUpdateCount < MAX_POLLS ? 1000 : false,
  })
  const [polls, setPolls] = useState(0)
  useEffect(() => {
    if (query.dataUpdatedAt > 0) setPolls((n) => n + 1)
  }, [query.dataUpdatedAt])
  const consents = useQuery(consentsQuery)

  if (query.isError) {
    return (
      <>
        <PageHeader title="Результат теста" />
        <ErrorState error={query.error} onRetry={() => query.refetch()} homeHref="/candidate/category" />
      </>
    )
  }
  if (!query.data || (!isResult(query.data) && query.data.status === 'in_progress' && polls < MAX_POLLS)) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <PageHeader title="Результат теста" />
        <p role="status" className="type-body text-ink-muted">
          {ASSESSMENT.result.counting}
        </p>
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    )
  }
  if (!isResult(query.data)) {
    return (
      <>
        <PageHeader title="Результат теста" />
        <ErrorState
          title="Результат пока не готов"
          text="Подсчёт занимает больше обычного."
          onRetry={() => void query.refetch()}
          homeHref="/candidate/category"
        />
      </>
    )
  }
  return (
    <ResultBody
      result={query.data}
      visibility={consents.data?.visibility.state ?? null}
      publicationVersion={consents.data?.publication.current_version ?? null}
      refetchConsents={() => consents.refetch()}
    />
  )
}

function ResultBody({
  result,
  visibility,
  publicationVersion,
  refetchConsents,
}: {
  result: TestResultView
  visibility: string | null
  publicationVersion: string | null
  refetchConsents: () => Promise<unknown>
}) {
  const { icon: Icon, tone } = OUTCOME_VIEW[result.outcome]
  const wizardMode = visibility === 'not_ready' || visibility === 'unpublished'
  const published = visibility === 'visible' || visibility === 'paused'
  const confirmed = result.outcome === 'confirmed' || result.outcome === 'confirmed_with_margin'
  const hasCategory = result.category != null
  const recommended = result.next_actions.find((a) => a.recommended && a.available)
  const higher = result.next_actions.find((a) => a.kind === 'take_higher')
  const others = result.next_actions.filter((a) => a !== recommended && (confirmed ? a === higher : true))

  const flagKey = `result-animated:${result.session_id}`
  const [animate] = useState(() => {
    try {
      const seen = sessionStorage.getItem(flagKey) != null
      if (!seen) sessionStorage.setItem(flagKey, '1')
      return !seen
    } catch {
      return false
    }
  })

  const weak = result.skills.filter((s) => s.verdict !== 'confirmed')

  return (
    <div className="flex min-w-0 max-w-[880px] flex-col gap-6">
      {wizardMode ? <Stepper steps={WIZARD_STEPS.candidate} current="done" linkCompleted={false} /> : null}
      <PageHeader
        title={result.outcome_label}
        breadcrumbs={
          wizardMode ? undefined : [{ label: 'Категория и тесты', href: '/candidate/category' }, { label: 'Результат' }]
        }
        meta={
          <span className="type-sm text-ink-muted">
            {formatDate(result.finished_at)} ·{' '}
            <span className="num">
              {result.items_answered} зад. · {formatDuration(result.duration_s)}
            </span>
          </span>
        }
      />

      <section className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6" aria-label="Исход теста">
        <div className="flex min-w-0 flex-wrap items-center gap-3">
          <Icon className={cn('size-8 shrink-0', tone)} aria-hidden="true" />
          {result.category ? <CategoryChip title={result.category.title} size="lg" /> : null}
          <span className="type-sm min-w-0 text-ink-muted">{result.target.title}</span>
        </div>
        {result.status === 'expired' ? <p className="type-sm">{ASSESSMENT.result.expiredNote}</p> : null}
        {!confirmed ? (
          <p className="type-sm min-w-0">
            {ASSESSMENT.result.notLowered}
            {!hasCategory ? ` ${ASSESSMENT.result.notVisible}` : ''}
          </p>
        ) : null}
      </section>

      <section className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6" aria-labelledby="r-level">
        <h2 id="r-level" className="type-h3">
          {ASSESSMENT.result.level}
        </h2>
        <LevelScale level={result.level} size="md" ownGrade={result.target.grade.code} animate={animate} />
        <p className="type-caption min-w-0 text-ink-muted">{ASSESSMENT.result.interval}</p>
      </section>

      <section className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6" aria-labelledby="r-topics">
        <h2 id="r-topics" className="type-h3">
          {ASSESSMENT.result.topics}
        </h2>
        <ul className="flex min-w-0 flex-col divide-y divide-line">
          {result.skills.map((s) => {
            const VIcon = VERDICT_ICON[s.verdict]
            return (
              <li
                key={s.group_code}
                className="flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2"
              >
                <span className="type-body min-w-0 break-words">{s.label}</span>
                <span className="type-sm flex min-w-0 items-center gap-2">
                  <VIcon className={cn('size-4 shrink-0', VERDICT_TONE[s.verdict])} aria-hidden="true" />
                  <span>{ASSESSMENT.result.verdicts[s.verdict]}</span>
                  <span className="num text-ink-muted">· {s.items}</span>
                </span>
              </li>
            )
          })}
        </ul>
        {result.notes.length > 0 ? (
          <ul className="type-sm flex min-w-0 list-disc flex-col gap-1 pl-5 text-ink-muted">
            {result.notes.map((n) => (
              <li key={n} className="min-w-0 break-words">
                {n}
              </li>
            ))}
          </ul>
        ) : null}
        <p className="type-caption min-w-0 text-ink-muted">{ASSESSMENT.result.topicsNote}</p>
        {!confirmed && weak.length > 0 ? (
          <p className="type-sm min-w-0 break-words">Темы для повторения: {weak.map((s) => s.label).join(', ')}</p>
        ) : null}
      </section>

      <section className="flex min-w-0 flex-col gap-3" aria-labelledby="r-next">
        <h2 id="r-next" className="type-h3">
          {ASSESSMENT.result.next}
        </h2>
        <div className="flex min-w-0 flex-wrap items-start gap-3">
          {confirmed ? (
            published || !hasCategory ? (
              <Button variant="primary" asChild>
                <Link to="/candidate">{ASSESSMENT.result.toCabinet}</Link>
              </Button>
            ) : null
          ) : recommended ? (
            <NextActionButton action={recommended} primary />
          ) : (
            <Button variant="primary" asChild>
              <Link to="/candidate">{ASSESSMENT.result.toCabinet}</Link>
            </Button>
          )}
          {!hasCategory && !confirmed ? (
            <Button variant="secondary" asChild>
              <Link to="/candidate/settings/fsp">Привязать ФСП ID</Link>
            </Button>
          ) : null}
        </div>
        <NextActionList actions={others as NextAction[]} />
      </section>

      {hasCategory && visibility === 'unpublished' ? (
        <PublishCard version={publicationVersion} refetchConsents={refetchConsents} />
      ) : null}
    </div>
  )
}

function PublishCard({
  version,
  refetchConsents,
}: {
  version: string | null
  refetchConsents: () => Promise<unknown>
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
      className="surface-card flex min-w-0 scroll-mt-24 flex-col gap-3 p-4 md:p-6"
      aria-labelledby="r-publish"
    >
      <h2 id="r-publish" className="type-h3">
        {ASSESSMENT.result.publishTitle}
      </h2>
      <p className="type-sm min-w-0">{ASSESSMENT.result.publishText}</p>
      <Link to="/candidate/settings/privacy" className="text-link type-sm w-fit">
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
