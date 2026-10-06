import { createFileRoute, Outlet, redirect } from '@tanstack/react-router'
import { NotFound } from '@/components/app'
import { CabinetFrame } from '@/features/auth'
import { employerGuard, home, loadHomeData, requireRole } from '@/lib/guards'

/**
 * Охрана кабинета работодателя (Арх. 11.3): гость уходит на вход с `next`, кандидат — на свой первый экран;
 * пока профиль компании не заполнен, доступны только он и аккаунт.
 */
export const Route = createFileRoute('/employer')({
  beforeLoad: async ({ context, location }) => {
    const me = await requireRole(context, 'employer', location.href)
    const homeData = await loadHomeData(context.queryClient, me)
    // У /employer нет своего экрана: первый экран работодателя зависит от состояния (E §1.4).
    if (location.pathname.replace(/\/$/, '') === '/employer') throw redirect({ href: home(me, homeData) })
    const target = employerGuard(location.pathname, homeData)
    if (target && target !== location.pathname) throw redirect({ href: target })
    return { me, homeData }
  },
  component: Outlet,
  notFoundComponent: EmployerNotFound,
})

/** Неизвестный адрес под /employer: 404 внутри каркаса кабинета. */
function EmployerNotFound() {
  const { me, catalog } = Route.useRouteContext()
  return (
    <CabinetFrame me={me} features={catalog?.features ?? null}>
      <NotFound homeHref="/employer/needs" />
    </CabinetFrame>
  )
}
