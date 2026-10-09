import { createFileRoute } from '@tanstack/react-router'
import { useCallback } from 'react'
import { InviteFlow } from '@/features/invitations'
import { BankScreen, bankSearchSchema, type InviteRenderProps } from '@/features/matching'

/** E8. Банк кандидатов: фильтры и открытая карточка — в адресе. */
export const Route = createFileRoute('/employer/_cabinet/search')({
  validateSearch: (search) => bankSearchSchema.parse(search),
  component: Screen,
})

function Screen() {
  const search = Route.useSearch()
  const { catalog } = Route.useRouteContext()
  const navigate = Route.useNavigate()
  const setSearch = useCallback(
    (patch: Record<string, unknown>, replace = false) =>
      navigate({ search: (prev) => ({ ...prev, ...patch }), replace }),
    [navigate],
  )
  // Приглашение из банка — без привязки к потребности: её можно выбрать в самой форме (E6).
  const renderInvite = useCallback((invite: InviteRenderProps) => <InviteFlow {...invite} />, [])
  return <BankScreen search={search} catalog={catalog} setSearch={setSearch} renderInvite={renderInvite} />
}
