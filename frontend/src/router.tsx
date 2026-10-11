/**
 * Маршрутизатор приложения (TanStack Router, файловые маршруты). Дерево `routeTree.gen.ts` генерирует плагин
 * сборки из каталога `routes/`; руками оно не правится.
 */
import { createRouter, type ErrorComponentProps, useRouter } from '@tanstack/react-router'
import { ErrorState, NotFound, PageSkeleton } from '@/components/app'
import { createTrailHistory } from '@/lib/history'
import { queryClient } from '@/lib/query'
import { routeTree } from './routeTree.gen'

const depth = (pathname: string) => pathname.split('/').filter(Boolean).length

/** Ошибка маршрута внутри каркаса: «Повторить» перезапускает загрузку маршрута (E §2.0). */
function RouteError({ error, reset }: ErrorComponentProps) {
  const router = useRouter()
  return (
    <ErrorState
      error={error}
      headingLevel={1}
      onRetry={() => {
        reset()
        void router.invalidate()
      }}
    />
  )
}

export const router = createRouter({
  routeTree,
  history: createTrailHistory(),
  context: { queryClient },
  // Предзагрузка по наведению выключена: `beforeLoad` маршрутов кабинета перепроверяет шаг мастера запросом,
  // и наведение на ссылку не должно его запускать. Экран может включить её у отдельной ссылки (`preload="intent"`).
  defaultPreload: false,
  // Скелетон появляется через 150 мс и держится не меньше 300 мс (E §2.0).
  defaultPendingMs: 400,
  defaultPendingMinMs: 300,
  defaultPendingComponent: () => <PageSkeleton />,
  defaultErrorComponent: RouteError,
  defaultNotFoundComponent: () => <NotFound />,
  scrollRestoration: true,
  scrollRestorationBehavior: 'instant',
  // Переход страниц анимируется только при смене пути: фильтры и версии подборки (search) не трогаем.
  defaultViewTransition: {
    types: ({ fromLocation, toLocation, pathChanged }) => {
      if (!pathChanged || !fromLocation) return false
      const from = depth(fromLocation.pathname)
      const to = depth(toLocation.pathname)
      return [to > from ? 'forward' : to < from ? 'back' : 'fade']
    },
  },
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}
