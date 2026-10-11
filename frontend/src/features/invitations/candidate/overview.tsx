import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import type { FspLinkView } from '@/client'
import {
  assessmentGetStateOptions,
  contactCandidateFunnelOptions,
  contactListCandidateInvitationsOptions,
  fspGetLinkOptions,
  profileGetConsentsOptions,
  profileGetProfileOptions,
} from '@/client/@tanstack/react-query.gen'
import { CandidateCategoryChip, CopyButton, ErrorState, LevelScale, SalaryRange, Section } from '@/components/app'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { CATEGORY_DECLARED, WORK_FORMAT_LABELS } from '@/content/common'
import { hasTest, isDeclared } from '@/lib/category'
import { formatDate } from '@/lib/format'
import { catalogQuery, invitationSummaryQuery, polling } from '@/lib/query'
import { FunnelCard } from './funnel-card'
import { useResumeVisibility } from './hooks'
import { InvitationCard } from './invitation-card'
import { PauseBanner } from './pause-banner'

function BlockSkeleton() {
  return (
    <div className="flex flex-col gap-2" aria-busy="true">
      <Skeleton className="h-6 w-2/3" />
      <Skeleton className="h-10 w-full" />
    </div>
  )
}

function fspRow(fsp: FspLinkView | undefined): { text: string; to: '/candidate/settings/fsp' } {
  const to = '/candidate/settings/fsp' as const
  if (!fsp || fsp.status === 'not_linked') return { text: 'Привязать ФСП ID', to }
  if (fsp.history_status === 'sync_pending') return { text: 'ФСП ID привязан, получаем данные', to }
  if (fsp.history_status === 'sync_failed') return { text: 'ФСП ID привязан, данные не получены', to }
  if (fsp.history_status === 'no_history') return { text: 'ФСП ID привязан, истории нет', to }
  if (fsp.signal && fsp.signal.counted > 0)
    return { text: `ФСП ID привязан, зачтено результатов: ${fsp.signal.counted}`, to }
  return { text: 'ФСП ID привязан', to }
}

function StatusCard() {
  const state = useQuery(assessmentGetStateOptions())
  const consents = useQuery({ ...profileGetConsentsOptions(), ...polling })
  const profile = useQuery(profileGetProfileOptions())
  const show = useResumeVisibility('visible')
  const catalog = useQuery(catalogQuery).data

  if (state.isPending || consents.isPending) return <BlockSkeleton />
  if (state.isError || consents.isError)
    return (
      <ErrorState
        compact
        headingLevel={3}
        error={state.error ?? consents.error}
        onRetry={() => {
          void state.refetch()
          void consents.refetch()
        }}
      />
    )

  const vis = consents.data.visibility
  const category = state.data.category
  const level = state.data.level
  const actions = state.data.next_actions ?? []
  const next = actions.find((a) => a.available && a.recommended) ?? actions.find((a) => a.available)
  const waiting = actions.find((a) => !a.available && a.available_at)
  // Грейд заявлен (теста по специализации нет): страницы результата нет, публикация и смена грейда — на экране категории.
  const declared = isDeclared(category, catalog)
  const noTest = state.data.specialization != null && !hasTest(catalog, state.data.specialization.code)

  let text = ''
  let action: React.ReactNode = null
  if (vis.state === 'not_ready') {
    text = 'Категория не присвоена. Профиль не виден работодателям'
    action = next ? (
      <Button asChild variant="primary">
        <Link to="/candidate/test/new" search={{ grade: next.grade.code }}>
          Пройти тест на {next.grade.title}
        </Link>
      </Button>
    ) : waiting?.available_at ? (
      <p className="type-sm text-ink-muted">Следующая попытка — с {formatDate(waiting.available_at)}</p>
    ) : noTest ? (
      <Button asChild variant="primary">
        <Link to="/candidate/category">Заявить грейд</Link>
      </Button>
    ) : null
  } else if (vis.state === 'unpublished') {
    text = declared ? 'Грейд заявлен, профиль не опубликован' : 'Категория присвоена, профиль не опубликован'
    action = category?.level_session_id ? (
      <Button asChild variant="primary">
        <Link to="/candidate/test/$sessionId/result" params={{ sessionId: category.level_session_id }} hash="publish">
          Опубликовать профиль
        </Link>
      </Button>
    ) : category ? (
      <Button asChild variant="primary">
        <Link to="/candidate/category" hash="publish">
          Опубликовать профиль
        </Link>
      </Button>
    ) : null
  } else if (vis.state === 'visible') {
    text = 'Профиль виден работодателям'
  } else if (vis.pause_reason === 'auto_silence') {
    text = `Профиль скрыт до ${vis.auto_paused_until ? formatDate(vis.auto_paused_until) : 'окончания паузы'}`
  } else {
    text = 'Вы приостановили показ профиля'
    action = (
      <Button variant="primary" loading={show.pending} onClick={show.run}>
        Возобновить показ
      </Button>
    )
  }

  return (
    <div className="surface-card flex min-w-0 flex-col gap-4 animate-rise-in">
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        {category ? <CandidateCategoryChip category={category} size="lg" /> : null}
      </div>
      {declared ? (
        <p className="type-sm min-w-0 text-ink-muted">
          {CATEGORY_DECLARED.line}.{' '}
          <Link to="/candidate/category" className="text-link">
            Изменить
          </Link>
        </p>
      ) : null}
      {level ? <LevelScale level={level} size="sm" className="w-full max-w-sm" /> : null}
      <p className="type-body text-ink [overflow-wrap:anywhere]">{text}</p>
      {profile.data ? (
        <p className="type-sm flex min-w-0 items-center gap-2 text-ink-muted">
          <span className="num text-ink">{profile.data.public_code}</span>
          <CopyButton value={profile.data.public_code} label="Скопировать код" />
        </p>
      ) : null}
      {action}
    </div>
  )
}

