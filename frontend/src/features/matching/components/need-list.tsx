import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Hourglass, Send, UserRoundCheck } from 'lucide-react'
import { useState } from 'react'
import type { NeedView } from '@/client'
import {
  EmptyState,
  ErrorState,
  PageHeader,
  PageSkeleton,
  ProgressRing,
  StatTile,
  SummaryStrip,
} from '@/components/app'
import { Button } from '@/components/ui/button'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { needsQuery, polling } from '@/lib/query'
import { statsQuery } from '../api'
import { MATCHING } from '../content'
import { ArchiveDialog } from './archive-dialog'
import { NeedCard } from './need-list-card'

const N = MATCHING.needs

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
            // Сводка активных потребностей: три числа со значками и кольцо «приняли / приглашено».
            <SummaryStrip
              label={N.summary}
              aside={
                <ProgressRing
                  label={N.acceptRate(accepted, invited)}
                  value={accepted / invited}
                  className="size-12 min-[360px]:size-14 sm:size-16"
                >
                  <span aria-hidden="true" className="num text-xs font-semibold text-ink min-[360px]:text-sm">
                    {Math.round(Math.min(1, accepted / invited) * 100)}%
                  </span>
                </ProgressRing>
              }
            >
              <StatTile icon={Send} value={invited} label={N.stageInvited} tone="solid" />
              <StatTile icon={Hourglass} value={awaiting} label={N.awaiting} tone="warning" />
              <StatTile icon={UserRoundCheck} value={accepted} label={N.stageAccepted} tone="success" />
            </SummaryStrip>
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
