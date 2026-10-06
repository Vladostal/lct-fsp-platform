import { createFileRoute, Outlet } from '@tanstack/react-router'
import { PublicLayout } from '@/components/app'
import { isDemoEnabled } from '@/lib/features'
import { roleRoot } from '@/lib/guards'

/** Каркас Public: лендинг, «Как это работает», демо-вход, витрина компонентов, документы. */
export const Route = createFileRoute('/_public')({
  component: PublicFrame,
})

function PublicFrame() {
  const { me, catalog } = Route.useRouteContext()
  return (
    <PublicLayout signedIn={Boolean(me)} homeHref={me ? roleRoot(me.role) : '/'} demo={isDemoEnabled(catalog)}>
      <Outlet />
    </PublicLayout>
  )
}
