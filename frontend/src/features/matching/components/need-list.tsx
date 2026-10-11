import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Hourglass, type LucideIcon, Send, UserRoundCheck } from 'lucide-react'
import { useState } from 'react'
import type { NeedView } from '@/client'
import { EmptyState, ErrorState, PageHeader, PageSkeleton } from '@/components/app'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { needsQuery, polling } from '@/lib/query'
import { statsQuery } from '../api'
import { MATCHING } from '../content'
import { ArchiveDialog } from './archive-dialog'
import { NEED_LIST_CSS, NeedCard } from './need-list-card'

const N = MATCHING.needs

type Figure = { Icon: LucideIcon; value: number; label: string; tile: string }

/** Сводка активных потребностей: одна акцентная полоса — три числа со значками и кольцо «приняли / приглашено». */
function Summary({ items, accepted, invited }: { items: readonly Figure[]; accepted: number; invited: number }) {
  const R = 20
  const C = 2 * Math.PI * R
  const share = invited > 0 ? Math.min(1, accepted / invited) : 0
  return (
    <div className="nl-band surface-row flex min-w-0 animate-rise-in items-center gap-2 p-3 sm:gap-6 sm:p-4 md:px-6">
      <dl aria-label={N.summary} className="flex min-w-0 flex-1 items-stretch divide-x divide-line">
        {items.map((it) => (
          <div
            key={it.label}
            className="flex min-w-0 flex-auto flex-col gap-1 px-1.5 first:pl-0 min-[360px]:px-2.5 sm:flex-none sm:flex-row sm:items-center sm:gap-3 sm:px-6 lg:px-8"
          >
            <span
              aria-hidden="true"
              className={`flex size-8 shrink-0 items-center justify-center rounded-lg sm:size-10 ${it.tile}`}
            >
              <it.Icon className="size-4 sm:size-5" />
            </span>
            <div className="flex min-w-0 flex-col-reverse">
              <dt className="text-[0.6875rem] leading-4 tracking-tight whitespace-nowrap text-ink-muted sm:text-xs sm:tracking-normal">
                {it.label}
              </dt>
              <dd className="num text-2xl leading-7 font-semibold text-ink">{it.value}</dd>
            </div>
          </div>
        ))}
      </dl>
      {invited > 0 ? (
        <div
          role="img"
          aria-label={N.acceptRate(accepted, invited)}
          title={N.acceptRate(accepted, invited)}
          className="relative flex size-12 shrink-0 min-[360px]:size-14 items-center justify-center sm:size-16"
        >
          <svg viewBox="0 0 48 48" aria-hidden="true" className="absolute inset-0 size-full -rotate-90">
            <circle cx="24" cy="24" r={R} fill="none" strokeWidth="5" stroke="var(--color-brand-100)" />
            <circle
              cx="24"
              cy="24"
              r={R}
              fill="none"
              strokeWidth="5"
              strokeLinecap="round"
              stroke="var(--color-success)"
              strokeDasharray={`${share * C} ${C}`}
            />
          </svg>
          <span aria-hidden="true" className="num text-xs font-semibold text-ink min-[360px]:text-sm">
            {Math.round(share * 100)}%
          </span>
        </div>
      ) : null}
    </div>
  )
}

export function NeedListScreen() {
  const needs = useQuery({ ...needsQuery, ...polling })
  const stats = useQuery({ ...statsQuery, ...polling })
  const [archiveId, setArchiveId] = useState<string | null>(null)

  const header = (
    <PageHeader
      title={N.title}
      description={N.description}
      actions={
        <Button asChild variant="primary">
          <Link to="/employer/needs/new">{N.create}</Link>
        </Button>
      }
    />
  )
  if (needs.isPending) return <PageSkeleton variant="cards" />
  if (needs.isError) return <ErrorState error={needs.error} onRetry={() => needs.refetch()} />

  const byNeed = new Map((stats.data?.by_need ?? []).map((s) => [s.need_id, s]))
  const active = needs.data.filter((n) => n.status === 'active')
  const archived = needs.data.filter((n) => n.status === 'archived')

  let invited = 0
  let accepted = 0
  let awaiting = 0
  for (const n of active) {
    const f = byNeed.get(n.id)?.funnel
    awaiting += byNeed.get(n.id)?.awaiting ?? 0
    invited += (f?.delivered ?? 0) + (f?.not_delivered ?? 0)
    accepted += f?.accepted ?? 0
  }

  const list = (rows: NeedView[], empty: React.ReactNode) =>
    rows.length === 0 ? (
      empty
    ) : (
      <ul className="grid min-w-0 grid-cols-1 gap-3 lg:grid-cols-2 lg:gap-4">
        {rows.map((n, i) => (
          <NeedCard key={n.id} need={n} stat={byNeed.get(n.id)} onArchive={setArchiveId} index={i} />
        ))}
      </ul>
    )

  return (
    <div className="flex min-w-0 flex-col gap-6">
      <style>{NEED_LIST_CSS}</style>
      {header}
      <Tabs defaultValue="active">
        <TabsList aria-label="Потребности">
          <TabsTrigger value="active">
            {N.active} ({active.length})
          </TabsTrigger>
          <TabsTrigger value="archive">
            {N.archive} ({archived.length})
          </TabsTrigger>
        </TabsList>
        <TabsContent value="active" className="flex min-w-0 flex-col gap-4">
          {invited > 0 ? (
            <Summary
              accepted={accepted}
              invited={invited}
              items={[
                { Icon: Send, value: invited, label: N.stageInvited, tile: 'bg-brand-600 text-white' },
                { Icon: Hourglass, value: awaiting, label: N.awaiting, tile: 'bg-warning-bg text-warning' },
                { Icon: UserRoundCheck, value: accepted, label: N.stageAccepted, tile: 'bg-success-bg text-success' },
              ]}
            />
          ) : null}
          {list(
            active,
            // Кнопка создания уже есть в шапке страницы: вторую primary не дублируем
            <EmptyState title={N.emptyTitle} text={N.emptyText} />,
          )}
        </TabsContent>
        <TabsContent value="archive">{list(archived, <EmptyState title={N.archiveEmpty} compact />)}</TabsContent>
      </Tabs>
      <ArchiveDialog needId={archiveId} onClose={() => setArchiveId(null)} />
    </div>
  )
}
