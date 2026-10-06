import { createFileRoute } from '@tanstack/react-router'
import { NeedFormScreen } from '@/features/matching'

/** E3. Описание потребности (создание). */
export const Route = createFileRoute('/employer/_cabinet/needs/new')({
  component: Screen,
})

function Screen() {
  const { me, catalog } = Route.useRouteContext()
  return <NeedFormScreen catalog={catalog} userId={me?.id ?? ''} />
}
