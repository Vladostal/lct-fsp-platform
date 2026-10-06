import { useInfiniteQuery } from '@tanstack/react-query'
import { EmptyState, ErrorState } from '@/components/app'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime } from '@/lib/format'
import { accessLogQuery } from '../api'
import { PRIVACY } from '../content'

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
      <h2 id="access-log-title" className="type-h3">
        {L.title}
      </h2>
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
        <EmptyState compact title={L.empty} />
      ) : (
        <>
          <ul className="flex min-w-0 flex-col">
            {items.map((item, index) => (
              <li
                // biome-ignore lint/suspicious/noArrayIndexKey: записи журнала не имеют идентификатора
                key={`${item.at}-${index}`}
                className="flex min-w-0 flex-col gap-0.5 border-b border-line py-3 last:border-b-0 sm:flex-row sm:items-baseline sm:gap-4"
              >
                <time dateTime={item.at} className="num type-sm shrink-0 text-ink-muted sm:w-40">
                  {formatDateTime(item.at)}
                </time>
                <span className="type-body min-w-0 text-ink [overflow-wrap:anywhere]">
                  <strong className="font-medium">{item.company_name}</strong> {L.actions[item.kind] ?? item.kind_label}
                </span>
              </li>
            ))}
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
