import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Ellipsis } from 'lucide-react'
import { useState } from 'react'
import type { NeedFunnel, NeedView } from '@/client'
import { CategoryChip, EmptyState, ErrorState, PageHeader, PageSkeleton, SalaryRange } from '@/components/app'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { needsQuery, polling } from '@/lib/query'
import { statsQuery } from '../api'
import { MATCHING } from '../content'
import { ArchiveDialog } from './archive-dialog'

const N = MATCHING.needs
const FORMATS = MATCHING.form.formats_

function NeedCard({ need, stat, onArchive }: { need: NeedView; stat?: NeedFunnel; onArchive: (id: string) => void }) {
  const f = stat?.funnel
  const invited = (f?.delivered ?? 0) + (f?.not_delivered ?? 0)
  return (
    <li className="surface-card relative flex min-w-0 flex-col gap-3 p-5">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <h2 className="type-h3 line-clamp-2 min-w-0 [overflow-wrap:anywhere]">
          <Link
            to="/employer/needs/$needId"
            params={{ needId: need.id }}
            className="text-ink after:absolute after:inset-0 after:content-[''] hover:text-brand-700"
          >
            {need.title}
          </Link>
        </h2>
        {need.status === 'active' ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`${N.menu}: ${need.title}`}
                className="relative z-10"
              >
                <Ellipsis aria-hidden="true" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem asChild>
                <Link to="/employer/needs/$needId/edit" params={{ needId: need.id }}>
                  {N.edit}
                </Link>
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => onArchive(need.id)}>{N.toArchive}</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
        <CategoryChip title={need.target.title} />
        <SalaryRange from={need.salary_from} to={need.salary_to} size="sm" />
        {need.work_formats.map((w) => (
          <span key={w} className="type-sm rounded-full bg-fill px-3 py-1">
            {FORMATS[w]}
          </span>
        ))}
      </div>
      <p className="num type-caption text-ink-muted">
        {need.latest_snapshot
          ? `${N.version} ${need.latest_snapshot.version_no} · ${N.inShortlist} ${need.latest_snapshot.items_count}`
          : N.noShortlist}
      </p>
      <p className="type-sm min-w-0 break-words text-ink-muted">
        приглашено <span className="num">{invited}</span> · ждут ответа{' '}
        <span className="num">{stat?.awaiting ?? 0}</span> · приняли <span className="num">{f?.accepted ?? 0}</span> ·
        отклонили <span className="num">{f?.declined ?? 0}</span>
        {(stat?.updates ?? 0) > 0 ? (
          <span className="ml-3 inline-flex items-center gap-1.5 font-medium text-ink">
            <span className="size-2 rounded-full bg-brand-600" aria-hidden="true" />
            {N.newReplies}: <span className="num">{stat?.updates}</span>
          </span>
        ) : null}
      </p>
    </li>
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

  const list = (rows: NeedView[], empty: React.ReactNode) =>
    rows.length === 0 ? (
      empty
    ) : (
      <ul className="grid min-w-0 gap-4 lg:grid-cols-2">
        {rows.map((n) => (
          <NeedCard key={n.id} need={n} stat={byNeed.get(n.id)} onArchive={setArchiveId} />
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
        <TabsContent value="active">
          {list(
            active,
            <EmptyState
              title={N.emptyTitle}
              text={N.emptyText}
              action={
                <Button asChild variant="secondary">
                  <Link to="/employer/needs/new">{N.create}</Link>
                </Button>
              }
            />,
          )}
        </TabsContent>
        <TabsContent value="archive">{list(archived, <EmptyState title={N.archiveEmpty} compact />)}</TabsContent>
      </Tabs>
      <ArchiveDialog needId={archiveId} onClose={() => setArchiveId(null)} />
    </div>
  )
}
