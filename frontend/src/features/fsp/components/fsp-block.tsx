import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import {
  ArrowRight,
  Award,
  BadgeCheck,
  CalendarDays,
  ChevronDown,
  FileText,
  Fingerprint,
  Gauge,
  Hourglass,
  Link2,
  LogIn,
  type LucideIcon,
  MapPin,
  Medal,
  Plus,
  RefreshCw,
  Scale,
  ScanEye,
  ShieldCheck,
  Sparkles,
  Trophy,
  Unlink,
  UserCog,
  Users,
} from 'lucide-react'
import type * as React from 'react'
import { Fragment, useEffect, useState } from 'react'
import { toast } from 'sonner'
import type { FspCalendarView, FspLinkView } from '@/client'
import { ErrorState, ExternalLink, IconTile, MiniBar, SoftPill, StatTile, type TileTone } from '@/components/app'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage, hasCode } from '@/lib/api'
import { formatDate, formatDateTime, formatRemaining } from '@/lib/format'
import { useServerNow } from '@/lib/time'
import { cn } from '@/lib/utils'
import {
  fspCalendarQuery,
  fspConsentQuery,
  fspPrivacyQuery,
  useFspLink,
  useFspSync,
  useFspUnlink,
  useStartFspLink,
} from '../api'
import { CREDENTIAL_KIND_LABELS, DATA_ITEM_LABELS, FSP } from '../content'
import { FspAchievementList } from './fsp-achievement-list'

export type FspBlockProps = {
  /** Результат возврата из потока привязки (`?result=`); после показа параметр убирается из адреса. */
  result?: string
  reason?: string
}

function ReturnAlert({ result, reason }: { result: string; reason?: string }) {
  const R = FSP.returned
  if (result === 'cancelled')
    return (
      <Alert variant="info">
        <AlertDescription>{R.cancelled}</AlertDescription>
      </Alert>
    )
  if (result === 'already_linked')
    return (
      <Alert variant="destructive">
        <AlertDescription>{R.already_linked}</AlertDescription>
      </Alert>
    )
  if (result === 'minor')
    return (
      <Alert variant="warning">
        <AlertDescription>{R.minor}</AlertDescription>
      </Alert>
    )
  if (result === 'error')
    return (
      <Alert variant="destructive">
        <AlertDescription>{(reason && R.reasons[reason]) || R.reasonFallback}</AlertDescription>
      </Alert>
    )
  return null
}

/** Пилюля с произвольным текстом: длинное значение переносится внутри, а не вылезает из карточки. */
const WRAP_PILL = 'h-auto min-h-6 shrink rounded-xl py-0.5 [overflow-wrap:anywhere] [&>svg]:size-3.5 [&>svg]:shrink-0'

const DATA_ITEM_ICON: Record<string, LucideIcon> = {
  competition: Trophy,
  result: Medal,
  team: Users,
  team_role: UserCog,
  rank: Award,
  credentials: Scale,
  identity: Fingerprint,
}

function BlockTitle({
  id,
  icon,
  tone,
  count,
  children,
}: {
  id: string
  icon: LucideIcon
  tone: TileTone
  count?: number
  children: React.ReactNode
}) {
  return (
    <h2 id={id} className="type-h2 flex min-w-0 items-center gap-2.5">
      <IconTile icon={icon} tone={tone} size="sm" />
      <span className="min-w-0">{children}</span>
      {count !== undefined ? <span className="num type-sm font-medium text-ink-muted">{count}</span> : null}
    </h2>
  )
}

const YEAR_TAIL = /\s\d{4}$/
const SOON_MS = 14 * 24 * 60 * 60 * 1000

/** Диапазон дат без повторов: «20–21 февр. 2027», «31 окт. – 1 нояб.»; год пишется один раз. */
function formatDateRange(start: string, end: string): string {
  const from = new Date(start)
  const to = new Date(end)
  const last = formatDate(end)
  if (Number.isNaN(from.getTime()) || Number.isNaN(to.getTime())) return formatDate(start) || last
  if (from.getFullYear() !== to.getFullYear()) return `${formatDate(start)} – ${last}`
  if (from.getMonth() !== to.getMonth()) return `${formatDate(start).replace(YEAR_TAIL, '')} – ${last}`
  return from.getDate() === to.getDate() ? last : `${from.getDate()}–${last}`
}

