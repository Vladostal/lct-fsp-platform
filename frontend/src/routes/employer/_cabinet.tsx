import { createFileRoute, Outlet } from '@tanstack/react-router'
import { CabinetFrame } from '@/features/auth'

/** Каркас Cabinet работодателя: шапка с навигацией и отметкой о приостановке отправки. */
export const Route = createFileRoute('/employer/_cabinet')({
  component: EmployerCabinet,
})

function EmployerCabinet() {
  const { me } = Route.useRouteContext()
  return (
    <CabinetFrame me={me}>
      <Outlet />
    </CabinetFrame>
  )
}
