import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from '@tanstack/react-router'
import { CalendarDays, ChevronDown } from 'lucide-react'
import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import type { FspCalendarView, FspLinkView } from '@/client'
import { ErrorState, ExternalLink } from '@/components/app'
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
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage, hasCode } from '@/lib/api'
import { formatDate, formatDateTime, formatRemaining } from '@/lib/format'
import { useServerNow } from '@/lib/time'
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

function Calendar({ data }: { data: FspCalendarView }) {
  const C = FSP.calendar
  if (data.items.length === 0) return null
  return (
    <section className="flex min-w-0 flex-col gap-3" aria-labelledby="fsp-calendar">
      <h2 id="fsp-calendar" className="type-h3 flex items-center gap-2">
        <CalendarDays className="size-4 text-ink-muted" aria-hidden="true" />
        {C.title}
      </h2>
      <ul className="grid min-w-0 gap-3 md:grid-cols-3">
        {data.items.map((item) => (
          <li key={item.competition_id} className="surface-card flex min-w-0 flex-col gap-1.5">
            <h3 className="type-body min-w-0 font-medium text-ink [overflow-wrap:anywhere]">{item.title}</h3>
            <p className="type-sm min-w-0 text-ink-muted [overflow-wrap:anywhere]">
              {[item.discipline_label, item.level_label, item.age_group_label].join(' · ')}
            </p>
            <p className="type-sm num min-w-0 text-ink">
              {formatDate(item.date_start)} – {formatDate(item.date_end)}
            </p>
            <p className="type-sm min-w-0 text-ink-muted [overflow-wrap:anywhere]">
              {[item.format_label, item.city].filter(Boolean).join(' · ')}
            </p>
            {item.registration_deadline ? (
              <p className="type-caption text-ink-muted">
                {C.registrationUntil(formatDate(item.registration_deadline))}
              </p>
            ) : null}
            {item.registration_url ? (
              <ExternalLink href={item.registration_url} className="type-sm mt-auto pt-1">
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
    <Card>
      <CardHeader>
        <CardTitle>{O.title}</CardTitle>
      </CardHeader>
      <ul className="flex min-w-0 flex-col divide-y divide-line">
        {O.items.map((item) => (
          <li key={item.title} className="flex min-w-0 flex-col gap-0.5 py-3 first:pt-0">
            <span className="type-body font-medium text-ink">{item.title}</span>
            <span className="type-sm text-ink-muted">{item.text}</span>
            {item.to ? (
              <Link to={item.to} className="text-link inline-flex min-h-11 items-center self-start">
                {item.link}
              </Link>
            ) : null}
          </li>
        ))}
      </ul>
      <p className="type-caption mt-3 text-ink-muted">{O.footer}</p>
    </Card>
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
      <Card>
        <p className="type-body min-w-0 text-ink">{T.lead}</p>
        {consent.isPending ? (
          <Skeleton className="mt-4 h-32 w-full" />
        ) : consent.isError ? (
          <div className="mt-4">
            <ErrorState
              compact
              headingLevel={3}
              error={consent.error}
              onRetry={() => consent.refetch()}
              retrying={consent.isFetching}
            />
          </div>
        ) : (
          <div className="mt-4 flex min-w-0 flex-col gap-4">
            <section aria-labelledby="fsp-will-get" className="flex min-w-0 flex-col gap-2">
              <h2 id="fsp-will-get" className="type-h3">
                {T.willGet}
              </h2>
              <ul className="flex min-w-0 list-disc flex-col gap-1 pl-5">
                {consent.data.data_items.map((item) => (
                  <li key={item} className="type-sm min-w-0 text-ink [overflow-wrap:anywhere]">
                    {DATA_ITEM_LABELS[item] ?? item}
                  </li>
                ))}
              </ul>
            </section>
            <Collapsible className="min-w-0">
              <CollapsibleTrigger className="type-sm tap-target group flex w-full min-w-0 items-center justify-between gap-2 text-left font-medium">
                <span className="min-w-0">
                  {T.consentToggle} <span className="num font-normal text-ink-muted">· {consent.data.version}</span>
                </span>
                <ChevronDown
                  className="size-4 shrink-0 transition-transform group-data-[state=open]:rotate-180"
                  aria-hidden="true"
                />
              </CollapsibleTrigger>
              <CollapsibleContent>
                <p className="type-sm max-h-64 min-w-0 overflow-y-auto bg-fill rounded-md p-3 whitespace-pre-line text-ink-muted [overflow-wrap:anywhere]">
                  {consent.data.text}
                </p>
              </CollapsibleContent>
            </Collapsible>
            <label htmlFor="fsp-consent" className="type-body flex min-w-0 cursor-pointer items-start gap-3">
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
    <div className="flex min-w-0 flex-col gap-2">
      <div className="flex min-w-0 flex-wrap gap-3">
        <Button
          variant="secondary"
          loading={sync.isPending}
          disabled={Boolean(wait)}
          onClick={() => sync.mutate(undefined, { onError: (error) => toast.error(errorMessage(error)) })}
        >
          {FSP.refresh}
        </Button>
        <Button variant="ghost" onClick={() => setConfirm(true)}>
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
        <p className="type-body mb-4 text-ink" role="status">
          {FSP.pending}
        </p>
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

      {noHistory ? (
        <Alert variant="info" data-testid="fsp-no-history">
          <AlertDescription>{FSP.noHistory[reason]}</AlertDescription>
        </Alert>
      ) : (
        <>
          <p className="type-sm min-w-0 text-ink-muted [overflow-wrap:anywhere]">
            {data.linked_at ? FSP.linkedSince(formatDate(data.linked_at)) : null}
            {data.subject_hint ? <span className="num"> · {data.subject_hint}</span> : null}
          </p>
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
              <CardHeader>
                <CardTitle>{FSP.employerView.title}</CardTitle>
              </CardHeader>
              <p className="type-body min-w-0 text-ink [overflow-wrap:anywhere]" data-testid="fsp-employer-line">
                {data.employer_preview.headline}
                {data.employer_preview.more ? <span className="text-ink-muted"> · {FSP.employerView.more}</span> : null}
              </p>
              {data.employer_preview.shortened ? (
                <p className="type-caption mt-2 text-ink-muted">{FSP.employerView.shortened}</p>
              ) : null}
            </Card>
          ) : null}
        </>
      )}

      {achievements.length > 0 ? (
        <section className="flex min-w-0 flex-col gap-3" aria-labelledby="fsp-achievements">
          <h2 id="fsp-achievements" className="type-h3">
            {FSP.achievements}
          </h2>
          <FspAchievementList achievements={achievements} mode="self" />
        </section>
      ) : null}

      {data.credentials && data.credentials.length > 0 ? (
        <section className="flex min-w-0 flex-col gap-3" aria-labelledby="fsp-credentials">
          <h2 id="fsp-credentials" className="type-h3">
            {FSP.credentials}
          </h2>
          <ul className="flex min-w-0 flex-col divide-y divide-line">
            {data.credentials.map((credential) => (
              <li key={credential.id} className="flex min-w-0 flex-col gap-0.5 py-3">
                <span className="type-body min-w-0 font-medium text-ink [overflow-wrap:anywhere]">
                  {credential.label}
                </span>
                <span className="type-sm min-w-0 text-ink-muted [overflow-wrap:anywhere]">
                  {[
                    credential.kind ? CREDENTIAL_KIND_LABELS[credential.kind] : null,
                    credential.discipline_label,
                    credential.status_label,
                    credential.valid_until ? `до ${formatDate(credential.valid_until)}` : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </span>
              </li>
            ))}
          </ul>
          {achievements.length === 0 ? <p className="type-sm text-ink-muted">{FSP.rolesOnly}</p> : null}
        </section>
      ) : null}

      {data.refresh?.source_label && checkedAt ? (
        <p className="type-caption min-w-0 text-ink-muted">
          {FSP.source(data.refresh.source_label, formatDate(checkedAt))}
          {data.refresh.stale ? ` · ${FSP.stale}` : ''}
        </p>
      ) : null}

      <Actions data={data} />

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
