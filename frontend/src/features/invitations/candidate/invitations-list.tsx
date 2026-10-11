import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Archive, CircleCheck, Hourglass, Inbox, TimerOff } from 'lucide-react'
import { contactListCandidateInvitationsOptions } from '@/client/@tanstack/react-query.gen'
import { EmptyState, ErrorState, SoftPill, StatTile, SummaryStrip } from '@/components/app'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { invitationSummaryQuery, polling } from '@/lib/query'
import { InvitationCard } from './invitation-card'
import { PauseBanner } from './pause-banner'

export type CandidateTab = 'awaiting' | 'accepted' | 'archived'

const EMPTY: Record<CandidateTab, string> = {
  awaiting: 'Работодатели сами присылают приглашение с зарплатой.',
  accepted: 'Принятых приглашений нет.',
  archived: 'Отклонённых, истёкших и отозванных нет.',
}

/** C8. Входящие приглашения: вкладки по статусам, карточки, опрос раз в 20 с. */
export function CandidateInvitationsList({ tab, onTab }: { tab: CandidateTab; onTab: (tab: CandidateTab) => void }) {
  const summary = useQuery({ ...invitationSummaryQuery, ...polling })
  const list = useQuery({
    ...contactListCandidateInvitationsOptions({ query: { status: tab, limit: 50 } }),
    ...polling,
  })
  const counts = summary.data
  // Числа несёт полоса сводки (во вкладках их нет); когда везде ноль, полоса не нужна.
  const hasAny = counts ? counts.awaiting + counts.accepted + counts.archived + counts.strikes.count > 0 : false

  const items = list.data?.items
    ? [...list.data.items].sort((a, b) =>
        tab === 'awaiting' ? a.expires_at.localeCompare(b.expires_at) : b.updated_at.localeCompare(a.updated_at),
      )
    : []

  return (
    <div className="flex min-w-0 flex-col gap-4">
      {counts ? <PauseBanner visibility={counts.visibility} manual /> : null}
      {counts && hasAny ? (
        <SummaryStrip
          label="Приглашения по статусам"
          aside={
            counts.strikes.count > 0 ? (
              <SoftPill tone="warning" icon={TimerOff} className="max-sm:hidden">
                <span className="num">
                  пропущено {counts.strikes.count} из {counts.strikes.limit}
                </span>
              </SoftPill>
            ) : undefined
          }
        >
          <StatTile icon={Hourglass} value={counts.awaiting} label="ждут ответа" tone="warning" />
          <StatTile icon={CircleCheck} value={counts.accepted} label="принято" tone="success" />
          <StatTile icon={Archive} value={counts.archived} label="в архиве" tone="neutral" />
        </SummaryStrip>
      ) : null}
      <Tabs value={tab} onValueChange={(v) => onTab(v as CandidateTab)}>
        <TabsList aria-label="Приглашения">
          <TabsTrigger value="awaiting">Ждут ответа</TabsTrigger>
          <TabsTrigger value="accepted">Принятые</TabsTrigger>
          <TabsTrigger value="archived">Архив</TabsTrigger>
        </TabsList>
      </Tabs>
      {list.isPending ? (
        <div className="grid gap-3 lg:grid-cols-2 lg:gap-4" aria-busy="true">
          {[0, 1].map((i) => (
            <Skeleton key={i} className="h-40 w-full rounded-lg" />
          ))}
        </div>
      ) : list.isError ? (
        <ErrorState error={list.error} onRetry={() => void list.refetch()} retrying={list.isFetching} />
      ) : items.length === 0 ? (
        <div className="surface-card min-w-0 animate-rise-in">
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
        </div>
      ) : (
        <ul className="grid min-w-0 gap-3 lg:grid-cols-2 lg:gap-4">
          {items.map((item, index) => (
            <li key={item.id} className="min-w-0">
              <InvitationCard item={item} index={index} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
