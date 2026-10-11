import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  BadgeCheck,
  Braces,
  Briefcase,
  Building2,
  CalendarCheck,
  ChevronRight,
  ChevronsUp,
  CircleCheck,
  CircleDashed,
  CircleX,
  ClipboardList,
  Code,
  Compass,
  Gauge,
  History,
  Hourglass,
  ListChecks,
  type LucideIcon,
  PencilLine,
  Play,
  RefreshCw,
  RotateCw,
  Ruler,
  ShieldCheck,
  Timer,
  Trophy,
} from 'lucide-react'
import type { Catalog, Contribution, EvidenceKind, HistoryItem, TestOutcome } from '@/client'
import {
  CategoryChip,
  ContributionBars,
  ErrorState,
  EvidenceChip,
  GoChevron,
  IconTile,
  LevelScale,
  PageHeader,
  Section,
  SoftPill,
  StatusBadge,
  StrengthPill,
  type TileTone,
} from '@/components/app'
import { Alert } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { STRENGTH_SUMMARY } from '@/content/common'
import { hasTest, isDeclared } from '@/lib/category'
import { formatAgo, formatDate, formatDecimal, formatDuration } from '@/lib/format'
import { assessmentStateQuery } from '@/lib/query'
import { cn } from '@/lib/utils'
import { consentsQuery, evidenceQuery, historyQuery, surveyQuery } from '../api'
import { ASSESSMENT } from '../content'
import { DeclaredGradeForm } from './declared-grade-form'
import { NextActionList, nextActionLabel } from './next-actions'
import { CardHead, specIcon } from './parts'
import { PublishCard } from './publish-panel'

const OUTCOME_TILE: Record<TestOutcome, { icon: LucideIcon; tone: TileTone }> = {
  confirmed: { icon: CircleCheck, tone: 'success' },
  confirmed_with_margin: { icon: ChevronsUp, tone: 'success' },
  borderline: { icon: CircleDashed, tone: 'warning' },
  // «Не подтверждён» — нейтральный, не красный: грейд автоматически не понижается.
  not_confirmed: { icon: CircleX, tone: 'neutral' },
}

/** История карточками: плитка исхода, событие с датой, исход пилюлей, объём и время; тест ведёт на результат. */
function HistoryRows({ items }: { items: HistoryItem[] }) {
  if (items.length === 0) return <p className="type-sm text-ink-muted">{ASSESSMENT.category.historyEmpty}</p>
  return (
    <ol className="flex min-w-0 flex-col gap-2">
      {items.map((h, i) => {
        const view = h.outcome ? OUTCOME_TILE[h.outcome] : null
        const linked = h.kind === 'test' && h.session_id != null
        return (
          <li
            key={`${h.kind}-${h.session_id ?? h.at}`}
            style={{ '--i': i } as React.CSSProperties}
            className={cn(
              'surface-row stagger relative flex min-w-0 animate-rise-in items-center gap-3 p-3 md:px-4',
              linked && 'lift-card',
            )}
          >
            <IconTile
              icon={view?.icon ?? (h.kind === 'survey' ? ClipboardList : ListChecks)}
              tone={view?.tone ?? 'soft'}
            />
            <div className="flex min-w-0 flex-1 flex-col gap-x-4 gap-y-1.5 sm:flex-row sm:items-center">
              <span className="flex min-w-0 flex-col sm:w-40 sm:shrink-0">
                <span className="min-w-0 break-words font-medium text-ink">{h.title}</span>
                <span className="num type-caption text-ink-muted">{formatDate(h.at)}</span>
              </span>
              <span className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
                {h.outcome ? <StatusBadge status={h.outcome} label={h.outcome_label ?? h.outcome} size="sm" /> : null}
                {h.items != null ? (
                  <SoftPill size="sm" icon={ListChecks}>
                    <span className="num">{h.items} зад.</span>
                  </SoftPill>
                ) : null}
                {h.duration_s != null ? (
                  <SoftPill size="sm" icon={Timer}>
                    <span className="num">{formatDuration(h.duration_s)}</span>
                  </SoftPill>
                ) : null}
              </span>
            </div>
            {linked && h.session_id ? (
              <>
                <Link
                  to="/candidate/test/$sessionId/result"
                  params={{ sessionId: h.session_id }}
                  className="type-sm shrink-0 font-medium text-brand-700 after:absolute after:inset-0 after:z-[1] after:rounded-md after:content-['']"
                >
                  <span className="max-sm:sr-only">{ASSESSMENT.category.result}</span>
                  <ChevronRight aria-hidden="true" className="size-5 sm:hidden" />
                </Link>
                <GoChevron />
              </>
            ) : null}
          </li>
        )
      })}
    </ol>
  )
}

