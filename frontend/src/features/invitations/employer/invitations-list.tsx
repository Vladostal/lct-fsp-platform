import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { CalendarDays, Hourglass, Inbox, Info, UserRound } from 'lucide-react'
import type { InvitationEmployerBrief, InvitationFunnel, InvitationStatus } from '@/client'
import {
  contactInvitationsQuotaOptions,
  contactInvitationsStatsOptions,
  contactListEmployerInvitationsInfiniteOptions,
  matchingListNeedsOptions,
} from '@/client/@tanstack/react-query.gen'
import { CandidateCategoryChip, EmptyState, ErrorState, SalaryRange, StatusBadge } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { errorText } from '@/lib/api'
import { candidateTitle, formatDate, formatDateTime, initials } from '@/lib/format'
import { polling } from '@/lib/query'
import { cn } from '@/lib/utils'
import { DASHBOARD, LIST } from './content'
import { InvitationsDashboard } from './invitations-dashboard'

export type EmployerFilter = 'all' | 'awaiting' | 'accepted' | 'declined' | 'expired' | 'withdrawn' | 'bounced'

const FILTERS: EmployerFilter[] = ['all', 'awaiting', 'accepted', 'declined', 'expired', 'withdrawn', 'bounced']

/** Счётчики чипов фильтра из воронки (общей либо выбранной потребности). */
function filterCounts(funnel: InvitationFunnel): Record<EmployerFilter, number> {
  const delivered = funnel.delivered ?? 0
  const accepted = funnel.accepted ?? 0
  const declined = funnel.declined ?? 0
  const expired = funnel.expired ?? 0
  const withdrawn = funnel.withdrawn ?? 0
  const bounced = funnel.not_delivered ?? 0
  return {
    all: delivered + bounced,
    awaiting: Math.max(0, delivered - accepted - declined - expired - withdrawn),
    accepted,
    declined,
    expired,
    withdrawn,
    bounced,
  }
}

/** Итоги приглашений: воронка, исходы, время ответа. */
function Summary() {
  const quota = useQuery({ ...contactInvitationsQuotaOptions(), ...polling })
  const stats = useQuery({ ...contactInvitationsStatsOptions(), ...polling })
  if (quota.isPending || stats.isPending) return <Skeleton className="h-56 w-full" />
  if (quota.isError)
    return <ErrorState compact headingLevel={3} error={quota.error} onRetry={() => void quota.refetch()} />
  if (stats.isError)
    return <ErrorState compact headingLevel={3} error={stats.error} onRetry={() => void stats.refetch()} />
  return (
    <section className="surface-card flex min-w-0 flex-col gap-5" aria-label={DASHBOARD.title}>
      {quota.data.frozen ? (
        <Alert variant="destructive">
          <AlertDescription>{errorText('sending_frozen')}</AlertDescription>
        </Alert>
      ) : null}
      <InvitationsDashboard stats={stats.data} />
    </section>
  )
}

const TILE_TONES: Record<InvitationStatus, string> = {
  sent: 'bg-brand-100 text-brand-700',
  viewed: 'bg-brand-100 text-brand-700',
  accepted: 'bg-success-bg text-success',
  declined: 'bg-danger-bg text-danger',
  expired: 'bg-warning-bg text-warning',
  // Не дошло до кандидата: пунктир без заливки, как в сводке.
  bounced: 'border border-dashed border-line-strong bg-surface text-ink-muted',
  withdrawn: 'bg-fill text-ink',
}

/** Плитка кандидата: инициалы, если имя раскрыто, иначе силуэт. Цвет повторяет тон статуса. */
function CandidateTile({ inv }: { inv: InvitationEmployerBrief }) {
  const name = inv.candidate.display_name?.trim()
  return (
    <span
      aria-hidden="true"
      className={cn(
        'type-sm flex size-10 shrink-0 items-center justify-center rounded-lg font-semibold',
        TILE_TONES[inv.status],
      )}
    >
      {name ? initials(name) : <UserRound className="size-5" />}
    </span>
  )
}