/** До срока меньше двух недель: только тогда пилюля регистрации предупреждающая. */
function isSoon(deadline: string, now: Date): boolean {
  return new Date(deadline).getTime() - now.getTime() < SOON_MS
}

function Calendar({ data }: { data: FspCalendarView }) {
  const C = FSP.calendar
  const now = useServerNow()
  if (data.items.length === 0) return null
  return (
    <section className="flex min-w-0 flex-col gap-3" aria-labelledby="fsp-calendar">
      <BlockTitle id="fsp-calendar" icon={CalendarDays} tone="soft">
        {C.title}
      </BlockTitle>
      <ul className="grid min-w-0 gap-3 md:grid-cols-3">
        {data.items.map((item, index) => (
          <li
            key={item.competition_id}
            className="surface-row stagger flex min-w-0 animate-rise-in flex-col gap-2.5 p-4"
            style={{ '--i': index } as React.CSSProperties}
          >
            <SoftPill tone="brand" icon={CalendarDays} className={cn(WRAP_PILL, 'self-start font-medium')}>
              <span className="num whitespace-normal">{formatDateRange(item.date_start, item.date_end)}</span>
            </SoftPill>
            <h3 className="type-h3 min-w-0 text-ink [overflow-wrap:anywhere]">{item.title}</h3>
            <ul className="flex min-w-0 flex-wrap gap-1.5">
              {[item.level_label, item.format_label].filter(Boolean).map((label) => (
                <li key={label} className="max-w-full min-w-0">
                  <SoftPill size="sm" className={WRAP_PILL}>
                    {label}
                  </SoftPill>
                </li>
              ))}
              {item.city ? (
                <li className="max-w-full min-w-0">
                  <SoftPill size="sm" icon={MapPin} className={WRAP_PILL}>
                    {item.city}
                  </SoftPill>
                </li>
              ) : null}
            </ul>
            <p className="type-sm min-w-0 text-ink-muted [overflow-wrap:anywhere]">
              {[item.discipline_label, item.age_group_label].filter(Boolean).join(' · ')}
            </p>
            {item.registration_deadline ? (
              <SoftPill
                tone={isSoon(item.registration_deadline, now) ? 'warning' : 'neutral'}
                size="sm"
                icon={Hourglass}
                className={cn(WRAP_PILL, 'self-start')}
              >
                {C.registrationUntil(formatDate(item.registration_deadline))}
              </SoftPill>
            ) : null}
            {item.registration_url ? (
              <ExternalLink href={item.registration_url} className="type-sm mt-auto min-h-11 self-start">
                {C.open}
              </ExternalLink>
            ) : null}
          </li>
        ))}
      </ul>
      {data.stale && data.fetched_at ? (
        <p className="type-caption text-ink-muted">{C.stale(formatDate(data.fetched_at))}</p>
      ) : null}
    </section>
  )
}

function OtherWays() {
  const O = FSP.others
  return (
    <section className="flex min-w-0 flex-col gap-3" aria-labelledby="fsp-others">
      <BlockTitle id="fsp-others" icon={Sparkles} tone="soft">
        {O.title}
      </BlockTitle>
      <ul className="grid min-w-0 gap-3 md:grid-cols-2">
        <li className="surface-row flex min-w-0 flex-col gap-2 p-4">
          <div className="flex min-w-0 items-center gap-3">
            <IconTile icon={BadgeCheck} tone="brand" />
            <h3 className="type-h3 min-w-0 flex-1">{O.test.title}</h3>
          </div>
          <Link to={O.test.to} className="text-link mt-auto inline-flex min-h-11 items-center gap-1 self-start">
            {O.test.link}
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </li>
        <li className="surface-row flex min-w-0 flex-col gap-2 p-4">
          <div className="flex min-w-0 items-center gap-3">
            <IconTile icon={Trophy} tone="accent" />
            <h3 className="type-h3 min-w-0 flex-1">{O.competitions.title}</h3>
          </div>
          <p className="type-sm mt-auto flex min-h-11 min-w-0 items-center text-ink-muted">{O.competitions.text}</p>
        </li>
      </ul>
      <div className="surface-row flex min-w-0 flex-col gap-3 p-4">
        <div className="flex min-w-0 items-center gap-3">
          <IconTile icon={Gauge} tone="soft" />
          <h3 className="type-h3 min-w-0 flex-1">{O.strength.title}</h3>
        </div>
        <div className="grid min-w-0 gap-x-6 gap-y-2 md:grid-cols-3">
          {O.strength.parts.map((part, index) => (
            <MiniBar
              key={part.key}
              label={part.label}
              value={part.max}
              max={60}
              color={part.key === 'test' ? 'brand' : part.key === 'fsp' ? 'brandDeep' : 'neutral'}
              index={index}
            />
          ))}
        </div>
      </div>
      <p className="type-caption min-w-0 text-ink-muted">{O.footer}</p>
    </section>
  )
}

