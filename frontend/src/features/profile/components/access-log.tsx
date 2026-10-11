import { useInfiniteQuery } from '@tanstack/react-query'
import { Download, Eye, FileDown, History, KeyRound, type LucideIcon } from 'lucide-react'
import type * as React from 'react'
import { EmptyState, ErrorState, IconTile, SoftPill } from '@/components/app'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime } from '@/lib/format'
import { accessLogQuery } from '../api'
import { PRIVACY } from '../content'
import { CardHead } from './card-head'

const KIND_ICON: Record<string, LucideIcon> = {
  contacts_disclosed: KeyRound,
  contacts_viewed: Eye,
  pdf_downloaded: FileDown,
  export_downloaded: Download,
}

/** Инициалы компании для плитки: первые буквы двух первых слов. */
const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase() ?? '')
    .join('')

/** Журнал доступа: кто и когда открывал данные кандидата. */
export function AccessLog() {
  const L = PRIVACY.log
  const query = useInfiniteQuery({
    ...accessLogQuery({ query: { limit: 20 } }),
    initialPageParam: { query: { limit: 20 } },
    getNextPageParam: (last) => (last.next_cursor ? { query: { limit: 20, cursor: last.next_cursor } } : undefined),
  })
  const items = query.data?.pages.flatMap((page) => page.items) ?? []

  return (
    <section className="flex min-w-0 flex-col gap-3" aria-labelledby="access-log-title">
      <CardHead icon={History} tone="soft" title={L.title} id="access-log-title" />
      {query.isPending ? (
        <Skeleton className="h-24 w-full" />
      ) : query.isError ? (
        <ErrorState
          headingLevel={3}
          compact
          error={query.error}
          onRetry={() => query.refetch()}
          retrying={query.isFetching}
        />
      ) : items.length === 0 ? (
        <EmptyState compact icon={History} headingLevel={3} title={L.empty} />
      ) : (
        <>
          <ul className="flex min-w-0 flex-col gap-2">
            {items.map((item, index) => {
              const KindIcon = KIND_ICON[item.kind] ?? Eye
              return (
                <li
                  // biome-ignore lint/suspicious/noArrayIndexKey: записи журнала не имеют идентификатора
                  key={`${item.at}-${index}`}
                  className="surface-row stagger flex min-w-0 animate-rise-in flex-wrap items-center gap-x-3 gap-y-2 p-3"
                  style={{ '--i': Math.min(index, 8) } as React.CSSProperties}
                >
                  <IconTile tone="soft">{initials(item.company_name)}</IconTile>
                  <span className="flex min-w-0 flex-1 basis-40 flex-col">
                    <strong className="type-body min-w-0 font-medium text-ink [overflow-wrap:anywhere]">
                      {item.company_name}
                    </strong>
                    <span className="type-sm flex min-w-0 items-center gap-1.5 text-ink-muted">
                      <KindIcon className="size-3.5 shrink-0 text-brand-700" aria-hidden="true" />
                      <span className="min-w-0 [overflow-wrap:anywhere]">
                        {L.actions[item.kind] ?? item.kind_label}
                      </span>
                    </span>
                  </span>
                  <SoftPill size="sm">
                    <time dateTime={item.at} className="num">
                      {formatDateTime(item.at)}
                    </time>
                  </SoftPill>
                </li>
              )
            })}
          </ul>
          {query.hasNextPage ? (
            <Button
              variant="secondary"
              className="self-start"
              loading={query.isFetchingNextPage}
              onClick={() => query.fetchNextPage()}
            >
              {L.more}
            </Button>
          ) : null}
        </>
      )}
    </section>
  )
}
