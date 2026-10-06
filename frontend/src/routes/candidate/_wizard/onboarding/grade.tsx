import { createFileRoute } from '@tanstack/react-router'
import { GradePicker } from '@/features/assessment'

/** C3. Выбор грейда. */
export const Route = createFileRoute('/candidate/_wizard/onboarding/grade')({
  component: Screen,
})

function Screen() {
  const { catalog } = Route.useRouteContext()
  return <GradePicker catalog={catalog} />
}
