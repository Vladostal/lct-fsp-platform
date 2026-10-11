import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import {
  BadgeCheck,
  CalendarClock,
  CalendarDays,
  CircleDashed,
  Download,
  FileText,
  Hourglass,
  Inbox,
  Lock,
  type LucideIcon,
  MailX,
  PencilLine,
  Rocket,
  TrendingUp,
  Trophy,
  UserRoundPen,
} from 'lucide-react'
import type { FspLinkView } from '@/client'
import {
  assessmentGetStateOptions,
  contactCandidateFunnelOptions,
  contactListCandidateInvitationsOptions,
  fspGetLinkOptions,
  profileGetConsentsOptions,
  profileGetProfileOptions,
} from '@/client/@tanstack/react-query.gen'
import {
  CandidateCategoryChip,
  CopyButton,
  EmptyState,
  ErrorState,
  FormatPill,
  GoChevron,
  IconTile,
  LevelScale,
  SalaryRange,
  Section,
  SoftPill,
  StatusBadge,
  type TileTone,
  type Tone,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { CATEGORY_DECLARED, VISIBILITY_LABELS, visibilityTitle } from '@/content/common'
import { hasTest, isDeclared } from '@/lib/category'
import { formatDate } from '@/lib/format'
import { catalogQuery, invitationSummaryQuery, polling } from '@/lib/query'
import { FunnelCard } from './funnel-card'
import { useResumeVisibility } from './hooks'
import { InvitationCard } from './invitation-card'
import { PauseBanner } from './pause-banner'

function BlockSkeleton() {
  return (
    <div className="surface-card flex flex-col gap-3" aria-busy="true">
      <Skeleton className="h-6 w-2/3" />
      <Skeleton className="h-16 w-full" />
    </div>
  )
}

type FspNote = { title: string; note?: string; tone: Tone }

/** Строка ФСП: без истории и до получения данных — нейтрально, без штрафного тона. */
function fspRow(fsp: FspLinkView | undefined): FspNote {
  if (!fsp || fsp.status === 'not_linked') return { title: 'Привязать ФСП ID', tone: 'neutral' }
  const title = 'ФСП ID привязан'
  if (fsp.history_status === 'sync_pending') return { title, note: 'получаем данные', tone: 'neutral' }
  if (fsp.history_status === 'sync_failed') return { title, note: 'данные не получены', tone: 'warning' }
  if (fsp.history_status === 'no_history') return { title, note: 'истории нет', tone: 'neutral' }
  if (fsp.signal && fsp.signal.counted > 0)
    return { title, note: `зачтено результатов: ${fsp.signal.counted}`, tone: 'success' }
  return { title, tone: 'neutral' }
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
    text = VISIBILITY_LABELS.not_ready
    action = next ? (
      <Button asChild variant="primary">
        <Link to="/candidate/test/new" search={{ grade: next.grade.code }}>
          Пройти тест на {next.grade.title}
        </Link>
      </Button>
    ) : waiting?.available_at ? (
      <SoftPill tone="warning" icon={CalendarClock}>
        <span className="num">Следующая попытка — с {formatDate(waiting.available_at)}</span>
      </SoftPill>
    ) : noTest ? (
      <Button asChild variant="primary">
        <Link to="/candidate/category">Заявить грейд</Link>
      </Button>
    ) : null
  } else if (vis.state === 'unpublished') {
    text = VISIBILITY_LABELS.unpublished
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
    text = VISIBILITY_LABELS.visible
  } else if (vis.pause_reason === 'auto_silence') {
    text = `${VISIBILITY_LABELS.paused} до ${vis.auto_paused_until ? formatDate(vis.auto_paused_until) : 'окончания паузы'}`
  } else {
    text = VISIBILITY_LABELS.paused
    action = (
      <Button variant="primary" loading={show.pending} onClick={show.run}>
        Возобновить показ
      </Button>
    )
  }

  const tile: { icon: LucideIcon; tone: TileTone } = !category
    ? { icon: CircleDashed, tone: 'dashed' }
    : declared
      ? { icon: PencilLine, tone: 'dashed' }
      : { icon: BadgeCheck, tone: 'solid' }

  return (
    <div className="accent-card surface-card grid min-w-0 animate-rise-in gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)] lg:items-center lg:gap-8">
      <div className="flex min-w-0 flex-col gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <IconTile icon={tile.icon} tone={tile.tone} size="xl" />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            {category ? (
              <CandidateCategoryChip category={category} size="lg" />
            ) : (
              <p className="type-h2 min-w-0 text-ink [overflow-wrap:anywhere]">Категория не присвоена</p>
            )}
          </div>
        </div>
        {declared ? (
          <p className="type-sm min-w-0 text-ink-muted">
            {CATEGORY_DECLARED.line}.{' '}
            <Link to="/candidate/category" className="text-link">
              Изменить
            </Link>
          </p>
        ) : null}
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <StatusBadge status={vis.state} label={text} title={visibilityTitle(vis.state)} live />
          {profile.data ? (
            <span className="inline-flex h-8 min-w-0 items-center gap-0.5 rounded-full bg-fill pr-0.5 pl-3">
              <span className="sr-only">Код кандидата: </span>
              <span className="num text-sm font-medium text-ink">{profile.data.public_code}</span>
              <CopyButton value={profile.data.public_code} label="Скопировать код" className="rounded-full" />
            </span>
          ) : null}
        </div>
        {action ? <div className="flex min-w-0 flex-wrap items-center gap-2 max-[479px]:*:w-full">{action}</div> : null}
      </div>
      {level ? (
        <div className="surface-row min-w-0 p-4">
          <LevelScale level={level} size="md" ownGrade={category?.grade.code} animate className="min-w-0" />
        </div>
      ) : null}
    </div>
  )
}

