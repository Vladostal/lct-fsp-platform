import { createFileRoute } from '@tanstack/react-router'
import { EmployerInvitationDetail } from '@/features/invitations'

/** E7. Приглашение — слот, срок, исход и действие по статусу. Реализует пакет F41. */
export const Route = createFileRoute('/employer/_cabinet/invitations/$invitationId')({
  component: Screen,
})

function Screen() {
  const { invitationId } = Route.useParams()
  return <EmployerInvitationDetail id={invitationId} />
}
