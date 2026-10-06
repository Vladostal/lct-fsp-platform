import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { Catalog, HistoryItem } from '@/client'
import {
  CategoryChip,
  ContributionBars,
  EmptyState,
  ErrorState,
  EvidenceChip,
  LevelScale,
  PageHeader,
  StatusBadge,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { formatAgo, formatDate, formatDuration } from '@/lib/format'
import { assessmentStateQuery } from '@/lib/query'
import { evidenceQuery, historyQuery, surveyQuery } from '../api'
import { ASSESSMENT } from '../content'
import { NextActionList } from './next-actions'

function HistoryRows({ items }: { items: HistoryItem[] }) {
  if (items.length === 0) return <p className="type-sm text-ink-muted">{ASSESSMENT.category.historyEmpty}</p>
  const detail = (h: HistoryItem) =>
    [h.items != null ? `${h.items} зад.` : null, h.duration_s != null ? formatDuration(h.duration_s) : null]
      .filter(Boolean)
      .join(' · ')
  return (
    <>
      <div className="hidden md:block">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Дата</TableHead>
              <TableHead>Событие</TableHead>
              <TableHead>Исход</TableHead>
              <TableHead>Заданий</TableHead>
              <TableHead>Длительность</TableHead>
              <TableHead>
                <span className="sr-only">Результат</span>
              </TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {items.map((h) => (
              <TableRow key={`${h.kind}-${h.session_id ?? h.at}`}>
                <TableCell className="num whitespace-nowrap">{formatDate(h.at)}</TableCell>
                <TableCell className="min-w-0 break-words">{h.title}</TableCell>
                <TableCell>
                  {h.outcome ? <StatusBadge status={h.outcome} label={h.outcome_label ?? h.outcome} size="sm" /> : '—'}
                </TableCell>
                <TableCell className="num">{h.items ?? '—'}</TableCell>
                <TableCell className="num whitespace-nowrap">
                  {h.duration_s != null ? formatDuration(h.duration_s) : '—'}
                </TableCell>
                <TableCell>
                  {h.kind === 'test' && h.session_id ? (
                    <Link
                      to="/candidate/test/$sessionId/result"
                      params={{ sessionId: h.session_id }}
                      className="text-link"
                    >
                      Результат
                    </Link>
                  ) : null}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      <ul className="flex flex-col gap-3 md:hidden">
        {items.map((h) => (
          <li
            key={`${h.kind}-${h.session_id ?? h.at}`}
            className="surface-row flex min-w-0 flex-col gap-1 rounded-md border border-line p-3"
          >
            <span className="flex min-w-0 flex-wrap items-center justify-between gap-2">
              <span className="min-w-0 break-words font-medium">{h.title}</span>
              <span className="num type-caption text-ink-muted">{formatDate(h.at)}</span>
            </span>
            <span className="flex min-w-0 flex-wrap items-center gap-2">
              {h.outcome ? <StatusBadge status={h.outcome} label={h.outcome_label ?? h.outcome} size="sm" /> : null}
              <span className="num type-caption text-ink-muted">{detail(h)}</span>
            </span>
            {h.kind === 'test' && h.session_id ? (
              <Link
                to="/candidate/test/$sessionId/result"
                params={{ sessionId: h.session_id }}
                className="text-link type-sm w-fit"
              >
                Результат
              </Link>
            ) : null}
          </li>
        ))}
      </ul>
    </>
  )
}

export function CategoryScreen({ catalog }: { catalog: Catalog | null }) {
  const state = useQuery(assessmentStateQuery)
  const history = useQuery(historyQuery)
  const evidence = useQuery(evidenceQuery)
  const survey = useQuery(surveyQuery)

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

  return (
    <div className="flex min-w-0 max-w-[1040px] flex-col gap-6">
      <PageHeader title={ASSESSMENT.category.title} actions={actionsNode} />

      <section className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6" aria-labelledby="c-current">
        <h2 id="c-current" className="type-h3">
          {ASSESSMENT.category.current}
        </h2>
        {s.category && level ? (
          <>
            <div className="flex min-w-0 flex-wrap items-center gap-3">
              <CategoryChip title={s.category.title} size="lg" />
              <span className="type-sm min-w-0 text-ink-muted">
                {[s.direction?.title, s.category.specialization.title].filter(Boolean).join(' · ')}
              </span>
              {level.stale ? (
                <span className="type-caption rounded-full bg-warning-bg px-2 py-0.5 text-warning">
                  {ASSESSMENT.category.stale}
                </span>
              ) : null}
            </div>
            <LevelScale level={level} size="md" ownGrade={s.category.grade.code} />
            <p className="type-sm min-w-0 text-ink-muted">
              Тест от {formatDate(level.tested_at)} · подтверждено {formatAgo(level.last_evidence_at)}
            </p>
            {lastWeak ? <p className="type-sm min-w-0">{ASSESSMENT.category.kept}</p> : null}
          </>
        ) : (
          <EmptyState
            compact
            title={ASSESSMENT.category.none}
            text={ASSESSMENT.category.noneText}
            action={
              actions.length === 0 && !s.active_session && s.claimed_grade ? (
                <Button variant="primary" asChild>
                  <Link to="/candidate/test/new" search={{ grade: s.claimed_grade.code }}>
                    Пройти тест на {s.claimed_grade.title}
                  </Link>
                </Button>
              ) : undefined
            }
          />
        )}
      </section>

      {s.category ? (
        <section className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6" aria-labelledby="c-strength">
          <h2 id="c-strength" className="type-h3">
            {ASSESSMENT.category.strength}
          </h2>
          {evidence.isError ? (
            <ErrorState compact error={evidence.error} onRetry={() => evidence.refetch()} />
          ) : !evidence.data ? (
            <Skeleton className="h-16 w-full" />
          ) : (
            <>
              {evidence.data.strength ? (
                <p className="type-body">
                  Сила профиля: <strong>{ASSESSMENT.category.strengthLabels[evidence.data.strength.label]}</strong>
                </p>
              ) : null}
              <ContributionBars items={strengthItems} />
              <p className="type-caption min-w-0 text-ink-muted">{ASSESSMENT.category.strengthTips}</p>
            </>
          )}
        </section>
      ) : null}

      {s.category ? (
        <section className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6" aria-labelledby="c-skills">
          <h2 id="c-skills" className="type-h3">
            {ASSESSMENT.category.skills}
          </h2>
          {evidence.data && evidence.data.skills.length > 0 ? (
            <ul className="flex min-w-0 flex-wrap gap-2">
              {evidence.data.skills.map((sk) => (
                <li key={sk.skill.code} className="min-w-0 max-w-full">
                  <EvidenceChip kind={sk.kind} skill={sk.skill.title} label={sk.kind_label} detail={sk.detail} />
                </li>
              ))}
            </ul>
          ) : (
            <p className="type-sm text-ink-muted">{evidence.data ? 'Подтверждённых навыков пока нет' : 'Загрузка…'}</p>
          )}
        </section>
      ) : null}

      <section className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6" aria-labelledby="c-change">
        <h2 id="c-change" className="type-h3">
          {ASSESSMENT.category.change}
        </h2>
        <NextActionList actions={actions} />
        <p className="type-caption min-w-0 text-ink-muted">
          Сменить подтверждённый грейд можно раз в {changeDays} дн.; повторить тест на тот же грейд — через {retryDays}{' '}
          дн.
        </p>
      </section>

      {surveyRows.length > 0 ? (
        <section className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6" aria-labelledby="c-survey">
          <h2 id="c-survey" className="type-h3">
            {ASSESSMENT.category.survey}
          </h2>
          <dl className="grid min-w-0 gap-x-6 gap-y-2 sm:grid-cols-[minmax(0,240px)_minmax(0,1fr)]">
            {surveyRows.map((r) => (
              <div key={r.id} className="contents">
                <dt className="type-sm min-w-0 text-ink-muted">{r.title}</dt>
                <dd className="type-sm min-w-0 break-words">{r.value}</dd>
              </div>
            ))}
          </dl>
        </section>
      ) : null}

      <section className="surface-card flex min-w-0 flex-col gap-3 p-4 md:p-6" aria-labelledby="c-history">
        <h2 id="c-history" className="type-h3">
          {ASSESSMENT.category.history}
        </h2>
        <HistoryRows items={history.data} />
      </section>
    </div>
  )
}