/** Суммы баллов по источнику строки: подтверждено платформой и заявлено кандидатом. */
function strengthTotals(items: readonly Contribution[]): { confirmed: number; declared: number } | null {
  if (!items.some((item) => item.source != null)) return null
  const sum = (source: 'confirmed' | 'declared') =>
    Math.max(0, Math.round(items.filter((i) => i.source === source).reduce((acc, i) => acc + i.points, 0) * 10) / 10)
  return { confirmed: sum('confirmed'), declared: sum('declared') }
}

/** Половина итога силы профиля: подтверждённое — зелёная плитка, заявленное — пунктирная. */
function SplitTile({
  icon,
  label,
  value,
  of,
  confirmed = false,
}: {
  icon: LucideIcon
  label: string
  value: number
  of: string
  confirmed?: boolean
}) {
  return (
    <li
      className={cn(
        'flex min-w-0 flex-1 items-center gap-3 rounded-md border p-3',
        confirmed ? 'border-transparent bg-success-bg' : 'border-dashed border-line-strong',
      )}
    >
      <IconTile icon={icon} tone={confirmed ? 'plain' : 'neutral'} className={confirmed ? 'text-success' : undefined} />
      <span className="flex min-w-0 flex-col">
        <span className="type-caption text-ink">{label}</span>{' '}
        <span className="min-w-0">
          <span className="num text-2xl leading-7 font-semibold text-ink">{formatDecimal(value)}</span>{' '}
          <span className="num type-caption text-ink">{of}</span>
        </span>
      </span>
    </li>
  )
}

/** Кандидат на своём экране: подписи сервера и общего словаря «кандидатом» читаются как «вами». */
const selfText = (text: string) => text.replace(/кандидатом/g, 'вами')

/** Значки ответов опроса — те же, что у вопросов в самом опросе. */
const SURVEY_ICONS: Record<string, LucideIcon> = {
  direction: Compass,
  specialization: Code,
  main_language: Braces,
  experience_band: Briefcase,
  industry_domains: Building2,
}

type SkillGroup = 'test' | 'fsp' | 'declared' | 'none'
const SKILL_GROUP: Record<EvidenceKind, SkillGroup> = {
  test: 'test',
  pulse: 'test',
  fsp: 'fsp',
  declared: 'declared',
  none: 'none',
}
const SKILL_GROUP_VIEW: Record<SkillGroup, { icon: LucideIcon; tone: TileTone }> = {
  test: { icon: BadgeCheck, tone: 'brand' },
  fsp: { icon: Trophy, tone: 'accent' },
  declared: { icon: PencilLine, tone: 'dashed' },
  none: { icon: CircleDashed, tone: 'dashed' },
}
const SKILL_GROUP_ORDER: readonly SkillGroup[] = ['test', 'fsp', 'declared', 'none']