function Funnel({ fsp }: { fsp: FspLinkView | undefined }) {
  const funnel = useQuery({ ...contactCandidateFunnelOptions(), ...polling })
  const summary = useQuery({ ...invitationSummaryQuery, ...polling })
  if (funnel.isPending) return <BlockSkeleton />
  if (funnel.isError)
    return <ErrorState compact headingLevel={3} error={funnel.error} onRetry={() => void funnel.refetch()} />
  return (
    <FunnelCard
      funnel={funnel.data}
      fspLinked={fsp?.status === 'linked'}
      hasAwaiting={(summary.data?.awaiting ?? 0) > 0}
    />
  )
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
      <div className="surface-card flex h-full min-w-0 items-center justify-center">
        <EmptyState
          compact
          headingLevel={3}
          icon={Inbox}
          text="Пока нет приглашений. Работодатели сами находят вашу категорию."
        />
      </div>
    )
  return (
    <div className="flex h-full min-w-0 flex-col gap-3">
      {list.data.items.map((item, index) => (
        <InvitationCard key={item.id} item={item} index={index} />
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
    <Section title="Не доставлено" icon={MailX}>
      <div className="surface-card flex min-w-0 flex-col gap-4">
        <ul className="flex min-w-0 flex-col gap-3">
          {items.slice(0, 5).map((item) => (
            <li key={`${item.at}-${item.salary_from}`} className="flex min-w-0 items-center gap-3">
              <IconTile icon={MailX} tone="dashed" size="sm" />
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                <SoftPill>
                  <SalaryRange from={item.salary_from} to={item.salary_to} size="sm" />
                </SoftPill>
                <FormatPill format={item.work_format} />
                <span className="num type-sm inline-flex items-center gap-1.5 text-ink-muted">
                  <CalendarDays aria-hidden="true" className="size-3.5" />
                  {formatDate(item.at)}
                </span>
              </div>
            </li>
          ))}
        </ul>
        <p className="type-sm flex min-w-0 items-start gap-2 text-ink-muted">
          <Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
          Вилка этих предложений начиналась ниже вашего минимума. Компании не названы.
        </p>
      </div>
    </Section>
  )
}

const ACTION_CARD =
  'lift-card surface-row flex h-full min-h-16 min-w-0 items-center gap-3 p-4 focus-visible:outline-2 focus-visible:outline-offset-2'

function ActionBody({ title, note, tone = 'neutral' }: { title: string; note?: string; tone?: Tone }) {
  return (
    <span className="flex min-w-0 flex-1 flex-col items-start gap-1">
      <span className="type-body min-w-0 font-medium text-ink [overflow-wrap:anywhere]">{title}</span>
      {note ? (
        <SoftPill size="sm" tone={tone}>
          <span className="num">{note}</span>
        </SoftPill>
      ) : null}
    </span>
  )
}

function Strengthen({ fsp }: { fsp: FspLinkView | undefined }) {
  const row = fspRow(fsp)
  return (
    <Section title="Усилить профиль" icon={TrendingUp} iconTone="brand">
      <ul className="grid min-w-0 gap-3 md:grid-cols-3 lg:gap-4">
        <li className="min-w-0">
          <Link to="/candidate/settings/fsp" className={ACTION_CARD}>
            <IconTile icon={Trophy} tone="accent" size="lg" />
            <ActionBody {...row} />
            <GoChevron />
          </Link>
        </li>
        <li className="min-w-0">
          <Link to="/candidate/profile" className={ACTION_CARD}>
            <IconTile icon={UserRoundPen} tone="brand" size="lg" />
            <ActionBody title="Дополнить стек и раздел «О себе»" />
            <GoChevron />
          </Link>
        </li>
        <li className="min-w-0">
          <a href="/api/v1/candidate/profile/pdf" className={ACTION_CARD}>
            <IconTile icon={FileText} tone="deep" size="lg" />
            <ActionBody title="Скачать PDF-профиль" />
            <span
              aria-hidden="true"
              className="go-chip hidden size-7 shrink-0 items-center justify-center rounded-full bg-brand-50 text-brand-700 sm:flex"
            >
              <Download className="size-4" />
            </span>
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
  const funnel = useQuery({ ...contactCandidateFunnelOptions(), ...polling })
  return (
    <div className="flex min-w-0 flex-col gap-6 md:gap-8">
      {summary.data ? <PauseBanner visibility={summary.data.visibility} /> : null}
      <section aria-label="Ваша категория">
        <StatusCard />
      </section>
      <div className="grid min-w-0 gap-6 lg:grid-cols-2 lg:gap-4">
        <Section
          title="Спрос на ваш профиль"
          icon={Rocket}
          iconTone="brand"
          className="[&>div:last-child]:flex-1"
          action={
            funnel.data ? (
              <SoftPill size="sm" icon={CalendarDays}>
                <span className="num">{funnel.data.window_days} дней</span>
              </SoftPill>
            ) : undefined
          }
        >
          <Funnel fsp={fsp.data} />
        </Section>
        <Section
          title="Приглашения, ждущие ответа"
          icon={Hourglass}
          iconTone="warning"
          className="[&>div:last-child]:flex-1"
        >
          <Awaiting />
        </Section>
      </div>
      <NotDelivered />
      <Strengthen fsp={fsp.data} />
    </div>
  )
}
