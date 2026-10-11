import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  BadgeCheck,
  CalendarCheck,
  ChevronsUp,
  CircleCheck,
  CircleDashed,
  CircleX,
  Compass,
  Info,
  LayoutList,
  ListChecks,
  type LucideIcon,
  ShieldCheck,
  Timer,
  Trophy,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import type { NextAction, SkillVerdict, TestOutcome, TestResultView } from '@/client'
import {
  CandidateCategoryChip,
  CHART,
  type ChartColor,
  ErrorState,
  IconTile,
  LegendList,
  LevelScale,
  PageHeader,
  ProgressRing,
  SoftPill,
  StatTile,
  Stepper,
  type TileTone,
  type Tone,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { WIZARD_STEPS } from '@/content/common'
import { isDeclared } from '@/lib/category'
import { formatDate, formatDuration, PLURALS, plural } from '@/lib/format'
import { catalogQuery } from '@/lib/query'
import { cn } from '@/lib/utils'
import { consentsQuery, isResult, resultQuery } from '../api'
import { ASSESSMENT } from '../content'
import { LinkActionCard, NextActionList } from './next-actions'
import { PublishCard } from './publish-panel'

/*
 * Тон героя по исходу. «Не подтверждён» — нейтральный, не красный: грейд автоматически не понижается,
 * и тот же исход нейтрален в StatusBadge на всех экранах.
 */
const OUTCOME_VIEW: Record<TestOutcome, { icon: LucideIcon; tone: TileTone; wash: string }> = {
  confirmed: { icon: CircleCheck, tone: 'success', wash: 'var(--color-success)' },
  confirmed_with_margin: { icon: ChevronsUp, tone: 'success', wash: 'var(--color-success)' },
  borderline: { icon: CircleDashed, tone: 'warning', wash: 'var(--color-warning)' },
  not_confirmed: { icon: CircleX, tone: 'neutral', wash: 'var(--color-line-strong)' },
}

/*
 * У темы есть только вердикт, балла нет: полоса — три равные ступени (закрашено 3, 2 или 1),
 * а не доля, которую можно принять за измеренный процент.
 */
const VERDICT_VIEW: Record<SkillVerdict, { icon: LucideIcon; tone: Tone; color: ChartColor; steps: number }> = {
  confirmed: { icon: CircleCheck, tone: 'success', color: 'success', steps: 3 },
  partial: { icon: CircleDashed, tone: 'warning', color: 'warning', steps: 2 },
  not_confirmed: { icon: CircleX, tone: 'neutral', color: 'neutral', steps: 1 },
}
const STEPS = [1, 2, 3] as const
const VERDICT_ORDER: readonly SkillVerdict[] = ['confirmed', 'partial', 'not_confirmed']
const VERDICT_TEXT: Record<Tone, string> = {
  brand: 'text-brand-700',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
  neutral: 'text-ink-muted',
}

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
  const view = OUTCOME_VIEW[result.outcome]
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

  const counts = VERDICT_ORDER.map((verdict) => ({
    verdict,
    value: result.skills.filter((sk) => sk.verdict === verdict).length,
  }))
  const confirmedTopics = counts[0]?.value ?? 0
  const bindFsp = !hasCategory && !confirmed

  return (
    <div className="flex min-w-0 flex-col gap-6">
      {wizardMode ? <Stepper steps={WIZARD_STEPS.candidate} current="done" linkCompleted={false} /> : null}
      <PageHeader
        title={result.outcome_label}
        breadcrumbs={
          wizardMode ? undefined : [{ label: 'Категория и тесты', href: '/candidate/category' }, { label: 'Результат' }]
        }
      />

      <section
        className="surface-card relative flex min-w-0 flex-col gap-5 overflow-hidden"
        style={{
          backgroundImage: `linear-gradient(150deg, color-mix(in srgb, ${view.wash} 12%, var(--color-surface)), var(--color-surface) 52%)`,
        }}
        aria-label="Исход теста"
      >
        <span
          aria-hidden="true"
          className="absolute inset-x-0 top-0 h-[3px]"
          style={{
            background: `linear-gradient(90deg, ${view.wash}, color-mix(in srgb, ${view.wash} 20%, var(--color-surface)))`,
          }}
        />
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3">
          <IconTile
            icon={view.icon}
            tone={view.tone}
            size="xl"
            className={cn(
              animate && 'animate-pop-in',
              // На сером градиенте героя обычная нейтральная заливка не видна — берём плотнее.
              view.tone === 'neutral' &&
                'bg-[color-mix(in_srgb,var(--color-line-strong)_32%,var(--color-surface))] text-ink',
            )}
          />
          <div className="flex min-w-[14rem] flex-1 flex-col gap-2">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              {result.category ? (
                <span className={cn('inline-flex min-w-0', animate && 'animate-stamp stagger [--i:3]')}>
                  <CandidateCategoryChip category={result.category} size="lg" />
                </span>
              ) : null}
              {confirmed && hasCategory ? (
                <SoftPill tone="success" icon={BadgeCheck}>
                  {ASSESSMENT.result.confirmedByTest}
                </SoftPill>
              ) : null}
            </div>
            {/* Цель теста совпала с категорией — чип уже её назвал. */}
            {result.category?.code === result.target.code ? null : (
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <SoftPill icon={ListChecks}>{result.target.title}</SoftPill>
              </div>
            )}
          </div>
        </div>

        <ul aria-label={ASSESSMENT.result.summary} className="flex min-w-0 flex-wrap gap-x-8 gap-y-3">
          <li className="min-w-0">
            <StatTile icon={CalendarCheck} value={formatDate(result.finished_at)} label="завершён" tone="plain" />
          </li>
          <li className="min-w-0">
            <StatTile
              icon={ListChecks}
              value={result.items_answered}
              label={plural(result.items_answered, PLURALS.task)}
              tone="plain"
            />
          </li>
          <li className="min-w-0">
            <StatTile icon={Timer} value={formatDuration(result.duration_s)} label="время" tone="plain" />
          </li>
        </ul>

        <LevelScale
          level={result.level}
          size="md"
          ownGrade={result.target.grade.code}
          animate={animate}
          showVerdict={false}
        />

        {result.status === 'expired' || !confirmed ? (
          <ul className="flex min-w-0 flex-col gap-2">
            {result.status === 'expired' ? (
              <li className="type-sm flex min-w-0 items-start gap-2.5 text-ink">
                <IconTile icon={Timer} tone="warning" size="xs" />
                <span className="min-w-0 pt-1">{ASSESSMENT.result.expiredNote}</span>
              </li>
            ) : null}
            {!confirmed ? (
              <li className="type-sm flex min-w-0 items-start gap-2.5 text-ink">
                <IconTile icon={ShieldCheck} tone="success" size="xs" />
                <span className="min-w-0 pt-1">
                  {ASSESSMENT.result.notLowered}
                  {!hasCategory ? ` ${ASSESSMENT.result.notVisible}` : ''}
                </span>
              </li>
            ) : null}
          </ul>
        ) : null}
      </section>

      <section className="surface-card flex min-w-0 flex-col gap-5" aria-labelledby="r-topics">
        <div className="flex min-w-0 items-center gap-3">
          <IconTile icon={LayoutList} />
          <h2 id="r-topics" className="type-h3 min-w-0 flex-1">
            {ASSESSMENT.result.topics}
          </h2>
        </div>
        <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)]">
          <div className="flex min-w-0 flex-col items-center gap-4 sm:flex-row lg:flex-col lg:items-stretch">
            <ProgressRing
              label={`${ASSESSMENT.result.topicsRing}: ${counts
                .map((c) => `${ASSESSMENT.result.verdicts[c.verdict]} — ${c.value}`)
                .join(', ')}`}
              segments={counts.map((c) => ({ key: c.verdict, value: c.value, color: VERDICT_VIEW[c.verdict].color }))}
              className={cn('size-28 lg:mx-auto lg:size-32', animate && 'animate-pop-in')}
            >
              <span className="flex flex-col items-center" aria-hidden="true">
                <span className="num text-2xl leading-7 font-semibold text-ink">{confirmedTopics}</span>
                <span className="num type-caption text-ink-muted">
                  {ASSESSMENT.result.topicsOf(result.skills.length)}
                </span>
              </span>
            </ProgressRing>
            <LegendList
              items={counts.map((c) => ({
                key: c.verdict,
                label: ASSESSMENT.result.verdicts[c.verdict],
                value: c.value,
                icon: VERDICT_VIEW[c.verdict].icon,
                tone: VERDICT_VIEW[c.verdict].tone,
                color: VERDICT_VIEW[c.verdict].color,
              }))}
              className="max-sm:w-full max-sm:flex-none"
            />
          </div>
          <ul className="grid min-w-0 content-start gap-x-6 gap-y-4 sm:grid-cols-2">
            {result.skills.map((sk, i) => {
              const v = VERDICT_VIEW[sk.verdict]
              return (
                <li
                  key={sk.group_code}
                  style={{ '--i': i } as React.CSSProperties}
                  className={cn('flex min-w-0 flex-col gap-1.5', animate && 'animate-rise-in stagger')}
                >
                  <span className="type-sm min-w-0 break-words font-medium text-ink">{sk.label}</span>
                  <span aria-hidden="true" className="grid grid-cols-3 gap-1">
                    {STEPS.map((step) => (
                      <span
                        key={step}
                        className={cn(
                          'block h-2 rounded-full',
                          step <= v.steps ? animate && 'stagger origin-left animate-grow-x' : 'bg-fill',
                        )}
                        style={
                          step <= v.steps
                            ? ({ backgroundColor: CHART[v.color], '--i': i * 2 + step } as React.CSSProperties)
                            : undefined
                        }
                      />
                    ))}
                  </span>
                  <span className="type-caption flex min-w-0 items-center justify-between gap-2">
                    <span className={cn('inline-flex min-w-0 items-center gap-1', VERDICT_TEXT[v.tone])}>
                      <v.icon aria-hidden="true" className="size-3.5 shrink-0" />
                      {ASSESSMENT.result.verdicts[sk.verdict]}
                    </span>
                    <span className="num text-ink-muted">
                      {sk.items} {ASSESSMENT.result.itemsShort}
                    </span>
                  </span>
                </li>
              )
            })}
          </ul>
        </div>
        {result.notes.length > 0 ? (
          <ul aria-label={ASSESSMENT.result.notesTitle} className="flex min-w-0 flex-col gap-2">
            {result.notes.map((n) => (
              <li key={n} className="type-sm flex min-w-0 items-start gap-2.5 text-ink">
                <IconTile icon={Info} tone="neutral" size="xs" />
                <span className="min-w-0 break-words pt-1">{n}</span>
              </li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="flex min-w-0 flex-col gap-3" aria-labelledby="r-next">
        <h2 id="r-next" className="type-eyebrow flex min-w-0 items-center gap-1.5">
          <Compass aria-hidden="true" className="size-3.5 text-brand-700" />
          {ASSESSMENT.result.next}
        </h2>
        <NextActionList
          actions={(recommended && !confirmed ? [recommended, ...others] : others) as NextAction[]}
          extraCount={bindFsp ? 1 : 0}
          extra={
            bindFsp ? (
              <LinkActionCard icon={Trophy} tone="accent" index={result.next_actions.length}>
                <Link to="/candidate/settings/fsp">{ASSESSMENT.result.bind}</Link>
              </LinkActionCard>
            ) : null
          }
        />
        <div className="flex min-w-0 flex-wrap items-start gap-3 empty:hidden">
          {confirmed ? (
            published || !hasCategory || visibility == null ? (
              <Button variant="primary" asChild>
                <Link to="/candidate">{ASSESSMENT.result.toCabinet}</Link>
              </Button>
            ) : null
          ) : recommended ? null : (
            <Button variant="primary" asChild>
              <Link to="/candidate">{ASSESSMENT.result.toCabinet}</Link>
            </Button>
          )}
        </div>
      </section>

      {hasCategory && visibility === 'unpublished' ? (
        <PublishCard version={publicationVersion} refetchConsents={refetchConsents} declared={declared} />
      ) : null}
    </div>
  )
}
