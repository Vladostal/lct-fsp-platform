import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Inbox } from 'lucide-react'
import { contactListCandidateInvitationsOptions } from '@/client/@tanstack/react-query.gen'
import { EmptyState, ErrorState } from '@/components/app'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { invitationSummaryQuery, polling } from '@/lib/query'
import { InvitationCard } from './invitation-card'
import { PauseBanner } from './pause-banner'

export type CandidateTab = 'awaiting' | 'accepted' | 'archived'

const EMPTY: Record<CandidateTab, string> = {
  awaiting:
    'Приглашений, ждущих ответа, нет. Откликаться не нужно: работодатели сами находят вашу категорию и присылают приглашение с зарплатой.',
  accepted: 'Принятых приглашений пока нет.',
  archived: 'Архив пуст: отклонённых, истёкших и отозванных приглашений нет.',
}

/** C8. Входящие приглашения: вкладки по статусам, карточки, опрос раз в 20 с. */
export function CandidateInvitationsList({ tab, onTab }: { tab: CandidateTab; onTab: (tab: CandidateTab) => void }) {
  const summary = useQuery({ ...invitationSummaryQuery, ...polling })
  const list = useQuery({
    ...contactListCandidateInvitationsOptions({ query: { status: tab, limit: 50 } }),
    ...polling,
  })
  const counts = summary.data

  const items = list.data?.items
    ? [...list.data.items].sort((a, b) =>
        tab === 'awaiting' ? a.expires_at.localeCompare(b.expires_at) : b.updated_at.localeCompare(a.updated_at),
      )
    : []

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {counts ? <PauseBanner visibility={counts.visibility} manual /> : null}
      <Tabs value={tab} onValueChange={(v) => onTab(v as CandidateTab)}>
        <TabsList aria-label="Приглашения">
          <TabsTrigger value="awaiting">Ждут ответа{counts ? ` (${counts.awaiting})` : ''}</TabsTrigger>
          <TabsTrigger value="accepted">Принятые{counts ? ` (${counts.accepted})` : ''}</TabsTrigger>
          <TabsTrigger value="archived">Архив{counts ? ` (${counts.archived})` : ''}</TabsTrigger>
        </TabsList>
      </Tabs>
      {list.isPending ? (
        <div className="flex flex-col gap-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-32 w-full rounded-lg" />
          ))}
        </div>
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} retrying={list.isFetching} />
      ) : items.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title="Здесь пока пусто"
          text={EMPTY[tab]}
          action={
            tab === 'awaiting' ? (
              <Button asChild variant="secondary">
                <Link to="/candidate">На обзор</Link>
              </Button>
            ) : undefined
          }
        />
      ) : (
        <ul className="flex min-w-0 flex-col gap-3">
          {items.map((item) => (
            <li key={item.id} className="min-w-0">
              <InvitationCard item={item} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
