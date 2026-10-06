import { createFileRoute } from '@tanstack/react-router'
import { CandidateInvitationDetail } from '@/features/invitations'

/** C9. Приглашение — условия, причина, ответ. Реализует пакет F40. */
export const Route = createFileRoute('/candidate/_cabinet/invitations/$invitationId')({
  component: Screen,
})

function Screen() {
  const { invitationId } = Route.useParams()
  return <CandidateInvitationDetail id={invitationId} />
}
