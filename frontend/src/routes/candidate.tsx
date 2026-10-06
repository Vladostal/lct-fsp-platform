import { createFileRoute, Outlet, redirect } from '@tanstack/react-router'
import { NotFound } from '@/components/app'
import { CabinetFrame } from '@/features/auth'
import { candidateGuard, isWizardPath, loadHomeData, requireRole } from '@/lib/guards'

/**
 * Охрана кабинета кандидата (Арх. 11.3): гость уходит на вход с `next`, работодатель — на свой первый экран;
 * шаг мастера вычисляется из профиля и состояния теста. Данные охраны лежат в контексте маршрута (`homeData`).
 */
export const Route = createFileRoute('/candidate')({
  beforeLoad: async ({ context, location }) => {
    const me = await requireRole(context, 'candidate', location.href)
    const homeData = await loadHomeData(context.queryClient, me, { fresh: isWizardPath(location.pathname) })
    const target = candidateGuard(location.pathname, homeData)
    if (target && target !== location.pathname) throw redirect({ href: target })
    return { me, homeData }
  },
  component: Outlet,
  notFoundComponent: CandidateNotFound,
})

/** Неизвестный адрес под /candidate: 404 внутри каркаса кабинета. */
function CandidateNotFound() {
  const { me, catalog } = Route.useRouteContext()
  return (
    <CabinetFrame me={me} features={catalog?.features ?? null}>
      <NotFound homeHref="/candidate" />
    </CabinetFrame>
  )
}
