import { createFileRoute, Outlet } from '@tanstack/react-router'
import { CabinetFrame } from '@/features/auth'

/** Каркас Cabinet работодателя: шапка с навигацией и квотой «Слоты {used} / {limit}». */
export const Route = createFileRoute('/employer/_cabinet')({
  component: EmployerCabinet,
})

function EmployerCabinet() {
  const { me, catalog } = Route.useRouteContext()
  return (
    <CabinetFrame me={me} features={catalog?.features ?? null}>
      <Outlet />
    </CabinetFrame>
  )
}
