import { createFileRoute, notFound } from '@tanstack/react-router'
import { z } from 'zod'
import { DemoPage } from '@/features/demo'
import { isDemoEnabled } from '@/lib/features'

/** P7. Демо-доступ: аккаунты стенда, перезапуск сценария, блок ведущего. */
export const Route = createFileRoute('/_public/demo/')({
  validateSearch: (search) => z.object({ reason: z.string().optional().catch(undefined) }).parse(search),
  // Страница существует только при `features.demo`.
  beforeLoad: ({ context }) => {
    if (!isDemoEnabled(context.catalog)) throw notFound()
  },
  component: Screen,
})

function Screen() {
  const { me } = Route.useRouteContext()
  const { reason } = Route.useSearch()
  return <DemoPage me={me ?? null} expired={reason === 'restarted'} />
}
