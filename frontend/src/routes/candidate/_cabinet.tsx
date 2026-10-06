import { createFileRoute, Outlet } from '@tanstack/react-router'
import { CabinetFrame } from '@/features/auth'

/** Каркас Cabinet кандидата: шапка с навигацией, сводкой приглашений и видимостью профиля. */
export const Route = createFileRoute('/candidate/_cabinet')({
  component: CandidateCabinet,
})

function CandidateCabinet() {
  const { me, catalog } = Route.useRouteContext()
  return (
    <CabinetFrame me={me} features={catalog?.features ?? null}>
      <Outlet />
    </CabinetFrame>
  )
}
