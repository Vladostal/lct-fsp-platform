import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { z } from 'zod'
import { PageHeader } from '@/components/app'
import { CandidateInvitationsList } from '@/features/invitations'

const searchSchema = z.object({ tab: z.enum(['awaiting', 'accepted', 'archived']).optional().catch(undefined) })

/** C8. Приглашения — входящие: ждут ответа, принятые, архив. Реализует пакет F40. */
export const Route = createFileRoute('/candidate/_cabinet/invitations/')({
  validateSearch: (search) => searchSchema.parse(search),
  component: Screen,
})

function Screen() {
  const { tab = 'awaiting' } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader title="Приглашения" description="Работодатели присылают предложения с зарплатой до начала общения." />
      <CandidateInvitationsList tab={tab} onTab={(next) => void navigate({ search: { tab: next }, replace: true })} />
    </div>
  )
}
