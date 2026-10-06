import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Inbox } from 'lucide-react'
import type { InvitationStatus } from '@/client'
import {
  contactInvitationsQuotaOptions,
  contactInvitationsStatsOptions,
  contactListEmployerInvitationsInfiniteOptions,
  matchingListNeedsOptions,
} from '@/client/@tanstack/react-query.gen'
import { CategoryChip, EmptyState, ErrorState, SalaryRange, StatusBadge } from '@/components/app'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { errorText } from '@/lib/api'
import { candidateTitle, formatDate, formatDateTime, formatNumber } from '@/lib/format'
import { polling } from '@/lib/query'
import { slotLine } from './slot-line'

export type EmployerFilter = 'all' | 'awaiting' | 'accepted' | 'declined' | 'expired' | 'withdrawn' | 'bounced'

const FILTERS: { value: EmployerFilter; label: string }[] = [
  { value: 'all', label: 'Все' },
  { value: 'awaiting', label: 'Ждут ответа' },
  { value: 'accepted', label: 'Приняты' },
  { value: 'declined', label: 'Отклонены' },
  { value: 'expired', label: 'Истекли' },
  { value: 'withdrawn', label: 'Отозваны' },
  { value: 'bounced', label: 'Не доставлены' },
]

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="surface-card flex min-w-0 flex-col gap-3" aria-label={title}>
      <h2 className="type-h3 text-ink">{title}</h2>
      {children}
    </section>
  )
}

function Quota() {
  const quota = useQuery({ ...contactInvitationsQuotaOptions(), ...polling })
  if (quota.isPending) return <Skeleton className="h-24 w-full" />
  if (quota.isError)
    return <ErrorState compact headingLevel={3} error={quota.error} onRetry={() => void quota.refetch()} />
  const q = quota.data
  return (
    <Section title="Слоты">
      {q.frozen ? (
        <Alert variant="destructive">
          <AlertDescription>{errorText('sending_frozen')}</AlertDescription>
        </Alert>
      ) : null}
      <p className="num type-body text-ink">
        Занято {q.used} из {q.limit}
      </p>
      <Progress value={q.limit > 0 ? (q.used / q.limit) * 100 : 0} aria-label="Занятые слоты" />
      <p className="type-sm text-ink-muted">
        {q.next_release_at ? `Ближайший освободится ${formatDateTime(q.next_release_at)}. ` : ''}За сутки отправлено{' '}
        {q.daily_used} из {q.daily_limit}
      </p>
    </Section>
  )
}

