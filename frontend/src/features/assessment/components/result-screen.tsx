import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronsUp, CircleCheck, CircleDashed, CircleX, type LucideIcon } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { NextAction, TestOutcome, TestResultView } from '@/client'
import { CandidateCategoryChip, ErrorState, LevelScale, PageHeader, Section, Stepper } from '@/components/app'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { WIZARD_STEPS } from '@/content/common'
import { isDeclared } from '@/lib/category'
import { formatDate, formatDuration } from '@/lib/format'
import { catalogQuery } from '@/lib/query'
import { cn } from '@/lib/utils'
import { consentsQuery, isResult, resultQuery } from '../api'
import { ASSESSMENT } from '../content'
import { NextActionButton, NextActionList } from './next-actions'
import { PublishCard } from './publish-panel'

const OUTCOME_VIEW: Record<TestOutcome, { icon: LucideIcon; tone: string }> = {
  confirmed: { icon: CircleCheck, tone: 'text-success' },
  confirmed_with_margin: { icon: ChevronsUp, tone: 'text-success' },
  borderline: { icon: CircleDashed, tone: 'text-warning' },
  not_confirmed: { icon: CircleX, tone: 'text-ink-muted' },
}

const VERDICT_DOT = { confirmed: 'bg-success', partial: 'bg-warning', not_confirmed: 'bg-ink-subtle' } as const

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
  // Тест не подтвердил грейд, а прежняя категория — заявленная (по другой специализации): она так и помечается.
  const catalog = useQuery(catalogQuery).data
  const declared = isDeclared(result.category, catalog)
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

      <section className="flex min-w-0 flex-col gap-4" aria-label="Исход теста">
        {confirmed && hasCategory ? (
          <p className="type-eyebrow flex items-center gap-2">
            <span aria-hidden="true" className="size-1.5 rounded-full bg-fsp-red" />
            категория подтверждена тестом
          </p>
        ) : null}
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
          <Icon className={cn('size-8 shrink-0', tone, animate && 'animate-pop-in')} aria-hidden="true" />
          {result.category ? (
            <span className={cn('inline-flex', animate && 'animate-stamp stagger [--i:3]')}>
              <CandidateCategoryChip category={result.category} size="lg" />
            </span>
          ) : null}
          <span className="type-sm min-w-0 text-ink-muted">{result.target.title}</span>
        </div>
        {result.status === 'expired' ? <p className="type-sm">{ASSESSMENT.result.expiredNote}</p> : null}
        {!confirmed ? (
          <p className="type-sm min-w-0">
            {ASSESSMENT.result.notLowered}
            {!hasCategory ? ` ${ASSESSMENT.result.notVisible}` : ''}
          </p>
        ) : null}
        <LevelScale level={result.level} size="md" ownGrade={result.target.grade.code} animate={animate} />
      </section>

      <Section title={ASSESSMENT.result.topics}>
        <ul className="flex min-w-0 flex-col divide-y divide-line">
          {result.skills.map((s, i) => (
            <li
              key={s.group_code}
              style={{ '--i': i } as React.CSSProperties}
              className={cn(
                'flex min-w-0 flex-wrap items-center justify-between gap-x-4 gap-y-1 py-2.5',
                animate && 'animate-rise-in stagger',
              )}
            >
              <span className="type-body min-w-0 break-words">{s.label}</span>
              <span className="type-sm flex min-w-0 items-center gap-2">
                <span aria-hidden="true" className={cn('size-1.5 shrink-0 rounded-full', VERDICT_DOT[s.verdict])} />
                <span>{ASSESSMENT.result.verdicts[s.verdict]}</span>
                <span className="num text-ink-muted">{s.items}</span>
              </span>
            </li>
          ))}
        </ul>
        {result.notes.length > 0 ? (
          <ul className="type-sm mt-3 flex min-w-0 list-disc flex-col gap-1 pl-5 text-ink-muted">
            {result.notes.map((n) => (
              <li key={n} className="min-w-0 break-words">
                {n}
              </li>
            ))}
          </ul>
        ) : null}
        {!confirmed && weak.length > 0 ? (
          <p className="type-sm mt-3 min-w-0 break-words">Темы для повторения: {weak.map((s) => s.label).join(', ')}</p>
        ) : null}
      </Section>

      <Section title={ASSESSMENT.result.next}>
        <div className="flex min-w-0 flex-wrap items-start gap-3">
          {confirmed ? (
            published || !hasCategory || visibility == null ? (
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
      </Section>

      {hasCategory && visibility === 'unpublished' ? (
        <PublishCard version={publicationVersion} refetchConsents={refetchConsents} declared={declared} />
      ) : null}
    </div>
  )
}
