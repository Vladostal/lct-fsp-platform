import { createFileRoute } from '@tanstack/react-router'
import { PageHeader } from '@/components/app'
import { CandidateView, cardSearchSchema } from '@/features/matching'

/** E5. Карточка кандидата страницей (прямая ссылка из приглашений, письма). */
export const Route = createFileRoute('/employer/_cabinet/candidates/$candidateId')({
  validateSearch: (search) => cardSearchSchema.parse(search),
  component: Screen,
})

function Screen() {
  const { candidateId } = Route.useParams()
  const search = Route.useSearch()
  const navigate = Route.useNavigate()
  return (
    <div className="mx-auto flex w-full min-w-0 max-w-[760px] flex-col gap-6">
      <PageHeader
        title="Карточка кандидата"
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
        layout="page"
      />
    </div>
  )
}