export function CategoryScreen({ catalog }: { catalog: Catalog | null }) {
  const state = useQuery(assessmentStateQuery)
  const history = useQuery(historyQuery)
  const evidence = useQuery(evidenceQuery)
  const survey = useQuery(surveyQuery)
  const consents = useQuery(consentsQuery)

  const failure = state.error ?? history.error
  if (failure) {
    return (
      <>
        <PageHeader title={ASSESSMENT.category.title} />
        <ErrorState
          error={failure}
          onRetry={() => {
            void state.refetch()
            void history.refetch()
          }}
          homeHref="/candidate"
        />
      </>
    )
  }
  if (!state.data || !history.data) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true">
        <PageHeader title={ASSESSMENT.category.title} />
        <Skeleton className="h-40 w-full" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-32 w-full" />
      </div>
    )
  }

  const s = state.data
  const level = s.level
  const actions = s.next_actions ?? []
  const lastWeak =
    s.last_session && (s.last_session.outcome === 'borderline' || s.last_session.outcome === 'not_confirmed')
  const strengthItems = evidence.data?.strength?.contributions.filter((c) => c.group === 'strength') ?? []
  const retryDays = Number(catalog?.limits.assessment_retry_same_grade_days ?? 14)
  const changeDays = Number(catalog?.limits.assessment_grade_change_cooldown_days ?? 90)

  // Грейд заявлен (теста по специализации нет): уровня и шкалы нет, вместо пересдачи — форма заявленного грейда.
  const D = ASSESSMENT.category.declared
  const declared = isDeclared(s.category, catalog)
  const specialization = s.specialization ?? s.category?.specialization ?? null
  const noTest = specialization != null && !hasTest(catalog, specialization.code)
  const declaredHere = declared && s.category?.specialization.code === specialization?.code

  const actionsNode = s.active_session ? (
    <Button variant="primary" asChild>
      <Link to="/candidate/test/$sessionId" params={{ sessionId: s.active_session.id }}>
        {ASSESSMENT.category.continue}
      </Link>
    </Button>
  ) : undefined

  const answers = survey.data?.answers
  const surveyRows = survey.data
    ? survey.data.questions
        .map((q) => {
          const a = answers?.[q.id]
          if (a == null) return null
          const codes = Array.isArray(a) ? a : [a]
          if (codes.length === 0) return null
          const titles = codes.map((c) => q.options.find((o) => o.code === c)?.title ?? c)
          return { id: q.id, title: q.title, value: titles.join(', ') }
        })
        .filter((r): r is { id: string; title: string; value: string } => r != null)
    : []

  const totals = strengthTotals(strengthItems)
  const skills = evidence.data?.skills ?? []
  const skillGroups = SKILL_GROUP_ORDER.map((group) => ({
    group,
    items: skills.filter((sk) => SKILL_GROUP[sk.kind] === group),
  })).filter((g) => g.items.length > 0)
  const HeroIcon = specIcon(specialization?.code)
  const lastOutcome = s.last_session?.outcome ?? null
  const heroAction = !s.category && !s.active_session ? actions.find((a) => a.recommended && a.available) : undefined

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader title={ASSESSMENT.category.title} actions={actionsNode} />

      <section
        className={cn('surface-card flex min-w-0 animate-rise-in flex-col gap-4', !declared && 'accent-card')}
        aria-labelledby="c-current"
      >
        <div className="flex min-w-0 items-start gap-3 md:gap-4">
          <IconTile
            icon={s.category ? HeroIcon : CircleDashed}
            tone={!s.category || declared ? 'dashed' : 'solid'}
            size="xl"
          />
          <div className="flex min-w-0 flex-1 flex-col gap-2">
            <h2 id="c-current" className="type-eyebrow">
              {declared ? D.current : ASSESSMENT.category.current}
            </h2>
            {s.category ? (
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <CategoryChip title={s.category.title} size="lg" declared={declared} />
              </div>
            ) : (
              <>
                <p className="type-h2 min-w-0">{ASSESSMENT.category.none}</p>
                {lastOutcome ? (
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    <StatusBadge
                      status={lastOutcome}
                      label={
                        history.data.find((h) => h.session_id === s.last_session?.id)?.outcome_label ??
                        ASSESSMENT.category.none
                      }
                    />
                    {s.last_session ? (
                      <SoftPill icon={CalendarCheck}>
                        <span className="num">
                          {ASSESSMENT.category.tested(formatDate(s.last_session.finished_at))}
                        </span>
                      </SoftPill>
                    ) : null}
                  </div>
                ) : null}
              </>
            )}
          </div>
        </div>

        {s.category && declared ? (
          <>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="type-sm inline-flex min-h-7 min-w-0 items-center gap-1.5 rounded-full bg-fill px-2.5 py-0.5 text-ink">
                <Hourglass aria-hidden="true" className="size-4 shrink-0 text-ink-muted" />
                <span className="min-w-0">{D.line(formatDate(s.category.assigned_at))}</span>
              </span>
            </div>
            <p className="type-sm flex min-w-0 items-start gap-2.5 rounded-md border border-dashed border-line-strong p-3 text-ink">
              <Ruler aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-ink-muted" />
              <span className="min-w-0">
                {D.noLevel}. {D.explain}
              </span>
            </p>
          </>
        ) : s.category && level ? (
          <>
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <StatusBadge status={level.verdict} label={level.verdict_label} />
              <SoftPill icon={CalendarCheck}>
                <span className="num">{ASSESSMENT.category.tested(formatDate(level.tested_at))}</span>
              </SoftPill>
              <SoftPill icon={ShieldCheck} tone={level.stale ? 'warning' : 'neutral'}>
                <span className="num">{ASSESSMENT.category.evidenced(formatAgo(level.last_evidence_at))}</span>
              </SoftPill>
              {level.stale ? (
                <SoftPill tone="warning" icon={Hourglass}>
                  {ASSESSMENT.category.stale}
                </SoftPill>
              ) : null}
            </div>
            <LevelScale level={level} size="md" ownGrade={s.category.grade.code} showVerdict={false} />
            {lastWeak ? (
              <p className="type-sm flex min-w-0 items-start gap-2.5 rounded-md border border-dashed border-line-strong p-3 text-ink">
                <ShieldCheck aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-success" />
                <span className="min-w-0">{ASSESSMENT.category.keptShort}</span>
              </p>
            ) : null}
            {s.category.is_demo_result ? <Alert variant="info">{ASSESSMENT.category.demo}</Alert> : null}
          </>
        ) : (
          <>
            {heroAction ? (
              <div>
                <Button variant="primary" asChild>
                  <Link to="/candidate/test/new" search={{ grade: heroAction.grade.code }}>
                    <Play aria-hidden="true" />
                    {nextActionLabel(heroAction)}
                  </Link>
                </Button>
              </div>
            ) : null}
            {actions.length === 0 && !s.active_session && s.claimed_grade && !noTest ? (
              <div>
                <Button variant="primary" asChild>
                  <Link to="/candidate/test/new" search={{ grade: s.claimed_grade.code }}>
                    Пройти тест на {s.claimed_grade.title}
                  </Link>
                </Button>
              </div>
            ) : null}
          </>
        )}
      </section>

      {declared && consents.data?.visibility.state === 'unpublished' ? (
        <PublishCard
          declared
          version={consents.data.publication.current_version ?? null}
          refetchConsents={() => consents.refetch()}
        />
      ) : null}

      {noTest && specialization ? (
        <section className="surface-card flex min-w-0 flex-col gap-4" aria-labelledby="c-change">
          <CardHead id="c-change" icon={PencilLine} tone="neutral" title={D.formTitle} />
          <DeclaredGradeForm
            key={`${s.category?.code ?? 'none'}:${s.category?.change_available_at ?? ''}`}
            catalog={catalog}
            specialization={specialization.title}
            current={
              declaredHere && s.category
                ? {
                    gradeCode: s.category.grade.code,
                    assignedAt: s.category.assigned_at,
                    changeAvailableAt: s.category.change_available_at,
                  }
                : null
            }
            replaces={s.category != null && !declaredHere}
          />
        </section>
      ) : (
        <section className="flex min-w-0 flex-col gap-3" aria-labelledby="c-change">
          <h2 id="c-change" className="type-eyebrow flex min-w-0 items-center gap-1.5">
            <RefreshCw aria-hidden="true" className="size-3.5 text-brand-700" />
            {ASSESSMENT.category.change}
          </h2>
          {/* Специализацию сменили, грейд ещё не выбран: действий сервер не предлагает, а шаг выбора доступен. */}
          {s.survey_completed && !s.claimed_grade && !s.active_session && actions.length === 0 ? (
            <Button variant="primary" className="self-start" asChild>
              <Link to="/candidate/onboarding/grade">{ASSESSMENT.category.pickGrade}</Link>
            </Button>
          ) : null}
          <NextActionList actions={actions} />
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <SoftPill size="sm" icon={RefreshCw}>
              <span className="num">{ASSESSMENT.category.changeEvery(changeDays)}</span>
            </SoftPill>
            <SoftPill size="sm" icon={RotateCw}>
              <span className="num">{ASSESSMENT.category.retryAfter(retryDays)}</span>
            </SoftPill>
          </div>
        </section>
      )}

      {s.category ? (
        <>
          <section className="surface-card flex min-w-0 flex-col gap-4" aria-labelledby="c-strength">
            <CardHead
              id="c-strength"
              icon={Gauge}
              title={ASSESSMENT.category.strength}
              aside={
                evidence.data?.strength ? <StrengthPill strength={evidence.data.strength.label} size="md" /> : null
              }
            />
            {evidence.isError ? (
              <ErrorState compact error={evidence.error} onRetry={() => evidence.refetch()} />
            ) : !evidence.data ? (
              <Skeleton className="h-16 w-full" />
            ) : (
              <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,17rem)_minmax(0,1fr)] lg:gap-6">
                {totals ? (
                  <ul data-slot="contribution-summary" className="flex min-w-0 flex-col gap-2 sm:flex-row lg:flex-col">
                    <SplitTile
                      confirmed
                      icon={BadgeCheck}
                      label={STRENGTH_SUMMARY.confirmed}
                      value={totals.confirmed}
                      of={STRENGTH_SUMMARY.confirmedOf}
                    />
                    <SplitTile
                      icon={PencilLine}
                      label={selfText(STRENGTH_SUMMARY.declared)}
                      value={totals.declared}
                      of={STRENGTH_SUMMARY.declaredOf}
                    />
                  </ul>
                ) : null}
                <ContributionBars
                  items={strengthItems.map((c) => ({ ...c, label: selfText(c.label) }))}
                  className={totals ? undefined : 'lg:col-span-2'}
                />
              </div>
            )}
          </section>

          <section className="surface-card flex min-w-0 flex-col gap-4" aria-labelledby="c-skills">
            <CardHead
              id="c-skills"
              icon={BadgeCheck}
              tone="soft"
              title={ASSESSMENT.category.skills}
              aside={
                skills.length > 0 ? (
                  <SoftPill tone="brand">
                    <span className="num font-semibold">{skills.length}</span>
                  </SoftPill>
                ) : null
              }
            />
            {skillGroups.length > 0 ? (
              <div className="flex min-w-0 flex-col gap-4">
                {skillGroups.map(({ group, items }) => {
                  const view = SKILL_GROUP_VIEW[group]
                  const groupId = `c-skills-${group}`
                  return (
                    <div key={group} className="flex min-w-0 flex-col gap-2 md:flex-row md:items-start md:gap-4">
                      <h3
                        id={groupId}
                        className="type-sm flex min-w-0 items-center gap-2 font-medium md:w-36 md:shrink-0"
                      >
                        <IconTile icon={view.icon} tone={view.tone} size="xs" />
                        <span className="min-w-0">{ASSESSMENT.category.skillGroups[group]}</span>
                        <span className="num text-ink-muted">{items.length}</span>
                      </h3>
                      <ul aria-labelledby={groupId} className="flex min-w-0 flex-1 flex-wrap gap-2">
                        {items.map((sk) => (
                          <li key={sk.skill.code} className="min-w-0 max-w-full" title={sk.detail ?? undefined}>
                            <EvidenceChip
                              kind={sk.kind}
                              skill={sk.skill.title}
                              label={selfText(sk.kind_label)}
                              showLabel={false}
                            />
                            {sk.detail ? <span className="sr-only"> — {sk.detail}</span> : null}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )
                })}
              </div>
            ) : (
              <p className="type-sm text-ink-muted">
                {!evidence.data ? 'Загрузка…' : declared ? D.skillsEmpty : 'Подтверждённых навыков пока нет'}
              </p>
            )}
          </section>
        </>
      ) : null}

      {surveyRows.length > 0 ? (
        <section className="surface-card flex min-w-0 flex-col gap-4" aria-labelledby="c-survey">
          <CardHead
            id="c-survey"
            icon={ClipboardList}
            tone="soft"
            title={ASSESSMENT.category.survey}
            aside={
              // Опрос недоступен, пока идёт тест: охрана всё равно вернула бы на экран теста.
              s.active_session ? undefined : (
                <Link to="/candidate/onboarding/survey" className="text-link tap-target type-sm">
                  {ASSESSMENT.category.changeSpecialization}
                </Link>
              )
            }
          />
          <dl className="flex min-w-0 flex-wrap gap-2">
            {surveyRows.map((r) => (
              <div key={r.id} className="flex min-w-0 max-w-full">
                <dt className="sr-only">{r.title}</dt>
                <dd className="flex min-w-0 max-w-full">
                  <SoftPill icon={SURVEY_ICONS[r.id] ?? ClipboardList} tone="brand" title={`${r.title}: ${r.value}`}>
                    <span className="min-w-0 truncate">{r.value}</span>
                  </SoftPill>
                </dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      <Section title={ASSESSMENT.category.history} icon={History} iconTone="brand">
        <HistoryRows items={history.data} />
      </Section>
    </div>
  )
}
