import { createFileRoute } from '@tanstack/react-router'
import { useCallback } from 'react'
import { BankScreen, bankSearchSchema } from '@/features/matching'

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
  return <BankScreen search={search} catalog={catalog} setSearch={setSearch} />
}
