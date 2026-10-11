import type { QueryClient } from '@tanstack/react-query'
import { createRootRouteWithContext, Outlet, useRouterState } from '@tanstack/react-router'
import { useEffect, useRef } from 'react'
import type { Catalog, MeView } from '@/client'
import { NotFound, PublicLayout } from '@/components/app'
import { RouteProgress } from '@/components/app/layout/route-progress'
import { roleRoot } from '@/lib/guards'
import { catalogQuery, meQuery } from '@/lib/query'

export type RouterContext = {
  queryClient: QueryClient
}

/**
 * Корень дерева маршрутов. В `beforeLoad` читаются `me` (401 означает «гость») и каталог с флагами стенда;
 * оба результата попадают в контекст дочерних маршрутов.
 *
 * Сбой этих запросов не роняет публичные страницы: `me` считается неизвестным (`meError`), каталог — `null`.
 * Закрытые маршруты при `meError` показывают ошибку с «Повторить», а не уводят на вход.
 */
export const Route = createRootRouteWithContext<RouterContext>()({
  beforeLoad: async ({ context }) => {
    const [meResult, catalogResult] = await Promise.allSettled([
      context.queryClient.fetchQuery(meQuery),
      context.queryClient.ensureQueryData(catalogQuery),
    ])
    const me: MeView | null = meResult.status === 'fulfilled' ? meResult.value : null
    const meError: unknown = meResult.status === 'rejected' ? meResult.reason : null
    const catalog: Catalog | null = catalogResult.status === 'fulfilled' ? catalogResult.value : null
    return { me, meError, catalog }
  },
  component: RootComponent,
  notFoundComponent: RootNotFound,
})

/**
 * После смены маршрута фокус переходит на заголовок страницы (E §7): пользователь клавиатуры и скринридера
 * узнаёт, что экран сменился. При первой загрузке фокус не трогаем.
 */
function useFocusPageTitle() {
  const pathname = useRouterState({ select: (state) => state.resolvedLocation?.pathname })
  const previous = useRef<string | undefined>(undefined)
  useEffect(() => {
    if (pathname === undefined) return
    if (previous.current !== undefined && previous.current !== pathname) {
      const frame = window.requestAnimationFrame(() => {
        const title =
          document.querySelector<HTMLElement>('[data-page-title]') ?? document.querySelector<HTMLElement>('h1')
        if (title && !title.hasAttribute('tabindex')) title.setAttribute('tabindex', '-1')
        title?.focus({ preventScroll: true })
      })
      previous.current = pathname
      return () => window.cancelAnimationFrame(frame)
    }
    previous.current = pathname
  }, [pathname])
}

function RootComponent() {
  useFocusPageTitle()
  return (
    <>
      <RouteProgress />
      <Outlet />
    </>
  )
}

/** Неизвестный адрес верхнего уровня: 404 в публичном каркасе со ссылкой на первый экран роли. */
function RootNotFound() {
  const { me, catalog } = Route.useRouteContext()
  const homeHref = me ? roleRoot(me.role) : '/'
  return (
    <PublicLayout signedIn={Boolean(me)} homeHref={homeHref} demo={catalog?.features.demo ?? false}>
      <div className="page-container">
        <NotFound homeHref={homeHref} />
      </div>
    </PublicLayout>
  )
}
