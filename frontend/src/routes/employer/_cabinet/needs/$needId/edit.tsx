import { createFileRoute } from '@tanstack/react-router'
import { NeedFormScreen } from '@/features/matching'

/** E3. Описание потребности (правка). */
export const Route = createFileRoute('/employer/_cabinet/needs/$needId/edit')({
  component: Screen,
})

function Screen() {
  const { needId } = Route.useParams()
  const { me, catalog } = Route.useRouteContext()
  return <NeedFormScreen key={needId} needId={needId} catalog={catalog} userId={me?.id ?? ''} />
}
