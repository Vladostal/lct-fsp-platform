import { createFileRoute } from '@tanstack/react-router'
import { ProfileStep } from '@/features/profile'

/** C1. Расскажите о себе: профиль, резюме и условия (шаг 1 мастера). */
export const Route = createFileRoute('/candidate/_wizard/onboarding/profile')({
  component: Screen,
})

function Screen() {
  const { me, catalog } = Route.useRouteContext()
  return <ProfileStep userId={me.id} catalog={catalog ?? null} />
}
