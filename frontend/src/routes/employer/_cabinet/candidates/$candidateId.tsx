import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { PageHeader } from '@/components/app'
import { InviteFlow } from '@/features/invitations'
import { CandidateView, cardQuery, cardSearchSchema } from '@/features/matching'
import { candidateTitle } from '@/lib/format'

/** E5. Карточка кандидата страницей (прямая ссылка из приглашений, письма). */
export const Route = createFileRoute('/employer/_cabinet/candidates/$candidateId')({
  validateSearch: (search) => cardSearchSchema.parse(search),
  component: Screen,
})

function Screen() {
  const { candidateId } = Route.useParams()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  // Тот же ключ, что у CandidateView: второго запроса нет, заголовок берёт имя или код из кэша карточки.
  const card = useQuery(cardQuery(candidateId, search.need, search.snapshot)).data
  const name = card ? candidateTitle(card.display_name, card.public_code) : null
  return (
    <div className="mx-auto flex w-full min-w-0 max-w-[760px] flex-col gap-6">
      <PageHeader
        eyebrow="Карточка кандидата"
        documentTitle={name ?? 'Карточка кандидата'}
        title={<span className="num min-w-0 [overflow-wrap:anywhere]">{name ?? 'Карточка кандидата'}</span>}
        back={
          search.need
            ? { label: 'К подборке', href: `/employer/needs/${search.need}` }
            : { label: 'К банку кандидатов', href: '/employer/search' }
        }
      />
      <CandidateView
        key={candidateId}
        candidateId={candidateId}
        needId={search.need}
        snapshotId={search.snapshot}
        invite={Boolean(search.invite)}
        onInvite={() => navigate({ search: (prev) => ({ ...prev, invite: true }) })}
        onBackFromInvite={() => navigate({ search: (prev) => ({ ...prev, invite: undefined, revises: undefined }) })}
        renderInvite={(invite) => <InviteFlow {...invite} revisesId={search.revises} />}
        layout="page"
      />
    </div>
  )
}