function Stats() {
  const stats = useQuery({ ...contactInvitationsStatsOptions(), ...polling })
  if (stats.isPending) return <Skeleton className="h-24 w-full" />
  if (stats.isError)
    return <ErrorState compact headingLevel={3} error={stats.error} onRetry={() => void stats.refetch()} />
  const t = stats.data.total
  const items: [string, number | undefined][] = [
    ['доставлено', t.delivered],
    ['не доставлено', t.not_delivered],
    ['просмотрено', t.viewed],
    ['принято', t.accepted],
    ['отклонено', t.declined],
    ['истекло', t.expired],
  ]
  return (
    <Section title="Итоги">
      <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {items.map(([label, value]) => (
          <div key={label} className="min-w-0">
            <dd className="num text-2xl leading-8 font-medium text-ink">{formatNumber(value ?? 0)}</dd>
            <dt className="type-sm text-ink-muted">{label}</dt>
          </div>
        ))}
      </dl>
      {stats.data.median_response_hours != null ? (
        <p className="type-sm text-ink-muted">
          Медиана времени до ответа: {Math.round(stats.data.median_response_hours)} ч
        </p>
      ) : null}
      {stats.data.reasons.length > 0 ? (
        <div className="min-w-0">
          <p className="type-sm font-medium text-ink">Причины отказов</p>
          <ul className="type-sm text-ink-muted">
            {stats.data.reasons.map((r) => (
              <li key={r.reason_code}>
                {r.reason_label}: <span className="num">{r.count}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Section>
  )
}

/** E7. Список: слоты, итоги, фильтры и таблица (на узком экране — карточки). */
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
  const list = useInfiniteQuery({
    ...contactListEmployerInvitationsInfiniteOptions({ query: { status, need_id: needId ?? null, limit: 20 } }),
    initialPageParam: undefined as unknown as string,
    getNextPageParam: (last) => last.next_cursor ?? undefined,
    ...polling,
  })
  const items = list.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <div className="flex min-w-0 flex-col gap-4">
      <div className="grid min-w-0 gap-4 lg:grid-cols-2">
        <Quota />
        <Stats />
      </div>
      <div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <ToggleGroup
          type="single"
          value={status}
          onValueChange={(v) => v && onChange({ status: v as EmployerFilter })}
          aria-label="Статус приглашений"
        >
          {FILTERS.map((f) => (
            <ToggleGroupItem key={f.value} value={f.value}>
              {f.label}
            </ToggleGroupItem>
          ))}
        </ToggleGroup>
        {needs.data && needs.data.length > 0 ? (
          <Select value={needId ?? 'all'} onValueChange={(v) => onChange({ need: v === 'all' ? undefined : v })}>
            <SelectTrigger aria-label="Потребность" className="md:w-64">
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
          <div className="hidden md:block">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Кандидат</TableHead>
                  <TableHead>Предложение</TableHead>
                  <TableHead>Вилка</TableHead>
                  <TableHead>Статус</TableHead>
                  <TableHead>Слот и срок</TableHead>
                  <TableHead>Обновлено</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {items.map((inv) => (
                  <TableRow key={inv.id}>
                    <TableCell className="min-w-0 max-w-48 align-top">
                      <Link
                        to="/employer/invitations/$invitationId"
                        params={{ invitationId: inv.id }}
                        className="flex flex-col gap-1 text-ink hover:text-brand-700"
                      >
                        <span className="num truncate">
                          {candidateTitle(inv.candidate.display_name, inv.candidate.public_code)}
                        </span>
                        <CategoryChip title={inv.candidate.category.title} />
                      </Link>
                    </TableCell>
                    <TableCell className="max-w-64 align-top">
                      <p className="line-clamp-2 [overflow-wrap:anywhere]">{inv.title}</p>
                      {inv.need ? <p className="type-sm truncate text-ink-muted">{inv.need.title}</p> : null}
                    </TableCell>
                    <TableCell className="align-top">
                      <SalaryRange from={inv.salary_from} to={inv.salary_to} size="sm" />
                    </TableCell>
                    <TableCell className="align-top">
                      <div className="flex flex-col items-start gap-1">
                        <StatusBadge status={inv.status} label={inv.status_label} size="sm" />
                        {inv.is_new_for_employer ? <NewMark /> : null}
                      </div>
                    </TableCell>
                    <TableCell className="type-sm max-w-64 align-top text-ink-muted [overflow-wrap:anywhere]">
                      {slotLine(inv)}
                    </TableCell>
                    <TableCell className="num type-sm align-top text-ink-muted">{formatDate(inv.updated_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
          <ul className="flex min-w-0 flex-col gap-3 md:hidden">
            {items.map((inv) => (
              <li key={inv.id} className="min-w-0">
                <Link
                  to="/employer/invitations/$invitationId"
                  params={{ invitationId: inv.id }}
                  className="surface-row flex min-w-0 flex-col gap-2 p-4"
                >
                  <div className="flex min-w-0 items-start justify-between gap-3">
                    <span className="num type-body min-w-0 truncate text-ink">
                      {candidateTitle(inv.candidate.display_name, inv.candidate.public_code)}
                    </span>
                    <StatusBadge status={inv.status} label={inv.status_label} size="sm" />
                  </div>
                  <p className="type-body line-clamp-2 [overflow-wrap:anywhere] text-ink">{inv.title}</p>
                  <SalaryRange from={inv.salary_from} to={inv.salary_to} size="sm" />
                  <p className="type-sm text-ink-muted [overflow-wrap:anywhere]">{slotLine(inv)}</p>
                  {inv.is_new_for_employer ? <NewMark /> : null}
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

function NewMark() {
  return (
    <span className="type-caption flex items-center gap-1 text-brand-700">
      <span aria-hidden="true" className="size-2 rounded-full bg-brand-600" />
      новое
    </span>
  )
}

export type { InvitationStatus }
