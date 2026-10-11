import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { z } from 'zod'
import { PageHeader } from '@/components/app'
import { EmployerInvitationsList } from '@/features/invitations'

const searchSchema = z.object({
  status: z
    .enum(['all', 'awaiting', 'accepted', 'declined', 'expired', 'withdrawn', 'bounced'])
    .optional()
    .catch(undefined),
  need: z.string().optional().catch(undefined),
})

/** E7. Приглашения — итоги, статусы. Реализует пакет F41. */
export const Route = createFileRoute('/employer/_cabinet/invitations/')({
  validateSearch: (search) => searchSchema.parse(search),
  component: Screen,
})

function Screen() {
  const { status = 'all', need } = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader title="Приглашения" description="Срок и исход по каждому приглашению." />
      <EmployerInvitationsList
        status={status}
        needId={need}
        onChange={(next) =>
          void navigate({
            search: (prev) => ({
              status: next.status ?? prev.status,
              need: 'need' in next ? next.need : prev.need,
            }),
            replace: true,
          })
        }
      />
    </div>
  )
}