/** Вторая строка статуса: только то, чего нет в плашке. Дата исхода стоит в колонке «Обновлено». */
function StatusNote({ inv, withDate = false }: { inv: InvitationEmployerBrief; withDate?: boolean }) {
  let icon = CalendarDays
  let text: string
  let prefix = ''
  switch (inv.status) {
    case 'sent':
    case 'viewed':
      icon = Hourglass
      prefix = LIST.answerBy
      text = `${LIST.until} ${formatDateTime(inv.expires_at)}`
      break
    case 'bounced':
      icon = Info
      text = LIST.bounced
      break
    case 'expired':
      text = formatDate(inv.expires_at)
      break
    default:
      if (!withDate) return null
      text = formatDate(inv.updated_at)
  }
  const Icon = icon
  return (
    <span className="type-sm inline-flex min-w-0 items-center gap-1.5 text-ink-muted">
      <Icon aria-hidden="true" className="size-3.5" />
      <span className="num min-w-0 whitespace-normal">
        {prefix ? <span className="sr-only">{prefix} </span> : null}
        {text}
      </span>
    </span>
  )
}

/** Плашка статуса; отказ красный, недоставленное нейтральное — как в сводке. */
function StatusPill({ inv }: { inv: InvitationEmployerBrief }) {
  return (
    <StatusBadge
      status={inv.status}
      label={inv.status_label}
      size="sm"
      appearance="pill"
      tone={inv.status === 'declined' ? 'danger' : inv.status === 'bounced' ? 'neutral' : undefined}
      className="rounded-full"
    />
  )
}

// Вилка нейтральная: зелёный на этом экране значит «принято».
const SALARY_PILL = 'w-fit rounded-full bg-fill px-2.5 py-0.5 font-medium text-ink'

