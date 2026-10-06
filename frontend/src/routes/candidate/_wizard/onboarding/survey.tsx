import { createFileRoute } from '@tanstack/react-router'
import { SurveyForm } from '@/features/assessment'

/** C2. Направление и специализация. */
export const Route = createFileRoute('/candidate/_wizard/onboarding/survey')({
  component: Screen,
})

function Screen() {
  const { me } = Route.useRouteContext()
  return <SurveyForm userId={me.id} />
}
