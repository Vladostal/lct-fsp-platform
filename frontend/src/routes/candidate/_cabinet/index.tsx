import { createFileRoute } from '@tanstack/react-router'
import { PageHeader } from '@/components/app'
import { CandidateOverview } from '@/features/invitations'

/** C7. Обзор — статус профиля, спрос на категорию, приглашения. Реализует пакет F40. */
export const Route = createFileRoute('/candidate/_cabinet/')({
  component: Screen,
})

function Screen() {
  return (
    <div className="flex min-w-0 flex-col gap-6">
      <PageHeader title="Обзор" />
      <CandidateOverview />
    </div>
  )
}