/** E7. Список: итоги, фильтры и таблица (на узком экране — карточки). */
export function EmployerInvitationsList({
  status,
  needId,
  onChange,
}: {
  status: EmployerFilter
  needId: string | undefined
  onChange: (next: { status?: EmployerFilter; need?: string | undefined }) => void
}) {
  const needs = useQuery(matchingListNeedsOptions())
  // Тот же запрос, что у сводки: счётчики чипов берутся из кэша.
  const stats = useQuery({ ...contactInvitationsStatsOptions(), ...polling })
  const funnel = needId ? stats.data?.by_need.find((n) => n.need_id === needId)?.funnel : stats.data?.total
  const counts = funnel ? filterCounts(funnel) : null
  const list = useInfiniteQuery({
    ...contactListEmployerInvitationsInfiniteOptions({ query: { status, need_id: needId ?? null, limit: 20 } }),
    initialPageParam: undefined as unknown as string,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    ...polling,
  })
  const items = list.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <Summary />
      <div className="flex min-w-0 flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <ToggleGroup
          type="single"
          value={status}
          onValueChange={(v) => v && onChange({ status: v as EmployerFilter })}
          aria-label="Статус приглашений"
          size="sm"
        >
          {FILTERS.map((f) => (
            <ToggleGroupItem key={f} value={f}>
              {LIST.filters[f]}
              {counts ? (
                <span className="num type-caption min-w-5 rounded-full bg-fill px-1.5 py-0.5 text-center font-medium text-ink group-data-[state=on]/toggle-item:bg-brand-100 group-data-[state=on]/toggle-item:text-brand-700">
                  {counts[f]}
                </span>
              ) : null}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {needs.data && needs.data.length > 0 ? (
          <Select value={needId ?? 'all'} onValueChange={(v) => onChange({ need: v === 'all' ? undefined : v })}>
            <SelectTrigger aria-label="Потребность" className="shrink-0 md:w-64">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Все потребности</SelectItem>
              {needs.data.map((n) => (
                <SelectItem key={n.id} value={n.id}>
                  {n.title}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        ) : null}
      </div>

      {list.isPending ? (
        <div className="flex flex-col gap-2" aria-busy="true">
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} retrying={list.isFetching} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title={status === 'all' && !needId ? 'Приглашений пока нет' : 'По этому фильтру приглашений нет'}
          text={
            status === 'all' && !needId
              ? 'Откройте подборку по потребности, выберите кандидата и отправьте приглашение с вилкой зарплаты.'
              : 'Смените фильтр, чтобы увидеть другие приглашения.'
          }
          action={
            status === 'all' && !needId ? (
              <Button asChild variant="secondary">
                <Link to="/employer/needs">К потребностям</Link>
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          <div className="surface-row hidden overflow-hidden lg:block">
            <Table>
              <TableHeader>
                <TableRow className="bg-canvas hover:bg-canvas">
                  <TableHead className="pl-5">{LIST.columns.candidate}</TableHead>
                  <TableHead>{LIST.columns.offer}</TableHead>
                  <TableHead>{LIST.columns.status}</TableHead>
                  <TableHead className="pr-5 text-right">{LIST.columns.updated}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((inv) => (
                  <TableRow key={inv.id} className="hover:bg-brand-50">
                    <TableCell className="max-w-64 py-4 pl-5">
                      <Link
                        to="/employer/invitations/$invitationId"
                        params={{ invitationId: inv.id }}
                        className="group/cand flex min-w-0 items-center gap-3 text-ink hover:text-brand-700"
                      >
                        <CandidateTile inv={inv} />
                        <span className="flex min-w-0 flex-col gap-0.5">
                          <span className="num type-body truncate font-medium">
                            {candidateTitle(inv.candidate.display_name, inv.candidate.public_code)}
                          </span>
                          <CandidateCategoryChip
                            category={inv.candidate.category}
                            className="font-normal text-ink-muted"
                          />
                        </span>
                      </Link>
                    </TableCell>
                    <TableCell className="max-w-72 py-4">
                      <div className="flex min-w-0 flex-col items-start gap-1.5">
                        <p className="type-sm line-clamp-2 [overflow-wrap:anywhere] text-ink">{inv.title}</p>
                        <SalaryRange from={inv.salary_from} to={inv.salary_to} size="sm" className={SALARY_PILL} />
                        {inv.need && inv.need.title !== inv.title ? (
                          <p className="type-caption max-w-full truncate text-ink-muted">{inv.need.title}</p>
                        ) : null}
                      </div>
                    </TableCell>
                    <TableCell className="max-w-64 py-4">
                      <div className="flex flex-col items-start gap-1.5">
                        <span className="flex flex-wrap items-center gap-2">
                          <StatusPill inv={inv} />
                        </span>
                        <StatusNote inv={inv} />
                      </div>
                    </TableCell>
                    <TableCell className="num type-sm py-4 pr-5 text-right text-ink-muted">
                      {formatDate(inv.updated_at)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <ul className="flex min-w-0 flex-col gap-3 md:grid md:grid-cols-2 lg:hidden">
            {items.map((inv) => (
              <li key={inv.id} className="min-w-0">
                <Link
                  to="/employer/invitations/$invitationId"
                  params={{ invitationId: inv.id }}
                  className="surface-row flex h-full min-w-0 flex-col gap-3 p-4 transition-colors duration-(--dur-fast) hover:border-brand-200 hover:bg-brand-50"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <CandidateTile inv={inv} />
                    <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                      <span className="num type-body min-w-0 truncate font-medium text-ink">
                        {candidateTitle(inv.candidate.display_name, inv.candidate.public_code)}
                      </span>
                      <CandidateCategoryChip category={inv.candidate.category} className="font-normal text-ink-muted" />
                    </span>
                  </div>
                  <p className="type-sm line-clamp-2 [overflow-wrap:anywhere] text-ink">{inv.title}</p>
                  <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
                    <SalaryRange from={inv.salary_from} to={inv.salary_to} size="sm" className={SALARY_PILL} />
                  </div>
                  <div className="mt-auto flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2 border-t border-line pt-3">
                    <StatusPill inv={inv} />
                    <StatusNote inv={inv} withDate />
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          {list.hasNextPage ? (
            <Button
              variant="secondary"
              className="self-center"
              loading={list.isFetchingNextPage}
              onClick={() => void list.fetchNextPage()}
            >
              Показать ещё
            </Button>
          ) : null}
        </>
      )}
    </div>
  )
}

export type { InvitationStatus }