function NotLinked({ data }: { data: FspLinkView }) {
  const T = FSP.notLinked
  const consent = useQuery({ ...fspConsentQuery(), retry: false })
  const start = useStartFspLink()
  const [accepted, setAccepted] = useState(false)
  // Возврат кнопкой «Назад» со страницы ФСП ID восстанавливает экран из кэша браузера: снимаем вечную загрузку.
  const resetStart = start.reset
  useEffect(() => {
    const onShow = (event: PageTransitionEvent) => {
      if (event.persisted) resetStart()
    }
    window.addEventListener('pageshow', onShow)
    return () => window.removeEventListener('pageshow', onShow)
  }, [resetStart])

  const failure = start.error
  useEffect(() => {
    if (hasCode(failure, 'fsp_consent_outdated')) {
      setAccepted(false)
      void consent.refetch()
    }
  }, [failure, consent.refetch])

  return (
    <div className="flex min-w-0 flex-col gap-6">
      {data.notice ? (
        <Alert variant="info">
          <AlertDescription>{FSP.notice[data.notice]}</AlertDescription>
        </Alert>
      ) : null}
      <Card className="accent-card animate-rise-in gap-5">
        <div className="flex min-w-0 items-start gap-3">
          <IconTile icon={Link2} tone="solid" size="xl" />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <h2 className="type-h2 min-w-0">{T.title}</h2>
            <p className="type-sm min-w-0 text-ink-muted">{T.lead}</p>
          </div>
        </div>
        {consent.isPending ? (
          <Skeleton className="h-32 w-full" />
        ) : consent.isError ? (
          <div>
            <ErrorState
              compact
              headingLevel={3}
              error={consent.error}
              onRetry={() => consent.refetch()}
              retrying={consent.isFetching}
            />
          </div>
        ) : (
          <div className="flex min-w-0 flex-col gap-4">
            <section aria-labelledby="fsp-will-get" className="flex min-w-0 flex-col gap-3">
              <h3 id="fsp-will-get" className="type-caption font-semibold tracking-wide text-ink-muted uppercase">
                {T.willGet}
              </h3>
              <ul className="grid min-w-0 gap-x-4 gap-y-2 sm:grid-cols-2">
                {consent.data.data_items.map((item) => (
                  <li key={item} className="flex min-w-0 items-center gap-2.5">
                    <IconTile icon={DATA_ITEM_ICON[item] ?? FileText} tone="soft" size="xs" />
                    <span className="type-sm min-w-0 text-ink [overflow-wrap:anywhere]">
                      {DATA_ITEM_LABELS[item] ?? item}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
            <Collapsible className="min-w-0 rounded-lg bg-fill px-3">
              <CollapsibleTrigger className="type-sm group flex min-h-11 w-full min-w-0 items-center gap-2.5 text-left font-medium">
                <FileText className="size-4 shrink-0 text-ink-muted" aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  {T.consentToggle} <span className="num font-normal text-ink-muted">· {consent.data.version}</span>
                </span>
                <ChevronDown
                  className="size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180"
                  aria-hidden="true"
                />
              </CollapsibleTrigger>
              <CollapsibleContent>
                <p className="type-sm max-h-64 min-w-0 overflow-y-auto pb-3 whitespace-pre-line text-ink-muted [overflow-wrap:anywhere]">
                  {consent.data.text}
                </p>
              </CollapsibleContent>
            </Collapsible>
            <label
              htmlFor="fsp-consent"
              className="type-body flex min-w-0 cursor-pointer items-start gap-3 rounded-lg border border-line p-3 transition-colors hover:border-brand-200 has-[[data-state=checked]]:border-brand-600 has-[[data-state=checked]]:bg-brand-50"
            >
              <Checkbox
                id="fsp-consent"
                checked={accepted}
                onCheckedChange={(v) => setAccepted(v === true)}
                className="mt-0.5"
              />
              <span className="min-w-0">{T.consentCheckbox}</span>
            </label>
            <p className="type-caption text-ink-muted">
              {T.consentNote} ·{' '}
              <Link to="/candidate/settings/privacy" className="text-link">
                {T.privacyLink}
              </Link>
            </p>
            {start.isError ? (
              <Alert variant="destructive">
                <AlertDescription>{errorMessage(start.error)}</AlertDescription>
              </Alert>
            ) : null}
            <Button
              variant="primary"
              className="self-start rounded-full"
              disabled={!accepted}
              loading={start.isPending || start.isSuccess}
              onClick={() => start.mutate(consent.data.version)}
            >
              <LogIn aria-hidden="true" />
              {T.login}
            </Button>
          </div>
        )}
      </Card>
      <OtherWays />
      <CalendarBlock />
    </div>
  )
}

function CalendarBlock() {
  const calendar = useQuery({ ...fspCalendarQuery({ query: { limit: 3 } }), retry: false })
  return calendar.data ? <Calendar data={calendar.data} /> : null
}

function Actions({ data }: { data: FspLinkView }) {
  const sync = useFspSync()
  const unlink = useFspUnlink()
  const now = useServerNow(5000)
  const [confirm, setConfirm] = useState(false)
  const canSyncAt = data.refresh?.can_sync_at
  const wait = canSyncAt ? formatRemaining(canSyncAt, now) : null

  return (
    <div className="flex min-w-0 flex-col gap-2 sm:items-end">
      <div className="flex min-w-0 flex-wrap gap-2">
        <Button
          variant="secondary"
          loading={sync.isPending}
          disabled={Boolean(wait)}
          onClick={() => sync.mutate(undefined, { onError: (error) => toast.error(errorMessage(error)) })}
        >
          <RefreshCw aria-hidden="true" />
          {FSP.refresh}
        </Button>
        <Button variant="ghost" onClick={() => setConfirm(true)}>
          <Unlink aria-hidden="true" />
          {FSP.unlink}
        </Button>
      </div>
      {wait ? <p className="type-caption text-ink-muted">{FSP.refreshAt(wait)}</p> : null}
      <AlertDialog open={confirm} onOpenChange={setConfirm}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{FSP.unlinkTitle}</AlertDialogTitle>
          </AlertDialogHeader>
          <AlertDialogBody>
            <AlertDialogDescription>{FSP.unlinkText}</AlertDialogDescription>
          </AlertDialogBody>
          <AlertDialogFooter>
            <AlertDialogCancel>{FSP.unlinkCancel}</AlertDialogCancel>
            <Button
              variant="destructive"
              loading={unlink.isPending}
              onClick={() =>
                unlink.mutate(undefined, {
                  onSuccess: () => {
                    setConfirm(false)
                    toast.success(FSP.unlinked)
                  },
                  onError: (error) => {
                    setConfirm(false)
                    toast.error(errorMessage(error))
                  },
                })
              }
            >
              {FSP.unlink}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

function Linked({ data }: { data: FspLinkView }) {
  const sync = useFspSync()
  const privacy = useQuery({ ...fspPrivacyQuery(), retry: false })
  const status = data.history_status
  const achievements = data.achievements ?? []
  const refreshFailed = data.refresh?.last_outcome?.startsWith('failed_') ?? false
  const checkedAt = data.refresh?.checked_at ?? data.last_sync_at

  if (status === 'sync_pending') {
    return (
      <Card aria-busy="true">
        <div className="flex min-w-0 items-center gap-3">
          <IconTile icon={RefreshCw} tone="soft" />
          <p className="type-h3 min-w-0 text-ink" role="status">
            {FSP.pending}
          </p>
        </div>
        <div className="flex flex-col gap-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      </Card>
    )
  }

  if (status === 'sync_failed') {
    return (
      <Alert variant="warning">
        <AlertTitle>{FSP.syncFailed}</AlertTitle>
        <AlertDescription>
          <Button
            variant="secondary"
            size="sm"
            className="mt-2"
            loading={sync.isPending}
            onClick={() => sync.mutate(undefined, { onError: (error) => toast.error(errorMessage(error)) })}
          >
            {FSP.retry}
          </Button>
        </AlertDescription>
      </Alert>
    )
  }

  const hidden = privacy.data?.show_fsp_summary === false
  const noHistory = status === 'no_history'
  const reason = data.no_history_reason ?? 'no_results'
  const counted = achievements.filter((item) => item.counted).length

  return (
    <div className="flex min-w-0 flex-col gap-6">
      {refreshFailed && checkedAt ? (
        <Alert variant="warning">
          <AlertDescription className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="min-w-0">{FSP.refreshFailed(formatDateTime(checkedAt))}</span>
            <Button
              variant="secondary"
              size="sm"
              loading={sync.isPending}
              onClick={() => sync.mutate(undefined, { onError: (error) => toast.error(errorMessage(error)) })}
            >
              {FSP.retry}
            </Button>
          </AlertDescription>
        </Alert>
      ) : null}

      <div className="accent-card surface-card flex min-w-0 animate-rise-in flex-col gap-4">
        <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-3">
          <div className="flex min-w-0 flex-1 basis-64 items-center gap-3">
            <IconTile icon={BadgeCheck} tone="success" size="xl" />
            <div className="flex min-w-0 flex-1 flex-col items-start gap-1.5">
              <h2 className="type-h2 min-w-0 [overflow-wrap:anywhere]">
                {data.linked_at ? FSP.linkedSince(formatDate(data.linked_at)) : FSP.returned.linked}
              </h2>
              <div className="flex min-w-0 flex-wrap gap-1.5">
                {data.subject_hint ? (
                  <SoftPill size="sm" icon={Fingerprint} className={WRAP_PILL}>
                    <span className="num">{data.subject_hint}</span>
                  </SoftPill>
                ) : null}
                {noHistory ? (
                  <SoftPill tone="success" size="sm" icon={ShieldCheck} className={WRAP_PILL}>
                    {FSP.noPenalty}
                  </SoftPill>
                ) : null}
              </div>
            </div>
          </div>
          <Actions data={data} />
        </div>
        {noHistory ? (
          <p
            className="type-sm min-w-0 rounded-lg bg-fill p-3 text-ink [overflow-wrap:anywhere]"
            data-testid="fsp-no-history"
          >
            {FSP.noHistory[reason]}
          </p>
        ) : achievements.length > 0 ? (
          <div className="flex min-w-0 flex-wrap gap-x-8 gap-y-3 border-t border-line pt-4">
            <StatTile icon={Trophy} tone="accent" value={counted} label={FSP.stats.counted} />
            <StatTile icon={Medal} tone="soft" value={achievements.length} label={FSP.stats.total} />
            {data.credentials?.length ? (
              <StatTile icon={Award} tone="success" value={data.credentials.length} label={FSP.stats.credentials} />
            ) : null}
          </div>
        ) : null}
        {data.refresh?.source_label && checkedAt ? (
          <p className="type-caption min-w-0 text-ink-muted">
            {FSP.source(data.refresh.source_label, formatDate(checkedAt))}
            {data.refresh.stale ? ` · ${FSP.stale}` : ''}
          </p>
        ) : null}
      </div>

      {noHistory ? null : (
        <>
          {hidden ? (
            <Alert variant="warning">
              <AlertDescription>
                {FSP.hidden}{' '}
                <Link to="/candidate/settings/privacy" className="text-link">
                  {FSP.hiddenLink}
                </Link>
              </AlertDescription>
            </Alert>
          ) : null}
          {data.employer_preview ? (
            <Card>
              <div className="flex min-w-0 items-center gap-3">
                <IconTile icon={ScanEye} tone="solid" />
                <h2 className="type-h3 min-w-0 flex-1">{FSP.employerView.title}</h2>
              </div>
              <p className="flex min-w-0 flex-wrap gap-1.5" data-testid="fsp-employer-line">
                {data.employer_preview.headline.split(' · ').map((part, index) => (
                  // biome-ignore lint/suspicious/noArrayIndexKey: части строки не меняют порядок
                  <Fragment key={index}>
                    {index > 0 ? <span className="sr-only"> · </span> : null}
                    <SoftPill tone={index === 0 ? 'brand' : 'neutral'} className={cn(WRAP_PILL, 'min-h-7')}>
                      {part}
                    </SoftPill>
                  </Fragment>
                ))}
                {data.employer_preview.more ? (
                  <>
                    <span className="sr-only"> · </span>
                    <SoftPill icon={Plus} className={cn(WRAP_PILL, 'min-h-7')}>
                      {FSP.employerView.more}
                    </SoftPill>
                  </>
                ) : null}
              </p>
              {data.employer_preview.shortened ? (
                <p className="type-caption text-ink-muted">{FSP.employerView.shortened}</p>
              ) : null}
            </Card>
          ) : null}
        </>
      )}

      {achievements.length > 0 ? (
        <section className="flex min-w-0 flex-col gap-3" aria-labelledby="fsp-achievements">
          <BlockTitle id="fsp-achievements" icon={Trophy} tone="accent" count={achievements.length}>
            {FSP.achievements}
          </BlockTitle>
          <FspAchievementList achievements={achievements} mode="self" />
        </section>
      ) : null}

      {data.credentials && data.credentials.length > 0 ? (
        <section className="flex min-w-0 flex-col gap-3" aria-labelledby="fsp-credentials">
          <BlockTitle id="fsp-credentials" icon={Award} tone="success" count={data.credentials.length}>
            {FSP.credentials}
          </BlockTitle>
          <ul className="grid min-w-0 gap-3 md:grid-cols-2">
            {data.credentials.map((credential) => (
              <li key={credential.id} className="surface-row flex min-w-0 items-start gap-3 p-4">
                <IconTile icon={Award} tone="success" />
                <div className="flex min-w-0 flex-1 flex-col items-start gap-1.5">
                  <span className="type-h3 min-w-0 text-ink [overflow-wrap:anywhere]">{credential.label}</span>
                  <ul className="flex min-w-0 flex-wrap gap-1.5">
                    {[
                      credential.kind ? CREDENTIAL_KIND_LABELS[credential.kind] : null,
                      credential.discipline_label,
                      credential.status_label,
                      credential.valid_until ? `до ${formatDate(credential.valid_until)}` : null,
                    ]
                      .filter(Boolean)
                      .map((label) => (
                        <li key={label} className="max-w-full min-w-0">
                          <SoftPill size="sm" className={WRAP_PILL}>
                            {label}
                          </SoftPill>
                        </li>
                      ))}
                  </ul>
                </div>
              </li>
            ))}
          </ul>
          {achievements.length === 0 ? <p className="type-sm text-ink-muted">{FSP.rolesOnly}</p> : null}
        </section>
      ) : null}

      {noHistory ? (
        <>
          <OtherWays />
          <CalendarBlock />
        </>
      ) : null}
    </div>
  )
}

/** C13. Блок привязки ФСП ID: все состояния `FspLinkView`, возврат из потока, обновление и отвязка. */
export function FspBlock({ result, reason }: FspBlockProps) {
  const navigate = useNavigate()
  const link = useFspLink()
  const [shown, setShown] = useState<{ result: string; reason?: string } | null>(result ? { result, reason } : null)

  useEffect(() => {
    if (!result) return
    setShown({ result, reason })
    if (result === 'linked') toast.success(FSP.returned.linked)
    void navigate({ to: '.', search: {}, replace: true })
  }, [result, reason, navigate])

  return (
    <div className="flex min-w-0 flex-col gap-6">
      {shown ? <ReturnAlert result={shown.result} reason={shown.reason} /> : null}
      {link.isPending ? (
        <Skeleton className="h-64 w-full" />
      ) : link.isError ? (
        <ErrorState error={link.error} onRetry={() => link.refetch()} retrying={link.isFetching} />
      ) : link.data.status === 'not_linked' ? (
        <NotLinked data={link.data} />
      ) : (
        <Linked data={link.data} />
      )}
    </div>
  )
}
