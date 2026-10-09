import { createFileRoute } from '@tanstack/react-router'
import { useCallback } from 'react'
import { InviteFlow } from '@/features/invitations'
import { type InviteRenderProps, NeedScreen, needSearchSchema } from '@/features/matching'

/** E4. Подборка: вкладка, версия, вид, категория, открытая карточка и режим приглашения — в адресе. */
export const Route = createFileRoute('/employer/_cabinet/needs/$needId/')({
  validateSearch: (search) => needSearchSchema.parse(search),
  component: Screen,
})

function Screen() {
  const { needId } = Route.useParams()
  const search = Route.useSearch()
  const { catalog } = Route.useRouteContext()
  const navigate = Route.useNavigate()
  const setSearch = useCallback(
    (patch: Record<string, unknown>, replace = false) =>
      navigate({ search: (prev) => ({ ...prev, ...patch }), replace }),
    [navigate],
  )
  // Форму отправки приглашения (E6) подключает маршрут: домен подбора о домене приглашений не знает.
  const renderInvite = useCallback(
    (invite: InviteRenderProps) => <InviteFlow {...invite} revisesId={search.revises} />,
    [search.revises],
  )
  return (
    <NeedScreen
      key={needId}
      needId={needId}
      search={search}
      catalog={catalog}
      setSearch={setSearch}
      renderInvite={renderInvite}
    />
  )
}
