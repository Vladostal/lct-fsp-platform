import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { ChevronRight, FileDown } from 'lucide-react'
import type { FspLinkView } from '@/client'
import {
  assessmentGetStateOptions,
  contactCandidateFunnelOptions,
  contactListCandidateInvitationsOptions,
  fspGetLinkOptions,
  profileGetConsentsOptions,
  profileGetProfileOptions,
} from '@/client/@tanstack/react-query.gen'
import { CategoryChip, CopyButton, ErrorState, LevelScale, SalaryRange } from '@/components/app'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { WORK_FORMAT_LABELS } from '@/content/common'
import { formatDate } from '@/lib/format'
import { invitationSummaryQuery, polling } from '@/lib/query'
import { FunnelCard } from './funnel-card'
import { useResumeVisibility } from './hooks'
import { InvitationCard } from './invitation-card'
import { PauseBanner } from './pause-banner'

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="surface-card flex min-w-0 flex-col gap-4" aria-label={title}>
      <h2 className="type-h3 text-ink">{title}</h2>
      {children}
    </section>
  )
}

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

  let text = ''
  let action: React.ReactNode = null
  if (vis.state === 'not_ready') {
    text = 'Категория не присвоена. Профиль не виден работодателям'
    action = next ? (
      <Button asChild variant="primary">
        <Link to="/candidate/test/new">Пройти тест на {next.grade.title}</Link>
      </Button>
    ) : waiting?.available_at ? (
      <p className="type-sm text-ink-muted">Следующая попытка — с {formatDate(waiting.available_at)}</p>
    ) : null
  } else if (vis.state === 'unpublished') {
    text = 'Категория присвоена, профиль не опубликован'
    action = category ? (
      <Button asChild variant="primary">
        <Link to="/candidate/test/$sessionId/result" params={{ sessionId: category.level_session_id }} hash="publish">
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
    <div className="flex min-w-0 flex-col gap-4">
      <div className="flex min-w-0 flex-wrap items-center gap-3">
        {category ? <CategoryChip title={category.title} /> : null}
      </div>
      {level ? <LevelScale level={level} size="sm" className="w-full max-w-sm" /> : null}
      <p className="type-body text-ink [overflow-wrap:anywhere]">{text}</p>
      {profile.data ? (
        <p className="type-sm flex min-w-0 flex-wrap items-center gap-2 text-ink-muted">
          <span>Ваш код</span>
          <span className="num text-ink">{profile.data.public_code}</span>
          <CopyButton value={profile.data.public_code} label="Скопировать код" />
          <span className="min-w-0">по этому коду вас видит работодатель до согласия</span>
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
    return (
      <p className="type-body max-w-[60ch] text-ink-muted">
        Откликаться не нужно: работодатели сами находят вашу категорию и присылают приглашение с зарплатой. Здесь
        появятся приглашения, на которые нужно ответить.
      </p>
    )
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
    <Block title="Не доставлено">
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
    </Block>
  )
}

function Strengthen({ fsp }: { fsp: FspLinkView | undefined }) {
  const row = fspRow(fsp)
  const rows = [
    { key: 'fsp', text: row.text, to: row.to },
    { key: 'profile', text: 'Дополнить стек и раздел «О себе»', to: '/candidate/profile' as const },
  ]
  return (
    <Block title="Усилить профиль">
      <ul className="flex min-w-0 flex-col divide-y divide-line">
        {rows.map((r) => (
          <li key={r.key}>
            <Link
              to={r.to}
              className="type-body flex min-h-11 min-w-0 items-center justify-between gap-3 py-2 text-ink hover:text-brand-700"
            >
              <span className="min-w-0 [overflow-wrap:anywhere]">{r.text}</span>
              <ChevronRight className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
            </Link>
          </li>
        ))}
        <li>
          <a
            href="/api/v1/candidate/profile/pdf"
            className="type-body flex min-h-11 min-w-0 items-center justify-between gap-3 py-2 text-ink hover:text-brand-700"
          >
            <span className="min-w-0">Скачать PDF-профиль</span>
            <FileDown className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
          </a>
        </li>
      </ul>
    </Block>
  )
}

/** C7. Обзор: статус, спрос, ждущие приглашения, не доставленные и подсказки. Блоки грузятся независимо. */
export function CandidateOverview() {
  const summary = useQuery({ ...invitationSummaryQuery, ...polling })
  const fsp = useQuery(fspGetLinkOptions())
  return (
    <div className="flex min-w-0 flex-col gap-4">
      {summary.data ? <PauseBanner visibility={summary.data.visibility} /> : null}
      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <Block title="Ваш профиль">
          <StatusCard />
        </Block>
        <Block title="Спрос на ваш профиль">
          <Funnel fsp={fsp.data} />
        </Block>
      </div>
      <Block title="Приглашения, ждущие ответа">
        <Awaiting />
      </Block>
      <NotDelivered />
      <Strengthen fsp={fsp.data} />
    </div>
  )
}