function Funnel({ fsp }: { fsp: FspLinkView | undefined }) {
  const funnel = useQuery({ ...contactCandidateFunnelOptions(), ...polling })
  if (funnel.isPending) return <BlockSkeleton />
  if (funnel.isError)
    return <ErrorState compact headingLevel={3} error={funnel.error} onRetry={() => void funnel.refetch()} />
  return <FunnelCard funnel={funnel.data} fspLinked={fsp?.status === 'linked'} />
}

function Awaiting() {
  const list = useQuery({
    ...contactListCandidateInvitationsOptions({ query: { status: 'awaiting', limit: 3 } }),
    ...polling,
  })
  const summary = useQuery({ ...invitationSummaryQuery, ...polling })
  if (list.isPending) return <BlockSkeleton />
  if (list.isError)
    return <ErrorState compact headingLevel={3} error={list.error} onRetry={() => void list.refetch()} />
  if (list.data.items.length === 0)
    return <p className="type-body text-ink-muted">Пока нет приглашений. Работодатели сами находят вашу категорию.</p>
  return (
    <div className="flex min-w-0 flex-col gap-3">
      {list.data.items.map((item) => (
        <InvitationCard key={item.id} item={item} />
      ))}
      <Button asChild variant="secondary" size="sm" className="self-start">
        <Link to="/candidate/invitations">Все приглашения{summary.data ? ` (${summary.data.awaiting})` : ''}</Link>
      </Button>
    </div>
  )
}

function NotDelivered() {
  const funnel = useQuery({ ...contactCandidateFunnelOptions(), ...polling })
  const items = funnel.data?.not_delivered_items ?? []
  if (!funnel.data || funnel.data.not_delivered < 1 || items.length === 0) return null
  return (
    <Section title="Не доставлено">
      <ul className="flex min-w-0 flex-col gap-2">
        {items.slice(0, 5).map((item) => (
          <li key={`${item.at}-${item.salary_from}`} className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
            <SalaryRange from={item.salary_from} to={item.salary_to} size="sm" />
            <span className="type-sm text-ink-muted">
              {WORK_FORMAT_LABELS[item.work_format]} · {formatDate(item.at)}
            </span>
          </li>
        ))}
      </ul>
      <p className="type-sm text-ink-muted">
        Вилка этих предложений начиналась ниже вашего минимума. Компании не названы.
      </p>
    </Section>
  )
}

function Strengthen({ fsp }: { fsp: FspLinkView | undefined }) {
  const row = fspRow(fsp)
  const cls = 'type-body flex min-h-11 min-w-0 items-center py-2 text-ink hover:text-brand-700'
  return (
    <Section title="Усилить профиль">
      <ul className="flex min-w-0 flex-col divide-y divide-line">
        <li>
          <Link to={row.to} className={cls}>
            <span className="min-w-0 [overflow-wrap:anywhere]">{row.text}</span>
          </Link>
        </li>
        <li>
          <Link to="/candidate/profile" className={cls}>
            <span className="min-w-0">Дополнить стек и раздел «О себе»</span>
          </Link>
        </li>
        <li>
          <a href="/api/v1/candidate/profile/pdf" className={cls}>
            <span className="min-w-0">Скачать PDF-профиль</span>
          </a>
        </li>
      </ul>
    </Section>
  )
}

/** C7. Обзор: статус, спрос, ждущие приглашения, не доставленные и подсказки. Блоки грузятся независимо. */
export function CandidateOverview() {
  const summary = useQuery({ ...invitationSummaryQuery, ...polling })
  const fsp = useQuery(fspGetLinkOptions())
  return (
    <div className="flex min-w-0 flex-col gap-8">
      {summary.data ? <PauseBanner visibility={summary.data.visibility} /> : null}
      <section aria-label="Ваша категория">
        <StatusCard />
      </section>
      <Section title="Спрос на ваш профиль">
        <Funnel fsp={fsp.data} />
      </Section>
      <Section title="Приглашения, ждущие ответа">
        <Awaiting />
      </Section>
      <NotDelivered />
      <Strengthen fsp={fsp.data} />
    </div>
  )
}
